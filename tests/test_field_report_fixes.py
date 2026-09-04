"""Regression tests for defects found by the v3.3.1 real-world field report.

Each test drives the REAL entry point end to end and asserts on the RENDERED
output, not on a renderer called with an explicit keyword. That distinction
matters here: several past rounds in this repo shipped gates that proved a
renderer behaves *when told* something and proved nothing about it ever being
told. Where a flag has a safe default, the test therefore exercises both the
flag-set and flag-clear cases so it cannot pass by emitting the signal
unconditionally.
"""

from functools import partial
from typing import Any, Dict, List, Optional
from unittest.mock import Mock

import pytest

from openzim_mcp.simple_tools import SimpleToolsHandler
from openzim_mcp.zim.search import _SearchMixin


def _search_payload(
    *,
    reason: Optional[str],
    results: List[Dict[str, Any]],
    suggestions: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Build a ``search_zim_file_data`` payload with a chosen ``_meta.reason``.

    Mirrors the wire shape ``openzim_mcp/zim/search.py`` produces: ``reason``
    lives under ``_meta`` alongside the suggestion pool, and ``results`` carries
    the ranked hits.
    """
    meta: Dict[str, Any] = {}
    if reason is not None:
        meta["reason"] = reason
    if suggestions is not None:
        meta["suggestions"] = suggestions
    return {
        "query": "metformin dosage",
        "results": results,
        "total": len(results),
        "done": True,
        "next_cursor": None,
        "page_info": {"offset": 0, "limit": 10, "returned_count": len(results)},
        "_meta": meta,
    }


# Nine supplement monographs — the real MedlinePlus response to
# "metformin dosage", none of which token-match the query. This is the
# observed shape the field report captured, not an invented one.
_WEAK_HITS: List[Dict[str, Any]] = [
    {
        "path": "medlineplus.gov/druginfo/natural/97.html",
        "title": "Black Psyllium: MedlinePlus Supplements",
        "snippet": "Black psyllium is a herb.",
    },
    {
        "path": "medlineplus.gov/druginfo/natural/866.html",
        "title": "Blond Psyllium: MedlinePlus Supplements",
        "snippet": "Blond psyllium is a herb.",
    },
    {
        "path": "medlineplus.gov/druginfo/natural/78.html",
        "title": "Bee Pollen: MedlinePlus Supplements",
        "snippet": "Bee pollen is a food.",
    },
]

_STRONG_HITS: List[Dict[str, Any]] = [
    {
        "path": "medlineplus.gov/druginfo/meds/a696005.html",
        "title": "Metformin: MedlinePlus Drug Information",
        "snippet": "Metformin is used to treat type 2 diabetes.",
    },
]


class TestLowRelevanceReachesTheNaturalLanguageSurface:
    """``low_relevance`` must survive the trip to ``zim_query``'s output.

    The backend computes the verdict (``zim/search.py``), the footer branch
    that renders it already exists (``meta.py``), and ``_handle_search``
    dropped it on the floor for every non-empty result set — so simple mode,
    where ``zim_query`` is the only tool, presented nine irrelevant supplement
    monographs as a confident complete answer.
    """

    @pytest.fixture
    def ops(self) -> Mock:
        """A stubbed backend that still renders through the REAL formatter.

        Only the data-fetch call is faked. ``_format_search_text`` is bound to
        the genuine implementation so the assertions below run against the
        markdown a real client receives, not against a Mock's repr.
        """
        mock = Mock()
        mock.list_zim_files.return_value = (
            '[{"path": "/test/file.zim", "name": "file.zim"}]'
        )
        mock._format_search_text = partial(_SearchMixin._format_search_text, mock)
        return mock

    def _run(self, ops: Mock, payload: Dict[str, Any]) -> str:
        """Drive the real ``handle_zim_query`` with a stubbed backend."""
        ops.search_zim_file_data.return_value = payload
        handler = SimpleToolsHandler(ops)
        # ``compact=True`` is the shape ``zim_query`` actually runs in — it is
        # the default the MCP tool passes, and the only branch that consults
        # the structured payload's ``_meta``.
        result = handler.handle_zim_query(
            "search for metformin dosage",
            "/test/file.zim",
            {"compact": True},
        )
        assert isinstance(result, str), result
        return result

    def test_weak_hits_are_flagged_in_the_rendered_output(self, ops: Mock) -> None:
        """A low-relevance result set must not read as a confident answer."""
        rendered = self._run(
            ops, _search_payload(reason="low_relevance", results=_WEAK_HITS)
        )
        # Positive: the caller is told the hits are weak. Paired with the
        # negative below so "renders nothing at all" cannot satisfy this.
        assert "weak" in rendered.lower() or "low relevance" in rendered.lower(), (
            "rendered output carries no low-relevance signal:\n" + rendered
        )
        # The hits themselves are still returned — this is a caveat, not a
        # suppression.
        assert "Black Psyllium" in rendered

    def test_strong_hits_are_not_flagged(self, ops: Mock) -> None:
        """The signal must be conditional, or the previous test is vacuous."""
        rendered = self._run(ops, _search_payload(reason=None, results=_STRONG_HITS))
        assert "low relevance" not in rendered.lower()
        assert "Metformin" in rendered

    def test_backend_suggestions_survive_alongside_the_flag(self, ops: Mock) -> None:
        """A low-relevance response keeps the recovery pool it was given."""
        rendered = self._run(
            ops,
            _search_payload(
                reason="low_relevance",
                results=_WEAK_HITS,
                suggestions=[{"type": "alt_spelling", "value": "glucophage"}],
            ),
        )
        # ``glucophage`` appears nowhere but the suggestion pool, so this
        # cannot be satisfied by the query echo the way "metformin" would be.
        assert "suggestions for glucophage" in rendered, rendered
