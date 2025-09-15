"""
Main OpenZIM MCP server implementation.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, cast

from mcp.server.fastmcp import FastMCP

from .cache import OpenZimMcpCache
from .config import OpenZimMcpConfig
from .content_processor import ContentProcessor
from .exceptions import (
    OpenZimMcpArchiveError,
    OpenZimMcpFileNotFoundError,
    OpenZimMcpSecurityError,
    OpenZimMcpValidationError,
)
from .instance_tracker import InstanceTracker
from .security import PathValidator, sanitize_input
from .zim_operations import ZimOperations

logger = logging.getLogger(__name__)


class OpenZimMcpServer:
    """Main OpenZIM MCP server class with dependency injection."""

    def __init__(
        self, config: OpenZimMcpConfig, instance_tracker: Optional[InstanceTracker] = None
    ):
        """
        Initialize OpenZIM MCP server.

        Args:
            config: Server configuration
            instance_tracker: Optional instance tracker for multi-server management
        """
        self.config = config
        self.instance_tracker = instance_tracker

        # Setup logging
        config.setup_logging()
        logger.info(f"Initializing OpenZIM MCP server v{config.server_name}")

        # Initialize components
        self.path_validator = PathValidator(config.allowed_directories)
        self.cache = OpenZimMcpCache(config.cache)
        self.content_processor = ContentProcessor(config.content.snippet_length)
        self.zim_operations = ZimOperations(
            config, self.path_validator, self.cache, self.content_processor
        )

        # Initialize MCP server
        self.mcp = FastMCP(config.server_name)
        self._register_tools()

        logger.info("OpenZIM MCP server initialized successfully")

        # Minimal server startup logging - detailed config available via MCP tools
        logger.info(
            f"Server: {self.config.server_name}, "
            f"Directories: {len(self.config.allowed_directories)}, "
            f"Cache: {self.config.cache.enabled}"
        )
        logger.debug(
            "Use get_server_configuration() or diagnose_server_state() MCP tools "
            "for detailed configuration and diagnostics"
        )

    def _create_enhanced_error_message(
        self, operation: str, error: Exception, context: str = ""
    ) -> str:
        """
        Create educational, actionable error messages for LLM users.

        Args:
            operation: The operation that failed (e.g., "search", "get_entry")
            error: The exception that occurred
            context: Additional context (e.g., file path, query)

        Returns:
            Enhanced error message with troubleshooting guidance
        """
        error_type = type(error).__name__
        base_message = str(error)

        # Create context-aware error messages
        if isinstance(error, OpenZimMcpFileNotFoundError):
            return (
                f"❌ **File Not Found Error**\n\n"
                f"**Operation**: {operation}\n"
                f"**Issue**: The specified ZIM file could not be found.\n"
                f"**Context**: {context}\n\n"
                f"**Troubleshooting Steps**:\n"
                f"1. Verify the file path is correct\n"
                f"2. Check that the file exists in one of the allowed directories\n"
                f"3. Use `list_zim_files()` to see available ZIM files\n"
                f"4. Ensure you have read permissions for the file\n\n"
                f"**Technical Details**: {base_message}"
            )
        elif isinstance(error, OpenZimMcpArchiveError):
            return (
                f"❌ **Archive Operation Error**\n\n"
                f"**Operation**: {operation}\n"
                f"**Issue**: The ZIM archive operation failed.\n"
                f"**Context**: {context}\n\n"
                f"**Troubleshooting Steps**:\n"
                f"1. Verify the ZIM file is not corrupted\n"
                f"2. Check if the file is currently being written to\n"
                f"3. Ensure sufficient system resources (memory/disk space)\n"
                f"4. Try with a different ZIM file to isolate the issue\n"
                f"5. Use `diagnose_server_state()` to check for server conflicts\n\n"
                f"**Technical Details**: {base_message}"
            )
        elif isinstance(error, OpenZimMcpSecurityError):
            return (
                f"🔒 **Security Validation Error**\n\n"
                f"**Operation**: {operation}\n"
                f"**Issue**: The request was blocked for security reasons.\n"
                f"**Context**: {context}\n\n"
                f"**Troubleshooting Steps**:\n"
                f"1. Ensure the file path is within allowed directories\n"
                f"2. Check for path traversal attempts (../ sequences)\n"
                f"3. Verify the file path doesn't contain suspicious characters\n"
                f"4. Use `get_server_configuration()` to see allowed directories\n\n"
                f"**Technical Details**: {base_message}"
            )
        elif isinstance(error, OpenZimMcpValidationError):
            return (
                f"⚠️ **Input Validation Error**\n\n"
                f"**Operation**: {operation}\n"
                f"**Issue**: The provided input parameters are invalid.\n"
                f"**Context**: {context}\n\n"
                f"**Troubleshooting Steps**:\n"
                f"1. Check parameter formats and ranges\n"
                f"2. Ensure required parameters are provided\n"
                f"3. Verify string lengths are within limits\n"
                f"4. Check for special characters that might need escaping\n\n"
                f"**Technical Details**: {base_message}"
            )
        elif "permission" in base_message.lower() or "access" in base_message.lower():
            return (
                f"🔐 **Permission Error**\n\n"
                f"**Operation**: {operation}\n"
                f"**Issue**: Insufficient permissions to access the resource.\n"
                f"**Context**: {context}\n\n"
                f"**Troubleshooting Steps**:\n"
                f"1. Check file and directory permissions\n"
                f"2. Ensure the server process has read access\n"
                f"3. Verify the file is not locked by another process\n"
                f"4. Try running with appropriate permissions\n"
                f"5. Use `diagnose_server_state()` for environment validation\n\n"
                f"**Technical Details**: {base_message}"
            )
        elif (
            "not found" in base_message.lower()
            or "does not exist" in base_message.lower()
        ):
            return (
                f"📁 **Resource Not Found**\n\n"
                f"**Operation**: {operation}\n"
                f"**Issue**: The requested resource could not be located.\n"
                f"**Context**: {context}\n\n"
                f"**Troubleshooting Steps**:\n"
                f"1. Double-check the spelling and path\n"
                f"2. Use browsing tools to explore available content\n"
                f"3. Check if the resource exists in a different namespace\n"
                f"4. Verify the ZIM file contains the expected content\n"
                f"5. Try using search tools to locate similar content\n\n"
                f"**Technical Details**: {base_message}"
            )
        else:
            # Generic enhanced error message
            return (
                f"❌ **Operation Failed**\n\n"
                f"**Operation**: {operation}\n"
                f"**Error Type**: {error_type}\n"
                f"**Context**: {context}\n\n"
                f"**Troubleshooting Steps**:\n"
                f"1. Try the operation again (temporary issues may resolve)\n"
                f"2. Use `diagnose_server_state()` to check for server issues\n"
                f"3. Verify your input parameters are correct\n"
                f"4. Check if other operations work with the same file\n"
                f"5. Consider using alternative tools or approaches\n\n"
                f"**Technical Details**: {base_message}\n\n"
                f"**Need Help?** Use `get_server_configuration()` to check server "
                f"status or try simpler operations first."
            )

    def _register_tools(self) -> None:
        """Register MCP tools."""

        @self.mcp.tool()
        async def list_zim_files() -> str:
            """List all ZIM files in allowed directories.

            Includes automatic conflict detection and warnings if multiple
            server instances are detected.

            Returns:
                JSON string containing the list of ZIM files and any warnings
            """
            try:
                # Get the basic ZIM files list
                zim_files_result = self.zim_operations.list_zim_files()

                # Check for conflicts if instance tracker is available
                warnings = []
                if self.instance_tracker:
                    try:
                        conflicts = self.instance_tracker.detect_conflicts(
                            self.config.get_config_hash()
                        )
                        if conflicts:
                            for conflict in conflicts:
                                if conflict["type"] == "configuration_mismatch":
                                    warnings.append(
                                        {
                                            "type": "configuration_conflict",
                                            "message": (
                                                "⚠️  Configuration mismatch detected "
                                                f"with server PID {conflict['instance']['pid']}"
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
                                                "⚠️  Multiple server instances detected "
                                                f"(PID {conflict['instance']['pid']})"
                                            ),
                                            "resolution": (
                                                "Multiple servers may cause confusion. "
                                                "Use 'diagnose_server_state()' for detailed "
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
                    warning_text = "\n🔍 SERVER DIAGNOSTICS:\n"
                    for warning in warnings:
                        warning_text += f"\n{warning['message']}\n"
                        warning_text += f"Resolution: {warning['resolution']}\n"

                    warning_text += "\n📋 ZIM FILES:\n"
                    return warning_text + zim_files_result
                else:
                    return zim_files_result

            except Exception as e:
                logger.error(f"Error listing ZIM files: {e}")
                return self._create_enhanced_error_message(
                    operation="list ZIM files",
                    error=e,
                    context="Scanning allowed directories for ZIM files",
                )

        @self.mcp.tool()
        async def search_zim_file(
            zim_file_path: str,
            query: str,
            limit: Optional[int] = None,
            offset: int = 0,
        ) -> str:
            """Search within ZIM file content.

            Args:
                zim_file_path: Path to the ZIM file
                query: Search query term
                limit: Maximum number of results to return (default from config)
                offset: Result starting offset (for pagination)

            Returns:
                Search result text
            """
            try:
                # Sanitize inputs
                zim_file_path = sanitize_input(zim_file_path, 1000)
                query = sanitize_input(query, 500)

                # Validate parameters
                if limit is not None and (limit < 1 or limit > 100):
                    return (
                        "⚠️ **Parameter Validation Error**\n\n"
                        f"**Issue**: Search limit must be between 1 and 100 "
                        f"(provided: {limit})\n\n"
                        "**Troubleshooting**: Adjust the limit parameter to be "
                        "within the valid range.\n"
                        "**Example**: Use `limit=10` for 10 results or "
                        "`limit=50` for more results."
                    )

                if offset < 0:
                    return (
                        "⚠️ **Parameter Validation Error**\n\n"
                        f"**Issue**: Offset must be non-negative (provided: {offset})\n\n"
                        "**Troubleshooting**: Use `offset=0` to start from the "
                        "beginning, or a positive number to skip results.\n"
                        "**Example**: Use `offset=0` for first page, "
                        "`offset=10` for second page with limit=10."
                    )

                # Perform the search
                search_result = self.zim_operations.search_zim_file(
                    zim_file_path, query, limit, offset
                )

                # Add proactive conflict detection for search operations
                if self.instance_tracker:
                    try:
                        conflicts = self.instance_tracker.detect_conflicts(
                            self.config.get_config_hash()
                        )
                        if conflicts:
                            conflict_warning = "\n\n🔍 **Server Conflict Detected**\n"
                            for conflict in conflicts:
                                if conflict["type"] == "configuration_mismatch":
                                    conflict_warning += (
                                        f"⚠️ Configuration mismatch with server PID {conflict['instance']['pid']}. "
                                        "Search results may be inconsistent.\n"
                                    )
                                elif conflict["type"] == "multiple_instances":
                                    conflict_warning += (
                                        f"⚠️ Multiple servers detected (PID {conflict['instance']['pid']}). "
                                        "Results may come from different server instances.\n"
                                    )
                            conflict_warning += "\n💡 Use 'resolve_server_conflicts()' to fix these issues.\n"
                            return search_result + conflict_warning
                    except Exception:
                        # Don't fail the search if conflict detection fails
                        pass

                return search_result

            except Exception as e:
                logger.error(f"Error searching ZIM file: {e}")
                return self._create_enhanced_error_message(
                    operation="search ZIM file",
                    error=e,
                    context=f"File: {zim_file_path}, Query: '{query}'",
                )

        @self.mcp.tool()
        async def get_zim_entry(
            zim_file_path: str,
            entry_path: str,
            max_content_length: Optional[int] = None,
        ) -> str:
            """Get detailed content of a specific entry in a ZIM file.

            Args:
                zim_file_path: Path to the ZIM file
                entry_path: Entry path, e.g., 'A/Some_Article'
                max_content_length: Maximum length of content to return

            Returns:
                Entry content text
            """
            try:
                # Sanitize inputs
                zim_file_path = sanitize_input(zim_file_path, 1000)
                entry_path = sanitize_input(entry_path, 500)

                # Validate parameters
                if max_content_length is not None and max_content_length < 1000:
                    return (
                        "⚠️ **Parameter Validation Error**\n\n"
                        f"**Issue**: max_content_length must be at least 1000 characters (provided: {max_content_length})\n\n"
                        "**Troubleshooting**: Increase the max_content_length parameter or omit it to use the default.\n"
                        "**Example**: Use `max_content_length=5000` for longer content or omit the parameter for "
                        "default length."
                    )

                return self.zim_operations.get_zim_entry(
                    zim_file_path, entry_path, max_content_length
                )

            except Exception as e:
                logger.error(f"Error getting ZIM entry: {e}")
                return self._create_enhanced_error_message(
                    operation="get ZIM entry",
                    error=e,
                    context=f"File: {zim_file_path}, Entry: {entry_path}",
                )

        @self.mcp.tool()
        async def get_server_health() -> str:
            """Get comprehensive server health and statistics.

            Includes instance tracking status, conflict detection, cache performance,
            and recommendations for maintaining server health.

            Returns:
                JSON string containing detailed server health information
            """
            try:
                import json
                import os
                from datetime import datetime
                from pathlib import Path

                cache_stats = self.cache.stats()
                recommendations: List[str] = []
                warnings: List[str] = []
                instance_tracking: Dict[str, Any] = {
                    "enabled": self.instance_tracker is not None,
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
                    "server_name": self.config.server_name,
                    "uptime_info": {
                        "process_id": os.getpid(),
                        "started_at": getattr(self, "_start_time", "unknown"),
                    },
                    "configuration": {
                        "allowed_directories": len(self.config.allowed_directories),
                        "cache_enabled": self.config.cache.enabled,
                        "config_hash": self.config.get_config_hash()[:8]
                        + "...",  # Short hash for display
                    },
                    "cache_performance": cache_stats,
                    "instance_tracking": instance_tracking,
                    "health_checks": health_checks,
                    "recommendations": recommendations,
                    "warnings": warnings,
                }

                # Instance tracking health
                if self.instance_tracker:
                    try:
                        active_instances = self.instance_tracker.get_active_instances()
                        instance_tracking["active_instances"] = len(active_instances)

                        conflicts = self.instance_tracker.detect_conflicts(
                            self.config.get_config_hash()
                        )
                        instance_tracking["conflicts_detected"] = len(conflicts)

                        if conflicts:
                            health_info["status"] = "warning"
                            warnings.append(
                                f"Server conflicts detected ({len(conflicts)} instances)"
                            )
                            recommendations.append(
                                "Use 'resolve_server_conflicts()' to address instance conflicts"
                            )

                        # Check for stale instances
                        try:
                            stale_count = len(
                                [
                                    inst
                                    for inst in active_instances
                                    if not self.instance_tracker._is_process_running(
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
                                    "Use 'resolve_server_conflicts()' to clean up stale instances"
                                )
                        except Exception:
                            pass

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

                for directory in self.config.allowed_directories:
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
                        recommendations.append(
                            f"Check file permissions for: {directory}"
                        )
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
                    if hit_rate < 0.3:  # Less than 30% hit rate
                        recommendations.append(
                            "Cache hit rate is low - consider warming up cache with common queries"
                        )
                    elif hit_rate > 0.8:  # Greater than 80% hit rate
                        recommendations.append("Cache is performing well")
                else:
                    recommendations.append(
                        "Consider enabling cache for better performance"
                    )

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
                return self._create_enhanced_error_message(
                    operation="get server health",
                    error=e,
                    context="Checking server health and performance metrics",
                )

        @self.mcp.tool()
        async def get_server_configuration() -> str:
            """Get detailed server configuration with diagnostics and validation.

            Returns:
                Server configuration information including conflict detection,
                validation results, and recommendations
            """
            try:
                import json

                # Basic configuration info
                config_info = {
                    "server_name": self.config.server_name,
                    "allowed_directories": self.config.allowed_directories,
                    "cache_enabled": self.config.cache.enabled,
                    "cache_max_size": self.config.cache.max_size,
                    "cache_ttl_seconds": self.config.cache.ttl_seconds,
                    "content_max_length": self.config.content.max_content_length,
                    "content_snippet_length": self.config.content.snippet_length,
                    "search_default_limit": self.config.content.default_search_limit,
                    "config_hash": self.config.get_config_hash(),
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
                if self.instance_tracker:
                    try:
                        conflicts = self.instance_tracker.detect_conflicts(
                            self.config.get_config_hash()
                        )
                        if conflicts:
                            conflicts_detected_list.extend(conflicts)
                            diagnostics["validation_status"] = "warning"
                            warnings_list.append(
                                f"Found {len(conflicts)} potential server conflicts"
                            )
                            recommendations_list.append(
                                "Multiple server instances detected. Consider using diagnose_server_state() for "
                                "detailed analysis."
                            )
                    except Exception as e:
                        warnings_list.append(f"Could not check for conflicts: {e}")

                # Basic directory validation
                invalid_dirs = []
                for directory in self.config.allowed_directories:
                    from pathlib import Path

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
                return f"Error: Failed to get configuration: {e}"

        @self.mcp.tool()
        async def diagnose_server_state() -> str:
            """Comprehensive server diagnostics accessible to LLM users.

            Checks for multiple instances, validates configuration, checks file
            accessibility, and returns actionable recommendations.

            Returns:
                JSON string containing diagnostic results and recommendations
            """
            try:
                import json
                from pathlib import Path

                conflicts_list: List[Dict[str, Any]] = []
                issues_list: List[str] = []
                recommendations_list: List[str] = []
                environment_checks: Dict[str, Any] = {}
                diagnostics = {
                    "status": "healthy",
                    "timestamp": datetime.now().isoformat(),
                    "server_info": {
                        "pid": os.getpid(),
                        "server_name": self.config.server_name,
                        "config_hash": self.config.get_config_hash(),
                    },
                    "configuration": {
                        "allowed_directories": self.config.allowed_directories,
                        "cache_enabled": self.config.cache.enabled,
                        "cache_max_size": self.config.cache.max_size,
                    },
                    "conflicts": conflicts_list,
                    "issues": issues_list,
                    "recommendations": recommendations_list,
                    "environment_checks": environment_checks,
                }

                # Check for instance conflicts if tracker is available
                if self.instance_tracker:
                    try:
                        conflicts = self.instance_tracker.detect_conflicts(
                            self.config.get_config_hash()
                        )
                        conflicts_list.extend(conflicts)

                        if conflicts:
                            diagnostics["status"] = "warning"
                            for conflict in conflicts:
                                if conflict["type"] == "configuration_mismatch":
                                    recommendations_list.append(
                                        "Configuration mismatch detected with another server instance. "
                                        "Consider stopping other instances or ensuring they use the same configuration."
                                    )
                                elif conflict["type"] == "multiple_instances":
                                    recommendations_list.append(
                                        f"Multiple server instances detected (PID: {conflict['instance']['pid']}). "
                                        "This may cause unexpected behavior. Consider stopping unused instances."
                                    )
                    except Exception as e:
                        issues_list.append(f"Failed to check for conflicts: {e}")

                # Comprehensive environment validation
                for directory in self.config.allowed_directories:
                    dir_path = Path(directory)
                    dir_issues: List[str] = []
                    dir_warnings: List[str] = []
                    dir_check = {
                        "exists": dir_path.exists(),
                        "is_directory": (
                            dir_path.is_dir() if dir_path.exists() else False
                        ),
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
                            try:
                                test_file = dir_path / ".openzim_mcp_write_test"
                                test_file.touch()
                                test_file.unlink()
                                dir_check["writable"] = True
                            except (PermissionError, OSError):
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
                                                        f"File may not be a valid ZIM file: {zim_file.name}"
                                                    )
                                        except Exception:
                                            dir_warnings.append(
                                                f"Cannot read ZIM file header: {zim_file.name}"
                                            )
                                    else:
                                        dir_issues.append(
                                            f"ZIM file path is not a file: {zim_file}"
                                        )

                                except (PermissionError, OSError) as e:
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
                            elif accessible_count < cast(
                                int, dir_check["zim_files_count"]
                            ):
                                dir_issues.append(
                                    f"Some ZIM files are not accessible ({accessible_count}/{dir_check['zim_files_count']})"
                                )
                                recommendations_list.append(
                                    f"Check file permissions for ZIM files in: {directory}"
                                )

                            # Check disk space (basic)
                            try:
                                import shutil

                                free_space = shutil.disk_usage(dir_path).free / (
                                    1024 * 1024
                                )  # MB
                                if free_space < 100:  # Less than 100MB
                                    dir_warnings.append(
                                        f"Low disk space: {free_space:.1f}MB available"
                                    )
                                    recommendations_list.append(
                                        "Consider freeing up disk space for optimal performance"
                                    )
                            except Exception:
                                pass

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
                    elif dir_warnings:
                        if diagnostics["status"] == "healthy":
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
                return f"Error: Failed to run diagnostics: {e}"

        @self.mcp.tool()
        async def resolve_server_conflicts() -> str:
            """Identify and resolve server instance conflicts.

            This tool can identify stale instances, clean up orphaned instance
            files, and provide guidance for resolving conflicts between multiple
            server instances.

            Returns:
                JSON string containing conflict resolution results and actions taken
            """
            try:
                import json

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

                if not self.instance_tracker:
                    resolution_results["status"] = "error"
                    recommendations_list.append(
                        "Instance tracker not available. Server may not be properly configured for conflict detection."
                    )
                    return json.dumps(resolution_results, indent=2)

                # Step 1: Clean up stale instances
                try:
                    cleaned_count = self.instance_tracker.cleanup_stale_instances()
                    cleanup_results["stale_instances_removed"] = cleaned_count
                    if cleaned_count > 0:
                        actions_taken_list.append(
                            f"Removed {cleaned_count} stale instance files"
                        )
                        logger.info(f"Cleaned up {cleaned_count} stale instance files")
                except Exception as e:
                    recommendations_list.append(
                        f"Failed to clean up stale instances: {e}"
                    )

                # Step 2: Detect current conflicts
                try:
                    conflicts = self.instance_tracker.detect_conflicts(
                        self.config.get_config_hash()
                    )
                    conflicts_found_list.extend(conflicts)

                    active_instances = self.instance_tracker.get_active_instances()
                    cleanup_results["active_instances_found"] = len(active_instances)

                    if conflicts:
                        resolution_results["status"] = "conflicts_detected"

                        for conflict in conflicts:
                            if conflict["type"] == "configuration_mismatch":
                                recommendations_list.append(
                                    f"Configuration conflict with PID {conflict['instance']['pid']}: "
                                    "Stop the conflicting server or ensure both use the same configuration."
                                )
                            elif conflict["type"] == "multiple_instances":
                                recommendations_list.append(
                                    f"Multiple server detected (PID {conflict['instance']['pid']}): "
                                    "Consider stopping unused instances to avoid confusion."
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
                            "🔧 **Conflict Resolution Steps**:",
                            "1. Identify which server instance you want to keep running",
                            "2. Stop other server processes using their PID (kill <PID> on Unix/Mac)",
                            "3. Run this tool again to verify conflicts are resolved",
                            "4. Use 'diagnose_server_state()' for detailed server analysis",
                            "",
                            "💡 **Prevention Tips**:",
                            "- Always stop previous servers before starting new ones",
                            "- Use consistent configuration across server instances",
                            "- Monitor server status with diagnostic tools",
                        ]
                    )
                else:
                    recommendations_list.extend(
                        [
                            "✅ Server instance management is healthy.",
                            "💡 Use 'diagnose_server_state()' for comprehensive server diagnostics.",
                        ]
                    )

                return json.dumps(resolution_results, indent=2)

            except Exception as e:
                logger.error(f"Error in conflict resolution: {e}")
                return self._create_enhanced_error_message(
                    operation="resolve server conflicts",
                    error=e,
                    context="Attempting to identify and resolve server instance conflicts",
                )

        @self.mcp.tool()
        async def get_zim_metadata(zim_file_path: str) -> str:
            """Get ZIM file metadata from M namespace entries.

            Args:
                zim_file_path: Path to the ZIM file

            Returns:
                JSON string containing ZIM metadata
            """
            try:
                # Sanitize inputs
                zim_file_path = sanitize_input(zim_file_path, 1000)

                return self.zim_operations.get_zim_metadata(zim_file_path)

            except Exception as e:
                logger.error(f"Error getting ZIM metadata: {e}")
                return self._create_enhanced_error_message(
                    operation="get ZIM metadata",
                    error=e,
                    context=f"File: {zim_file_path}",
                )

        @self.mcp.tool()
        async def get_main_page(zim_file_path: str) -> str:
            """Get the main page entry from W namespace.

            Args:
                zim_file_path: Path to the ZIM file

            Returns:
                Main page content or information about main page
            """
            try:
                # Sanitize inputs
                zim_file_path = sanitize_input(zim_file_path, 1000)

                return self.zim_operations.get_main_page(zim_file_path)

            except Exception as e:
                logger.error(f"Error getting main page: {e}")
                return f"Error: Failed to get main page: {e}"

        @self.mcp.tool()
        async def list_namespaces(zim_file_path: str) -> str:
            """List available namespaces and their entry counts.

            Args:
                zim_file_path: Path to the ZIM file

            Returns:
                JSON string containing namespace information
            """
            try:
                # Sanitize inputs
                zim_file_path = sanitize_input(zim_file_path, 1000)

                return self.zim_operations.list_namespaces(zim_file_path)

            except Exception as e:
                logger.error(f"Error listing namespaces: {e}")
                return f"Error: Failed to list namespaces: {e}"

        @self.mcp.tool()
        async def browse_namespace(
            zim_file_path: str,
            namespace: str,
            limit: int = 50,
            offset: int = 0,
        ) -> str:
            """Browse entries in a specific namespace with pagination.

            Args:
                zim_file_path: Path to the ZIM file
                namespace: Namespace to browse (C, M, W, X, A, I, etc. for old format; domain names for new format)
                limit: Maximum number of entries to return (1-200, default: 50)
                offset: Starting offset for pagination (default: 0)

            Returns:
                JSON string containing namespace entries
            """
            try:
                # Sanitize inputs
                zim_file_path = sanitize_input(zim_file_path, 1000)
                namespace = sanitize_input(namespace, 100)  # Increased to support new namespace scheme

                # Validate parameters
                if limit < 1 or limit > 200:
                    return "Error: limit must be between 1 and 200"
                if offset < 0:
                    return "Error: offset must be non-negative"

                return self.zim_operations.browse_namespace(
                    zim_file_path, namespace, limit, offset
                )

            except Exception as e:
                logger.error(f"Error browsing namespace: {e}")
                return self._create_enhanced_error_message(
                    operation="browse namespace",
                    error=e,
                    context=f"File: {zim_file_path}, Namespace: {namespace}, Limit: {limit}, Offset: {offset}",
                )

        @self.mcp.tool()
        async def search_with_filters(
            zim_file_path: str,
            query: str,
            namespace: Optional[str] = None,
            content_type: Optional[str] = None,
            limit: Optional[int] = None,
            offset: int = 0,
        ) -> str:
            """Search within ZIM file content with namespace and content type filters.

            Args:
                zim_file_path: Path to the ZIM file
                query: Search query term
                namespace: Optional namespace filter (C, M, W, X, etc.)
                content_type: Optional content type filter (text/html, text/plain, etc.)
                limit: Maximum number of results to return (default from config)
                offset: Result starting offset (for pagination)

            Returns:
                Search result text
            """
            try:
                # Sanitize inputs
                zim_file_path = sanitize_input(zim_file_path, 1000)
                query = sanitize_input(query, 500)
                if namespace:
                    namespace = sanitize_input(namespace, 100)  # Increased to support new namespace scheme
                if content_type:
                    content_type = sanitize_input(content_type, 100)

                # Validate parameters
                if limit is not None and (limit < 1 or limit > 100):
                    return "Error: limit must be between 1 and 100"
                if offset < 0:
                    return "Error: offset must be non-negative"

                # Perform the filtered search
                search_result = self.zim_operations.search_with_filters(
                    zim_file_path, query, namespace, content_type, limit, offset
                )

                # Add proactive conflict detection for filtered search operations
                if self.instance_tracker:
                    try:
                        conflicts = self.instance_tracker.detect_conflicts(
                            self.config.get_config_hash()
                        )
                        if conflicts:
                            conflict_warning = "\n\n🔍 **Server Conflict Detected**\n"
                            for conflict in conflicts:
                                if conflict["type"] == "configuration_mismatch":
                                    conflict_warning += (
                                        f"⚠️ Configuration mismatch with server PID {conflict['instance']['pid']}. "
                                        "Filtered search results may be inconsistent.\n"
                                    )
                                elif conflict["type"] == "multiple_instances":
                                    conflict_warning += (
                                        f"⚠️ Multiple servers detected (PID {conflict['instance']['pid']}). "
                                        "Results may come from different server instances.\n"
                                    )
                            conflict_warning += "\n💡 Use 'resolve_server_conflicts()' to fix these issues.\n"
                            return search_result + conflict_warning
                    except Exception:
                        # Don't fail the search if conflict detection fails
                        pass

                return search_result

            except Exception as e:
                logger.error(f"Error in filtered search: {e}")
                return f"Error: Failed to perform filtered search: {e}"

        @self.mcp.tool()
        async def get_search_suggestions(
            zim_file_path: str, partial_query: str, limit: int = 10
        ) -> str:
            """Get search suggestions and auto-complete for partial queries.

            Args:
                zim_file_path: Path to the ZIM file
                partial_query: Partial search query
                limit: Maximum number of suggestions to return (1-50, default: 10)

            Returns:
                JSON string containing search suggestions
            """
            try:
                # Sanitize inputs
                zim_file_path = sanitize_input(zim_file_path, 1000)
                partial_query = sanitize_input(partial_query, 200)

                # Validate parameters
                if limit < 1 or limit > 50:
                    return "Error: limit must be between 1 and 50"

                return self.zim_operations.get_search_suggestions(
                    zim_file_path, partial_query, limit
                )

            except Exception as e:
                logger.error(f"Error getting search suggestions: {e}")
                return f"Error: Failed to get search suggestions: {e}"

        @self.mcp.tool()
        async def get_article_structure(zim_file_path: str, entry_path: str) -> str:
            """Extract article structure including headings, sections, and key metadata.

            Args:
                zim_file_path: Path to the ZIM file
                entry_path: Entry path, e.g., 'C/Some_Article'

            Returns:
                JSON string containing article structure
            """
            try:
                # Sanitize inputs
                zim_file_path = sanitize_input(zim_file_path, 1000)
                entry_path = sanitize_input(entry_path, 500)

                return self.zim_operations.get_article_structure(
                    zim_file_path, entry_path
                )

            except Exception as e:
                logger.error(f"Error getting article structure: {e}")
                return f"Error: Failed to get article structure: {e}"

        @self.mcp.tool()
        async def extract_article_links(zim_file_path: str, entry_path: str) -> str:
            """Extract internal and external links from an article.

            Args:
                zim_file_path: Path to the ZIM file
                entry_path: Entry path, e.g., 'C/Some_Article'

            Returns:
                JSON string containing extracted links
            """
            try:
                # Sanitize inputs
                zim_file_path = sanitize_input(zim_file_path, 1000)
                entry_path = sanitize_input(entry_path, 500)

                return self.zim_operations.extract_article_links(
                    zim_file_path, entry_path
                )

            except Exception as e:
                logger.error(f"Error extracting article links: {e}")
                return f"Error: Failed to extract article links: {e}"

        logger.info("MCP tools registered successfully")

    def run(
        self, transport: Literal["stdio", "sse", "streamable-http"] = "stdio"
    ) -> None:
        """
        Run the OpenZIM MCP server.

        Args:
            transport: Transport protocol to use
        """
        logger.info(f"Starting OpenZIM MCP server with transport: {transport}")
        try:
            self.mcp.run(transport=transport)
        except KeyboardInterrupt:
            logger.info("Server shutdown requested")
        except Exception as e:
            logger.error(f"Server error: {e}")
            raise
        finally:
            logger.info("OpenZIM MCP server stopped")
