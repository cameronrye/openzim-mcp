"""Main OpenZIM MCP server implementation."""

import logging
from typing import Any, Dict, List, Literal, Optional

from mcp.server.fastmcp import FastMCP

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
from .instance_tracker import InstanceTracker
from .rate_limiter import RateLimitConfig, RateLimiter
from .security import PathValidator, sanitize_context_for_error
from .simple_tools import SimpleToolsHandler
from .tools import register_all_tools
from .zim_operations import ZimOperations

logger = logging.getLogger(__name__)


class OpenZimMcpServer:
    """Main OpenZIM MCP server class with dependency injection."""

    def __init__(
        self,
        config: OpenZimMcpConfig,
        instance_tracker: Optional[InstanceTracker] = None,
    ):
        """Initialize OpenZIM MCP server.

        Args:
            config: Server configuration
            instance_tracker: Optional instance tracker for multi-server management
        """
        self.config = config
        self.instance_tracker = instance_tracker

        # Setup logging
        config.setup_logging()
        logger.info(f"Initializing OpenZIM MCP server v{config.server_name}")

        # Initialize components
        self.path_validator = PathValidator(config.allowed_directories)
        self.cache = OpenZimMcpCache(config.cache)
        self.content_processor = ContentProcessor(config.content.snippet_length)
        self.rate_limiter = RateLimiter(
            RateLimitConfig(
                enabled=config.rate_limit.enabled,
                requests_per_second=config.rate_limit.requests_per_second,
                burst_size=config.rate_limit.burst_size,
            )
        )
        self.zim_operations = ZimOperations(
            config, self.path_validator, self.cache, self.content_processor
        )
        self.async_zim_operations = AsyncZimOperations(self.zim_operations)

        # Initialize simple tools handler if in simple mode
        self.simple_tools_handler = None
        if config.tool_mode == TOOL_MODE_SIMPLE:
            self.simple_tools_handler = SimpleToolsHandler(self.zim_operations)

        # Initialize MCP server
        self.mcp = FastMCP(config.server_name)
        self._register_tools()

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
                "Use get_server_configuration() or diagnose_server_state() MCP tools "
                "for detailed configuration and diagnostics"
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
        base_message = str(error)
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

    def _format_conflict_warnings(self, conflicts: List[Dict[str, Any]]) -> str:
        """Format conflict detection warnings for appending to results."""
        if not conflicts:
            return ""

        warning = "\n\n**Server Conflict Detected**\n"
        for conflict in conflicts:
            if conflict["type"] == "configuration_mismatch":
                warning += (
                    f"WARNING: Configuration mismatch with server "
                    f"PID {conflict['instance']['pid']}. "
                    f"Results may be inconsistent.\n"
                )
            elif conflict["type"] == "multiple_instances":
                warning += (
                    f"WARNING: Multiple servers detected "
                    f"(PID {conflict['instance']['pid']}). "
                    f"Results may come from different server instances.\n"
                )
        warning += "\nTIP: Use 'resolve_server_conflicts()' to fix these issues.\n"
        return warning

    def _check_and_append_conflict_warnings(self, result: str) -> str:
        """Check for conflicts and append warnings to result if found.

        This helper method reduces code duplication by encapsulating the common
        pattern of checking for instance conflicts and appending warnings to
        operation results.

        Args:
            result: The operation result string to potentially append warnings to

        Returns:
            The result string, with conflict warnings appended if any were detected
        """
        if not self.instance_tracker:
            return result
        try:
            conflicts = self.instance_tracker.detect_conflicts(
                self.config.get_config_hash()
            )
            conflict_warning = self._format_conflict_warnings(conflicts)
            if conflict_warning:
                return result + conflict_warning
        except Exception as e:
            logger.debug(f"Failed to check for conflicts: {e}")
        return result

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

                # Use simple tools handler
                if self.simple_tools_handler:
                    return self.simple_tools_handler.handle_zim_query(
                        query, zim_file_path, options
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
        """Register advanced mode tools (all 18 tools).

        Tools are organized into logical groups in separate modules:
        - File tools: list_zim_files
        - Search tools: search_zim_file
        - Content tools: get_zim_entry
        - Server tools: get_server_health, get_server_configuration,
                       diagnose_server_state, resolve_server_conflicts
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
            self.mcp.run(transport=transport)
        except KeyboardInterrupt:
            logger.info("Server shutdown requested")
        except Exception as e:
            logger.error(f"Server error: {e}")
            raise
        finally:
            logger.info("OpenZIM MCP server stopped")
