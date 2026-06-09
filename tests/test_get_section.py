"""Tests for openzim_mcp.zim.structure._StructureMixin.get_section_data."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

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
from tests.test_bundle import SAMPLE_HTML, TABLE_HTML, _make_archive_with_entry


@pytest.fixture
def ops(tmp_path: Path) -> ZimOperations:
    """Return ZimOperations backed by a temp directory with a fake .zim file."""
    zim = tmp_path / "test.zim"
    zim.touch()
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=True, max_size=50, ttl_seconds=300),
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
def patched_archive():
    """Context-manager patcher that returns a mock archive for SAMPLE_HTML."""
    return _make_archive_with_entry(SAMPLE_HTML, title="Berlin", entry_path="A/Berlin")


def test_get_section_returns_geography(ops, tmp_path, patched_archive) -> None:
    """Successful section fetch returns expected fields and body text."""
    zim_path = str(tmp_path / "test.zim")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = patched_archive
        response = ops.get_section_data(zim_path, "A/Berlin", section_id="geography")

    assert response["entry_path"] == "A/Berlin"
    assert response["title"] == "Berlin"
    assert response["section_id"] == "geography"
    assert response["section_title"] == "Geography"
    assert response["level"] == 2
    assert "Spree" in response["content_markdown"]
    assert response["truncated"] is False
    assert response["char_count"] == len(response["content_markdown"])
    assert response["word_count"] == len(response["content_markdown"].split())


def test_get_section_unknown_id_returns_tool_error(
    ops, tmp_path, patched_archive
) -> None:
    """An unrecognised section_id returns a ToolErrorPayload with available ids."""
    zim_path = str(tmp_path / "test.zim")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = patched_archive
        response = ops.get_section_data(
            zim_path, "A/Berlin", section_id="this-does-not-exist"
        )

    assert response.get("error") is True, f"Expected ToolErrorPayload, got: {response}"
    assert "available_section_ids" in response
    assert "geography" in response["available_section_ids"]


def test_get_section_max_chars_truncates(ops, tmp_path, patched_archive) -> None:
    """max_chars truncates content_markdown and sets truncated=True in the meta envelope."""
    zim_path = str(tmp_path / "test.zim")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = patched_archive
        response = ops.get_section_data(
            zim_path, "A/Berlin", section_id="geography", max_chars=20
        )

    assert response["truncated"] is True
    assert len(response["content_markdown"]) <= 20
    assert response["_meta"]["truncated"] is True


def test_get_section_meta_envelope_present(ops, tmp_path, patched_archive) -> None:
    """Response includes a _meta envelope with tokens_est."""
    zim_path = str(tmp_path / "test.zim")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = patched_archive
        response = ops.get_section_data(zim_path, "A/Berlin", section_id="geography")

    assert "_meta" in response
    assert "tokens_est" in response["_meta"]


def test_get_section_compact_mode_controls_table_rendering(ops, tmp_path) -> None:
    """compact=True collapses oversized tables; compact=False keeps full rows."""
    archive = _make_archive_with_entry(TABLE_HTML, title="Data", entry_path="A/Data")
    zim_path = str(tmp_path / "test.zim")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        compact = ops.get_section_data(
            zim_path, "A/Data", section_id="stats", compact=True
        )
        raw = ops.get_section_data(
            zim_path, "A/Data", section_id="stats", compact=False
        )
    assert "[Table" in compact["content_markdown"]
    assert "alpha" not in compact["content_markdown"]
    assert "alpha" in raw["content_markdown"]
    assert "[Table" not in raw["content_markdown"]
