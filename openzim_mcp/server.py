"""Main OpenZIM MCP server implementation."""

import asyncio
import logging
from typing import Literal, Optional

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
from .security import (
    PathValidator,
    redact_paths_in_message,
    sanitize_context_for_error,
)
from .simple_tools import SimpleToolsHandler
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

        # Setup logging
        config.setup_logging()
        logger.info(f"Initializing OpenZIM MCP server v{__version__}")

        # Initialize components
        self.path_validator = PathValidator(config.allowed_directories)
        self.cache = OpenZimMcpCache(config.cache)
        self.content_processor = ContentProcessor(config.content.snippet_length)
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
        self.mcp = FastMCP(config.server_name)
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
            logger.info(
                "Running in SIMPLE mode with 1 intelligent tool (zim_query) "
                "plus all underlying tools"
            )
        else:
            logger.debug(
                "Use get_server_configuration() MCP tool " "for detailed configuration"
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
        """Register simple mode tools with underlying tools for routing."""

        # Register the simple wrapper tools that LLMs will primarily use
        @self.mcp.tool()
        async def zim_query(
            query: str,
            zim_file_path: Optional[str] = None,
            limit: Optional[int] = None,
            offset: int = 0,
            max_content_length: Optional[int] = None,
        ) -> str:
            """Query ZIM files using natural language.

            This intelligent tool understands natural language queries and automatically
            routes them to the appropriate underlying operations. It can handle:

            - File listing: "list files", "what ZIM files are available"
            - Metadata: "metadata for file.zim", "info about this ZIM"
            - Main page: "show main page", "get home page"
            - Namespaces: "list namespaces", "what namespaces exist"
            - Browsing: "browse namespace C", "show articles in namespace A"
            - Article structure: "structure of Biology", "outline of Evolution"
            - Links: "links in Biology", "references from Evolution"
            - Suggestions: "suggestions for bio", "autocomplete evol"
            - Filtered search: "search evolution in namespace C"
            - Get article: "get article Biology", "show Evolution"
            - General search: "search for biology", "find evolution"
            - Cross-file search: "search all files for python" → search_all
            - Namespace walk: "walk namespace M" → walk_namespace
            - Title lookup: "find article titled Photosynthesis"
              → find_entry_by_title
            - Related articles: "articles related to Climate_Change"
              → get_related_articles

            Args:
                query: Natural language query (REQUIRED)
                zim_file_path: Optional ZIM file path (auto-selects if one exists)
                limit: Max results for search/browse operations
                offset: Optional starting offset for pagination (default: 0)
                max_content_length: Optional maximum content length for articles

            Returns:
                Response based on the query intent

            Examples:
                - "list available ZIM files"
                - "search for biology in wikipedia.zim"
                - "get article Evolution"
                - "show structure of Biology"
                - "browse namespace C with limit 10"
                - "search all files for python"
                - "walk namespace M"
                - "find article titled Photosynthesis"
                - "articles related to Climate_Change"
            """
            try:
                # Build options dict from parameters
                options = {}
                if limit is not None:
                    options["limit"] = limit
                if offset != 0:
                    options["offset"] = offset
                if max_content_length is not None:
                    options["max_content_length"] = max_content_length

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

        # Also register the advanced tools so they're available for advanced use
        # This allows the simple mode to still have access to all functionality
        self._register_advanced_tools()

        logger.info("Simple mode tools registered (zim_query + all underlying tools)")

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
        self, transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    ) -> None:
        """
        Run the OpenZIM MCP server.

        Args:
            transport: Transport protocol to use ("stdio", "sse", or "streamable-http")

        Raises:
            OpenZimMcpConfigurationError: If transport type is invalid

        Example:
            >>> server = OpenZimMcpServer()
            >>> server.run(transport="stdio")
        """
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
