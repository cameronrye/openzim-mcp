"""Tests for the per-entry zim:// resource."""

from unittest.mock import MagicMock


def test_detect_mime_html():
    """Strip charset parameter from HTML mimetype."""
    from openzim_mcp.tools.resource_tools import _detect_mime_type

    item = MagicMock()
    item.mimetype = "text/html; charset=utf-8"
    assert _detect_mime_type(item) == "text/html"


def test_detect_mime_image():
    """Image mimetypes pass through unchanged."""
    from openzim_mcp.tools.resource_tools import _detect_mime_type

    item = MagicMock()
    item.mimetype = "image/png"
    assert _detect_mime_type(item) == "image/png"


def test_detect_mime_unknown_falls_back_to_octet():
    """Empty mimetype falls back to application/octet-stream."""
    from openzim_mcp.tools.resource_tools import _detect_mime_type

    item = MagicMock()
    item.mimetype = ""
    assert _detect_mime_type(item) == "application/octet-stream"


def test_detect_mime_missing_attr_falls_back():
    """No mimetype attribute on the item falls back to octet-stream."""
    from openzim_mcp.tools.resource_tools import _detect_mime_type

    item = MagicMock(spec=[])  # no mimetype attribute
    assert _detect_mime_type(item) == "application/octet-stream"
