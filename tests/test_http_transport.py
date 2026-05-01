"""HTTP transport smoke + health endpoints."""

from unittest.mock import MagicMock

import pytest
from starlette.testclient import TestClient


@pytest.fixture
def mock_server():
    """Build an OpenZimMcpServer-like mock with a tmp config."""
    from openzim_mcp.config import OpenZimMcpConfig

    config = OpenZimMcpConfig(allowed_directories=["/tmp"], transport="http")
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


def test_serve_streamable_http_runs_safe_check_and_serves(monkeypatch, tmp_path):
    """serve_streamable_http calls check_safe_startup, builds app, runs uvicorn."""
    from openzim_mcp.http_app import serve_streamable_http

    server = MagicMock()
    server.config.host = "127.0.0.1"
    server.config.port = 8001
    server.config.transport = "http"
    server.config.auth_token = None
    server.config.cors_origins = []
    # Stub the FastMCP-like surface
    server.mcp._custom_starlette_routes = []
    fake_app = MagicMock()
    server.mcp.streamable_http_app.return_value = fake_app
    server.mcp.settings = MagicMock()

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
    # Health routes were appended to the FastMCP custom routes list
    assert len(server.mcp._custom_starlette_routes) == 2
    paths = {r.path for r in server.mcp._custom_starlette_routes}
    assert paths == {"/healthz", "/readyz"}
    # Auth + CORS middleware get added (auth always; CORS only if origins set)
    assert fake_app.add_middleware.called
