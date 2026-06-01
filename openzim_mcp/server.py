"""Main OpenZIM MCP server implementation."""

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
from .tools import register_phase_f_tools
from .zim_operations import ZimOperations

logger = logging.getLogger(__name__)

# Loopback entries always present in the Host allow-list so localhost-direct
# access keeps working alongside any proxied hostname. Both the bare host and
# its ``:*`` wildcard-port form are listed: the SDK matcher treats a portless
# ``Host`` header and a ``host:port`` header as distinct cases.
_LOOPBACK_TRANSPORT_HOSTS = (
    "127.0.0.1",
    "127.0.0.1:*",
    "localhost",
    "localhost:*",
    "[::1]",
    "[::1]:*",
)


def _build_transport_allowed_hosts(configured_hosts: list[str]) -> list[str]:
    """Build FastMCP Host allow-list entries from configured hostnames.

    The MCP SDK matcher (``mcp.server.transport_security``) accepts a request
    whose ``Host`` is ``base_host:port`` only when the allow-list holds a
    pattern ending in ``:*``; a bare entry matches just the exact portless
    host. A reverse proxy or Tailscale serve typically forwards
    ``Host: mcp.example.com:443``, so a bare configured ``mcp.example.com``
    would be rejected with 421. We therefore add a ``host:*`` variant for any
    configured host that does not already carry a port/wildcard, while leaving
    explicit ``host:*`` entries untouched (no double ``:*:*``).
    """
    allowed_hosts = list(_LOOPBACK_TRANSPORT_HOSTS)
    for host in configured_hosts:
        allowed_hosts.append(host)
        if ":" not in host:
            allowed_hosts.append(f"{host}:*")
    return allowed_hosts


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

        # Phase F: simple_tools_handler backs zim_query in BOTH simple and
        # advanced modes (the simple/advanced split is now a registration-
        # time filter on the same code path). zim_search.py does NOT use
        # the handler — it calls topic_preprocessing functions directly —
        # but the handler is still load-bearing for zim_query. Initialize
        # unconditionally.
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
                allowed_hosts=_build_transport_allowed_hosts(config.allowed_hosts),
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

    def _register_tools(self) -> None:
        """Register MCP tools via the Phase F orchestrator.

        The orchestrator reads ``self.config.tool_mode`` and registers
        the right tool set itself (simple → ``zim_query`` only;
        advanced → all 8 Phase F tools plus resources + prompts). The
        b13 simple/advanced split lived in this method as two separate
        registration code paths; Phase F collapses them into one
        registration-time filter.
        """
        register_phase_f_tools(self)
        logger.info("MCP tools registered via Phase F orchestrator")

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
