"""Main entry point for OpenZIM MCP server."""

import argparse
import sys
from typing import Literal

from .config import OpenZimMcpConfig
from .constants import TOOL_MODE_SIMPLE, VALID_TOOL_MODES
from .exceptions import OpenZimMcpConfigurationError
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

        config = OpenZimMcpConfig(**config_kwargs)

        # Create and run server
        server = OpenZimMcpServer(config)

        mode_desc = (
            "SIMPLE mode (1 intelligent tool + all underlying tools)"
            if config.tool_mode == TOOL_MODE_SIMPLE
            else "ADVANCED mode (21 specialized tools)"
        )
        print(
            f"OpenZIM MCP server started in {mode_desc}",
            file=sys.stderr,
        )
        print(
            f"Allowed directories: {', '.join(args.directories)}",
            file=sys.stderr,
        )

        # Map user-facing transport to FastMCP's wire value.
        # 'http' is our short name for FastMCP's 'streamable-http'.
        transport_map: dict[str, Literal["stdio", "sse", "streamable-http"]] = {
            "stdio": "stdio",
            "http": "streamable-http",
            "sse": "sse",
        }
        server.run(transport=transport_map[config.transport])

    except OpenZimMcpConfigurationError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Server startup error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
