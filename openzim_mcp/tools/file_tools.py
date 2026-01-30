"""File listing tools for OpenZIM MCP server."""

import logging
from typing import TYPE_CHECKING

from ..exceptions import OpenZimMcpRateLimitError

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def register_file_tools(server: "OpenZimMcpServer") -> None:
    """
    Register file listing tools.

    Args:
        server: The OpenZimMcpServer instance to register tools on
    """

    @server.mcp.tool()
    async def list_zim_files() -> str:
        """List all ZIM files in allowed directories.

        Includes automatic conflict detection and warnings if multiple
        server instances are detected.

        Returns:
            JSON string containing the list of ZIM files and any warnings
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("default")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="list ZIM files",
                    error=e,
                    context="Listing available ZIM files",
                )

            # Get the basic ZIM files list using async operations
            zim_files_result = await server.async_zim_operations.list_zim_files()

            # Check for conflicts if instance tracker is available
            warnings = []
            if server.instance_tracker:
                try:
                    conflicts = server.instance_tracker.detect_conflicts(
                        server.config.get_config_hash()
                    )
                    if conflicts:
                        for conflict in conflicts:
                            if conflict["type"] == "configuration_mismatch":
                                warnings.append(
                                    {
                                        "type": "configuration_conflict",
                                        "message": (
                                            "WARNING: Configuration mismatch detected "
                                            f"with server PID "
                                            f"{conflict['instance']['pid']}"
                                        ),
                                        "resolution": (
                                            "Different server configurations may "
                                            "cause inconsistent results. Consider "
                                            "stopping other instances or ensuring they "
                                            "use the same configuration."
                                        ),
                                        "severity": "high",
                                    }
                                )
                            elif conflict["type"] == "multiple_instances":
                                warnings.append(
                                    {
                                        "type": "multiple_servers",
                                        "message": (
                                            "WARNING: Multiple server instances "
                                            f"detected (PID "
                                            f"{conflict['instance']['pid']})"
                                        ),
                                        "resolution": (
                                            "Multiple servers may cause confusion. "
                                            "Use 'diagnose_server_state()' for "
                                            "analysis or stop unused instances."
                                        ),
                                        "severity": "medium",
                                    }
                                )
                except Exception as e:
                    warnings.append(
                        {
                            "type": "diagnostic_error",
                            "message": f"Could not check for server conflicts: {e}",
                            "resolution": (
                                "Server conflict detection failed. Results may "
                                "be from a different server instance."
                            ),
                            "severity": "low",
                        }
                    )

            # If there are warnings, prepend them to the result
            if warnings:
                warning_text = "\nSERVER DIAGNOSTICS:\n"
                for warning in warnings:
                    warning_text += f"\n{warning['message']}\n"
                    warning_text += f"Resolution: {warning['resolution']}\n"

                warning_text += "\nZIM FILES:\n"
                return warning_text + zim_files_result
            else:
                return zim_files_result

        except Exception as e:
            logger.error(f"Error listing ZIM files: {e}")
            return server._create_enhanced_error_message(
                operation="list ZIM files",
                error=e,
                context="Scanning allowed directories for ZIM files",
            )
