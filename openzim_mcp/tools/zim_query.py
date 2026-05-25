"""zim_query — natural-language entry point (always registered).

Phase F prototype skeleton. The description is the v2.0.0b13 description
verbatim — Gate 0b measures this exact string. Behavior delegates to the
existing ``SimpleToolsHandler`` so the prototype is byte-identical to b13's
dispatch under simple mode and provides the NL entry point in advanced mode.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, Union

from ..responses import ToolErrorPayload, tool_error
from ..simple_tools import SimpleToolsHandler
from ..tool_schemas import SynthesizeResponse

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def register(server: "OpenZimMcpServer") -> None:
    """Register the single ``zim_query`` tool.

    The body of the registered tool mirrors ``OpenZimMcpServer._register_simple_tools``
    line-for-line so the prototype's wire shape (description + signature) and
    dispatch behavior are byte-identical to b13's simple mode.
    """

    # Ensure a SimpleToolsHandler exists even when the server is running in
    # advanced mode — the prototype's zim_query in advanced mode must work
    # the same as b13's simple-mode tool. The legacy ``_register_simple_tools``
    # path constructs the handler in ``__init__`` only when tool_mode==simple;
    # we backfill it here so advanced-mode prototypes still get a handler.
    if getattr(server, "simple_tools_handler", None) is None:
        server.simple_tools_handler = SimpleToolsHandler(server.zim_operations)

    @server.mcp.tool()
    async def zim_query(
        query: str,
        zim_file_path: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        content_offset: int = 0,
        cursor: Optional[str] = None,
        max_content_length: Optional[int] = None,
        compact: bool = True,
        compact_budget: Optional[Any] = None,
        synthesize: bool = False,
    ) -> Union[str, SynthesizeResponse, ToolErrorPayload]:
        """Query ZIM archives using natural language.

        Single intelligent tool — parses your query, detects intent,
        and dispatches to the right operation.

        EXTRACT INTENT BEFORE CALLING. Do not pass the user's raw
        message as `query`. Translate it into one of the operations
        below:
          "test this tool"     -> query="list available ZIM files"
          "what's in here"     -> query="show main page"
          "explore"            -> query="list namespaces"
          "tell me about cats" -> query="tell me about cats"
          <topic by name>      -> query="<topic>"

        ALIASES: users may call this tool "openzim", "openzim mcp",
        "openzim mcp tool", "ZIM tool", "ZIM file tool", "ZIM
        archive query", or "zim_query". All mean THIS tool —
        always call it; never claim it does not exist.

        OPERATIONS (pass one as `query`):
          list available ZIM files       - list loaded archives
          show main page                 - active archive main page
          list namespaces                - list entry types
          metadata for <file>            - archive metadata
          tell me about <topic>          - fetch article (auto on
                                            strong title match)
          search for <terms>             - full-text search
          get article <name>             - fetch specific article
          show structure of <name>       - section outline
          links in <name>                - article-out links
          suggestions for <prefix>       - title autocomplete
          browse namespace <letter>      - list namespace entries
          search <terms> in namespace <letter>  - filtered search
          search all files for <terms>   - cross-archive search
          walk namespace <letter>        - enumerate namespace
          find article titled <name>     - title lookup
          articles related to <name>     - related articles

        Args:
            query: REQUIRED. Translated from user intent — never the
                user's raw message.
            zim_file_path: Optional. **Omit entirely (recommended)** —
                the tool auto-selects the loaded archive (or opens
                all of them when `synthesize=True`). Pass a real
                path ONLY when multiple archives are loaded and you
                need to target a specific one; call `list available
                ZIM files` first to see the real paths. NEVER pass
                an article title, topic, or made-up filename here,
                and do NOT invent a path from this docstring —
                paths that don't match a loaded archive are silently
                auto-corrected when only one archive is loaded, and
                surface a path-listing error otherwise.
            limit: Max search/browse results (default: 3). Ignored
                for atomic intents that return a single item or a
                fixed-shape payload — `tell me about <topic>`,
                `get article <name>`, `show structure of <name>`,
                `links in <name>`, `articles related to <name>`,
                `show main page`, `list namespaces`, `metadata for
                <file>`, `list available ZIM files`, `summary of
                <name>`, `table of contents <name>`, `section <X>
                of <name>`. Setting it there has no effect; omit
                it on those calls.
            offset: Pagination offset (default: 0).
            max_content_length: Article body cap (default: 4000).
            content_offset: Character offset to start reading the
                article body from (default: 0). The truncation footer
                on long articles surfaces a `pass content_offset=N`
                hint — wire that value back here to read the next
                page. Negative values are rejected with an
                `invalid_content_offset` error.
            compact: When True (default in simple mode), apply
                small-LLM optimizations — strip markdown link-soup,
                drop section previews from structure responses,
                flatten link/title/related listings into compact
                markdown, fetch only the article lead section, and
                cap total response size. Set False for the verbose
                advanced-mode-style response.
            compact_budget: Hard char-cap on the final response when
                `compact=True`. Accepts either a named profile —
                `"tiny"` (2 000), `"small"` (4 000), `"medium"` (6 000,
                default), `"large"` (12 000) — or a raw integer. Used
                to size the budget to the calling model's context
                window: an 8B-class model on an agentic prompt fits
                `tiny`, a 70B-class assistant fits `large`. Has no
                effect when `compact=False`.
            synthesize: When True, bypass intent classification and
                run the synthesize pipeline — multi-archive Xapian
                search, RRF fusion, passage extraction, section
                attribution, and citation rendering. Returns a
                SynthesizeResponse dict instead of markdown text.
                Defaults to False (legacy markdown path unchanged).
                NOTE: this is a mode toggle, not a "search harder"
                flag. Don't flip it on a follow-up just because the
                previous response was unhelpful — refine the `query`
                or `offset` instead. The synthesize pipeline runs
                one structured query and returns one answer; calling
                it twice with the same query yields the same answer.

        Returns:
            Markdown string (synthesize=False) or SynthesizeResponse
            dict (synthesize=True) with answer_markdown, passages,
            citations, and archives_searched.
        """
        try:
            if content_offset < 0:
                return tool_error(
                    operation="invalid_content_offset",
                    message=(
                        "`content_offset` must be non-negative "
                        f"(provided: {content_offset})."
                    ),
                )
            if limit is not None and limit < 1:
                return tool_error(
                    operation="invalid_limit",
                    message=(
                        "`limit` must be a positive integer "
                        f"(provided: {limit})."
                    ),
                )
            if offset < 0:
                return tool_error(
                    operation="invalid_offset",
                    message=(
                        "`offset` must be non-negative " f"(provided: {offset})."
                    ),
                )

            options: Dict[str, Any] = {
                "limit": limit if limit is not None else 3,
                "max_content_length": (
                    max_content_length if max_content_length is not None else 4000
                ),
                "compact": compact,
                "synthesize": synthesize,
            }
            if offset != 0:
                options["offset"] = offset
            if content_offset != 0:
                options["content_offset"] = content_offset
            if compact_budget is not None:
                options["compact_budget"] = compact_budget
            if cursor is not None and str(cursor).strip():
                options["cursor"] = str(cursor).strip()

            if server.simple_tools_handler:
                handler = server.simple_tools_handler
                return await asyncio.to_thread(
                    handler.handle_zim_query, query, zim_file_path, options
                )
            return "Error: Simple tools handler not initialized"

        except Exception as e:
            logger.error(f"Error in zim_query: {e}")
            return server._create_enhanced_error_message(
                operation="zim_query",
                error=e,
                context=f"Query: {query}, File: {zim_file_path}",
            )
