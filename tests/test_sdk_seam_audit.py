"""Seam audit for the ``mcp[cli]>=2.3.0,<2.4`` range.

The seams this server reaches into are all underscore-prefixed or otherwise
outside upstream's documented compatibility promise (``VERSIONING.md``: it
"does not cover underscore-prefixed names, undocumented modules"). CI resolves
``uv.lock``, so the only wheel any test ever exercises is the locked one — a
fresh ``pip install openzim-mcp`` takes the newest the range admits instead.
That gap is what these tests close: each one pins a property of the SDK the
range spans, so a resolution that moves one fails here by name rather than at
runtime in someone's deployment.

The behaviours below all changed between 2.0.0 and 2.1.0 in ways that touch
code or comments in this repo:

* upstream #3336 moved ``DEFAULT_MAX_REQUEST_BODY_SIZE`` (and
  ``RequestBodyLimitMiddleware``) into ``mcp.server.transport_security`` and
  put a method guard and a body cap on the SSE message endpoint;
* upstream #3314 stopped a *crashing* tool body's exception text from
  reaching the client — while deliberately leaving argument-validation
  failures leaking pydantic's report, which is why ``zim_browse``'s
  ``_ModeArg`` comment is still accurate;
* 2.1.1's ``read_resource`` moved ``get_resource`` inside the ``try`` and
  added a runtime ``str | bytes`` check on ``Resource.read()``.

Between 2.1.1 and 2.3.0, these changes reach code or comments here:

* upstream #3395 (2.2.0) rewrote the handshake-era session lifecycle. A
  DELETE now frees its session, a refused opening request no longer leaves
  one behind, a session idle for 30 minutes expires, and the manager holds at
  most 10,000 sessions. That retires the leak the ``http_app`` gates were
  written against (GHSA-84m7-p3x7-pcfv, issue #453), and
  ``TestSessionLifecycleSeam`` pins it;
* 2.3.0's ``MCPServer(subscriptions=False)`` leaves ``subscriptions/listen``
  unregistered, the public spelling of what ``server.py`` used to do by
  popping ``_request_handlers`` (``test_subscriptions.py``'s capability gate
  covers it). Installing the bounded handler still goes through the private
  registry;
* 2.3.0 validates ``Mcp-Param-*`` headers against ``tool.parameters``
  directly (``get_tool_input_schema``) instead of running the ``tools/list``
  handler. ``schema_slimming`` rewrites that dict in place at registration,
  so the schema validated against is still the one served.

Audited and found inert here: mcp-types 2.3 turning ``RequestId``,
``Cursor`` and the other single-value ``RootModel`` wrappers into plain
aliases (only the versioned wire modules changed, not the ``mcp_types``
names this repo imports); the dispatcher's outbound-request changes (this
server sends the client no requests); ``func_metadata``'s dict output model
(no tool here declares structured output); and ``initialize`` omitting an
empty ``capabilities.experimental``.

What is deliberately *not* here: the advertised schema footprint (already
measured live and asserted against the allocation table in
``test_phase_f_schema_budget.py`` and against the docs in
``test_docs_freshness.py`` — a third hardcoded copy would red those same
edits with the least informative message of the three); upstream's ping
stance (``test_sdk_ping_shim.py::test_canary_upstream_still_lacks_modern_ping``
asserts it against the resolved SDK, which is the range-sensitive form of the
claim); and the docs-quote-the-range gate, which moved to
``test_docs_freshness.py`` section 15 when it was widened to sweep prose.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from packaging.requirements import Requirement
from packaging.version import Version
from starlette.testclient import TestClient

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.http_app import serve_streamable_http
from openzim_mcp.server import OpenZimMcpServer
from tests.test_mcp_session import _text, advanced_session


def _server(tmp_path: Path) -> OpenZimMcpServer:
    return OpenZimMcpServer(
        OpenZimMcpConfig(allowed_directories=[str(tmp_path)], tool_mode="advanced")
    )


class TestRequestBodyCapSeam:
    """``DEFAULT_MAX_REQUEST_BODY_SIZE`` and its new home."""

    def test_constant_lives_in_transport_security(self) -> None:
        """The cap's canonical module, post-#3336.

        ``streamable_http_manager`` still re-exports it, so importing from
        the old home keeps working — which is exactly why this has to be
        asserted rather than inferred from a green suite. The re-export is
        upstream's compatibility shim, and a shim is the kind of thing a
        minor release drops.
        """
        from mcp.server.transport_security import DEFAULT_MAX_REQUEST_BODY_SIZE

        assert DEFAULT_MAX_REQUEST_BODY_SIZE == 4 * 1024 * 1024

    def test_gate_sources_the_cap_from_its_canonical_home(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The gate must read ``transport_security``, not the re-export.

        ``SessionlessRequestGateMiddleware`` replays a buffered body into the
        SDK, so its ceiling has to be the SDK's own or the gate becomes the
        limit nobody documented. A plain
        ``gate._max_body_size == DEFAULT_MAX_REQUEST_BODY_SIZE`` used to stand
        here saying so and was deleted as dead weight: both spellings resolve
        to the same 4 MiB int inside this range, so that assertion could not
        tell the two homes apart *and* stayed green when the ``else`` branch
        was replaced by a hardcoded ``4 * 1024 * 1024``. The import move was
        unobservable — the whole floor decision rested on an edit no test
        would have noticed reverting. This one reds under both mutations, so
        it subsumes the equality outright.

        Patching the constant on ``transport_security`` separates them:
        ``streamable_http_manager`` binds its own module-level name at import
        time (``from ... import X as X``), so it keeps the old value while the
        canonical module reports the new one. The gate's import is
        function-local, so it re-reads on every construction.
        """
        import mcp.server.streamable_http_manager as manager
        import mcp.server.transport_security as canonical

        from openzim_mcp.http_app import SessionlessRequestGateMiddleware

        async def _app(scope: Any, receive: Any, send: Any) -> None:  # pragma: no cover
            raise AssertionError("not called")

        sentinel = 4 * 1024 * 1024 + 7
        monkeypatch.setattr(canonical, "DEFAULT_MAX_REQUEST_BODY_SIZE", sentinel)
        # Guard the guard: if upstream ever made the re-export a live lookup
        # this test would stop distinguishing the two homes and quietly pass.
        assert manager.DEFAULT_MAX_REQUEST_BODY_SIZE != sentinel

        assert SessionlessRequestGateMiddleware(_app)._max_body_size == sentinel


class TestToolFailureTextOnTheWire:
    """What a crashing tool body versus a rejected argument tells the client."""

    @pytest.mark.asyncio
    async def test_crash_text_is_withheld_from_the_client(self, tmp_path: Path) -> None:
        """A tool body that crashes must not put its message on the wire.

        Pre-#3314 the SDK stringified *any* body exception into
        ``Error executing tool <name>: <text>``, so a stray internal message
        — a filesystem path, a stack-derived detail — reached the model
        verbatim. From 2.1.0 an unanticipated exception becomes
        ``UnexpectedToolError`` carrying only the tool's name.

        Asserted through a real session rather than against the SDK's source
        so it stays true of whatever the range resolves.
        """
        server = _server(tmp_path)
        tool = server.mcp._tool_manager.get_tool("zim_health")
        assert tool is not None
        secret = "n0tf0rcl13nts-/private/var/secret.zim"

        async def _boom(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError(secret)

        tool.fn = _boom  # type: ignore[assignment]

        from tests.test_mcp_session import _connected_client

        async with _connected_client(server) as session:
            result = await session.call_tool("zim_health", {})

        assert result.is_error is True
        text = _text(result)
        assert secret not in text, text
        assert "Error executing tool zim_health" in text, text

    @pytest.mark.asyncio
    async def test_crash_is_typed_as_unexpected(self, tmp_path: Path) -> None:
        """The wrapper's *type* is the seam ``mcp_envelope`` classifies on.

        ``call_tool`` catches ``ToolError`` and re-raises anything without a
        ``ValidationError`` in its ``__cause__`` chain. ``UnexpectedToolError``
        subclasses ``ToolError``, so that catch still sees a crash — if the
        subclassing ever went away the envelope would stop covering it.

        Imported inside the test rather than at module scope so a resolution
        that removes the name fails *here*, naming the seam, instead of
        killing collection for the whole file.
        """
        from mcp.server.mcpserver.exceptions import UnexpectedToolError

        assert issubclass(UnexpectedToolError, ToolError)

        server = _server(tmp_path)
        tool = server.mcp._tool_manager.get_tool("zim_health")
        assert tool is not None

        async def _boom(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("internal detail")

        tool.fn = _boom  # type: ignore[assignment]

        with pytest.raises(UnexpectedToolError):
            await server.mcp._tool_manager.call_tool(
                "zim_health", {}, context=None, convert_result=False
            )

    @pytest.mark.asyncio
    async def test_argument_rejection_still_carries_pydantic_report(
        self, tmp_path: Path
    ) -> None:
        """The paired control: #3314 did *not* touch argument validation.

        ``zim_browse``'s ``mode`` is typed ``str`` with the enum attached as
        schema metadata rather than as a ``Literal`` precisely because a
        ``Literal`` rejection happens inside pydantic, before the handler, and
        the SDK stringifies pydantic's report into the ``ToolError`` message.
        That is still true at the top of the range, so that comment — and the
        design it explains — stands. Asserted at the SDK layer, because
        ``mcp_envelope`` converts the leak before a client ever sees it.
        """
        server = _server(tmp_path)
        with pytest.raises(ToolError) as excinfo:
            await server.mcp._tool_manager.call_tool(
                "zim_search",
                {"query": "climate", "limit": "not-an-int"},
                context=None,
                convert_result=False,
            )

        from mcp.server.mcpserver.exceptions import UnexpectedToolError

        message = str(excinfo.value)
        assert "validation error" in message, message
        # ...and it is *not* classified as a crash, which is what lets
        # ``mcp_envelope`` tell the caller's mistake from the server's.
        assert not isinstance(excinfo.value, UnexpectedToolError), message

    @pytest.mark.asyncio
    async def test_bad_enum_value_still_reaches_the_envelope(
        self, tmp_path: Path
    ) -> None:
        """End to end: the leak above never reaches a client."""
        (tmp_path / "a.zim").write_bytes(b"ZIM\x04")
        async with advanced_session(tmp_path) as session:
            result = await session.call_tool(
                "zim_search",
                {
                    "query": "climate",
                    "zim_file_path": str(tmp_path / "a.zim"),
                    "mode": "query",
                },
            )

        payload = json.loads(_text(result))
        assert payload["operation"] == "invalid_argument"


class TestResourceReadSeam:
    """2.1.1's ``read_resource``: ``get_resource`` inside the ``try``."""

    @pytest.mark.asyncio
    async def test_unknown_archive_name_still_maps_to_invalid_params(
        self, tmp_path: Path
    ) -> None:
        """``ResourceNotFoundError`` must survive the move into the ``try``.

        2.0.0 raised it from ``get_resource`` *outside* the ``try``; 2.1.1
        raises it inside one whose first clause is
        ``except (MCPError, ResourceError): raise``. Since
        ``ResourceNotFoundError`` subclasses ``ResourceError`` the outcome is
        unchanged — but "unchanged" is a claim about a private control flow,
        so it gets an assertion instead of a reading.
        """
        server = _server(tmp_path)
        with pytest.raises(ResourceNotFoundError):
            await server.mcp.read_resource("zim://no-such-archive/entry/A%2FX")

    @pytest.mark.asyncio
    async def test_a_non_str_read_is_wrapped_not_forwarded(
        self, tmp_path: Path
    ) -> None:
        """2.1.1's ``TypeError`` becomes ``UnexpectedResourceError``.

        The check is new in 2.1.1: before it, a ``Resource.read()`` returning
        (say) a ``dict`` went out to the client as JSON; now it raises inside
        the ``try``, where ``except (MCPError, ResourceError): raise`` does
        *not* catch a ``TypeError``, so it falls through to the generic
        wrapper. That is what turns a shape change into an opaque "Error
        reading resource <uri>" instead of a silently different payload, and
        it is the half of the rework this file has to pin, so it is driven
        with a resource built to trip it.

        A purpose-built one, because no resource this server registers can
        reach the check — see the sweep below for why. Reads *through*
        ``server.mcp.read_resource``, not ``resource.read()``, because the
        check lives in the caller.
        """
        from mcp.server.mcpserver.exceptions import UnexpectedResourceError
        from mcp.server.mcpserver.resources.base import Resource

        uri = "zim://seam-audit-nonstr"
        payload = {"seam_audit": "payload-must-not-reach-the-client"}

        class _DictResource(Resource):
            async def read(self) -> Any:
                return payload

        server = _server(tmp_path)
        server.mcp._resource_manager.add_resource(
            _DictResource(
                uri=uri,
                name="seam_audit_nonstr",
                mime_type="application/json",
            )
        )

        with pytest.raises(UnexpectedResourceError) as excinfo:
            await server.mcp.read_resource(uri)

        assert isinstance(excinfo.value.__cause__, TypeError), excinfo.value.__cause__
        # ...and the client is told nothing but the URI. Asserted as equality
        # rather than as the payload's absence, because an absence check here
        # cannot fail: this line read `assert "not a string" not in
        # str(excinfo.value)` against a fixture returning {"not": "a string"},
        # whose repr is {'not': 'a string'} — the space-separated substring it
        # looked for is not a substring of any rendering of that dict, so the
        # docstring's headline claim was unchecked. Measured: appending the
        # cause to the SDK's message (`f"...{uri}: {exc}"`) left the old line
        # green; equality reds on that mutation and on any other addition,
        # including a `str | bytes` TypeError that names the value it rejected.
        assert str(excinfo.value) == f"Error reading resource {uri}", (
            f"read_resource's message must carry the URI and nothing else, "
            f"but it is {str(excinfo.value)!r} (payload was {payload!r})"
        )

    @pytest.mark.asyncio
    async def test_registered_resource_functions_return_str_themselves(
        self, tmp_path: Path
    ) -> None:
        """Each static resource function returns ``str`` *before* the SDK helps.

        This used to sweep the static list through ``read_resource`` and
        assert ``isinstance(content, (str, bytes))``, which cannot fail:
        every static resource here is a ``FunctionResource``, and
        ``FunctionResource.read()`` JSON-encodes anything that is not already
        ``str``/``bytes`` (``pydantic_core.to_json(result, fallback=str,
        indent=2)``) before ``read_resource`` ever type-checks it. Verified:
        making ``list_zim_files_resource`` return ``{"mutant": True}`` left
        that sweep green.

        So the property worth holding is the repo's, one layer lower — the
        function's own return type. ``zim://files`` builds its payload with
        ``json.dumps(..., indent=2, ensure_ascii=False)``; falling back to
        the SDK's encoder would keep the suite green while changing the bytes
        on the wire (different escaping, different key handling). The
        ``FunctionResource`` assertion is the other half: if a ``Resource``
        subclass is ever registered statically, its ``read()`` *can* reach the
        type check above, and this reds to say so.
        """
        import inspect

        from mcp.server.mcpserver.resources import FunctionResource

        server = _server(tmp_path)
        static = await server.mcp.list_resources()
        assert static, "expected at least one static resource"

        registry = server.mcp._resource_manager._resources
        for descriptor in static:
            resource = registry[str(descriptor.uri)]
            assert isinstance(resource, FunctionResource), (
                f"{descriptor.uri} is a {type(resource).__name__}, not a "
                "FunctionResource: its read() reaches 2.1.1's str|bytes check "
                "directly, so it needs the treatment ZimEntryResource gets."
            )
            fn = resource.fn
            raw = await fn() if inspect.iscoroutinefunction(fn) else fn()
            assert isinstance(raw, (str, bytes)), (
                f"{descriptor.uri} returns {type(raw).__name__}; the SDK will "
                "JSON-encode it with pydantic_core.to_json, silently changing "
                "the bytes this resource puts on the wire."
            )

    @pytest.mark.asyncio
    async def test_entry_template_read_survives_the_type_check(
        self, basic_test_zim_files: dict[str, Any]
    ) -> None:
        """The templated entry resource is the one that returns ``bytes``.

        ``ZimEntryResource.read()`` returns ``str`` for text and ``bytes`` for
        binary, and it is reached through the template rather than the static
        list, so the loop above never touches it. Driven through
        ``read_resource`` (not ``resource.read()``) because that is where
        2.1.1's ``str | bytes`` check lives.
        """
        archive = basic_test_zim_files["withns"]
        if archive is None:
            pytest.skip("ZIM test corpus not present")

        server = _server(archive.parent)
        name = archive.stem
        contents = await server.mcp.read_resource(f"zim://{name}/entry/A%2Fmain.html")
        items = list(contents)
        assert items, "expected the entry read to return content"
        for item in items:
            assert isinstance(item.content, (str, bytes))


class TestSseTransportSeam:
    """#3336's method guard on the SSE message endpoint.

    ``--transport sse`` is deprecated but still shipped, and the server
    reaches it through ``self.mcp.run(transport="sse", ...)`` — which is why
    an earlier audit that grepped for ``sse_app`` concluded #3336 was a no-op
    here. ``tests/live/test_live_sse.py`` covers this against a real spawned
    process, but the live marker is deselected by ``addopts`` and no workflow
    passes ``-m live``, so nothing in CI was watching a transport whose patch
    releases Dependabot may now propose. This builds the app through the same
    ``sse_app`` call ``run_sse_async`` makes, with the arguments ``server.py``
    hands ``mcp.run``, and drives it in-process — so it runs on every PR.
    """

    @staticmethod
    def _sse_app(tmp_path: Path) -> Any:
        server = _server(tmp_path)
        return server.mcp.sse_app(
            host=server.config.host,
            transport_security=server._transport_security,
        )

    @pytest.mark.asyncio
    async def test_message_endpoint_answers_405_not_a_content_type_error(
        self, tmp_path: Path
    ) -> None:
        """``GET /messages/`` must blame the verb, not the headers.

        Before #3336 a ``GET`` fell straight through into the POST handler and
        came back ``400 Invalid Content-Type header`` — a status that sends
        the caller to fix a header when the real problem is the method. The
        guard is the first statement in ``handle_post_message``, ahead of
        transport-security validation, so this reaches it without a Host
        allow-list entry.
        """
        transport = httpx.ASGITransport(app=self._sse_app(tmp_path))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1"
        ) as client:
            response = await client.get("/messages/")

        assert response.status_code == 405, response.text
        assert "POST" in response.headers.get("allow", "")

    @pytest.mark.asyncio
    async def test_message_endpoint_caps_the_request_body(self, tmp_path: Path) -> None:
        """#3336 moved ``RequestBodyLimitMiddleware`` with the constant.

        ``SseServerTransport.__init__`` wraps its post handler in that
        middleware, so the SSE endpoint refuses an over-cap body before any
        of its own code runs. The first version of this asserted
        ``callable(RequestBodyLimitMiddleware)`` after importing it — true of
        any class, so the import was the whole test and the docstring's "the
        SSE app uses it" went unchecked. This drives the app instead: nothing
        in this repo imports the middleware, so its module home is not a seam
        we depend on; the cap being enforced on that route is.

        The under-cap control is what makes the 413 mean something: it comes
        back 421 from transport-security's Host check, which sits *behind*
        the body limit — so the 413 is the cap answering, not a blanket
        rejection of everything posted here.
        """
        from mcp.server.transport_security import DEFAULT_MAX_REQUEST_BODY_SIZE

        transport = httpx.ASGITransport(app=self._sse_app(tmp_path))
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1"
        ) as client:
            oversized = await client.post(
                "/messages/",
                content=b"x" * (DEFAULT_MAX_REQUEST_BODY_SIZE + 1),
                headers={"content-type": "application/json"},
            )
            small = await client.post(
                "/messages/",
                content=b"{}",
                headers={"content-type": "application/json"},
            )

        assert oversized.status_code == 413, oversized.text
        assert small.status_code != 413, small.text


_LEGACY_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "seam-audit", "version": "0"},
    },
}


class TestSessionLifecycleSeam:
    """2.2's handshake-era session lifecycle (upstream #3395, issue #453).

    On 2.1.1 a session left the manager's table only when the process exited:
    a DELETE terminated it in place, a refused opening request left it
    behind, and the app builder took no ``session_idle_timeout``. The gates in
    ``http_app`` were written against that. Their docstrings now say nothing
    accumulates and only churn is saved, and the deployment guide quotes the
    SDK's limits; these pin both claims to the resolved SDK.

    Every assertion on the table sits inside the ``TestClient`` block: leaving
    it runs the lifespan shutdown, which empties the table on any version.
    """

    @staticmethod
    def _http_server(tmp_path: Path) -> OpenZimMcpServer:
        return OpenZimMcpServer(
            OpenZimMcpConfig(allowed_directories=[str(tmp_path)], transport="http")
        )

    @classmethod
    def _production_app(cls, tmp_path: Path) -> tuple[OpenZimMcpServer, Any]:
        server = cls._http_server(tmp_path)
        box: dict[str, Any] = {}
        serve_streamable_http(
            server, runner=lambda app, host, port: box.update(app=app)
        )
        return server, box["app"]

    def test_complete_sessions_leave_the_table_empty(self, tmp_path: Path) -> None:
        """The #453 churn, through the production-wired app.

        ``initialize``, ``notifications/initialized``, ``tools/list``,
        ``DELETE``: the sequence Open WebUI runs per chat request, per MCP
        server. On 2.1.1 each run left one entry (about 4 KB) until restart.
        """
        server, app = self._production_app(tmp_path)
        table = server.mcp.session_manager._server_instances
        with TestClient(app, base_url="http://127.0.0.1") as client:
            for _ in range(25):
                opened = client.post("/mcp", json=_INITIALIZE, headers=_LEGACY_HEADERS)
                assert opened.status_code == 200, opened.text
                session = {
                    **_LEGACY_HEADERS,
                    "Mcp-Session-Id": opened.headers["mcp-session-id"],
                }
                initialized = client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    headers=session,
                )
                assert initialized.status_code == 202, initialized.text
                listed = client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    headers=session,
                )
                assert listed.status_code == 200, listed.text
                # The session was really registered, so the empty table below
                # is the DELETE's doing.
                assert session["Mcp-Session-Id"] in table
                ended = client.delete("/mcp", headers=session)
                assert ended.status_code == 200, ended.text
            assert table == {}

    def test_a_refused_opening_request_is_discarded(
        self, tmp_path: Path, minted_transports: list[object]
    ) -> None:
        """The bare SDK app, no gates: it mints for a refusal, then lets go.

        This is the property that turned the gates' leak into churn. Should a
        release regress it, the gates become load-bearing again and their
        docstrings wrong, so it fails here first.
        """
        server = self._http_server(tmp_path)
        app = server.mcp.streamable_http_app(
            host=server.config.host, transport_security=server._transport_security
        )
        table = server.mcp.session_manager._server_instances
        with TestClient(app, base_url="http://127.0.0.1") as client:
            refused = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                headers=_LEGACY_HEADERS,
            )
            hostile = client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
                headers={**_LEGACY_HEADERS, "Origin": "http://evil.example"},
            )
            assert refused.status_code == 400, refused.text
            assert hostile.status_code == 403, hostile.text
            # Both really did mint: an empty table is the SDK discarding them,
            # not the requests never reaching the session code.
            assert len(minted_transports) == 2
            assert table == {}

    def test_the_sdk_limits_are_the_ones_we_document(self, tmp_path: Path) -> None:
        """``http_app`` takes the SDK's defaults; the deployment guide quotes them.

        A minor that changed either default would change what the guide
        promises without any diff here, so the numbers are pinned on the
        manager ``serve_streamable_http`` actually builds.
        """
        server, _app = self._production_app(tmp_path)
        manager = server.mcp.session_manager
        assert manager.session_idle_timeout == 30 * 60
        assert manager.max_sessions == 10_000


class TestDeclaredRangeIsTheTestedRange:
    """The lockfile must not sit below the top minor of the declared cap."""

    @staticmethod
    def _declared_specifier() -> Any:
        """``mcp``'s specifier, parsed rather than pattern-matched.

        The first version of this read ``"mcp\\[cli\\]>=[\\d.]+,<(\\d+)\\.(\\d+)"``
        out of the raw file and reported "mcp requirement not found in
        pyproject.toml" for anything it did not recognise — so writing the cap
        as ``<2.2.0`` would have failed both range gates with an error naming
        the wrong problem.
        """
        data = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
                encoding="utf-8"
            )
        )
        for raw in data["project"]["dependencies"]:
            requirement = Requirement(raw)
            if requirement.name == "mcp":
                return requirement.specifier
        raise AssertionError("no mcp requirement in pyproject's dependencies")

    @staticmethod
    def _locked_version(name: str) -> str:
        """``name``'s version as pinned in ``uv.lock``."""
        lock = tomllib.loads(
            (Path(__file__).resolve().parents[1] / "uv.lock").read_text(
                encoding="utf-8"
            )
        )
        for package in lock["package"]:
            if package["name"] == name:
                return str(package["version"])
        raise AssertionError(f"{name} not found in uv.lock")

    def test_locked_mcp_is_in_the_caps_top_minor(self) -> None:
        """Guard against a widened cap that ships an untested wheel.

        ``uv lock`` keeps an already-resolved version when a bound is widened,
        so raising the ceiling without ``--upgrade-package mcp`` produces a
        green PR that advertises a new range while CI goes on testing the old
        floor — and only a fresh ``pip install`` finds out. (That is not
        hypothetical: plain ``uv lock`` on the ``<2.2`` widening left the
        lockfile on 2.0.0.) This asserts the *locked* version sits in the
        highest minor series the cap admits, so that PR fails here instead.

        Read out of ``uv.lock``, not out of ``importlib.metadata``: every
        workflow installs with ``uv sync --locked``, so the lockfile is what
        CI actually exercises, and it is the file the failure message tells
        you to regenerate. Asserting the interpreter's own site-packages
        instead would red on a contributor's stale venv for a reason the
        message misdescribes, and could not see a lockfile CI would install
        differently.

        A major-boundary cap (``<3.0``) used to ``pytest.skip`` here, on the
        grounds that which minor series such a range admits at the top is not
        knowable offline. That is true and it was the wrong answer: the skip
        fired exactly in the case the gate exists for — ``>=2.1.0,<3.0``
        without ``--upgrade-package mcp`` is the same trap one bound wider —
        and announced itself as a single ``s`` in the CI log. It fails now,
        because the policy this whole audit rests on (pyproject's requirement
        comment, and the docs sentence about holding ``mcp`` to one series) is
        one audited minor series at a time. Widening past that is a decision
        someone has to take here, in this test, rather than inherit from a
        skip.
        """
        declared = self._declared_specifier()
        upper = [s for s in declared if s.operator in ("<", "<=")]
        assert len(upper) == 1, f"expected exactly one upper bound, got {upper}"
        cap = Version(upper[0].version)
        locked = Version(self._locked_version("mcp"))

        assert locked in declared, (
            f"uv.lock pins mcp {locked}, which pyproject's mcp{declared} does "
            "not admit — CI is testing a wheel no fresh install can get. Run "
            "`uv lock --upgrade-package mcp`."
        )
        assert not (upper[0].operator == "<" and cap.minor == 0), (
            f"pyproject caps mcp at the major boundary {upper[0]}, which "
            "admits every minor series below it; which one a fresh install "
            "resolves cannot be read out of the lockfile, so this gate can no "
            "longer tell a tested wheel from an untested one. This audit pins "
            "one minor series at a time (see the module docstring and "
            "pyproject's requirement comment). Either declare a minor cap "
            f"(`<{cap.major - 1}.N`), or re-audit the seams against the new "
            "major and rewrite this gate deliberately."
        )
        if upper[0].operator == "<":
            top = (cap.major, cap.minor - 1)
        else:
            top = (cap.major, cap.minor)

        assert (locked.major, locked.minor) == top, (
            f"pyproject admits mcp{declared}, so the top "
            f"series is {top[0]}.{top[1]}.x, but uv.lock pins {locked}. Run "
            "`uv lock --upgrade-package mcp` so CI tests the wheel a fresh "
            "install would get."
        )
