"""Shared helper for tests that drive the HTTP health endpoints."""

from typing import Any

from starlette.applications import Starlette
from starlette.routing import Route

from openzim_mcp.http_app import HEALTHZ_PATH, READYZ_PATH, _make_readyz, healthz


def build_health_app(server: Any) -> Starlette:
    """Mount the production ``/healthz`` and ``/readyz`` handlers on a bare app.

    ``serve_streamable_http`` registers these same two handlers on the SDK's
    Starlette app through ``custom_route``. Mounting them alone lets a test
    reach them without the MCP transport, the auth middleware or CORS.
    """
    return Starlette(
        routes=[
            Route(HEALTHZ_PATH, healthz),
            Route(READYZ_PATH, _make_readyz(server)),
        ]
    )
