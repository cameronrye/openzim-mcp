"""Server health and diagnostics tools for OpenZIM MCP server."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Tuple

from ..constants import CACHE_HIGH_HIT_RATE_THRESHOLD, CACHE_LOW_HIT_RATE_THRESHOLD
from ..security import redact_paths_in_message, sanitize_path_for_error

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string with offset.

    All server-tools timestamps go through this helper so a single response
    never mixes timezone-aware (``+00:00``) and naive local strings.
    """
    return datetime.now(timezone.utc).isoformat()


def register_server_tools(server: "OpenZimMcpServer") -> None:
    """Register server health and diagnostics tools."""
    _register_get_server_health(server)
    _register_get_server_configuration(server)


def _register_get_server_health(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def get_server_health() -> str:
        """Get comprehensive server health and statistics.

        Includes cache performance, directory health, and recommendations.

        Returns:
            JSON string containing detailed server health information
        """
        return await asyncio.to_thread(_build_health_report, server)


def _register_get_server_configuration(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def get_server_configuration() -> str:
        """Get detailed server configuration with diagnostics and validation.

        Returns:
            Server configuration information including validation results
            and recommendations
        """
        return await asyncio.to_thread(_build_configuration_report, server)


def _check_directory_health(
    directory: str,
    health_info: Dict[str, Any],
    health_checks: Dict[str, Any],
    warnings: List[str],
    recommendations: List[str],
) -> Tuple[int, int]:
    """Probe one allowed directory and return (accessible, zim_count).

    Mutates ``health_info``/``health_checks``/``warnings``/``recommendations``
    in place so the caller can accumulate aggregate state across directories.
    """
    # Sanitize the path before it ever lands in user-visible warning /
    # recommendation strings — diagnostic output is frequently copy-pasted
    # into bug reports and must not leak host topology.
    redacted = sanitize_path_for_error(str(directory))
    try:
        dir_path = Path(directory)
        if dir_path.exists() and dir_path.is_dir():
            list(dir_path.iterdir())
            zim_files = list(dir_path.glob("**/*.zim"))
            return 1, len(zim_files)
        warnings.append(f"Directory not accessible: {redacted}")
        recommendations.append(f"Check directory path and permissions: {redacted}")
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
            f"Error accessing {redacted}: {redact_paths_in_message(str(e))}"
        )
        if health_info["status"] == "healthy":
            health_info["status"] = "warning"
    return 0, 0


def _append_cache_recommendations(
    cache_stats: Dict[str, Any], recommendations: List[str]
) -> None:
    """Translate cache hit-rate stats into human-readable recommendations.

    Skip the "low" warning until the cache has seen a meaningful sample
    (>= ``_CACHE_RECOMMENDATION_MIN_SAMPLES`` total accesses). A fresh
    session legitimately has a low hit rate while it warms up; warning
    on the first query was misleading and got beta-tester complaints.
    """
    if cache_stats.get("enabled", False):
        hit_rate = cache_stats.get("hit_rate", 0)
        total_accesses = cache_stats.get("hits", 0) + cache_stats.get("misses", 0)
        if total_accesses < _CACHE_RECOMMENDATION_MIN_SAMPLES:
            return  # Not enough signal yet — silence is more useful than noise.
        if hit_rate < CACHE_LOW_HIT_RATE_THRESHOLD:
            recommendations.append(
                "Cache hit rate is low — consider issuing repeated "
                "queries against the same ZIM files"
            )
        elif hit_rate > CACHE_HIGH_HIT_RATE_THRESHOLD:
            recommendations.append("Cache is performing well")
    else:
        recommendations.append("Consider enabling cache for better performance")


# Minimum cache accesses before we report on hit-rate trends. Below this we
# treat the rate as too noisy to comment on. 50 is enough that a steady-state
# pattern has emerged; below that, warming-up effects dominate.
_CACHE_RECOMMENDATION_MIN_SAMPLES = 50


def _finalize_health_status(
    health_info: Dict[str, Any],
    accessible_dirs: int,
    total_zim_files: int,
    warnings: List[str],
    recommendations: List[str],
) -> None:
    """Roll up accumulated checks into the final ``status`` field."""
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


def _redact_directory_path(path: str) -> str:
    """Render a directory path for the configuration response.

    Returns ``<redacted>/<basename>`` so it's unambiguous that the leading
    components were intentionally hidden. The basename stays so operators
    can still tell which configured directory each entry corresponds to.
    """
    if not path:
        return "<redacted>"
    parts = path.replace("\\", "/").split("/")
    basename = parts[-1] if parts[-1] else (parts[-2] if len(parts) > 1 else "")
    if not basename:
        return "<redacted>"
    return f"<redacted>/{basename}"


def _build_uptime_info(server: "OpenZimMcpServer") -> Dict[str, Any]:
    """Return uptime block for the health report.

    ``started_at`` and ``uptime_seconds`` are filled in from the server's
    init-time anchors when present; falls back to ``"unknown"`` /
    ``None`` for legacy paths that didn't record them.
    """
    import time as _time

    start_iso = getattr(server, "_start_time", None) or "unknown"
    start_mono = getattr(server, "_start_monotonic", None)
    uptime_seconds: Any = None
    if start_mono is not None:
        uptime_seconds = round(_time.monotonic() - start_mono, 3)
    return {
        # Redact PID — diagnostic output may end up in bug reports.
        "process_id": "[REDACTED]",
        "started_at": start_iso,
        "uptime_seconds": uptime_seconds,
    }


def _build_health_report(server: "OpenZimMcpServer") -> str:
    try:
        cache_stats = server.cache.stats()
        recommendations: List[str] = []
        warnings: List[str] = []
        health_checks: Dict[str, Any] = {
            "directories_accessible": 0,
            "zim_files_found": 0,
            "permissions_ok": True,
        }
        health_info: Dict[str, Any] = {
            "timestamp": _utc_now_iso(),
            "status": "healthy",
            "server_name": server.config.server_name,
            "uptime_info": _build_uptime_info(server),
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

        accessible_dirs = 0
        total_zim_files = 0
        for directory in server.config.allowed_directories:
            ok, zim_count = _check_directory_health(
                directory, health_info, health_checks, warnings, recommendations
            )
            accessible_dirs += ok
            total_zim_files += zim_count

        health_checks["directories_accessible"] = accessible_dirs
        health_checks["zim_files_found"] = total_zim_files

        _append_cache_recommendations(cache_stats, recommendations)
        _finalize_health_status(
            health_info, accessible_dirs, total_zim_files, warnings, recommendations
        )

        return json.dumps(health_info, indent=2)

    except Exception as e:
        logger.error(f"Error getting server health: {e}")
        return server._create_enhanced_error_message(
            operation="get server health",
            error=e,
            context="Checking server health and performance metrics",
        )


def _build_configuration_report(server: "OpenZimMcpServer") -> str:
    try:
        # Always redact paths and PID — even on stdio, diagnostic output
        # frequently ends up in bug reports / logs / issue trackers, so
        # leaking host topology is an info-disclosure risk regardless of
        # transport. The unredacted values remain available to operators
        # in server logs.
        #
        # The basename-only format (``<redacted>/<basename>``) is
        # unambiguous: a leading ``...`` was reading like a malformed path
        # in beta testing while ``list_zim_files`` exposes the real paths
        # for tool-input use. Making the redaction explicit closes that gap.
        config_info = {
            "server_name": server.config.server_name,
            "allowed_directories": [
                _redact_directory_path(str(p))
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

        # Match the redaction format used for ``allowed_directories`` so
        # callers comparing the two lists don't see a different convention.
        invalid_dirs = [
            _redact_directory_path(str(d))
            for d in server.config.allowed_directories
            if not Path(d).exists()
        ]
        if invalid_dirs:
            diagnostics["validation_status"] = "error"
            warnings_list.append(f"Invalid directories: {invalid_dirs}")
            recommendations_list.append(
                "Check that all allowed directories exist and are accessible"
            )

        result = {
            "configuration": config_info,
            "diagnostics": diagnostics,
            "timestamp": _utc_now_iso(),
        }

        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error getting server configuration: {e}")
        return server._create_enhanced_error_message(
            operation="get server configuration",
            error=e,
            context="Configuration diagnostics",
        )
