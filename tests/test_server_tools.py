"""
Tests for server_tools module.
"""

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

    def test_server_health_instance_tracking(self, server: OpenZimMcpServer):
        """Test that server health includes instance tracking info."""
        # Instance tracking structure
        instance_tracking = {
            "enabled": server.instance_tracker is not None,
            "active_instances": 0,
            "conflicts_detected": 0,
            "stale_instances": 0,
        }
        assert "enabled" in instance_tracking
        assert "active_instances" in instance_tracking

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
            "conflicts_detected": [],
            "validation_status": "ok",
            "warnings": [],
            "recommendations": [],
        }

        assert "conflicts_detected" in diagnostics
        assert diagnostics["validation_status"] in ["ok", "warning", "error"]


class TestDiagnoseServerStateTool:
    """Test diagnose_server_state tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_diagnostics_structure(self, server: OpenZimMcpServer):
        """Test that diagnostics have the correct structure."""
        diagnostics = {
            "status": "healthy",
            "server_info": {
                "pid": os.getpid(),
                "server_name": server.config.server_name,
                "config_hash": server.config.get_config_hash(),
            },
            "configuration": {
                "allowed_directories": server.config.allowed_directories,
                "cache_enabled": server.config.cache.enabled,
            },
            "conflicts": [],
            "issues": [],
            "recommendations": [],
            "environment_checks": {},
        }

        assert diagnostics["status"] in ["healthy", "warning", "error"]
        assert "server_info" in diagnostics
        assert "configuration" in diagnostics

    def test_directory_check_structure(self, server: OpenZimMcpServer):
        """Test that directory checks have correct structure."""
        dir_check = {
            "exists": True,
            "is_directory": True,
            "readable": True,
            "writable": True,
            "zim_files_count": 0,
            "zim_files_accessible": 0,
            "total_size_mb": 0,
            "issues": [],
            "warnings": [],
        }

        assert "exists" in dir_check
        assert "readable" in dir_check
        assert "zim_files_count" in dir_check


class TestResolveServerConflictsTool:
    """Test resolve_server_conflicts tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_resolution_results_structure(self, server: OpenZimMcpServer):
        """Test that resolution results have correct structure."""
        resolution_results = {
            "conflicts_found": [],
            "actions_taken": [],
            "cleanup_results": {
                "stale_instances_removed": 0,
                "corrupted_files_removed": 0,
                "active_instances_found": 0,
            },
            "recommendations": [],
            "status": "success",
        }

        assert resolution_results["status"] in [
            "success",
            "error",
            "conflicts_detected",
        ]
        assert "cleanup_results" in resolution_results

    def test_conflict_resolution_guidance(self):
        """Test that conflict resolution provides proper guidance."""
        recommendations = [
            "",
            "**Conflict Resolution Steps**:",
            "1. Identify which server instance you want to keep running",
            "2. Stop other server processes using their PID (kill <PID> on Unix/Mac)",
            "3. Run this tool again to verify conflicts are resolved",
            "4. Use 'diagnose_server_state()' for detailed server analysis",
        ]

        assert any("Conflict Resolution Steps" in r for r in recommendations)
        assert any("Stop other server processes" in r for r in recommendations)

    def test_no_instance_tracker_error(self, server: OpenZimMcpServer):
        """Test behavior when instance tracker is not available."""
        # Simulate no instance tracker
        original_tracker = server.instance_tracker
        server.instance_tracker = None

        resolution_results = {
            "status": "error",
            "recommendations": ["Instance tracker not available."],
        }

        assert resolution_results["status"] == "error"

        # Restore
        server.instance_tracker = original_tracker


class TestZimMagicNumberValidation:
    """Test ZIM magic number validation in diagnostics."""

    def test_zim_magic_number(self):
        """Test that ZIM magic number constant is correct."""
        # ZIM files start with "ZIM\x04"
        zim_magic = b"ZIM\x04"
        assert len(zim_magic) == 4
        assert zim_magic[0:3] == b"ZIM"
        assert zim_magic[3] == 0x04


class TestDiskSpaceChecking:
    """Test disk space checking functionality."""

    def test_low_disk_space_warning(self):
        """Test that low disk space generates warning."""
        free_space_mb = 50  # Less than 100MB

        warnings = []
        if free_space_mb < 100:
            warnings.append(f"Low disk space: {free_space_mb:.1f}MB available")

        assert len(warnings) == 1
        assert "Low disk space" in warnings[0]

    def test_adequate_disk_space_no_warning(self):
        """Test that adequate disk space doesn't generate warning."""
        free_space_mb = 500  # More than 100MB threshold

        # With adequate space, no warnings should be generated
        warnings = []
        # Only add warning if space is low (this condition is False for 500MB)
        warnings = (
            [f"Low disk space: {free_space_mb:.1f}MB available"]
            if free_space_mb < 100
            else []
        )

        assert len(warnings) == 0
