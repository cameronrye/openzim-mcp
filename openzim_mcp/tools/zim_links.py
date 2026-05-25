"""zim_links — outbound / related links from an article (2-direction dispatch).

Phase F prototype skeleton. Delegates to legacy ``extract_article_links_data``
and ``get_related_articles_data``. Flat schema (no oneOf).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, Optional, Union

from ..constants import INPUT_LIMIT_ENTRY_PATH, INPUT_LIMIT_FILE_PATH
from ..exceptions import OpenZimMcpRateLimitError
from ..responses import ToolErrorPayload, tool_error
from ..security import sanitize_input
from ..tool_schemas import LinksResponse, RelatedArticlesResponse

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


_DESCRIPTION = """Extract links from an article: outbound buckets or related articles.

  direction="outbound" (default) — internal/external/media link buckets,
    cursor-paginated. `category_totals` echoes counts.
  direction="related" — articles connected via outbound-link overlap.

v2.5 adds `direction="inbound"` later — enum is not exhaustive at v2.0.

Args:
  zim_file_path, entry_path  REQUIRED.
  cursor   Outbound only.
  limit    Outbound: 1-500, default 100. Related: 1-100, default 10.
  offset   Outbound only.

Returns `LinksResponse` or `RelatedArticlesResponse`, or `ToolErrorPayload`.
Collapses `extract_article_links` + `get_related_articles` (2 to 1).
"""


def register(server: "OpenZimMcpServer") -> None:
    """Register the ``zim_links`` tool."""

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_links(
        zim_file_path: str,
        entry_path: str,
        direction: Literal["outbound", "related"] = "outbound",
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Union[LinksResponse, RelatedArticlesResponse, ToolErrorPayload]:
        try:
            try:
                server.rate_limiter.check_rate_limit("get_structure")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="zim_links",
                    message=server._create_enhanced_error_message(
                        operation="zim_links",
                        error=e,
                        context=f"Entry: {entry_path}, direction: {direction}",
                    ),
                    context=f"Entry: {entry_path}, direction: {direction}",
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)
            ops = server.async_zim_operations

            if direction == "related":
                return await ops.get_related_articles_data(
                    zim_file_path, entry_path, limit or 10
                )

            # direction == "outbound" — default to internal bucket; rc1
            # consumes a `kind` parameter or pipes via cursor.
            kind = "internal"
            cursor_ai: Optional[str] = None
            if cursor:
                from ..pagination import Cursor

                try:
                    decoded = Cursor.decode(
                        cursor, expected_tool="extract_article_links"
                    )
                except Exception as e:  # pragma: no cover - skeleton path
                    return tool_error(
                        operation="zim_links",
                        message=f"Invalid cursor: {e}",
                    )
                state = decoded["s"]
                offset = state.get("o", offset)
                limit = state.get("l", limit)
                entry_path = state.get("ep", entry_path)
                kind = state.get("k", kind)
                cursor_ai = state.get("ai")

            return await ops.extract_article_links_data(
                zim_file_path,
                entry_path,
                limit=limit or 100,
                offset=offset,
                kind=kind,
                cursor_archive_identity=cursor_ai,
            )

        except Exception as e:
            logger.error(f"Error in zim_links: {e}")
            return tool_error(
                operation="zim_links",
                message=server._create_enhanced_error_message(
                    operation="zim_links",
                    error=e,
                    context=f"Entry: {entry_path}, direction: {direction}",
                ),
                context=f"Entry: {entry_path}, direction: {direction}",
            )
