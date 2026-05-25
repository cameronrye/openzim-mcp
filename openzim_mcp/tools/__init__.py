"""Tool registration modules for OpenZIM MCP server.

This package contains modular tool registration functions that are called
by the main server to register MCP tools. Each module handles a specific
category of tools.
"""

from typing import TYPE_CHECKING

from .content_tools import register_content_tools
from .file_tools import register_file_tools
from .metadata_tools import register_metadata_tools
from .navigation_tools import register_navigation_tools
from .prompts import register_prompts
from .resource_tools import register_resources
from .search_tools import register_search_tools
from .server_tools import register_server_tools
from .structure_tools import register_structure_tools

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

__all__ = [
    "register_all_tools",
    "register_file_tools",
    "register_search_tools",
    "register_content_tools",
    "register_server_tools",
    "register_metadata_tools",
    "register_navigation_tools",
    "register_structure_tools",
    "register_resources",
    "register_prompts",
    "register_phase_f_tools",
]


def register_all_tools(server: "OpenZimMcpServer") -> None:
    """Register all advanced mode tools.

    This function orchestrates the registration of all tool categories
    by calling each specialized registration function.

    Args:
        server: The OpenZimMcpServer instance to register tools on
    """
    register_file_tools(server)
    register_search_tools(server)
    register_content_tools(server)
    register_server_tools(server)
    register_metadata_tools(server)
    register_navigation_tools(server)
    register_structure_tools(server)
    register_resources(server)
    register_prompts(server)


def register_phase_f_tools(server: "OpenZimMcpServer") -> None:
    """Register the v2 Phase F tool surface.

    Honors ``server.config.tool_mode``: ``simple`` registers only
    ``zim_query``; ``advanced`` registers all 8 tools.

    This is the prototype-branch registrar that exists only behind the
    ``OZM_PHASE_F_PROTOTYPE=1`` env var (see ``OpenZimMcpServer._register_tools``).
    It is NEVER reached on the rc0 mainline.
    """
    from . import zim_query

    zim_query.register(server)

    if server.config.tool_mode == "simple":
        return  # 1-tool surface (v2.0.0 default)

    # advanced — all 8 tools
    from . import (
        zim_browse,
        zim_get,
        zim_get_section,
        zim_health,
        zim_links,
        zim_metadata,
        zim_search,
    )

    for module in (
        zim_search,
        zim_get,
        zim_get_section,
        zim_browse,
        zim_metadata,
        zim_links,
        zim_health,
    ):
        module.register(server)
