"""Tests for the walk_namespace header when the scan skipped filtered entries.

For the generic C-namespace walk, ``page_info.offset`` is ``scan_at`` — a
resume position in raw entry-id space — while ``returned_count`` counts only
filter-surviving matches. When assets are filtered out (the default on
new-scheme archives), ``scanned_count > returned_count`` and the legacy
``entries {offset+1}-{offset+returned}`` header is incoherent in both id
space and ordinal space.
"""

from openzim_mcp import compact_renderers


def _walk_payload(**overrides):
    payload = {
        "namespace": "C",
        "results": [{"title": "T", "path": "C/T"}],
        "next_cursor": "cursor-token",
        "total": None,
        "done": False,
        "page_info": {"offset": 0, "limit": 200, "returned_count": 1},
        "scanned_count": 1,
        "scanned_through_id": 0,
        "archive_entry_count": 1234,
    }
    payload.update(overrides)
    return payload


def test_filtered_scan_header_does_not_claim_ordinal_entry_range():
    """Page 2 of a filtered C walk: 200 matches found while scanning ids
    500-749. The old header read ``entries 501-700`` — neither the id
    range scanned (501-750) nor the ordinal match range (201-400).
    """
    out = compact_renderers.render_walk_namespace(
        _walk_payload(
            results=[{"title": f"T{i}", "path": f"C/T{i}"} for i in range(200)],
            page_info={"offset": 500, "limit": 200, "returned_count": 200},
            scanned_count=250,
            scanned_through_id=749,
            namespace_entry_count=100_000,
        )
    )
    assert "501-700" not in out
    assert "200 entries" in out
    assert "501-750" in out


def test_unfiltered_scan_header_keeps_entry_range():
    """When every scanned entry matched (M/W walks, or a C page with no
    filtered assets), the plain ``entries X-Y`` range stays coherent and
    is kept.
    """
    out = compact_renderers.render_walk_namespace(
        _walk_payload(
            namespace="M",
            results=[{"title": f"K{i}", "path": f"M/K{i}"} for i in range(50)],
            page_info={"offset": 100, "limit": 50, "returned_count": 50},
            scanned_count=50,
            scanned_through_id=149,
            namespace_entry_count=200,
        )
    )
    assert "entries 101-150" in out
