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


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser used by ``main``."""
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
            f"intelligent NL tool "
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
    return parser


def _config_kwargs_from_args(args: argparse.Namespace) -> dict:
    """Translate parsed CLI args into OpenZimMcpConfig keyword arguments."""
    kwargs: dict = {"allowed_directories": args.directories}
    if args.mode:
        kwargs["tool_mode"] = args.mode
    if args.transport:
        kwargs["transport"] = args.transport
    if args.host:
        kwargs["host"] = args.host
    if args.port is not None:
        kwargs["port"] = args.port
    return kwargs


def _format_pydantic_error(exc: PydanticValidationError) -> str:
    """Flatten a pydantic ValidationError into a single readable message.

    Pydantic v2 wraps any exception raised inside a field_validator
    (including our own OpenZimMcpConfigurationError) in a ValidationError.
    Re-surface the original message instead of pydantic's multi-line dump.
    """
    messages = []
    for err in exc.errors():
        ctx_err = err.get("ctx", {}).get("error")
        if ctx_err is not None:
            messages.append(str(ctx_err))
            continue
        loc = ".".join(str(p) for p in err.get("loc", ()))
        msg = err.get("msg", "invalid")
        messages.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(messages)


def main() -> None:
    """Run the OpenZIM MCP server."""
    parser = _build_arg_parser()

    if len(sys.argv) == 1:
        parser.print_help(sys.stderr)
        sys.exit(1)

    args = parser.parse_args()

    try:
        try:
            config = OpenZimMcpConfig(**_config_kwargs_from_args(args))
        except PydanticValidationError as exc:
            raise OpenZimMcpConfigurationError(_format_pydantic_error(exc)) from exc

        server = OpenZimMcpServer(config)

        mode_desc = (
            "SIMPLE mode (1 intelligent tool)"
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
