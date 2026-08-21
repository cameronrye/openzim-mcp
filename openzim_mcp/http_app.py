"""HTTP-mode helpers for OpenZIM MCP.

Provides the Starlette app the MCP server is mounted on, plus health
endpoints, auth middleware, and CORS for streamable-HTTP transport.

This module exists so server.py stays focused on MCP-protocol concerns and
HTTP-specific behavior is grouped here.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import socket
import warnings
from collections import deque
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
from starlette.datastructures import Headers
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .exceptions import OpenZimMcpConfigurationError, OpenZimMcpTimeoutError
from .timeout_utils import _get_executor, run_with_timeout

if TYPE_CHECKING:
    from .server import OpenZimMcpServer

logger = logging.getLogger(__name__)


HEALTHZ_PATH = "/healthz"
READYZ_PATH = "/readyz"

# The one route the SDK mints sessions on. Passed to the app builder *and* to
# the sessionless gate so the two cannot drift: a gate that guessed wrong
# would answer paths the router owns, turning a typo'd URL into a session
# complaint instead of a 404.
MCP_PATH = "/mcp"

# Health endpoints exempt from auth.
AUTH_EXEMPT_PATHS = {HEALTHZ_PATH, READYZ_PATH}

# Request headers a browser client may send to the MCP endpoint. A module
# constant rather than an inline literal so the policy is inspectable — see
# ``test_header_bearing_tool_params_are_cors_allowed``, which holds the one
# entry a future change could silently need.
#
# No ``Mcp-Param-*`` entry is listed, which is the decision on the 2026-07-28
# custom-header passthrough rather than an oversight. That revision lets a tool
# annotate an input property with ``x-mcp-header``, and a modern client then
# sends that argument as an ``Mcp-Param-<token>`` request header instead of in
# the JSON body. No tool here annotates one, so no such header is ever sent and
# allowing them would only widen what a browser may put on the wire. The
# coupling is the trap: adding the annotation to a tool schema breaks browser
# clients at preflight with nothing in the request itself to explain why, so
# the guard test fails until the header is listed here.
CORS_ALLOW_HEADERS = (
    "Authorization",
    "Content-Type",
    "Mcp-Session-Id",
    "Last-Event-ID",
    "MCP-Protocol-Version",
    "Mcp-Method",
    "Mcp-Name",
)

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
    # The shared asyncio wrapper for `_readyz_inflight`. Sweep follow-up:
    # `wrap_future` chains a done-callback onto the concurrent future and
    # nothing unchains it when a waiter times out, so a fresh per-request
    # wrapper grew the wedged probe's callback list without bound
    # (`/readyz` is auth-exempt and unmetered). One wrapper per probe;
    # `shield` already removes its own per-waiter callback on timeout.
    _readyz_inflight_wrapped: Optional["asyncio.Future[bool]"] = None

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
        nonlocal _readyz_inflight, _readyz_inflight_wrapped
        # Single-flight by SHARING the in-flight probe, not by short-circuiting
        # to 503. Only one work item is ever outstanding, so a wedged stat can
        # never burn more than one worker — but concurrent probes against a
        # HEALTHY server still get the real answer. Reporting "probe timed out"
        # merely because another request was in flight would fail a readiness
        # check on a perfectly good instance and pull it from rotation.
        probe = _readyz_inflight
        wrapped = _readyz_inflight_wrapped
        if probe is None or probe.done():
            probe = _get_executor("readyz").submit(_any_readable_dir)
            _readyz_inflight = probe
            wrapped = asyncio.wrap_future(probe)
            _readyz_inflight_wrapped = wrapped
        elif wrapped is None or wrapped.get_loop() is not asyncio.get_running_loop():
            # A wrapper is loop-bound; recreate it if the loop changed
            # under a still-running probe (test harnesses; a uvicorn
            # loop restart). Production keeps one loop, so the shared
            # wrapper stays one-per-probe.
            wrapped = asyncio.wrap_future(probe)
            _readyz_inflight_wrapped = wrapped
        try:
            # `shield` is load-bearing, not defensive. `wrap_future` chains via
            # `asyncio.futures._chain_future`, whose `_call_check_cancel` calls
            # `source.cancel()` on the *concurrent* future when the asyncio
            # wrapper is cancelled. `concurrent.futures.Future.cancel()` fails
            # while the work is RUNNING but SUCCEEDS while it is still queued —
            # so without the shield, the first waiter to time out discards the
            # shared work item and every co-waiter is cancelled too. That
            # raises `CancelledError`, which is a `BaseException` and so slips
            # past the `except asyncio.TimeoutError` below and out of the
            # handler, killing the request instead of answering 503.
            # Shielding cancels only the outer future, so each waiter times out
            # independently and the probe really does stay single-flight.
            ready = await asyncio.wait_for(
                asyncio.shield(wrapped),
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
        # The SDK serves both protocol eras on this one endpoint, so the
        # allow-list is the union of what each needs rather than just the
        # 2026-07-28 set. A 2025-era client still opens a session (GET stream,
        # DELETE to terminate, Mcp-Session-Id on every subsequent request,
        # Last-Event-ID to resume a dropped stream); a 2026-era client is
        # stateless and uses none of them. Dropping the legacy entries here
        # would break browser-based legacy clients while the deprecation
        # window is still open.
        allow_methods=["GET", "POST", "OPTIONS", "DELETE"],
        # MCP-Protocol-Version is sent by legacy clients post-initialize; the
        # 2026-07-28 revision also defines it as the header form of the
        # per-request protocol version. Mcp-Method and Mcp-Name are that
        # revision's required POST headers, and the SDK enforces them today: a
        # modern POST whose Mcp-Method disagrees with the body's method is
        # rejected with -32020, and tools/call additionally requires Mcp-Name.
        # Both are therefore load-bearing here, not forward-compatibility —
        # omitting them fails browser preflight for every 2026-era client.
        allow_headers=list(CORS_ALLOW_HEADERS),
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


# How long uvicorn waits for open connections to drain on SIGTERM/SIGINT
# before force-closing them.
#
# Load-bearing, not tuning. uvicorn's default is ``None`` — wait forever —
# and a ``subscriptions/listen`` stream never ends on its own: the SDK's SSE
# loop emits keepalive pings until the *client* disconnects. So a single
# subscribed client made this process unkillable by SIGTERM, and shutdown
# never reached the ASGI lifespan — which is where ``lifespan_with_watcher``
# stops the MtimeWatcher. ``docker stop`` burned its full grace period and
# then SIGKILLed, and SIGKILL skips ``atexit``, discarding the cache
# persistence save registered in ``OpenZimMcpCache.__init__``.
#
# Five seconds sits inside Docker's 10s default stop timeout (and any
# sane Kubernetes ``terminationGracePeriodSeconds``), so termination is
# clean rather than killed.
SHUTDOWN_GRACE_SECONDS = 5


def _default_uvicorn_runner(app: Starlette, host: str, port: int) -> None:
    """Run the given Starlette app under uvicorn (blocking)."""
    import uvicorn

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        timeout_graceful_shutdown=SHUTDOWN_GRACE_SECONDS,
    )
    uvicorn.Server(config).run()


class TransportSecurityGateMiddleware(BaseHTTPMiddleware):
    """Run the DNS-rebinding Host/Origin check *in front of* the SDK app.

    The SDK does the same validation, but on the legacy branch it does it too
    late to matter. Era routing sends any request without an
    ``MCP-Protocol-Version`` header down the legacy path, and that path creates
    the transport, registers it in the manager's session table and starts its
    task *before* calling into the handler where Host/Origin is checked. So a
    request answered ``403 Invalid Origin header`` has already allocated a
    session and a live task — and nothing reaps them: the app builder exposes
    no ``session_idle_timeout``, so the manager's idle-expiry branch is dead
    and the table is only ever emptied by an explicit DELETE or process exit.

    The default HTTP deployment is the exposed one: ``127.0.0.1`` with no token
    (which ``check_safe_startup`` permits) and no CORS origins, so neither of
    the other two middlewares stops anything. A page the user happens to visit
    can ``fetch()`` the endpoint in a loop; every request is rejected and every
    request leaks a session, until the process is killed for its memory.

    Health endpoints are exempt for the same reason they are exempt from auth.
    """

    def __init__(self, app: ASGIApp, security: Any) -> None:
        """Capture the resolved transport-security settings."""
        super().__init__(app)
        from mcp.server.transport_security import TransportSecurityMiddleware

        self._validator = TransportSecurityMiddleware(security)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Reject a request the SDK would reject, before it costs a session."""
        if request.url.path in AUTH_EXEMPT_PATHS:
            return await call_next(request)
        error = await self._validator.validate_request(
            request, is_post=request.method == "POST"
        )
        if error is not None:
            return error
        return await call_next(request)


def _is_initialize_request(body: bytes) -> bool:
    """True iff ``body`` is a JSON-RPC request the SDK would accept as ``initialize``.

    Mirrors what ``JSONRPCRequest`` validation lets through — ``jsonrpc`` of
    exactly ``"2.0"``, a string or (strict, so not bool) int ``id``, and
    ``params`` absent or an object — so the gate never turns away a request
    the SDK would have opened a session for, and never lets through one it
    would have rejected *after* opening a session.
    """
    try:
        message = json.loads(body)
    except (ValueError, RecursionError):
        # ``RecursionError`` is a ``RuntimeError``, not a ``ValueError``: a
        # body nested past the interpreter's limit is undecodable the same way
        # malformed JSON is, and must be answered rather than escape the gate.
        return False
    if not isinstance(message, dict) or message.get("method") != "initialize":
        return False
    if message.get("jsonrpc") != "2.0":
        return False
    request_id = message.get("id")
    if isinstance(request_id, bool) or not isinstance(request_id, (int, str)):
        return False
    return message.get("params", None) is None or isinstance(message["params"], dict)


def _accepts_json_and_sse(scope: Scope) -> bool:
    """Whether ``Accept`` satisfies the SDK's POST precondition.

    Delegated to the SDK's own parser so the gate's answer and the transport's
    stay in step, wildcards included. The app is built without
    ``json_response``, so the SSE branch applies: both types are required.
    """
    from mcp.server.streamable_http import check_accept_headers

    has_json, has_sse = check_accept_headers(Request(scope))
    return bool(has_json and has_sse)


class _BodyTooLarge(Exception):
    """A buffered sessionless body crossed the request-size cap mid-stream."""


class SessionlessRequestGateMiddleware:
    """Refuse handshake-era requests that have no session and are not ``initialize``.

    The SDK's stateful request path mints a transport, registers it in the
    session table and starts its serve loop for *any* request that lacks an
    ``Mcp-Session-Id`` header — and only then looks at the request. Every
    sessionless request except ``initialize`` is rejected at that point
    (``400 Missing session ID``), but the session it minted outlives the 400:
    the caller never learns it owns one, so no DELETE comes, and the idle-expiry
    branch is dead because the app builder exposes no ``session_idle_timeout``.
    A plain curl, a misbehaving client, or a page the user happens to visit can
    grow the table and the task count without bound on the default deployment.

    This gate answers those requests itself, with the SDK's own ``400`` body,
    before the SDK can mint anything. Only two kinds of request legitimately
    arrive without a session and must pass: an ``initialize`` POST (the session
    does not exist yet) and anything on the 2026-07-28 stateless path, which is
    routed by the ``MCP-Protocol-Version`` header and never has a session.
    ``initialize`` is only recognisable from the body, so a sessionless POST is
    buffered — under the SDK's request-size cap, which it mirrors — and replayed
    to the app. A body the gate can neither parse nor recognise gets the same
    ``Missing session ID`` answer: whatever else is wrong with it, the request
    has no session and can never be served.

    A pure ASGI middleware rather than ``BaseHTTPMiddleware`` so the body
    replay is explicit and bounded. It answers only on the MCP route: the
    health endpoints and every unrouted path belong to Starlette, which still
    404s them.
    """

    def __init__(
        self,
        app: ASGIApp,
        max_body_size: Optional[int] = None,
        mcp_path: str = MCP_PATH,
    ) -> None:
        """Wrap ``app``; ``max_body_size`` defaults to the SDK's request cap."""
        from mcp.server.streamable_http_manager import DEFAULT_MAX_REQUEST_BODY_SIZE

        self.app = app
        self._mcp_path = mcp_path
        self._max_body_size = (
            max_body_size
            if max_body_size is not None
            else DEFAULT_MAX_REQUEST_BODY_SIZE
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass through every request that cannot leak; answer the rest."""
        if scope["type"] != "http" or self._never_mints(scope):
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        if method in ("GET", "DELETE"):
            await self._reject_missing_session(scope, receive, send)
            return
        if method != "POST":
            # The SDK answers 405 for these too — after minting a session.
            await self._send_jsonrpc_error(
                scope,
                receive,
                send,
                "Method Not Allowed",
                405,
                extra_headers={"Allow": "GET, POST, DELETE"},
            )
            return
        if self._declares_oversized_body(Headers(scope=scope)):
            # The SDK's own body-limit middleware rejects this with 413
            # before its session code runs; no need to read it.
            await self.app(scope, receive, send)
            return

        try:
            cached, body = await self._buffer_body(receive)
        except _BodyTooLarge:
            response = Response("Request body too large", status_code=413)
            await response(scope, receive, send)
            return
        if body is None or not _is_initialize_request(body):
            # ``None``: disconnected mid-body — nothing to classify and nobody
            # to answer, but the outer middleware needs *a* response.
            await self._reject_missing_session(scope, receive, send)
            return
        if not _accepts_json_and_sse(scope):
            # The SDK validates ``Accept`` inside the transport it has already
            # minted, registered and task-started, so an ``initialize`` it is
            # about to refuse with 406 leaks a session all the same. Answer it
            # here, in the SDK's own words, before anything is minted.
            await self._send_jsonrpc_error(
                scope,
                receive,
                send,
                "Not Acceptable: Client must accept both application/json and "
                "text/event-stream",
                406,
            )
            return

        async def replay() -> Message:
            if cached:
                return cached.popleft()
            return await receive()

        await self.app(scope, replay, send)

    def _never_mints(self, scope: Scope) -> bool:
        """Whether the SDK serves this HTTP request without minting a session.

        Only the MCP route mints, so every other path — the health endpoints
        and anything the router will 404 — belongs to Starlette, not to this
        gate. Beyond that: a request that already names a session (live or
        unknown) takes a path that never mints, and a non-handshake
        ``MCP-Protocol-Version`` is era-routed to the stateless 2026-07-28
        handler.
        """
        from mcp.server.streamable_http import MCP_SESSION_ID_HEADER
        from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER
        from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS

        if scope["path"] != self._mcp_path:
            return True
        headers = Headers(scope=scope)
        if headers.get(MCP_SESSION_ID_HEADER) is not None:
            return True
        protocol_version = headers.get(MCP_PROTOCOL_VERSION_HEADER)
        return (
            protocol_version is not None
            and protocol_version not in HANDSHAKE_PROTOCOL_VERSIONS
        )

    def _declares_oversized_body(self, headers: Headers) -> bool:
        """Whether ``Content-Length`` already promises more than the body cap."""
        declared = headers.get("content-length")
        if declared is None:
            return False
        try:
            return int(declared) > self._max_body_size
        except ValueError:
            # A non-numeric Content-Length is not this gate's to police:
            # treat it as undeclared and let the chunked read enforce the cap.
            return False

    async def _buffer_body(
        self, receive: Receive
    ) -> "tuple[deque[Message], Optional[bytes]]":
        """Drain the request body, keeping the raw messages for replay.

        Returns the buffered messages and the complete body, or ``None`` for
        the body when the client disconnected before finishing it. Raises
        ``_BodyTooLarge`` the moment the running total crosses the cap.
        """
        cached: "deque[Message]" = deque()
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return cached, None
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self._max_body_size:
                raise _BodyTooLarge()
            body.extend(chunk)
            cached.append(message)
            if not message.get("more_body", False):
                return cached, bytes(body)

    async def _reject_missing_session(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        await self._send_jsonrpc_error(
            scope, receive, send, "Bad Request: Missing session ID", 400
        )

    async def _send_jsonrpc_error(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        message: str,
        status_code: int,
        extra_headers: Optional[Mapping[str, str]] = None,
    ) -> None:
        """Answer exactly as the SDK transport would, minus the session header."""
        from mcp_types import INVALID_REQUEST, ErrorData, JSONRPCError

        error = JSONRPCError(
            jsonrpc="2.0",
            id=None,
            error=ErrorData(code=INVALID_REQUEST, message=message),
        )
        response = Response(
            error.model_dump_json(by_alias=True, exclude_unset=True),
            status_code=status_code,
            headers=dict(extra_headers or {}),
            media_type="application/json",
        )
        await response(scope, receive, send)


def serve_streamable_http(
    server: "OpenZimMcpServer",
    runner: Callable[[Starlette, str, int], None] = _default_uvicorn_runner,
) -> None:
    """Serve OpenZIM MCP over streamable-HTTP transport.

    Validates the safe-startup matrix, registers /healthz and /readyz on the
    underlying MCPServer Starlette app, applies bearer-token auth and CORS,
    then runs uvicorn.

    Args:
        server: the OpenZIM MCP server to serve.
        runner: callable that takes (app, host, port) and runs the server.
            Defaults to a uvicorn runner; tests inject a fake.
    """
    check_safe_startup(server.config)

    # Register health routes through the SDK's public custom-route hook.
    #
    # Guarded because ``custom_route`` appends unconditionally: serving the
    # same server object twice (a retry after a failed bind, or an embedding
    # harness) would stack duplicate Route objects that Starlette can never
    # reach — it matches the first — while retaining every dead closure for
    # the process lifetime. The pre-port ``_custom_starlette_routes.extend``
    # had the same shape, so this is fixed at the seam rather than carried.
    _registered = {
        getattr(route, "path", None) for route in server.mcp._custom_starlette_routes
    }
    if HEALTHZ_PATH not in _registered:
        server.mcp.custom_route(HEALTHZ_PATH, methods=["GET"])(healthz)
    if READYZ_PATH not in _registered:
        server.mcp.custom_route(READYZ_PATH, methods=["GET"])(_make_readyz(server))

    # Transport configuration is an argument to the app builder on the v2 SDK
    # (there is no ``settings`` object to mutate). ``host`` feeds the SDK's
    # DNS-rebinding Host allow-list; we still run uvicorn ourselves below.
    app = server.mcp.streamable_http_app(
        streamable_http_path=MCP_PATH,
        host=server.config.host,
        transport_security=server._transport_security,
    )
    # Order matters. Starlette's add_middleware is LIFO: the LAST-added
    # middleware becomes the OUTERMOST layer. We want CORS as the outer
    # layer so 401 responses from the inner auth middleware still carry
    # Access-Control-Allow-Origin headers (otherwise browser JS clients
    # see an opaque CORS error instead of "401 unauthorized").
    # Added FIRST, so it is the INNERMOST layer: everything else answers
    # before it, and only a request that cleared auth and Host/Origin has its
    # body read. It is the last line between a sessionless request and the
    # SDK's session-minting code. See SessionlessRequestGateMiddleware.
    app.add_middleware(SessionlessRequestGateMiddleware)
    # Next-innermost: auth and CORS still get to answer first, but a request
    # that clears them is Host/Origin checked here rather than after the SDK
    # has already minted a session for it. See TransportSecurityGateMiddleware.
    if server._transport_security is not None:
        app.add_middleware(
            TransportSecurityGateMiddleware, security=server._transport_security
        )
    app.add_middleware(BearerTokenAuthMiddleware, config=server.config)
    apply_cors_middleware(app, server.config)

    # Wire the resource-change watcher when subscriptions are enabled (the bus
    # exists) and there are allowed dirs to watch.
    #
    # Why we wrap lifespan_context instead of using add_event_handler:
    # streamable_http_app() supplies its own Starlette lifespan, so
    # Starlette's _DefaultLifespan — the only path that iterates
    # on_startup/on_shutdown — is never installed and
    # add_event_handler('startup', ...) silently does nothing.
    bus = server.subscription_bus
    if bus is not None and server.config.allowed_directories:
        from . import subscriptions as _subs

        async def _on_change(uri: str, change_type: str) -> None:
            await _subs.publish_change(bus, uri, change_type)

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
