"""Tests for the per-entry zim:// resource."""

import asyncio
import contextlib
import time
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ResourceNotFoundError


@pytest.fixture
def ctx(server) -> Context:
    """Build the ``Context`` that SDK v2 requires on every resource lookup.

    ``ResourceManager.get_resource`` takes a mandatory ``context`` in MCP 2.0
    so templates can drive the multi-round-trip input flow. These tests never
    request input, so a bare context bound to the server's own MCPServer and
    subscription bus is enough to exercise routing and reads.
    """
    return Context(mcp_server=server.mcp, subscriptions=server.subscription_bus)


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
    async def test_html_returns_text(self, server, ctx: Context, monkeypatch):
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
        resource = await rm.get_resource("zim://wiki/entry/A%2FArticle", ctx)
        body = await resource.read()
        assert isinstance(body, str)
        assert "<html>" in body
        # decoded path was forwarded to libzim, not the encoded form
        archive.get_entry_by_path.assert_called_once_with("A/Article")

    @pytest.mark.asyncio
    async def test_entry_path_is_not_double_decoded(
        self, server, ctx: Context, monkeypatch
    ):
        """A stored path containing a literal ``%`` survives the round-trip.

        The v2 SDK's ``UriTemplate.match`` already percent-decodes captured
        parameters, so a request for ``page%2520name`` hands the template
        ``page%20name`` — the verbatim stored path (zimit/web-archive ZIMs
        keep percent-escapes in entry paths). A second decode would corrupt
        it to ``page name`` and miss the entry.
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
        item.content = b"body"
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
        resource = await rm.get_resource("zim://wiki/entry/page%2520name", ctx)
        await resource.read()
        archive.get_entry_by_path.assert_called_once_with("page%20name")

    @pytest.mark.asyncio
    async def test_binary_returns_bytes(self, server, ctx: Context, monkeypatch):
        """An image entry comes back as raw bytes (the SDK base64-wraps)."""
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
        resource = await rm.get_resource("zim://wiki/entry/I%2Flogo.png", ctx)
        body = await resource.read()
        assert isinstance(body, bytes)
        assert body == png_bytes
        archive.get_entry_by_path.assert_called_once_with("I/logo.png")

    @pytest.mark.asyncio
    async def test_unknown_zim_file_raises(self, server, ctx: Context):
        """An unknown name raises ResourceNotFoundError, not a bare ValueError.

        The type matters on the wire: the SDK maps ResourceNotFoundError to
        ``-32602`` invalid params carrying the descriptive message, while an
        unmapped ValueError escapes as a generic ``-32603`` "Internal server
        error" — turning a routine client typo into what looks like a
        retryable server fault.
        """
        server.zim_operations.list_zim_files_data = MagicMock(return_value=[])
        rm = server.mcp._resource_manager
        with pytest.raises(ResourceNotFoundError, match="not found"):
            await rm.get_resource("zim://nonexistent/entry/A%2FMissing", ctx)

    @pytest.mark.asyncio
    async def test_missing_entry_is_invalid_params_naming_the_entry(
        self, server, ctx: Context, monkeypatch
    ):
        """A missing entry names itself instead of reading as a server fault.

        libzim signals one with a bare ``KeyError('Cannot find entry')``.
        Being neither ``MCPError`` nor ``OpenZimMcpArchiveError``, it fell
        through to the SDK, which replaced it with "Error reading resource
        <uri>" under ``-32603`` — an internal-error code inviting a retry, for
        a request that can never succeed, and no mention of which entry was
        missing. ``test_unknown_zim_file_raises`` above pins the same contract
        one level up, for the archive.
        """
        from mcp.shared.exceptions import MCPError
        from mcp_types import INVALID_PARAMS

        from openzim_mcp.tools import resource_tools

        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wiki.zim", "name": "wiki.zim"}]
        )
        server.path_validator.validate_path = MagicMock(return_value="/zim/wiki.zim")
        server.path_validator.validate_zim_file = MagicMock(
            return_value="/zim/wiki.zim"
        )

        archive = MagicMock()
        archive.get_entry_by_path.side_effect = KeyError("Cannot find entry")

        class FakeCtx:
            def __enter__(self_inner):
                return archive

            def __exit__(self_inner, *exc):
                return False

        monkeypatch.setattr(resource_tools, "zim_archive", lambda *a, **k: FakeCtx())

        rm = server.mcp._resource_manager
        resource = await rm.get_resource("zim://wiki/entry/A%2FMissing", ctx)
        with pytest.raises(MCPError) as excinfo:
            await resource.read()

        assert excinfo.value.error.code == INVALID_PARAMS
        message = excinfo.value.error.message
        assert "A/Missing" in message, message
        assert "wiki" in message, message

    @pytest.mark.asyncio
    async def test_literal_slash_does_not_route(self, server, ctx: Context):
        """Unencoded '/' in the path doesn't match the template.

        Locks in the SDK behaviour documented in the spike note: the URI
        template's ``[^/]+`` regex won't match a literal slash, so the request
        fails to route. MCP 2.0 signals that with ``ResourceNotFoundError``
        rather than the bare ``ValueError`` the 1.x manager raised.
        """
        rm = server.mcp._resource_manager
        with pytest.raises(ResourceNotFoundError):
            await rm.get_resource("zim://wiki/entry/A/Article", ctx)

    @pytest.mark.asyncio
    async def test_mime_type_reflects_native_item_mime(
        self, server, ctx: Context, monkeypatch
    ):
        """The Resource's mime_type after read() matches the libzim Item mime.

        Pinning this prevents regression of the v1.0.0 bug where the SDK
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
        resource = await rm.get_resource("zim://wiki/entry/A%2FArticle", ctx)
        # Before read(): placeholder mime from create_resource()
        assert resource.mime_type == "application/octet-stream"
        await resource.read()
        # After read(): mutated to the libzim native MIME (charset stripped)
        assert resource.mime_type == "text/html"

    @pytest.mark.asyncio
    async def test_mime_type_reflects_binary_item_mime(
        self, server, ctx: Context, monkeypatch
    ):
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
        resource = await rm.get_resource("zim://wiki/entry/I%2Flogo.png", ctx)
        await resource.read()
        assert resource.mime_type == "image/png"

    @pytest.mark.asyncio
    async def test_lowercase_encoding_also_works(
        self, server, ctx: Context, monkeypatch
    ):
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
        resource = await rm.get_resource("zim://wiki/entry/A%2farticle", ctx)
        await resource.read()
        archive.get_entry_by_path.assert_called_once_with("A/article")

    @pytest.mark.asyncio
    async def test_uri_with_null_byte_is_rejected_by_router(
        self, server, ctx: Context, monkeypatch
    ):
        r"""A URI carrying an encoded NUL never reaches the ZIM archive.

        ``zim://name/entry/A%2FFoo%00bar`` decodes to ``A/Foo\x00bar``. In
        MCP 2.0 the resource manager's ``ResourceSecurity`` policy rejects
        NUL-bearing template parameters up front (surfacing as
        ``ResourceNotFoundError`` so a laxer template can't pick the URI up),
        so the request dies before any template handler runs.
        """
        from openzim_mcp.tools import resource_tools

        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wiki.zim", "name": "wiki.zim"}]
        )
        archive = MagicMock()

        class FakeCtx:
            def __enter__(self_inner):
                return archive

            def __exit__(self_inner, *exc):
                return False

        monkeypatch.setattr(resource_tools, "zim_archive", lambda *a, **k: FakeCtx())

        rm = server.mcp._resource_manager
        with pytest.raises(ResourceNotFoundError):
            await rm.get_resource("zim://wiki/entry/A%2FFoo%00bar", ctx)
        archive.get_entry_by_path.assert_not_called()

    @pytest.mark.asyncio
    async def test_decoded_path_is_sanitized_before_libzim(
        self, server, ctx: Context, monkeypatch
    ):
        r"""Control characters in the decoded path are stripped before libzim.

        Defense in depth behind the router's NUL check: the template is
        driven directly with an already-decoded ``A/Foo\x00bar`` so that our
        own ``sanitize_input`` pass is the only thing standing between the
        parameter and ``archive.get_entry_by_path``, which libzim offers no
        protection against embedded NULs for.
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

        template = server.mcp._resource_manager._templates["zim://{name}/entry/{path}"]
        resource = await template.create_resource(
            "zim://wiki/entry/A%2FFoo%00bar",
            {"name": "wiki", "path": "A/Foo\x00bar"},
            context=ctx,
        )
        await resource.read()
        called_path = archive.get_entry_by_path.call_args.args[0]
        assert (
            "\x00" not in called_path
        ), f"NUL byte leaked through to libzim: {called_path!r}"
        # The non-control portion survives.
        assert called_path == "A/Foobar"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("bad_path", "expected"),
        [
            ("   ", "empty"),
            ("A/" + "x" * 600, "too long"),
        ],
        ids=["empty-after-sanitize", "over-length"],
    )
    async def test_rejected_entry_path_keeps_its_message_on_the_wire(
        self, server, ctx: Context, bad_path: str, expected: str
    ):
        """A path ``sanitize_input`` rejects must not become "Internal server error".

        ``sanitize_input`` raises ``OpenZimMcpValidationError``, which is
        neither ``MCPError`` nor a ``ResourceError`` — and nothing downstream
        converts it, because ``ResourceManager.get_resource`` calls
        ``create_resource`` *outside* the ``try`` that wraps ``resource.read()``.
        An unmapped exception is replaced wholesale by a generic
        ``-32603 Internal server error``, so the caller loses the only
        actionable part ("Input is empty…" / "Input too long: N > M") and reads
        a request-shaped mistake as a retryable server fault.
        """
        from mcp.shared.exceptions import MCPError
        from mcp_types import INVALID_PARAMS

        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wiki.zim", "name": "wiki.zim"}]
        )
        template = server.mcp._resource_manager._templates["zim://{name}/entry/{path}"]

        with pytest.raises(MCPError) as excinfo:
            await template.create_resource(
                f"zim://wiki/entry/{bad_path}",
                {"name": "wiki", "path": bad_path},
                context=ctx,
            )

        assert excinfo.value.error.code == INVALID_PARAMS
        assert expected in excinfo.value.error.message.lower()

    @pytest.mark.asyncio
    async def test_redirect_entry_is_resolved_before_get_item(
        self, server, ctx: Context, monkeypatch
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
        resource = await rm.get_resource("zim://wiki/entry/A%2FStub", ctx)
        body = await resource.read()
        assert body == "target"
        target.get_item.assert_called_once()
        redirect.get_item.assert_not_called()

    @pytest.mark.asyncio
    async def test_redirect_cycle_raises_archive_error(
        self, server, ctx: Context, monkeypatch
    ):
        """A redirect cycle (A → A) raises MCPError with the diagnostic intact.

        ``MCPError`` and ``ResourceError`` are the exception types SDK v2's
        ``read_resource`` re-raises verbatim (2.0.x re-raised only
        ``MCPError``); anything else is swallowed into a generic "Error
        reading resource <uri>" that tells the client nothing. ``MCPError``
        is the one that carries a chosen JSON-RPC code as well as the text.
        """
        from mcp.shared.exceptions import MCPError

        from openzim_mcp.tools import resource_tools

        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wiki.zim", "name": "wiki.zim"}]
        )
        server.path_validator.validate_path = MagicMock(return_value="/zim/wiki.zim")
        server.path_validator.validate_zim_file = MagicMock(
            return_value="/zim/wiki.zim"
        )

        # Self-referential redirect (entry redirects to itself).
        cyclic = MagicMock()
        cyclic.is_redirect = True
        cyclic.path = "A/Loop"
        cyclic.get_redirect_entry.return_value = cyclic

        archive = MagicMock()
        archive.get_entry_by_path.return_value = cyclic

        class FakeCtx:
            def __enter__(self_inner):
                return archive

            def __exit__(self_inner, *exc):
                return False

        monkeypatch.setattr(resource_tools, "zim_archive", lambda *a, **k: FakeCtx())

        rm = server.mcp._resource_manager
        resource = await rm.get_resource("zim://wiki/entry/A%2FLoop", ctx)
        with pytest.raises(MCPError, match="Redirect cycle"):
            await resource.read()

    @pytest.mark.asyncio
    async def test_redirect_chain_too_deep_raises_archive_error(
        self, server, ctx: Context, monkeypatch
    ):
        """A chain longer than MAX_REDIRECT_DEPTH raises MCPError (see above)."""
        from mcp.shared.exceptions import MCPError

        from openzim_mcp.tools import resource_tools
        from openzim_mcp.zim_operations import MAX_REDIRECT_DEPTH

        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wiki.zim", "name": "wiki.zim"}]
        )
        server.path_validator.validate_path = MagicMock(return_value="/zim/wiki.zim")
        server.path_validator.validate_zim_file = MagicMock(
            return_value="/zim/wiki.zim"
        )

        # Build MAX_REDIRECT_DEPTH+1 unique redirects so the chain exceeds the
        # cap without triggering the cycle guard.
        chain = []
        for i in range(MAX_REDIRECT_DEPTH + 1):
            link = MagicMock()
            link.is_redirect = True
            link.path = f"A/Hop{i}"
            chain.append(link)
        for prev, nxt in zip(chain, chain[1:]):
            prev.get_redirect_entry.return_value = nxt
        # The last hop continues to redirect (still is_redirect=True), keeping
        # the chain "too deep" rather than terminating in a real entry.
        chain[-1].get_redirect_entry.return_value = chain[-1]
        chain[-1].path = "A/HopFinal"

        archive = MagicMock()
        archive.get_entry_by_path.return_value = chain[0]

        class FakeCtx:
            def __enter__(self_inner):
                return archive

            def __exit__(self_inner, *exc):
                return False

        monkeypatch.setattr(resource_tools, "zim_archive", lambda *a, **k: FakeCtx())

        rm = server.mcp._resource_manager
        resource = await rm.get_resource("zim://wiki/entry/A%2FHop0", ctx)
        with pytest.raises(MCPError, match="Redirect chain too deep"):
            await resource.read()

    @pytest.mark.asyncio
    async def test_resource_template_does_not_block_event_loop(
        self, server, ctx: Context, monkeypatch
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
                context=ctx,
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
