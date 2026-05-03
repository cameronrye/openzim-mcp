"""Main entry point for OpenZIM MCP server."""

import argparse
import logging
import sys

from pydantic import ValidationError as PydanticValidationError

from .config import OpenZimMcpConfig
from .constants import TOOL_MODE_SIMPLE, VALID_TOOL_MODES
from .exceptions import OpenZimMcpConfigurationError
from .server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def main() -> None:
    """Run the OpenZIM MCP server."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="OpenZIM MCP Server - Access ZIM files through MCP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Simple mode (default - 1 intelligent NL tool)
  python -m openzim_mcp /path/to/zim/files
  python -m openzim_mcp --mode simple /path/to/zim/files

  # Advanced mode (all 21 tools)
  python -m openzim_mcp --mode advanced /path/to/zim/files

Environment Variables:
  OPENZIM_MCP_TOOL_MODE - Set tool mode (advanced or simple)
        """,
    )
    parser.add_argument(
        "directories",
        nargs="+",
        help="One or more directories containing ZIM files",
    )
    parser.add_argument(
        "--mode",
        choices=list(VALID_TOOL_MODES),
        default=None,
        help=(
            f"Tool mode: 'advanced' for all 21 tools, 'simple' for 1 "
            f"intelligent NL tool + underlying tools "
            f"(default: {TOOL_MODE_SIMPLE}, or from OPENZIM_MCP_TOOL_MODE env var)"
        ),
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse"],
        default=None,
        help=(
            "Transport: 'stdio' (default, for local MCP clients), 'http' "
            "(streamable HTTP), or 'sse' (legacy SSE — no auth middleware, "
            "localhost only). Env: OPENZIM_MCP_TRANSPORT"
        ),
    )
    parser.add_argument(
        "--host",
        default=None,
        help=("HTTP/SSE bind host (default 127.0.0.1). Env: OPENZIM_MCP_HOST"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=("HTTP/SSE bind port (default 8000). Env: OPENZIM_MCP_PORT"),
    )

    # Handle case where no arguments provided
    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    try:
        # Create configuration with tool mode
        config_kwargs = {"allowed_directories": args.directories}
        if args.mode:
            config_kwargs["tool_mode"] = args.mode
        if args.transport:
            config_kwargs["transport"] = args.transport
        if args.host:
            config_kwargs["host"] = args.host
        if args.port is not None:
            config_kwargs["port"] = args.port

        try:
            config = OpenZimMcpConfig(**config_kwargs)
        except PydanticValidationError as exc:
            # Pydantic v2 wraps any exception raised inside a field_validator
            # (including our own OpenZimMcpConfigurationError) in a
            # ValidationError. Re-surface as OpenZimMcpConfigurationError so
            # the operator sees the targeted message rather than pydantic's
            # multi-line validation dump.
            messages = []
            for err in exc.errors():
                ctx_err = err.get("ctx", {}).get("error")
                if ctx_err is not None:
                    messages.append(str(ctx_err))
                else:
                    loc = ".".join(str(p) for p in err.get("loc", ()))
                    messages.append(
                        f"{loc}: {err.get('msg', 'invalid')}"
                        if loc
                        else err.get("msg", "invalid")
                    )
            raise OpenZimMcpConfigurationError("; ".join(messages)) from exc

        # Create and run server
        server = OpenZimMcpServer(config)

        mode_desc = (
            "SIMPLE mode (1 intelligent tool + all underlying tools)"
            if config.tool_mode == TOOL_MODE_SIMPLE
            else "ADVANCED mode (21 specialized tools)"
        )
        # Route the startup banner through the logger so log-level configuration
        # (env: ``OPENZIM_MCP_LOGGING__LEVEL``) actually suppresses it. The
        # original ``print(..., file=sys.stderr)`` calls bypassed logging and
        # emitted regardless of operator-configured verbosity.
        logger.info("OpenZIM MCP server started in %s", mode_desc)
        logger.info("Allowed directories: %s", ", ".join(args.directories))

        # ``OpenZimMcpServer.run()`` derives the wire transport from
        # ``config.transport`` directly (translating our short name 'http'
        # to FastMCP's 'streamable-http'); calling without an argument keeps
        # the configured transport and the runtime transport in sync.
        server.run()

    except OpenZimMcpConfigurationError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Server startup error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
