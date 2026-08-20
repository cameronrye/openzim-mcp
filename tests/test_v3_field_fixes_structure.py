"""v3.0.0 field-defect fixes — ``structure`` workstream (links / sections / TOC).

One test class per defect from the 2026-08-19 real-world sweep, in packet
order. Each docstring names the defect id and the behaviour it pins.
"""

from __future__ import annotations

from pathlib import Path
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

ARCHIVE_CTX = "openzim_mcp.zim_operations.zim_archive"


@pytest.fixture
def ops(tmp_path: Path) -> ZimOperations:
    """ZimOperations rooted in a temp dir holding one fake ``.zim`` path."""
    (tmp_path / "test.zim").touch()
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=100_000, snippet_length=200),
        logging=LoggingConfig(level="ERROR"),
    )
    return ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache, enable_background_cleanup=False),
        ContentProcessor(snippet_length=200),
    )


@pytest.fixture
def zim_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.zim")


def _html_archive(
    html: str,
    *,
    title: str = "Test",
    entry_path: str = "Test",
    mime: str = "text/html",
) -> MagicMock:
    """Mock libzim archive serving ``html`` for any requested path."""
    item = MagicMock()
    item.content = html.encode("utf-8")
    item.mimetype = mime
    item.path = entry_path
    entry = MagicMock()
    entry.title = title
    entry.path = entry_path
    entry.is_redirect = False
    entry.get_item.return_value = item
    archive = MagicMock()
    archive.get_entry_by_path.return_value = entry
    archive.has_entry_by_path.return_value = True
    return archive


def _missing_entry_archive() -> MagicMock:
    """Mock archive whose every path lookup misses the way libzim does."""
    archive = MagicMock()
    archive.get_entry_by_path.side_effect = KeyError("Cannot find entry")
    archive.has_entry_by_path.return_value = False
    return archive


# ---------------------------------------------------------------------------
# D18 — zim_get_section on a nonexistent entry must return entry_not_found
# ---------------------------------------------------------------------------


class TestD18SectionMissingEntry:
    """D18: a missing entry_path is an ``entry_not_found`` envelope, not a
    raw ``KeyError`` that the wrapper renders as a transient server fault."""

    def test_missing_entry_returns_entry_not_found_payload(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _missing_entry_archive()
            result = ops.get_section_data(zim_path, "A/Nope", section_id="summary")

        assert result.get("error") is True
        assert result["operation"] == "entry_not_found"
        assert "A/Nope" in result["message"]
        assert "KeyError" not in result["message"]
        # The guidance must point at path correction, not retries.
        assert "spelling" in result["message"].lower()
