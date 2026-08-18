"""A rejected request must not cost a session.

Era routing sends any request without an ``MCP-Protocol-Version`` header down
the SDK's legacy branch, which creates the transport, registers it in the
manager's session table and starts its task *before* the handler validates
Host/Origin. So a request answered ``403 Invalid Origin header`` had already
allocated a session and a live task, and nothing reaps them: the app builder
exposes no ``session_idle_timeout``, so the manager's idle-expiry branch never
runs and the table empties only on an explicit DELETE or process exit.

The default HTTP deployment is the exposed one — ``127.0.0.1``, no token
(which ``check_safe_startup`` permits), no CORS origins — so neither of the
other middlewares stops anything.
"""

from __future__ import annotations

import gc
from typing import Any, List

import httpx
import pytest
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from openzim_mcp import http_app
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

_ALLOWED = "test_data/zim-testing-suite/withns"


def _build_app(**overrides: Any):
    cfg = OpenZimMcpConfig(
        allowed_directories=[_ALLOWED],
        transport="http",
        host="127.0.0.1",
        port=8791,
        **overrides,
    )
    server = OpenZimMcpServer(cfg)
    captured: List[Any] = []
    http_app.serve_streamable_http(server, runner=lambda a, h, p: captured.append(a))
    return server, captured[0]


def _session_manager() -> StreamableHTTPSessionManager:
    managers = [
        o for o in gc.get_objects() if isinstance(o, StreamableHTTPSessionManager)
    ]
    assert managers, "no session manager constructed"
    return managers[-1]


@pytest.mark.asyncio
async def test_rejected_origin_allocates_no_session() -> None:
    _server, app = _build_app()
    manager = _session_manager()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8791"
    ) as client:
        async with app.router.lifespan_context(app):
            before = len(manager._server_instances)
            for i in range(10):
                response = await client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": i, "method": "ping"},
                    headers={
                        "Origin": "http://evil.example",
                        "Accept": "application/json, text/event-stream",
                        "Content-Type": "application/json",
                    },
                )
                assert response.status_code == 403, response.text
            assert len(manager._server_instances) == before, (
                "a rejected cross-origin request allocated a session: "
                f"{before} -> {len(manager._server_instances)}"
            )


@pytest.mark.asyncio
async def test_health_endpoints_stay_reachable() -> None:
    """The gate must not shadow the probes the deployment guide documents."""
    _server, app = _build_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8791"
    ) as client:
        async with app.router.lifespan_context(app):
            for path in ("/healthz", "/readyz"):
                response = await client.get(path, headers={"Origin": "http://evil.x"})
                assert response.status_code == 200, (path, response.text)
