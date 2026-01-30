"""Server health and diagnostics tools for OpenZIM MCP server."""

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, cast

from ..constants import CACHE_HIGH_HIT_RATE_THRESHOLD, CACHE_LOW_HIT_RATE_THRESHOLD

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

        Includes instance tracking status, conflict detection, cache performance,
        and recommendations for maintaining server health.

        Returns:
            JSON string containing detailed server health information
        """
        try:
            cache_stats = server.cache.stats()
            recommendations: List[str] = []
            warnings: List[str] = []
            instance_tracking: Dict[str, Any] = {
                "enabled": server.instance_tracker is not None,
                "active_instances": 0,
                "conflicts_detected": 0,
                "stale_instances": 0,
            }
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
                    "process_id": os.getpid(),
                    "started_at": getattr(server, "_start_time", "unknown"),
                },
                "configuration": {
                    "allowed_directories": len(server.config.allowed_directories),
                    "cache_enabled": server.config.cache.enabled,
                    "config_hash": server.config.get_config_hash()[:8]
                    + "...",  # Short hash for display
                },
                "cache_performance": cache_stats,
                "instance_tracking": instance_tracking,
                "health_checks": health_checks,
                "recommendations": recommendations,
                "warnings": warnings,
            }

            # Instance tracking health
            if server.instance_tracker:
                try:
                    active_instances = server.instance_tracker.get_active_instances()
                    instance_tracking["active_instances"] = len(active_instances)

                    conflicts = server.instance_tracker.detect_conflicts(
                        server.config.get_config_hash()
                    )
                    instance_tracking["conflicts_detected"] = len(conflicts)

                    if conflicts:
                        health_info["status"] = "warning"
                        warnings.append(
                            f"Server conflicts detected ({len(conflicts)} instances)"
                        )
                        recommendations.append(
                            "Use 'resolve_server_conflicts()' to address "
                            "instance conflicts"
                        )

                    # Check for stale instances
                    try:
                        stale_count = len(
                            [
                                inst
                                for inst in active_instances
                                if not server.instance_tracker._is_process_running(
                                    inst.pid
                                )
                            ]
                        )
                        instance_tracking["stale_instances"] = stale_count
                        if stale_count > 0:
                            warnings.append(
                                f"Stale instance files detected ({stale_count})"
                            )
                            recommendations.append(
                                "Use 'resolve_server_conflicts()' to clean "
                                "up stale instances"
                            )
                    except Exception as e:
                        logger.debug(f"Failed to get instance stats: {e}")

                except Exception as e:
                    warnings.append(f"Instance tracking check failed: {e}")
            else:
                warnings.append("Instance tracking not available")
                recommendations.append(
                    "Instance tracking helps prevent server conflicts"
                )

            # Directory and file health checks
            accessible_dirs = 0
            total_zim_files = 0

            for directory in server.config.allowed_directories:
                try:
                    dir_path = Path(directory)
                    if dir_path.exists() and dir_path.is_dir():
                        # Test readability
                        list(dir_path.iterdir())
                        accessible_dirs += 1

                        # Count ZIM files
                        zim_files = list(dir_path.glob("**/*.zim"))
                        total_zim_files += len(zim_files)
                    else:
                        warnings.append(f"Directory not accessible: {directory}")
                        recommendations.append(
                            f"Check directory path and permissions: {directory}"
                        )
                        if health_info["status"] == "healthy":
                            health_info["status"] = "warning"
                except PermissionError:
                    warnings.append(f"Permission denied: {directory}")
                    recommendations.append(f"Check file permissions for: {directory}")
                    health_checks["permissions_ok"] = False
                    if health_info["status"] == "healthy":
                        health_info["status"] = "warning"
                except Exception as e:
                    warnings.append(f"Error accessing {directory}: {e}")
                    if health_info["status"] == "healthy":
                        health_info["status"] = "warning"

            health_checks["directories_accessible"] = accessible_dirs
            health_checks["zim_files_found"] = total_zim_files

            # Cache performance analysis
            if cache_stats.get("enabled", False):
                hit_rate = cache_stats.get("hit_rate", 0)
                if hit_rate < CACHE_LOW_HIT_RATE_THRESHOLD:
                    recommendations.append(
                        "Cache hit rate is low - consider warming up "
                        "cache with common queries"
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

            # Add general recommendations if everything is healthy
            if health_info["status"] == "healthy" and not recommendations:
                recommendations.extend(
                    [
                        "Server is running optimally",
                        "Use 'diagnose_server_state()' for detailed diagnostics",
                        "Monitor cache performance with regular health checks",
                    ]
                )

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
            Server configuration information including conflict detection,
            validation results, and recommendations
        """
        try:
            # Basic configuration info
            config_info = {
                "server_name": server.config.server_name,
                "allowed_directories": server.config.allowed_directories,
                "cache_enabled": server.config.cache.enabled,
                "cache_max_size": server.config.cache.max_size,
                "cache_ttl_seconds": server.config.cache.ttl_seconds,
                "content_max_length": server.config.content.max_content_length,
                "content_snippet_length": server.config.content.snippet_length,
                "search_default_limit": server.config.content.default_search_limit,
                "config_hash": server.config.get_config_hash(),
                "server_pid": os.getpid(),
            }

            # Add diagnostic information
            warnings_list: List[str] = []
            recommendations_list: List[str] = []
            conflicts_detected_list: List[Dict[str, Any]] = []
            diagnostics = {
                "conflicts_detected": conflicts_detected_list,
                "validation_status": "ok",
                "warnings": warnings_list,
                "recommendations": recommendations_list,
            }

            # Check for instance conflicts if tracker is available
            if server.instance_tracker:
                try:
                    conflicts = server.instance_tracker.detect_conflicts(
                        server.config.get_config_hash()
                    )
                    if conflicts:
                        conflicts_detected_list.extend(conflicts)
                        diagnostics["validation_status"] = "warning"
                        warnings_list.append(
                            f"Found {len(conflicts)} potential server conflicts"
                        )
                        recommendations_list.append(
                            "Multiple server instances detected. Use "
                            "diagnose_server_state() for detailed analysis."
                        )
                except Exception as e:
                    warnings_list.append(f"Could not check for conflicts: {e}")

            # Basic directory validation
            invalid_dirs = []
            for directory in server.config.allowed_directories:
                dir_path = Path(directory)
                if not dir_path.exists():
                    invalid_dirs.append(directory)

            if invalid_dirs:
                diagnostics["validation_status"] = "error"
                warnings_list.append(f"Invalid directories: {invalid_dirs}")
                recommendations_list.append(
                    "Check that all allowed directories exist and are accessible"
                )

            # Combine configuration and diagnostics
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

    @server.mcp.tool()
    async def diagnose_server_state() -> str:
        """Comprehensive server diagnostics accessible to LLM users.

        Checks for multiple instances, validates configuration, checks file
        accessibility, and returns actionable recommendations.

        Returns:
            JSON string containing diagnostic results and recommendations
        """
        try:
            conflicts_list: List[Dict[str, Any]] = []
            issues_list: List[str] = []
            recommendations_list: List[str] = []
            environment_checks: Dict[str, Any] = {}
            diagnostics = {
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "server_info": {
                    "pid": os.getpid(),
                    "server_name": server.config.server_name,
                    "config_hash": server.config.get_config_hash(),
                },
                "configuration": {
                    "allowed_directories": server.config.allowed_directories,
                    "cache_enabled": server.config.cache.enabled,
                    "cache_max_size": server.config.cache.max_size,
                },
                "conflicts": conflicts_list,
                "issues": issues_list,
                "recommendations": recommendations_list,
                "environment_checks": environment_checks,
            }

            # Check for instance conflicts if tracker is available
            if server.instance_tracker:
                try:
                    conflicts = server.instance_tracker.detect_conflicts(
                        server.config.get_config_hash()
                    )
                    conflicts_list.extend(conflicts)

                    if conflicts:
                        diagnostics["status"] = "warning"
                        for conflict in conflicts:
                            if conflict["type"] == "configuration_mismatch":
                                recommendations_list.append(
                                    "Configuration mismatch detected with "
                                    "another server. Consider stopping other "
                                    "instances or using same configuration."
                                )
                            elif conflict["type"] == "multiple_instances":
                                recommendations_list.append(
                                    f"Multiple servers detected "
                                    f"(PID: {conflict['instance']['pid']}). "
                                    f"Consider stopping unused instances."
                                )
                except Exception as e:
                    issues_list.append(f"Failed to check for conflicts: {e}")

            # Comprehensive environment validation
            for directory in server.config.allowed_directories:
                dir_path = Path(directory)
                dir_issues: List[str] = []
                dir_warnings: List[str] = []
                dir_check = {
                    "exists": dir_path.exists(),
                    "is_directory": (dir_path.is_dir() if dir_path.exists() else False),
                    "readable": False,
                    "writable": False,
                    "zim_files_count": 0,
                    "zim_files_accessible": 0,
                    "total_size_mb": 0,
                    "issues": dir_issues,
                    "warnings": dir_warnings,
                }

                if dir_check["exists"] and dir_check["is_directory"]:
                    try:
                        # Test readability
                        list(dir_path.iterdir())
                        dir_check["readable"] = True

                        # Test writability (for cache/temp files)
                        # Use os.access for efficiency instead of creating temp files
                        if os.access(dir_path, os.W_OK):
                            dir_check["writable"] = True
                        else:
                            dir_check["writable"] = False
                            dir_warnings.append(
                                "Directory is not writable (may affect caching)"
                            )

                        # Comprehensive ZIM file analysis
                        zim_files = list(dir_path.glob("**/*.zim"))
                        dir_check["zim_files_count"] = len(zim_files)

                        total_size = 0
                        accessible_count: int = 0

                        for zim_file in zim_files:
                            try:
                                # Check file accessibility
                                if zim_file.is_file():
                                    accessible_count += 1
                                    # Get file size
                                    size = zim_file.stat().st_size
                                    total_size += size

                                    # Basic ZIM file integrity check
                                    try:
                                        with open(zim_file, "rb") as f:
                                            # Check for ZIM magic number
                                            magic = f.read(4)
                                            if magic != b"ZIM\x04":
                                                dir_warnings.append(
                                                    f"May not be a valid ZIM: "
                                                    f"{zim_file.name}"
                                                )
                                    except Exception:
                                        dir_warnings.append(
                                            f"Cannot read ZIM header: "
                                            f"{zim_file.name}"
                                        )
                                else:
                                    dir_issues.append(
                                        f"ZIM file path is not a file: {zim_file}"
                                    )

                            except OSError as e:
                                dir_issues.append(
                                    f"Cannot access ZIM file {zim_file.name}: {e}"
                                )

                        dir_check["zim_files_accessible"] = accessible_count
                        dir_check["total_size_mb"] = round(
                            total_size / (1024 * 1024), 2
                        )

                        # Check for common issues
                        if dir_check["zim_files_count"] == 0:
                            dir_warnings.append("No ZIM files found in directory")
                            recommendations_list.append(
                                f"Add ZIM files to directory: {directory}"
                            )
                        elif accessible_count < cast(int, dir_check["zim_files_count"]):
                            dir_issues.append(
                                f"Some ZIM files not accessible "
                                f"({accessible_count}/{dir_check['zim_files_count']})"
                            )
                            recommendations_list.append(
                                f"Check file permissions for ZIM files in: {directory}"
                            )

                        # Check disk space (basic)
                        try:
                            free_space = shutil.disk_usage(dir_path).free / (
                                1024 * 1024
                            )  # MB
                            if free_space < 100:  # Less than 100MB
                                dir_warnings.append(
                                    f"Low disk space: {free_space:.1f}MB available"
                                )
                                recommendations_list.append(
                                    "Consider freeing up disk space "
                                    "for optimal performance"
                                )
                        except Exception as e:
                            logger.debug(f"Could not check disk space: {e}")

                    except PermissionError:
                        dir_check["readable"] = False
                        dir_issues.append("Permission denied accessing directory")
                        issues_list.append(
                            f"Permission denied accessing directory: {directory}"
                        )
                        recommendations_list.append(
                            f"Check file permissions for directory: {directory}"
                        )
                    except Exception as e:
                        dir_issues.append(f"Error accessing directory: {e}")
                        issues_list.append(
                            f"Error accessing directory {directory}: {e}"
                        )
                else:
                    if not dir_check["exists"]:
                        dir_issues.append("Directory does not exist")
                        issues_list.append(f"Directory does not exist: {directory}")
                        recommendations_list.append(
                            f"Create or fix path to directory: {directory}"
                        )
                    elif not dir_check["is_directory"]:
                        dir_issues.append("Path is not a directory")
                        issues_list.append(f"Path is not a directory: {directory}")
                        recommendations_list.append(
                            f"Ensure path points to a directory: {directory}"
                        )

                # Add directory-specific issues to main diagnostics
                if dir_issues:
                    diagnostics["status"] = "error"
                elif dir_warnings and diagnostics["status"] == "healthy":
                    diagnostics["status"] = "warning"

                environment_checks[directory] = dir_check

            # Set overall status based on issues
            if issues_list:
                diagnostics["status"] = (
                    "error"
                    if any(
                        "does not exist" in issue or "Permission denied" in issue
                        for issue in issues_list
                    )
                    else "warning"
                )

            # Add general recommendations
            if not recommendations_list:
                recommendations_list.append(
                    "Server appears to be running normally. No issues detected."
                )

            return json.dumps(diagnostics, indent=2)

        except Exception as e:
            logger.error(f"Error in server diagnostics: {e}")
            return server._create_enhanced_error_message(
                operation="diagnose server state",
                error=e,
                context="Server diagnostics",
            )

    @server.mcp.tool()
    async def resolve_server_conflicts() -> str:
        """Identify and resolve server instance conflicts.

        This tool can identify stale instances, clean up orphaned instance
        files, and provide guidance for resolving conflicts between multiple
        server instances.

        Returns:
            JSON string containing conflict resolution results and actions taken
        """
        try:
            conflicts_found_list: List[Dict[str, Any]] = []
            actions_taken_list: List[str] = []
            recommendations_list: List[str] = []
            cleanup_results: Dict[str, Any] = {
                "stale_instances_removed": 0,
                "corrupted_files_removed": 0,
                "active_instances_found": 0,
            }
            resolution_results = {
                "timestamp": datetime.now().isoformat(),
                "conflicts_found": conflicts_found_list,
                "actions_taken": actions_taken_list,
                "cleanup_results": cleanup_results,
                "recommendations": recommendations_list,
                "status": "success",
            }

            if not server.instance_tracker:
                resolution_results["status"] = "error"
                recommendations_list.append(
                    "Instance tracker not available. Server may not be "
                    "properly configured for conflict detection."
                )
                return json.dumps(resolution_results, indent=2)

            # Step 1: Clean up stale instances
            try:
                cleaned_count = server.instance_tracker.cleanup_stale_instances()
                cleanup_results["stale_instances_removed"] = cleaned_count
                if cleaned_count > 0:
                    actions_taken_list.append(
                        f"Removed {cleaned_count} stale instance files"
                    )
                    logger.info(f"Cleaned up {cleaned_count} stale instance files")
            except Exception as e:
                recommendations_list.append(f"Failed to clean up stale instances: {e}")

            # Step 2: Detect current conflicts
            try:
                conflicts = server.instance_tracker.detect_conflicts(
                    server.config.get_config_hash()
                )
                conflicts_found_list.extend(conflicts)

                active_instances = server.instance_tracker.get_active_instances()
                cleanup_results["active_instances_found"] = len(active_instances)

                if conflicts:
                    resolution_results["status"] = "conflicts_detected"

                    for conflict in conflicts:
                        if conflict["type"] == "configuration_mismatch":
                            recommendations_list.append(
                                f"Configuration conflict with "
                                f"PID {conflict['instance']['pid']}: "
                                f"Stop the conflicting server or use same config."
                            )
                        elif conflict["type"] == "multiple_instances":
                            recommendations_list.append(
                                f"Multiple server detected "
                                f"(PID {conflict['instance']['pid']}): "
                                f"Consider stopping unused instances."
                            )
                else:
                    recommendations_list.append("No active conflicts detected.")

            except Exception as e:
                recommendations_list.append(f"Failed to detect conflicts: {e}")

            # Step 3: Provide specific resolution guidance
            if conflicts_found_list:
                recommendations_list.extend(
                    [
                        "",
                        "**Conflict Resolution Steps**:",
                        "1. Identify which server instance you want to keep running",
                        "2. Stop other servers using PID (kill <PID> on Unix/Mac)",
                        "3. Run this tool again to verify conflicts are resolved",
                        "4. Use 'diagnose_server_state()' for detailed server analysis",
                        "",
                        "**Prevention Tips**:",
                        "- Always stop previous servers before starting new ones",
                        "- Use consistent configuration across server instances",
                        "- Monitor server status with diagnostic tools",
                    ]
                )
            else:
                recommendations_list.extend(
                    [
                        "Server instance management is healthy.",
                        "TIP: Use 'diagnose_server_state()' for diagnostics.",
                    ]
                )

            return json.dumps(resolution_results, indent=2)

        except Exception as e:
            logger.error(f"Error in conflict resolution: {e}")
            return server._create_enhanced_error_message(
                operation="resolve server conflicts",
                error=e,
                context="Attempting to identify and resolve server instance conflicts",
            )
