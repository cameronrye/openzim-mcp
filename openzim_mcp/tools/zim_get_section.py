"""zim_get_section — fetch a single article section by section_id.

Phase F prototype skeleton. Renamed from v1.x ``get_section`` and gained
``compact`` / ``compact_budget`` parameters. Flat schema (no oneOf).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional, Union

from ..constants import INPUT_LIMIT_ENTRY_PATH, INPUT_LIMIT_FILE_PATH
from ..exceptions import OpenZimMcpRateLimitError
from ..responses import ToolErrorPayload, tool_error
from ..security import sanitize_input
from ..tool_schemas import GetSectionResponse

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


_DESCRIPTION = """Fetch a single article section by `section_id`.

`section_id` values come from `zim_get(view="toc")` or
`zim_get(view="structure")`. On miss, returns `ToolErrorPayload` with
`available_section_ids` for self-correction.

Args:
  zim_file_path, entry_path, section_id  All REQUIRED.
  max_chars       Optional body cap.
  include_subsections   True (default) includes nested children;
                  False ends at the next heading of any level.
  compact         v2.0 default True. Set False for legacy raw rendering.
  compact_budget  Char-cap when compact=True; "tiny"/"small"/"medium"/"large"
                  or int.

v2 rename of `get_section`. Returns `GetSectionResponse` or
`ToolErrorPayload`.
"""


def register(server: "OpenZimMcpServer") -> None:
    """Register the ``zim_get_section`` tool."""

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_get_section(
        zim_file_path: str,
        entry_path: str,
        section_id: str,
        max_chars: Optional[int] = None,
        include_subsections: bool = True,
        compact: bool = True,
        compact_budget: Optional[Any] = None,
    ) -> Union[GetSectionResponse, ToolErrorPayload]:
        try:
            try:
                server.rate_limiter.check_rate_limit("get_structure")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="zim_get_section",
                    message=server._create_enhanced_error_message(
                        operation="zim_get_section",
                        error=e,
                        context=f"Entry: {entry_path}, section_id: {section_id}",
                    ),
                    context=f"Entry: {entry_path}, section_id: {section_id}",
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)

            # Skeleton: compact / compact_budget are signature-only at the
            # prototype layer — the legacy get_section_data does not consume
            # them. rc1 wires them through to the renderer.
            _ = (compact, compact_budget)

            return await server.async_zim_operations.get_section_data(
                zim_file_path,
                entry_path,
                section_id,
                max_chars=max_chars,
                include_subsections=include_subsections,
            )

        except Exception as e:
            logger.error(f"Error in zim_get_section: {e}")
            return tool_error(
                operation="zim_get_section",
                message=server._create_enhanced_error_message(
                    operation="zim_get_section",
                    error=e,
                    context=(
                        f"File: {zim_file_path}, Entry: {entry_path}, "
                        f"section_id: {section_id}"
                    ),
                ),
                context=(
                    f"File: {zim_file_path}, Entry: {entry_path}, "
                    f"section_id: {section_id}"
                ),
            )
