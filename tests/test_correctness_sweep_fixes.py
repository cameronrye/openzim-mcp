"""Correctness-sweep regression tests.

Each test class pins one defect found in the 2026-08 full-codebase sweep;
the docstrings name the failure the fix closes.
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
    e.is_redirect = False
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


# --------------------------------------------------------------------------
# _perform_search: Xapian estimate exceeding the real hit count must not
# produce a stuck cursor (empty page + done=False + same offset forever).
# --------------------------------------------------------------------------


class TestSearchCursorTerminatesOnEstimateOvershoot:
    def _perform(self, tmp_path, entry_ids, estimated, limit, offset):
        ops = _ops(tmp_path)
        zim_file = tmp_path / "test.zim"
        zim_file.write_bytes(b"zim")
        archive = _archive_stub()
        with patch("openzim_mcp.zim_operations.Searcher") as mock_searcher:
            mock_searcher.return_value.search.return_value = _search_stub(
                entry_ids, estimated=estimated
            )
            payload, _total = ops._perform_search(
                archive, "q", limit, offset, validated_path=zim_file
            )
        return payload

    def test_empty_page_past_real_hits_is_done(self, tmp_path) -> None:
        """Estimate 250, 180 real hits: the page at offset=180 is empty and
        must terminate pagination instead of re-minting the same cursor."""
        entry_ids = [f"C/A_{i}" for i in range(180)]
        payload = self._perform(tmp_path, entry_ids, 250, limit=10, offset=180)
        assert payload["results"] == []
        assert payload["done"] is True
        assert payload["next_cursor"] is None

    def test_short_page_at_exhaustion_is_done(self, tmp_path) -> None:
        """A page that comes back shorter than requested means the real
        result stream is exhausted — done must be True."""
        entry_ids = [f"C/A_{i}" for i in range(180)]
        payload = self._perform(tmp_path, entry_ids, 250, limit=20, offset=170)
        assert len(payload["results"]) == 10
        assert payload["done"] is True
        assert payload["next_cursor"] is None

    def test_full_page_mid_stream_still_pages(self, tmp_path) -> None:
        entry_ids = [f"C/A_{i}" for i in range(180)]
        payload = self._perform(tmp_path, entry_ids, 250, limit=10, offset=0)
        assert len(payload["results"]) == 10
        assert payload["done"] is False
        assert payload["next_cursor"] is not None
