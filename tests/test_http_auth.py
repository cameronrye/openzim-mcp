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
    """Missing Authorization header → 401 with WWW-Authenticate: Bearer.

    M28: the challenge carries ``realm`` per RFC 6750 §3.
    """
    client = TestClient(app_with_auth)
    resp = client.get("/protected")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == 'Bearer realm="openzim-mcp"'


def test_options_request_requires_auth(app_with_auth):
    """OPTIONS to a protected path must NOT bypass bearer-token auth.

    The previous implementation let every OPTIONS request through to
    facilitate CORS preflight, which let non-browser callers probe
    auth-protected paths (notably the MCP endpoint) without a token.
    """
    client = TestClient(app_with_auth)
    resp = client.options("/protected")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == 'Bearer realm="openzim-mcp"'


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
    config.insecure_disable_auth = False

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
    config.insecure_disable_auth = False
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
    config.insecure_disable_auth = False

    if should_start:
        check_safe_startup(config)
    else:
        with pytest.raises(OpenZimMcpConfigurationError) as exc:
            check_safe_startup(config)
        assert "SSE transport" in str(exc.value)
        assert "127.0.0.1" in str(exc.value)


def test_insecure_disable_auth_allows_public_http_no_token(caplog):
    """With the bypass set, public HTTP bind without token is allowed and warns."""
    from openzim_mcp.http_app import check_safe_startup

    config = MagicMock()
    config.transport = "http"
    config.host = "0.0.0.0"
    config.auth_token = None
    config.insecure_disable_auth = True

    with caplog.at_level("WARNING", logger="openzim_mcp.http_app"):
        check_safe_startup(config)  # must not raise

    assert any(
        "INSECURE" in rec.getMessage() and "0.0.0.0" in rec.getMessage()
        for rec in caplog.records
    ), "expected loud WARNING naming the bound host"


def test_insecure_disable_auth_does_not_apply_to_sse():
    """Bypass is HTTP-only — SSE still refuses non-loopback even when set."""
    from openzim_mcp.exceptions import OpenZimMcpConfigurationError
    from openzim_mcp.http_app import check_safe_startup

    config = MagicMock()
    config.transport = "sse"
    config.host = "0.0.0.0"
    config.auth_token = None
    config.insecure_disable_auth = True

    with pytest.raises(OpenZimMcpConfigurationError) as exc:
        check_safe_startup(config)
    assert "SSE transport" in str(exc.value)


def test_insecure_disable_auth_redundant_when_token_already_set(caplog):
    """If a token is set, the bypass is unused (token path takes priority)."""
    from openzim_mcp.http_app import check_safe_startup

    config = MagicMock()
    config.transport = "http"
    config.host = "0.0.0.0"
    config.auth_token = SecretStr("abc")
    config.insecure_disable_auth = True

    with caplog.at_level("WARNING", logger="openzim_mcp.http_app"):
        check_safe_startup(config)

    assert not any(
        "INSECURE" in rec.getMessage() for rec in caplog.records
    ), "no INSECURE warning expected when a real token is configured"


class TestClientIdPlumbing:
    """Per-request ``client_id`` propagation from HTTP middleware to tools.

    The rate limiter's per-(client_id, operation) bucket isolation
    requires that tools see a stable per-connection identifier.
    Stdio transport has no middleware so ``current_client_id()`` returns
    ``"default"``. HTTP transport must set the var via
    ``request_context.set_client_id`` before dispatching to the route
    handler.
    """

    def test_token_path_sets_client_id_from_token_hash(self):
        """A valid Bearer token derives a stable per-token client_id.

        Different tokens → different client_ids so per-token rate
        isolation works.
        """
        import hashlib
        from openzim_mcp.http_app import BearerTokenAuthMiddleware
        from openzim_mcp.request_context import current_client_id

        captured = {}

        async def probe(request: Request) -> PlainTextResponse:
            captured["client_id"] = current_client_id()
            return PlainTextResponse("ok")

        config = MagicMock()
        config.auth_token = SecretStr("alpha-token")
        app = Starlette(routes=[Route("/probe", probe)])
        app.add_middleware(BearerTokenAuthMiddleware, config=config)
        client = TestClient(app)

        resp = client.get(
            "/probe", headers={"Authorization": "Bearer alpha-token"}
        )
        assert resp.status_code == 200
        expected = (
            "bearer:"
            + hashlib.sha256(b"alpha-token").hexdigest()[:8]
        )
        assert captured["client_id"] == expected

    def test_different_tokens_resolve_to_different_client_ids(self):
        """Bucket isolation actually works: two distinct tokens land on
        two distinct client_ids.
        """
        from openzim_mcp.http_app import BearerTokenAuthMiddleware
        from openzim_mcp.request_context import current_client_id

        seen: list[str] = []

        async def probe(request: Request) -> PlainTextResponse:
            seen.append(current_client_id())
            return PlainTextResponse("ok")

        # Two parallel apps each with their own expected token. Realistic
        # multi-token deployments are typically reverse-proxy-fronted with
        # one MCP server per token, but the derivation function operates
        # on the *presented* token so the resolution is still correct
        # when one server accepts multiple tokens via callers.
        config1 = MagicMock()
        config1.auth_token = SecretStr("token-a")
        app1 = Starlette(routes=[Route("/probe", probe)])
        app1.add_middleware(BearerTokenAuthMiddleware, config=config1)
        TestClient(app1).get(
            "/probe", headers={"Authorization": "Bearer token-a"}
        )

        config2 = MagicMock()
        config2.auth_token = SecretStr("token-b")
        app2 = Starlette(routes=[Route("/probe", probe)])
        app2.add_middleware(BearerTokenAuthMiddleware, config=config2)
        TestClient(app2).get(
            "/probe", headers={"Authorization": "Bearer token-b"}
        )

        assert len(seen) == 2
        assert seen[0] != seen[1], (
            f"Different Bearer tokens must map to different client_ids; "
            f"got both as {seen[0]!r}"
        )

    def test_no_token_config_falls_back_to_remote_address(self):
        """The token-disabled localhost path still gets per-IP isolation —
        not the bare ``"default"`` fallback that would share one bucket
        across every loopback caller.
        """
        from openzim_mcp.http_app import BearerTokenAuthMiddleware
        from openzim_mcp.request_context import current_client_id

        captured = {}

        async def probe(request: Request) -> PlainTextResponse:
            captured["client_id"] = current_client_id()
            return PlainTextResponse("ok")

        config = MagicMock()
        config.auth_token = None
        app = Starlette(routes=[Route("/probe", probe)])
        app.add_middleware(BearerTokenAuthMiddleware, config=config)
        TestClient(app).get("/probe")

        assert captured["client_id"].startswith("ip:"), (
            f"Expected ip-derived client_id; got {captured['client_id']!r}"
        )
