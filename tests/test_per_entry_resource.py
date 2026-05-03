"""Tests for the per-entry zim:// resource."""

import asyncio
import contextlib
import time
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
        entry.is_redirect = False
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
        entry.is_redirect = False
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
    async def test_mime_type_reflects_native_item_mime(self, server, monkeypatch):
        """The Resource's mime_type after read() matches the libzim Item mime.

        Pinning this prevents regression of the v1.0.0 bug where FastMCP
        froze the template's default ``text/plain`` mime in the response
        regardless of the actual content type.
        """
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
        item.mimetype = "text/html; charset=utf-8"
        item.content = b"<html></html>"
        entry = MagicMock()
        entry.is_redirect = False
        entry.get_item.return_value = item
        archive.get_entry_by_path.return_value = entry

        class FakeCtx:
            def __enter__(self_inner):
                return archive

            def __exit__(self_inner, *exc):
                return False

        monkeypatch.setattr(resource_tools, "zim_archive", lambda *a, **k: FakeCtx())

        rm = server.mcp._resource_manager
        resource = await rm.get_resource("zim://wiki/entry/A%2FArticle")
        # Before read(): placeholder mime from create_resource()
        assert resource.mime_type == "application/octet-stream"
        await resource.read()
        # After read(): mutated to the libzim native MIME (charset stripped)
        assert resource.mime_type == "text/html"

    @pytest.mark.asyncio
    async def test_mime_type_reflects_binary_item_mime(self, server, monkeypatch):
        """Binary entries report their native MIME (e.g. image/png), not text/plain."""
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
        item.content = b"\x89PNG\r\n\x1a\n"
        entry = MagicMock()
        entry.is_redirect = False
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
        await resource.read()
        assert resource.mime_type == "image/png"

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
        entry.is_redirect = False
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

    @pytest.mark.asyncio
    async def test_uri_decoded_path_is_sanitized(self, server, monkeypatch):
        r"""Control characters in the URI-decoded path are stripped before libzim.

        A URI like ``zim://name/entry/A%2FFoo%00bar`` decodes to
        ``A/Foo\x00bar``; this byte must not reach
        ``archive.get_entry_by_path`` because libzim has no defense against
        embedded NULs in paths.
        """
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
        entry.is_redirect = False
        entry.get_item.return_value = item
        archive.get_entry_by_path.return_value = entry

        class FakeCtx:
            def __enter__(self_inner):
                return archive

            def __exit__(self_inner, *exc):
                return False

        monkeypatch.setattr(resource_tools, "zim_archive", lambda *a, **k: FakeCtx())

        rm = server.mcp._resource_manager
        # %00 is NUL; it must be stripped before reaching libzim.
        resource = await rm.get_resource("zim://wiki/entry/A%2FFoo%00bar")
        await resource.read()
        called_path = archive.get_entry_by_path.call_args.args[0]
        assert (
            "\x00" not in called_path
        ), f"NUL byte leaked through to libzim: {called_path!r}"
        # The non-control portion survives.
        assert called_path == "A/Foobar"

    @pytest.mark.asyncio
    async def test_redirect_entry_is_resolved_before_get_item(
        self, server, monkeypatch
    ):
        """Redirect entries follow their chain before get_item() is called.

        ``Entry.get_item()`` raises ``RuntimeError`` if called on a redirect
        entry, so the resource must walk the redirect chain first.
        """
        from openzim_mcp.tools import resource_tools

        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wiki.zim", "name": "wiki.zim"}]
        )
        server.path_validator.validate_path = MagicMock(return_value="/zim/wiki.zim")
        server.path_validator.validate_zim_file = MagicMock(
            return_value="/zim/wiki.zim"
        )

        item = MagicMock()
        item.mimetype = "text/plain"
        item.content = b"target"

        target = MagicMock()
        target.is_redirect = False
        target.get_item.return_value = item

        redirect = MagicMock()
        redirect.is_redirect = True
        redirect.path = "A/Stub"
        redirect.get_redirect_entry.return_value = target
        # Calling get_item() on a redirect entry would raise; assert we don't.
        redirect.get_item.side_effect = RuntimeError("get_item on redirect entry")

        archive = MagicMock()
        archive.get_entry_by_path.return_value = redirect

        class FakeCtx:
            def __enter__(self_inner):
                return archive

            def __exit__(self_inner, *exc):
                return False

        monkeypatch.setattr(resource_tools, "zim_archive", lambda *a, **k: FakeCtx())

        rm = server.mcp._resource_manager
        resource = await rm.get_resource("zim://wiki/entry/A%2FStub")
        body = await resource.read()
        assert body == "target"
        target.get_item.assert_called_once()
        redirect.get_item.assert_not_called()

    @pytest.mark.asyncio
    async def test_resource_template_does_not_block_event_loop(
        self, server, monkeypatch
    ):
        """create_resource must offload list_zim_files_data via to_thread.

        H17: under HTTP/SSE with concurrent clients, a sync directory scan in
        an async handler starves all other clients. Wrap in asyncio.to_thread
        so the loop stays responsive while the directory scan runs.

        We assert by counting heartbeats that fire *during* the blocking call.
        If the loop is blocked, the heartbeat task can't tick at all until
        create_resource returns, so we'd see <= 1 tick during a 0.5s call.
        """
        from openzim_mcp.tools.resource_tools import ZimEntryTemplate

        # Force list_zim_files_data to take 0.5s synchronously so we can
        # detect whether the event loop is blocked during the call.
        def slow():
            time.sleep(0.5)
            return [{"path": "/zim/wiki.zim", "name": "wiki.zim"}]

        monkeypatch.setattr(server.zim_operations, "list_zim_files_data", slow)

        # Reuse the registered template instance (carries server_ref).
        rm = server.mcp._resource_manager
        template = rm._templates["zim://{name}/entry/{path}"]
        assert isinstance(template, ZimEntryTemplate)

        # Heartbeat ticks every 50ms. Records ticks observed by the time
        # create_resource returns. If the loop is blocked the whole 0.5s,
        # ticks will be ~0; if offloaded, ticks should be ~10.
        ticks_during_call = 0

        async def heartbeat() -> None:
            nonlocal ticks_during_call
            while True:
                await asyncio.sleep(0.05)
                ticks_during_call += 1

        hb = asyncio.create_task(heartbeat())
        # Yield once so the heartbeat task starts before we begin blocking.
        await asyncio.sleep(0)
        # We're testing event-loop responsiveness, not the success path,
        # so swallow any error from create_resource.
        with contextlib.suppress(Exception):
            await template.create_resource(
                "zim://wiki/entry/A%2FFoo",
                {"name": "wiki", "path": "A%2FFoo"},
            )
        # Snapshot ticks before cancelling the heartbeat task.
        observed = ticks_during_call
        hb.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await hb
        # 0.5s blocking call / 50ms tick = ~10 ticks if non-blocking.
        # Allow scheduling jitter; require at least 8/10.
        assert (
            observed >= 8
        ), f"event loop was blocked: {observed} heartbeats fired during call"


class TestResolveZimName:
    """Tests for the shared _resolve_zim_name helper.

    The helper consolidates the previously-duplicated stem/full-name match
    logic from create_resource (per-entry) and zim_file_overview (zim://name).
    Both call sites must accept either the bare basename ('wikipedia') or
    the full filename ('wikipedia.zim') and resolve to the same path.
    """

    @pytest.fixture
    def server(self, test_config):
        """Build a server instance bound to the test config."""
        from openzim_mcp.server import OpenZimMcpServer

        return OpenZimMcpServer(test_config)

    def test_resolve_by_stem(self, server):
        """Bare basename ('wikipedia') resolves to the matching archive path."""
        from openzim_mcp.tools.resource_tools import _resolve_zim_name

        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wikipedia.zim", "name": "wikipedia.zim"}]
        )
        assert _resolve_zim_name(server, "wikipedia") == "/zim/wikipedia.zim"

    def test_resolve_by_full_name(self, server):
        """Full filename ('wikipedia.zim') resolves to the matching archive path."""
        from openzim_mcp.tools.resource_tools import _resolve_zim_name

        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wikipedia.zim", "name": "wikipedia.zim"}]
        )
        assert _resolve_zim_name(server, "wikipedia.zim") == "/zim/wikipedia.zim"

    def test_resolve_stem_and_full_name_agree(self, server):
        """The two name forms must resolve to the same path."""
        from openzim_mcp.tools.resource_tools import _resolve_zim_name

        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wikipedia.zim", "name": "wikipedia.zim"}]
        )
        assert _resolve_zim_name(server, "wikipedia") == _resolve_zim_name(
            server, "wikipedia.zim"
        )

    def test_resolve_unknown_returns_none(self, server):
        """Unknown name returns None — caller surfaces the error envelope."""
        from openzim_mcp.tools.resource_tools import _resolve_zim_name

        server.zim_operations.list_zim_files_data = MagicMock(return_value=[])
        assert _resolve_zim_name(server, "nonexistent") is None
