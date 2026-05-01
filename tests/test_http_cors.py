"""CORS middleware for HTTP transport."""

from unittest.mock import MagicMock

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def _build_app(cors_origins):
    from openzim_mcp.http_app import apply_cors_middleware

    config = MagicMock()
    config.cors_origins = cors_origins

    async def hello(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/hello", hello)])
    apply_cors_middleware(app, config)
    return app


def test_cors_disabled_by_default():
    """Empty cors_origins → no CORS headers emitted."""
    app = _build_app([])
    client = TestClient(app)
    resp = client.get("/hello", headers={"Origin": "http://example.com"})
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}


def test_cors_allows_listed_origin():
    """Listed origin gets allow-origin header echoed back."""
    app = _build_app(["http://localhost:5173"])
    client = TestClient(app)
    resp = client.get("/hello", headers={"Origin": "http://localhost:5173"})
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_blocks_unlisted_origin():
    """Unlisted origin → no allow-origin header."""
    app = _build_app(["http://localhost:5173"])
    client = TestClient(app)
    resp = client.get("/hello", headers={"Origin": "http://evil.com"})
    assert "access-control-allow-origin" not in {k.lower() for k in resp.headers}


def test_cors_preflight_options():
    """OPTIONS preflight returns the allow-origin header for listed origins."""
    app = _build_app(["http://localhost:5173"])
    client = TestClient(app)
    resp = client.options(
        "/hello",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
