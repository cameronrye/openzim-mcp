"""Regression tests for code-review 2026-06-10 Phase 2 (HTTP transport / auth).

Covers H4 (empty auth token disables auth), H10 (non-loopback bind 421s),
M6 (readyz blocking syscalls), and M12 (rate limiter never enforced).
"""

import tempfile
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpConfigurationError

# ---------------------------------------------------------------------------
# H4 — empty OPENZIM_MCP_AUTH_TOKEN must not silently disable authentication
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_blank_auth_token_rejected_at_config_load(tmp_path, blank):
    with pytest.raises(OpenZimMcpConfigurationError):
        OpenZimMcpConfig(
            allowed_directories=[str(tmp_path)],
            transport="http",
            auth_token=blank,
        )


def test_valid_and_absent_auth_token_accepted(tmp_path):
    # A real secret is fine.
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)], transport="http", auth_token="s3cret"
    )
    assert cfg.auth_token is not None
    # No token at all is fine (localhost-only mode).
    cfg2 = OpenZimMcpConfig(allowed_directories=[str(tmp_path)], transport="http")
    assert cfg2.auth_token is None


def test_middleware_treats_empty_secret_as_no_auth(tmp_path):
    """Defense in depth: an empty expected token must not authenticate all."""
    from openzim_mcp.http_app import BearerTokenAuthMiddleware

    cfg = MagicMock()
    secret = MagicMock()
    secret.get_secret_value.return_value = ""
    cfg.auth_token = secret
    mw = BearerTokenAuthMiddleware(MagicMock(), cfg)
    # Empty secret collapses to the "no auth configured" fast-path, not a
    # value that hmac.compare_digest('', '') would accept.
    assert mw._expected is None


# ---------------------------------------------------------------------------
# H10 — non-loopback bind without ALLOWED_HOSTS must not 421 every request
# ---------------------------------------------------------------------------


def test_specific_lan_ip_bind_allows_direct_host(tmp_path):
    """Binding a fixed non-loopback IP adds it (and :*) to the allow-list."""
    from openzim_mcp.server import _build_transport_security

    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        transport="http",
        host="192.168.1.50",
        auth_token="s3cret",
    )
    settings, warning = _build_transport_security(cfg)
    assert settings.enable_dns_rebinding_protection is True
    hosts = set(settings.allowed_hosts)
    assert {"192.168.1.50", "192.168.1.50:*"} <= hosts
    # Loopback stays reachable.
    assert {"127.0.0.1:*", "localhost:*"} <= hosts
    assert warning is None


def test_bind_all_without_allowed_hosts_disables_host_validation(tmp_path):
    """0.0.0.0 with no pinned Host disables rebinding validation + warns."""
    from openzim_mcp.server import _build_transport_security

    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        transport="http",
        host="0.0.0.0",  # noqa: S104 — exercising the bind-all branch
        auth_token="s3cret",
    )
    settings, warning = _build_transport_security(cfg)
    assert settings.enable_dns_rebinding_protection is False
    assert warning is not None
    assert "ALLOWED_HOSTS" in warning


def test_bind_all_with_allowed_hosts_keeps_validation(tmp_path):
    """0.0.0.0 WITH pinned hostnames keeps Host validation enabled."""
    from openzim_mcp.server import _build_transport_security

    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        transport="http",
        host="0.0.0.0",  # noqa: S104 — exercising the bind-all branch
        allowed_hosts=["mcp.example.com"],
        auth_token="s3cret",
    )
    settings, warning = _build_transport_security(cfg)
    assert settings.enable_dns_rebinding_protection is True
    assert "mcp.example.com" in set(settings.allowed_hosts)
    assert warning is None


def test_fastmcp_bind_all_server_constructs(tmp_path):
    """A 0.0.0.0-bound http server builds without raising and disables protection."""
    from openzim_mcp.server import OpenZimMcpServer

    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        transport="http",
        host="0.0.0.0",  # noqa: S104 — exercising the bind-all branch
        auth_token="s3cret",
    )
    server = OpenZimMcpServer(cfg)
    sec = server.mcp.settings.transport_security  # type: ignore[union-attr]
    assert sec is not None
    assert sec.enable_dns_rebinding_protection is False


# ---------------------------------------------------------------------------
# M6 — readyz must not run blocking stat syscalls on the event loop
# ---------------------------------------------------------------------------


@pytest.fixture
def http_mock_server(tmp_path):
    config = OpenZimMcpConfig(
        allowed_directories=[tempfile.gettempdir()], transport="http"
    )
    config.allowed_directories = [str(tmp_path)]
    server = MagicMock()
    server.config = config
    return server


def test_readyz_times_out_to_503_when_probe_hangs(http_mock_server, monkeypatch):
    """A hung allowed-directory stat returns a fast 503 instead of blocking."""
    import openzim_mcp.http_app as http_app

    monkeypatch.setattr(http_app, "READYZ_PROBE_TIMEOUT_SECONDS", 0.05)

    def hanging_isdir(_d):
        import time

        time.sleep(0.5)  # >> the 0.05s probe timeout; would freeze the loop inline
        return True

    monkeypatch.setattr(http_app.os.path, "isdir", hanging_isdir)

    app = http_app.build_starlette_app(http_mock_server)
    client = TestClient(app)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert "timed out" in resp.json()["reason"]


# ---------------------------------------------------------------------------
# M12 — rate limiter must actually be enforced
# ---------------------------------------------------------------------------


def test_enforce_rate_limit_returns_error_payload_when_exhausted():
    from openzim_mcp.rate_limiter import RateLimitConfig, RateLimiter
    from openzim_mcp.tools._common import enforce_rate_limit

    server = MagicMock()
    server.rate_limiter = RateLimiter(
        RateLimitConfig(enabled=True, requests_per_second=1.0, burst_size=2)
    )

    # Burst of 2 allowed, then the limiter trips.
    assert enforce_rate_limit(server, "zim_query") is None
    assert enforce_rate_limit(server, "zim_query") is None
    blocked = enforce_rate_limit(server, "zim_query")
    assert blocked is not None
    assert blocked["error"] is True
    assert blocked["operation"] == "rate_limited"


def test_enforce_rate_limit_noop_when_disabled():
    from openzim_mcp.rate_limiter import RateLimitConfig, RateLimiter
    from openzim_mcp.tools._common import enforce_rate_limit

    server = MagicMock()
    server.rate_limiter = RateLimiter(RateLimitConfig(enabled=False))
    for _ in range(100):
        assert enforce_rate_limit(server, "zim_query") is None
