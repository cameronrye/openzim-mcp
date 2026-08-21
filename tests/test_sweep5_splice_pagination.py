"""The canonical-title splice must not consume a BM25 slot it never paged past.

``_splice_title_match_into_search`` prepended a synthetic canonical row and
then trimmed back to ``limit`` — dropping the last real BM25 hit of page 1 —
while leaving ``page_info["limit"]``, ``next_cursor`` and ``total`` untouched.
Both resume mechanisms therefore advanced by the full ``limit``:

* the renderer advertises ``offset + limit`` for the next page, and
* ``next_cursor`` encodes ``o = offset + <pre-splice returned_count>``.

So the displaced hit sat between what page 1 showed and where page 2 starts,
unreachable by any advertised offset. Against the shipped corpus,
``search for biomass fuel`` with ``limit=3`` showed ``A/Biofuel`` (spliced),
``A/Biomass_(energy)``, ``A/Biomass_briquettes`` and pointed at ``offset=3``,
while the third BM25 hit ``A/Aviation_biofuel`` appeared on neither page.

The filtered sibling ``search_with_filters_with_canonical_splice`` already
prepends without trimming and renders ``showing 1-4 … pass offset=3``; this
brings the unfiltered path onto the same contract.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

from openzim_mcp.simple_tools import SimpleToolsHandler


def _payload(paths: list, limit: int) -> Dict[str, Any]:
    return {
        "query": "biomass fuel",
        "results": [
            {"path": p, "title": p.split("/")[-1], "snippet": "..."} for p in paths
        ],
        "total": 70,
        "done": False,
        "next_cursor": "opaque",
        "page_info": {"offset": 0, "limit": limit, "returned_count": len(paths)},
        "_meta": {},
    }


def test_splice_keeps_every_bm25_hit_on_the_page(monkeypatch: Any) -> None:
    """The synthetic row is an extra, not a replacement for a real hit."""
    import openzim_mcp.simple_tools as st

    monkeypatch.setattr(
        st,
        "find_title_match",
        lambda *a, **k: {"path": "A/Biofuel", "title": "Biofuel"},
    )
    monkeypatch.setattr(st, "is_strong_canonical_title_match", lambda *a, **k: False)

    handler = SimpleToolsHandler(MagicMock())
    payload = _payload(
        ["A/Biomass_(energy)", "A/Biomass_briquettes", "A/Aviation_biofuel"], limit=3
    )
    out = handler._splice_title_match_into_search(payload, "/x.zim", "biomass fuel")
    paths = [r["path"] for r in out["results"]]

    assert paths[0] == "A/Biofuel", "canonical must lead"
    # The hit the trim used to discard.
    assert "A/Aviation_biofuel" in paths, (
        "trimming to `limit` dropped the last BM25 hit, which the next page's "
        "offset then skipped past — the row was unreachable"
    )
    assert paths == [
        "A/Biofuel",
        "A/Biomass_(energy)",
        "A/Biomass_briquettes",
        "A/Aviation_biofuel",
    ]


def test_splice_records_the_bm25_rows_it_consumed(monkeypatch: Any) -> None:
    """``source_consumed`` is what the resume point must advance by.

    ``returned_count`` now counts the synthetic row too, so it is no longer
    a safe proxy for "how far through the ranked stream this page went".
    """
    import openzim_mcp.simple_tools as st

    monkeypatch.setattr(
        st,
        "find_title_match",
        lambda *a, **k: {"path": "A/Biofuel", "title": "Biofuel"},
    )
    monkeypatch.setattr(st, "is_strong_canonical_title_match", lambda *a, **k: False)

    handler = SimpleToolsHandler(MagicMock())
    payload = _payload(
        ["A/Biomass_(energy)", "A/Biomass_briquettes", "A/Aviation_biofuel"], limit=3
    )
    out = handler._splice_title_match_into_search(payload, "/x.zim", "biomass fuel")
    page_info = out["page_info"]

    assert page_info["returned_count"] == 4
    assert page_info["source_consumed"] == 3
    # ``limit`` is untouched, so the renderer's ``offset + limit`` still
    # resumes at the first BM25 row this page did not show.
    assert page_info["limit"] == 3


def test_reorder_branch_is_unaffected(monkeypatch: Any) -> None:
    """When the canonical is already on the page, nothing is added or lost."""
    import openzim_mcp.simple_tools as st

    monkeypatch.setattr(
        st,
        "find_title_match",
        lambda *a, **k: {"path": "A/Biomass_briquettes", "title": "Biomass briquettes"},
    )
    monkeypatch.setattr(st, "is_strong_canonical_title_match", lambda *a, **k: False)

    handler = SimpleToolsHandler(MagicMock())
    payload = _payload(
        ["A/Biomass_(energy)", "A/Biomass_briquettes", "A/Aviation_biofuel"], limit=3
    )
    out = handler._splice_title_match_into_search(payload, "/x.zim", "biomass fuel")
    paths = [r["path"] for r in out["results"]]

    assert paths[0] == "A/Biomass_briquettes"
    assert len(paths) == 3
    assert sorted(paths) == sorted(
        ["A/Biomass_(energy)", "A/Biomass_briquettes", "A/Aviation_biofuel"]
    )
