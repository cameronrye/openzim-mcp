"""Main OpenZIM MCP server implementation."""

import asyncio
import logging
from typing import Any, Dict, Literal, Optional, Union

from mcp.server.fastmcp import FastMCP

from . import __version__
from .async_operations import AsyncZimOperations
from .cache import OpenZimMcpCache
from .config import OpenZimMcpConfig
from .constants import TOOL_MODE_SIMPLE, VALID_TRANSPORT_TYPES
from .content_processor import ContentProcessor
from .error_messages import (
    format_error_message,
    format_generic_error,
    get_error_config,
)
from .exceptions import OpenZimMcpConfigurationError
from .rate_limiter import RateLimiter
from .responses import ToolErrorPayload, tool_error
from .security import (
    PathValidator,
    redact_paths_in_message,
    sanitize_context_for_error,
)
from .simple_tools import SimpleToolsHandler
from .tool_schemas import SynthesizeResponse
from .tools import register_all_tools
from .zim_operations import ZimOperations

logger = logging.getLogger(__name__)


class OpenZimMcpServer:
    """Main OpenZIM MCP server class with dependency injection."""

    def __init__(self, config: OpenZimMcpConfig):
        """Initialize OpenZIM MCP server.

        Args:
            config: Server configuration
        """
        self.config = config

        # Track server start so health reports can show real uptime instead
        # of the placeholder ``"unknown"`` it returned before. Stored as both
        # a UTC ISO-8601 string (for display) and a monotonic anchor (for
        # uptime maths that survive wall-clock jumps).
        import time as _time
        from datetime import datetime, timezone

        self._start_time = datetime.now(timezone.utc).isoformat()
        self._start_monotonic = _time.monotonic()

        # Setup logging
        config.setup_logging()
        logger.info(f"Initializing OpenZIM MCP server v{__version__}")

        # Initialize components
        self.path_validator = PathValidator(config.allowed_directories)
        self.cache = OpenZimMcpCache(config.cache)
        self.content_processor = ContentProcessor(
            config.content.snippet_length,
            table_row_threshold=config.content.table_row_threshold,
            table_char_threshold=config.content.table_char_threshold,
            infobox_kv_limit=config.content.infobox_kv_limit,
        )
        # ``RateLimitConfig`` is unified — ``OpenZimMcpConfig.rate_limit`` is
        # the same model the limiter expects, including ``per_operation_limits``
        # which would otherwise be unreachable from env-var/JSON config.
        self.rate_limiter = RateLimiter(config.rate_limit)
        self.zim_operations = ZimOperations(
            config, self.path_validator, self.cache, self.content_processor
        )
        self.async_zim_operations = AsyncZimOperations(self.zim_operations)

        # Initialize simple tools handler if in simple mode
        self.simple_tools_handler = None
        if config.tool_mode == TOOL_MODE_SIMPLE:
            self.simple_tools_handler = SimpleToolsHandler(self.zim_operations)

        # Initialize MCP server. FastMCP itself doesn't accept a version
        # kwarg, but the underlying lowlevel Server does — set it after
        # construction so MCP `serverInfo.version` advertises openzim-mcp's
        # version rather than the SDK's default.
        #
        # When sitting behind a reverse proxy or Tailscale serve, the
        # public hostname differs from the bind interface and the SDK's
        # default Host allowlist (loopback only) rejects every request
        # with 421 Misdirected Request. Operators extend the allowlist
        # via OPENZIM_MCP_ALLOWED_HOSTS for those deployments. Loopback
        # entries are always preserved so localhost-direct access keeps
        # working alongside the proxied path.
        #
        # The MCP SDK's transport security ALSO validates the Origin header
        # against ``allowed_origins`` (separate from CORS — application-layer
        # DNS-rebinding defense). Without populating it, every browser
        # request fails with ``403 Invalid Origin header`` even after CORS
        # preflight succeeds. We mirror ``OPENZIM_MCP_CORS_ORIGINS`` into the
        # SDK's ``allowed_origins`` because they encode the same trust
        # decision: an origin we let into CORS is one we let past the
        # rebinding check.
        fastmcp_kwargs: dict = {}
        if config.transport == "http" and config.allowed_hosts:
            from mcp.server.transport_security import TransportSecuritySettings

            fastmcp_kwargs["transport_security"] = TransportSecuritySettings(
                allowed_hosts=[
                    "127.0.0.1:*",
                    "localhost:*",
                    "[::1]:*",
                    *config.allowed_hosts,
                ],
                allowed_origins=list(config.cors_origins),
            )
        self.mcp = FastMCP(config.server_name, **fastmcp_kwargs)
        self.mcp._mcp_server.version = __version__
        self._register_tools()

        # Subscription support is HTTP-only: the MtimeWatcher that emits
        # update notifications only runs under the HTTP lifespan (see
        # http_app.serve_streamable_http). Wiring handlers in stdio mode
        # would advertise a capability we silently can't honor.
        self.subscriber_registry = None
        if config.subscriptions_enabled and config.transport == "http":
            from .subscriptions import (
                SubscriberRegistry,
                patch_capabilities_to_advertise_subscribe,
                register_subscription_handlers,
            )

            self.subscriber_registry = SubscriberRegistry()
            register_subscription_handlers(self.mcp, self.subscriber_registry)
            patch_capabilities_to_advertise_subscribe(self.mcp)

        logger.info(
            f"OpenZIM MCP server initialized successfully in {config.tool_mode} mode"
        )

        # Minimal server startup logging - detailed config available via MCP tools
        logger.info(
            f"Server: {self.config.server_name}, "
            f"Mode: {self.config.tool_mode}, "
            f"Directories: {len(self.config.allowed_directories)}, "
            f"Cache: {self.config.cache.enabled}"
        )
        if config.tool_mode == TOOL_MODE_SIMPLE:
            logger.info("Running in SIMPLE mode with 1 intelligent tool (zim_query)")
        else:
            logger.debug(
                "Use get_server_configuration() MCP tool for detailed configuration"
            )

    def _create_enhanced_error_message(
        self, operation: str, error: Exception, context: str = ""
    ) -> str:
        """Create educational, actionable error messages for LLM users.

        Uses externalized error message templates from error_messages module.

        Args:
            operation: The operation that failed
            error: The exception that occurred
            context: Additional context (e.g., file path, query)

        Returns:
            Enhanced error message with troubleshooting guidance
        """
        error_type = type(error).__name__
        # Redact absolute paths (e.g. the canonical resolved path embedded
        # in OpenZimMcpSecurityError) before the message reaches the
        # client. Without this the host's allowed-dirs layout leaks via
        # the **Technical Details** field on every rejected traversal.
        base_message = redact_paths_in_message(str(error))
        sanitized_context = sanitize_context_for_error(context)

        # Check for known error types using externalized config
        config = get_error_config(error)
        if config:
            return format_error_message(
                config, operation, sanitized_context, base_message
            )

        # Generic error using externalized template
        return format_generic_error(
            operation=operation,
            error_type=error_type,
            context=sanitized_context,
            details=base_message,
        )

    def _register_simple_tools(self) -> None:
        """Register the single ``zim_query`` tool used in simple mode.

        Simple mode exposes exactly one MCP tool. ``zim_query`` parses the
        natural-language query, classifies its intent, and delegates to
        ``ZimOperations`` directly — the underlying advanced-mode tools are
        deliberately not registered, so the schema sent to the model stays
        compact and matches the README's "simple mode = 1 tool" promise.
        """

        # Register the simple wrapper tools that LLMs will primarily use
        @self.mcp.tool()
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
                    <file>`, `list available ZIM files`. Setting it
                    there has no effect; omit it on those calls.
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
                # A11: ``content_offset`` is the article-body paging
                # channel surfaced by the truncation footer on long
                # ``tell me about`` / ``get article`` responses. Reject
                # negative offsets up-front so a malformed cursor can't
                # produce an out-of-range slice downstream — the cursor
                # decoder already enforces this contract.
                if content_offset < 0:
                    return tool_error(
                        operation="invalid_content_offset",
                        message=(
                            "`content_offset` must be non-negative "
                            f"(provided: {content_offset})."
                        ),
                    )
                # A11 F1: ``limit=0`` used to produce a nonsensical
                # ``Showing 1-0 of N — pass offset=0 for the next
                # page`` pagination header that looped on itself.
                # Reject non-positive limits up-front. ``None`` keeps
                # working — that's the "use the default limit" sentinel.
                if limit is not None and limit < 1:
                    return tool_error(
                        operation="invalid_limit",
                        message=(
                            "`limit` must be a positive integer "
                            f"(provided: {limit})."
                        ),
                    )
                # A11 F1: same for ``offset``.
                if offset < 0:
                    return tool_error(
                        operation="invalid_offset",
                        message=(
                            "`offset` must be non-negative " f"(provided: {offset})."
                        ),
                    )

                # Build options dict from parameters. Simple mode is for
                # smaller / context-limited LLMs, so we apply tighter
                # defaults than ContentConfig's (100 000-char articles,
                # 10-result searches) when the caller doesn't specify them.
                # An LLM that wants the full article can still pass an
                # explicit ``max_content_length``; this only affects calls
                # that omit it.
                #
                # Tightened in v1.2.0 follow-up: 5 results × 3000-char
                # snippets is ~15k chars per search response, and 8k-char
                # article bodies are ~2k tokens of dense Wikipedia
                # markdown — both too large for an 8B Q4 with a typical
                # agentic prompt window. 3 results and 4k bodies preserve
                # the lead + first major section while halving the
                # context cost. Callers still override via the explicit
                # ``limit`` / ``max_content_length`` parameters.
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
                # D10: ``cursor`` is the v2 Phase B pagination handle.
                # When supplied, it's decoded and its embedded ``o``
                # (offset) overrides any caller-supplied ``offset``.
                # Without this, the cursors that walk/browse/search
                # responses surface are decorative: the only paging
                # channel reachable from zim_query was the integer
                # ``offset`` parameter.
                if cursor is not None and str(cursor).strip():
                    options["cursor"] = str(cursor).strip()

                # Use simple tools handler. handle_zim_query is synchronous and
                # performs blocking ZIM I/O, so dispatch it to a worker thread
                # rather than blocking the asyncio event loop.
                if self.simple_tools_handler:
                    handler = self.simple_tools_handler
                    return await asyncio.to_thread(
                        handler.handle_zim_query, query, zim_file_path, options
                    )
                else:
                    return "Error: Simple tools handler not initialized"

            except Exception as e:
                logger.error(f"Error in zim_query: {e}")
                return self._create_enhanced_error_message(
                    operation="zim_query",
                    error=e,
                    context=f"Query: {query}, File: {zim_file_path}",
                )

        logger.info("Simple mode tools registered (zim_query only)")

    def _register_tools(self) -> None:
        """Register MCP tools based on configured mode."""
        # Check tool mode and register appropriate tools
        if self.config.tool_mode == TOOL_MODE_SIMPLE:
            logger.info("Registering simple mode tools...")
            self._register_simple_tools()
            return

        # Advanced mode - register all tools (existing behavior)
        logger.info("Registering advanced mode tools...")
        self._register_advanced_tools()

    def _register_advanced_tools(self) -> None:
        """Register advanced mode tools.

        Tools are organized into logical groups in separate modules:
        - File tools: list_zim_files
        - Search tools: search_zim_file
        - Content tools: get_zim_entry
        - Server tools: get_server_health, get_server_configuration
        - Metadata tools: get_zim_metadata, get_main_page, list_namespaces
        - Navigation tools: browse_namespace, search_with_filters,
                           get_search_suggestions
        - Structure tools: get_article_structure, extract_article_links,
                          get_entry_summary, get_table_of_contents,
                          get_binary_entry
        """
        register_all_tools(self)
        logger.info("MCP tools registered successfully")

    # Individual tool registration methods have been extracted to
    # openzim_mcp/tools/ modules for better maintainability.
    # See: file_tools.py, search_tools.py, content_tools.py,
    #      server_tools.py, metadata_tools.py, navigation_tools.py,
    #      structure_tools.py
    #
    # REMOVED: _register_file_tools, _register_search_tools,
    #          _register_content_tools, _register_server_tools,
    #          _register_metadata_tools, _register_navigation_tools,
    #          _register_structure_tools (all moved to tools/ package)

    def run(
        self,
        transport: Optional[Literal["stdio", "sse", "streamable-http"]] = None,
    ) -> None:
        """
        Run the OpenZIM MCP server.

        Args:
            transport: Optional override for the transport protocol. When
                ``None`` (default), the value is derived from
                ``self.config.transport`` — which is the value the
                ``__init__`` already used to decide whether to wire
                subscriptions, so the two stay consistent. Passing an
                explicit value that contradicts the configured transport
                raises ``OpenZimMcpConfigurationError`` rather than
                silently advertising capabilities the running transport
                cannot honour.

        Raises:
            OpenZimMcpConfigurationError: If transport type is invalid or
                disagrees with ``self.config.transport``.

        Example:
            >>> server = OpenZimMcpServer(config)
            >>> server.run()  # uses config.transport
        """
        # 'http' is our short name for FastMCP's 'streamable-http' wire value.
        config_transport: Literal["stdio", "sse", "streamable-http"] = (
            "streamable-http"
            if self.config.transport == "http"
            else self.config.transport
        )

        if transport is None:
            transport = config_transport
        elif transport != config_transport:
            raise OpenZimMcpConfigurationError(
                f"Transport mismatch: run(transport={transport!r}) but "
                f"config.transport is {self.config.transport!r}. "
                f"Subscriptions and other transport-specific features were "
                f"wired against the configured transport during __init__; "
                f"omit the run() argument to use it, or rebuild the server "
                f"with a matching config.transport."
            )

        # Validate transport type
        if transport not in VALID_TRANSPORT_TYPES:
            raise OpenZimMcpConfigurationError(
                f"Invalid transport type: '{transport}'. "
                f"Must be one of: {', '.join(sorted(VALID_TRANSPORT_TYPES))}"
            )

        logger.info(f"Starting OpenZIM MCP server with transport: {transport}")
        try:
            if transport == "streamable-http":
                from . import http_app

                http_app.serve_streamable_http(self)
            else:
                if transport == "sse":
                    from . import http_app

                    http_app.check_safe_startup(self.config)
                    # FastMCP's SSE path reads host/port from settings; mirror
                    # them from config so --host/--port take effect.
                    self.mcp.settings.host = self.config.host
                    self.mcp.settings.port = self.config.port
                self.mcp.run(transport=transport)
        except KeyboardInterrupt:
            logger.info("Server shutdown requested")
        except Exception as e:
            logger.error(f"Server error: {e}")
            raise
        finally:
            logger.info("OpenZIM MCP server stopped")
