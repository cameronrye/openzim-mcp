"""HTTP-mode helpers for OpenZIM MCP.

Provides the Starlette app the FastMCP server is mounted on, plus health
endpoints, auth middleware, and CORS for streamable-HTTP transport.

This module exists so server.py stays focused on MCP-protocol concerns and
HTTP-specific behavior is grouped here.
"""

import hmac
import logging
import os
from typing import TYPE_CHECKING, Awaitable, Callable

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

from .exceptions import OpenZimMcpConfigurationError

if TYPE_CHECKING:
    from .server import OpenZimMcpServer

logger = logging.getLogger(__name__)


# Health endpoints exempt from auth.
AUTH_EXEMPT_PATHS = {"/healthz", "/readyz"}


def check_safe_startup(config: object) -> None:
    """Refuse to start if HTTP transport is exposed without a token.

    Applied only when transport='http'. The four cases:
      * host=127.0.0.1, token unset    → OK (localhost-only, no auth)
      * host=127.0.0.1, token set      → OK
      * host=any other,  token unset   → REFUSE
      * host=any other,  token set     → OK

    Raises:
        OpenZimMcpConfigurationError: when binding non-localhost without auth.
    """
    if getattr(config, "transport", None) != "http":
        return
    host = getattr(config, "host", None)
    is_localhost = host in ("127.0.0.1", "::1", "localhost")
    has_token = getattr(config, "auth_token", None) is not None
    if not is_localhost and not has_token:
        raise OpenZimMcpConfigurationError(
            f"HTTP transport bound to {host} requires authentication. "
            "Set OPENZIM_MCP_AUTH_TOKEN, or bind to 127.0.0.1 for "
            "localhost-only access. (Use a reverse proxy for TLS termination.)"
        )


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


class BearerTokenAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests without a valid Bearer token.

    Health endpoints (/healthz, /readyz) are exempt.
    Comparison is timing-safe via hmac.compare_digest.
    The attempted token is NEVER logged.
    """

    def __init__(self, app: ASGIApp, config: object) -> None:
        """Capture the expected token from config (None disables auth)."""
        super().__init__(app)
        token = getattr(config, "auth_token", None)
        self._expected = token.get_secret_value() if token is not None else None

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Validate the Bearer token; pass through on success, 401 otherwise."""
        if request.url.path in AUTH_EXEMPT_PATHS:
            return await call_next(request)

        # If no token configured, allow (the safe-default check ensures this
        # only happens for localhost binding).
        if self._expected is None:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer":
            self._log_failure(request, "missing_or_wrong_scheme")
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not hmac.compare_digest(token, self._expected):
            self._log_failure(request, "invalid_token")
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

    def _log_failure(self, request: Request, reason: str) -> None:
        client_host = request.client.host if request.client else "unknown"
        logger.warning(
            "auth failure: reason=%s client=%s path=%s",
            reason,
            client_host,
            request.url.path,
        )


def apply_cors_middleware(app: Starlette, config: object) -> None:
    """Attach CORS middleware to the app if any origins are configured."""
    origins = getattr(config, "cors_origins", None) or []
    if not origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


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


def _default_uvicorn_runner(app: Starlette, host: str, port: int) -> None:
    """Run the given Starlette app under uvicorn (blocking)."""
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    uvicorn.Server(config).run()


def serve_streamable_http(
    server: "OpenZimMcpServer",
    runner: Callable[[Starlette, str, int], None] = _default_uvicorn_runner,
) -> None:
    """Serve OpenZIM MCP over streamable-HTTP transport.

    Validates the safe-startup matrix, registers /healthz and /readyz on the
    underlying FastMCP Starlette app, applies bearer-token auth and CORS,
    then runs uvicorn.

    Args:
        server: the OpenZIM MCP server to serve.
        runner: callable that takes (app, host, port) and runs the server.
            Defaults to a uvicorn runner; tests inject a fake.
    """
    check_safe_startup(server.config)

    # Register health routes on the FastMCP-built app via its public-ish
    # custom-routes list (looked at SDK source — this is the documented hook).
    server.mcp._custom_starlette_routes.extend(
        [
            Route("/healthz", healthz),
            Route("/readyz", _make_readyz(server)),
        ]
    )

    # Tell FastMCP what host/port to advertise (settings are read by the SDK
    # in run_streamable_http_async; we still set them for consistency even
    # though we run uvicorn ourselves below).
    server.mcp.settings.host = server.config.host
    server.mcp.settings.port = server.config.port

    app = server.mcp.streamable_http_app()
    app.add_middleware(BearerTokenAuthMiddleware, config=server.config)
    apply_cors_middleware(app, server.config)

    # Wire the resource-subscription watcher when both the registry exists
    # (subscriptions enabled) and we have allowed dirs to watch.
    if server.subscriber_registry is not None and server.config.allowed_directories:
        from . import subscriptions as _subs

        async def _on_change(uri: str, change_type: str) -> None:
            await _subs.broadcast_resource_updated(server.subscriber_registry, uri)

        watcher = _subs.MtimeWatcher(
            server.config.allowed_directories,
            server.config.watch_interval_seconds,
            on_change=_on_change,
        )

        async def _start() -> None:
            await watcher.start()

        async def _stop() -> None:
            await watcher.stop()

        app.add_event_handler("startup", _start)
        app.add_event_handler("shutdown", _stop)

    runner(app, server.config.host, server.config.port)
