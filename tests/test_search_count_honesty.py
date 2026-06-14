"""Real-world-test regression: search match counts must not present a
libzim ``getEstimatedMatches()`` estimate as if it were an exact count.

Two honest behaviours:

* When the result set is *exhausted* (``done=True``) the reported total
  must be the actual enumerated count, not a (possibly inflated) estimate —
  e.g. "Found 500 matches ... (end of results)" while only 3 rows exist.
* When more pages remain (``done=False``) and the estimate exceeds what was
  actually shown, the count must be marked approximate (``~N``) so callers
  don't trust a round ceiling (e.g. "20000") as exact.
"""

from __future__ import annotations

from typing import Any, Dict, List

from openzim_mcp.zim.search import _SearchMixin


def _fmt(payload: Dict[str, Any], **kw: Any) -> str:
    inst = object.__new__(_SearchMixin)
    return _SearchMixin._format_search_text(inst, payload, **kw)  # type: ignore[arg-type]


def _payload(
    total: int,
    results: List[Dict[str, str]],
    *,
    done: bool,
    offset: int = 0,
    limit: int = 10,
    query: str = "q",
) -> Dict[str, Any]:
    return {
        "query": query,
        "total": total,
        "done": done,
        "next_cursor": None,
        "results": results,
        "page_info": {"offset": offset, "limit": limit},
        "_meta": {},
    }


def _rows(*titles: str) -> List[Dict[str, str]]:
    return [{"path": t, "title": t, "snippet": "snip"} for t in titles]


def test_estimate_marked_approximate_when_more_pages_remain():
    out = _fmt(_payload(20000, _rows("A", "B"), done=False, limit=2))
    assert "~20000" in out
    assert "Found 20000 matches" not in out


def test_exhausted_set_reports_exact_count_not_estimate():
    out = _fmt(_payload(500, _rows("A", "B", "C"), done=True))
    assert "Found 3 matches" in out
    assert "500" not in out
    assert "Showing 1-3 of 3 (end of results)" in out


def test_small_exact_count_is_unchanged():
    out = _fmt(_payload(1, _rows("biology"), done=True, query="biology"))
    assert 'Found 1 matches for "biology", showing 1-1:' in out
    assert "~" not in out
    assert "Showing 1-1 of 1 (end of results)" in out
