"""HTTP-mode helpers for OpenZIM MCP.

Provides the Starlette app the FastMCP server is mounted on, plus health
endpoints, auth middleware, and CORS for streamable-HTTP transport.

This module exists so server.py stays focused on MCP-protocol concerns and
HTTP-specific behavior is grouped here.
"""

import hmac
import logging
import os
import socket
import warnings
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable, Mapping

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


def _is_loopback_host(host: str) -> bool:
    """Return True iff `host` is a loopback address on this machine.

    Accepts the literal IPv4/IPv6 loopback addresses directly. For the
    string "localhost", performs name resolution via socket.gethostbyname
    and only returns True if it resolves to 127.0.0.1 — this guards
    against /etc/hosts mapping "localhost" to a non-loopback address.

    On resolution failure, returns False (treated as not-loopback).
    """
    if host in ("127.0.0.1", "::1"):
        return True
    if host == "localhost":
        # gethostbyname has no per-call timeout; on a flaky resolver this
        # would block startup indefinitely. Set a short default timeout for
        # the duration of the call so a slow DNS doesn't hang the server.
        prev_timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(1.0)
            resolved = socket.gethostbyname(host)
        except OSError:
            return False
        finally:
            socket.setdefaulttimeout(prev_timeout)
        return resolved == "127.0.0.1"
    return False


def check_safe_startup(config: object) -> None:
    """Refuse to start if a network transport is exposed unsafely.

    Applied to network transports ('http' and 'sse'). Behavior differs:

    For transport='http' (streamable-HTTP, has bearer-auth + CORS middleware):
      * host=127.0.0.1, token unset    → OK (localhost-only, no auth)
      * host=127.0.0.1, token set      → OK
      * host=any other,  token unset   → REFUSE
      * host=any other,  token set     → OK

    For transport='sse' (no auth middleware):
      * host=127.0.0.1                 → OK
      * host=any other                 → REFUSE (no token escape — there
                                                 is no middleware to enforce
                                                 a token on the SSE path)

    Raises:
        OpenZimMcpConfigurationError: when binding unsafely.
    """
    transport = getattr(config, "transport", None)
    if transport not in ("http", "sse"):
        return
    host = getattr(config, "host", None)
    is_localhost = isinstance(host, str) and _is_loopback_host(host)
    # Distinguish "user typed 'localhost'" from "user typed an actual IP" so
    # we can emit a targeted warning when /etc/hosts maps localhost away
    # from loopback. Without this, a misconfigured host would silently fall
    # through to the public-host branch and the operator wouldn't know why
    # the safe-default check fired.
    if host == "localhost" and not is_localhost:
        warnings.warn(
            "Host 'localhost' does not resolve to loopback (127.0.0.1) on "
            "this machine; treating as a public host. Set the host "
            "explicitly to 127.0.0.1 (or fix /etc/hosts) if loopback was "
            "intended.",
            UserWarning,
            stacklevel=2,
        )
    if transport == "sse":
        if not is_localhost:
            raise OpenZimMcpConfigurationError(
                f"SSE transport bound to {host} is not allowed. SSE has no "
                "auth middleware in this server, so it must bind 127.0.0.1. "
                "For exposed deployments use --transport http (streamable "
                "HTTP) with OPENZIM_MCP_AUTH_TOKEN."
            )
        return
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
            # Health endpoints are public; OPTIONS preflight against them is
            # also fine (no secret to leak via the preflight response).
            return await call_next(request)

        # NOTE: We deliberately do NOT carve out a generic "OPTIONS bypasses
        # auth" path here. A blanket OPTIONS exemption lets non-browser
        # callers probe the MCP endpoint without a token, with no upside
        # (CORS preflight is still answered correctly by the outer CORS
        # middleware before this handler ever runs for legitimate browser
        # flows; for non-CORS-configured deployments there is no preflight
        # to worry about).

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
        # Mcp-Session-Id is sent by streamable-HTTP clients on every request
        # after initialization to resume a session; without allowing it,
        # browser CORS preflight rejects all session-resume requests.
        allow_headers=["Authorization", "Content-Type", "Mcp-Session-Id"],
        expose_headers=["Mcp-Session-Id"],
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
    # Order matters. Starlette's add_middleware is LIFO: the LAST-added
    # middleware becomes the OUTERMOST layer. We want CORS as the outer
    # layer so 401 responses from the inner auth middleware still carry
    # Access-Control-Allow-Origin headers (otherwise browser JS clients
    # see an opaque CORS error instead of "401 unauthorized").
    app.add_middleware(BearerTokenAuthMiddleware, config=server.config)
    apply_cors_middleware(app, server.config)

    # Wire the resource-subscription watcher when both the registry exists
    # (subscriptions enabled) and we have allowed dirs to watch.
    #
    # Why we wrap lifespan_context instead of using add_event_handler:
    # FastMCP's streamable_http_app() supplies a custom Starlette lifespan
    # (session_manager.run()), so Starlette's _DefaultLifespan — the only
    # path that iterates on_startup/on_shutdown — is never installed and
    # add_event_handler('startup', ...) silently does nothing.
    registry = server.subscriber_registry
    if registry is not None and server.config.allowed_directories:
        from . import subscriptions as _subs

        async def _on_change(uri: str, change_type: str) -> None:
            await _subs.broadcast_resource_updated(registry, uri)

        watcher = _subs.MtimeWatcher(
            server.config.allowed_directories,
            server.config.watch_interval_seconds,
            on_change=_on_change,
        )

        inner_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def lifespan_with_watcher(
            scoped_app: ASGIApp,
        ) -> AsyncIterator[Mapping[str, Any] | None]:
            await watcher.start()
            try:
                async with inner_lifespan(scoped_app) as state:
                    yield state
            finally:
                await watcher.stop()

        # mypy can't reconcile the @asynccontextmanager-produced
        # _AsyncGeneratorContextManager with the union type Starlette
        # declares for lifespan_context (Callable returning either of two
        # AbstractAsyncContextManager parameterizations). The runtime
        # types are compatible — _AsyncGeneratorContextManager subclasses
        # AbstractAsyncContextManager — so suppress here.
        app.router.lifespan_context = lifespan_with_watcher  # type: ignore[assignment]

    runner(app, server.config.host, server.config.port)
