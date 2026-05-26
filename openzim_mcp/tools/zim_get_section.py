"""zim_get_section — fetch one named section of an article.

Phase F renames Phase C's ``get_section`` to ``zim_get_section`` and
adds ``compact`` / ``compact_budget`` parameters for surface uniformity
with the rest of the family (``zim_query`` / ``zim_get`` /
``zim_get_section``). At v2.0 both parameters are **no-ops at the
data layer** — ``get_section_data`` reads the bundle's
``rendered_markdown`` which is always compact-rendered (see
``openzim_mcp/bundle.py`` line 300+: compact rendering keeps the
section slice shape identical to ``get_zim_entry`` for UX
consistency, a load-bearing invariant of the v1.x → v2.0 rename).
v2.5 #18 will wire a true raw-text path; until then, ``compact=True``
and ``compact=False`` produce identical responses, and the migration
from legacy ``get_section`` is **behavior-preserving** (rename only).

The data layer (``zim_operations.get_section_data``) and response
shape (``GetSectionResponse``) are unchanged from Phase C.
"""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING, Any, Optional, Union

from ..responses import tool_error

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)

_DIR = pathlib.Path(__file__).parent
_DESCRIPTION = (_DIR / "zim_get_section_description.md").read_text(encoding="utf-8")


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
            # `compact` / `compact_budget` are surface-uniformity params;
            # at v2.0 they are no-ops at the data layer because the bundle
            # is always compact-rendered (see module docstring). The
            # parameters stay on the surface so callers can adopt the
            # zim_get_section shape today and v2.5 #18 can wire the
            # raw-text path without another rename.
            return await ops.get_section_data(
                zim_file_path,
                entry_path,
                section_id,
                max_chars=max_chars,
            )
        except Exception as e:  # noqa: BLE001 — broad catch matches b13 envelope
            logger.error(f"Error in zim_get_section: {e}")
            return server._create_enhanced_error_message(
                operation="zim_get_section",
                error=e,
                context=f"Path: {entry_path}, Section: {section_id}",
            )
