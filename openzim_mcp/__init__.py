"""OpenZIM MCP - ZIM MCP Server.

A modern, secure MCP server for accessing ZIM format knowledge bases offline.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("openzim-mcp")
except PackageNotFoundError:
    # Editable install without metadata, or running from source tree without
    # installation. Fall back to a sentinel so callers still get a string.
    __version__ = "0.0.0+unknown"

__author__ = "Cameron Rye"

from .config import OpenZimMcpConfig
from .exceptions import (
    OpenZimMcpError,
    OpenZimMcpSecurityError,
    OpenZimMcpValidationError,
)
from .server import OpenZimMcpServer

__all__ = [
    "OpenZimMcpServer",
    "OpenZimMcpConfig",
    "OpenZimMcpError",
    "OpenZimMcpSecurityError",
    "OpenZimMcpValidationError",
]
