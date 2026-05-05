"""Shared structured-response helpers for MCP tool functions.

When an MCP tool function declares a structured return type (a dict,
TypedDict, or Pydantic model), FastMCP serializes the value into the
response's ``structuredContent`` field — letting clients consume a real
object instead of a JSON string nested inside a TextContent block. The
helpers in this module standardize the shapes used for error responses
so every tool emits a recognisable envelope on failure.
"""

from typing import NotRequired, Optional, TypedDict


class ToolErrorPayload(TypedDict):
    """Envelope for tool errors returned via structuredContent.

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
) -> ToolErrorPayload:
    """Build a structured error payload for a failed tool invocation.

    Args:
        operation: The high-level operation name (mirrors the value passed
            to ``OpenZimMcpServer._create_enhanced_error_message``).
        message: The user-facing error text — typically the markdown blob
            produced by ``_create_enhanced_error_message``.
        context: Optional contextual hint (file path, query, etc.).

    Returns:
        A ``ToolErrorPayload`` dict suitable for returning from a tool
        function annotated with a structured return type.
    """
    payload: ToolErrorPayload = {
        "error": True,
        "operation": operation,
        "message": message,
    }
    if context is not None:
        payload["context"] = context
    return payload
