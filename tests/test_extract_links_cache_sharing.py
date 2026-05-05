"""Cache regression test for extract_article_links pagination.

The pagination fix accidentally cached per-(limit, offset, kind) combo,
so requesting offset=0 then offset=10 re-parsed the same HTML twice.
Cache the parsed link lists once under a stable key and slice from
cache for subsequent pages.
"""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations


@pytest.fixture
def ops_with_cache(temp_dir):
    """Build ZimOperations with a real cache (the regression is cache-shaped)."""
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(temp_dir)],
        cache=CacheConfig(enabled=True, max_size=50, ttl_seconds=600),
        content=ContentConfig(max_content_length=1000, snippet_length=100),
        logging=LoggingConfig(level="ERROR"),
    )
    return ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=100),
    )


def _patch_archive_with_html(html: str) -> Any:
    mock_entry = MagicMock()
    mock_entry.title = "Test"
    mock_entry.path = "Test"
    mock_entry.is_redirect = False
    mock_item = MagicMock()
    mock_item.mimetype = "text/html"
    mock_item.content = html.encode("utf-8")
    mock_entry.get_item.return_value = mock_item

    mock_archive = MagicMock()
    mock_archive.has_new_namespace_scheme = True
    mock_archive.get_entry_by_path.return_value = mock_entry
    mock_archive.has_entry_by_path.return_value = True
    return mock_archive


@pytest.fixture
def big_links_html() -> str:
    """Synthetic HTML with 50 internal links, big enough to page through."""
    parts = ["<html><body>"]
    for i in range(50):
        parts.append(f'<a href="Page_{i}">internal {i}</a>')
    parts.append("</body></html>")
    return "\n".join(parts)


def test_paged_requests_share_one_html_parse(ops_with_cache, temp_dir, big_links_html):
    """Paging through extract_article_links must reuse the parsed list.

    Two consecutive calls with different (limit, offset) on the same
    archive+entry must trigger only ONE call to ContentProcessor's
    HTML link extractor, not one per page.
    """
    zim = temp_dir / "test.zim"
    zim.touch()

    parse_calls = 0
    real_extract = ops_with_cache.content_processor.extract_html_links

    def counting_extract(html: str):
        nonlocal parse_calls
        parse_calls += 1
        return real_extract(html)

    with (
        patch("openzim_mcp.zim_operations.zim_archive") as mock_archive_ctx,
        patch.object(
            ops_with_cache.content_processor,
            "extract_html_links",
            side_effect=counting_extract,
        ),
    ):
        mock_archive_ctx.return_value.__enter__.return_value = _patch_archive_with_html(
            big_links_html
        )
        first = json.loads(
            ops_with_cache.extract_article_links(str(zim), "Test", limit=10, offset=0)
        )
        second = json.loads(
            ops_with_cache.extract_article_links(str(zim), "Test", limit=10, offset=10)
        )

    # Both pages came from the same parse → only one call.
    assert parse_calls == 1, (
        f"expected 1 HTML parse, got {parse_calls} — pagination is "
        f"re-parsing instead of slicing from cache"
    )
    # And the page contents are correct.
    assert len(first["internal_links"]) == 10
    assert len(second["internal_links"]) == 10
    # Pages are distinct slices.
    first_urls = {
        link.get("url") or link.get("href") for link in first["internal_links"]
    }
    second_urls = {
        link.get("url") or link.get("href") for link in second["internal_links"]
    }
    assert first_urls.isdisjoint(second_urls), (first_urls, second_urls)
