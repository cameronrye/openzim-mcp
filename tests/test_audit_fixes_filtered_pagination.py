"""Filtered-search pagination fixes.

Covers four interacting defects in the ``_scan_filtered_search`` /
``search_with_filters_data`` pipeline:

* ``done=True`` (and a truncated total) was reported whenever the page
  filled inside the final scan batch — the common case for any query
  whose unfiltered Xapian estimate fits in one 500-hit batch — because
  ``scanned`` was advanced to the batch end BEFORE the batch entries
  were examined.
* Query-string variant dedup consumed a ``filtered_count`` slot for the
  skipped variant, so the resume offset (emitted-row units) landed one
  row early per in-page duplicate and re-emitted rows on the next page.
* The namespace-only cheap-skip phase counted every candidate toward the
  offset, while the emit phase skipped entries that failed
  materialisation without counting them — the two phases used different
  units, shifting the resume window early.
* When the 10k scan cap fired and a page emitted nothing, the response
  carried ``done=False`` with a cursor that resumed at the SAME offset —
  a livelock for contract-following clients.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock, patch

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import CacheConfig, ContentConfig, OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations


def _ops(tmp_path: Path) -> ZimOperations:
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=10000, snippet_length=200),
    )
    return ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(snippet_length=200),
    )


def _entry_for(eid: str) -> MagicMock:
    e = MagicMock()
    e.path = eid
    e.title = eid.rsplit("/", 1)[-1]
    item = MagicMock()
    item.mimetype = "text/html"
    item.content = b"<p>body text</p>"
    e.get_item.return_value = item
    return e


def _search_stub(entry_ids: List[str], estimated: Optional[int] = None) -> MagicMock:
    search = MagicMock()
    search.getEstimatedMatches.return_value = (
        len(entry_ids) if estimated is None else estimated
    )
    search.getResults.side_effect = lambda start, count: entry_ids[
        start : start + count
    ]
    return search


def _archive_stub(get_entry=_entry_for) -> MagicMock:
    archive = MagicMock()
    archive.has_new_namespace_scheme = False
    archive.has_fulltext_index = True
    archive.get_entry_by_path.side_effect = get_entry
    return archive


def _filtered_data(ops, zim_file, archive, entry_ids, **kwargs):
    """Run ``search_with_filters_data`` against fully mocked libzim hooks."""
    with (
        patch("openzim_mcp.zim_operations.zim_archive") as mock_zim_archive,
        patch("openzim_mcp.zim_operations.Searcher") as mock_searcher,
    ):
        mock_zim_archive.return_value.__enter__.return_value = archive
        mock_searcher.return_value.search.return_value = _search_stub(entry_ids)
        return ops.search_with_filters_data(str(zim_file), "term", **kwargs)


# --------------------------------------------------------------------------
# Page fills inside the final batch -> total is a lower bound, not done
# --------------------------------------------------------------------------


def test_done_not_claimed_when_page_fills_inside_final_batch(tmp_path) -> None:
    """50 all-matching hits in one batch, limit=10: the scan stops at the
    10th hit with 40 candidates never examined, so the response must NOT
    claim ``done=True`` / a final total of 10."""
    ops = _ops(tmp_path)
    zim_file = tmp_path / "test.zim"
    zim_file.write_bytes(b"zim")

    entry_ids = [f"C/Article_{i}.htm" for i in range(50)]
    data = _filtered_data(
        ops, zim_file, _archive_stub(), entry_ids, namespace="C", limit=10, offset=0
    )

    assert len(data["results"]) == 10
    assert data["page_info"].get("total_is_lower_bound") is True
    assert data["done"] is False
    assert data["next_cursor"] is not None


# --------------------------------------------------------------------------
# Query-variant dedup must not consume a resume-offset slot
# --------------------------------------------------------------------------


def test_query_variant_dedup_does_not_skew_resume_offset(tmp_path) -> None:
    """A deduped ``?x=1`` variant inside page 1 must not shift page 2's
    window one row early (re-emitting the page-1 tail row)."""
    from openzim_mcp.pagination import Cursor

    ops = _ops(tmp_path)
    zim_file = tmp_path / "test.zim"
    zim_file.write_bytes(b"zim")

    entry_ids = [
        "C/A.htm",
        "C/A.htm?x=1",
        "C/B.htm",
        "C/C.htm",
        "C/D.htm",
        "C/E.htm",
    ]
    page1 = _filtered_data(
        ops, zim_file, _archive_stub(), entry_ids, namespace="C", limit=3, offset=0
    )
    paths1 = [r["path"] for r in page1["results"]]
    assert paths1 == ["C/A.htm", "C/B.htm", "C/C.htm"]
    assert page1["next_cursor"] is not None

    resume = Cursor.decode(page1["next_cursor"], expected_tool="search_with_filters")
    page2 = _filtered_data(
        ops,
        zim_file,
        _archive_stub(),
        entry_ids,
        namespace="C",
        limit=3,
        offset=int(resume["s"]["o"]),
    )
    paths2 = [r["path"] for r in page2["results"]]
    assert not set(paths1) & set(paths2), f"pages overlap: {paths1} / {paths2}"
    assert paths2 == ["C/D.htm", "C/E.htm"]
    assert page2["done"] is True


# --------------------------------------------------------------------------
# Materialisation failures must not desync the cheap-skip window
# --------------------------------------------------------------------------


def test_materialisation_failure_does_not_skew_resume_offset(tmp_path) -> None:
    """The namespace-only cheap-skip phase counts candidates it never
    materialises; a candidate that fails materialisation during the emit
    phase must count the same way, or the next page's skip window lands
    early and re-emits rows."""
    from openzim_mcp.pagination import Cursor

    ops = _ops(tmp_path)
    zim_file = tmp_path / "test.zim"
    zim_file.write_bytes(b"zim")

    entry_ids = ["A/E1", "A/E2", "A/E3", "A/E4", "A/E5"]

    def _get(eid: str) -> MagicMock:
        if eid == "A/E2":
            raise RuntimeError("corrupt entry")
        return _entry_for(eid)

    page1 = _filtered_data(
        ops,
        zim_file,
        _archive_stub(get_entry=_get),
        entry_ids,
        namespace="A",
        limit=2,
        offset=0,
    )
    paths1 = [r["path"] for r in page1["results"]]
    assert paths1 == ["A/E1", "A/E3"]
    assert page1["next_cursor"] is not None

    resume = Cursor.decode(page1["next_cursor"], expected_tool="search_with_filters")
    page2 = _filtered_data(
        ops,
        zim_file,
        _archive_stub(get_entry=_get),
        entry_ids,
        namespace="A",
        limit=2,
        offset=int(resume["s"]["o"]),
    )
    paths2 = [r["path"] for r in page2["results"]]
    assert not set(paths1) & set(paths2), f"pages overlap: {paths1} / {paths2}"
    assert paths2 == ["A/E4", "A/E5"]


# --------------------------------------------------------------------------
# Scan cap with no new rows must terminate the cursor chain
# --------------------------------------------------------------------------


def test_scan_cap_with_no_new_rows_terminates_pagination(tmp_path, monkeypatch) -> None:
    """When the scan cap fires and a page emits nothing, the cursor cannot
    advance — the response must report ``done=True`` instead of re-issuing
    the same offset forever."""
    from openzim_mcp.pagination import Cursor

    monkeypatch.setattr("openzim_mcp.zim.search._FILTERED_MAX_SCAN", 20)
    monkeypatch.setattr("openzim_mcp.zim.search._FILTERED_BATCH_SIZE", 10)

    ops = _ops(tmp_path)
    zim_file = tmp_path / "test.zim"
    zim_file.write_bytes(b"zim")

    # 5 namespace-M matches inside the (patched) scan window, then a long
    # tail of C-namespace hits stretching past the cap.
    entry_ids = [f"M/Key_{i}" for i in range(5)] + [f"C/Junk_{i}" for i in range(35)]

    page1 = _filtered_data(
        ops, zim_file, _archive_stub(), entry_ids, namespace="M", limit=10, offset=0
    )
    assert page1["page_info"]["returned_count"] == 5
    assert page1["done"] is False
    assert page1["next_cursor"] is not None

    resume = Cursor.decode(page1["next_cursor"], expected_tool="search_with_filters")
    page2 = _filtered_data(
        ops,
        zim_file,
        _archive_stub(),
        entry_ids,
        namespace="M",
        limit=10,
        offset=int(resume["s"]["o"]),
    )
    assert page2["results"] == []
    assert page2["done"] is True, (
        "a capped scan that emitted nothing must terminate the cursor "
        "chain, not re-issue the same offset"
    )
    assert page2["next_cursor"] is None
