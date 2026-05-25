"""zim_health — combined server health / configuration / loaded archives.

Phase F prototype skeleton. Delegates to legacy server-tool data methods
and merges them into one response.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Union

from ..responses import ToolErrorPayload, tool_error
from .server_tools import _build_configuration_report, _build_health_report

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


_DESCRIPTION = """Server health, configuration, and loaded archives — one call.

No parameters. Returns combined diagnostics: cache stats, directory health,
configuration summary, and the list of currently-loaded ZIM archives. Single
tool that answers "what is this server, what does it have, and is it OK".

Collapses v1.x `get_server_health` + `get_server_configuration` +
`list_zim_files` (3 tools to 1).
"""


def register(server: "OpenZimMcpServer") -> None:
    """Register the ``zim_health`` tool."""

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_health() -> Union[Dict[str, Any], ToolErrorPayload]:
        try:
            health = await asyncio.to_thread(_build_health_report, server)
            config = await asyncio.to_thread(_build_configuration_report, server)
            archives = await server.async_zim_operations.list_zim_files_summary_data(
                name_filter=""
            )
            return {
                "health": health,
                "configuration": config,
                "loaded_archives": archives,
            }
        except Exception as e:
            logger.error(f"Error in zim_health: {e}")
            return tool_error(
                operation="zim_health",
                message=server._create_enhanced_error_message(
                    operation="zim_health",
                    error=e,
                    context="combined health/config/archives",
                ),
                context="combined health/config/archives",
            )
