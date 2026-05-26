"""Phase F tool registration orchestrator.

Replaces the b13 ``register_all_tools`` (which dispatched to seven
per-domain registration modules) with a single
``register_phase_f_tools`` entry point. The orchestrator reads
``server.config.tool_mode`` and registers the right tool set:

  - ``simple``  (v2.0.0 default): only ``zim_query``.
  - ``advanced``: all 8 Phase F tools — ``zim_query`` plus
    ``zim_search``, ``zim_get``, ``zim_get_section``,
    ``zim_browse``, ``zim_metadata``, ``zim_links``, and
    ``zim_health``.

MCP Resources and Prompts are orthogonal to tools and stay
registered as the legacy per-domain modules did (advanced-mode-only,
matching b13 behavior).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

__all__ = ["register_phase_f_tools"]


def register_phase_f_tools(server: "OpenZimMcpServer") -> None:
    """Register the v2 Phase F tool surface. Honors
    ``server.config.tool_mode`` — the simple/advanced split is now a
    registration-time filter, not two independent code paths."""
    from . import zim_query

    zim_query.register(server)

    mode = server.config.tool_mode
    if mode == "simple":
        return  # 1-tool surface (v2.0.0 default)

    # advanced — register the remaining 7 Phase F tools
    from . import (
        zim_browse,
        zim_get,
        zim_get_section,
        zim_health,
        zim_links,
        zim_metadata,
        zim_search,
    )
    from .prompts import register_prompts
    from .resource_tools import register_resources

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

    # MCP Resources + Prompts are orthogonal to tools; keep them on the
    # advanced surface as in b13 so the migration is "tools changed
    # shape" only.
    register_resources(server)
    register_prompts(server)
