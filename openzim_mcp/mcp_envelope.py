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
"""

from __future__ import annotations

from typing import Any

import pydantic_core
from mcp.server.mcpserver import Context, MCPServer
from mcp_types import CallToolResult, InputRequiredResult, TextContent

__all__ = ["EnvelopeAwareMCPServer", "is_tool_error_envelope"]

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
    """

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
