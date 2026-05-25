"""zim_metadata — combined archive metadata + namespace listing.

Phase F prototype skeleton. Delegates to legacy ``get_zim_metadata_data`` and
``list_namespaces_data`` and merges them into a single response.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Union

from ..constants import INPUT_LIMIT_FILE_PATH
from ..exceptions import OpenZimMcpRateLimitError
from ..responses import ToolErrorPayload, tool_error
from ..security import sanitize_input

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


_DESCRIPTION = """Get combined ZIM archive metadata + namespace listing.

Returns `metadata` (Title, Description, Language, Creator, Date, entry
counts) and `namespaces` (per-namespace `total` + `discovery_method`).
New-scheme archives use domain-string namespaces; legacy use single
letters ('C', 'M', 'W', 'X', 'A', 'I').

Args:
  zim_file_path  REQUIRED.

For main-page fetch, use `zim_get(main_page=True)`. Collapses v1.x
`get_zim_metadata` + `list_namespaces` (2 to 1).
"""


def register(server: "OpenZimMcpServer") -> None:
    """Register the ``zim_metadata`` tool."""

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_metadata(
        zim_file_path: str,
    ) -> Union[Dict[str, Any], ToolErrorPayload]:
        try:
            try:
                server.rate_limiter.check_rate_limit("get_metadata")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="zim_metadata",
                    message=server._create_enhanced_error_message(
                        operation="zim_metadata",
                        error=e,
                        context=f"File: {zim_file_path}",
                    ),
                    context=f"File: {zim_file_path}",
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            ops = server.async_zim_operations

            metadata = await ops.get_zim_metadata_data(zim_file_path)
            namespaces = await ops.list_namespaces_data(zim_file_path)

            # Skeleton: combine the two legacy responses. rc1 may move to a
            # native combined response type.
            combined: Dict[str, Any] = {
                "metadata": metadata,
                "namespaces": namespaces,
            }
            return combined

        except Exception as e:
            logger.error(f"Error in zim_metadata: {e}")
            return tool_error(
                operation="zim_metadata",
                message=server._create_enhanced_error_message(
                    operation="zim_metadata",
                    error=e,
                    context=f"File: {zim_file_path}",
                ),
                context=f"File: {zim_file_path}",
            )
