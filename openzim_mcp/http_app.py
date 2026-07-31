"""HTTP-mode helpers for OpenZIM MCP.

Provides the Starlette app the FastMCP server is mounted on, plus health
endpoints, auth middleware, and CORS for streamable-HTTP transport.

This module exists so server.py stays focused on MCP-protocol concerns and
HTTP-specific behavior is grouped here.
"""

import asyncio
import hashlib
import hmac
import logging
import os
import socket
import warnings
from concurrent.futures import Future
from contextlib import asynccontextmanager
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Mapping,
    Optional,
)

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

from .exceptions import OpenZimMcpConfigurationError, OpenZimMcpTimeoutError
from .timeout_utils import _get_executor, run_with_timeout

if TYPE_CHECKING:
    from .server import OpenZimMcpServer

logger = logging.getLogger(__name__)


HEALTHZ_PATH = "/healthz"
READYZ_PATH = "/readyz"

# Health endpoints exempt from auth.
AUTH_EXEMPT_PATHS = {HEALTHZ_PATH, READYZ_PATH}

# Upper bound on the /readyz allowed-directory stat probe. A hung network mount
# returns a fast 503 after this instead of stalling the event loop.
READYZ_PROBE_TIMEOUT_SECONDS = 5.0


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
        # gethostbyname calls the libc resolver directly, so it has no
        # per-call timeout (socket.setdefaulttimeout only affects Python
        # socket objects, not name resolution); on a flaky resolver it
        # would block startup indefinitely. Run it on a bounded worker
        # thread so a slow DNS doesn't hang the server; a timeout is
        # treated as not-loopback.
        try:
            resolved = run_with_timeout(
                lambda: socket.gethostbyname(host),
                1.0,
                "localhost DNS resolution timed out",
            )
        except (OSError, OpenZimMcpTimeoutError):
            return False
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
                "HTTP) with OPENZIM_MCP_AUTH_TOKEN. "
                "OPENZIM_MCP_INSECURE_DISABLE_AUTH does not apply to SSE."
            )
        return
    has_token = getattr(config, "auth_token", None) is not None
    if not is_localhost and not has_token:
        if getattr(config, "insecure_disable_auth", False):
            logger.warning(
                "INSECURE: HTTP transport bound to %s with no auth token "
                "(OPENZIM_MCP_INSECURE_DISABLE_AUTH=1). The server is "
                "trusting the surrounding network as the trust boundary. "
                "Anyone who can reach this address can call every tool.",
                host,
            )
            return
        raise OpenZimMcpConfigurationError(
            f"HTTP transport bound to {host} requires authentication. "
            "Set OPENZIM_MCP_AUTH_TOKEN, or bind to 127.0.0.1 for "
            "localhost-only access. (Use a reverse proxy for TLS termination.) "
            "If the surrounding network is your trust boundary (Docker bridge, "
            "Tailscale-only, isolated LAN) and you accept the risk, set "
            "OPENZIM_MCP_INSECURE_DISABLE_AUTH=1."
        )


async def healthz(request: Request) -> JSONResponse:
    """Liveness endpoint — process is up and event loop is responsive."""
    return JSONResponse({"status": "ok"})


def _make_readyz(
    server: "OpenZimMcpServer",
) -> Callable[[Request], Awaitable[JSONResponse]]:
    def _any_readable_dir() -> bool:
        return any(
            os.path.isdir(d) and os.access(d, os.R_OK)
            for d in server.config.allowed_directories
        )

    # The `concurrent.futures.Future` of the probe currently on the worker,
    # or None. Deliberately the CONCURRENT future and not the asyncio wrapper:
    # `wait_for` cancels the wrapper on timeout, so the wrapper is immediately
    # `.done()` (CANCELLED) while the real work is still running — the
    # single-flight check below would silently no-op against it.
    _readyz_inflight: Optional["Future[bool]"] = None

    async def readyz(request: Request) -> JSONResponse:
        """Readiness — at least one allowed directory is readable."""
        # os.path.isdir / os.access are blocking stat-family syscalls. On a
        # hung network mount (NFS/SMB) they freeze the event loop — and every
        # in-flight MCP request — for the full uninterruptible stat, exactly
        # the condition a readiness probe is meant to detect. Offload to a
        # thread and bound it so a wedged mount returns a fast 503 instead of
        # stalling the server (mirrors MtimeWatcher._scan's to_thread offload).
        #
        # The offload uses a DEDICATED single-slot pool, not `asyncio.to_thread`
        # (which runs on the loop's default executor — the same pool every
        # `AsyncZimOperations` call and `zim_query`'s own `to_thread` dispatch
        # uses). `wait_for` cannot cancel work already running in a thread, so
        # each timed-out probe permanently burned one default-executor worker;
        # `/readyz` is auth-exempt and unmetered by the rate limiter, so N
        # unauthenticated requests wedged every MCP tool call. The pool's
        # daemon workers also let the process exit while a probe is stuck.
        nonlocal _readyz_inflight
        # Single-flight by SHARING the in-flight probe, not by short-circuiting
        # to 503. Only one work item is ever outstanding, so a wedged stat can
        # never burn more than one worker — but concurrent probes against a
        # HEALTHY server still get the real answer. Reporting "probe timed out"
        # merely because another request was in flight would fail a readiness
        # check on a perfectly good instance and pull it from rotation.
        probe = _readyz_inflight
        if probe is None or probe.done():
            probe = _get_executor("readyz").submit(_any_readable_dir)
            _readyz_inflight = probe
        try:
            # `wait_for` cancels only this wrapper on timeout, never the
            # underlying thread, so a slow probe shared by several waiters
            # times each of them out independently and stays single-flight.
            ready = await asyncio.wait_for(
                asyncio.wrap_future(probe),
                timeout=READYZ_PROBE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return JSONResponse(
                {
                    "status": "not_ready",
                    "reason": "allowed-directory readiness probe timed out",
                },
                status_code=503,
            )
        if ready:
            return JSONResponse({"status": "ready"})
        return JSONResponse(
            {"status": "not_ready", "reason": "no readable allowed directories"},
            status_code=503,
        )

    return readyz


def _derive_client_id(request: Request, token: str) -> str:
    """Derive a stable client identifier from the request.

    Priority:
    1. Hash of the presented Bearer token (8 hex chars). Different tokens
       → different buckets, so per-token rate isolation works when
       operators issue one token per consumer.
    2. ``request.client.host`` when no token is set (the configuration
       allowed by ``OPENZIM_MCP_INSECURE_DISABLE_AUTH`` or a localhost
       bind with auth disabled). Per-IP isolation is the next best
       coarse-grained signal.
    3. ``"default"`` if neither is available.

    The token is hashed (not stored verbatim) so the rate-limiter's
    ``_global_buckets`` keys don't leak the secret if a stats endpoint
    is later added. Hash output is truncated to 8 hex chars — collision
    probability across a realistic operator's token set is negligible
    and the short form keeps log messages readable.
    """
    if token:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:8]
        return f"bearer:{digest}"
    if request.client is not None and request.client.host:
        return f"ip:{request.client.host}"
    return "default"


class BearerTokenAuthMiddleware(BaseHTTPMiddleware):
    """Reject requests without a valid Bearer token.

    Health endpoints (/healthz, /readyz) are exempt.
    Comparison is timing-safe via hmac.compare_digest.
    The attempted token is NEVER logged.

    Side effect: on successful auth (or on the no-token-configured fast
    path), sets ``request_context.client_id_var`` so the rate limiter
    can isolate buckets per-token. ContextVars propagate across the
    ``await call_next(request)`` boundary, so the value is visible
    inside every tool handler dispatched for this request.
    """

    def __init__(self, app: ASGIApp, config: object) -> None:
        """Capture the expected token from config (None disables auth)."""
        super().__init__(app)
        token = getattr(config, "auth_token", None)
        secret = token.get_secret_value() if token is not None else None
        # Defense in depth: an empty/whitespace secret must NOT authenticate
        # every request via ``hmac.compare_digest('', '')``. Config validation
        # already rejects a blank token at load time (H4); normalise here too
        # so the ``is None`` fast-path below treats it as "no auth configured".
        self._expected = secret if secret and secret.strip() else None

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Validate the Bearer token; pass through on success, 401 otherwise."""
        from .request_context import set_client_id

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
        # only happens for localhost binding). Still derive a client_id
        # from the remote address so per-IP isolation applies on the
        # insecure-localhost path.
        if self._expected is None:
            set_client_id(_derive_client_id(request, ""))
            return await call_next(request)

        # M28: RFC 6750 §3 requires ``realm`` on the Bearer challenge.
        # Some MCP SDK clients inspect the full challenge header to
        # decide whether to auto-inject a credential; a bare ``Bearer``
        # without ``realm`` is technically invalid and blocks that flow.
        _CHALLENGE = 'Bearer realm="openzim-mcp"'
        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer":
            self._log_failure(request, "missing_or_wrong_scheme")
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": _CHALLENGE},
            )
        # Compare as bytes: ``compare_digest`` raises TypeError on
        # non-ASCII str args, and Starlette decodes header bytes as
        # latin-1 — so a raw 0xE9 byte in the header (or a non-ASCII
        # configured token) would otherwise 500 instead of 401.
        if not hmac.compare_digest(
            token.encode("utf-8"), self._expected.encode("utf-8")
        ):
            self._log_failure(request, "invalid_token")
            return JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": (_CHALLENGE + ', error="invalid_token"')},
            )
        # Token validated. Set client_id for rate-limit isolation; the
        # hash is over the *presented* token (which matches the expected
        # token here, since compare_digest just verified it) so callers
        # presenting different tokens land on different rate buckets.
        set_client_id(_derive_client_id(request, token))
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
        # DELETE is the MCP streamable-HTTP method for explicit session
        # termination (per the spec; see also the SDK handler in
        # streamable_http.py: "Allow: GET, POST, DELETE"). Without it,
        # browser preflight blocks clean session shutdown.
        allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
        # Mcp-Session-Id is sent by streamable-HTTP clients on every request
        # after initialization to resume a session; Last-Event-ID is used to
        # resume interrupted streams; MCP-Protocol-Version is sent on every
        # post-init request per the MCP spec. Without allowing these, browser
        # CORS preflight rejects session-resume requests.
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Mcp-Session-Id",
            "Last-Event-ID",
            "MCP-Protocol-Version",
        ],
        expose_headers=["Mcp-Session-Id"],
    )


def build_starlette_app(server: "OpenZimMcpServer") -> Starlette:
    """Build the Starlette app served by streamable-HTTP transport.

    Includes /healthz, /readyz, and (later tasks) auth/CORS middleware.
    """
    return Starlette(
        routes=[
            Route(HEALTHZ_PATH, healthz),
            Route(READYZ_PATH, _make_readyz(server)),
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
            Route(HEALTHZ_PATH, healthz),
            Route(READYZ_PATH, _make_readyz(server)),
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
            # The watcher tick doubles as the registry's sweep: per-URI
            # containers left behind by disconnected sessions are otherwise
            # never reclaimed (see SubscriberRegistry.prune).
            registry=registry,
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
