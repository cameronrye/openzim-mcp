"""
Caching functionality for OpenZIM MCP server.

Provides an in-memory LRU cache with TTL support, optional background
cleanup to proactively remove expired entries, and optional persistence
for cache warmup between restarts.
"""

import atexit
import contextlib
import heapq
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import CacheConfig

logger = logging.getLogger(__name__)

# Default interval for background cleanup (in seconds)
DEFAULT_CLEANUP_INTERVAL = 60

# File extension for persistence files
CACHE_FILE_EXTENSION = ".json"


class CacheEntry:
    """Represents a single cache entry with TTL."""

    def __init__(self, value: Any, ttl_seconds: int):
        """
        Initialize cache entry.

        Args:
            value: Value to cache
            ttl_seconds: Time to live in seconds

        Example:
            >>> entry = CacheEntry("cached_value", ttl_seconds=3600)
            >>> entry.is_expired()
            False
        """
        self.value = value
        self.created_at = time.time()
        self.ttl_seconds = ttl_seconds

    def is_expired(self) -> bool:
        """Check if cache entry has expired."""
        return time.time() - self.created_at > self.ttl_seconds


class OpenZimMcpCache:
    """Simple in-memory cache with TTL support and hit/miss statistics.

    This cache implements LRU (Least Recently Used) eviction with TTL-based
    expiration. It tracks cache hits and misses for performance monitoring.

    Features:
    - Thread-safe operations with locking
    - Background cleanup thread for proactive expiration
    - LRU eviction using heap for O(log n) performance
    - Hit/miss statistics for monitoring
    - Optional persistence for cache warmup between restarts

    Example:
        >>> from openzim_mcp.config import CacheConfig
        >>> config = CacheConfig(enabled=True, max_size=100, ttl_seconds=3600)
        >>> cache = OpenZimMcpCache(config)
        >>> cache.set("key1", "value1")
        >>> cache.get("key1")
        'value1'
        >>> stats = cache.stats()
        >>> stats["hits"]
        1
    """

    def __init__(
        self,
        config: CacheConfig,
        enable_background_cleanup: bool = True,
        cleanup_interval: int = DEFAULT_CLEANUP_INTERVAL,
    ):
        """
        Initialize cache.

        Args:
            config: Cache configuration
            enable_background_cleanup: If True, start a background thread to
                proactively clean up expired entries
            cleanup_interval: Interval in seconds between cleanup runs
        """
        self.config = config
        self._cache: Dict[str, CacheEntry] = {}
        self._access_order: Dict[str, float] = {}
        # Heap for O(log n) LRU eviction: (access_time, key)
        # Uses lazy deletion - entries may be stale if key was updated or removed
        self._lru_heap: List[Tuple[float, str]] = []
        self._hits: int = 0
        self._misses: int = 0
        self._lock = threading.RLock()  # Reentrant lock for thread safety

        # Background cleanup thread
        self._cleanup_thread: Optional[threading.Thread] = None
        self._cleanup_stop_event = threading.Event()
        self._cleanup_interval = cleanup_interval

        # Persistence settings
        self._persistence_enabled = getattr(config, "persistence_enabled", False)
        self._persistence_path = Path(
            getattr(config, "persistence_path", ".openzim_mcp_cache")
        )

        # Load persisted cache if enabled
        if config.enabled and self._persistence_enabled:
            self._load_from_disk()

        if config.enabled and enable_background_cleanup:
            self._start_cleanup_thread()
            # Register shutdown handler to stop cleanup thread gracefully
            atexit.register(self._stop_cleanup_thread)

        # Register persistence handler on shutdown
        if config.enabled and self._persistence_enabled:
            atexit.register(self._save_to_disk)

        logger.info(
            f"Cache initialized: enabled={config.enabled}, "
            f"max_size={config.max_size}, ttl={config.ttl_seconds}s, "
            f"background_cleanup={enable_background_cleanup}, "
            f"persistence={self._persistence_enabled}"
        )

    def _start_cleanup_thread(self) -> None:
        """Start the background cleanup thread."""
        if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
            return  # Already running

        self._cleanup_stop_event.clear()
        self._cleanup_thread = threading.Thread(
            target=self._background_cleanup_loop,
            name="CacheCleanupThread",
            daemon=True,  # Daemon thread will exit when main program exits
        )
        self._cleanup_thread.start()
        logger.debug("Cache background cleanup thread started")

    def _stop_cleanup_thread(self) -> None:
        """Stop the background cleanup thread gracefully."""
        if self._cleanup_thread is None:
            return

        self._cleanup_stop_event.set()
        # Give the thread a chance to exit cleanly
        self._cleanup_thread.join(timeout=2.0)
        # Use try/except for logging during shutdown to avoid logging errors
        try:
            if self._cleanup_thread.is_alive():
                logger.debug("Cache cleanup thread did not stop in time")
            else:
                logger.debug("Cache background cleanup thread stopped")
        except Exception as e:
            # Logging may fail during shutdown - best effort debug log
            with contextlib.suppress(Exception):
                logger.debug(f"Exception during cleanup thread shutdown: {e}")
        self._cleanup_thread = None

    def _background_cleanup_loop(self) -> None:
        """Background loop that periodically cleans up expired entries."""
        while not self._cleanup_stop_event.is_set():
            try:
                # Wait for the cleanup interval or until stop is signaled
                if self._cleanup_stop_event.wait(timeout=self._cleanup_interval):
                    break  # Stop event was set

                # Perform cleanup
                self._cleanup_expired()
            except Exception as e:
                # Log but don't crash the cleanup thread
                logger.debug(f"Error in cache cleanup thread: {e}")

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache (thread-safe).

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        if not self.config.enabled:
            return None

        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            entry = self._cache[key]

            # Check if expired
            if entry.is_expired():
                self._remove(key)
                self._misses += 1
                logger.debug(f"Cache entry expired: {key}")
                return None

            # Update access time for LRU
            access_time = time.time()
            self._access_order[key] = access_time
            # Push to heap - old entries skipped during eviction (lazy cleanup)
            heapq.heappush(self._lru_heap, (access_time, key))
            self._hits += 1
            logger.debug(f"Cache hit: {key}")
            return entry.value

    def set(self, key: str, value: Any) -> None:
        """
        Set value in cache (thread-safe).

        Args:
            key: Cache key
            value: Value to cache
        """
        if not self.config.enabled:
            return

        with self._lock:
            # Check if we need to evict entries
            if len(self._cache) >= self.config.max_size and key not in self._cache:
                self._evict_lru()

            # Add/update entry
            self._cache[key] = CacheEntry(value, self.config.ttl_seconds)
            access_time = time.time()
            self._access_order[key] = access_time
            # Push to heap for O(log n) LRU eviction
            heapq.heappush(self._lru_heap, (access_time, key))
            logger.debug(f"Cache set: {key}")

    def delete(self, key: str) -> None:
        """
        Delete a specific key from cache (thread-safe).

        Args:
            key: Cache key to delete
        """
        if not self.config.enabled:
            return

        with self._lock:
            if key in self._cache:
                self._remove(key)
                logger.debug(f"Cache entry deleted: {key}")

    def _remove(self, key: str) -> None:
        """Remove entry from cache (must be called with lock held)."""
        self._cache.pop(key, None)
        self._access_order.pop(key, None)

    def _cleanup_expired(self) -> None:
        """Remove all expired entries (thread-safe)."""
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items() if entry.is_expired()
            ]

            for key in expired_keys:
                self._remove(key)

            if expired_keys:
                logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

    def _evict_lru(self) -> None:
        """Evict least recently used entry using heap (must be called with lock held).

        Uses lazy deletion: entries in heap may be stale if key was accessed again
        or removed. We skip invalid entries until we find a valid one to evict.
        """
        while self._lru_heap:
            # Pop the oldest entry from heap
            access_time, key = heapq.heappop(self._lru_heap)

            # Check if this entry is still valid (not stale)
            # An entry is valid if:
            # 1. The key still exists in cache
            # 2. The access time matches (not updated since)
            if key in self._access_order and self._access_order[key] == access_time:
                self._remove(key)
                logger.debug(f"Evicted LRU cache entry: {key}")
                return

            # Entry is stale (key was removed or accessed more recently), skip it

        # Fallback: if heap is empty but cache has entries, use linear scan
        # This shouldn't happen in normal operation but provides safety
        if self._access_order:
            lru_key = min(
                self._access_order.keys(), key=lambda k: self._access_order[k]
            )
            self._remove(lru_key)
            logger.debug(f"Evicted LRU cache entry (fallback): {lru_key}")

    def clear(self) -> None:
        """Clear all cache entries and reset statistics (thread-safe)."""
        with self._lock:
            self._cache.clear()
            self._access_order.clear()
            self._lru_heap.clear()
            self._hits = 0
            self._misses = 0
        logger.info("Cache cleared")

    def reset_stats(self) -> None:
        """Reset hit/miss statistics without clearing cache entries (thread-safe)."""
        with self._lock:
            self._hits = 0
            self._misses = 0
        logger.debug("Cache statistics reset")

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics including hit/miss rates (thread-safe)."""
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0

            stats = {
                "enabled": self.config.enabled,
                "size": len(self._cache),
                "max_size": self.config.max_size,
                "ttl_seconds": self.config.ttl_seconds,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 4),
                "background_cleanup": (
                    self._cleanup_thread is not None and self._cleanup_thread.is_alive()
                ),
                "persistence_enabled": self._persistence_enabled,
            }

            # Add persistence file info if enabled
            if self._persistence_enabled:
                persistence_file = self._get_persistence_file()
                stats["persistence_path"] = str(persistence_file)
                stats["persistence_file_exists"] = persistence_file.exists()

            return stats

    def shutdown(self) -> None:
        """Shutdown the cache and stop background threads."""
        self._stop_cleanup_thread()
        if self._persistence_enabled:
            self._save_to_disk()
        logger.debug("Cache shutdown complete")

    def _get_persistence_file(self) -> Path:
        """Get the path to the persistence file."""
        if self._persistence_path.suffix == CACHE_FILE_EXTENSION:
            return self._persistence_path
        return self._persistence_path.with_suffix(CACHE_FILE_EXTENSION)

    def _save_to_disk(self) -> None:
        """Save cache contents to disk for persistence.

        Only saves non-expired entries. Thread-safe.
        """
        if not self._persistence_enabled:
            return

        try:
            with self._lock:
                # Collect non-expired entries
                entries_to_save: Dict[str, Dict[str, Any]] = {}
                for key, entry in self._cache.items():
                    if not entry.is_expired():
                        entries_to_save[key] = {
                            "value": entry.value,
                            "created_at": entry.created_at,
                            "ttl_seconds": entry.ttl_seconds,
                        }

            if not entries_to_save:
                # Remove persistence file if cache is empty
                persistence_file = self._get_persistence_file()
                if persistence_file.exists():
                    persistence_file.unlink()
                    logger.debug("Removed empty cache persistence file")
                return

            # Ensure parent directory exists
            persistence_file = self._get_persistence_file()
            persistence_file.parent.mkdir(parents=True, exist_ok=True)

            # Write to temp file first, then rename for atomicity
            temp_file = persistence_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "version": 1,
                        "saved_at": time.time(),
                        "entries": entries_to_save,
                    },
                    f,
                    indent=2,
                    default=str,  # Handle non-serializable values
                )

            # Atomic rename
            temp_file.replace(persistence_file)
            logger.debug(f"Saved {len(entries_to_save)} cache entries to disk")

        except Exception as e:
            logger.warning(f"Failed to save cache to disk: {e}")

    def _load_from_disk(self) -> None:
        """Load cache contents from disk.

        Skips expired entries and entries with non-deserializable values.
        """
        if not self._persistence_enabled:
            return

        persistence_file = self._get_persistence_file()
        if not persistence_file.exists():
            logger.debug("No cache persistence file found")
            return

        try:
            with open(persistence_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            if data.get("version") != 1:
                logger.warning(
                    f"Unsupported cache persistence version: {data.get('version')}"
                )
                return

            entries = data.get("entries", {})
            loaded_count = 0
            current_time = time.time()

            with self._lock:
                for key, entry_data in entries.items():
                    created_at = entry_data.get("created_at", 0)
                    ttl_seconds = entry_data.get("ttl_seconds", self.config.ttl_seconds)

                    # Skip expired entries
                    if current_time - created_at > ttl_seconds:
                        continue

                    # Restore entry
                    entry = CacheEntry(entry_data["value"], ttl_seconds)
                    entry.created_at = created_at
                    self._cache[key] = entry

                    # Restore access order (use created_at as initial access time)
                    self._access_order[key] = created_at
                    heapq.heappush(self._lru_heap, (created_at, key))
                    loaded_count += 1

            logger.info(f"Loaded {loaded_count} cache entries from disk")

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse cache persistence file: {e}")
        except Exception as e:
            logger.warning(f"Failed to load cache from disk: {e}")

    def persist(self) -> bool:
        """Manually trigger cache persistence.

        Returns:
            True if persistence succeeded, False otherwise
        """
        if not self._persistence_enabled:
            logger.debug("Cache persistence is not enabled")
            return False

        try:
            self._save_to_disk()
            return True
        except Exception as e:
            logger.error(f"Manual cache persistence failed: {e}")
            return False
