"""Main entry point for OpenZIM MCP server."""

import argparse
import atexit
import sys

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

        config = OpenZimMcpConfig(**config_kwargs)

        # Initialize instance tracker
        instance_tracker = InstanceTracker()

        # Register this server instance
        instance_tracker.register_instance(
            config_hash=config.get_config_hash(),
            allowed_directories=config.allowed_directories,
            server_name=config.server_name,
        )

        # Register cleanup function
        def cleanup_instance() -> None:
            # Use silent mode - logging may be closed during shutdown
            instance_tracker.unregister_instance(silent=True)

        atexit.register(cleanup_instance)

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

        server.run(transport="stdio")

    except OpenZimMcpConfigurationError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Server startup error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
