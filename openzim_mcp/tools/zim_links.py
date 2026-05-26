"""zim_links — outbound link buckets or related-article suggestions.

Collapses ``extract_article_links`` + ``get_related_articles`` (2 → 1)
via a ``direction: Literal["outbound", "related"]`` dispatch.
v2.0 omits ``"inbound"`` per spec — see description file.
"""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING, Any, Literal, Optional

from ..responses import tool_error

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)

_DIR = pathlib.Path(__file__).parent
_DESCRIPTION = (_DIR / "zim_links_description.md").read_text(encoding="utf-8")

_VALID_DIRECTIONS = {"outbound", "related"}


def register(server: "OpenZimMcpServer") -> None:
    """Register the `zim_links` tool with the MCP server."""
    from ..async_operations import AsyncZimOperations

    ops = AsyncZimOperations(server.zim_operations)

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_links(
        zim_file_path: str,
        entry_path: str,
        direction: Literal["outbound", "related"] = "outbound",
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Any:
        try:
            if direction not in _VALID_DIRECTIONS:
                return tool_error(
                    operation="invalid_direction",
                    message=(
                        f"`direction` must be one of {sorted(_VALID_DIRECTIONS)} "
                        f"(provided: {direction!r}). 'inbound' lands in v2.5 "
                        "with the link-graph sidecar."
                    ),
                )

            if direction == "outbound":
                return await ops.extract_article_links_data(
                    zim_file_path,
                    entry_path,
                    limit=limit if limit is not None else 100,
                    offset=offset,
                )
            # direction == "related"
            return await ops.get_related_articles_data(
                zim_file_path,
                entry_path,
                limit=limit if limit is not None else 10,
            )
        except Exception as e:  # noqa: BLE001 — broad catch matches b13 envelope
            logger.error(f"Error in zim_links: {e}")
            return server._create_enhanced_error_message(
                operation="zim_links",
                error=e,
                context=f"Path: {entry_path}, Direction: {direction}",
            )
