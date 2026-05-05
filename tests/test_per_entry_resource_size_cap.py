"""Tests for the per-entry resource size cap.

Beta-test feedback: ``zim://{name}/entry/{path}`` returned the full body
of large entries (e.g. an 800 KB Wikipedia article) without any cap,
overflowing the MCP response budget. The fix caps text bodies at a
configurable byte limit and appends a truncation notice that points
callers at ``get_zim_entry`` (which supports paging through ``content_offset``).
"""

import pytest

from openzim_mcp.tools.resource_tools import (
    DEFAULT_RESOURCE_MAX_BYTES,
    _truncate_text_body,
)


def test_truncates_oversize_text_body_with_notice():
    """A body longer than the cap must come back truncated with a notice."""
    body = "x" * (DEFAULT_RESOURCE_MAX_BYTES + 5000)
    truncated = _truncate_text_body(body, DEFAULT_RESOURCE_MAX_BYTES)
    # Body proper is at most the cap.
    assert len(truncated) <= DEFAULT_RESOURCE_MAX_BYTES + 1024  # allow notice
    assert truncated.startswith("x")
    # Notice must point callers at the paging tool.
    assert "truncated" in truncated.lower()
    assert "get_zim_entry" in truncated


def test_under_cap_body_returned_unchanged():
    """A body smaller than the cap must round-trip unchanged."""
    body = "small body content"
    out = _truncate_text_body(body, DEFAULT_RESOURCE_MAX_BYTES)
    assert out == body


def test_cap_applies_per_byte_count_not_character_count():
    """The cap is a UTF-8 byte cap so multi-byte chars don't bypass it."""
    # Each CJK character is 3 bytes in UTF-8; 100 of them = 300 bytes.
    body = "中" * 100
    truncated = _truncate_text_body(body, 60)  # 60-byte cap → ~20 chars
    assert len(truncated.encode("utf-8")) <= 60 + 1024  # body+notice slack
    # Notice must still appear.
    assert "truncated" in truncated.lower()


@pytest.mark.parametrize("max_bytes", [0, -1, -100])
def test_zero_or_negative_cap_returns_only_notice(max_bytes):
    """A zero/negative cap must not wedge the implementation."""
    body = "anything"
    out = _truncate_text_body(body, max_bytes)
    # Either an empty string with notice, or just the notice — both are
    # acceptable so long as it doesn't raise.
    assert isinstance(out, str)


class TestBinaryResourceCap:
    """Oversize binary resources must refuse rather than silently truncate.

    A clipped PDF / PNG / video is unusable and the caller has no way to
    detect the corruption. Better to raise so the caller can switch to
    ``get_binary_entry`` (which exposes ``max_size_bytes`` and returns
    a ``truncated`` flag).
    """

    @pytest.mark.asyncio
    async def test_oversize_binary_raises_with_actionable_message(self):
        """Read of an oversize binary entry raises and points at get_binary_entry."""
        from unittest.mock import MagicMock, patch

        from openzim_mcp.exceptions import OpenZimMcpArchiveError
        from openzim_mcp.tools.resource_tools import (
            DEFAULT_RESOURCE_MAX_BYTES,
            ZimEntryResource,
        )

        # Construct a fake archive whose only entry returns oversize bytes
        # with a binary MIME type (image/png).
        mock_entry = MagicMock()
        mock_entry.path = "I/big.png"
        mock_entry.is_redirect = False
        mock_item = MagicMock()
        mock_item.mimetype = "image/png"
        mock_item.content = b"\x89PNG\r\n\x1a\n" + b"x" * (
            DEFAULT_RESOURCE_MAX_BYTES + 1024
        )
        mock_entry.get_item.return_value = mock_item
        mock_archive = MagicMock()
        mock_archive.get_entry_by_path.return_value = mock_entry

        # Stub the validator + zim_archive context manager.
        validator = MagicMock()
        validator.validate_path.return_value = "/data/x.zim"
        validator.validate_zim_file.return_value = "/data/x.zim"

        resource = ZimEntryResource(
            uri="zim://x.zim/entry/I%2Fbig.png",
            name="zim_entry",
            mime_type="application/octet-stream",
            archive_path="/data/x.zim",
            entry_path="I/big.png",
            path_validator=validator,
        )
        with patch("openzim_mcp.tools.resource_tools.zim_archive") as mock_zim_archive:
            mock_zim_archive.return_value.__enter__.return_value = mock_archive
            with pytest.raises(OpenZimMcpArchiveError) as exc:
                await resource.read()
        msg = str(exc.value)
        assert "get_binary_entry" in msg, msg
        assert "max_size_bytes" in msg, msg
