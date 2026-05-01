"""Main entry point for OpenZIM MCP server."""

import argparse
import atexit
import sys
from typing import Literal

from .config import OpenZimMcpConfig
from .constants import TOOL_MODE_SIMPLE, VALID_TOOL_MODES
from .exceptions import OpenZimMcpConfigurationError
from .instance_tracker import InstanceTracker
from .server import OpenZimMcpServer


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

  # Advanced mode (all 18 tools)
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
            f"Tool mode: 'advanced' for all 18 tools, 'simple' for 1 "
            f"intelligent NL tool + underlying tools "
            f"(default: {TOOL_MODE_SIMPLE}, or from OPENZIM_MCP_TOOL_MODE env var)"
        ),
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=None,
        help=(
            "Transport: 'stdio' (default, for local MCP clients) or 'http' "
            "(streamable HTTP). Env: OPENZIM_MCP_TRANSPORT"
        ),
    )
    parser.add_argument(
        "--host",
        default=None,
        help=("HTTP bind host (default 127.0.0.1). Env: OPENZIM_MCP_HOST"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=("HTTP bind port (default 8000). Env: OPENZIM_MCP_PORT"),
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

        config = OpenZimMcpConfig(**config_kwargs)

        # Initialize instance tracker
        instance_tracker = InstanceTracker()

        # Register the cleanup atexit BEFORE register_instance, so that even
        # a partially-completed registration (e.g. a write that succeeded for
        # one directory but raised on another) still gets cleaned up.
        def cleanup_instance() -> None:
            # Use silent mode - logging may be closed during shutdown
            instance_tracker.unregister_instance(silent=True)

        atexit.register(cleanup_instance)

        # Register this server instance. Filesystem errors here shouldn't
        # block startup — instance tracking is advisory.
        try:
            instance_tracker.register_instance(
                config_hash=config.get_config_hash(),
                allowed_directories=config.allowed_directories,
                server_name=config.server_name,
                transport=config.transport,
                host=config.host if config.transport == "http" else None,
                port=config.port if config.transport == "http" else None,
            )
        except Exception as e:
            print(
                f"Warning: failed to register instance for tracking: {e}",
                file=sys.stderr,
            )

        # Create and run server
        server = OpenZimMcpServer(config, instance_tracker)

        mode_desc = (
            "SIMPLE mode (1 intelligent tool + all underlying tools)"
            if config.tool_mode == TOOL_MODE_SIMPLE
            else "ADVANCED mode (18 specialized tools)"
        )
        print(
            f"OpenZIM MCP server started in {mode_desc}",
            file=sys.stderr,
        )
        print(
            f"Allowed directories: {', '.join(args.directories)}",
            file=sys.stderr,
        )

        # Map user-facing 'http' to FastMCP's wire value 'streamable-http'.
        transport_arg: Literal["stdio", "streamable-http"] = (
            "streamable-http" if config.transport == "http" else "stdio"
        )
        server.run(transport=transport_arg)

    except OpenZimMcpConfigurationError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Server startup error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
