"""CORS middleware for HTTP transport."""

from unittest.mock import MagicMock

from pydantic import SecretStr
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


def test_unauthorized_response_includes_cors_headers():
    """A 401 from auth middleware must still carry CORS headers.

    CORS must wrap auth so browser JavaScript clients can read the 401
    response. If auth is the outer layer (CORS inner), the browser sees
    an opaque network error and cannot tell that the token was wrong.
    """
    from openzim_mcp.http_app import BearerTokenAuthMiddleware, apply_cors_middleware

    config = MagicMock()
    config.auth_token = SecretStr("topsecret")
    config.cors_origins = ["https://allowed.example.com"]

    async def protected(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/protected", protected)])
    # Wire in the same order that serve_streamable_http uses so this test
    # exercises the production ordering.
    app.add_middleware(BearerTokenAuthMiddleware, config=config)
    apply_cors_middleware(app, config)

    client = TestClient(app)
    resp = client.get(
        "/protected",
        headers={"Origin": "https://allowed.example.com"},
    )
    assert resp.status_code == 401
    assert (
        resp.headers.get("access-control-allow-origin") == "https://allowed.example.com"
    )


def test_cors_preflight_allows_mcp_protocol_version_header():
    """MCP-Protocol-Version is sent on every post-init request per the MCP spec.

    Without this header in allow_headers, browser preflight rejects every
    request after the initial handshake — making the streamable-HTTP server
    unreachable from any browser MCP client.
    """
    app = _build_app(["http://localhost:5173"])
    client = TestClient(app)
    resp = client.options(
        "/hello",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "mcp-protocol-version",
        },
    )
    assert resp.status_code == 200
    allowed = resp.headers.get("access-control-allow-headers", "").lower()
    assert "mcp-protocol-version" in allowed


def test_cors_preflight_allows_last_event_id_header():
    """Last-Event-ID lets browser MCP clients resume interrupted streams.

    Without this header in allow_headers, browser preflight rejects stream
    resume requests before they reach the streamable-HTTP transport.
    """
    app = _build_app(["http://localhost:5173"])
    client = TestClient(app)
    resp = client.options(
        "/hello",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "last-event-id",
        },
    )
    assert resp.status_code == 200
    allowed = resp.headers.get("access-control-allow-headers", "").lower()
    assert "last-event-id" in allowed


def test_cors_preflight_allows_delete_for_session_termination():
    """The MCP streamable-HTTP spec defines DELETE for explicit session
    termination (the SDK's handler advertises ``Allow: GET, POST, DELETE``).

    Without DELETE in allow_methods, browser MCP clients cannot cleanly
    end a session and must abandon it (the server eventually times it out).
    """
    app = _build_app(["http://localhost:5173"])
    client = TestClient(app)
    resp = client.options(
        "/hello",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "DELETE",
        },
    )
    assert resp.status_code == 200
    assert "DELETE" in resp.headers.get("access-control-allow-methods", "")


def test_header_bearing_tool_params_are_cors_allowed(tmp_path):
    """Any tool param that travels as a header must be allowed through preflight.

    The 2026-07-28 revision lets a tool annotate an input property with
    ``x-mcp-header``; a modern client then sends that argument as an
    ``Mcp-Param-<token>`` request header rather than in the JSON body. No tool
    does that today, which is why ``CORS_ALLOW_HEADERS`` lists no such entry.

    The failure mode if one is added is silent and remote from its cause: the
    browser rejects the request at preflight, so the server never sees it and
    has nothing to log. This fails the build at the moment the annotation is
    added instead, naming the header that has to be listed.
    """
    import asyncio

    from mcp.shared.inbound import MCP_PARAM_HEADER_PREFIX, x_mcp_header_map

    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.http_app import CORS_ALLOW_HEADERS
    from openzim_mcp.server import OpenZimMcpServer

    server = OpenZimMcpServer(
        OpenZimMcpConfig(allowed_directories=[str(tmp_path)], tool_mode="advanced")
    )
    tools = asyncio.run(server.mcp.list_tools())
    allowed = {h.lower() for h in CORS_ALLOW_HEADERS}

    for tool in tools:
        for path, token in x_mcp_header_map(tool.input_schema).items():
            header = f"{MCP_PARAM_HEADER_PREFIX}{token}"
            assert header.lower() in allowed, (
                f"{tool.name}.{'.'.join(path)} is annotated x-mcp-header "
                f"{token!r}, so a modern client sends it as the {header} "
                "request header. Add it to CORS_ALLOW_HEADERS or browser "
                "clients fail preflight with no server-side trace."
            )
