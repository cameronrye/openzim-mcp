"""
Main entry point for OpenZIM MCP server.
"""

import atexit
import sys

from .config import OpenZimMcpConfig
from .exceptions import OpenZimMcpConfigurationError
from .instance_tracker import InstanceTracker
from .server import OpenZimMcpServer


def main() -> None:
    """Main entry point for OpenZIM MCP server."""
    args = sys.argv[1:]

    if not args:
        print(
            "Usage: python -m openzim_mcp <allowed_directory> [other_directories...]",
            file=sys.stderr,
        )
        print(
            "   or: uv run openzim_mcp/main.py <allowed_directory> [other_directories...]",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        # Create configuration
        config = OpenZimMcpConfig(allowed_directories=args)

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
            # Use silent mode to avoid logging during shutdown when logging system may be closed
            instance_tracker.unregister_instance(silent=True)

        atexit.register(cleanup_instance)

        # Create and run server
        server = OpenZimMcpServer(config, instance_tracker)

        print(
            f"OpenZIM MCP server started, allowed directories: {', '.join(args)}",
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
