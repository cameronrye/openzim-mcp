"""``OPENZIM_MCP_STATELESS_HTTP`` — handshake-era clients without sessions (#452).

By default a handshake-era client (one that opens with ``initialize``) gets a
server-issued ``Mcp-Session-Id`` and a GET stream held open for the session's
lifetime, which rules out replicas without session affinity and makes every
proxy hop carry a long-lived SSE stream. The SDK can serve those clients
statelessly, but forcing its flag alone broke them: the sessionless gate
answered their sessionless follow-ups ``400 Missing session ID``.

``TestTheSetting`` checks the config model, and that stdio and sse start
exactly as they would without the setting; the tripwire at the end reads the
package's source against the SDK's API. Everything else drives the app
``serve_streamable_http`` hands to uvicorn — session manager, gates, auth —
because the behaviour lives in how the setting, the SDK's app builder and the
gate agree, which no stub can show.

Nothing here waits on the wall clock. A request whose answer might never end
(a GET stream, a ``subscriptions/listen`` stream, a call the client walks away
from) is driven straight through the ASGI app, and its client hangs up on an
event — the answer completing, a stream starting, an acknowledgement
arriving, a tool starting. Each wait has a ceiling a passing run never comes
near, which only bounds how long a regression to a held stream takes to fail.
"""

from __future__ import annotations

import ast
import contextlib
import importlib
import json
import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import FunctionType
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    Iterator,
    List,
    Mapping,
    Optional,
    Set,
    Tuple,
)
from unittest.mock import MagicMock
from uuid import uuid4

import anyio
import pytest
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS
from starlette.testclient import TestClient

from openzim_mcp import http_app
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.http_app import serve_streamable_http
from openzim_mcp.server import OpenZimMcpServer

REPO = Path(__file__).resolve().parents[1]
DEPLOYMENT_DOC = REPO / "website/src/content/docs/http-and-docker-deployment.mdx"

HANDSHAKE_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
# What a 2025-06-18-or-later handshake-era client sends on every request after
# ``initialize``. A 2025-03-26 client sends ``HANDSHAKE_HEADERS`` alone.
NEGOTIATED = {**HANDSHAKE_HEADERS, "MCP-Protocol-Version": "2025-11-25"}

# Every way a request can be handshake-era: no ``MCP-Protocol-Version`` at all
# — what a 2025-03-26 client sends after ``initialize``, and what a bare curl
# sends — or any revision before 2026-07-28, read from the SDK so a new one is
# covered the day it lands.
HANDSHAKE_ERAS: List[Optional[str]] = [None, *HANDSHAKE_PROTOCOL_VERSIONS]
HANDSHAKE_ERA_IDS = ["no-version-header", *HANDSHAKE_PROTOCOL_VERSIONS]

INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized"}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
TOOLS_CALL = {
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {"name": "zim_health", "arguments": {}},
}

MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}

# The ceiling on any wait in this module. A passing run ends every one of
# them on an event within milliseconds; this only bounds how long a
# regression — a stream held open, a cancel that never lands — takes to fail.
CEILING_SECONDS = 30.0


def _initialize(protocol_version: str = "2025-11-25") -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": protocol_version,
            "capabilities": {},
            "clientInfo": {"name": "stateless-test", "version": "0"},
        },
    }


def _naming_era(headers: Dict[str, str], version: Optional[str]) -> Dict[str, str]:
    """``headers``, plus an ``MCP-Protocol-Version`` unless ``version`` is None."""
    if version is None:
        return dict(headers)
    return {**headers, "mcp-protocol-version": version}


def _server(tmp_path: Path, **overrides: Any) -> OpenZimMcpServer:
    """An HTTP server over a directory holding one stub archive."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "sample.zim").write_bytes(b"placeholder")
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        transport="http",
        tool_mode="advanced",
        **overrides,
    )
    return OpenZimMcpServer(config)


def _build_client(
    tmp_path: Path, **overrides: Any
) -> Tuple[TestClient, OpenZimMcpServer]:
    """The production-wired app over a directory holding one stub archive."""
    server = _server(tmp_path, **overrides)
    captured: Dict[str, Any] = {}
    serve_streamable_http(
        server, runner=lambda app, host, port: captured.update(app=app)
    )
    # Loopback base URL: ``testserver`` would be refused by the DNS-rebinding
    # gate (421) before the request reached the layers under test.
    return TestClient(captured["app"], base_url="http://127.0.0.1"), server


def _sessions(server: OpenZimMcpServer) -> Dict[str, Any]:
    """The SDK's session table — what a stateless server must never fill."""
    return server.mcp.session_manager._server_instances


def _sse_payload(text: str) -> Optional[Dict[str, Any]]:
    """The JSON-RPC payload inside the SDK's one-event SSE response."""
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :])
    return None


@dataclass
class _Exchange:
    """What a client driving the app directly saw, and whether it ended."""

    status: Optional[int] = None
    headers: Dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    # The last body chunk was sent: the answer is whole.
    complete: bool = False
    # The app returned inside the ceiling, rather than being cut off by it.
    returned: bool = False

    @property
    def is_event_stream(self) -> bool:
        return self.headers.get("content-type", "").startswith("text/event-stream")


def _answered(exchange: _Exchange) -> bool:
    """Hang up once the answer is whole — or, for a stream, once it starts.

    A real client reads a refusal to the end, and closes an event stream it
    did not want as soon as it sees one; a regression to a held stream then
    fails on its status instead of hanging the run.
    """
    return exchange.complete or exchange.is_event_stream


async def _asgi_exchange(
    client: TestClient,
    method: str,
    headers: Mapping[str, str],
    body: bytes,
    until: Callable[[_Exchange], bool],
    hang_up_on: Optional[anyio.Event],
) -> _Exchange:
    """One request straight through the app, on the portal's event loop.

    The client hangs up when ``until`` first holds for what it has seen, or
    when ``hang_up_on`` is set, whichever is given. Runs where the session
    manager lives, so this is the production middleware stack, not a stub.
    """
    exchange = _Exchange()
    hang_up = hang_up_on if hang_up_on is not None else anyio.Event()
    request_sent = False

    async def receive() -> Dict[str, Any]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await hang_up.wait()
        return {"type": "http.disconnect"}

    async def send(message: Dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            exchange.status = message["status"]
            exchange.headers = {
                name.decode().lower(): value.decode()
                for name, value in message.get("headers", [])
            }
        elif message["type"] == "http.response.body":
            exchange.body += message.get("body", b"")
            if not message.get("more_body", False):
                exchange.complete = True
        if hang_up_on is None and until(exchange):
            hang_up.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "root_path": "",
        "query_string": b"",
        "headers": [
            (name.lower().encode(), value.encode())
            for name, value in {"host": "127.0.0.1", **headers}.items()
        ],
        "client": ("127.0.0.1", 45678),
        "server": ["127.0.0.1", 80],
        "extensions": {"http.response.debug": {}},
        # The lifespan state ``TestClient`` hands every request it makes.
        "state": client.app_state.copy(),
    }
    with anyio.move_on_after(CEILING_SECONDS) as ceiling:
        await client.app(scope, receive, send)  # type: ignore[operator]
    exchange.returned = not ceiling.cancelled_caught
    return exchange


def _drive(
    client: TestClient,
    method: str,
    headers: Mapping[str, str],
    body: bytes = b"",
    *,
    until: Callable[[_Exchange], bool] = _answered,
    hang_up_on: Optional[anyio.Event] = None,
) -> _Exchange:
    """Send one request through the production stack; see ``_asgi_exchange``.

    ``TestClient`` waits for a response to complete, and a GET stream or a
    ``subscriptions/listen`` stream never completes on its own, so a request
    that might be answered with one is driven directly instead.
    """
    return client.portal.call(  # type: ignore[union-attr]
        _asgi_exchange, client, method, headers, body, until, hang_up_on
    )


def _assert_refused_by_the_gate(exchange: _Exchange) -> None:
    """The stateless gate's answer, told apart from every SDK answer.

    The SDK's own 405s carry an empty body (2026-07-28 path), no ``Allow``
    header (a stateless DELETE) or ``Allow: GET, POST, DELETE`` (the rest),
    and a GET it lets through is a ``200`` event stream.
    """
    assert exchange.returned, "the request was held open until the ceiling"
    assert exchange.status == 405, (exchange.status, exchange.headers, exchange.body)
    assert exchange.headers.get("allow") == "POST", exchange.headers
    assert "mcp-session-id" not in exchange.headers, exchange.headers
    error = json.loads(exchange.body)["error"]
    assert error["code"] == -32600, error
    assert error["message"].startswith("Method Not Allowed"), error


@contextlib.contextmanager
def _collected(logger_name: str) -> Iterator[List[logging.LogRecord]]:
    """Every record ``logger_name`` passes to its handlers while the block runs.

    A handler of our own on the named logger, because ``OpenZimMcpServer``
    construction runs ``logging.basicConfig(force=True)``, which drops
    caplog's root handler. Levels are left as the process has them: a record
    the logger's own filters drop never reaches this handler, which is what
    the log-noise tests rely on.
    """
    records: List[logging.LogRecord] = []

    class _Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    target = logging.getLogger(logger_name)
    handler = _Collect(level=logging.DEBUG)
    target.addHandler(handler)
    try:
        yield records
    finally:
        target.removeHandler(handler)


class TestTheSetting:
    """The knob itself: name, default, and what it changes about the config."""

    def test_default_is_off(self, tmp_path: Path) -> None:
        assert (
            OpenZimMcpConfig(allowed_directories=[str(tmp_path)]).stateless_http
            is False
        )

    def test_env_var_turns_it_on(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENZIM_MCP_STATELESS_HTTP", "1")
        assert (
            OpenZimMcpConfig(allowed_directories=[str(tmp_path)]).stateless_http is True
        )

    def test_config_hash_tells_the_modes_apart(self, tmp_path: Path) -> None:
        """The hash fingerprints the settings that change what a client sees.

        This one changes the wire protocol a handshake-era client meets — a
        session id, or none — so two configurations that differ only here
        must not share a fingerprint.
        """
        base = OpenZimMcpConfig(allowed_directories=[str(tmp_path)])
        stateless = OpenZimMcpConfig(
            allowed_directories=[str(tmp_path)], stateless_http=True
        )
        assert base.get_config_hash() != stateless.get_config_hash()

    @pytest.mark.parametrize("transport", ["stdio", "sse"])
    def test_other_transports_accept_it_and_start_unchanged(
        self, tmp_path: Path, transport: str
    ) -> None:
        """Like every HTTP-only setting, it is no startup error elsewhere, and inert.

        ``allowed_hosts``, ``cors_origins`` and ``subscriptions_enabled`` are
        all honoured on ``http`` only and ignored otherwise, so an env file
        shared by a stdio launch and an HTTP service keeps working. Ignored,
        not merely accepted: the transport is started with exactly the
        arguments it gets with the setting off.
        """
        starts = []
        for stateless in (False, True):
            config = OpenZimMcpConfig(
                allowed_directories=[str(tmp_path)],
                transport=transport,  # type: ignore[arg-type]
                stateless_http=stateless,
            )
            server = OpenZimMcpServer(config)
            server.mcp.run = MagicMock()  # type: ignore[method-assign]
            server.run()
            server.mcp.run.assert_called_once()
            starts.append(server.mcp.run.call_args)
        assert starts[0] == starts[1], starts


class TestHandshakeEraWithoutSessions:
    """The issue's sequence, served with the setting on."""

    def test_the_sdk_builds_its_stateless_manager(self, tmp_path: Path) -> None:
        _on, on_server = _build_client(tmp_path / "on", stateless_http=True)
        _off, off_server = _build_client(tmp_path / "off")
        assert on_server.mcp.session_manager.stateless is True
        assert off_server.mcp.session_manager.stateless is False

    def test_full_sequence_never_issues_a_session(self, tmp_path: Path) -> None:
        """connect → tools/list → tools/call, every request standing alone.

        This is the sequence Open WebUI's client (mcp 1.27.2) sends: after
        ``initialize`` it carries the negotiated ``MCP-Protocol-Version`` and,
        with no session id to echo, nothing else.
        """
        client, server = _build_client(tmp_path, stateless_http=True)
        with client:
            opened = client.post("/mcp", json=_initialize(), headers=HANDSHAKE_HEADERS)
            assert opened.status_code == 200, opened.text
            assert "mcp-session-id" not in opened.headers
            payload = _sse_payload(opened.text)
            assert payload is not None, opened.text
            assert payload["result"]["protocolVersion"] == "2025-11-25"
            assert payload["result"]["serverInfo"]["name"] == "openzim-mcp"

            initialized = client.post("/mcp", json=INITIALIZED, headers=NEGOTIATED)
            assert initialized.status_code == 202, initialized.text
            assert "mcp-session-id" not in initialized.headers

            listed = client.post("/mcp", json=TOOLS_LIST, headers=NEGOTIATED)
            assert listed.status_code == 200, listed.text
            assert "mcp-session-id" not in listed.headers
            payload = _sse_payload(listed.text)
            assert payload is not None, listed.text
            names = {tool["name"] for tool in payload["result"]["tools"]}
            assert "zim_health" in names, names

            called = client.post("/mcp", json=TOOLS_CALL, headers=NEGOTIATED)
            assert called.status_code == 200, called.text
            assert "mcp-session-id" not in called.headers
            payload = _sse_payload(called.text)
            assert payload is not None, called.text
            assert payload["id"] == 3
            assert payload["result"]["isError"] is False, payload
            assert "health" in json.loads(payload["result"]["content"][0]["text"])

            assert _sessions(server) == {}

    def test_a_2025_03_26_client_needs_no_protocol_header(self, tmp_path: Path) -> None:
        """The oldest handshake revision sends no ``MCP-Protocol-Version`` at all.

        2025-03-26 predates the header, so its follow-ups carry neither it nor
        (here) a session id. They reach the SDK's stateless path all the same,
        which seeds the connection with the spec's default revision — so the
        gate must not read a missing header as a request it has to refuse.
        """
        client, server = _build_client(tmp_path, stateless_http=True)
        with client:
            opened = client.post(
                "/mcp", json=_initialize("2025-03-26"), headers=HANDSHAKE_HEADERS
            )
            payload = _sse_payload(opened.text)
            assert payload is not None, opened.text
            assert payload["result"]["protocolVersion"] == "2025-03-26"
            answers = [opened]
            for message in (INITIALIZED, TOOLS_LIST, TOOLS_CALL):
                answers.append(
                    client.post("/mcp", json=message, headers=HANDSHAKE_HEADERS)
                )

            statuses = [answer.status_code for answer in answers]
            assert statuses == [200, 202, 200, 200], [a.text for a in answers]
            assert not any("mcp-session-id" in answer.headers for answer in answers)
            called = _sse_payload(answers[-1].text)
            assert called is not None and called["result"]["isError"] is False
            assert _sessions(server) == {}

    def test_a_request_needs_no_handshake_on_the_replica_answering_it(
        self, tmp_path: Path
    ) -> None:
        """What makes affinity unnecessary: no request depends on an earlier one.

        A replica that never saw this client's ``initialize`` answers its
        ``tools/list`` all the same.
        """
        client, server = _build_client(tmp_path, stateless_http=True)
        with client:
            listed = client.post("/mcp", json=TOOLS_LIST, headers=NEGOTIATED)
            assert listed.status_code == 200, listed.text
            payload = _sse_payload(listed.text)
            assert payload is not None and payload["result"]["tools"], listed.text
            assert _sessions(server) == {}

    def test_a_session_id_from_a_stateful_replica_is_ignored_on_a_post(
        self, tmp_path: Path
    ) -> None:
        """A client mid-session when its replica switched mode keeps working.

        The id names nothing here, and the stateless path never looks it up,
        so the request is served instead of answered ``404 Session not
        found``.
        """
        client, server = _build_client(tmp_path, stateless_http=True)
        with client:
            listed = client.post(
                "/mcp",
                json=TOOLS_LIST,
                headers={**NEGOTIATED, "Mcp-Session-Id": uuid4().hex},
            )
            assert listed.status_code == 200, listed.text
            assert "mcp-session-id" not in listed.headers
            assert _sessions(server) == {}

    def test_post_bodies_reach_the_sdk_unread(self, tmp_path: Path) -> None:
        """Nothing is minted, so the gate has nothing to classify a body for.

        An undecodable body gets the SDK's own parse error rather than the
        stateful gate's ``Missing session ID``.
        """
        client, _server = _build_client(tmp_path, stateless_http=True)
        with client:
            response = client.post("/mcp", content=b"{not json", headers=NEGOTIATED)
            assert response.status_code == 400, response.text
            assert response.json()["error"]["code"] == -32700, response.text


class TestEveryOtherMethodIsRefused:
    """GET, DELETE and the rest: answered ``405``, ``Allow: POST``, by the gate."""

    @pytest.mark.parametrize("method", ["GET", "DELETE"])
    @pytest.mark.parametrize(
        "session_id", [None, uuid4().hex], ids=["no-session-id", "session-id"]
    )
    @pytest.mark.parametrize("version", HANDSHAKE_ERAS, ids=HANDSHAKE_ERA_IDS)
    def test_get_and_delete_are_refused_rather_than_served(
        self,
        tmp_path: Path,
        method: str,
        session_id: Optional[str],
        version: Optional[str],
    ) -> None:
        """No session means no stream to open and nothing to end.

        Left to the SDK, a stateless GET is answered ``200 text/event-stream``
        and held, empty, until the client hangs up — the long-lived stream
        through every proxy hop this mode exists to remove. A client that
        opens it regardless of session (the TypeScript SDK does, after
        ``notifications/initialized``) treats ``405`` as "no stream here". A
        stateless DELETE gets the SDK's ``405`` without the ``Allow`` header
        RFC 9110 requires. An ``Mcp-Session-Id`` — say, one a stateful
        replica issued before this one switched mode — changes neither, and
        nor does which handshake revision the request names, or that it
        names none: era routing reads a missing header as the handshake era.
        """
        client, server = _build_client(tmp_path, stateless_http=True)
        headers = _naming_era({"accept": "text/event-stream"}, version)
        if session_id is not None:
            headers["mcp-session-id"] = session_id
        with client:
            exchange = _drive(client, method, headers)
            assert _sessions(server) == {}
        _assert_refused_by_the_gate(exchange)

    @pytest.mark.parametrize("method", ["PUT", "PATCH", "HEAD", "OPTIONS"])
    @pytest.mark.parametrize("version", HANDSHAKE_ERAS, ids=HANDSHAKE_ERA_IDS)
    def test_the_rest_are_refused_with_the_same_allow(
        self, tmp_path: Path, method: str, version: Optional[str]
    ) -> None:
        """``Allow`` must list what the endpoint supports *here*: POST alone.

        Passed through, these would reach the SDK's catch-all, which answers
        ``Allow: GET, POST, DELETE`` — two of them refused on this server.
        OPTIONS reaches the gate only because no CORS origins are configured;
        with them, a preflight is the CORS layer's to answer. (HEAD's body is
        the server's to drop on the wire; the app's answer is the same 405.)
        """
        client, _server = _build_client(tmp_path, stateless_http=True)
        with client:
            exchange = _drive(client, method, _naming_era(HANDSHAKE_HEADERS, version))
        _assert_refused_by_the_gate(exchange)

    @pytest.mark.parametrize(
        ("path", "status"),
        [
            ("/healthz", 200),
            ("/readyz", 200),
            ("/not-a-route", 404),
            # Next to the MCP route rather than on it: the gate must match
            # the path exactly, or a typo is blamed on the method.
            ("/mcp/extra", 404),
            ("/mcpx", 404),
        ],
    )
    def test_only_the_mcp_route_is_gated(
        self, tmp_path: Path, path: str, status: int
    ) -> None:
        """Probes and unrouted paths keep Starlette's answers.

        The docs' own Kubernetes example runs liveness and readiness probes
        against a stateless Deployment: a 405 here would take every replica
        out of rotation.
        """
        client, _server = _build_client(tmp_path, stateless_http=True)
        with client:
            response = client.get(path)
        assert response.status_code == status, response.text


class TestTheDocumentedModeCheck:
    """The deployment docs' way to tell a replica's mode from outside."""

    @pytest.mark.parametrize(
        ("overrides", "status"),
        [({"stateless_http": True}, 405), ({}, 400)],
        ids=["stateless", "default"],
    )
    def test_a_bare_get_is_answered_at_once_in_either_mode(
        self, tmp_path: Path, overrides: Dict[str, Any], status: int
    ) -> None:
        """``curl http://<replica>:8000/mcp``, exactly as the docs give it.

        curl sends ``Accept: */*`` and no ``MCP-Protocol-Version``: a
        handshake-era GET, which the SDK would take as asking for an event
        stream. The docs promise a status line from each replica — ``405``
        stateless, ``400 Missing session ID`` with sessions — and a curl
        with no timeout would hang on a held stream instead of printing one.
        """
        client, server = _build_client(tmp_path, **overrides)
        with client:
            exchange = _drive(client, "GET", {"accept": "*/*", "user-agent": "curl"})
            assert _sessions(server) == {}
        if status == 405:
            _assert_refused_by_the_gate(exchange)
            return
        assert exchange.returned, "the request was held open until the ceiling"
        assert exchange.status == 400, (exchange.status, exchange.body)
        assert json.loads(exchange.body)["error"]["message"] == (
            "Bad Request: Missing session ID"
        )


class TestTheDefaultIsUnchanged:
    """Off by default: sessions, and the gate that keeps them from leaking."""

    def test_default_server_issues_a_session_and_gates_sessionless_requests(
        self, tmp_path: Path
    ) -> None:
        client, server = _build_client(tmp_path)
        with client:
            opened = client.post("/mcp", json=_initialize(), headers=HANDSHAKE_HEADERS)
            assert opened.status_code == 200, opened.text
            session_id = opened.headers.get("mcp-session-id")
            assert session_id

            sessionless = client.post("/mcp", json=INITIALIZED, headers=NEGOTIATED)
            assert sessionless.status_code == 400, sessionless.text
            assert sessionless.json()["error"]["message"] == (
                "Bad Request: Missing session ID"
            )
            stream = client.request("GET", "/mcp", headers=NEGOTIATED)
            assert stream.status_code == 400, stream.text

            assert list(_sessions(server)) == [session_id]


class TestModernTrafficIsUnaffected:
    """2026-07-28 requests are era-routed ahead of the stateful/stateless switch."""

    def test_modern_tools_list_is_answered_the_same_way(self, tmp_path: Path) -> None:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {"_meta": MODERN_META},
        }
        headers = {
            **HANDSHAKE_HEADERS,
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/list",
        }
        answers = []
        for name, overrides in (("off", {}), ("on", {"stateless_http": True})):
            client, _server = _build_client(tmp_path / name, **overrides)
            with client:
                response = client.post("/mcp", json=request, headers=headers)
            assert response.status_code == 200, (name, response.text)
            assert "mcp-session-id" not in response.headers
            answers.append(
                (response.headers["content-type"], response.json()["result"])
            )
        assert answers[0] == answers[1]

    def test_a_modern_get_gets_the_sdks_own_405(self, tmp_path: Path) -> None:
        """The gate leaves the 2026-07-28 path's non-POST answers to the SDK.

        Same status and ``Allow`` as the gate's, but the SDK's carries no
        body: that is what shows the request reached it. Driven directly, so
        an SDK that stopped routing the era ahead of its stateless switch —
        and so answered this GET with the stateless path's held stream —
        fails here instead of hanging.
        """
        client, _server = _build_client(tmp_path, stateless_http=True)
        with client:
            exchange = _drive(
                client,
                "GET",
                {
                    "accept": "application/json, text/event-stream",
                    "mcp-protocol-version": "2026-07-28",
                },
            )
        assert exchange.returned, "the modern GET was held open"
        assert exchange.status == 405, exchange
        assert exchange.headers.get("allow") == "POST", exchange.headers
        assert exchange.body == b"", exchange.body

    def test_modern_listen_still_opens_with_subscriptions_enabled(
        self, tmp_path: Path
    ) -> None:
        """Live updates are 2026-07-28's ``subscriptions/listen``, not a session.

        So the two settings are independent: a stateless server with
        subscriptions on (the default) still acknowledges a listen stream.
        """
        client, server = _build_client(tmp_path, stateless_http=True)
        assert server.subscription_bus is not None
        acknowledged = b"notifications/subscriptions/acknowledged"
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "subscriptions/listen",
                "params": {
                    "notifications": {"resourcesListChanged": True},
                    "_meta": MODERN_META,
                },
            }
        ).encode()
        with client:
            exchange = _drive(
                client,
                "POST",
                {
                    "content-type": "application/json",
                    "accept": "application/json, text/event-stream",
                    "mcp-protocol-version": "2026-07-28",
                    "mcp-method": "subscriptions/listen",
                },
                body,
                until=lambda seen: acknowledged in seen.body,
            )
        assert exchange.status == 200, exchange
        assert exchange.is_event_stream, exchange.headers
        assert acknowledged in exchange.body, exchange.body


class TestEachReplicaNamesItsMode:
    """Nothing in ordinary client traffic names the mode, so each replica logs it."""

    @pytest.mark.parametrize(
        ("overrides", "line"),
        [
            (
                {"stateless_http": True},
                "Serving handshake-era clients statelessly "
                "(OPENZIM_MCP_STATELESS_HTTP=true): no Mcp-Session-Id is issued, "
                "and a GET or DELETE on /mcp is answered 405",
            ),
            (
                {},
                "Serving handshake-era clients with sessions "
                "(OPENZIM_MCP_STATELESS_HTTP=false): each Mcp-Session-Id is known "
                "only to the replica that issued it",
            ),
        ],
        ids=["stateless", "default"],
    )
    def test_startup_logs_one_line_naming_the_mode(
        self, tmp_path: Path, overrides: Dict[str, Any], line: str
    ) -> None:
        """One INFO line per start, written before serving, quoted by the docs.

        Replicas that disagree break handshake-era clients mid-sequence, and
        the docs tell an operator to check this line on every replica — so the
        line the docs quote has to be the one the server writes, every word of
        it: a line naming one mode beside the other's setting would mislead.
        It is read at the moment ``runner`` is called, because uvicorn blocks
        there until shutdown: a line logged after it would never be seen by an
        operator looking at a running replica.
        """
        logger = logging.getLogger("openzim_mcp.http_app")
        level = logger.level
        logger.setLevel(logging.INFO)
        server = _server(tmp_path, **overrides)
        announced: List[str] = []

        def mode_lines(records: List[logging.LogRecord]) -> List[str]:
            return [
                record.getMessage()
                for record in records
                if record.levelno == logging.INFO
                and record.getMessage().startswith("Serving handshake-era clients")
            ]

        try:
            with _collected("openzim_mcp.http_app") as records:
                serve_streamable_http(
                    server,
                    runner=lambda app, host, port: announced.extend(
                        mode_lines(records)
                    ),
                )
        finally:
            logger.setLevel(level)
        assert announced == [line], announced
        assert mode_lines(records) == [line], "logged again after serving began"
        quoted = line.split(" (", 1)[0]
        assert quoted in DEPLOYMENT_DOC.read_text(encoding="utf-8"), (
            f"the deployment docs tell operators to look for {quoted!r} at "
            "startup, but no longer quote it"
        )


class TestLogNoise:
    """The SDK's per-request ``Terminating session: None`` line, filtered."""

    SDK_LOGGER = "mcp.server.streamable_http"

    def test_stateless_requests_log_no_session_ending_and_sessions_still_do(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both directions through one installed filter, on real traffic.

        Driven, not synthesised, so the filter is matched against the record
        the SDK really writes: a changed message would bring the noise back
        here. The stateful DELETE is the control that INFO records from that
        logger reach a handler at all — without it, a raised level or a filter
        that swallowed every termination would pass the first half.
        """
        # The servers below configure logging from the environment, so an
        # ``OPENZIM_MCP_LOGGING__LEVEL`` above INFO left in the shell would
        # drop the very records this test reads (the live tier pins it too).
        monkeypatch.setenv("OPENZIM_MCP_LOGGING__LEVEL", "INFO")
        sdk_logger = logging.getLogger(self.SDK_LOGGER)
        level_before = sdk_logger.level
        stateless, _ = _build_client(tmp_path / "on", stateless_http=True)
        stateful, _ = _build_client(tmp_path / "off")
        # Raising the level instead would hide the module's DEBUG output too.
        assert sdk_logger.level == level_before
        assert sdk_logger.isEnabledFor(logging.INFO)

        with _collected(self.SDK_LOGGER) as records:
            with stateless:
                listed = stateless.post("/mcp", json=TOOLS_LIST, headers=NEGOTIATED)
                assert listed.status_code == 200, listed.text
            with stateful:
                opened = stateful.post(
                    "/mcp", json=_initialize(), headers=HANDSHAKE_HEADERS
                )
                session_id = opened.headers["mcp-session-id"]
                ended = stateful.request(
                    "DELETE",
                    "/mcp",
                    headers={**NEGOTIATED, "Mcp-Session-Id": session_id},
                )
                assert ended.status_code == 200, ended.text

        terminations = [
            record.getMessage()
            for record in records
            if record.getMessage().startswith("Terminating session:")
        ]
        assert terminations == [f"Terminating session: {session_id}"], terminations

    def test_the_filter_is_in_place_before_serving_starts(self, tmp_path: Path) -> None:
        """uvicorn blocks inside ``runner`` until shutdown, so the filter goes in first.

        Installed after it, the filter would only start dropping records once
        the server had stopped, every request in between logging the noise
        again — and a runner that returns at once, as ``_build_client``'s
        does, would never notice. So the SDK's two records are written from
        inside the runner, the moment serving would begin: the ``None`` one
        must be dropped there, and a real session's must still get through.
        """
        sdk_logger = logging.getLogger(self.SDK_LOGGER)
        terminate_filter = http_app._STATELESS_TERMINATE_FILTER
        was_installed = terminate_filter in sdk_logger.filters
        level = sdk_logger.level
        # Lifted first: any stateless app built earlier in this process
        # installed it, which would pass this test for the wrong reason.
        sdk_logger.removeFilter(terminate_filter)
        sdk_logger.setLevel(logging.INFO)
        server = _server(tmp_path, stateless_http=True)
        session_id = uuid4().hex

        def runner(app: Any, host: str, port: int) -> None:
            sdk_logger.info("Terminating session: None")
            sdk_logger.info("Terminating session: %s", session_id)

        try:
            with _collected(self.SDK_LOGGER) as records:
                serve_streamable_http(server, runner=runner)
        finally:
            sdk_logger.setLevel(level)
            if not was_installed:
                sdk_logger.removeFilter(terminate_filter)
        assert [record.getMessage() for record in records] == [
            f"Terminating session: {session_id}"
        ]

    def test_the_filter_is_installed_once(self, tmp_path: Path) -> None:
        """Serving twice, or building several apps, must not stack filters."""
        sdk_logger = logging.getLogger(self.SDK_LOGGER)
        _build_client(tmp_path / "first", stateless_http=True)
        installed = list(sdk_logger.filters)
        _build_client(tmp_path / "second", stateless_http=True)
        assert sdk_logger.filters == installed


class TestWhatTheSessionCarried:
    """The trade-off the setting's description states, pinned where it is claimed."""

    def test_closing_the_call_connection_cancels_it(self, tmp_path: Path) -> None:
        """The cancel a stateless client keeps: hanging up on the call.

        A handshake-era ``notifications/cancelled`` arrives on its own POST and
        cannot reach a call in flight on another — the one thing the
        description says is given up — so what it promises instead has to
        hold: closing the call's connection cancels the call.
        """
        client, server = _build_client(tmp_path, stateless_http=True)
        cancelled = threading.Event()
        tool_started: Dict[str, anyio.Event] = {}

        async def slow_call() -> str:
            tool_started["event"].set()
            try:
                await anyio.sleep_forever()
            except anyio.get_cancelled_exc_class():
                cancelled.set()
                raise
            return "unreachable"  # pragma: no cover

        server.mcp.add_tool(slow_call, name="slow_call")
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "slow_call", "arguments": {}},
            }
        ).encode()
        with client:
            # Created on the portal's loop, where the tool runs and sets it.
            tool_started["event"] = client.portal.call(anyio.Event)  # type: ignore[union-attr]
            exchange = _drive(
                client,
                "POST",
                {name.lower(): value for name, value in NEGOTIATED.items()},
                body,
                hang_up_on=tool_started["event"],
            )
            # Checked before the lifespan ends: shutdown cancels every task,
            # which would satisfy this for the wrong reason.
            assert cancelled.wait(
                CEILING_SECONDS
            ), "hanging up on the call left it running"
        assert exchange.returned, "the call's stream outlived the hang-up"

    def test_capabilities_match_and_promise_no_notifications(
        self, tmp_path: Path
    ) -> None:
        """A handshake-era client is promised nothing a session would carry.

        ``resources.subscribe`` and every ``listChanged`` flag are promises of
        notifications on the session's standalone stream, which stateless
        mode refuses. If any were ever advertised to a handshake-era client,
        the setting's "nothing else rides on the session" would be wrong.
        """
        capabilities = []
        for name, overrides in (("off", {}), ("on", {"stateless_http": True})):
            client, _server = _build_client(tmp_path / name, **overrides)
            with client:
                opened = client.post(
                    "/mcp", json=_initialize(), headers=HANDSHAKE_HEADERS
                )
            payload = _sse_payload(opened.text)
            assert payload is not None, opened.text
            capabilities.append(payload["result"]["capabilities"])
        assert capabilities[0] == capabilities[1]
        advertised = capabilities[1]
        assert advertised["resources"]["subscribe"] is False, advertised
        for kind in ("resources", "tools", "prompts"):
            assert advertised[kind]["listChanged"] is False, advertised


# --------------------------------------------------------------------------
# The tripwire: stateless mode depends on this server never needing a session.
# --------------------------------------------------------------------------

# Every public method the SDK defines on its server-side contexts and channels,
# sorted by whether a call can reach a client outside the response to that
# client's own request. A handshake-era client served statelessly has no
# session: a server-to-client request raises ``NoBackChannelError`` there, and
# a notification on the connection's standalone stream is dropped. So any
# back-channel name appearing in the package is a feature that would silently
# degrade under OPENZIM_MCP_STATELESS_HTTP. Keyed by where the SDK defines
# each method, so the table is checked against the SDK both ways rather than
# trusted: a method a release adds or drops fails until it is sorted here.
#
# Banned wherever the name appears.
_BACK_CHANNEL = "back-channel"
# Back-channel as well — a Connection's own channel is its standalone stream —
# but under names the standard library shares (``Logger.log``,
# ``Condition.notify``), so banned only where a Connection is the receiver.
_ON_A_CONNECTION = "back-channel on a Connection"
# Rides the response stream of the request being handled, which stateless
# mode keeps: ``Context.log`` and its level helpers pass the request id.
_REQUEST_SCOPED = "request-scoped"
# The 2026-07-28 subscription bus: it reaches only ``subscriptions/listen``
# streams, which are era-routed ahead of the stateful/stateless switch.
_BUS = "subscription bus"
_SENDS_NOTHING = "sends nothing"

_SDK_SURFACE: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "mcp.server.mcpserver.context:Context": {
        _BACK_CHANNEL: ("elicit", "elicit_url"),
        _REQUEST_SCOPED: (
            "debug",
            "error",
            "info",
            "log",
            "report_progress",
            "warning",
        ),
        _BUS: (
            "notify_prompts_changed",
            "notify_resource_updated",
            "notify_resources_changed",
            "notify_tools_changed",
        ),
        _SENDS_NOTHING: (
            "close_sse_stream",
            "close_standalone_sse_stream",
            "model_post_init",
            "read_resource",
        ),
    },
    "mcp.server.context:Context": {_REQUEST_SCOPED: ("log",)},
    "mcp.shared.context:BaseContext": {
        _BACK_CHANNEL: ("send_raw_request",),
        _REQUEST_SCOPED: ("notify", "report_progress"),
    },
    "mcp.server.session:ServerSession": {
        _BACK_CHANNEL: (
            "create_message",
            "elicit",
            "elicit_form",
            "elicit_url",
            "list_roots",
            "send_elicit_complete",
            "send_notification",
            "send_ping",
            "send_prompt_list_changed",
            "send_request",
            "send_resource_list_changed",
            "send_resource_updated",
            "send_tool_list_changed",
            # Request-scoped only when handed a related request id, and on
            # the standalone stream otherwise: counted as the latter.
            "send_log_message",
            "send_progress_notification",
        ),
        _REQUEST_SCOPED: ("report_progress",),
        _SENDS_NOTHING: ("check_client_capability",),
    },
    "mcp.server.connection:Connection": {
        _BACK_CHANNEL: (
            "send_prompt_list_changed",
            "send_raw_request",
            "send_request",
            "send_resource_list_changed",
            "send_resource_updated",
            "send_tool_list_changed",
        ),
        _ON_A_CONNECTION: ("log", "notify", "ping"),
        _SENDS_NOTHING: ("check_capability", "for_loop", "from_envelope"),
    },
    "mcp.server.subscriptions:SubscriptionBus": {
        _BUS: ("publish",),
        _SENDS_NOTHING: ("subscribe",),
    },
}
# Module-level names, which have no class to enumerate. ``ClientPeer`` wraps
# any outbound channel in typed server-to-client requests; nothing in the SDK
# hands one out, so banning the class name covers every method it has or gains.
_BACK_CHANNEL_HELPERS: Dict[str, Tuple[str, ...]] = {
    "mcp.server.elicitation": ("elicit_url", "elicit_with_validation"),
    "mcp.shared.peer": ("ClientPeer",),
}


def _sorted_as(category: str) -> FrozenSet[str]:
    """Every name ``_SDK_SURFACE`` sorts into ``category``, on any owner."""
    return frozenset(
        name for groups in _SDK_SURFACE.values() for name in groups.get(category, ())
    )


_BACK_CHANNEL_NAMES = _sorted_as(_BACK_CHANNEL) | frozenset(
    name for names in _BACK_CHANNEL_HELPERS.values() for name in names
)
_ON_A_CONNECTION_NAMES = _sorted_as(_ON_A_CONNECTION)
# Where the package could reach a Connection: the lowlevel context's
# ``connection``, or the ``_connection`` a ServerSession keeps. Nothing in the
# package touches either today. The rule reads the receiver only, so a
# Connection first bound to a name of its own would slip past it: the wire
# methods below would still catch that alias's ``notify`` of one of them, but
# not its ``log`` or ``ping``.
_CONNECTION_ATTRIBUTES = frozenset({"connection", "_connection"})
# What a raw channel would be handed to send the same traffic.
_BACK_CHANNEL_METHODS = frozenset(
    {
        "elicitation/create",
        "sampling/createMessage",
        "roots/list",
        "notifications/elicitation/complete",
        "notifications/message",
        "notifications/resources/updated",
        "notifications/resources/list_changed",
        "notifications/tools/list_changed",
        "notifications/prompts/list_changed",
    }
)


def _sdk_methods(owner: str) -> Set[str]:
    """The public methods ``owner`` defines itself, in the resolved SDK."""
    module_name, _, class_name = owner.partition(":")
    cls = getattr(importlib.import_module(module_name), class_name)
    return {
        name
        for name, value in vars(cls).items()
        if not name.startswith("_")
        and isinstance(value, (FunctionType, classmethod, staticmethod))
    }


def _back_channel_uses() -> Tuple[List[str], List[Tuple[str, str]]]:
    """Scan ``openzim_mcp`` for back-channel APIs; also report what was seen.

    Returns the offending uses as ``path:line name`` strings, and every
    ``(path, attribute)`` called anywhere — the positive control that the
    scan read the package at all.
    """
    offences: List[str] = []
    called: List[Tuple[str, str]] = []
    package = REPO / "openzim_mcp"
    for source in sorted(package.rglob("*.py")):
        relative = source.relative_to(REPO).as_posix()
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if node.attr in _BACK_CHANNEL_NAMES:
                    offences.append(f"{relative}:{node.lineno} .{node.attr}")
                elif (
                    node.attr in _ON_A_CONNECTION_NAMES
                    and isinstance(node.value, ast.Attribute)
                    and node.value.attr in _CONNECTION_ATTRIBUTES
                ):
                    offences.append(
                        f"{relative}:{node.lineno} .{node.value.attr}.{node.attr}"
                    )
            elif isinstance(node, ast.Name):
                if node.id in _BACK_CHANNEL_NAMES:
                    offences.append(f"{relative}:{node.lineno} {node.id}")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _BACK_CHANNEL_NAMES:
                        offences.append(f"{relative}:{node.lineno} import {alias.name}")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    called.append((relative, node.func.attr))
                for argument in [*node.args, *(kw.value for kw in node.keywords)]:
                    if (
                        isinstance(argument, ast.Constant)
                        and argument.value in _BACK_CHANNEL_METHODS
                    ):
                        offences.append(f"{relative}:{node.lineno} {argument.value!r}")
    return offences, called


class TestNothingNeedsASession:
    """Stateless mode is only lossless while the server never talks first."""

    def test_the_tripwire_sorts_every_sdk_method(self) -> None:
        """Every public method on the SDK's contexts and channels is sorted.

        Checked against the resolved SDK both ways — a listed name it no
        longer has, and a method it has that no list names — so neither a
        dropped entry nor a server-to-client API a new release adds can narrow
        the tripwire unnoticed: the failure names the method to sort.
        """
        for owner, groups in _SDK_SURFACE.items():
            listed = [name for names in groups.values() for name in names]
            assert len(listed) == len(set(listed)), f"{owner} sorts a name twice"
            actual = _sdk_methods(owner)
            unsorted = sorted(actual - set(listed))
            gone = sorted(set(listed) - actual)
            assert not unsorted and not gone, (
                f"{owner} has {unsorted} that _SDK_SURFACE does not sort, and "
                f"no longer has {gone}. Sort each new method by whether it can "
                "reach a client outside the response to its own request; a "
                "back-channel one is what OPENZIM_MCP_STATELESS_HTTP cannot "
                "carry."
            )
        for module_name, names in _BACK_CHANNEL_HELPERS.items():
            module = importlib.import_module(module_name)
            for name in names:
                assert hasattr(module, name), f"{module_name} has no {name}"
        # A name banned wherever it appears must not be legitimate on another
        # owner, or the scan would flag every legitimate use of it.
        legitimate = (
            _sorted_as(_REQUEST_SCOPED)
            | _sorted_as(_BUS)
            | _sorted_as(_SENDS_NOTHING)
            | _ON_A_CONNECTION_NAMES
        )
        assert not _BACK_CHANNEL_NAMES & legitimate

    def test_openzim_mcp_sends_no_server_to_client_traffic(self) -> None:
        """Fails the day the package grows a request or a standalone notification.

        Read from the source rather than observed at runtime, so a call on a
        path no test drives still trips it.
        """
        offences, called = _back_channel_uses()
        # Positive control: the scan read the package, and it sees the
        # subscription bus — the one outbound path it must let through.
        assert ("openzim_mcp/subscriptions.py", "publish") in called, called[:20]
        assert not offences, (
            "openzim_mcp now reaches clients outside the response to their own "
            f"request: {offences}. A handshake-era client served with "
            "OPENZIM_MCP_STATELESS_HTTP has no session, so a server-to-client "
            "request raises NoBackChannelError there and a connection-scoped "
            "notification is dropped. Before allowing it, revisit the "
            "`stateless_http` field description in openzim_mcp/config.py "
            '("this server sends handshake-era clients no requests and no '
            'connection-scoped notifications") and the Scaling considerations '
            "section of website/src/content/docs/http-and-docker-deployment.mdx, "
            "which both promise that nothing but cancellation rides on the "
            "session."
        )
