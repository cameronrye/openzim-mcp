"""MCP ``CallToolResult`` envelope conformance.

Phase F tools signal failure by *returning* a structured error envelope
(``{"error": true, "operation": ..., "message": ...}``, built by
:func:`openzim_mcp.responses.tool_error`) rather than by raising. That keeps
the failure machine-readable and lets a small model self-correct from the
``message`` — but it also meant the value travelled the SDK's ordinary success
path, so every failure reached the client with ``isError=false``.

That is a protocol defect, not a cosmetic one. Agent frameworks branch on
``isError`` to decide whether to surface, retry, or stop; with the flag always
false, a security denial is indistinguishable from a successful search that
happened to find nothing. Raising instead would fix the flag but discard the
envelope — the SDK stringifies exceptions into a bare text block.

:class:`EnvelopeAwareMCPServer` gets both. It intercepts the tool return value
before the SDK converts it, and when the value is an error envelope it emits a
``CallToolResult`` with ``is_error=True`` whose ``content`` is byte-identical to
what the plain dict return produced. Clients that parse the body keep working;
clients that check the flag start working.

The same class also stamps the per-URI half of the 2026-07-28 cache hints. The
server-wide ``cache_hints`` map is keyed by *method*, so one TTL has to cover
every ``resources/read`` — and because that method serves both sealed archives
and a live directory scan, the honest method-wide value is the short one. Only
a handler can tell the two apart, which is what :meth:`_handle_read_resource`
does here.
"""

from __future__ import annotations

import json
from typing import Any

import pydantic_core
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import (
    CallToolResult,
    InputRequiredResult,
    ReadResourceResult,
    TextContent,
    TextResourceContents,
)

__all__ = ["EnvelopeAwareMCPServer", "is_tool_error_envelope"]

# The one ``zim://`` URI whose content is not fixed by a sealed archive file:
# it is a live scan of the allowed directories, so it must keep the
# watcher-bounded TTL that the method-wide hint supplies.
_LIVE_SCAN_URI = "zim://files"

# Per-entry URIs (``zim://{name}/entry/{path}``) are archive-backed too, but
# the long TTL would be dishonest on them: a replacement publishes
# ``resources/updated`` only for the overview URI, and both SDK delivery and
# client-side eviction are exact-URI, so nothing could ever invalidate a
# cached entry read before the TTL ran out. They stay on the watcher-bounded
# method-wide hint instead.
_ENTRY_URI_MARKER = "/entry/"

# The exact keys ``responses.tool_error`` always sets. Matching all three (and
# ``error is True`` by identity, not truthiness) keeps an ordinary payload that
# merely carries an ``error`` field from being misread as a failure.
_ENVELOPE_REQUIRED_KEYS = ("error", "operation", "message")


def is_tool_error_envelope(value: Any) -> bool:
    """True when ``value`` is a :func:`openzim_mcp.responses.tool_error` payload."""
    if not isinstance(value, dict):
        return False
    if value.get("error") is not True:
        return False
    return all(
        isinstance(value.get(key), str)
        for key in _ENVELOPE_REQUIRED_KEYS
        if key != "error"
    )


def _is_overview_error_body(result: ReadResourceResult) -> bool:
    """True when a ``zim://{name}`` overview reported failure inside its body.

    The overview resource deliberately returns errors as *successful* JSON
    bodies — ``{"error": ...}`` for a missing archive, ``*_error`` keys for
    partial section failures (a contract pinned in ``test_resources.py``).
    Those bodies describe a moment, not the sealed archive, so they must not
    be stamped with the hour-long TTL: a cached not-found error would outlive
    the operator dropping the archive into place, and nothing ever publishes
    a ``resources/updated`` that could evict it.
    """
    if len(result.contents) != 1:
        return False
    sole = result.contents[0]
    if not isinstance(sole, TextResourceContents):
        return False
    # Cheap probe first. This runs on the response path of every archive-backed
    # read, and the alternative is re-parsing a body the handler just
    # serialized — full metadata dict, namespace summary, and up to a
    # 2000-character main-page preview — on the event loop, to answer one
    # boolean. Both key shapes end in ``error"`` once serialized, so a body
    # without that substring cannot be an error body; one that has it (an
    # article mentioning the word) still gets the exact check below.
    if 'error"' not in sole.text:
        return False
    try:
        payload = json.loads(sole.text)
    except ValueError:
        return False
    if not isinstance(payload, dict):
        return False
    return "error" in payload or any(key.endswith("_error") for key in payload)


def _serialize_envelope(payload: dict) -> str:
    """Render an envelope exactly as the SDK's dict-return path does.

    ``func_metadata._convert_to_content`` serializes a non-str result with
    ``pydantic_core.to_json(..., fallback=str, indent=2)``. Reusing the same
    call keeps the body byte-for-byte identical to the pre-fix wire format, so
    this stays a flag change rather than a payload change.
    """
    return pydantic_core.to_json(payload, fallback=str, indent=2).decode()


def error_result(payload: dict) -> CallToolResult:
    """Wrap an error envelope as a failed ``CallToolResult``.

    ``structuredContent`` is deliberately left unset: the tool advertises no
    ``outputSchema``, and per the MCP spec ``structuredContent`` is the
    counterpart to one. The envelope stays available as parseable JSON in
    ``content``, which is where every existing client already reads it.
    """
    return CallToolResult(
        content=[TextContent(type="text", text=_serialize_envelope(payload))],
        is_error=True,
    )


class EnvelopeAwareMCPServer(MCPServer):
    """``MCPServer`` that maps returned error envelopes onto ``is_error=True``.

    The override is at ``call_tool`` — the single point where every tool's
    return value passes through — so tools keep returning plain dicts and no
    registration site has to know about the protocol envelope.

    Args:
        archive_read_ttl_ms: TTL stamped on reads of archive-backed ``zim://``
            URIs. ``0`` leaves the result alone, so those reads fall back to
            the server-wide ``resources/read`` hint.
    """

    def __init__(self, *args: Any, archive_read_ttl_ms: int = 0, **kwargs: Any) -> None:
        """Capture the archive TTL, then defer to the SDK constructor."""
        super().__init__(*args, **kwargs)
        self._archive_read_ttl_ms = archive_read_ttl_ms

    async def _handle_read_resource(
        self, ctx: Any, params: Any
    ) -> ReadResourceResult | InputRequiredResult:
        """Stamp the long TTL on reads whose content a sealed archive fixes.

        ``apply_cache_hint`` fills only fields a handler left unset, so setting
        ``ttl_ms`` here wins over the method-wide hint for exactly these URIs
        while ``cache_scope`` still comes from the server-wide value. The
        result is built with ``model_copy(update=...)``, which records the
        field in ``model_fields_set`` — the flag the SDK keys that precedence
        on.

        This overrides a private SDK method, which the v2 port otherwise moved
        away from. It is the extension point the caching design implies: the
        SDK's own docs say a per-result hint is set "by returning a result with
        explicit ``ttl_ms``", and on this layer the only code that returns a
        ``ReadResourceResult`` is this handler — ``MCPServer`` binds it as
        ``on_read_resource`` at construction, so a subclass override is what
        the lowlevel server ends up calling. If a future SDK stops routing
        through it, the per-URI TTL tests fail rather than the hint silently
        reverting to the method-wide value.

        Which URIs qualify is stated as an exception rather than a match
        because every registered resource except ``zim://files`` is
        archive-backed. ``test_every_registered_resource_has_a_deliberate_ttl``
        fails if that stops being true. Two further carve-outs keep the long
        TTL honest: per-entry reads (see ``_ENTRY_URI_MARKER``) and overview
        reads whose JSON body reports an error (see
        ``_is_overview_error_body``) have no invalidation story, so they stay
        on the watcher-bounded method-wide hint.
        """
        result = await super()._handle_read_resource(ctx, params)
        if (
            self._archive_read_ttl_ms <= 0
            or isinstance(result, InputRequiredResult)
            or str(params.uri) == _LIVE_SCAN_URI
            or _ENTRY_URI_MARKER in str(params.uri)
            or _is_overview_error_body(result)
        ):
            return result
        return result.model_copy(update={"ttl_ms": self._archive_read_ttl_ms})

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        context: Context[Any, Any] | None = None,
    ) -> CallToolResult | InputRequiredResult:
        if context is None:
            context = Context(mcp_server=self, subscriptions=self._subscriptions)
        # convert_result=False so the raw return value is still inspectable;
        # the success path is then converted by the same
        # ``fn_metadata.convert_result`` the base class would have used, which
        # keeps that path byte-identical to a stock server.
        result = await self._tool_manager.call_tool(
            name, arguments, context, convert_result=False
        )
        if is_tool_error_envelope(result):
            return error_result(result)

        tool = self._tool_manager.get_tool(name)
        if tool is None:  # pragma: no cover - call_tool raises on unknown names
            return result  # type: ignore[no-any-return]
        converted: CallToolResult | InputRequiredResult = (
            tool.fn_metadata.convert_result(result)
        )
        return converted
