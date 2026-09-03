"""Seam audit for the ``mcp[cli]>=2.1.0,<2.2`` range.

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

from openzim_mcp.config import OpenZimMcpConfig
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

    def test_sessionless_gate_mirrors_the_sdk_cap(self) -> None:
        """The gate buffers a sessionless POST under *the SDK's* cap.

        ``SessionlessRequestGateMiddleware`` replays a buffered body into the
        SDK, so its ceiling has to be the SDK's own or the gate becomes the
        limit nobody documented.
        """
        from mcp.server.transport_security import DEFAULT_MAX_REQUEST_BODY_SIZE

        from openzim_mcp.http_app import SessionlessRequestGateMiddleware

        async def _app(scope: Any, receive: Any, send: Any) -> None:  # pragma: no cover
            raise AssertionError("not called")

        gate = SessionlessRequestGateMiddleware(_app)
        assert gate._max_body_size == DEFAULT_MAX_REQUEST_BODY_SIZE

    def test_body_limit_middleware_lives_beside_it(self) -> None:
        """#3336 moved the middleware with the constant; the SSE app uses it."""
        from mcp.server.transport_security import RequestBodyLimitMiddleware

        assert callable(RequestBodyLimitMiddleware)

    def test_gate_sources_the_cap_from_its_canonical_home(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The gate must read ``transport_security``, not the re-export.

        Both spellings resolve to the same 4 MiB int inside this range, so a
        plain value assertion cannot tell them apart and the import move was
        unobservable — the whole floor decision rested on an edit no test
        would have noticed reverting.

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
    async def test_every_registered_resource_reads_str_or_bytes(
        self, tmp_path: Path
    ) -> None:
        """2.1.1 raises ``TypeError`` on anything else, wrapped as a crash.

        The check is new in 2.1.1, so a resource returning (say) a ``dict``
        went out as JSON under 2.0.0 and becomes a generic
        "Error reading resource" now. Every static resource this server
        publishes is read here to show none of them do that.
        """
        server = _server(tmp_path)
        static = await server.mcp.list_resources()
        assert static, "expected at least one static resource"
        for descriptor in static:
            contents = await server.mcp.read_resource(str(descriptor.uri))
            for item in contents:
                assert isinstance(item.content, (str, bytes)), descriptor.uri

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
    releases Dependabot may now propose. This drives the same app object
    ``run_sse_async`` builds, in-process, so it runs on every PR.
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
        """
        upper = [s for s in self._declared_specifier() if s.operator in ("<", "<=")]
        assert len(upper) == 1, f"expected exactly one upper bound, got {upper}"
        cap = Version(upper[0].version)
        if upper[0].operator == "<" and cap.minor == 0:
            pytest.skip(
                "cap is a major boundary; the top minor it admits is not "
                "knowable without querying the index"
            )
        if upper[0].operator == "<":
            top = (cap.major, cap.minor - 1)
        else:
            top = (cap.major, cap.minor)

        locked = Version(self._locked_version("mcp"))
        assert (locked.major, locked.minor) == top, (
            f"pyproject admits mcp{self._declared_specifier()}, so the top "
            f"series is {top[0]}.{top[1]}.x, but uv.lock pins {locked}. Run "
            "`uv lock --upgrade-package mcp` so CI tests the wheel a fresh "
            "install would get."
        )
