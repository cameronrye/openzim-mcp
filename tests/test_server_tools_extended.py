"""
Extended tests for server_tools module to increase test coverage.

These tests focus on the untested paths in server_tools.py:
- get_server_health: directory checks, cache performance
- get_server_configuration: validation
- exception handling
"""

from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


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

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            health = await tool_handler()

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

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            health = await tool_handler()

            assert health["health_checks"]["zim_files_found"] == 0
            assert any("no zim files" in w.lower() for w in health["warnings"])

    @pytest.mark.asyncio
    async def test_get_server_health_with_zim_files(self, temp_dir):
        """Test health check when ZIM files exist."""
        zim_file = temp_dir / "test.zim"
        zim_file.write_bytes(b"ZIM\x04" + b"\x00" * 100)

        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            health = await tool_handler()

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
        # Use enough accesses (>= 50) to clear the warm-up gate that
        # silences low-rate warnings in fresh sessions.
        server.cache.stats = MagicMock(
            return_value={
                "enabled": True,
                "hit_rate": 0.1,
                "hits": 10,
                "misses": 90,
            }
        )

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            health = await tool_handler()

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
        server.cache.stats = MagicMock(
            return_value={"enabled": True, "hit_rate": 0.95, "hits": 95, "misses": 5}
        )

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            health = await tool_handler()

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

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            health = await tool_handler()

            assert any(
                "enabling cache" in r.lower() or "performance" in r.lower()
                for r in health["recommendations"]
            )


class TestGetServerConfigurationToolInvocation:
    """Test get_server_configuration tool invocation."""

    @pytest.mark.asyncio
    async def test_get_server_configuration_basic(self, temp_dir):
        """Test get_server_configuration returns a structured dict."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=True),
        )
        server = OpenZimMcpServer(config)

        tools = server.mcp._tool_manager._tools
        if "get_server_configuration" in tools:
            tool_handler = tools["get_server_configuration"].fn
            config_info = await tool_handler()

            assert "configuration" in config_info
            assert "diagnostics" in config_info
            assert "timestamp" in config_info
            assert config_info["configuration"]["server_name"] is not None


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
        server.cache.stats = MagicMock(side_effect=RuntimeError("Cache error"))

        tools = server.mcp._tool_manager._tools
        if "get_server_health" in tools:
            tool_handler = tools["get_server_health"].fn
            result = await tool_handler()
            # Tool now returns a structured error envelope.
            assert result.get("error") is True
            assert result.get("operation") == "get server health"
            assert "message" in result
