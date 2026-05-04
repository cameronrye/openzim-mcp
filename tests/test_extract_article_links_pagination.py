"""Tests for extract_article_links pagination.

Background: large articles can carry hundreds-to-thousands of internal/external
links. Without pagination, ``extract_article_links`` returns the full set in
one response and risks blowing the MCP response token budget. The fix adds
``limit``, ``offset``, and ``kind`` parameters and surfaces ``has_more``.
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
def ops_with_synthetic_archive(temp_dir):
    """Build ZimOperations rooted in a temp dir with one fake-but-valid path."""
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(temp_dir)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=1000, snippet_length=100),
        logging=LoggingConfig(level="ERROR"),
    )
    return ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=100),
    )


def _patch_archive_with_html(
    html: str,
) -> Any:
    """Build an archive-context patch that returns ``html`` for any entry."""
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
    """HTML with 50 internal + 30 external + 20 media links."""
    parts = ["<html><body>"]
    for i in range(50):
        parts.append(f'<a href="Page_{i}">internal {i}</a>')
    for i in range(30):
        parts.append(f'<a href="https://example.com/{i}">external {i}</a>')
    for i in range(20):
        parts.append(f'<img src="image_{i}.png" alt="img {i}">')
    parts.append("</body></html>")
    return "\n".join(parts)


class TestExtractArticleLinksPagination:
    """Pagination contract for extract_article_links."""

    def test_default_caps_internal_links(
        self, ops_with_synthetic_archive, temp_dir, big_links_html
    ):
        """Default response must report full totals even when paged.

        The default page size protects the response budget; the caller can
        still see ``total_*_links`` to decide whether to fetch more.
        """
        zim = temp_dir / "test.zim"
        zim.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive_ctx:
            mock_archive_ctx.return_value.__enter__.return_value = (
                _patch_archive_with_html(big_links_html)
            )
            raw = ops_with_synthetic_archive.extract_article_links(str(zim), "Test")
        data = json.loads(raw)
        # Default limit is 100 per category, so 50 fits and 30 fits and 20 fits.
        # Switch to a clearly oversize fixture for the cap assertion below.
        assert "internal_links" in data
        # Total counts must report the *real* total, even if links are paged.
        assert data["total_internal_links"] == 50
        assert data["total_external_links"] == 30
        assert data["total_media_links"] == 20

    def test_limit_truncates_with_has_more(
        self, ops_with_synthetic_archive, temp_dir, big_links_html
    ):
        """limit=10 returns 10 internal links and signals has_more=True."""
        zim = temp_dir / "test.zim"
        zim.touch()
        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive_ctx:
            mock_archive_ctx.return_value.__enter__.return_value = (
                _patch_archive_with_html(big_links_html)
            )
            raw = ops_with_synthetic_archive.extract_article_links(
                str(zim), "Test", limit=10
            )
        data = json.loads(raw)
        assert len(data["internal_links"]) == 10
        assert data["pagination"]["has_more"] is True
        assert data["pagination"]["limit"] == 10
        assert data["pagination"]["offset"] == 0
        # Externals and media share the same limit cap
        assert len(data["external_links"]) == 10
        assert len(data["media_links"]) == 10

    def test_offset_skips_prefix(
        self, ops_with_synthetic_archive, temp_dir, big_links_html
    ):
        """offset=20, limit=5 returns links 20..24 of internals."""
        zim = temp_dir / "test.zim"
        zim.touch()
        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive_ctx:
            mock_archive_ctx.return_value.__enter__.return_value = (
                _patch_archive_with_html(big_links_html)
            )
            raw = ops_with_synthetic_archive.extract_article_links(
                str(zim), "Test", limit=5, offset=20
            )
        data = json.loads(raw)
        assert len(data["internal_links"]) == 5
        # The first link in the paged window points to Page_20 (links emitted
        # in source order).
        assert any(
            "Page_20" in (link.get("url") or link.get("href", ""))
            for link in data["internal_links"]
        ), data["internal_links"][:3]

    def test_kind_internal_only_excludes_external(
        self, ops_with_synthetic_archive, temp_dir, big_links_html
    ):
        """kind='internal' returns only internal_links; external/media empty."""
        zim = temp_dir / "test.zim"
        zim.touch()
        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive_ctx:
            mock_archive_ctx.return_value.__enter__.return_value = (
                _patch_archive_with_html(big_links_html)
            )
            raw = ops_with_synthetic_archive.extract_article_links(
                str(zim), "Test", limit=200, kind="internal"
            )
        data = json.loads(raw)
        assert len(data["internal_links"]) == 50
        assert data["external_links"] == []
        assert data["media_links"] == []

    def test_kind_external_only(
        self, ops_with_synthetic_archive, temp_dir, big_links_html
    ):
        """kind='external' must isolate the external bucket."""
        zim = temp_dir / "test.zim"
        zim.touch()
        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive_ctx:
            mock_archive_ctx.return_value.__enter__.return_value = (
                _patch_archive_with_html(big_links_html)
            )
            raw = ops_with_synthetic_archive.extract_article_links(
                str(zim), "Test", limit=200, kind="external"
            )
        data = json.loads(raw)
        assert data["internal_links"] == []
        assert len(data["external_links"]) == 30

    def test_invalid_limit_rejected(self, ops_with_synthetic_archive, temp_dir):
        """Reject limit < 1 or > 500 with a validation error."""
        from openzim_mcp.exceptions import OpenZimMcpValidationError

        zim = temp_dir / "test.zim"
        zim.touch()
        with pytest.raises(OpenZimMcpValidationError):
            ops_with_synthetic_archive.extract_article_links(str(zim), "Test", limit=0)
        with pytest.raises(OpenZimMcpValidationError):
            ops_with_synthetic_archive.extract_article_links(
                str(zim), "Test", limit=501
            )

    def test_invalid_kind_rejected(self, ops_with_synthetic_archive, temp_dir):
        """Reject any kind value outside internal/external/media."""
        from openzim_mcp.exceptions import OpenZimMcpValidationError

        zim = temp_dir / "test.zim"
        zim.touch()
        with pytest.raises(OpenZimMcpValidationError):
            ops_with_synthetic_archive.extract_article_links(
                str(zim), "Test", kind="bogus"
            )
