"""
Tests for cache module.
"""

import time

from openzim_mcp.cache import CacheEntry, OpenZimMcpCache
from openzim_mcp.config import CacheConfig


class TestCacheEntry:
    """Test CacheEntry class."""

    def test_cache_entry_creation(self):
        """Test cache entry creation."""
        entry = CacheEntry("test_value", 60)
        assert entry.value == "test_value"
        assert entry.ttl_seconds == 60
        assert not entry.is_expired()

    def test_cache_entry_expiration(self):
        """Test cache entry expiration."""
        entry = CacheEntry("test_value", 0.1)  # 0.1 second TTL
        assert not entry.is_expired()

        time.sleep(0.2)
        assert entry.is_expired()


class TestOpenZimMcpCache:
    """Test OpenZimMcpCache class."""

    def test_cache_disabled(self):
        """Test cache when disabled."""
        config = CacheConfig(enabled=False)
        cache = OpenZimMcpCache(config)

        cache.set("key", "value")
        result = cache.get("key")
        assert result is None

    def test_cache_set_and_get(self, openzim_mcp_cache: OpenZimMcpCache):
        """Test basic cache set and get operations."""
        openzim_mcp_cache.set("test_key", "test_value")
        result = openzim_mcp_cache.get("test_key")
        assert result == "test_value"

    def test_cache_get_nonexistent(self, openzim_mcp_cache: OpenZimMcpCache):
        """Test getting non-existent key."""
        result = openzim_mcp_cache.get("nonexistent_key")
        assert result is None

    def test_cache_expiration(self):
        """Test cache entry expiration."""
        config = CacheConfig(enabled=True, max_size=10, ttl_seconds=60)
        cache = OpenZimMcpCache(config)

        # Manually create an expired entry
        cache.set("key", "value")
        # Manually expire the entry by setting its created_at to the past
        if "key" in cache._cache:
            cache._cache["key"].created_at = time.time() - 61  # 61 seconds ago

        result = cache.get("key")
        assert result is None

    def test_cache_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        import time

        config = CacheConfig(enabled=True, max_size=2, ttl_seconds=60)
        cache = OpenZimMcpCache(config)

        # Fill cache to capacity
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Access key1 to make it more recently used
        time.sleep(0.01)  # Ensure different timestamps
        cache.get("key1")

        # Add another key, should evict key2 (least recently used)
        time.sleep(0.01)  # Ensure different timestamps
        cache.set("key3", "value3")

        assert cache.get("key1") == "value1"  # Should still exist
        assert cache.get("key2") is None  # Should be evicted
        assert cache.get("key3") == "value3"  # Should exist

    def test_cache_clear(self, openzim_mcp_cache: OpenZimMcpCache):
        """Test cache clear operation."""
        openzim_mcp_cache.set("key1", "value1")
        openzim_mcp_cache.set("key2", "value2")

        openzim_mcp_cache.clear()

        assert openzim_mcp_cache.get("key1") is None
        assert openzim_mcp_cache.get("key2") is None

    def test_cache_stats(self, openzim_mcp_cache: OpenZimMcpCache):
        """Test cache statistics."""
        stats = openzim_mcp_cache.stats()

        assert stats["enabled"] is True
        assert stats["size"] == 0
        assert stats["max_size"] == 5
        assert stats["ttl_seconds"] == 60

        openzim_mcp_cache.set("key", "value")
        stats = openzim_mcp_cache.stats()
        assert stats["size"] == 1

    def test_cache_update_existing_key(self, openzim_mcp_cache: OpenZimMcpCache):
        """Test updating existing cache key."""
        openzim_mcp_cache.set("key", "old_value")
        openzim_mcp_cache.set("key", "new_value")

        result = openzim_mcp_cache.get("key")
        assert result == "new_value"

    def test_cache_cleanup_expired_entries(self):
        """Test _cleanup_expired method with actual expired entries."""
        config = CacheConfig(enabled=True, max_size=10, ttl_seconds=60)
        cache = OpenZimMcpCache(config)

        # Add entries that will expire
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Manually expire the entries by setting their created_at to the past
        for key in cache._cache:
            cache._cache[key].created_at = time.time() - 61  # 61 seconds ago (past TTL)

        # Verify entries are expired
        assert cache._cache["key1"].is_expired()
        assert cache._cache["key2"].is_expired()

        # Call _cleanup_expired to trigger the missing lines
        cache._cleanup_expired()

        # Verify entries were removed
        assert len(cache._cache) == 0
        assert len(cache._access_order) == 0

    def test_cache_evict_lru_empty_cache(self):
        """Test _evict_lru method when cache is empty."""
        config = CacheConfig(enabled=True, max_size=5, ttl_seconds=60)
        cache = OpenZimMcpCache(config)

        # Ensure cache is empty
        assert len(cache._access_order) == 0

        # Call _evict_lru on empty cache to trigger the early return (line 122)
        cache._evict_lru()

        # Cache should still be empty
        assert len(cache._cache) == 0
        assert len(cache._access_order) == 0

    def test_cache_cleanup_expired_with_mixed_entries(self):
        """Test _cleanup_expired with both expired and non-expired entries."""
        config = CacheConfig(enabled=True, max_size=10, ttl_seconds=60)
        cache = OpenZimMcpCache(config)

        # Add entries
        cache.set("expired1", "value1")
        cache.set("expired2", "value2")
        cache.set("valid", "value3")

        # Manually expire some entries
        cache._cache["expired1"].created_at = time.time() - 61  # Expired
        cache._cache["expired2"].created_at = time.time() - 61  # Expired
        # "valid" entry remains with current timestamp (not expired)

        # Call _cleanup_expired to trigger the missing lines
        cache._cleanup_expired()

        # Verify only expired entries were removed
        assert "expired1" not in cache._cache
        assert "expired2" not in cache._cache
        assert "valid" in cache._cache
        assert cache.get("valid") == "value3"

    def test_cache_delete_specific_key(self, openzim_mcp_cache: OpenZimMcpCache):
        """Test deleting a specific cache key."""
        # Add some entries
        openzim_mcp_cache.set("key1", "value1")
        openzim_mcp_cache.set("key2", "value2")
        openzim_mcp_cache.set("key3", "value3")

        assert openzim_mcp_cache.stats()["size"] == 3
        assert openzim_mcp_cache.get("key2") == "value2"

        # Delete specific key
        openzim_mcp_cache.delete("key2")

        assert openzim_mcp_cache.stats()["size"] == 2
        assert openzim_mcp_cache.get("key1") == "value1"
        assert openzim_mcp_cache.get("key2") is None  # Deleted
        assert openzim_mcp_cache.get("key3") == "value3"

    def test_cache_delete_nonexistent_key(self, openzim_mcp_cache: OpenZimMcpCache):
        """Test deleting a key that doesn't exist."""
        openzim_mcp_cache.set("key1", "value1")

        # Delete non-existent key should not raise error
        openzim_mcp_cache.delete("nonexistent")

        assert openzim_mcp_cache.stats()["size"] == 1
        assert openzim_mcp_cache.get("key1") == "value1"

    def test_cache_delete_with_disabled_cache(self):
        """Test delete operation when cache is disabled."""
        config = CacheConfig(enabled=False)
        cache = OpenZimMcpCache(config)

        # Should not raise error even when cache is disabled
        cache.delete("any_key")
