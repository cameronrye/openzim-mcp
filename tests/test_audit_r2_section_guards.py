"""Guards on the ``zim_get_section`` data layer.

Two defects on ``get_section_data``:

* the ``section_not_found`` recovery hint pointed at
  ``get_table_of_contents``, a name that is not a registered tool on the
  Phase F surface — a client following it issues a call that fails;
* ``max_chars`` was applied as a bare Python slice, so a non-positive cap
  trimmed the section TAIL (``max_chars=-5`` returned every character but
  the last five, flagged ``truncated``) instead of being rejected the way
  every sibling surface rejects a non-positive cap.
"""

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
from tests.test_bundle import SAMPLE_HTML, _make_archive_with_entry


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


def _get_section(ops, tmp_path, archive, **kwargs):
    zim_path = str(tmp_path / "test.zim")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        return ops.get_section_data(zim_path, "A/Berlin", **kwargs)


def test_section_not_found_hint_names_a_registered_tool(
    ops, tmp_path, patched_archive
) -> None:
    """The recovery hint must name a tool the client can actually call."""
    response = _get_section(
        ops, tmp_path, patched_archive, section_id="this-does-not-exist"
    )

    assert response.get("error") is True
    message = response["message"]
    assert "get_table_of_contents" not in message, (
        "get_table_of_contents is not a registered Phase F tool; following "
        "the hint fails"
    )
    assert "zim_get" in message and "toc" in message


@pytest.mark.parametrize("max_chars", [0, -1, -5])
def test_non_positive_max_chars_rejected(
    ops, tmp_path, patched_archive, max_chars: int
) -> None:
    """A non-positive cap is an error, not a tail trim."""
    response = _get_section(
        ops, tmp_path, patched_archive, section_id="geography", max_chars=max_chars
    )

    assert response.get("error") is True, (
        f"max_chars={max_chars} silently sliced the body instead of erroring: "
        f"{response}"
    )
    assert response["operation"] == "invalid_max_chars"
    assert str(max_chars) in response["message"]


def test_positive_max_chars_still_caps_from_the_start(
    ops, tmp_path, patched_archive
) -> None:
    """The guard leaves the ordinary cap path untouched."""
    response = _get_section(
        ops, tmp_path, patched_archive, section_id="geography", max_chars=20
    )

    assert response.get("error") is not True
    assert response["truncated"] is True
    assert response["char_count"] == 20

    full = _get_section(ops, tmp_path, patched_archive, section_id="geography")
    assert full["content_markdown"].startswith(response["content_markdown"])
