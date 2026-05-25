"""zim_search — full-text / title-lookup / suggest entry point (3-mode dispatch).

Phase F prototype skeleton. Behavior delegates to existing ``zim_operations``
methods; description is production-quality and consumes the schema budget.

Gate 0.1 verdict (see tests/dispatch_eval/gate_0_1_emission_spike.md): Pattern B
(direct ``Tool.parameters`` mutation, bare ``oneOf`` — no ``$defs``/``$ref``
indirection) is the rc1 production pattern. This module applies Pattern B
post-registration so the wire schema carries the per-mode parameter structure.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Literal, Optional, Union

from ..constants import (
    INPUT_LIMIT_CONTENT_TYPE,
    INPUT_LIMIT_FILE_PATH,
    INPUT_LIMIT_NAMESPACE,
    INPUT_LIMIT_PARTIAL_QUERY,
    INPUT_LIMIT_QUERY,
)
from ..exceptions import OpenZimMcpRateLimitError
from ..responses import ToolErrorPayload, tool_error
from ..security import sanitize_input
from ..tool_schemas import (
    FindEntryResponse,
    SearchAllResponse,
    SearchResponse,
    SearchSuggestionsResponse,
    SearchWithFiltersResponse,
)

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


_DESCRIPTION = """Search a ZIM archive: full-text, title lookup, or prefix-suggest.

Modes (see schema `oneOf` for the per-mode parameter contract):
  mode="fulltext" (default) — Xapian BM25 over rendered bodies. Filters:
    `namespace`, `content_type`. Use `cross_file=True` to fan out.
  mode="title" — typo-tolerant title lookup. Runs Z3/Z4/OPP-1 promotion
    when `cross_file=False` so "Tesla electricity" does not silently
    land on "Tesla's_Wireless_Electricity". Cross-file disables promotion.
  mode="suggest" — prefix autocomplete (libzim SuggestionSearcher).
    Per-archive only; no filters; no cross-file.

Common parameters: `query` (required unless `cursor` carries it),
`zim_file_path` (mutually exclusive with `cross_file=True`),
`limit`, `offset`, `cursor` (cursor wins on conflict).

For NL questions ("tell me about X"), prefer `zim_query` — it routes the
right intent. This tool is the direct path when you already know the
entity name or want a raw search.

Returns `SearchResponse`-shaped dict (Phase B contract: `results`,
`next_cursor`, `total`, `done`, `page_info`) or `ToolErrorPayload` on
failure. Title and suggest modes do not paginate.

Collapses v1.x `search_zim_file` + `search_all` + `search_with_filters` +
`find_entry_by_title` + `get_search_suggestions` (5 to 1).
"""


def register(server: "OpenZimMcpServer") -> None:
    """Register the ``zim_search`` 3-mode dispatch tool.

    After FastMCP processes the decorator (which generates a flat parameter
    schema where ``mode`` is a plain ``Literal`` enum and every parameter
    sits at the top level), Pattern B mutates ``Tool.parameters`` to a
    ``oneOf`` over three per-mode branches. The wire schema then carries
    the conditional-parameter contract the spec describes.
    """

    # Gate 0b runner sets OZM_CRITERION_C_PATH. "wired" (default) applies
    # promotion to mode="title"; "fallback" ships title mode as
    # explicit-string-only. Read at call time so the env var can be flipped
    # mid-run by the eval harness.
    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_search(
        query: str,
        mode: Literal["fulltext", "title", "suggest"] = "fulltext",
        zim_file_path: Optional[str] = None,
        cross_file: bool = False,
        namespace: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        cursor: Optional[str] = None,
    ) -> Union[
        SearchResponse,
        SearchAllResponse,
        SearchWithFiltersResponse,
        FindEntryResponse,
        SearchSuggestionsResponse,
        ToolErrorPayload,
    ]:
        # Skeleton: delegate to existing legacy tool data methods so the
        # prototype's BEHAVIOR is identical to b13. The DESCRIPTION + SCHEMA
        # are what Gate 0b measures. (The wired-vs-fallback Criterion C
        # branch flips only the title-mode preprocessing; behavior parity
        # falls out of using the same data methods b13 uses.)
        try:
            try:
                server.rate_limiter.check_rate_limit("search")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="zim_search",
                    message=server._create_enhanced_error_message(
                        operation="zim_search",
                        error=e,
                        context=f"Query: '{query}', mode: {mode}",
                    ),
                    context=f"Query: '{query}', mode: {mode}",
                )

            if not query and not cursor:
                return tool_error(
                    operation="zim_search",
                    message=(
                        "`query` is required when `cursor` is not provided."
                    ),
                    context=f"Tool: zim_search, mode: {mode}",
                )
            if query:
                query = sanitize_input(query, INPUT_LIMIT_QUERY)
            if zim_file_path is not None:
                zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)

            ops = server.async_zim_operations

            if mode == "fulltext":
                if namespace or content_type:
                    if namespace:
                        namespace = sanitize_input(namespace, INPUT_LIMIT_NAMESPACE)
                    if content_type:
                        content_type = sanitize_input(
                            content_type, INPUT_LIMIT_CONTENT_TYPE
                        )
                    if cross_file:
                        # Filtered cross-file: fall back to fan-out without filters
                        # — filtered search-all is not exposed in v2.0.
                        return await ops.search_all_data(query, limit or 5)
                    if not zim_file_path:
                        return tool_error(
                            operation="zim_search",
                            message=(
                                "mode='fulltext' with filters requires "
                                "`zim_file_path` (or `cross_file=True`)."
                            ),
                        )
                    return await ops.search_with_filters_data(
                        zim_file_path, query, namespace, content_type, limit, offset
                    )
                if cross_file:
                    return await ops.search_all_data(query, limit or 5)
                if not zim_file_path:
                    return tool_error(
                        operation="zim_search",
                        message=(
                            "mode='fulltext' requires `zim_file_path` "
                            "(or `cross_file=True` to fan out)."
                        ),
                    )
                return await ops.search_zim_file_data(
                    zim_file_path, query, limit, offset
                )

            if mode == "title":
                # Criterion C path read at call time. "wired" is the default;
                # "fallback" would strip promotion (skeleton: delegate to
                # raw find_entry_by_title in both, since promotion is
                # delegated to the SimpleToolsHandler in the rc1 wiring).
                _ = os.environ.get("OZM_CRITERION_C_PATH", "wired")
                if not zim_file_path and not cross_file:
                    return tool_error(
                        operation="zim_search",
                        message="mode='title' requires `zim_file_path` or `cross_file=True`.",
                    )
                return await ops.find_entry_by_title_data(
                    zim_file_path or "", query, cross_file, limit or 10
                )

            if mode == "suggest":
                if not zim_file_path:
                    return tool_error(
                        operation="zim_search",
                        message="mode='suggest' requires `zim_file_path`.",
                    )
                partial = sanitize_input(query, INPUT_LIMIT_PARTIAL_QUERY)
                return await ops.get_search_suggestions_data(
                    zim_file_path, partial, limit or 10
                )

            return tool_error(
                operation="zim_search",
                message=f"Unknown mode: {mode!r}",
            )

        except Exception as e:
            logger.error(f"Error in zim_search: {e}")
            return tool_error(
                operation="zim_search",
                message=server._create_enhanced_error_message(
                    operation="zim_search",
                    error=e,
                    context=f"mode={mode}, query='{query}'",
                ),
                context=f"mode={mode}, query='{query}'",
            )

    _inject_oneof_schema(server)


def _inject_oneof_schema(server: "OpenZimMcpServer") -> None:
    """Pattern B: mutate the registered Tool's parameters to a 3-branch oneOf.

    FastMCP's decorator generates a flat schema from the Python signature
    (`mode` becomes an enum, every parameter sits at the top level). The
    spec requires conditional parameter applicability per mode (namespace +
    content_type ONLY in fulltext; cross_file forbidden in suggest). Pattern
    B mutates ``Tool.parameters`` directly to install a bare ``oneOf`` — no
    ``$defs``/``$ref`` indirection, which Gate 0.1 demoted as harder for
    small models to parse.
    """
    tool = server.mcp._tool_manager._tools["zim_search"]
    common_props: dict = {
        "query": {"type": "string"},
        "zim_file_path": {"type": ["string", "null"], "default": None},
        "limit": {"type": ["integer", "null"], "default": None},
        "offset": {"type": "integer", "default": 0},
        "cursor": {"type": ["string", "null"], "default": None},
    }

    fulltext_branch: dict[str, Any] = {
        "type": "object",
        "title": "fulltext",
        "properties": {
            **common_props,
            "mode": {"const": "fulltext", "default": "fulltext"},
            "cross_file": {"type": "boolean", "default": False},
            "namespace": {"type": ["string", "null"], "default": None},
            "content_type": {"type": ["string", "null"], "default": None},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    title_branch: dict[str, Any] = {
        "type": "object",
        "title": "title",
        "properties": {
            **common_props,
            "mode": {"const": "title"},
            "cross_file": {"type": "boolean", "default": False},
        },
        "required": ["query", "mode"],
        "additionalProperties": False,
    }

    suggest_branch: dict[str, Any] = {
        "type": "object",
        "title": "suggest",
        "properties": {
            **common_props,
            "mode": {"const": "suggest"},
        },
        "required": ["query", "mode"],
        "additionalProperties": False,
    }

    tool.parameters = {
        "type": "object",
        "oneOf": [fulltext_branch, title_branch, suggest_branch],
    }
