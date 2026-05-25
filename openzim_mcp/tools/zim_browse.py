"""zim_browse — page / walk a namespace (2-mode dispatch, flat schema).

Phase F prototype skeleton. Behavior delegates to legacy ``browse_namespace`` /
``walk_namespace`` data methods.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal, Optional, Union

from ..constants import INPUT_LIMIT_FILE_PATH, INPUT_LIMIT_NAMESPACE
from ..exceptions import OpenZimMcpRateLimitError
from ..responses import ToolErrorPayload, tool_error
from ..security import sanitize_input
from ..tool_schemas import BrowseNamespaceResponse, WalkNamespaceResponse

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


_DESCRIPTION = """Browse or walk entries in a ZIM namespace.

Modes:
  mode="page" (default) — cursor-paginated browse (current `browse_namespace`
    semantics). On large archives may return a sampled view with
    `sampling_based: true`; `done=True` then means "end of sample". Default
    limit: 50 (1-200).
  mode="walk" — deterministic-cursor enumeration (current `walk_namespace`).
    No sampling cap; use for exhaustive dumps. `total` is always None.
    Default limit: 200 (1-500). `offset` is ignored.

Args:
  zim_file_path  REQUIRED. Path to the ZIM archive.
  namespace      REQUIRED. 'C', 'M', 'W', 'X', 'A', 'I' on legacy archives;
                 domain strings on new-scheme. Call `zim_metadata` for the
                 real list.
  cursor         Opaque pagination token; cursor wins on conflict.
  limit, offset  Per-page size + pagination offset.

Returns `BrowseNamespaceResponse` (page) or `WalkNamespaceResponse` (walk),
or `ToolErrorPayload` on failure. Collapses v1.x `browse_namespace` +
`walk_namespace` (2 to 1).
"""


def register(server: "OpenZimMcpServer") -> None:
    """Register the ``zim_browse`` 2-mode dispatch tool."""

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_browse(
        zim_file_path: str,
        namespace: str,
        mode: Literal["page", "walk"] = "page",
        cursor: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> Union[BrowseNamespaceResponse, WalkNamespaceResponse, ToolErrorPayload]:
        try:
            try:
                server.rate_limiter.check_rate_limit("browse_namespace")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="zim_browse",
                    message=server._create_enhanced_error_message(
                        operation="zim_browse",
                        error=e,
                        context=f"namespace={namespace}, mode={mode}",
                    ),
                    context=f"namespace={namespace}, mode={mode}",
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            namespace = sanitize_input(namespace, INPUT_LIMIT_NAMESPACE)
            ops = server.async_zim_operations

            if mode == "walk":
                cursor_state = None
                if cursor:
                    from ..pagination import Cursor

                    try:
                        decoded = Cursor.decode(cursor, expected_tool="walk_namespace")
                    except Exception as e:  # pragma: no cover - skeleton path
                        return tool_error(
                            operation="zim_browse",
                            message=f"Invalid cursor: {e}",
                        )
                    cursor_state = dict(decoded["s"])
                    if "l" in cursor_state and limit is None:
                        limit = cursor_state["l"]
                return await ops.walk_namespace_data(
                    zim_file_path,
                    namespace,
                    cursor_state=cursor_state,
                    limit=limit or 200,
                )

            # mode == "page"
            return await ops.browse_namespace_data(
                zim_file_path,
                namespace,
                limit or 50,
                offset,
            )

        except Exception as e:
            logger.error(f"Error in zim_browse: {e}")
            return tool_error(
                operation="zim_browse",
                message=server._create_enhanced_error_message(
                    operation="zim_browse",
                    error=e,
                    context=f"namespace={namespace}, mode={mode}",
                ),
                context=f"namespace={namespace}, mode={mode}",
            )
