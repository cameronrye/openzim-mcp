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
