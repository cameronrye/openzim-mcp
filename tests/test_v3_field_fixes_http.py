"""v3.0.0 field-defect fixes: HTTP transport (workstream ``http``).

Every test here drives the REAL streamable-HTTP app that
``serve_streamable_http`` hands to uvicorn — SDK session manager, auth, CORS
and the gates wired in production order — through Starlette's ``TestClient``.
The defects are about what the SDK does *before* our handlers run, so a
stubbed app would prove nothing.

D62: a sessionless request on the handshake-era path made the SDK mint,
register and task-start a session before rejecting the request with
``400 Missing session ID``; nothing ever reaped it.
"""

import json
from typing import Any, Dict, Iterator, Optional, Tuple

import pytest
from starlette.testclient import TestClient

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.http_app import serve_streamable_http
from openzim_mcp.server import OpenZimMcpServer

# What a handshake-era client sends on every request (the Accept pair is the
# SDK's precondition for even looking at the body).
LEGACY_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

# The SDK's verbatim rejection for a sessionless non-initialize request. The
# gate must answer identically, so a client sees no behavior change — only
# the leak goes away.
MISSING_SESSION_BODY = {
    "jsonrpc": "2.0",
    "id": None,
    "error": {"code": -32600, "message": "Bad Request: Missing session ID"},
}

INITIALIZE_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "field-test", "version": "0"},
    },
}

TOOLS_LIST_BODY = {"jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {}}


def _build_client(
    tmp_path: Any, **config_overrides: Any
) -> Tuple[TestClient, OpenZimMcpServer]:
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)], transport="http", **config_overrides
    )
    server = OpenZimMcpServer(cfg)
    captured: Dict[str, Any] = {}
    serve_streamable_http(
        server, runner=lambda app, host, port: captured.update(app=app)
    )
    # Loopback base URL: the default ``testserver`` Host would be turned away
    # by the DNS-rebinding gate (421) before the request reaches the SDK,
    # which is exactly the layer these defects live in.
    return TestClient(captured["app"], base_url="http://127.0.0.1"), server


@pytest.fixture
def http_client(tmp_path: Any) -> Iterator[Tuple[TestClient, OpenZimMcpServer]]:
    """Production-wired app on a real server, lifespan running."""
    client, server = _build_client(tmp_path)
    with client:
        yield client, server


def _sessions(server: OpenZimMcpServer) -> Dict[str, Any]:
    """The SDK session table the leak grows."""
    return server.mcp.session_manager._server_instances


def _sse_result(text: str) -> Optional[Dict[str, Any]]:
    """Pull the JSON-RPC payload out of the SDK's one-event SSE response."""
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :])
    return None


# --------------------------------------------------------------------------
# D62 — sessionless handshake-era requests must not mint a session
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw_body",
    [
        pytest.param(json.dumps(TOOLS_LIST_BODY), id="request"),
        pytest.param(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            id="notification",
        ),
        pytest.param("{not json", id="unparseable"),
    ],
)
def test_d62_sessionless_post_is_rejected_without_minting_a_session(
    http_client: Tuple[TestClient, OpenZimMcpServer], raw_body: str
) -> None:
    """The packet repro: 30 sessionless POSTs → 30 × 400, created=0.

    Before the fix each 400 carried a FRESH ``mcp-session-id`` and left a
    registered transport plus a live serve_loop task behind.
    """
    client, server = http_client
    for _ in range(30):
        resp = client.post("/mcp", content=raw_body, headers=LEGACY_HEADERS)
        assert resp.status_code == 400
        assert resp.json() == MISSING_SESSION_BODY
        assert "mcp-session-id" not in resp.headers
    assert _sessions(server) == {}


@pytest.mark.parametrize("method", ["GET", "DELETE"])
def test_d62_sessionless_get_and_delete_are_rejected_without_minting(
    http_client: Tuple[TestClient, OpenZimMcpServer], method: str
) -> None:
    """A bare GET (stream open) or DELETE without a session id leaked too."""
    client, server = http_client
    resp = client.request(method, "/mcp", headers=LEGACY_HEADERS)
    assert resp.status_code == 400
    assert resp.json() == MISSING_SESSION_BODY
    assert "mcp-session-id" not in resp.headers
    assert _sessions(server) == {}


def test_d62_legacy_version_header_without_session_is_gated_too(
    http_client: Tuple[TestClient, OpenZimMcpServer],
) -> None:
    """Naming a 2025 revision keeps a request on the handshake path."""
    client, server = http_client
    resp = client.post(
        "/mcp",
        json=TOOLS_LIST_BODY,
        headers={**LEGACY_HEADERS, "MCP-Protocol-Version": "2025-06-18"},
    )
    assert resp.status_code == 400
    assert resp.json() == MISSING_SESSION_BODY
    assert _sessions(server) == {}


def test_d62_initialize_still_opens_a_session_and_delete_terminates_it(
    http_client: Tuple[TestClient, OpenZimMcpServer],
) -> None:
    """The one legitimate sessionless request must still pass the gate.

    Exercises the full handshake-era lifecycle through the gate: initialize
    (no session yet) → server-issued id → initialized notification →
    tools/list reuse → DELETE → the id is dead afterwards.
    """
    client, server = http_client

    resp = client.post("/mcp", json=INITIALIZE_BODY, headers=LEGACY_HEADERS)
    assert resp.status_code == 200, resp.text
    session_id = resp.headers.get("mcp-session-id")
    assert session_id
    assert session_id in _sessions(server)
    payload = _sse_result(resp.text)
    assert payload is not None and "result" in payload, resp.text
    assert payload["result"]["serverInfo"]

    with_session = {**LEGACY_HEADERS, "Mcp-Session-Id": session_id}
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=with_session,
    )
    assert resp.status_code == 202

    resp = client.post("/mcp", json=TOOLS_LIST_BODY, headers=with_session)
    assert resp.status_code == 200, resp.text
    payload = _sse_result(resp.text)
    assert payload is not None and payload["result"]["tools"], resp.text

    resp = client.delete("/mcp", headers=with_session)
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("mcp-session-id") == session_id

    resp = client.post("/mcp", json=TOOLS_LIST_BODY, headers=with_session)
    assert resp.status_code == 404
    assert "terminated" in resp.json()["error"]["message"].lower()
    # Only the one session the handshake legitimately created ever existed.
    assert list(_sessions(server)) == [session_id]


def test_d62_modern_stateless_post_passes_the_gate(
    http_client: Tuple[TestClient, OpenZimMcpServer],
) -> None:
    """A 2026-07-28 client never has a session id; the gate must not care."""
    client, server = http_client
    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                }
            },
        },
        headers={
            **LEGACY_HEADERS,
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/list",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["result"]["tools"]
    assert _sessions(server) == {}


def test_d62_oversized_sessionless_body_is_bounded_not_buffered(
    http_client: Tuple[TestClient, OpenZimMcpServer],
) -> None:
    """Sniffing the body for ``initialize`` must not become its own DoS.

    A chunked body with no Content-Length cannot be pre-checked by size, so
    the gate reads it under the SDK's own request cap and answers the SDK's
    413 when that is exceeded — without minting a session either way.
    """
    from mcp.server.streamable_http_manager import DEFAULT_MAX_REQUEST_BODY_SIZE

    client, server = http_client
    chunk = b"x" * 65536

    def too_big() -> Iterator[bytes]:
        sent = 0
        while sent <= DEFAULT_MAX_REQUEST_BODY_SIZE:
            yield chunk
            sent += len(chunk)

    resp = client.post("/mcp", content=too_big(), headers=LEGACY_HEADERS)
    assert resp.status_code == 413
    assert _sessions(server) == {}


def test_d62_health_endpoints_are_not_gated(
    http_client: Tuple[TestClient, OpenZimMcpServer],
) -> None:
    """The gate is for the MCP endpoint; probes stay sessionless by nature."""
    client, _server = http_client
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
