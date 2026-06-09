"""zim_get_section — fetch one named section of an article.

Phase F renames Phase C's ``get_section`` to ``zim_get_section`` and
adds ``compact`` / ``compact_budget`` parameters for surface uniformity
with the rest of the family (``zim_query`` / ``zim_get``).

``compact`` is wired at the data layer (v2.5 #18): ``compact=True``
(default) ships the bundle's compact rendering — oversized tables
collapsed to ``[Table N: ...]`` placeholders, matching the
``get_zim_entry`` slice shape — while ``compact=False`` returns the
unrendered section body with full pipe-delimited tables. The lead
section's infobox is not inlined in either mode (the bundle decomposes
it for all consumers); callers wanting the infobox-bearing lead should
use ``zim_get(view="full", compact=False)``. ``compact_budget`` remains
a surface-only no-op.

The data layer (``zim_operations.get_section_data``) and response
shape (``GetSectionResponse``) are unchanged from Phase C.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Union

from ..responses import tool_error
from ._common import load_description, tool_error_response

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

_DESCRIPTION = load_description("zim_get_section")


def register(server: "OpenZimMcpServer") -> None:
    """Register the `zim_get_section` tool with the MCP server."""
    from ..async_operations import AsyncZimOperations

    ops = AsyncZimOperations(server.zim_operations)

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_get_section(
        zim_file_path: str,
        entry_path: str,
        section_id: str,
        max_chars: Optional[int] = None,
        compact: bool = True,
        compact_budget: Optional[Union[str, int]] = None,
    ) -> Any:
        try:
            if not section_id:
                return tool_error(
                    operation="invalid_section",
                    message="`section_id` is required and cannot be empty.",
                )
            # `compact` selects render fidelity: True (default) ships the
            # bundle's compact rendering (oversized tables collapsed to
            # `[Table N: ...]` placeholders), matching get_zim_entry;
            # False returns the unrendered section body with full tables
            # (v2.5 #18). `compact_budget` is still a surface-only no-op.
            return await ops.get_section_data(
                zim_file_path,
                entry_path,
                section_id,
                max_chars=max_chars,
                compact=compact,
            )
        except Exception as e:  # noqa: BLE001 — broad catch matches b13 envelope
            return tool_error_response(
                server,
                operation="zim_get_section",
                error=e,
                context=f"Path: {entry_path}, Section: {section_id}",
            )
