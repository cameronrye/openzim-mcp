"""Tests for cache_stats and cache_clear tools."""

import json

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


class TestCacheStats:
    """Test cache_stats."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Build a server bound to the test config."""
        return OpenZimMcpServer(test_config)

    def test_cache_stats_shape(self, server: OpenZimMcpServer):
        """Return required JSON keys from cache.stats()."""
        # Bypass MCP — call the cache directly to assert shape.
        stats = server.cache.stats()
        assert "size" in stats
        assert "max_size" in stats
        assert "hits" in stats
        assert "misses" in stats

    @pytest.mark.asyncio
    async def test_cache_stats_wrapper_returns_cache_stats(
        self, server: OpenZimMcpServer
    ):
        """End-to-end: cache_stats tool wrapper returns the cache.stats() shape.

        Drives the registered MCP tool function so the JSON serialization
        path is exercised, not just the underlying cache object.
        """
        tools = server.mcp._tool_manager._tools
        assert "cache_stats" in tools, "cache_stats tool not registered"
        tool_handler = tools["cache_stats"].fn

        # Generate at least one hit and one miss so hit_rate is meaningful.
        server.cache.set("k", "v")
        server.cache.get("k")  # hit
        server.cache.get("missing")  # miss

        result_json = await tool_handler()
        result = json.loads(result_json)

        # Confirm the wrapper passes through the cache.stats() shape, including
        # hit_rate (which the wrapper now sources directly from cache.stats()).
        assert "size" in result
        assert "max_size" in result
        assert "hits" in result
        assert "misses" in result
        assert "hit_rate" in result
        # cache.stats() rounds hit_rate to 4 decimals — confirm the wrapper
        # didn't re-compute and clobber that rounding.
        assert result["hit_rate"] == round(result["hit_rate"], 4)


class TestCacheClear:
    """Test cache_clear."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Build a server bound to the test config."""
        return OpenZimMcpServer(test_config)

    def test_cache_clear_empties_cache(self, server: OpenZimMcpServer):
        """Drop cached entries; stats size goes to 0."""
        server.cache.set("key1", "value1")
        server.cache.set("key2", "value2")
        before = server.cache.stats()["size"]
        assert before >= 2

        server.cache.clear()
        after = server.cache.stats()["size"]
        assert after == 0

    @pytest.mark.asyncio
    async def test_cache_clear_wrapper_captures_prior_size(
        self, server: OpenZimMcpServer
    ):
        """End-to-end: cache_clear's JSON includes prior_size and current_size=0.

        The wrapper records prior_size *before* calling clear() — that ordering
        is unique to the tool layer and not exercised by direct cache calls.
        """
        tools = server.mcp._tool_manager._tools
        assert "cache_clear" in tools, "cache_clear tool not registered"
        tool_handler = tools["cache_clear"].fn

        server.cache.set("k1", "v1")
        server.cache.set("k2", "v2")
        prior = server.cache.stats()["size"]
        assert prior >= 2

        result_json = await tool_handler()
        result = json.loads(result_json)

        assert result["cleared"] is True
        assert result["prior_size"] == prior
        assert result["current_size"] == 0
        # And the cache really is empty.
        assert server.cache.stats()["size"] == 0
