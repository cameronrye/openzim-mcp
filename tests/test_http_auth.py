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
