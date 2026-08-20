"""Patches for defects in the pinned MCP SDK.

Two residents. Each has a canary test that fails the day the locked SDK
fixes the defect itself, which is the signal to delete the patch.

The first is the ping keepalive shim for
https://github.com/modelcontextprotocol/python-sdk/issues/3273. SDK 2.0.0's
per-version method tables lack ``("ping", "2026-07-28")``, in both directions
that matter to a server: ``CLIENT_REQUESTS`` (the runner's version gate, so
the request dies as -32601 before the SDK's own ping handler is consulted)
and ``SERVER_RESULTS`` (the outbound sieve, so fixing only the gate would
turn the miss into an unhandled ``KeyError`` mid-response). A modern client
that pings on a keepalive timer — FastMCP 4 does — sees an error per ping
and flaps the connection.

The tables are ``MappingProxyType`` views over module-private dicts, and the
SDK binds them as call-time *defaults*, so neither rebinding the module
attribute nor passing ``surface=`` from our layer can reach the runner's
calls. The one seam that reaches every consumer is the dict under the proxy:
a proxy is a live view, so inserting the missing rows there is exactly the
edit upstream's fix will make to the literal. ``gc.get_referents`` is how
CPython hands out that dict; it is deliberate surgery on SDK internals,
confined to this module and covered by ``tests/test_sdk_ping_shim.py``.

Retirement: the canary in ``tests/test_sdk_ping_shim.py`` fails the day the
locked SDK ships the rows itself. Delete the shim, its install call in
``server.py``, and the canary file; the wire tests in ``test_mcp_session.py``
stay.

The second is :func:`stdio_server_answering_malformed_frames`. The SDK's stdio
reader forwards any line ``jsonrpc_message_adapter`` rejects — undecodable
JSON, a JSON-RPC batch array, a bare string, an object missing ``jsonrpc`` —
as a bare ``Exception`` item on the read stream, and the server-side
dispatcher, which installs no ``on_stream_exception`` observer, drops those
items at debug level. JSON-RPC 2.0 requires a ``-32700`` (id null) for a
parse failure and a ``-32600`` for an invalid Request object, and the SDK's
own HTTP transports do answer them; only the stdio path is silent, so a
hand-rolled client waiting on such an id hangs with no diagnostic anywhere.
The wrapper relays the read stream and answers the ``Exception`` items on
the write stream itself, so the serving loop never sees them. It is wiring
around the transport rather than surgery inside it, which is why it needs
no private-dict access.

Retirement: the canary in ``tests/test_v3_field_fixes_protocol.py`` runs the
SDK's stdio server bare and fails when it starts answering these frames.
Delete the wrapper and the ``run_stdio_async`` override in
``mcp_envelope.py``; the wire tests beside the canary stay.
"""

import gc
import logging
from collections import Counter
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from types import TracebackType
from typing import Any, cast

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.server.stdio import stdio_server
from mcp.shared._stream_protocols import ReadStream, WriteStream
from mcp.shared.dispatcher import coerce_request_id
from mcp.shared.jsonrpc_dispatcher import cancelled_request_id_from_params
from mcp.shared.message import SessionMessage
from mcp_types import (
    INVALID_REQUEST,
    PARSE_ERROR,
    ErrorData,
    JSONRPCError,
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    RequestId,
)
from mcp_types.methods import CLIENT_REQUESTS, SERVER_RESULTS
from pydantic import ValidationError

logger = logging.getLogger(__name__)

MODERN_PING_ROW = ("ping", "2026-07-28")

# How long, after stdin closes, already-read requests may still be answered.
#
# EOF means the client has nothing more to say, not that it has stopped
# listening: ``printf '<request>' | server`` closes stdin before the server
# has even parsed the line. The SDK dispatcher cancels every in-flight handler
# the moment its read stream ends, so the frame layer holds that EOF back
# until each request it forwarded has been answered — bounded, because a
# handler that never answers (none of this server's do, but the bound is what
# makes that claim safe) must not keep the process alive after its client
# hung up.
STDIN_EOF_DRAIN_TIMEOUT_S = 30.0

# The newest revision whose ping rows upstream does define. Ping's wire shape
# did not change in 2026 — the gap is a missing table entry, not a missing
# schema — so the modern rows are copies of these, which also keeps this
# module off the ``mcp_types._v*`` internal packages.
_PREVIOUS_PING_ROW = ("ping", "2025-11-25")

# Captured before ``install_ping_keepalive_shim`` can have run: the module
# body executes on first import and the only caller lives below it. The
# canary test asserts this is still False; when it flips, the SDK has fixed
# python-sdk#3273 and this module must be deleted.
UPSTREAM_DEFINES_MODERN_PING = (
    MODERN_PING_ROW in CLIENT_REQUESTS and MODERN_PING_ROW in SERVER_RESULTS
)


def _underlying_dict(proxy: Mapping[Any, Any]) -> dict[Any, Any]:
    """The mutable dict a ``MappingProxyType`` is a view of."""
    return cast(dict[Any, Any], gc.get_referents(proxy)[0])


def install_ping_keepalive_shim() -> bool:
    """Add ping's 2026-07-28 rows to the SDK's method tables.

    Idempotent, and a no-op against an SDK that defines the rows itself.
    Returns True when anything was added, so a caller (or test) can tell a
    real install from a redundant one.
    """
    added = False
    for table in (CLIENT_REQUESTS, SERVER_RESULTS):
        rows = _underlying_dict(table)
        if MODERN_PING_ROW not in rows:
            rows[MODERN_PING_ROW] = rows[_PREVIOUS_PING_ROW]
            added = True
    if added:
        logger.debug(
            "Installed ping keepalive shim for python-sdk#3273; "
            "modern connections can now be kept alive"
        )
    return added


def _rejection(code: int, message: str, request_id: RequestId | None) -> JSONRPCError:
    return JSONRPCError(
        jsonrpc="2.0", id=request_id, error=ErrorData(code=code, message=message)
    )


def _usable_request_id(value: Any) -> RequestId | None:
    """``value`` if it is an id the wire accepts (str or non-bool int), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, str)):
        return value
    return None


def _rejected_frame(errors: list[Any]) -> Any:
    """Recover the decoded frame from a shape-validation failure.

    pydantic reports the whole value as ``input`` for a top-level error (loc
    is just the union member) and the parent object for a ``missing`` field;
    one of the two is present for every frame the union can reject.
    """
    for err in errors:
        loc = err.get("loc", ())
        if len(loc) <= 1 or (err.get("type") == "missing" and len(loc) == 2):
            return err.get("input")
    return None


def rejection_for_frame(exc: Exception) -> JSONRPCError | None:
    """The JSON-RPC error a frame the transport could not decode deserves.

    ``None`` means answer nothing: a blank line carries no request anyone is
    waiting on, and answering it would turn a client's keepalive newlines
    into a stream of ``-32700``s.
    """
    if not isinstance(exc, ValidationError):
        return _rejection(INVALID_REQUEST, "Invalid Request", None)
    errors = exc.errors()
    raw = next(
        (e.get("input") for e in errors if e.get("type") == "json_invalid"), None
    )
    if raw is not None:
        if isinstance(raw, str) and not raw.strip():
            return None
        return _rejection(PARSE_ERROR, "Parse error: the line is not valid JSON", None)
    frame = _rejected_frame(errors)
    if isinstance(frame, list):
        return _rejection(
            INVALID_REQUEST,
            "Invalid Request: JSON-RPC batches are not supported by MCP "
            "(removed in 2025-06-18); send one message per line",
            None,
        )
    if not isinstance(frame, dict):
        return _rejection(
            INVALID_REQUEST,
            "Invalid Request: a JSON-RPC message must be an object",
            None,
        )
    return _rejection(
        INVALID_REQUEST,
        "Invalid Request: not a JSON-RPC 2.0 request, notification or response",
        _usable_request_id(frame.get("id")),
    )


async def _answer_rejected_frame(
    exc: Exception, write_stream: WriteStream[SessionMessage]
) -> None:
    rejection = rejection_for_frame(exc)
    if rejection is None:
        logger.debug("ignoring blank stdio line")
        return
    logger.warning(
        "rejected a malformed stdio frame with %d: %s",
        rejection.error.code,
        rejection.error.message,
    )
    try:
        await write_stream.send(SessionMessage(rejection))
    except (anyio.ClosedResourceError, anyio.BrokenResourceError):
        logger.debug("dropped rejection for a malformed frame: write stream closed")


class _InFlightRequests:
    """Client requests forwarded to the serving loop and not yet answered.

    Keyed the way the dispatcher keys its own in-flight table (``"7"`` and
    ``7`` are one id), and counted rather than set-membered so two requests
    that share an id both have to be answered. A ``notifications/cancelled``
    retires its id: the dispatcher never answers a cancelled request, so
    waiting for that answer would only delay the exit.
    """

    def __init__(self) -> None:
        self._pending: Counter[RequestId] = Counter()
        self._drained = anyio.Event()
        self._drained.set()

    def __len__(self) -> int:
        return sum(self._pending.values())

    def note_read(self, message: JSONRPCMessage) -> None:
        if isinstance(message, JSONRPCRequest):
            self._pending[coerce_request_id(message.id)] += 1
            self._drained = anyio.Event()
        elif (
            isinstance(message, JSONRPCNotification)
            and message.method == "notifications/cancelled"
        ):
            cancelled = cancelled_request_id_from_params(message.params)
            if cancelled is not None:
                self._retire(cancelled)

    def note_written(self, message: JSONRPCMessage) -> None:
        if isinstance(message, (JSONRPCResponse, JSONRPCError)) and (
            message.id is not None
        ):
            self._retire(message.id)

    def _retire(self, request_id: RequestId) -> None:
        key = coerce_request_id(request_id)
        if self._pending[key] > 1:
            self._pending[key] -= 1
            return
        self._pending.pop(key, None)
        if not self._pending:
            self._drained.set()

    async def wait_drained(self) -> None:
        while self._pending:
            await self._drained.wait()


class _AnsweringWriteStream:
    """The transport's write stream, retiring each request it answers.

    Retirement happens only after the send has completed — the SDK's stdout
    writer then owns the frame and flushes it before the transport exits —
    so EOF can never be released on a response that is still in a buffer.
    """

    def __init__(
        self, inner: WriteStream[SessionMessage], in_flight: _InFlightRequests
    ) -> None:
        self._inner = inner
        self._in_flight = in_flight

    async def send(self, item: SessionMessage, /) -> None:
        await self._inner.send(item)
        self._in_flight.note_written(item.message)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def __aenter__(self) -> "_AnsweringWriteStream":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.aclose()


async def _drain_after_eof(in_flight: _InFlightRequests) -> None:
    """Hold the serving loop's EOF until forwarded requests are answered."""
    if not in_flight:
        return
    logger.debug("stdin closed with %d request(s) in flight; draining", len(in_flight))
    with anyio.move_on_after(STDIN_EOF_DRAIN_TIMEOUT_S) as drain:
        await in_flight.wait_drained()
    if drain.cancelled_caught:
        logger.warning(
            "stdin closed %.0fs ago and %d request(s) are still unanswered; "
            "abandoning them",
            STDIN_EOF_DRAIN_TIMEOUT_S,
            len(in_flight),
        )


async def _relay_frames(
    transport_read: ReadStream[SessionMessage | Exception],
    sink: MemoryObjectSendStream[SessionMessage | Exception],
    write_stream: WriteStream[SessionMessage],
    in_flight: _InFlightRequests,
) -> None:
    """Forward decoded frames; answer the ones the transport could not decode.

    EOF on the transport stops the forwarding, and the sink — whose closing
    is what ends the serving loop — closes only once the forwarded requests
    have been answered (or the drain bound has passed).
    """
    async with sink:
        try:
            async for item in transport_read:
                if isinstance(item, Exception):
                    await _answer_rejected_frame(item, write_stream)
                    continue
                in_flight.note_read(item.message)
                await sink.send(item)
        except (anyio.ClosedResourceError, anyio.BrokenResourceError):
            # The serving loop closed its end first; EOF either way.
            return
        await _drain_after_eof(in_flight)


@asynccontextmanager
async def stdio_server_answering_malformed_frames() -> AsyncIterator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        WriteStream[SessionMessage],
    ]
]:
    """``stdio_server()`` whose undecodable frames get -32700 / -32600 answers
    and whose stdin EOF waits for the requests already read to be answered.

    Same yield shape as the SDK's, so ``run_stdio_async`` swaps it in
    unchanged. The relay is sequential, so a rejection is written before any
    later frame is forwarded, and the error goes out on the transport's own
    write stream — the stdio server diverts fd 1 while serving, so nothing
    else can reach the wire.
    """
    async with stdio_server() as (transport_read, transport_write):
        in_flight = _InFlightRequests()
        write_stream = _AnsweringWriteStream(transport_write, in_flight)
        relay_send, relay_receive = anyio.create_memory_object_stream[
            SessionMessage | Exception
        ](0)
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(
                _relay_frames, transport_read, relay_send, write_stream, in_flight
            )
            try:
                yield relay_receive, write_stream
            finally:
                task_group.cancel_scope.cancel()
