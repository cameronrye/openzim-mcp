"""Shared structured-response helpers for MCP tool functions.

The helpers here standardize the shape every tool uses to report failure:
``{"error": true, "operation": ..., "message": ...}``, serialized as JSON
text in the response's ``content``. No tool advertises an ``outputSchema``,
so nothing arrives in ``structuredContent`` — clients parse the text block.
(An earlier version of this docstring claimed the opposite; see
``tool_schemas`` for why the one schema that existed was dropped.)

Returning this envelope rather than raising keeps a failure machine-readable
and lets a small model self-correct from ``message``. Because it is a
*return* value, the MCP ``isError`` flag has to be set separately —
:mod:`openzim_mcp.mcp_envelope` recognises the envelope on the way out and
marks the ``CallToolResult`` accordingly. A new failure path that builds its
payload by hand instead of calling :func:`tool_error` will be delivered as a
success; go through this module.
"""

from typing import Any, Dict, NotRequired, Optional, TypedDict


class ToolErrorPayload(TypedDict):
    """Envelope for tool errors, delivered as JSON text in ``content``.

    ``error`` is always ``True`` so a client can branch on a single key
    without inspecting the operation name. ``message`` carries the
    same human-readable text the tool would have returned as a string
    (markdown is fine — it's a string field, not nested JSON).
    """

    error: bool
    operation: str
    message: str
    context: NotRequired[str]


def tool_error(
    *,
    operation: str,
    message: str,
    context: Optional[str] = None,
    extras: Optional[Dict[str, Any]] = None,
) -> ToolErrorPayload:
    """Build a structured error payload for a failed tool invocation.

    Args:
        operation: The high-level operation name (mirrors the value passed
            to ``OpenZimMcpServer._create_enhanced_error_message``).
        message: The user-facing error text — typically the markdown blob
            produced by ``_create_enhanced_error_message``.
        context: Optional contextual hint (file path, query, etc.).
        extras: Optional dict of additional keys to merge into the payload.
            Useful for attaching self-correction hints (e.g.
            ``available_section_ids``) without a ``# type: ignore`` at
            every call site. The extra keys are intentional runtime
            extensions; ``ToolErrorPayload`` stays narrow in its TypedDict
            declaration.

    Returns:
        A ``ToolErrorPayload`` envelope ready to be returned from an MCP
        tool function whose return type is ``Union[..., ToolErrorPayload]``.
    """
    payload: ToolErrorPayload = {
        "error": True,
        "operation": operation,
        "message": message,
    }
    if context is not None:
        payload["context"] = context
    if extras:
        payload.update(extras)  # type: ignore[typeddict-item]
    return payload
