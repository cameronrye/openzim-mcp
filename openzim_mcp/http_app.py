"""HTTP-mode helpers for OpenZIM MCP.

Provides the Starlette app the FastMCP server is mounted on, plus health
endpoints, auth middleware, and CORS for streamable-HTTP transport.

This module exists so server.py stays focused on MCP-protocol concerns and
HTTP-specific behavior is grouped here.
"""

import logging
import os
from typing import TYPE_CHECKING, Awaitable, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

if TYPE_CHECKING:
    from .server import OpenZimMcpServer

logger = logging.getLogger(__name__)


async def healthz(request: Request) -> JSONResponse:
    """Liveness endpoint — process is up and event loop is responsive."""
    return JSONResponse({"status": "ok"})


def _make_readyz(
    server: "OpenZimMcpServer",
) -> Callable[[Request], Awaitable[JSONResponse]]:
    async def readyz(request: Request) -> JSONResponse:
        """Readiness — at least one allowed directory is readable."""
        for d in server.config.allowed_directories:
            if os.path.isdir(d) and os.access(d, os.R_OK):
                return JSONResponse({"status": "ready"})
        return JSONResponse(
            {"status": "not_ready", "reason": "no readable allowed directories"},
            status_code=503,
        )

    return readyz


def build_starlette_app(server: "OpenZimMcpServer") -> Starlette:
    """Build the Starlette app served by streamable-HTTP transport.

    Includes /healthz, /readyz, and (later tasks) auth/CORS middleware.
    """
    return Starlette(
        routes=[
            Route("/healthz", healthz),
            Route("/readyz", _make_readyz(server)),
        ]
    )
