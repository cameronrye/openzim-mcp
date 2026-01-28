"""
Caching functionality for OpenZIM MCP server.
"""

import logging
import time
from typing import Any, Dict, Optional

from .config import CacheConfig

logger = logging.getLogger(__name__)


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

    def __init__(self, config: CacheConfig):
        """
        Initialize cache.

        Args:
            config: Cache configuration
        """
        self.config = config
        self._cache: Dict[str, CacheEntry] = {}
        self._access_order: Dict[str, float] = {}
        self._hits: int = 0
        self._misses: int = 0
        logger.info(
            f"Cache initialized: enabled={config.enabled}, "
            f"max_size={config.max_size}, ttl={config.ttl_seconds}s"
        )

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        if not self.config.enabled:
            return None

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
        self._access_order[key] = time.time()
        self._hits += 1
        logger.debug(f"Cache hit: {key}")
        return entry.value

    def set(self, key: str, value: Any) -> None:
        """
        Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        if not self.config.enabled:
            return

        # Remove expired entries
        self._cleanup_expired()

        # Check if we need to evict entries
        if len(self._cache) >= self.config.max_size and key not in self._cache:
            self._evict_lru()

        # Add/update entry
        self._cache[key] = CacheEntry(value, self.config.ttl_seconds)
        self._access_order[key] = time.time()
        logger.debug(f"Cache set: {key}")

    def delete(self, key: str) -> None:
        """
        Delete a specific key from cache.

        Args:
            key: Cache key to delete
        """
        if not self.config.enabled:
            return

        if key in self._cache:
            self._remove(key)
            logger.debug(f"Cache entry deleted: {key}")

    def _remove(self, key: str) -> None:
        """Remove entry from cache."""
        self._cache.pop(key, None)
        self._access_order.pop(key, None)

    def _cleanup_expired(self) -> None:
        """Remove all expired entries."""
        expired_keys = [key for key, entry in self._cache.items() if entry.is_expired()]

        for key in expired_keys:
            self._remove(key)

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired cache entries")

    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if not self._access_order:
            return

        # Find least recently used key
        lru_key = min(self._access_order.keys(), key=lambda k: self._access_order[k])
        self._remove(lru_key)
        logger.debug(f"Evicted LRU cache entry: {lru_key}")

    def clear(self) -> None:
        """Clear all cache entries and reset statistics."""
        self._cache.clear()
        self._access_order.clear()
        self._hits = 0
        self._misses = 0
        logger.info("Cache cleared")

    def reset_stats(self) -> None:
        """Reset hit/miss statistics without clearing cache entries."""
        self._hits = 0
        self._misses = 0
        logger.debug("Cache statistics reset")

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics including hit/miss rates.

        Returns:
            Dictionary containing:
            - enabled: Whether cache is enabled
            - size: Current number of entries
            - max_size: Maximum allowed entries
            - ttl_seconds: Time-to-live for entries
            - hits: Number of cache hits
            - misses: Number of cache misses
            - hit_rate: Ratio of hits to total requests (0.0-1.0)

        Example:
            >>> cache = OpenZimMcpCache(config)
            >>> cache.set("key", "value")
            >>> cache.get("key")  # hit
            >>> cache.get("missing")  # miss
            >>> stats = cache.stats()
            >>> stats["hits"]
            1
            >>> stats["misses"]
            1
            >>> stats["hit_rate"]
            0.5
        """
        total_requests = self._hits + self._misses
        hit_rate = self._hits / total_requests if total_requests > 0 else 0.0

        return {
            "enabled": self.config.enabled,
            "size": len(self._cache),
            "max_size": self.config.max_size,
            "ttl_seconds": self.config.ttl_seconds,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
        }
