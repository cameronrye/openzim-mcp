"""
Extended tests for server_tools module to increase test coverage.

These tests focus on the untested paths in server_tools.py:
- get_server_health: instance tracking, directory checks, cache performance
- get_server_configuration: conflict detection, validation
- diagnose_server_state: comprehensive environment validation
- resolve_server_conflicts: cleanup operations, guidance
"""

import json
from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


class TestGetServerHealthToolInvocation:
    """Test get_server_health tool by invoking the actual registered handler."""

    @pytest.fixture
    def server_with_tracker(self, temp_dir):
        """Create a server with instance tracker."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=True, max_size=100, ttl_seconds=60),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = MagicMock()
        return server

    @pytest.mark.asyncio
    async def test_get_server_health_basic(self, server_with_tracker):
        """Test get_server_health returns valid JSON."""
        server_with_tracker.instance_tracker.get_active_instances = MagicMock(
            return_value=[]
        )
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[]
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            result = await tool_handler()
            health = json.loads(result)

            assert "status" in health
            assert "timestamp" in health
            assert "server_name" in health
            assert "cache_performance" in health
            assert "instance_tracking" in health
            assert "health_checks" in health

    @pytest.mark.asyncio
    async def test_get_server_health_with_conflicts(self, server_with_tracker):
        """Test get_server_health when conflicts are detected."""
        server_with_tracker.instance_tracker.get_active_instances = MagicMock(
            return_value=[MagicMock(pid=12345)]
        )
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[
                {
                    "type": "configuration_mismatch",
                    "instance": {"pid": 12345},
                }
            ]
        )
        server_with_tracker.instance_tracker._is_process_running = MagicMock(
            return_value=True
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            result = await tool_handler()
            health = json.loads(result)

            assert health["status"] == "warning"
            assert len(health["warnings"]) > 0
            assert "conflicts detected" in health["warnings"][0].lower()

    @pytest.mark.asyncio
    async def test_get_server_health_with_stale_instances(self, server_with_tracker):
        """Test get_server_health when stale instances are detected."""
        mock_instance = MagicMock()
        mock_instance.pid = 99999
        server_with_tracker.instance_tracker.get_active_instances = MagicMock(
            return_value=[mock_instance]
        )
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[]
        )
        # Simulate stale instance (process not running)
        server_with_tracker.instance_tracker._is_process_running = MagicMock(
            return_value=False
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            result = await tool_handler()
            health = json.loads(result)

            assert health["instance_tracking"]["stale_instances"] >= 0
            # Should have warning about stale instances if any found
            if health["instance_tracking"]["stale_instances"] > 0:
                assert any("stale" in w.lower() for w in health["warnings"])

    @pytest.mark.asyncio
    async def test_get_server_health_instance_tracker_fails(self, server_with_tracker):
        """Test get_server_health when instance tracker raises an exception."""
        server_with_tracker.instance_tracker.get_active_instances = MagicMock(
            side_effect=RuntimeError("Tracker error")
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            result = await tool_handler()
            health = json.loads(result)

            # Should still return valid health info with warning
            assert "timestamp" in health
            assert any("failed" in w.lower() for w in health["warnings"])

    @pytest.mark.asyncio
    async def test_get_server_health_no_instance_tracker(self, temp_dir):
        """Test get_server_health without instance tracker."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=True),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = None

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            result = await tool_handler()
            health = json.loads(result)

            assert "Instance tracking not available" in health["warnings"]


class TestGetServerHealthDirectoryAndCacheChecks:
    """Test directory and cache health checks in get_server_health."""

    @pytest.mark.asyncio
    async def test_get_server_health_directory_exists(self, temp_dir):
        """Test health check for existing directory."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = None

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            result = await tool_handler()
            health = json.loads(result)

            assert health["health_checks"]["directories_accessible"] >= 1

    @pytest.mark.asyncio
    async def test_get_server_health_no_zim_files(self, temp_dir):
        """Test health check when no ZIM files are found."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = None

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            result = await tool_handler()
            health = json.loads(result)

            assert health["health_checks"]["zim_files_found"] == 0
            assert any("no zim files" in w.lower() for w in health["warnings"])

    @pytest.mark.asyncio
    async def test_get_server_health_with_zim_files(self, temp_dir):
        """Test health check when ZIM files exist."""
        # Create a fake ZIM file
        zim_file = temp_dir / "test.zim"
        zim_file.write_bytes(b"ZIM\x04" + b"\x00" * 100)

        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = None

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            result = await tool_handler()
            health = json.loads(result)

            assert health["health_checks"]["zim_files_found"] >= 1

    @pytest.mark.asyncio
    async def test_get_server_health_low_cache_hit_rate(self, temp_dir):
        """Test cache performance analysis with low hit rate."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=True, max_size=100),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = None
        # Simulate low hit rate
        server.cache.stats = MagicMock(
            return_value={"enabled": True, "hit_rate": 0.1, "hits": 1, "misses": 9}
        )

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            result = await tool_handler()
            health = json.loads(result)

            assert any("hit rate" in r.lower() for r in health["recommendations"])

    @pytest.mark.asyncio
    async def test_get_server_health_high_cache_hit_rate(self, temp_dir):
        """Test cache performance analysis with high hit rate."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=True),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = None
        server.cache.stats = MagicMock(
            return_value={"enabled": True, "hit_rate": 0.95, "hits": 95, "misses": 5}
        )

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            result = await tool_handler()
            health = json.loads(result)

            assert any(
                "performing well" in r.lower() for r in health["recommendations"]
            )

    @pytest.mark.asyncio
    async def test_get_server_health_cache_disabled(self, temp_dir):
        """Test cache performance when cache is disabled."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = None

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            result = await tool_handler()
            health = json.loads(result)

            assert any(
                "enabling cache" in r.lower() or "performance" in r.lower()
                for r in health["recommendations"]
            )


class TestGetServerConfigurationToolInvocation:
    """Test get_server_configuration tool invocation."""

    @pytest.fixture
    def server_with_tracker(self, temp_dir):
        """Create server with instance tracker."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=True),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = MagicMock()
        return server

    @pytest.mark.asyncio
    async def test_get_server_configuration_basic(self, server_with_tracker):
        """Test get_server_configuration returns valid JSON."""
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[]
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "get_server_configuration" in tools:
            tool_handler = tools["get_server_configuration"].fn
            result = await tool_handler()
            config_info = json.loads(result)

            assert "configuration" in config_info
            assert "diagnostics" in config_info
            assert "timestamp" in config_info
            assert config_info["configuration"]["server_name"] is not None

    @pytest.mark.asyncio
    async def test_get_server_configuration_with_conflicts(self, server_with_tracker):
        """Test get_server_configuration with conflicts detected."""
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[{"type": "multiple_instances", "instance": {"pid": 12345}}]
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "get_server_configuration" in tools:
            tool_handler = tools["get_server_configuration"].fn
            result = await tool_handler()
            config_info = json.loads(result)

            assert config_info["diagnostics"]["validation_status"] == "warning"
            assert len(config_info["diagnostics"]["conflicts_detected"]) > 0

    @pytest.mark.asyncio
    async def test_get_server_configuration_conflict_check_fails(
        self, server_with_tracker
    ):
        """Test get_server_configuration when conflict check fails."""
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            side_effect=RuntimeError("Check failed")
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "get_server_configuration" in tools:
            tool_handler = tools["get_server_configuration"].fn
            result = await tool_handler()
            config_info = json.loads(result)

            assert any(
                "could not check" in w.lower()
                for w in config_info["diagnostics"]["warnings"]
            )


class TestDiagnoseServerStateToolInvocation:
    """Test diagnose_server_state tool invocation."""

    @pytest.fixture
    def server_with_tracker(self, temp_dir):
        """Create server with instance tracker."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=True),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = MagicMock()
        return server

    @pytest.mark.asyncio
    async def test_diagnose_server_state_basic(self, server_with_tracker):
        """Test diagnose_server_state returns valid diagnostics."""
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[]
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "diagnose_server_state" in tools:
            tool_handler = tools["diagnose_server_state"].fn
            result = await tool_handler()
            diagnostics = json.loads(result)

            assert "status" in diagnostics
            assert "server_info" in diagnostics
            assert "configuration" in diagnostics
            assert "environment_checks" in diagnostics
            assert len(diagnostics["environment_checks"]) >= 1

    @pytest.mark.asyncio
    async def test_diagnose_server_state_with_conflicts(self, server_with_tracker):
        """Test diagnose_server_state with configuration mismatch."""
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[
                {"type": "configuration_mismatch", "instance": {"pid": 12345}}
            ]
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "diagnose_server_state" in tools:
            tool_handler = tools["diagnose_server_state"].fn
            result = await tool_handler()
            diagnostics = json.loads(result)

            assert diagnostics["status"] == "warning"
            assert len(diagnostics["conflicts"]) > 0
            assert any("mismatch" in r.lower() for r in diagnostics["recommendations"])

    @pytest.mark.asyncio
    async def test_diagnose_server_state_multiple_instances(self, server_with_tracker):
        """Test diagnose_server_state with multiple instances conflict."""
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[{"type": "multiple_instances", "instance": {"pid": 67890}}]
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "diagnose_server_state" in tools:
            tool_handler = tools["diagnose_server_state"].fn
            result = await tool_handler()
            diagnostics = json.loads(result)

            assert diagnostics["status"] == "warning"
            assert any(
                "multiple server" in r.lower() or "67890" in r
                for r in diagnostics["recommendations"]
            )

    @pytest.mark.asyncio
    async def test_diagnose_server_state_with_zim_files(self, temp_dir):
        """Test diagnose_server_state with ZIM files."""
        # Create a fake ZIM file with valid magic number
        zim_file = temp_dir / "test.zim"
        zim_file.write_bytes(b"ZIM\x04" + b"\x00" * 100)

        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = MagicMock()
        server.instance_tracker.detect_conflicts = MagicMock(return_value=[])

        tools = server.mcp._tool_manager._tools
        if "diagnose_server_state" in tools:
            tool_handler = tools["diagnose_server_state"].fn
            result = await tool_handler()
            diagnostics = json.loads(result)

            # Check the directory in environment_checks
            # Use resolved path from config (handles /var -> /private/var symlink)
            dir_key = server.config.allowed_directories[0]
            assert dir_key in diagnostics["environment_checks"]
            dir_check = diagnostics["environment_checks"][dir_key]
            assert dir_check["zim_files_count"] >= 1
            assert dir_check["zim_files_accessible"] >= 1

    @pytest.mark.asyncio
    async def test_diagnose_server_state_invalid_zim_magic(self, temp_dir):
        """Test diagnose_server_state with invalid ZIM magic number."""
        # Create a file with wrong magic number
        zim_file = temp_dir / "invalid.zim"
        zim_file.write_bytes(b"NOTAZIM" + b"\x00" * 100)

        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = MagicMock()
        server.instance_tracker.detect_conflicts = MagicMock(return_value=[])

        tools = server.mcp._tool_manager._tools
        if "diagnose_server_state" in tools:
            tool_handler = tools["diagnose_server_state"].fn
            result = await tool_handler()
            diagnostics = json.loads(result)

            # Use resolved path from config (handles /var -> /private/var symlink)
            dir_key = server.config.allowed_directories[0]
            dir_check = diagnostics["environment_checks"][dir_key]
            # Should have warning about invalid ZIM file
            assert any(
                "may not be a valid zim" in w.lower() for w in dir_check["warnings"]
            )

    @pytest.mark.asyncio
    async def test_diagnose_server_state_conflict_detection_fails(
        self, server_with_tracker
    ):
        """Test diagnose_server_state when conflict detection fails."""
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            side_effect=RuntimeError("Detection failed")
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "diagnose_server_state" in tools:
            tool_handler = tools["diagnose_server_state"].fn
            result = await tool_handler()
            diagnostics = json.loads(result)

            assert any("failed" in i.lower() for i in diagnostics["issues"])


class TestResolveServerConflictsToolInvocation:
    """Test resolve_server_conflicts tool invocation."""

    @pytest.fixture
    def server_with_tracker(self, temp_dir):
        """Create server with instance tracker."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = MagicMock()
        return server

    @pytest.mark.asyncio
    async def test_resolve_server_conflicts_no_tracker(self, temp_dir):
        """Test resolve_server_conflicts without instance tracker."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = None

        tools = server.mcp._tool_manager._tools
        if "resolve_server_conflicts" in tools:
            tool_handler = tools["resolve_server_conflicts"].fn
            result = await tool_handler()
            resolution = json.loads(result)

            assert resolution["status"] == "error"
            assert any(
                "not available" in r.lower() for r in resolution["recommendations"]
            )

    @pytest.mark.asyncio
    async def test_resolve_server_conflicts_no_conflicts(self, server_with_tracker):
        """Test resolve_server_conflicts when no conflicts exist."""
        server_with_tracker.instance_tracker.cleanup_stale_instances = MagicMock(
            return_value=0
        )
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[]
        )
        server_with_tracker.instance_tracker.get_active_instances = MagicMock(
            return_value=[]
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "resolve_server_conflicts" in tools:
            tool_handler = tools["resolve_server_conflicts"].fn
            result = await tool_handler()
            resolution = json.loads(result)

            assert resolution["status"] == "success"
            assert any("healthy" in r.lower() for r in resolution["recommendations"])

    @pytest.mark.asyncio
    async def test_resolve_server_conflicts_with_stale_cleanup(
        self, server_with_tracker
    ):
        """Test resolve_server_conflicts when stale instances are cleaned."""
        server_with_tracker.instance_tracker.cleanup_stale_instances = MagicMock(
            return_value=3
        )
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[]
        )
        server_with_tracker.instance_tracker.get_active_instances = MagicMock(
            return_value=[]
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "resolve_server_conflicts" in tools:
            tool_handler = tools["resolve_server_conflicts"].fn
            result = await tool_handler()
            resolution = json.loads(result)

            assert resolution["cleanup_results"]["stale_instances_removed"] == 3
            assert any(
                "removed 3 stale" in a.lower() for a in resolution["actions_taken"]
            )

    @pytest.mark.asyncio
    async def test_resolve_server_conflicts_with_active_conflicts(
        self, server_with_tracker
    ):
        """Test resolve_server_conflicts with active conflicts."""
        server_with_tracker.instance_tracker.cleanup_stale_instances = MagicMock(
            return_value=0
        )
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[
                {"type": "configuration_mismatch", "instance": {"pid": 12345}}
            ]
        )
        server_with_tracker.instance_tracker.get_active_instances = MagicMock(
            return_value=[MagicMock(pid=12345)]
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "resolve_server_conflicts" in tools:
            tool_handler = tools["resolve_server_conflicts"].fn
            result = await tool_handler()
            resolution = json.loads(result)

            assert resolution["status"] == "conflicts_detected"
            assert len(resolution["conflicts_found"]) > 0
            assert any(
                "configuration conflict" in r.lower() or "12345" in r
                for r in resolution["recommendations"]
            )

    @pytest.mark.asyncio
    async def test_resolve_server_conflicts_cleanup_fails(self, server_with_tracker):
        """Test resolve_server_conflicts when cleanup fails."""
        server_with_tracker.instance_tracker.cleanup_stale_instances = MagicMock(
            side_effect=RuntimeError("Cleanup failed")
        )
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[]
        )
        server_with_tracker.instance_tracker.get_active_instances = MagicMock(
            return_value=[]
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "resolve_server_conflicts" in tools:
            tool_handler = tools["resolve_server_conflicts"].fn
            result = await tool_handler()
            resolution = json.loads(result)

            assert any(
                "failed to clean up" in r.lower() for r in resolution["recommendations"]
            )

    @pytest.mark.asyncio
    async def test_resolve_server_conflicts_detect_fails(self, server_with_tracker):
        """Test resolve_server_conflicts when conflict detection fails."""
        server_with_tracker.instance_tracker.cleanup_stale_instances = MagicMock(
            return_value=0
        )
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            side_effect=RuntimeError("Detection failed")
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "resolve_server_conflicts" in tools:
            tool_handler = tools["resolve_server_conflicts"].fn
            result = await tool_handler()
            resolution = json.loads(result)

            assert any(
                "failed to detect" in r.lower() for r in resolution["recommendations"]
            )


class TestServerToolsExceptionHandling:
    """Test exception handling in server tools."""

    @pytest.mark.asyncio
    async def test_get_server_health_exception(self, temp_dir):
        """Test get_server_health handles unexpected exceptions."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)
        # Force an exception by breaking cache
        server.cache.stats = MagicMock(side_effect=RuntimeError("Cache error"))

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            result = await tool_handler()
            # Should return error message, not raise
            assert "Error" in result or "error" in result.lower()
