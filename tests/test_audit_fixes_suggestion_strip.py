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

from pathlib import Path
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


def _entry(eid: str) -> MagicMock:
    e = MagicMock()
    e.path = eid
    e.title = eid.rsplit("/", 1)[-1]
    return e


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
