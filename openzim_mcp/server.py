"""Main OpenZIM MCP server implementation."""

import ipaddress
import logging
from typing import Any, Literal, Optional

from mcp.types import Icon

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
from .instructions import instructions_for
from .mcp_envelope import EnvelopeAwareMCPServer
from .rate_limiter import RateLimiter
from .sdk_compat import install_ping_keepalive_shim
from .security import (
    PathValidator,
    redact_paths_in_message,
    sanitize_context_for_error,
)
from .simple_tools import SimpleToolsHandler
from .tools import register_phase_f_tools
from .zim_operations import ZimOperations

logger = logging.getLogger(__name__)

# TTL for results derived purely from the startup registration tables. One hour
# is a cache-lifetime choice, not a claim about the process: the tables cannot
# change without a restart, and a restart gives clients a new connection.
_STATIC_LIST_TTL_MS = 60 * 60 * 1000

# Identity advertised in ``serverInfo``. The docs site is the project's public
# face — a client that surfaces a "learn more" link should land users on
# documentation rather than the raw repository — and the icon is served from
# the same origin, so both live or die together with the published site.
PROJECT_WEBSITE_URL = "https://cameronrye.github.io/openzim-mcp/"
PROJECT_ICON_URL = "https://cameronrye.github.io/openzim-mcp/assets/logo.svg"

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
    """Build SDK Host allow-list entries from configured hostnames.

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
        if not _has_port_or_wildcard(host):
            allowed_hosts.append(f"{host}:*")
    return allowed_hosts


def _has_port_or_wildcard(host: str) -> bool:
    """True when ``host`` already carries a ``:port`` / ``:*`` suffix.

    A bare ``":" in host`` test misclassified bracketed IPv6 literals:
    ``[2001:db8::1]`` contains colons but no port, so it never got its
    ``:*`` variant and a proxied ``Host: [2001:db8::1]:443`` was 421'd
    (the hand-built loopback list shows both forms are required). For
    bracketed literals the port can only follow the closing bracket.
    """
    if host.startswith("["):
        bracket_end = host.rfind("]")
        return bracket_end != -1 and ":" in host[bracket_end:]
    return ":" in host


# Bind-all sentinels: a server bound here has no single client-facing Host to
# pin into the DNS-rebinding allow-list. These are literals we DETECT, not an
# address we bind — the actual bind host comes from config. (nosec B104.)
_BIND_ALL_HOSTS = frozenset({"0.0.0.0", "::", "[::]"})  # nosec B104


def _is_loopback_literal(host: str) -> bool:
    """Best-effort check that a configured bind host is a loopback literal."""
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1", "[::1]"}


def _cache_hints(config: OpenZimMcpConfig) -> dict:
    """Freshness hints for the 2026-07-28 ``CacheableResult`` fields.

    Clients cache a result for ``ttlMs`` and may re-serve it without asking
    again, so each value is a promise about how stale an answer may get.

    The list endpoints and ``server/discover`` describe the *registration*
    tables, which are built once at startup from ``tool_mode`` and never change
    while the process runs — nothing short of a restart can invalidate them, so
    they get a long TTL. That is also what makes them worth caching: a stable
    tool block is what earns a client's prompt-cache hits.

    ``resources/read`` is capped at the watcher's polling interval instead,
    because this hint is per *method* and that one method serves both a sealed
    archive and ``zim://files``, a live directory scan. The floor belongs to
    the mutable member: bounding it by the poll interval means a cached read is
    never staler than the server's own detection latency.

    That floor is the *fallback*, not the whole story. ``zim://{name}``
    overview reads carry a much longer TTL, stamped per URI by
    ``EnvelopeAwareMCPServer._handle_read_resource`` — the SDK fills only
    fields a handler left unset, so a handler's explicit ``ttl_ms`` wins over
    the value here. Everything else lands on this one: ``zim://files``,
    per-entry reads (no ``resources/updated`` is ever published for an entry
    URI), and overview bodies that report an error.

    ``cacheScope`` is ``private`` throughout: these payloads embed
    server-local absolute paths and configuration, so a shared intermediary
    must not serve one tenant's response to another.
    """
    from mcp.server import CacheHint

    static_hint = CacheHint(ttl_ms=_STATIC_LIST_TTL_MS, scope="private")
    return {
        "server/discover": static_hint,
        "tools/list": static_hint,
        "prompts/list": static_hint,
        "resources/list": static_hint,
        "resources/templates/list": static_hint,
        "resources/read": CacheHint(
            ttl_ms=config.watch_interval_seconds * 1000, scope="private"
        ),
    }


def _build_transport_security(
    config: OpenZimMcpConfig,
) -> tuple[Any, Optional[str]]:
    """Build SDK transport-security settings for an HTTP bind (returns settings + warning).

    Closes the gap where MCPServer, run without a ``host`` kwarg, defaults
    its DNS-rebinding allow-list to loopback only — so a non-loopback bind
    (0.0.0.0 or a fixed LAN IP) that passes the auth safe-startup check then
    421-rejects every MCP request because the real ``Host`` header is not in the
    loopback allow-list, while /healthz and /readyz still answer 200.
    """
    from mcp.server.transport_security import TransportSecuritySettings

    host = config.host
    allowed_origins = list(config.cors_origins)
    allowed_hosts = _build_transport_allowed_hosts(config.allowed_hosts)

    if _is_loopback_literal(host):
        # Loopback bind: the always-present loopback entries already cover it.
        return (
            TransportSecuritySettings(
                allowed_hosts=allowed_hosts, allowed_origins=allowed_origins
            ),
            None,
        )

    if host in _BIND_ALL_HOSTS:
        if config.allowed_hosts:
            # Operator pinned their public hostname(s); keep Host validation on.
            return (
                TransportSecuritySettings(
                    allowed_hosts=allowed_hosts, allowed_origins=allowed_origins
                ),
                None,
            )
        # Bound to all interfaces with no pinned Host. The client-facing Host
        # varies by reachable IP / container, so any Host allow-list would 421
        # every request. Disable DNS-rebinding Host validation — the auth token
        # (or the explicitly-acknowledged OPENZIM_MCP_INSECURE_DISABLE_AUTH) is
        # the access gate here — and surface the trade-off loudly.
        warning = (
            f"HTTP transport bound to {host} with no OPENZIM_MCP_ALLOWED_HOSTS "
            "set; disabling DNS-rebinding Host validation so direct-IP clients "
            "are not rejected with 421 Misdirected Request. Set "
            "OPENZIM_MCP_ALLOWED_HOSTS to your reachable hostname(s) to "
            "re-enable Host validation."
        )
        return (
            TransportSecuritySettings(
                enable_dns_rebinding_protection=False,
                allowed_hosts=allowed_hosts,
                allowed_origins=allowed_origins,
            ),
            warning,
        )

    # Bound to a specific non-loopback interface (e.g. a fixed LAN IP). Allow
    # direct access to that host (and its ":*" port form) so the deployment
    # works without forcing the operator to duplicate the bind host into
    # OPENZIM_MCP_ALLOWED_HOSTS. IPv6 literals are bracketed first: clients
    # send ``Host: [fd00::1]:8000``, so the raw unbracketed literal would
    # never match (and its embedded ``:`` would also suppress the ``:*``
    # variant), 421-ing every MCP request.
    try:
        is_ipv6 = ipaddress.ip_address(host).version == 6
    except ValueError:
        is_ipv6 = False
    if is_ipv6:
        host = f"[{host}]"
    if host not in allowed_hosts:
        allowed_hosts.append(host)
        if is_ipv6 or ":" not in host:
            allowed_hosts.append(f"{host}:*")
    return (
        TransportSecuritySettings(
            allowed_hosts=allowed_hosts, allowed_origins=allowed_origins
        ),
        None,
    )


class OpenZimMcpServer:
    """Main OpenZIM MCP server class with dependency injection."""

    def __init__(self, config: OpenZimMcpConfig):
        """Initialize OpenZIM MCP server.

        Args:
            config: Server configuration
        """
        # 2026-07-28 drops ping, so a stock SDK rejects keepalive pings on a
        # modern connection. This server answers them anyway, for clients that
        # ping on a timer — a deliberate deviation from the revision (see
        # ``sdk_compat`` and issue #371, where it was decided to keep this
        # permanently), installed before anything is served.
        install_ping_keepalive_shim()
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
            tool_mode=config.tool_mode,
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

        # Initialize MCP server. ``version`` is a constructor kwarg on the v2
        # SDK, so `serverInfo.version` advertises openzim-mcp's version rather
        # than the SDK default (which is the empty string).
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
        # ``instructions`` is advertised through ``server/discover`` (the
        # stateless protocol's replacement for the initialize handshake), so
        # cross-tool routing guidance lives there instead of being duplicated
        # across the tool descriptions.
        #
        # Transport security is no longer a constructor kwarg on the v2 SDK —
        # it is passed to the ASGI app builder at serve time. Resolve it here
        # anyway so a misconfigured allow-list is reported during startup
        # rather than on the first request.
        self._transport_security: Any = None
        if config.transport == "http":
            self._transport_security, host_warning = _build_transport_security(config)
            if host_warning:
                logger.warning(host_warning)

        # Subscription support is HTTP-only: the MtimeWatcher that emits
        # update notifications only runs under the HTTP lifespan (see
        # http_app.serve_streamable_http). Handing the server a bus in stdio
        # mode would advertise a capability we silently can't honor.
        #
        # The bus is the SDK's own fan-out for `subscriptions/listen`: it owns
        # the listener registry and the per-connection delivery that this
        # project previously hand-rolled against ServerSession internals.
        self.subscription_bus = None
        if config.subscriptions_enabled and config.transport == "http":
            from mcp.server.subscriptions import InMemorySubscriptionBus

            self.subscription_bus = InMemorySubscriptionBus()

        # ``website_url`` and ``icons`` ride in ``serverInfo``. Without them a
        # registry listing or client UI has nothing to show beyond a bare name
        # string. Both are served over https from the published docs site: an
        # icon fetched over plain http would be blocked as mixed content in any
        # browser-based client. ``title`` and ``description`` are the v2-only
        # remainder of the same identity surface — the display name a client
        # shows instead of the machine ``name``, and the one-liner next to it.
        self.mcp = EnvelopeAwareMCPServer(
            config.server_name,
            title="OpenZIM MCP",
            description=(
                "Enables AI models to access and search ZIM format "
                "knowledge bases offline"
            ),
            website_url=PROJECT_WEBSITE_URL,
            icons=[Icon(src=PROJECT_ICON_URL, mime_type="image/svg+xml")],
            instructions=instructions_for(config.tool_mode),
            version=__version__,
            subscriptions=self.subscription_bus,
            cache_hints=_cache_hints(config),
            archive_read_ttl_ms=config.resource_cache_ttl_seconds * 1000,
        )
        if self.subscription_bus is None:
            # Withholding the bus is not enough to withhold the capability:
            # the SDK substitutes its own private bus for ``None`` and
            # registers ``subscriptions/listen`` unconditionally, and the
            # modern capability derivation reports ``resources.subscribe``
            # and every ``listChanged`` flag purely from that handler's
            # presence. Drop the handler so the advertisement stays honest
            # and a listen request fails fast with method-not-found instead
            # of acking a stream that nothing will ever publish to.
            self.mcp._lowlevel_server._request_handlers.pop(
                "subscriptions/listen", None
            )
        else:
            # Bound the one dimension the SDK's handler leaves open: the
            # client-supplied URI set it holds for the stream's lifetime.
            from .subscriptions import install_bounded_listen_handler

            install_bounded_listen_handler(self.mcp, self.subscription_bus)
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
            logger.info("Running in SIMPLE mode with 1 intelligent tool (zim_query)")
        else:
            # ``get_server_configuration`` was deleted in v2.0.0; the
            # configuration it exposed is part of the zim_health payload.
            logger.debug(
                "Detailed configuration is available from the zim_health MCP tool"
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

        # Check for known error types using externalized config. The tool
        # name and a lazy archive counter let archive-path advice name only
        # the recovery steps this tool can honour (D02).
        # ``tool_mode`` keeps the recovery steps inside the registry the
        # client can actually see: simple mode registers ``zim_query`` alone,
        # so the templates' ``zim_health()`` advice would name a tool that
        # does not exist there.
        config = get_error_config(
            error,
            operation=operation,
            count_archives=lambda: len(self.zim_operations.list_zim_files_data()),
            tool_mode=self.config.tool_mode,
        )
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
            tool_mode=self.config.tool_mode,
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
        # 'http' is our short name for the SDK's 'streamable-http' wire value.
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
                run_kwargs: dict[str, Any] = {}
                if transport == "sse":
                    from . import http_app

                    # This is the one site that runs exactly once per SSE
                    # start and never on stdio/http, so the deprecation
                    # notice lives here rather than in main.py's argparse:
                    # operators who select SSE through
                    # OPENZIM_MCP_TRANSPORT, an MCP client config, or a
                    # library call never see argparse help at all. It is a
                    # logger.warning and not a DeprecationWarning because
                    # Python's default filters hide DeprecationWarning
                    # outside __main__ — the notice would be swallowed for
                    # exactly the operators it is aimed at — and because the
                    # other operator-facing startup notice (the INSECURE
                    # banner in check_safe_startup) already uses the logger.
                    logger.warning(
                        "DEPRECATED: the 'sse' transport is deprecated and "
                        "will be removed in the next major release (4.0.0). "
                        "Switch to --transport http (streamable HTTP): it is "
                        "the transport the current MCP revision specifies, "
                        "and the only network transport here that can "
                        "enforce an auth token."
                    )
                    http_app.check_safe_startup(self.config)
                    # The v2 SDK has no settings object: the SSE path takes
                    # host/port (and transport security) as run() kwargs, which
                    # it forwards to run_sse_async. HTTP+SSE is deprecated by
                    # the 2026-07-28 revision but still served by the SDK, so
                    # it keeps working here rather than being dropped as a
                    # side effect of the SDK upgrade.
                    run_kwargs = {
                        "host": self.config.host,
                        "port": self.config.port,
                        "transport_security": self._transport_security,
                    }
                self.mcp.run(transport=transport, **run_kwargs)
        except KeyboardInterrupt:
            logger.info("Server shutdown requested")
        except Exception as e:
            logger.error(f"Server error: {e}")
            raise
        finally:
            # M21: cancel queued timeout work and release the daemon pools so a
            # finite runaway doesn't delay exit by its full remaining duration.
            # (A truly-hung libzim worker runs on a daemon thread and is
            # abandoned rather than joined, so this never blocks.)
            from .timeout_utils import shutdown_timeout_executors

            shutdown_timeout_executors()
            logger.info("OpenZIM MCP server stopped")
