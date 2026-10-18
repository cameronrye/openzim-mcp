"""Live HTTP transport smoke + multi-instance + safe-default refusal.

Covers v1.0 items: HTTP transport (auth, CORS, /healthz, /readyz,
OPTIONS-requires-auth, safe-default refusal) and multi-instance HTTP
coexistence — and, for ``OPENZIM_MCP_STATELESS_HTTP``, the probes and a
handshake-era client's whole sequence against a spawned server, where env
parsing, the real uvicorn runner, the gates and the SDK all take part.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx
import pytest

from tests.live.conftest import expect_failed_startup, fresh_token

pytestmark = pytest.mark.live

TOKEN = fresh_token()

# Both values spelled out, so a variable left in the shell cannot pick the
# mode the "default" case runs in.
_MODES = pytest.mark.parametrize(
    "stateless_http", ["false", "true"], ids=["stateful", "stateless"]
)


@_MODES
def test_healthz_returns_ok(spawn_live_server, stateless_http: str) -> None:
    """``GET /healthz`` returns 200 on a freshly-started HTTP server.

    In both modes: the stateless gate answers every non-POST method on the
    MCP route, and a probe that strayed into it would pull every replica.
    The startup line the deployment docs tell operators to check is read
    back from the process too, so the variable is known to have reached it.
    """
    srv = spawn_live_server(
        transport="http", extra_env={"OPENZIM_MCP_STATELESS_HTTP": stateless_http}
    )
    resp = srv.healthz()
    assert resp.status_code == 200
    mode = "statelessly" if stateless_http == "true" else "with sessions"
    assert srv.stderr_path is not None
    startup = srv.stderr_path.read_text(encoding="utf-8", errors="replace")
    assert f"Serving handshake-era clients {mode}" in startup, startup[-2000:]


@_MODES
def test_readyz_returns_ok(spawn_live_server, stateless_http: str) -> None:
    """``GET /readyz`` returns 200 when allowed dirs are readable, in both modes."""
    srv = spawn_live_server(
        transport="http", extra_env={"OPENZIM_MCP_STATELESS_HTTP": stateless_http}
    )
    resp = srv.readyz()
    assert resp.status_code == 200


def _sse_payload(text: str) -> Optional[Dict[str, Any]]:
    """The JSON-RPC payload inside the SDK's one-event SSE response."""
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:") :])
    return None


def test_stateless_handshake_sequence_over_a_real_socket(spawn_live_server) -> None:
    """A handshake-era client's whole sequence, with no session anywhere.

    The frames Open WebUI's client sends (mcp 1.27.2): ``initialize``, then
    ``notifications/initialized``, ``tools/list`` and ``tools/call``, each a
    POST standing alone. Then the GET a TypeScript client opens after
    ``notifications/initialized``, which must be refused rather than held:
    read through ``stream`` so a regression to a held stream fails on the
    status line instead of waiting on a body that never ends.
    """
    srv = spawn_live_server(
        transport="http",
        token=TOKEN,
        extra_env={"OPENZIM_MCP_STATELESS_HTTP": "true"},
    )
    url = f"{srv.base_url}/mcp"
    base = {
        **srv.auth_headers,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    negotiated = {**base, "MCP-Protocol-Version": "2025-11-25"}
    frames = [
        (
            base,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "live-stateless", "version": "0"},
                },
            },
        ),
        (negotiated, {"jsonrpc": "2.0", "method": "notifications/initialized"}),
        (negotiated, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        (
            negotiated,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "zim_health", "arguments": {}},
            },
        ),
    ]
    with httpx.Client(timeout=30) as client:
        answers = [client.post(url, json=body, headers=hdrs) for hdrs, body in frames]
        with client.stream(
            "GET",
            url,
            headers={
                **srv.auth_headers,
                "Accept": "text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
        ) as stream:
            stream_status = stream.status_code
            stream_headers = dict(stream.headers)

    assert [answer.status_code for answer in answers] == [200, 202, 200, 200], [
        answer.text[:200] for answer in answers
    ]
    for answer in answers:
        assert "mcp-session-id" not in answer.headers, answer.headers
    opened = _sse_payload(answers[0].text)
    assert opened is not None and opened["result"]["protocolVersion"] == "2025-11-25"
    listed = _sse_payload(answers[2].text)
    assert listed is not None
    assert "zim_health" in {tool["name"] for tool in listed["result"]["tools"]}
    called = _sse_payload(answers[3].text)
    assert called is not None and called["result"]["isError"] is False, called

    assert stream_status == 405, stream_headers
    assert stream_headers.get("allow") == "POST", stream_headers
    assert "mcp-session-id" not in stream_headers


def test_no_auth_returns_401(spawn_live_server) -> None:
    """With OPENZIM_MCP_AUTH_TOKEN set, /mcp requires Bearer auth."""
    srv = spawn_live_server(transport="http", token=TOKEN)
    resp = httpx.post(f"{srv.base_url}/mcp", timeout=5)
    assert resp.status_code == 401


def test_wrong_token_returns_401(spawn_live_server) -> None:
    """Bearer header with the wrong token is rejected with 401."""
    srv = spawn_live_server(transport="http", token=TOKEN)
    resp = httpx.post(
        f"{srv.base_url}/mcp",
        headers={"Authorization": "Bearer wrong-token"},
        timeout=5,
    )
    assert resp.status_code == 401


def test_options_mcp_requires_auth(spawn_live_server) -> None:
    """v1.0 security fix: OPTIONS /mcp must not bypass auth."""
    srv = spawn_live_server(transport="http", token=TOKEN)
    resp = httpx.options(f"{srv.base_url}/mcp", timeout=5)
    assert resp.status_code == 401


def test_options_healthz_skips_auth(spawn_live_server) -> None:
    """Health endpoints stay open even with auth on, so probes work."""
    srv = spawn_live_server(transport="http", token=TOKEN)
    resp = httpx.options(f"{srv.base_url}/healthz", timeout=5)
    assert resp.status_code in (200, 204, 405)  # any non-401 is fine


def test_safe_default_refuses_public_bind_without_token(zim_dir, tmp_path) -> None:
    """Binding non-loopback host without a token must fail to start."""
    # Pick a free port on 127.0.0.1, then try to bind 0.0.0.0:that_port.
    import socket as _socket

    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])

    cp = expect_failed_startup(
        zim_dir=zim_dir, transport="http", host="0.0.0.0", port=port, token=None
    )
    # Server should exit non-zero and explain why on stderr.
    assert cp.returncode != 0
    stderr_text = cp.stderr.decode(errors="replace")
    assert (
        "auth" in stderr_text.lower() or "token" in stderr_text.lower()
    ), f"expected auth/token in stderr, got:\n{stderr_text}"


def test_cors_preflight_allowed_origin(spawn_live_server) -> None:
    """CORS preflight from a listed origin returns 200 with ACAO echo.

    Run without a token so the OPTIONS preflight isn't intercepted by
    auth before reaching the CORS middleware. This is what a browser
    actually sees: the preflight is unauthenticated by spec.
    """
    origin = "https://allowed.example"
    srv = spawn_live_server(transport="http", cors_origins=[origin])
    resp = httpx.options(
        f"{srv.base_url}/mcp",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
        timeout=5,
    )
    assert resp.status_code in (200, 204), (
        f"preflight from allowed origin returned {resp.status_code}: "
        f"{resp.text[:200]}"
    )
    assert resp.headers.get("access-control-allow-origin") == origin
    # Must also echo the requested method back as allowed.
    allow_methods = resp.headers.get("access-control-allow-methods", "")
    assert "POST" in allow_methods, f"ACAM should include POST, got: {allow_methods!r}"


def test_cors_preflight_disallowed_origin(spawn_live_server) -> None:
    """CORS preflight from origin not on allow-list omits the ACAO header."""
    srv = spawn_live_server(transport="http", cors_origins=["https://allowed.example"])
    resp = httpx.options(
        f"{srv.base_url}/mcp",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
        timeout=5,
    )
    # Starlette's CORSMiddleware returns 400 for disallowed origins on
    # preflight; either way, ACAO must not be present (or must not echo
    # the disallowed origin).
    acao = resp.headers.get("access-control-allow-origin")
    assert (
        acao != "https://evil.example"
    ), f"ACAO leaked the disallowed origin: {acao!r}"


def test_cors_disabled_when_no_origins_configured(spawn_live_server) -> None:
    """No cors_origins → no CORS middleware → no ACAO header on any response."""
    srv = spawn_live_server(transport="http")  # no cors_origins
    resp = httpx.options(
        f"{srv.base_url}/healthz",
        headers={
            "Origin": "https://anything.example",
            "Access-Control-Request-Method": "GET",
        },
        timeout=5,
    )
    assert resp.headers.get("access-control-allow-origin") is None


def test_two_http_instances_coexist(spawn_live_server) -> None:
    """Two HTTP servers on different ports both come up (no conflict tracking)."""
    srv_a = spawn_live_server(transport="http")
    srv_b = spawn_live_server(transport="http")
    assert srv_a.port != srv_b.port
    assert srv_a.healthz().status_code == 200
    assert srv_b.healthz().status_code == 200
