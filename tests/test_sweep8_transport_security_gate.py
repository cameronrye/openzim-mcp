"""A rejected request must not cost a session.

Era routing sends any request without an ``MCP-Protocol-Version`` header down
the SDK's legacy branch, which creates the transport, registers it in the
manager's session table and starts its task *before* the handler validates
Host/Origin. On mcp 2.1 a request answered ``403 Invalid Origin header`` left
that session and task in place until the process exited (#453). From 2.2 the
SDK discards it once it has answered, so the table comes back empty with or
without the gate; what the gate still prevents is the transport being built
at all, which is what these tests count.

The default HTTP deployment is the exposed one — ``127.0.0.1``, no token
(which ``check_safe_startup`` permits), no CORS origins — so neither of the
other middlewares stops anything.
"""

from __future__ import annotations

import gc
from pathlib import Path
from typing import Any, List

import httpx
import pytest
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from openzim_mcp import http_app
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


def _build_app(allowed: str, **overrides: Any):
    cfg = OpenZimMcpConfig(
        allowed_directories=[allowed],
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
async def test_rejected_origin_allocates_no_session(
    tmp_path: Path, minted_transports: List[object]
) -> None:
    _server, app = _build_app(str(tmp_path))
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
            assert minted_transports == [], (
                f"{len(minted_transports)} transports built for requests the "
                "gate should have answered"
            )
            # Control: the same client, minus the hostile Origin, does reach
            # the SDK, so the zero above is the gate and not a dead counter.
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 99,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "control", "version": "0"},
                    },
                },
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                },
            )
            assert response.status_code == 200, response.text
            assert len(minted_transports) == 1


@pytest.mark.asyncio
async def test_health_endpoints_stay_reachable(tmp_path: Path) -> None:
    """The gate must not shadow the probes the deployment guide documents."""
    _server, app = _build_app(str(tmp_path))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8791"
    ) as client:
        async with app.router.lifespan_context(app):
            for path in ("/healthz", "/readyz"):
                response = await client.get(path, headers={"Origin": "http://evil.x"})
                assert response.status_code == 200, (path, response.text)
