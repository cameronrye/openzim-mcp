"""A missing ``M/<key>`` must fail like every other missing entry.

``zim_get(entry_path="M/iep.utm.edu/kantview/")`` returned ``isError=false``
with the sentence "Metadata key '…' not found in this archive." sitting in
the ``content`` field, so a client that renders ``content`` showed an error
message as though it were the article's text. A content-namespace miss on
the same server correctly raises and surfaces the Resource Not Found
envelope.

The recovery hint was also uncallable: ``walk namespace M`` is a ``zim_query``
phrasing, not a tool at the advanced surface, where the caller needs
``zim_browse(namespace="M")``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openzim_mcp.exceptions import OpenZimMcpEntryNotFoundError


def _content_ops(tmp_path, tool_mode: str = "advanced"):
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import CacheConfig, ContentConfig, OpenZimMcpConfig
    from openzim_mcp.content_processor import ContentProcessor
    from openzim_mcp.security import PathValidator
    from openzim_mcp.zim_operations import ZimOperations

    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=4, ttl_seconds=60),
        content=ContentConfig(max_content_length=5000, snippet_length=200),
        tool_mode=tool_mode,
    )
    return ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=200, tool_mode=tool_mode),
    )


@pytest.fixture
def content_ops(tmp_path):
    """The advanced surface — the one this module's hint was written for."""
    return _content_ops(tmp_path)


def _archive_without(key_error: bool = True) -> MagicMock:
    archive = MagicMock()
    archive.get_metadata_item.side_effect = KeyError("no such metadata key")
    return archive


def test_missing_metadata_key_raises_not_found(content_ops):
    """The miss must raise, not return a success-shaped payload."""
    with pytest.raises(OpenZimMcpEntryNotFoundError):
        content_ops._get_metadata_entry_data(
            _archive_without(), "M/iep.utm.edu/kantview/", 5000, 0
        )


def test_empty_metadata_key_raises_not_found(content_ops):
    with pytest.raises(OpenZimMcpEntryNotFoundError):
        content_ops._get_metadata_entry_data(_archive_without(), "M/", 5000, 0)


def test_recovery_hint_names_a_callable_tool(content_ops):
    with pytest.raises(OpenZimMcpEntryNotFoundError) as exc_info:
        content_ops._get_metadata_entry_data(_archive_without(), "M/NoSuchKey", 5000, 0)
    message = str(exc_info.value)
    assert "zim_browse" in message
    assert "walk namespace" not in message


def test_recovery_hint_is_callable_in_simple_mode(tmp_path):
    """The same fix, one surface further: ``zim_browse`` is not registered.

    Naming it here repeated the very defect this module was written for —
    an advanced tool offered to the client that has only ``zim_query`` —
    and the message is echoed verbatim into the ``zim_query`` body, so it
    was reaching real simple-mode callers.
    """
    ops = _content_ops(tmp_path, tool_mode="simple")
    with pytest.raises(OpenZimMcpEntryNotFoundError) as exc_info:
        ops._get_metadata_entry_data(_archive_without(), "M/NoSuchKey", 5000, 0)
    message = str(exc_info.value)
    assert "browse namespace M" in message
    assert "zim_browse" not in message


def test_present_metadata_key_still_returns_payload(content_ops):
    """Positive control: a real key must keep its success path."""
    archive = MagicMock()
    item = MagicMock()
    item.mimetype = "text/plain"
    item.content = b"Encyclopedia of Philosophy"
    archive.get_metadata_item.return_value = item

    payload, content_ok = content_ops._get_metadata_entry_data(
        archive, "M/Title", 5000, 0
    )
    assert content_ok is True
    assert payload["content"] == "Encyclopedia of Philosophy"
