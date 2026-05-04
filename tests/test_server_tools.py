"""Tests for server_tools module."""

import json
import os

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


class TestRegisterServerTools:
    """Test server tools registration."""

    def test_register_server_tools(self, test_config: OpenZimMcpConfig):
        """Test that server tools are registered correctly."""
        server = OpenZimMcpServer(test_config)
        assert server.mcp is not None


class TestGetServerHealthTool:
    """Test get_server_health tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_server_health_basic_info(self, server: OpenZimMcpServer):
        """Test that server health includes basic info."""
        # Verify server components are available
        assert server.cache is not None
        assert server.config is not None

        # Test cache stats
        cache_stats = server.cache.stats()
        assert "enabled" in cache_stats

    def test_health_checks_structure(self, server: OpenZimMcpServer):
        """Test that health checks have the correct structure."""
        health_checks = {
            "directories_accessible": 0,
            "zim_files_found": 0,
            "permissions_ok": True,
        }
        assert "directories_accessible" in health_checks
        assert "zim_files_found" in health_checks
        assert "permissions_ok" in health_checks

    def test_cache_performance_thresholds(self):
        """Test cache performance threshold constants."""
        from openzim_mcp.constants import (
            CACHE_HIGH_HIT_RATE_THRESHOLD,
            CACHE_LOW_HIT_RATE_THRESHOLD,
        )

        assert CACHE_LOW_HIT_RATE_THRESHOLD < CACHE_HIGH_HIT_RATE_THRESHOLD
        assert CACHE_LOW_HIT_RATE_THRESHOLD >= 0
        assert CACHE_HIGH_HIT_RATE_THRESHOLD <= 1


class TestGetServerConfigurationTool:
    """Test get_server_configuration tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_server_configuration_basic_info(self, server: OpenZimMcpServer):
        """Test that server configuration includes basic info."""
        config_info = {
            "server_name": server.config.server_name,
            "allowed_directories": server.config.allowed_directories,
            "cache_enabled": server.config.cache.enabled,
            "cache_max_size": server.config.cache.max_size,
            "cache_ttl_seconds": server.config.cache.ttl_seconds,
            "content_max_length": server.config.content.max_content_length,
            "config_hash": server.config.get_config_hash(),
            "server_pid": os.getpid(),
        }

        assert config_info["server_name"] is not None
        assert isinstance(config_info["allowed_directories"], list)
        assert isinstance(config_info["cache_enabled"], bool)

    def test_server_configuration_diagnostics_structure(self, server: OpenZimMcpServer):
        """Test that configuration diagnostics have correct structure."""
        diagnostics = {
            "validation_status": "ok",
            "warnings": [],
            "recommendations": [],
        }

        assert diagnostics["validation_status"] in ["ok", "warning", "error"]


class TestDiagnosticToolPathRedaction:
    """Diagnostic tool responses must not leak filesystem paths or PIDs."""

    @pytest.mark.asyncio
    async def test_get_server_configuration_redacts_allowed_directories(self, temp_dir):
        """Allowed directory paths must not appear verbatim in the response."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)

        tools = server.mcp._tool_manager._tools
        assert "get_server_configuration" in tools
        tool_handler = tools["get_server_configuration"].fn
        result = await tool_handler()

        # The full directory path must not be present.
        assert str(temp_dir) not in result, "allowed_directories path leaked"
        # But the section identifier should still be present.
        assert "allowed_directories" in result.lower()

        parsed = json.loads(result)
        # PID must not be exposed.
        assert parsed["configuration"]["server_pid"] != os.getpid()
        # A non-sensitive count should still be available for diagnostics.
        assert parsed["configuration"].get("allowed_directories_count") == len(
            config.allowed_directories
        )

    @pytest.mark.asyncio
    async def test_get_server_health_redacts_paths(self, temp_dir):
        """get_server_health must not leak any allowed directory paths."""
        # Create a missing/invalid subdirectory so warning paths are also exercised.
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)

        tools = server.mcp._tool_manager._tools
        assert "get_server_health" in tools
        tool_handler = tools["get_server_health"].fn
        result = await tool_handler()

        for d in server.config.allowed_directories:
            assert str(d) not in result, f"path leaked in health response: {d}"

        parsed = json.loads(result)
        # PID must not be exposed.
        assert parsed["uptime_info"]["process_id"] != os.getpid()
        # Uptime is now tracked (replaces the old "unknown" placeholder).
        assert parsed["uptime_info"]["started_at"] != "unknown"
        assert isinstance(parsed["uptime_info"]["uptime_seconds"], (int, float))
        assert parsed["uptime_info"]["uptime_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_get_server_health_warning_paths_redacted(self, temp_dir):
        """Warning messages about inaccessible directories must redact paths."""
        # Build a config that points at a real dir so validation passes,
        # then mutate the in-memory list to include a nonexistent path so
        # the warning code path runs and we can verify path redaction.
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)
        bogus = str(temp_dir / "definitely-not-here-xyz")
        # Bypass validation; we only want the runtime warning text.
        server.config.allowed_directories = list(server.config.allowed_directories) + [
            bogus
        ]

        tools = server.mcp._tool_manager._tools
        tool_handler = tools["get_server_health"].fn
        result = await tool_handler()

        assert bogus not in result, "bogus path leaked into warning text"

    @pytest.mark.asyncio
    async def test_get_server_configuration_invalid_dirs_redacted(self, temp_dir):
        """Invalid-directory warnings in get_server_configuration must redact paths."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)
        bogus = str(temp_dir / "missing-subdir-zzz")
        server.config.allowed_directories = list(server.config.allowed_directories) + [
            bogus
        ]

        tools = server.mcp._tool_manager._tools
        tool_handler = tools["get_server_configuration"].fn
        result = await tool_handler()

        assert bogus not in result, "bogus path leaked into config diagnostics"
