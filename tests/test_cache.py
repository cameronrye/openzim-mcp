"""Tests for cache module."""

import time
from datetime import datetime
from pathlib import Path

import pytest

from openzim_mcp.cache import CacheEntry, OpenZimMcpCache
from openzim_mcp.config import CacheConfig
from openzim_mcp.exceptions import OpenZimMcpValidationError


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
            cache._cache["key"].created_at = time.monotonic() - 61  # 61 seconds ago

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
            cache._cache[key].created_at = (
                time.monotonic() - 61
            )  # 61 seconds ago (past TTL)

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
        cache._cache["expired1"].created_at = time.monotonic() - 61  # Expired
        cache._cache["expired2"].created_at = time.monotonic() - 61  # Expired
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


class TestCacheStatistics:
    """Test cache statistics functionality."""

    def test_stats_hit_rate_calculation(self):
        """Test that hit rate is calculated correctly."""
        config = CacheConfig(enabled=True, max_size=10, ttl_seconds=60)
        cache = OpenZimMcpCache(config)

        # Set some values
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Generate some hits and misses
        cache.get("key1")  # Hit
        cache.get("key1")  # Hit
        cache.get("key2")  # Hit
        cache.get("nonexistent1")  # Miss
        cache.get("nonexistent2")  # Miss

        stats = cache.stats()
        assert stats["hits"] == 3
        assert stats["misses"] == 2
        # Hit rate should be 3/5 = 0.6
        assert stats["hit_rate"] == pytest.approx(0.6)

    def test_stats_with_zero_requests(self):
        """Test stats when no requests have been made."""
        config = CacheConfig(enabled=True, max_size=10, ttl_seconds=60)
        cache = OpenZimMcpCache(config)

        stats = cache.stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == pytest.approx(0.0)


class TestCacheBackgroundCleanup:
    """Test cache background cleanup functionality."""

    def test_cache_without_background_cleanup(self):
        """Test creating cache without background cleanup thread."""
        config = CacheConfig(enabled=True, max_size=10, ttl_seconds=60)
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)

        stats = cache.stats()
        assert stats["background_cleanup"] is False

    def test_cache_with_background_cleanup(self):
        """Test that background cleanup thread is started."""
        config = CacheConfig(enabled=True, max_size=10, ttl_seconds=60)
        cache = OpenZimMcpCache(config, enable_background_cleanup=True)

        # Give thread time to start
        time.sleep(0.1)

        stats = cache.stats()
        assert stats["background_cleanup"] is True

        # Clean up
        cache.shutdown()

    def test_cache_shutdown(self):
        """Test cache shutdown stops cleanup thread."""
        config = CacheConfig(enabled=True, max_size=10, ttl_seconds=60)
        cache = OpenZimMcpCache(config, enable_background_cleanup=True)

        # Verify thread is running
        time.sleep(0.1)
        assert cache.stats()["background_cleanup"] is True

        # Shutdown
        cache.shutdown()

        # Verify thread is stopped
        assert cache._cleanup_thread is None

    def test_cleanup_thread_already_running(self):
        """Test that starting cleanup thread when already running does nothing."""
        config = CacheConfig(enabled=True, max_size=10, ttl_seconds=60)
        cache = OpenZimMcpCache(config, enable_background_cleanup=True)

        time.sleep(0.1)
        original_thread = cache._cleanup_thread

        # Try to start again
        cache._start_cleanup_thread()

        # Should be the same thread
        assert cache._cleanup_thread is original_thread

        cache.shutdown()


class TestCacheLRUEviction:
    """Test LRU eviction with heap implementation."""

    def test_heap_based_lru_eviction(self):
        """Test that heap-based LRU correctly evicts oldest accessed entry."""
        config = CacheConfig(enabled=True, max_size=3, ttl_seconds=60)
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)

        # Add entries with controlled access patterns
        cache.set("key1", "value1")
        time.sleep(0.01)
        cache.set("key2", "value2")
        time.sleep(0.01)
        cache.set("key3", "value3")

        # Access key1 to make it more recent
        time.sleep(0.01)
        cache.get("key1")

        # Add new entry, should evict key2 (least recently accessed)
        time.sleep(0.01)
        cache.set("key4", "value4")

        assert cache.get("key1") == "value1"  # Most recently accessed
        assert cache.get("key2") is None  # Should be evicted
        assert cache.get("key3") == "value3"  # Existed
        assert cache.get("key4") == "value4"  # Newly added

    def test_evict_lru_with_stale_heap_entries(self):
        """Test that stale heap entries are skipped during eviction."""
        config = CacheConfig(enabled=True, max_size=2, ttl_seconds=60)
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)

        # Add and access entries to create stale heap entries
        cache.set("key1", "value1")
        time.sleep(0.01)
        cache.set("key2", "value2")

        # Access key1 multiple times (creates stale heap entries)
        for _ in range(5):
            time.sleep(0.001)
            cache.get("key1")

        # Now add new entry - should evict key2 despite stale entries in heap
        time.sleep(0.01)
        cache.set("key3", "value3")

        assert cache.get("key1") == "value1"
        assert cache.get("key2") is None  # Evicted
        assert cache.get("key3") == "value3"

    def test_evict_lru_fallback_empty_heap(self):
        """Test LRU eviction fallback when heap is empty but cache has entries."""
        config = CacheConfig(enabled=True, max_size=2, ttl_seconds=60)
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)

        # Add entries
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Manually clear the heap (simulating edge case)
        cache._lru_heap.clear()

        # Add new entry - should use fallback linear scan
        cache.set("key3", "value3")

        # One of the old entries should be evicted
        remaining = sum(1 for k in ["key1", "key2", "key3"] if cache.get(k) is not None)
        assert remaining == 2  # Only 2 should remain


class TestCacheByteBudget:
    """Phase C #13: byte-budget eviction prevents large entries from
    pinning hundreds of MB even when entry count stays well below
    ``max_size``."""

    def test_oversized_payloads_trigger_byte_eviction(self):
        # 6 KB cap, 100 entries allowed by count — byte cap kicks in first.
        config = CacheConfig(
            enabled=True, max_size=100, ttl_seconds=60, max_bytes=6 * 1024
        )
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)

        big = "X" * 2048  # ~2 KB JSON-encoded (with quotes)
        cache.set("a", big)
        cache.set("b", big)
        # Two ~2 KB entries fit under the 6 KB cap.
        assert cache.get("a") == big
        assert cache.get("b") == big
        assert cache.stats()["size"] == 2

        # Third entry pushes total over 6 KB → eviction kicks in,
        # evicting the LRU entry (key "a" was accessed first).
        cache.set("c", big)
        # Cache still respects the byte budget after eviction.
        assert cache.stats()["size_bytes"] <= 6 * 1024 + 1024  # +1 KB headroom
        # Some entry got evicted to make room (typically the LRU one).
        assert cache.stats()["size"] < 3

    def test_byte_budget_zero_disables_byte_eviction(self):
        """max_bytes=0 → byte cap disabled; only count cap applies."""
        config = CacheConfig(enabled=True, max_size=100, ttl_seconds=60, max_bytes=0)
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)

        big = "X" * 4096
        for i in range(10):
            cache.set(f"k{i}", big)
        # All 10 entries fit (under the 100-count cap).
        assert cache.stats()["size"] == 10

    def test_total_bytes_decrements_on_delete(self):
        config = CacheConfig(enabled=True, max_size=10, ttl_seconds=60)
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)
        cache.set("k", "value")
        before = cache.stats()["size_bytes"]
        assert before > 0
        cache.delete("k")
        assert cache.stats()["size_bytes"] == 0

    def test_total_bytes_resets_to_zero_on_clear(self):
        config = CacheConfig(enabled=True, max_size=10, ttl_seconds=60)
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)
        cache.set("k1", "value1")
        cache.set("k2", "value2")
        assert cache.stats()["size_bytes"] > 0
        cache.clear()
        assert cache.stats()["size_bytes"] == 0


class TestCachePersistence:
    """Test cache persistence functionality."""

    def test_persistence_disabled_by_default(self, temp_dir):
        """Test that persistence is disabled by default."""
        config = CacheConfig(enabled=True, max_size=10, ttl_seconds=60)
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)

        stats = cache.stats()
        assert stats["persistence_enabled"] is False

    def test_get_persistence_file_with_suffix(self, temp_dir):
        """Test _get_persistence_file returns correct path."""
        from openzim_mcp.config import CacheConfig

        # Create config with persistence (manual attribute setting for test)
        config = CacheConfig(
            enabled=True,
            max_size=10,
            ttl_seconds=60,
            persistence_enabled=True,
            persistence_path=str(temp_dir / "test_cache"),
        )
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)

        persistence_file = cache._get_persistence_file()
        assert str(persistence_file).endswith(".json")

    def test_get_persistence_file_already_has_suffix(self, temp_dir):
        """Test _get_persistence_file when path already has .json suffix."""
        from openzim_mcp.config import CacheConfig

        config = CacheConfig(
            enabled=True,
            max_size=10,
            ttl_seconds=60,
            persistence_enabled=True,
            persistence_path=str(temp_dir / "test_cache.json"),
        )
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)

        persistence_file = cache._get_persistence_file()
        # CacheConfig.persistence_path is now normalized via .resolve() so the
        # stored path is the canonical (symlink-resolved) form. Compare via
        # Path.resolve() to handle the macOS /var -> /private/var symlink and
        # any other canonicalization the validator applies.
        assert persistence_file.resolve() == (temp_dir / "test_cache.json").resolve()
        assert persistence_file.suffix == ".json"

    def test_save_and_load_from_disk(self, temp_dir):
        """Test saving cache to disk and loading it back."""
        from openzim_mcp.config import CacheConfig

        cache_path = str(temp_dir / "test_cache")
        config = CacheConfig(
            enabled=True,
            max_size=10,
            ttl_seconds=60,
            persistence_enabled=True,
            persistence_path=cache_path,
        )

        # Create cache and add entries
        cache1 = OpenZimMcpCache(config, enable_background_cleanup=False)
        cache1.set("key1", "value1")
        cache1.set("key2", {"nested": "data"})
        cache1.set("key3", [1, 2, 3])

        # Manually trigger save
        cache1._save_to_disk()

        # Verify file was created
        assert (temp_dir / "test_cache.json").exists()

        # Create new cache instance that will load from disk
        cache2 = OpenZimMcpCache(config, enable_background_cleanup=False)

        # Verify entries were loaded
        assert cache2.get("key1") == "value1"
        assert cache2.get("key2") == {"nested": "data"}
        assert cache2.get("key3") == [1, 2, 3]

    def test_save_empty_cache_removes_file(self, temp_dir):
        """Test that saving empty cache removes persistence file."""
        from openzim_mcp.config import CacheConfig

        cache_path = str(temp_dir / "test_cache")
        config = CacheConfig(
            enabled=True,
            max_size=10,
            ttl_seconds=60,
            persistence_enabled=True,
            persistence_path=cache_path,
        )

        # Create cache with entry
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)
        cache.set("key", "value")
        cache._save_to_disk()

        # Verify file exists
        persistence_file = cache._get_persistence_file()
        assert persistence_file.exists()

        # Clear cache and save
        cache.clear()
        cache._save_to_disk()

        # File should be removed
        assert not persistence_file.exists()

    def test_load_skips_expired_entries(self, temp_dir):
        """Test that loading from disk skips expired entries."""
        import json

        from openzim_mcp.config import CacheConfig

        cache_path = temp_dir / "test_cache.json"
        config = CacheConfig(
            enabled=True,
            max_size=10,
            ttl_seconds=60,
            persistence_enabled=True,
            persistence_path=str(cache_path),
        )

        # Create persistence file with expired entry
        current_time = time.time()
        data = {
            "version": 1,
            "saved_at": current_time,
            "entries": {
                "valid_key": {
                    "value": "valid_value",
                    "created_at": current_time - 30,  # 30 seconds ago, not expired
                    "ttl_seconds": 60,
                },
                "expired_key": {
                    "value": "expired_value",
                    "created_at": current_time - 120,  # 120 seconds ago, expired
                    "ttl_seconds": 60,
                },
            },
        }

        with open(cache_path, "w") as f:
            json.dump(data, f)

        # Load cache
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)

        # Only valid entry should be loaded
        assert cache.get("valid_key") == "valid_value"
        assert cache.get("expired_key") is None

    def test_load_with_invalid_version(self, temp_dir):
        """Test loading persistence file with unsupported version."""
        import json

        from openzim_mcp.config import CacheConfig

        cache_path = temp_dir / "test_cache.json"
        config = CacheConfig(
            enabled=True,
            max_size=10,
            ttl_seconds=60,
            persistence_enabled=True,
            persistence_path=str(cache_path),
        )

        # Create persistence file with wrong version
        data = {"version": 999, "entries": {"key": {"value": "value"}}}
        with open(cache_path, "w") as f:
            json.dump(data, f)

        # Load cache - should skip entries due to version mismatch
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)
        assert cache.get("key") is None
        assert cache.stats()["size"] == 0

    def test_load_with_corrupted_file(self, temp_dir):
        """Test loading corrupted persistence file."""
        from openzim_mcp.config import CacheConfig

        cache_path = temp_dir / "test_cache.json"
        config = CacheConfig(
            enabled=True,
            max_size=10,
            ttl_seconds=60,
            persistence_enabled=True,
            persistence_path=str(cache_path),
        )

        # Create corrupted file
        with open(cache_path, "w") as f:
            f.write("not valid json {{{")

        # Load cache - should handle error gracefully
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)
        assert cache.stats()["size"] == 0

    def test_load_skips_individual_malformed_entries(self, temp_dir):
        """A single malformed entry must not abort loading the rest.

        Older cache files (or hand-edited / partially-written ones) may
        contain entries missing required fields. Per-entry isolation
        means the loader logs and skips the bad record instead of
        bailing out before valid entries that follow it.
        """
        import json as _json

        from openzim_mcp.config import CacheConfig

        cache_path = temp_dir / "test_cache.json"
        config = CacheConfig(
            enabled=True,
            max_size=10,
            ttl_seconds=60,
            persistence_enabled=True,
            persistence_path=str(cache_path),
        )

        now = time.time()
        payload = {
            "version": 1,
            "saved_at": now,
            "entries": {
                "good_before": {
                    "value": "v1",
                    "created_at": now,
                    "ttl_seconds": 60,
                },
                "missing_value": {  # bad: no "value" key
                    "created_at": now,
                    "ttl_seconds": 60,
                },
                "wrong_shape": "not-a-dict",  # bad: not an object
                "good_after": {
                    "value": "v2",
                    "created_at": now,
                    "ttl_seconds": 60,
                },
            },
        }
        with open(cache_path, "w") as f:
            _json.dump(payload, f)

        cache = OpenZimMcpCache(config, enable_background_cleanup=False)
        # Both good entries survive; malformed records are skipped.
        assert cache.get("good_before") == "v1"
        assert cache.get("good_after") == "v2"
        assert cache.get("missing_value") is None
        assert cache.get("wrong_shape") is None

    def test_restore_entry_accounts_for_total_bytes(self, temp_dir):
        """Regression: _restore_entry must update _total_bytes.

        Before this guarantee, byte-budget eviction silently failed after
        a warm-start: ``_total_bytes`` read zero until enough new ``set()``
        calls accumulated to cross ``max_bytes`` from zero, even when the
        loaded snapshot was already well over the cap.
        """
        from openzim_mcp.config import CacheConfig

        cache_path = str(temp_dir / "byte_acct")
        config = CacheConfig(
            enabled=True,
            max_size=100,
            ttl_seconds=60,
            persistence_enabled=True,
            persistence_path=cache_path,
        )
        cache1 = OpenZimMcpCache(config, enable_background_cleanup=False)
        for i in range(5):
            cache1.set(f"k{i}", "x" * 1000)
        bytes_before = cache1.stats()["size_bytes"]
        assert bytes_before > 0
        cache1._save_to_disk()

        cache2 = OpenZimMcpCache(config, enable_background_cleanup=False)
        # After load, _total_bytes must reflect the loaded entries — not 0.
        bytes_after = cache2.stats()["size_bytes"]
        assert bytes_after == bytes_before, (
            f"After warm-start, _total_bytes={bytes_after} but expected "
            f"{bytes_before} (size of loaded entries)"
        )

    def test_load_enforces_max_size_cap(self, temp_dir):
        """Regression: _load_from_disk must enforce max_size against the snapshot.

        Operator tightens ``max_size`` between restarts → loaded entries
        must be evicted down to the new cap, not silently exceed it.
        """
        from openzim_mcp.config import CacheConfig

        cache_path = str(temp_dir / "size_cap")
        # Write a snapshot with 5 entries under a permissive cap.
        wide_config = CacheConfig(
            enabled=True,
            max_size=10,
            ttl_seconds=60,
            persistence_enabled=True,
            persistence_path=cache_path,
        )
        cache1 = OpenZimMcpCache(wide_config, enable_background_cleanup=False)
        for i in range(5):
            cache1.set(f"k{i}", f"v{i}")
        cache1._save_to_disk()

        # Reload under a tighter cap. Three entries must be evicted.
        narrow_config = CacheConfig(
            enabled=True,
            max_size=2,
            ttl_seconds=60,
            persistence_enabled=True,
            persistence_path=cache_path,
        )
        cache2 = OpenZimMcpCache(narrow_config, enable_background_cleanup=False)
        assert cache2.stats()["size"] <= 2, (
            f"After load under max_size=2, cache holds "
            f"{cache2.stats()['size']} entries"
        )

    def test_load_enforces_max_bytes_cap(self, temp_dir):
        """Regression: _load_from_disk must enforce max_bytes against the snapshot.

        Without this, a snapshot whose loaded ``_total_bytes`` exceeds
        the configured ``max_bytes`` violates the cap until new ``set()``
        calls trigger the eviction loop. Combined with the
        ``_restore_entry`` accounting fix, the byte budget is honored
        immediately after warm-start.
        """
        from openzim_mcp.config import CacheConfig

        cache_path = str(temp_dir / "byte_cap")
        wide_config = CacheConfig(
            enabled=True,
            max_size=100,
            ttl_seconds=60,
            max_bytes=0,  # disabled while building snapshot
            persistence_enabled=True,
            persistence_path=cache_path,
        )
        cache1 = OpenZimMcpCache(wide_config, enable_background_cleanup=False)
        # Each entry ~1100 bytes; 10 entries ~11 KB total.
        for i in range(10):
            cache1.set(f"k{i}", "x" * 1024)
        cache1._save_to_disk()

        # Reload with a tight 3 KB cap. Must evict down.
        narrow_config = CacheConfig(
            enabled=True,
            max_size=100,
            ttl_seconds=60,
            max_bytes=3 * 1024,
            persistence_enabled=True,
            persistence_path=cache_path,
        )
        cache2 = OpenZimMcpCache(narrow_config, enable_background_cleanup=False)
        # Assert on entry count (not just size_bytes): the prior bug masked
        # itself in ``size_bytes`` because ``_restore_entry`` didn't update
        # ``_total_bytes`` either, so a buggy load reported 0 bytes for 10
        # loaded entries. Count is the unambiguous signal.
        entry_count = cache2.stats()["size"]
        bytes_after = cache2.stats()["size_bytes"]
        # 1024-byte entries with a 3 KB cap → at most 3 entries (or 1 under
        # the single-entry-overshoot rule in set()).
        assert entry_count <= 3, (
            f"After load under max_bytes=3KB, cache holds {entry_count} "
            f"entries ({bytes_after} bytes) — byte cap not enforced"
        )

    def test_load_from_disk_holds_lock_during_file_read(self, temp_dir):
        """Regression: ``_load_from_disk`` must hold ``_lock`` across the
        file-read AND the entry-restore loop. Previously the JSON parse
        ran outside the lock, leaving a narrow window where a concurrent
        ``clear()`` or ``set()`` from another thread could land between
        the read and the restore. Verified by probing from a *different*
        thread whether the lock is acquirable while ``_load_from_disk``
        opens the persistence file. The cache uses ``RLock``, so a
        same-thread probe would always succeed (reentrant); a foreign
        thread sees the lock as held.
        """
        import builtins
        import threading

        from openzim_mcp.config import CacheConfig

        cache_path = str(temp_dir / "lock_race")
        config = CacheConfig(
            enabled=True,
            max_size=10,
            ttl_seconds=60,
            persistence_enabled=True,
            persistence_path=cache_path,
        )
        cache1 = OpenZimMcpCache(config, enable_background_cleanup=False)
        cache1.set("k", "v")
        cache1._save_to_disk()

        cache2 = OpenZimMcpCache(config, enable_background_cleanup=False)
        cache2.clear()
        cache2.set("probe", "v")
        cache2._save_to_disk()

        lock_held_during_read = {"value": None}
        real_open = builtins.open

        def probe_from_foreign_thread() -> bool:
            """Try-acquire from a thread that does NOT own the RLock.
            Returns ``True`` when the lock is currently held by someone
            else (acquire fails); ``False`` when it's free.
            """
            held = {"v": False}

            def runner() -> None:
                got = cache2._lock.acquire(blocking=False)
                if got:
                    cache2._lock.release()
                held["v"] = not got

            t = threading.Thread(target=runner)
            t.start()
            t.join(timeout=2.0)
            return held["v"]

        def probing_open(*args, **kwargs):
            lock_held_during_read["value"] = probe_from_foreign_thread()
            return real_open(*args, **kwargs)

        try:
            builtins.open = probing_open
            cache2._load_from_disk()
        finally:
            builtins.open = real_open

        assert lock_held_during_read["value"] is True, (
            "Expected ``_lock`` to be held when ``_load_from_disk`` opens "
            "the persistence file. A foreign-thread probe found the lock "
            "free, indicating the JSON parse runs outside the critical "
            "section."
        )


class TestCacheEdgeCases:
    """Test edge cases and error conditions."""

    def test_cache_with_none_value(self, openzim_mcp_cache: OpenZimMcpCache):
        """Test caching None values."""
        openzim_mcp_cache.set("null_key", None)
        # Note: get() returns None for both missing keys and None values
        # This is expected behavior
        result = openzim_mcp_cache.get("null_key")
        assert result is None

    def test_cache_with_empty_string_value(self, openzim_mcp_cache: OpenZimMcpCache):
        """Test caching empty string values."""
        openzim_mcp_cache.set("empty_key", "")
        result = openzim_mcp_cache.get("empty_key")
        assert result == ""

    def test_cache_with_complex_objects(self, openzim_mcp_cache: OpenZimMcpCache):
        """Test caching complex objects."""
        complex_obj = {
            "nested": {"list": [1, 2, 3], "dict": {"a": "b"}},
            "tuple": (1, 2, 3),  # Will be stored as list in JSON
        }
        openzim_mcp_cache.set("complex", complex_obj)
        result = openzim_mcp_cache.get("complex")
        assert result["nested"]["list"] == [1, 2, 3]

    def test_thread_safety_concurrent_access(self):
        """Test thread safety with concurrent access."""
        import threading

        config = CacheConfig(enabled=True, max_size=100, ttl_seconds=60)
        cache = OpenZimMcpCache(config, enable_background_cleanup=False)

        errors = []

        def writer():
            try:
                for i in range(50):
                    cache.set(
                        f"key_{threading.current_thread().name}_{i}", f"value_{i}"
                    )
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for i in range(50):
                    cache.get(f"key_{threading.current_thread().name}_{i}")
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            threads.append(threading.Thread(target=writer, name=f"writer_{i}"))
            threads.append(threading.Thread(target=reader, name=f"reader_{i}"))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"


class TestCacheJsonSerializableValidation:
    """Validate cache values are JSON-serializable when persistence is enabled (M21)."""

    def test_cache_set_rejects_non_json_serializable_when_persistence_enabled(
        self, tmp_path
    ):
        """Non-JSON values must be rejected at write time, not silently coerced."""
        cfg = CacheConfig(
            enabled=True,
            persistence_enabled=True,
            persistence_path=str(tmp_path / "cache"),
        )
        cache = OpenZimMcpCache(cfg, enable_background_cleanup=False)
        with pytest.raises(OpenZimMcpValidationError):
            cache.set("k", object())

    def test_cache_set_rejects_path_when_persistence_enabled(self, tmp_path):
        """Path is not JSON-serializable; reject rather than str()-coerce."""
        cfg = CacheConfig(
            enabled=True,
            persistence_enabled=True,
            persistence_path=str(tmp_path / "cache"),
        )
        cache = OpenZimMcpCache(cfg, enable_background_cleanup=False)
        with pytest.raises(OpenZimMcpValidationError):
            cache.set("k", Path("/tmp/foo"))

    def test_cache_set_rejects_datetime_when_persistence_enabled(self, tmp_path):
        """Datetime is not JSON-serializable; reject rather than str()-coerce."""
        cfg = CacheConfig(
            enabled=True,
            persistence_enabled=True,
            persistence_path=str(tmp_path / "cache"),
        )
        cache = OpenZimMcpCache(cfg, enable_background_cleanup=False)
        with pytest.raises(OpenZimMcpValidationError):
            cache.set("k", datetime.now())

    def test_cache_set_allows_non_json_when_persistence_disabled(self):
        """In-memory caches still accept arbitrary Python objects."""
        cfg = CacheConfig(enabled=True, persistence_enabled=False)
        cache = OpenZimMcpCache(cfg, enable_background_cleanup=False)
        sentinel = object()
        cache.set("k", sentinel)
        assert cache.get("k") is sentinel

    def test_cache_set_allows_json_compatible_values_when_persistence_enabled(
        self, tmp_path
    ):
        """Strings, dicts, lists, numbers, None still accepted."""
        cfg = CacheConfig(
            enabled=True,
            persistence_enabled=True,
            persistence_path=str(tmp_path / "cache"),
        )
        cache = OpenZimMcpCache(cfg, enable_background_cleanup=False)
        cache.set("s", "value")
        cache.set("d", {"a": 1, "b": [1, 2, 3]})
        cache.set("l", [1, 2, 3])
        cache.set("n", 42)
        cache.set("z", None)
        assert cache.get("s") == "value"
        assert cache.get("d") == {"a": 1, "b": [1, 2, 3]}
        assert cache.get("l") == [1, 2, 3]
        assert cache.get("n") == 42
