"""zim_get — entry retrieval / batch / main-page / binary (4-branch dispatch).

Phase F prototype skeleton. Behavior delegates to existing ``zim_operations``
methods. Pattern B oneOf is applied post-registration so the wire schema
carries the per-branch parameter contract.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, List, Literal, Optional, Union

from ..constants import INPUT_LIMIT_ENTRY_PATH, INPUT_LIMIT_FILE_PATH
from ..exceptions import OpenZimMcpRateLimitError
from ..responses import ToolErrorPayload, tool_error
from ..security import sanitize_input
from ..tool_schemas import (
    ArticleStructureResponse,
    BatchEntryResponse,
    BinaryEntryResponse,
    EntryResponse,
    EntrySummaryResponse,
    TableOfContentsResponse,
)

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


_DESCRIPTION = """Retrieve one or more entries from a ZIM archive.

Four mutually-exclusive call shapes (see `oneOf` for the contract):
  1. Single-entry body view — `entry_path` + `view∈{full,summary,toc,structure}`
     full → markdown body; summary → lead snippet; toc → heading tree;
     structure → flat section list + metadata.
  2. Single-entry binary — `entry_path` + `binary=True` (view locked to "full").
     Returns base64-encoded bytes plus mime_type and size.
  3. Batch — `entry_paths` (up to 50) + `view`. Per-entry failures are
     non-fatal; rate limit charged per entry.
  4. Main page — `main_page=True`. Path-free archive main-page fetch.

Common parameters: `zim_file_path` (REQUIRED; call `zim_health` or
`zim_search(mode="title")` first to discover real paths),
`max_content_length`, `content_offset` (single-entry body view only),
`compact` (v2.0 default False — set True for compact small-LLM rendering),
`compact_budget` ("tiny"/"small"/"medium"/"large" or int).

Returns the response type matching the called shape, or a
`ToolErrorPayload` envelope on failure. Invalid shape combinations return
`tool_error("invalid_path_combination", hint=...)` even when a client
flattens `oneOf`.

Collapses v1.x `get_zim_entry` + `get_zim_entries` + `get_main_page` +
`get_binary_entry` + `get_entry_summary` + `get_table_of_contents` +
`get_article_structure` (7 to 1).
"""


def register(server: "OpenZimMcpServer") -> None:
    """Register the ``zim_get`` 4-branch dispatch tool."""

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_get(
        zim_file_path: str,
        entry_path: Optional[str] = None,
        entry_paths: Optional[List[str]] = None,
        view: Literal["full", "summary", "toc", "structure"] = "full",
        binary: bool = False,
        main_page: bool = False,
        max_content_length: Optional[int] = None,
        content_offset: int = 0,
        compact: bool = False,
        compact_budget: Optional[Any] = None,
    ) -> Union[
        EntryResponse,
        BatchEntryResponse,
        EntrySummaryResponse,
        TableOfContentsResponse,
        ArticleStructureResponse,
        BinaryEntryResponse,
        ToolErrorPayload,
    ]:
        # Skeleton: delegate to existing legacy data methods so behavior
        # parity with rc0 is preserved.
        try:
            try:
                server.rate_limiter.check_rate_limit("get_entry")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="zim_get",
                    message=server._create_enhanced_error_message(
                        operation="zim_get",
                        error=e,
                        context=f"path={entry_path}, main_page={main_page}",
                    ),
                    context=f"path={entry_path}, main_page={main_page}",
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            ops = server.async_zim_operations

            # Branch 4: main page (path-free)
            if main_page:
                if entry_path or entry_paths or binary:
                    return tool_error(
                        operation="zim_get",
                        message=(
                            "invalid_path_combination: main_page=True forbids "
                            "entry_path, entry_paths, and binary=True."
                        ),
                    )
                return await ops.get_main_page_data(zim_file_path)

            # Branch 3: batch
            if entry_paths:
                if entry_path or binary:
                    return tool_error(
                        operation="zim_get",
                        message=(
                            "invalid_path_combination: entry_paths forbids "
                            "entry_path and binary=True."
                        ),
                    )
                sanitized: List[dict] = []
                for ep in entry_paths:
                    sanitized.append(
                        {
                            "zim_file_path": zim_file_path,
                            "entry_path": sanitize_input(
                                str(ep or ""),
                                INPUT_LIMIT_ENTRY_PATH,
                                allow_empty=True,
                            ),
                        }
                    )
                return await ops.get_entries_data(
                    sanitized, max_content_length, compact=compact
                )

            # Branch 2: single-entry binary
            if binary:
                if not entry_path:
                    return tool_error(
                        operation="zim_get",
                        message="binary=True requires entry_path.",
                    )
                entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)
                return await ops.get_binary_entry_data(
                    zim_file_path, entry_path, max_content_length, True
                )

            # Branch 1: single-entry body view
            if not entry_path:
                return tool_error(
                    operation="zim_get",
                    message=(
                        "Missing required parameter: provide entry_path, "
                        "entry_paths, or main_page=True."
                    ),
                )
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)
            if view == "full":
                return await ops.get_zim_entry_data(
                    zim_file_path,
                    entry_path,
                    max_content_length,
                    content_offset,
                    compact=compact,
                )
            if view == "summary":
                return await ops.get_entry_summary_data(
                    zim_file_path, entry_path, 200, compact=compact
                )
            if view == "toc":
                return await ops.get_table_of_contents_data(zim_file_path, entry_path)
            if view == "structure":
                return await ops.get_article_structure_data(zim_file_path, entry_path)

            return tool_error(
                operation="zim_get",
                message=f"Unknown view: {view!r}",
            )

        except Exception as e:
            logger.error(f"Error in zim_get: {e}")
            return tool_error(
                operation="zim_get",
                message=server._create_enhanced_error_message(
                    operation="zim_get",
                    error=e,
                    context=f"path={entry_path}, view={view}",
                ),
                context=f"path={entry_path}, view={view}",
            )

    _inject_zim_get_oneof(server)


def _inject_zim_get_oneof(server: "OpenZimMcpServer") -> None:
    """Pattern B: mutate Tool.parameters to a 4-branch oneOf.

    Branches encode the conditional-parameter contract from the spec:
      - Branch 1: single-entry body view (entry_path + view∈{full,summary,toc,structure})
      - Branch 2: single-entry binary (entry_path + binary=True; view locked to "full")
      - Branch 3: batch (entry_paths + view∈{full,summary,toc,structure})
      - Branch 4: main page (main_page=True; entry_path/entry_paths/binary forbidden)
    """
    tool = server.mcp._tool_manager._tools["zim_get"]

    shared_props: dict = {
        "zim_file_path": {"type": "string"},
        "max_content_length": {"type": ["integer", "null"], "default": None},
        "compact": {"type": "boolean", "default": False},
        "compact_budget": {"type": ["string", "integer", "null"], "default": None},
    }

    body_view_branch: dict[str, Any] = {
        "type": "object",
        "title": "body_view",
        "properties": {
            **shared_props,
            "entry_path": {"type": "string"},
            "view": {
                "enum": ["full", "summary", "toc", "structure"],
                "default": "full",
            },
            "content_offset": {"type": "integer", "default": 0},
        },
        "required": ["zim_file_path", "entry_path"],
        "additionalProperties": False,
    }

    binary_branch: dict[str, Any] = {
        "type": "object",
        "title": "binary",
        "properties": {
            **shared_props,
            "entry_path": {"type": "string"},
            "binary": {"const": True},
        },
        "required": ["zim_file_path", "entry_path", "binary"],
        "additionalProperties": False,
    }

    batch_branch: dict[str, Any] = {
        "type": "object",
        "title": "batch",
        "properties": {
            **shared_props,
            "entry_paths": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 50,
            },
            "view": {
                "enum": ["full", "summary", "toc", "structure"],
                "default": "full",
            },
        },
        "required": ["zim_file_path", "entry_paths"],
        "additionalProperties": False,
    }

    main_page_branch: dict[str, Any] = {
        "type": "object",
        "title": "main_page",
        "properties": {
            **shared_props,
            "main_page": {"const": True},
        },
        "required": ["zim_file_path", "main_page"],
        "additionalProperties": False,
    }

    tool.parameters = {
        "type": "object",
        "oneOf": [body_view_branch, binary_branch, batch_branch, main_page_branch],
    }
