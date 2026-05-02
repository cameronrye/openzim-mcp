"""Bearer-token auth middleware for HTTP transport."""

from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


@pytest.fixture
def app_with_auth():
    """Build a Starlette app with auth middleware applied."""
    from openzim_mcp.http_app import BearerTokenAuthMiddleware

    config = MagicMock()
    config.auth_token = SecretStr("topsecret")

    async def protected(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/protected", protected)])
    app.add_middleware(BearerTokenAuthMiddleware, config=config)
    return app


def test_no_auth_header_returns_401(app_with_auth):
    """Missing Authorization header → 401 with WWW-Authenticate: Bearer."""
    client = TestClient(app_with_auth)
    resp = client.get("/protected")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


def test_options_request_requires_auth(app_with_auth):
    """OPTIONS to a protected path must NOT bypass bearer-token auth.

    The previous implementation let every OPTIONS request through to
    facilitate CORS preflight, which let non-browser callers probe
    auth-protected paths (notably the MCP endpoint) without a token.
    """
    client = TestClient(app_with_auth)
    resp = client.options("/protected")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


def test_options_request_to_health_path_still_allowed(app_with_auth):
    """OPTIONS to an AUTH_EXEMPT_PATHS entry must still pass without a token."""
    from openzim_mcp.http_app import AUTH_EXEMPT_PATHS, BearerTokenAuthMiddleware

    # /healthz is in AUTH_EXEMPT_PATHS; build a tiny app that has it.
    assert "/healthz" in AUTH_EXEMPT_PATHS
    config = MagicMock()
    config.auth_token = SecretStr("topsecret")

    async def healthz(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/healthz", healthz)])
    app.add_middleware(BearerTokenAuthMiddleware, config=config)
    client = TestClient(app)
    # OPTIONS on the exempt path should not be challenged for auth.
    resp = client.options("/healthz")
    # Starlette's default OPTIONS responder returns 405 for plain Routes;
    # the important assertion is that we did NOT 401 on the exempt path.
    assert resp.status_code != 401


def test_wrong_scheme_returns_401(app_with_auth):
    """Non-Bearer Authorization scheme → 401."""
    client = TestClient(app_with_auth)
    resp = client.get("/protected", headers={"Authorization": "Basic xyz"})
    assert resp.status_code == 401


def test_invalid_token_returns_401(app_with_auth):
    """Wrong Bearer token → 401."""
    client = TestClient(app_with_auth)
    resp = client.get("/protected", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_valid_token_passes(app_with_auth):
    """Correct Bearer token → 200."""
    client = TestClient(app_with_auth)
    resp = client.get("/protected", headers={"Authorization": "Bearer topsecret"})
    assert resp.status_code == 200


def test_health_endpoints_skip_auth():
    """/healthz and /readyz must NOT require auth."""
    from openzim_mcp.http_app import BearerTokenAuthMiddleware, build_starlette_app

    server = MagicMock()
    server.config = MagicMock()
    server.config.auth_token = SecretStr("topsecret")
    server.config.allowed_directories = ["/tmp"]
    app = build_starlette_app(server)
    app.add_middleware(BearerTokenAuthMiddleware, config=server.config)
    client = TestClient(app)
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code in (200, 503)


def test_failure_logs_exclude_token(app_with_auth, caplog):
    """The attempted token must never appear in any log message."""
    client = TestClient(app_with_auth)
    client.get("/protected", headers={"Authorization": "Bearer leakedsecret"})
    # The attempted token must NEVER appear in any log message.
    for record in caplog.records:
        assert "leakedsecret" not in record.getMessage()


@pytest.mark.parametrize(
    "host,token,should_start",
    [
        ("127.0.0.1", None, True),  # localhost + no token → safe
        ("127.0.0.1", "abc", True),  # localhost + token → safe
        ("0.0.0.0", None, False),  # exposed + no token → REFUSE
        ("0.0.0.0", "abc", True),  # exposed + token → safe
        ("192.168.1.5", None, False),  # exposed + no token → REFUSE
    ],
)
def test_safe_default_startup_check(host, token, should_start):
    """The host/auth_token safety matrix from spec section 4.2."""
    from openzim_mcp.exceptions import OpenZimMcpConfigurationError
    from openzim_mcp.http_app import check_safe_startup

    config = MagicMock()
    config.transport = "http"
    config.host = host
    config.auth_token = SecretStr(token) if token else None

    if should_start:
        check_safe_startup(config)  # should not raise
    else:
        with pytest.raises(OpenZimMcpConfigurationError) as exc:
            check_safe_startup(config)
        assert "OPENZIM_MCP_AUTH_TOKEN" in str(exc.value)


def test_safe_default_check_skipped_for_stdio():
    """The check is HTTP-only; stdio doesn't apply."""
    from openzim_mcp.http_app import check_safe_startup

    config = MagicMock()
    config.transport = "stdio"
    config.host = "0.0.0.0"  # would refuse for HTTP
    config.auth_token = None
    check_safe_startup(config)  # no raise


@pytest.mark.parametrize(
    "host, should_start",
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("localhost", True),
        ("0.0.0.0", False),
        ("192.168.1.5", False),
    ],
)
def test_safe_default_startup_check_sse(host, should_start):
    """SSE has no auth middleware — non-localhost is refused regardless of token."""
    from openzim_mcp.exceptions import OpenZimMcpConfigurationError
    from openzim_mcp.http_app import check_safe_startup

    config = MagicMock()
    config.transport = "sse"
    config.host = host
    # Token presence should not change the SSE outcome — there is no middleware
    # to enforce it on the SSE path.
    config.auth_token = SecretStr("any-token")

    if should_start:
        check_safe_startup(config)
    else:
        with pytest.raises(OpenZimMcpConfigurationError) as exc:
            check_safe_startup(config)
        assert "SSE transport" in str(exc.value)
        assert "127.0.0.1" in str(exc.value)
