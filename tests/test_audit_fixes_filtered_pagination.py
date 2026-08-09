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

import re
from typing import Optional
from unittest.mock import MagicMock, patch

from tests.zim_stubs import make_archive_stub as _archive_stub
from tests.zim_stubs import make_entry as _entry_for
from tests.zim_stubs import make_ops as _ops
from tests.zim_stubs import make_search_stub as _search_stub


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


# --------------------------------------------------------------------------
# Rendered offset hints must match the consumed-slot resume offset the
# JSON cursor encodes (markdown and compact siblings of the cursor fix)
# --------------------------------------------------------------------------


def _filtered_text(ops, zim_file, archive, entry_ids, **kwargs):
    """Run ``search_with_filters`` (markdown) against mocked libzim hooks."""
    with (
        patch("openzim_mcp.zim_operations.zim_archive") as mock_zim_archive,
        patch("openzim_mcp.zim_operations.Searcher") as mock_searcher,
    ):
        mock_zim_archive.return_value.__enter__.return_value = archive
        mock_searcher.return_value.search.return_value = _search_stub(entry_ids)
        return ops.search_with_filters(str(zim_file), "term", **kwargs)


def _offset_hint(text: str) -> Optional[int]:
    match = re.search(r"pass `offset=(\d+)`", text)
    return int(match.group(1)) if match else None


def _get_with_failure(failing: set):
    def _get(eid: str) -> MagicMock:
        if eid in failing:
            raise RuntimeError("corrupt entry")
        return _entry_for(eid)

    return _get


def test_markdown_offset_hint_matches_cursor_resume_offset(tmp_path) -> None:
    """When a candidate inside the emit window fails materialisation, the
    markdown footer's ``pass offset=N`` hint must advance in consumed-slot
    units (like the JSON cursor), not ``offset + limit`` — otherwise the
    advertised next page re-emits the page-1 tail."""
    from openzim_mcp.pagination import Cursor

    ops = _ops(tmp_path)
    zim_file = tmp_path / "test.zim"
    zim_file.write_bytes(b"zim")

    entry_ids = [f"A/p{i}.htm" for i in range(10)]
    get_entry = _get_with_failure({"A/p2.htm"})

    page1_text = _filtered_text(
        ops,
        zim_file,
        _archive_stub(get_entry=get_entry),
        entry_ids,
        namespace="A",
        limit=4,
        offset=0,
    )
    hint = _offset_hint(page1_text)
    assert hint is not None

    page1 = _filtered_data(
        ops,
        zim_file,
        _archive_stub(get_entry=get_entry),
        entry_ids,
        namespace="A",
        limit=4,
        offset=0,
    )
    resume = Cursor.decode(page1["next_cursor"], expected_tool="search_with_filters")
    assert hint == int(
        resume["s"]["o"]
    ), "markdown hint and JSON cursor must resume at the same slot"

    page2 = _filtered_data(
        ops,
        zim_file,
        _archive_stub(get_entry=get_entry),
        entry_ids,
        namespace="A",
        limit=4,
        offset=hint,
    )
    paths1 = [r["path"] for r in page1["results"]]
    paths2 = [r["path"] for r in page2["results"]]
    assert not set(paths1) & set(paths2), f"pages overlap: {paths1} / {paths2}"


def test_markdown_no_phantom_next_page_when_scan_exhausted(tmp_path) -> None:
    """An exhausted scan whose page underfilled (failures consumed slots)
    must render ``(end of results)`` — not advertise a next page that only
    re-serves rows already shown."""
    ops = _ops(tmp_path)
    zim_file = tmp_path / "test.zim"
    zim_file.write_bytes(b"zim")

    entry_ids = [f"A/q{i}.htm" for i in range(5)]
    get_entry = _get_with_failure({"A/q1.htm", "A/q2.htm"})

    page1_text = _filtered_text(
        ops,
        zim_file,
        _archive_stub(get_entry=get_entry),
        entry_ids,
        namespace="A",
        limit=4,
        offset=0,
    )
    page1 = _filtered_data(
        ops,
        zim_file,
        _archive_stub(get_entry=get_entry),
        entry_ids,
        namespace="A",
        limit=4,
        offset=0,
    )
    assert page1["done"] is True
    assert page1["next_cursor"] is None
    assert "(end of results)" in page1_text
    assert _offset_hint(page1_text) is None, (
        "markdown must not advertise a next page the JSON contract "
        "says does not exist"
    )


def test_compact_filtered_offset_hint_matches_cursor_resume_offset(tmp_path) -> None:
    """The compact renderer's footer must advance in consumed-slot units
    for filtered payloads (``total`` is the consumed-slot count), matching
    the payload's own ``next_cursor``."""
    from openzim_mcp.pagination import Cursor
    from openzim_mcp.zim.search import _format_filter_text

    ops = _ops(tmp_path)
    zim_file = tmp_path / "test.zim"
    zim_file.write_bytes(b"zim")

    entry_ids = [f"A/p{i}.htm" for i in range(10)]
    get_entry = _get_with_failure({"A/p2.htm"})

    page1 = _filtered_data(
        ops,
        zim_file,
        _archive_stub(get_entry=get_entry),
        entry_ids,
        namespace="A",
        limit=4,
        offset=0,
    )
    resume = Cursor.decode(page1["next_cursor"], expected_tool="search_with_filters")

    compact_text = ops._format_search_text(
        page1,
        display_query="term",
        filter_text=_format_filter_text("A", None) or "",
    )
    assert _offset_hint(compact_text) == int(
        resume["s"]["o"]
    ), "compact hint and JSON cursor must resume at the same slot"


def test_compact_filtered_lower_bound_total_rendered_with_plus(tmp_path) -> None:
    """When ``page_info.total_is_lower_bound`` is set, the compact renderer
    must mark the total as a lower bound (``N+``, matching the non-compact
    ``_format_filtered_response``) instead of presenting it as exact."""
    from openzim_mcp.zim.search import _format_filter_text

    ops = _ops(tmp_path)
    zim_file = tmp_path / "test.zim"
    zim_file.write_bytes(b"zim")

    entry_ids = [f"C/Article_{i}.htm" for i in range(50)]
    page1 = _filtered_data(
        ops, zim_file, _archive_stub(), entry_ids, namespace="C", limit=10, offset=0
    )
    assert page1["page_info"].get("total_is_lower_bound") is True

    compact_text = ops._format_search_text(
        page1,
        display_query="term",
        filter_text=_format_filter_text("C", None) or "",
    )
    assert 'Found 10+ filtered matches for "term"' in compact_text
    assert "of 10+" in compact_text


def test_canonical_splice_offset_hint_skips_no_slot() -> None:
    """The splice prepends a synthetic row that consumed no scan slot, so
    its inflated ``filtered_count`` must not become the next-page offset —
    resuming there would skip a real row the scan never emitted."""
    from tests.test_canonical_splice_characterization import _SpliceStub

    payload = {
        "query": "berlin",
        "namespace_filter": "C",
        "content_type_filter": None,
        "results": [
            {
                "path": f"C/Hit_{i}.htm",
                "title": f"Hit {i}",
                "snippet": "body text",
                "namespace": "C",
                "content_type": "text/html",
            }
            for i in range(3)
        ],
        "next_cursor": "opaque",
        "total": 5,
        "done": False,
        "page_info": {
            "offset": 0,
            "limit": 3,
            "returned_count": 3,
            "total_is_lower_bound": True,
        },
    }
    stub = _SpliceStub(
        data_payload=payload,
        title_results=[{"path": "C/Berlin", "title": "Berlin", "score": 1.0}],
    )

    text = stub.search_with_filters_with_canonical_splice(
        "/x.zim", "berlin", namespace="C", limit=3, offset=0
    )
    assert "Berlin" in text
    assert _offset_hint(text) == payload["total"], (
        "the spliced row must not shift the resume offset past a slot the "
        "scan consumed"
    )
