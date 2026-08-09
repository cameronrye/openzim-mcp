"""Strategy-1 suggestion classification must strip the query.

``_get_suggestions_from_search`` classified titles against the RAW
partial query while Strategy 2 (``_generate_search_suggestions``) and
the canonical probe use the stripped form. A trailing-whitespace query
like ``"Photosynthesis\\n"`` still matches in Xapian (it tokenizes), but
``title_lower.startswith("photosynthesis\\n")`` rejects every title, so
Strategy 1 silently returned nothing and the caller fell through to the
lower-quality fuzzy path.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.zim_stubs import make_entry
from tests.zim_stubs import make_ops as _ops


def _entry(eid: str) -> MagicMock:
    return make_entry(eid, with_item=False)


def test_strategy1_classification_strips_query_whitespace(tmp_path) -> None:
    ops = _ops(tmp_path)

    archive = MagicMock()
    archive.get_entry_by_path.side_effect = _entry

    search = MagicMock()
    search.getEstimatedMatches.return_value = 1
    search.getResults.return_value = ["C/Photosynthesis"]

    with patch("openzim_mcp.zim_operations.Searcher") as mock_searcher:
        mock_searcher.return_value.search.return_value = search
        out = ops._get_suggestions_from_search(archive, "Photosynthesis\n", limit=10)

    assert [s["text"] for s in out] == ["Photosynthesis"]
    assert out[0]["type"] == "search_start_match"
