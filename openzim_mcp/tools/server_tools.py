"""Server health and diagnostics tools for OpenZIM MCP server."""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List

from ..constants import CACHE_HIGH_HIT_RATE_THRESHOLD, CACHE_LOW_HIT_RATE_THRESHOLD
from ..security import redact_paths_in_message, sanitize_path_for_error

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def register_server_tools(server: "OpenZimMcpServer") -> None:
    """Register server health and diagnostics tools.

    Args:
        server: The OpenZimMcpServer instance to register tools on
    """

    @server.mcp.tool()
    async def get_server_health() -> str:
        """Get comprehensive server health and statistics.

        Includes cache performance, directory health, and recommendations.

        Returns:
            JSON string containing detailed server health information
        """
        return await asyncio.to_thread(_get_server_health_sync)

    def _get_server_health_sync() -> str:
        try:
            cache_stats = server.cache.stats()
            recommendations: List[str] = []
            warnings: List[str] = []
            health_checks: Dict[str, Any] = {
                "directories_accessible": 0,
                "zim_files_found": 0,
                "permissions_ok": True,
            }
            health_info = {
                "timestamp": datetime.now().isoformat(),
                "status": "healthy",
                "server_name": server.config.server_name,
                "uptime_info": {
                    # Redact PID — diagnostic output may end up in bug reports.
                    "process_id": "[REDACTED]",
                    "started_at": getattr(server, "_start_time", "unknown"),
                },
                "configuration": {
                    "allowed_directories": len(server.config.allowed_directories),
                    "cache_enabled": server.config.cache.enabled,
                    "config_hash": server.config.get_config_hash()[:8] + "...",
                },
                "cache_performance": cache_stats,
                "health_checks": health_checks,
                "recommendations": recommendations,
                "warnings": warnings,
            }

            # Directory and file health checks
            accessible_dirs = 0
            total_zim_files = 0

            for directory in server.config.allowed_directories:
                # Sanitize the path before it ever lands in user-visible
                # warning/recommendation strings — diagnostic output is
                # frequently copy-pasted into bug reports and must not
                # leak host topology.
                redacted = sanitize_path_for_error(str(directory))
                try:
                    dir_path = Path(directory)
                    if dir_path.exists() and dir_path.is_dir():
                        list(dir_path.iterdir())
                        accessible_dirs += 1
                        zim_files = list(dir_path.glob("**/*.zim"))
                        total_zim_files += len(zim_files)
                    else:
                        warnings.append(f"Directory not accessible: {redacted}")
                        recommendations.append(
                            f"Check directory path and permissions: {redacted}"
                        )
                        if health_info["status"] == "healthy":
                            health_info["status"] = "warning"
                except PermissionError:
                    warnings.append(f"Permission denied: {redacted}")
                    recommendations.append(f"Check file permissions for: {redacted}")
                    health_checks["permissions_ok"] = False
                    if health_info["status"] == "healthy":
                        health_info["status"] = "warning"
                except Exception as e:
                    warnings.append(
                        f"Error accessing {redacted}: "
                        f"{redact_paths_in_message(str(e))}"
                    )
                    if health_info["status"] == "healthy":
                        health_info["status"] = "warning"

            health_checks["directories_accessible"] = accessible_dirs
            health_checks["zim_files_found"] = total_zim_files

            # Cache performance analysis
            if cache_stats.get("enabled", False):
                hit_rate = cache_stats.get("hit_rate", 0)
                if hit_rate < CACHE_LOW_HIT_RATE_THRESHOLD:
                    recommendations.append(
                        "Cache hit rate is low — consider issuing repeated "
                        "queries against the same ZIM files"
                    )
                elif hit_rate > CACHE_HIGH_HIT_RATE_THRESHOLD:
                    recommendations.append("Cache is performing well")
            else:
                recommendations.append("Consider enabling cache for better performance")

            # Overall health assessment
            if total_zim_files == 0:
                warnings.append("No ZIM files found in any directory")
                recommendations.append("Add ZIM files to configured directories")
                if health_info["status"] == "healthy":
                    health_info["status"] = "warning"

            if accessible_dirs == 0:
                health_info["status"] = "error"
                recommendations.append(
                    "Fix directory accessibility issues before using the server"
                )

            if health_info["status"] == "healthy" and not recommendations:
                recommendations.append("Server is running optimally")

            return json.dumps(health_info, indent=2)

        except Exception as e:
            logger.error(f"Error getting server health: {e}")
            return server._create_enhanced_error_message(
                operation="get server health",
                error=e,
                context="Checking server health and performance metrics",
            )

    @server.mcp.tool()
    async def get_server_configuration() -> str:
        """Get detailed server configuration with diagnostics and validation.

        Returns:
            Server configuration information including validation results
            and recommendations
        """
        return await asyncio.to_thread(_get_server_configuration_sync)

    def _get_server_configuration_sync() -> str:
        try:
            # Always redact paths and PID — even on stdio, diagnostic
            # output frequently ends up in bug reports / logs / issue
            # trackers, so leaking host topology is an info-disclosure
            # risk regardless of transport. The unredacted values remain
            # available to operators in server logs.
            config_info = {
                "server_name": server.config.server_name,
                "allowed_directories": [
                    sanitize_path_for_error(str(p))
                    for p in server.config.allowed_directories
                ],
                "allowed_directories_count": len(server.config.allowed_directories),
                "cache_enabled": server.config.cache.enabled,
                "cache_max_size": server.config.cache.max_size,
                "cache_ttl_seconds": server.config.cache.ttl_seconds,
                "content_max_length": server.config.content.max_content_length,
                "content_snippet_length": server.config.content.snippet_length,
                "search_default_limit": server.config.content.default_search_limit,
                "config_hash": server.config.get_config_hash(),
                "server_pid": "[REDACTED]",
            }

            warnings_list: List[str] = []
            recommendations_list: List[str] = []
            diagnostics = {
                "validation_status": "ok",
                "warnings": warnings_list,
                "recommendations": recommendations_list,
            }

            invalid_dirs = []
            for directory in server.config.allowed_directories:
                dir_path = Path(directory)
                if not dir_path.exists():
                    invalid_dirs.append(sanitize_path_for_error(str(directory)))

            if invalid_dirs:
                diagnostics["validation_status"] = "error"
                warnings_list.append(f"Invalid directories: {invalid_dirs}")
                recommendations_list.append(
                    "Check that all allowed directories exist and are accessible"
                )

            result = {
                "configuration": config_info,
                "diagnostics": diagnostics,
                "timestamp": datetime.now().isoformat(),
            }

            return json.dumps(result, indent=2)
        except Exception as e:
            logger.error(f"Error getting server configuration: {e}")
            return server._create_enhanced_error_message(
                operation="get server configuration",
                error=e,
                context="Configuration diagnostics",
            )
