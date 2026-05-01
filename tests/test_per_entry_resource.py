"""Tests for the per-entry zim:// resource."""

from unittest.mock import MagicMock

import pytest


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


class TestPerEntryResource:
    """Functional tests for the zim://{name}/entry/{path} resource."""

    @pytest.fixture
    def server(self, test_config):
        """Create a server with all tools and resources registered."""
        from openzim_mcp.server import OpenZimMcpServer

        return OpenZimMcpServer(test_config)

    def test_resource_template_is_registered(self, server):
        """Form-2 template registered with form 'zim://{name}/entry/{path}'."""
        templates = server.mcp._resource_manager._templates
        assert "zim://{name}/entry/{path}" in templates

    @pytest.mark.asyncio
    async def test_html_returns_text(self, server, monkeypatch):
        """An HTML entry comes back as decoded text (str)."""
        from openzim_mcp.tools import resource_tools

        # Stub list_zim_files_data so the name resolves.
        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wiki.zim", "name": "wiki.zim"}]
        )
        # Path validator is bypassed cleanly for the synthetic test path.
        server.path_validator.validate_path = MagicMock(return_value="/zim/wiki.zim")
        server.path_validator.validate_zim_file = MagicMock(
            return_value="/zim/wiki.zim"
        )

        # Stub the libzim archive layer.
        archive = MagicMock()
        item = MagicMock()
        item.mimetype = "text/html; charset=utf-8"
        item.content = b"<html><body>hi</body></html>"
        entry = MagicMock()
        entry.get_item.return_value = item
        archive.get_entry_by_path.return_value = entry

        class FakeCtx:
            def __enter__(self_inner):
                return archive

            def __exit__(self_inner, *exc):
                return False

        monkeypatch.setattr(resource_tools, "zim_archive", lambda *a, **k: FakeCtx())

        # Invoke through the resource manager so we exercise routing too.
        rm = server.mcp._resource_manager
        resource = await rm.get_resource("zim://wiki/entry/A%2FArticle")
        body = await resource.read()
        assert isinstance(body, str)
        assert "<html>" in body
        # decoded path was forwarded to libzim, not the encoded form
        archive.get_entry_by_path.assert_called_once_with("A/Article")

    @pytest.mark.asyncio
    async def test_binary_returns_bytes(self, server, monkeypatch):
        """An image entry comes back as raw bytes (FastMCP base64-wraps)."""
        from openzim_mcp.tools import resource_tools

        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wiki.zim", "name": "wiki.zim"}]
        )
        server.path_validator.validate_path = MagicMock(return_value="/zim/wiki.zim")
        server.path_validator.validate_zim_file = MagicMock(
            return_value="/zim/wiki.zim"
        )

        archive = MagicMock()
        item = MagicMock()
        item.mimetype = "image/png"
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        item.content = png_bytes
        entry = MagicMock()
        entry.get_item.return_value = item
        archive.get_entry_by_path.return_value = entry

        class FakeCtx:
            def __enter__(self_inner):
                return archive

            def __exit__(self_inner, *exc):
                return False

        monkeypatch.setattr(resource_tools, "zim_archive", lambda *a, **k: FakeCtx())

        rm = server.mcp._resource_manager
        resource = await rm.get_resource("zim://wiki/entry/I%2Flogo.png")
        body = await resource.read()
        assert isinstance(body, bytes)
        assert body == png_bytes
        archive.get_entry_by_path.assert_called_once_with("I/logo.png")

    @pytest.mark.asyncio
    async def test_unknown_zim_file_raises(self, server):
        """Requesting a name that isn't in list_zim_files_data raises ValueError."""
        server.zim_operations.list_zim_files_data = MagicMock(return_value=[])
        rm = server.mcp._resource_manager
        with pytest.raises(ValueError, match="not found"):
            await rm.get_resource("zim://nonexistent/entry/A%2FMissing")

    @pytest.mark.asyncio
    async def test_literal_slash_does_not_route(self, server):
        """Unencoded '/' in the path doesn't match the template.

        Locks in the SDK behaviour documented in the spike note: FastMCP's
        ``[^/]+`` regex won't match a literal slash, so the request fails to
        route and the manager raises ValueError.
        """
        rm = server.mcp._resource_manager
        with pytest.raises(ValueError):
            await rm.get_resource("zim://wiki/entry/A/Article")

    @pytest.mark.asyncio
    async def test_lowercase_encoding_also_works(self, server, monkeypatch):
        """`%2f` (lowercase) also rounds-trips through unquote."""
        from openzim_mcp.tools import resource_tools

        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wiki.zim", "name": "wiki.zim"}]
        )
        server.path_validator.validate_path = MagicMock(return_value="/zim/wiki.zim")
        server.path_validator.validate_zim_file = MagicMock(
            return_value="/zim/wiki.zim"
        )

        archive = MagicMock()
        item = MagicMock()
        item.mimetype = "text/plain"
        item.content = b"ok"
        entry = MagicMock()
        entry.get_item.return_value = item
        archive.get_entry_by_path.return_value = entry

        class FakeCtx:
            def __enter__(self_inner):
                return archive

            def __exit__(self_inner, *exc):
                return False

        monkeypatch.setattr(resource_tools, "zim_archive", lambda *a, **k: FakeCtx())

        rm = server.mcp._resource_manager
        resource = await rm.get_resource("zim://wiki/entry/A%2farticle")
        await resource.read()
        archive.get_entry_by_path.assert_called_once_with("A/article")
