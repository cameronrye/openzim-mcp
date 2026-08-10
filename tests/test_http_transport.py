"""HTTP transport smoke + health endpoints."""

import tempfile
from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def mock_server():
    """Build an OpenZimMcpServer-like mock with a tmp config."""
    from openzim_mcp.config import OpenZimMcpConfig

    config = OpenZimMcpConfig(
        allowed_directories=[tempfile.gettempdir()], transport="http"
    )
    server = MagicMock()
    server.config = config
    return server


def test_healthz_returns_ok(mock_server, tmp_path):
    """Liveness endpoint always returns 200."""
    mock_server.config.allowed_directories = [str(tmp_path)]
    from openzim_mcp.http_app import build_starlette_app

    app = build_starlette_app(mock_server)
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_readyz_returns_ok_when_dirs_readable(mock_server, tmp_path):
    """Readiness returns 200 when at least one allowed dir is readable."""
    mock_server.config.allowed_directories = [str(tmp_path)]
    from openzim_mcp.http_app import build_starlette_app

    app = build_starlette_app(mock_server)
    client = TestClient(app)
    resp = client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


def test_readyz_returns_503_when_dirs_unreadable(mock_server):
    """Readiness fails 503 when no allowed dir is readable."""
    mock_server.config.allowed_directories = ["/nonexistent_path_xyz"]
    from openzim_mcp.http_app import build_starlette_app

    app = build_starlette_app(mock_server)
    client = TestClient(app)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"


def test_run_http_dispatches_to_serve_helper(monkeypatch, tmp_path):
    """server.run(streamable-http) routes through http_app.serve_streamable_http."""
    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.server import OpenZimMcpServer

    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        transport="http",
        host="127.0.0.1",
        port=8001,
    )
    server = OpenZimMcpServer(cfg)

    called = []
    monkeypatch.setattr(
        "openzim_mcp.http_app.serve_streamable_http",
        lambda s: called.append(s),
    )
    server.run(transport="streamable-http")
    assert called == [server]


def test_check_safe_startup_warns_when_localhost_resolves_to_public(monkeypatch):
    """When /etc/hosts maps 'localhost' to a public IP, treat as public.

    `localhost` is conventionally loopback, but a misconfigured /etc/hosts
    can map it elsewhere. Resolve it and only accept 127.0.0.1/::1; emit a
    UserWarning and require a token otherwise.
    """
    import socket
    import warnings

    from openzim_mcp.exceptions import OpenZimMcpConfigurationError
    from openzim_mcp.http_app import check_safe_startup

    monkeypatch.setattr(
        socket,
        "gethostbyname",
        lambda host: "203.0.113.5" if host == "localhost" else host,
    )

    config = MagicMock()
    config.transport = "http"
    config.host = "localhost"
    config.auth_token = None  # no token → must REFUSE because not loopback
    config.insecure_disable_auth = False

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with pytest.raises(OpenZimMcpConfigurationError):
            check_safe_startup(config)

    assert any(
        "localhost" in str(w.message) and "loopback" in str(w.message).lower()
        for w in caught
    ), f"Expected a UserWarning about localhost not being loopback; got {caught!r}"


def test_check_safe_startup_localhost_resolving_to_loopback_is_safe(monkeypatch):
    """When 'localhost' resolves to 127.0.0.1, it remains safe with no token."""
    import socket

    from openzim_mcp.http_app import check_safe_startup

    monkeypatch.setattr(socket, "gethostbyname", lambda host: "127.0.0.1")
    config = MagicMock()
    config.transport = "http"
    config.host = "localhost"
    config.auth_token = None
    # Should not raise.
    check_safe_startup(config)


def test_is_loopback_host_bounds_slow_localhost_resolution(monkeypatch):
    """A hung resolver must not stall startup.

    ``socket.gethostbyname`` calls the libc resolver directly, so
    ``socket.setdefaulttimeout`` never bounds it — the resolution must
    run under a real deadline, with a timeout treated as not-loopback.
    """
    import socket
    import time

    from openzim_mcp.http_app import _is_loopback_host

    def slow_resolve(host):
        time.sleep(4.0)
        return "127.0.0.1"

    monkeypatch.setattr(socket, "gethostbyname", slow_resolve)
    start = time.monotonic()
    result = _is_loopback_host("localhost")
    elapsed = time.monotonic() - start
    assert result is False
    assert elapsed < 3.0


_LOOPBACK_HOSTS = {"127.0.0.1:*", "localhost:*", "[::1]:*"}
_BARE_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "[::1]"}


def test_build_transport_allowed_hosts_port_expands_bare_hosts():
    """A bare configured host is port-expanded so proxied ``Host: h:443`` passes.

    The SDK matcher (``mcp.server.transport_security``) only matches a
    ``base_host:port`` request against an allow-list pattern ending in
    ``:*``; a bare entry like ``mcp.example.com`` matches ONLY the exact
    portless host, so a reverse proxy forwarding ``Host: mcp.example.com:443``
    is rejected with 421. Expanding each bare host to also include
    ``host:*`` fixes that without the operator having to know the rule.
    """
    from openzim_mcp.server import _build_transport_allowed_hosts

    result = set(
        _build_transport_allowed_hosts(["mcp.example.com", "alt.example.com:*"])
    )

    # Bare host gains a wildcard-port variant (the fix); an entry that already
    # carries ``:*`` is left as-is. Assert via set algebra rather than ``in``
    # so static analyzers don't read the host literals as URL substring checks.
    assert {"mcp.example.com", "mcp.example.com:*", "alt.example.com:*"} <= result
    # The explicit ``:*`` entry is NOT double-expanded to ``:*:*``.
    assert result.isdisjoint({"alt.example.com:*:*"})
    # Loopback stays reachable in both bare and wildcard-port forms.
    assert (_LOOPBACK_HOSTS | _BARE_LOOPBACK_HOSTS) <= result


def test_server_resolves_transport_security_when_hosts_configured(tmp_path) -> None:
    """allowed_hosts resolves into TransportSecuritySettings at construction.

    Loopback values are always present in the resulting allow-list so that
    direct localhost access keeps working alongside the proxied hostname.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.server import OpenZimMcpServer

    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        transport="http",
        allowed_hosts=["mcp.example.com", "alt.example.com:*"],
    )
    server = OpenZimMcpServer(cfg)

    # Transport security is no longer a constructor kwarg with a home on a
    # settings object — the server resolves it eagerly into
    # ``_transport_security`` and hands it to ``streamable_http_app()`` at
    # serve time. We assert via set-superset rather than per-element ``in``
    # so neither (a) future SDK additions to the loopback defaults nor (b)
    # order changes break the test, and so static analyzers don't mistake
    # list-membership for URL substring matching.
    sec: TransportSecuritySettings = server._transport_security
    assert sec is not None
    hosts = set(sec.allowed_hosts)
    # Bare ``mcp.example.com`` is port-expanded so a proxied ``Host: …:443``
    # passes; the explicit ``alt.example.com:*`` is left as-is (not doubled).
    assert hosts >= (
        _LOOPBACK_HOSTS
        | _BARE_LOOPBACK_HOSTS
        | {"mcp.example.com", "mcp.example.com:*", "alt.example.com:*"}
    )
    assert hosts.isdisjoint({"alt.example.com:*:*"})


def test_transport_security_loopback_only_when_hosts_unset(tmp_path) -> None:
    """Loopback bind + empty allowed_hosts ⇒ loopback-only Host allow-list.

    For a loopback bind (the default host 127.0.0.1) we now always construct
    TransportSecuritySettings explicitly (H10), but its allow-list is the
    loopback entries only — the right behavior for purely local deployments,
    and unchanged from the previous SDK-auto-enable default.
    """
    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.server import OpenZimMcpServer

    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        transport="http",
    )
    server = OpenZimMcpServer(cfg)
    sec = server._transport_security
    assert sec is not None
    hosts = set(sec.allowed_hosts)
    assert hosts >= _LOOPBACK_HOSTS
    assert hosts.isdisjoint({"mcp.example.com"})


def test_transport_security_mirrors_cors_origins_into_allowed_origins(
    tmp_path,
) -> None:
    """``cors_origins`` is mirrored into the SDK's ``allowed_origins``.

    The SDK's transport security validates the Origin header (separate from
    CORS — application-layer DNS-rebinding defense) against
    ``allowed_origins``. Without populating it, every browser request fails
    with ``403 Invalid Origin header`` even after CORS preflight succeeds.
    Reusing ``cors_origins`` is correct because the two encode the same
    trust decision: an origin we let into CORS is one we let past the
    rebinding check.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.server import OpenZimMcpServer

    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        transport="http",
        allowed_hosts=["mcp.example.com"],
        cors_origins=["https://app.example.com", "https://chat.example.com"],
    )
    server = OpenZimMcpServer(cfg)

    sec: TransportSecuritySettings = server._transport_security
    assert sec is not None
    origins = set(sec.allowed_origins)
    assert origins == {"https://app.example.com", "https://chat.example.com"}


def test_transport_security_allowed_origins_empty_when_cors_unset(tmp_path) -> None:
    """No cors_origins ⇒ empty SDK allowed_origins.

    Non-browser MCP clients send no Origin header and bypass the SDK's
    origin check, so the empty list is the right default for deployments
    that only serve curl/desktop MCP clients.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.server import OpenZimMcpServer

    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        transport="http",
        allowed_hosts=["mcp.example.com"],
    )
    server = OpenZimMcpServer(cfg)

    sec: TransportSecuritySettings = server._transport_security
    assert sec is not None
    assert list(sec.allowed_origins) == []


def test_transport_security_unresolved_when_transport_stdio(tmp_path) -> None:
    """allowed_hosts is HTTP-only; stdio transport doesn't surface a Host header.

    On stdio there is no ASGI app to hand settings to, so the server leaves
    ``_transport_security`` unresolved rather than building an allow-list that
    nothing would ever consult.
    """
    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.server import OpenZimMcpServer

    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        transport="stdio",
        allowed_hosts=["mcp.example.com"],
    )
    server = OpenZimMcpServer(cfg)
    assert server._transport_security is None


def test_serve_streamable_http_runs_safe_check_and_serves(
    monkeypatch, tmp_path
) -> None:
    """serve_streamable_http calls check_safe_startup, builds app, runs uvicorn."""
    from openzim_mcp.http_app import serve_streamable_http

    server = MagicMock()
    server.config.host = "127.0.0.1"
    server.config.port = 8001
    server.config.transport = "http"
    server.config.auth_token = None
    server.config.cors_origins = []
    # Stub the MCPServer-like surface. ``subscription_bus`` is pinned to None
    # so the watcher-wiring branch stays out of this test's way (it has its
    # own coverage); a bare MagicMock attribute would read as "enabled".
    sentinel_security = object()
    server._transport_security = sentinel_security
    server.subscription_bus = None
    fake_app = MagicMock()
    server.mcp.streamable_http_app.return_value = fake_app

    safe_calls = []
    runner_calls = []
    monkeypatch.setattr(
        "openzim_mcp.http_app.check_safe_startup",
        lambda c: safe_calls.append(c),
    )

    def fake_runner(app, host, port):
        runner_calls.append((app, host, port))

    serve_streamable_http(server, runner=fake_runner)
    assert safe_calls == [server.config]
    assert len(runner_calls) == 1
    assert runner_calls[0][1:] == ("127.0.0.1", 8001)
    # Health routes are registered through the SDK's public custom_route
    # decorator now (the private _custom_starlette_routes list it used to
    # append to is no longer part of the contract). Each call returns the
    # decorator, which is then applied to the handler — so assert both the
    # registration arguments and that a handler was actually decorated.
    registered = {
        call.args[0]: call.kwargs["methods"]
        for call in server.mcp.custom_route.call_args_list
    }
    assert registered == {"/healthz": ["GET"], "/readyz": ["GET"]}
    decorated = server.mcp.custom_route.return_value.call_args_list
    assert len(decorated) == 2
    assert all(callable(call.args[0]) for call in decorated)
    # Transport config reaches the app builder as arguments (there is no
    # settings object to mutate ahead of the call).
    server.mcp.streamable_http_app.assert_called_once_with(
        host="127.0.0.1", transport_security=sentinel_security
    )
    # Auth + CORS middleware get added (auth always; CORS only if origins set)
    assert fake_app.add_middleware.called
