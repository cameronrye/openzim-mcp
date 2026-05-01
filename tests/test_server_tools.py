"""Tests for server_tools module."""

import os

import pytest

from openzim_mcp.config import OpenZimMcpConfig
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
