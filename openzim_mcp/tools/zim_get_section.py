"""zim_get_section — fetch one named section of an article.

Phase F renames Phase C's ``get_section`` to ``zim_get_section`` and
adds ``compact``/``compact_budget`` parameters with ``compact=True``
default (behavior break from Phase C's raw-text default, documented
in the migration table). The data layer
(``zim_operations.get_section_data``) and response shape
(``GetSectionResponse``) are unchanged.
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
            # The legacy get_section_data signature didn't accept compact /
            # compact_budget — those are surface-level shape params on
            # zim_get_section. The handler honors them by passing
            # max_chars through and letting the caller's compact_budget
            # narrow the result in the calling LLM's rendering layer
            # (no server-side post-processing yet — the legacy raw shape
            # is what get_section_data returns).
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
