"""
OpenZIM MCP - ZIM MCP Server

A modern, secure MCP server for accessing ZIM format knowledge bases offline.
"""

__version__ = "0.7.0"
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
