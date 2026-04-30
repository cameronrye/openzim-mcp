"""Tests for cache_stats and cache_clear tools."""

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
