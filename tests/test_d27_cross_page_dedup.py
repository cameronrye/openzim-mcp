"""D27 follow-up: canonical dedup must survive a page boundary.

PR #374 collapsed warc2zim query-string variants (``foo.htm`` and
``foo.htm?quiz=1``) *within* a page, and taught the renderer to advertise
``offset + page_info.source_consumed`` so a client resumes where the page
really stopped. Both are page-scoped, so a duplicate pair that straddles the
boundary still leaks: the last row of page N and the first row of page N+1
are the same article, and page N+1 starts with an empty ``seen`` set.

Measured on ``medlineplus.gov_en_all_2025-01.zim`` with a client following
the documented resume rule to the letter — ``offset += source_consumed``:

    q='quiz'     limit=2  -> 11 cross-page duplicates
    q='quiz'     limit=10 ->  7 (first at offset=18)
    q='diabetes' limit=13 ->  1 (at offset=80)

The fix is a bounded lookbehind: before filling a page at ``offset > 0``,
seed the seen-set from the ``_CANONICAL_LOOKBEHIND`` ranked rows immediately
before it. Duplicates are provably local — across 4251 ranked rows of five
queries on that archive the gap between two rows sharing a canonical was
never more than 2 (78 pairs at gap 1, 7 at gap 2) — so a small window makes
the rule "emit a row unless an earlier row within K carries the same
canonical", which is page-boundary independent.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.zim.search import _CANONICAL_LOOKBEHIND, canonical_result_path
from tests.zim_stubs import make_archive_stub, make_ops, make_search_stub

MEDLINEPLUS = Path("/Users/cameron/Developer/zim/medlineplus.gov_en_all_2025-01.zim")


def _perform(ops, zim_file, entry_ids, limit, offset, estimated=None):
    with patch("openzim_mcp.zim_operations.Searcher") as searcher:
        searcher.return_value.search.return_value = make_search_stub(
            entry_ids, estimated=estimated
        )
        return ops._perform_search(
            make_archive_stub(), "quiz", limit, offset, validated_path=zim_file
        )


def _walk(ops, zim_file, entry_ids, limit, estimated=None):
    """Page the stub stream exactly as the documented contract tells a
    client to: ``offset += source_consumed`` (else ``returned_count``)."""
    pages: List[List[str]] = []
    offset = 0
    for _ in range(20):
        payload, _total = _perform(
            ops, zim_file, entry_ids, limit, offset, estimated=estimated
        )
        rows = [r["path"] for r in payload["results"]]
        if rows:
            pages.append(rows)
        info = payload["page_info"]
        step = info.get("source_consumed", info.get("returned_count"))
        if payload["done"] or not step:
            break
        offset += step
    return pages


@pytest.fixture()
def ops_and_file(tmp_path):
    ops = make_ops(tmp_path)
    zim_file = tmp_path / "test.zim"
    zim_file.write_bytes(b"zim")
    return ops, zim_file


class TestCrossPageCanonicalDedup:
    def test_variant_does_not_leak_across_the_page_boundary(self, ops_and_file) -> None:
        """The duplicate pair straddles the boundary at limit=2.

        Before the lookbehind, page 2 opened with ``C/b.htm?x=1`` — the
        variant of the ``C/b.htm`` page 1 had just shown.
        """
        ops, zim_file = ops_and_file
        stream = ["C/a.htm", "C/b.htm", "C/b.htm?x=1", "C/c.htm", "C/d.htm"]

        page1, _ = _perform(ops, zim_file, stream, 2, 0)
        assert [r["path"] for r in page1["results"]] == ["C/a.htm", "C/b.htm"]
        resume = page1["page_info"].get(
            "source_consumed", page1["page_info"]["returned_count"]
        )
        assert resume == 2

        page2, _ = _perform(ops, zim_file, stream, 2, resume)
        assert [r["path"] for r in page2["results"]] == ["C/c.htm", "C/d.htm"]

        canon1 = {canonical_result_path(r["path"]) for r in page1["results"]}
        canon2 = {canonical_result_path(r["path"]) for r in page2["results"]}
        assert canon1 & canon2 == set()

    def test_no_canonical_repeats_across_a_full_contract_walk(
        self, ops_and_file
    ) -> None:
        """Every duplicate geometry seen on the real index, at every page
        size that could split it: gap-1 and gap-2 pairs, each landing on a
        boundary for at least one of these limits."""
        ops, zim_file = ops_and_file
        stream = [
            "C/a.htm",
            "C/b.htm",
            "C/b.htm?x=1",
            "C/c.htm",
            "C/d.htm",
            "C/d.htm?x=1",
            "C/e.htm",
            "C/f.htm",
            "C/e.htm?x=1",  # gap 2
            "C/g.htm",
            "C/h.htm",
            "C/h.htm?x=1",
        ]
        distinct = {canonical_result_path(p) for p in stream}
        for limit in (1, 2, 3, 4, 5, 6):
            pages = _walk(ops, zim_file, stream, limit)
            emitted = [p for page in pages for p in page]
            canon = [canonical_result_path(p) for p in emitted]
            assert len(canon) == len(
                set(canon)
            ), f"limit={limit}: canonical repeated across pages {pages}"
            assert set(canon) == distinct, f"limit={limit}: rows lost {pages}"

    def test_lookbehind_seed_never_marks_the_stream_exhausted(
        self, ops_and_file
    ) -> None:
        """The seeding fetch is short by construction — it must not feed
        the ``len(batch) < want -> exhausted`` heuristic that terminates
        pagination, or a mid-stream page would claim to be the last."""
        ops, zim_file = ops_and_file
        entry_ids = [f"C/A_{i}" for i in range(180)]

        # Estimate overshoot at the true end of the stream: still done.
        payload, _ = _perform(ops, zim_file, entry_ids, 20, 170, estimated=250)
        assert len(payload["results"]) == 10
        assert payload["done"] is True
        assert payload["next_cursor"] is None

        # Mid-stream, with a full lookbehind window available: not done.
        payload, _ = _perform(ops, zim_file, entry_ids, 10, 100, estimated=250)
        assert len(payload["results"]) == 10
        assert payload["done"] is False
        assert payload["next_cursor"] is not None

    def test_lookbehind_window_clamps_at_the_start_of_the_stream(
        self, ops_and_file
    ) -> None:
        """``offset - K`` is negative for every offset below K.

        ``getResults`` is a slice in the stubs and a C++ call in libzim; a
        negative start silently reads the tail of the stream in the former
        and is undefined in the latter, so the window must be clamped to 0.
        """
        assert _CANONICAL_LOOKBEHIND > 1
        ops, zim_file = ops_and_file
        # The stream's tail duplicates its head: an unclamped window would
        # slice the tail in and suppress the very rows this page must show.
        stream = ["C/a.htm", "C/b.htm", "C/c.htm", "C/d.htm", "C/a.htm?x=1"]

        payload, _ = _perform(ops, zim_file, stream, 2, 1)
        assert [r["path"] for r in payload["results"]] == ["C/b.htm", "C/c.htm"]

    def test_clean_page_is_byte_identical(self, ops_and_file) -> None:
        """No variants anywhere: no ``source_consumed`` key, same rows.

        The lookbehind must be invisible on the overwhelming majority of
        archives, which carry no query-string variants at all.
        """
        ops, zim_file = ops_and_file
        stream = [f"C/{c}.htm" for c in "abcdefghij"]

        payload, _ = _perform(ops, zim_file, stream, 3, 3)
        assert [r["path"] for r in payload["results"]] == [
            "C/d.htm",
            "C/e.htm",
            "C/f.htm",
        ]
        assert "source_consumed" not in payload["page_info"]

    def test_lookbehind_costs_one_extra_getresults_and_only_when_paging(
        self, ops_and_file
    ) -> None:
        """Cost pin: zero extra reads on page 1, exactly one after it, and
        it never materialises an entry (it reads path strings only)."""
        ops, zim_file = ops_and_file
        stream = [f"C/{i}.htm" for i in range(40)]

        for offset, extra in ((0, 0), (12, 1)):
            stub = make_search_stub(stream)
            with patch("openzim_mcp.zim_operations.Searcher") as searcher:
                searcher.return_value.search.return_value = stub
                ops._perform_search(
                    make_archive_stub(), "quiz", 5, offset, validated_path=zim_file
                )
            assert stub.getResults.call_count == 1 + extra
            if extra:
                start, count = stub.getResults.call_args_list[0].args
                assert (start, count) == (
                    offset - _CANONICAL_LOOKBEHIND,
                    _CANONICAL_LOOKBEHIND,
                )


class TestSpliceKeepsBackendConsumedCount:
    """D27c — the canonical splice clobbered ``source_consumed``."""

    @staticmethod
    def _handler(monkeypatch: Any):
        import openzim_mcp.simple_tools as st

        monkeypatch.setattr(
            st,
            "find_title_match",
            lambda *a, **k: {"path": "A/Biofuel", "title": "Biofuel"},
        )
        monkeypatch.setattr(
            st, "is_strong_canonical_title_match", lambda *a, **k: False
        )
        return st.SimpleToolsHandler(MagicMock())

    @staticmethod
    def _payload(paths: List[str], limit: int, **page_info: Any) -> Dict[str, Any]:
        return {
            "query": "biomass fuel",
            "results": [
                {"path": p, "title": p.split("/")[-1], "snippet": "..."} for p in paths
            ],
            "total": 70,
            "done": False,
            "next_cursor": "opaque",
            "page_info": {
                "offset": 0,
                "limit": limit,
                "returned_count": len(paths),
                **page_info,
            },
            "_meta": {},
        }

    def test_splice_keeps_the_backends_larger_consumed_count(
        self, monkeypatch: Any
    ) -> None:
        """The backend deduped two variants inside the window, so it walked
        5 ranked rows to emit 3. Overwriting that with the emitted-row count
        rewinds the resume point into rows this page already showed.
        """
        handler = self._handler(monkeypatch)
        payload = self._payload(
            ["A/Biomass_(energy)", "A/Biomass_briquettes", "A/Aviation_biofuel"],
            limit=3,
            source_consumed=5,
        )
        out = handler._splice_title_match_into_search(payload, "/x.zim", "biomass fuel")

        assert out["page_info"]["source_consumed"] == 5
        assert out["page_info"]["returned_count"] == 4

    def test_splice_still_records_consumed_when_the_backend_did_not(
        self, monkeypatch: Any
    ) -> None:
        """No incoming key (the clean-page case): the splice must still say
        how many ranked rows the page went through, or ``returned_count``
        — inflated by the synthetic row — becomes the resume point."""
        handler = self._handler(monkeypatch)
        payload = self._payload(
            ["A/Biomass_(energy)", "A/Biomass_briquettes", "A/Aviation_biofuel"],
            limit=3,
        )
        out = handler._splice_title_match_into_search(payload, "/x.zim", "biomass fuel")

        assert out["page_info"]["source_consumed"] == 3

    @pytest.mark.parametrize("bogus", [None, True, "5", -1])
    def test_splice_ignores_a_non_count_consumed_value(
        self, monkeypatch: Any, bogus: Any
    ) -> None:
        """``max()`` must not be fed a bool, a string or a negative — the
        emitted-row count is the floor in every one of those cases."""
        handler = self._handler(monkeypatch)
        payload = self._payload(
            ["A/Biomass_(energy)", "A/Biomass_briquettes", "A/Aviation_biofuel"],
            limit=3,
            source_consumed=bogus,
        )
        out = handler._splice_title_match_into_search(payload, "/x.zim", "biomass fuel")

        assert out["page_info"]["source_consumed"] == 3


# ---------------------------------------------------------------------------
# Corpus-backed pin. The shipped fixtures are wikipedia/wikibooks exports and
# carry no query-string variants at all, which is exactly why the cross-page
# case escaped PR #374's stub-based pin. This needs a warc2zim-shaped archive,
# so it is `live`-marked (the default ``addopts`` carries ``-m 'not live'``)
# and skips when the archive is absent.
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.skipif(
    not MEDLINEPLUS.exists(), reason="warc2zim-shaped archive not present"
)
@pytest.mark.parametrize(
    ("query", "limit"), [("quiz", 2), ("quiz", 10), ("diabetes", 13)]
)
def test_real_archive_contract_walk_emits_each_page_once(
    query: str, limit: int
) -> None:
    """Walk the real ranked stream by the documented resume rule and assert
    no canonical is emitted on two different pages."""
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import CacheConfig, ContentConfig, OpenZimMcpConfig
    from openzim_mcp.content_processor import ContentProcessor
    from openzim_mcp.security import PathValidator
    from openzim_mcp.zim_operations import ZimOperations

    config = OpenZimMcpConfig(
        allowed_directories=[str(MEDLINEPLUS.parent)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=10000, snippet_length=200),
    )
    ops = ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(snippet_length=200),
    )

    seen: Dict[str, int] = {}
    leaks: List[Any] = []
    offset = 0
    for page_no in range(12):
        payload = ops.search_zim_file_data(
            str(MEDLINEPLUS), query, limit=limit, offset=offset
        )
        rows = payload["results"]
        if not rows:
            break
        for row in rows:
            canonical = canonical_result_path(row["path"])
            if seen.get(canonical, page_no) != page_no:
                leaks.append((offset, row["path"]))
            seen[canonical] = page_no
        info = payload["page_info"]
        step = info.get("source_consumed", info.get("returned_count"))
        if payload.get("done") or not step:
            break
        offset += step

    assert leaks == [], f"cross-page duplicates for {query!r} at limit={limit}"
