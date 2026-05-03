"""Live HTTP transport smoke + multi-instance + safe-default refusal.

Covers v1.0 items: HTTP transport (auth, CORS, /healthz, /readyz,
OPTIONS-requires-auth, safe-default refusal) and multi-instance HTTP
coexistence.
"""

from __future__ import annotations

import httpx
import pytest

from tests.live.conftest import expect_failed_startup, fresh_token

pytestmark = pytest.mark.live

TOKEN = fresh_token()


def test_healthz_returns_ok(spawn_live_server) -> None:
    """``GET /healthz`` returns 200 on a freshly-started HTTP server."""
    srv = spawn_live_server(transport="http")
    resp = srv.healthz()
    assert resp.status_code == 200


def test_readyz_returns_ok(spawn_live_server) -> None:
    """``GET /readyz`` returns 200 when allowed dirs are readable."""
    srv = spawn_live_server(transport="http")
    resp = srv.readyz()
    assert resp.status_code == 200


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
