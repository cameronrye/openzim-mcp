"""
Rate limiting utilities for OpenZIM MCP server.

Provides a token bucket rate limiter to protect expensive operations
from abuse and ensure fair resource usage.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .defaults import RATE_LIMIT_COSTS
from .exceptions import OpenZimMcpRateLimitError

logger = logging.getLogger(__name__)


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting.

    Attributes:
        enabled: Whether rate limiting is enabled
        requests_per_second: Maximum requests per second (token refill rate)
        burst_size: Maximum burst size (token bucket capacity)
        per_operation_limits: Optional per-operation overrides
    """

    enabled: bool = True
    requests_per_second: float = 10.0
    burst_size: int = 20
    per_operation_limits: Dict[str, "RateLimitConfig"] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate configuration values."""
        if self.requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        if self.burst_size <= 0:
            raise ValueError("burst_size must be positive")


class TokenBucket:
    """Thread-safe token bucket rate limiter.

    Implements the token bucket algorithm where:
    - Tokens are added at a fixed rate (requests_per_second)
    - Bucket has a maximum capacity (burst_size)
    - Each request consumes one token
    - Requests are rejected if no tokens are available
    """

    def __init__(self, rate: float, capacity: int):
        """Initialize token bucket.

        Args:
            rate: Token refill rate (tokens per second)
            capacity: Maximum bucket capacity
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last_update = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time (must hold lock)."""
        now = time.monotonic()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now

    def acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens from the bucket.

        Args:
            tokens: Number of tokens to acquire

        Returns:
            True if tokens were acquired, False if rate limited
        """
        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def refund(self, tokens: int = 1) -> None:
        """Refund tokens back to the bucket.

        Used when an operation is rejected after tokens were already consumed
        from the global bucket but before the operation completed.

        Args:
            tokens: Number of tokens to refund
        """
        with self._lock:
            self.tokens = min(self.capacity, self.tokens + tokens)

    def get_wait_time(self, tokens: int = 1) -> float:
        """Get time to wait before tokens are available.

        Args:
            tokens: Number of tokens needed

        Returns:
            Seconds to wait (0 if tokens are available now)
        """
        with self._lock:
            self._refill()
            if self.tokens >= tokens:
                return 0.0
            needed = tokens - self.tokens
            return needed / self.rate

    @property
    def available_tokens(self) -> float:
        """Get current available tokens."""
        with self._lock:
            self._refill()
            return self.tokens


class RateLimiter:
    """Rate limiter with support for multiple operation types.

    Provides separate rate limits for different operation categories
    (e.g., search, content retrieval) to allow fine-grained control.
    """

    # Operation costs imported from centralized defaults
    DEFAULT_COSTS: Dict[str, int] = RATE_LIMIT_COSTS

    def __init__(self, config: Optional[RateLimitConfig] = None):
        """Initialize rate limiter.

        Args:
            config: Rate limit configuration (uses defaults if None)
        """
        self.config = config or RateLimitConfig()
        self._buckets: Dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

        # Create global bucket
        self._global_bucket = TokenBucket(
            rate=self.config.requests_per_second,
            capacity=self.config.burst_size,
        )

        logger.info(
            f"Rate limiter initialized: enabled={self.config.enabled}, "
            f"rate={self.config.requests_per_second}/s, burst={self.config.burst_size}"
        )

    def _get_bucket(self, operation: str) -> TokenBucket:
        """Get or create a token bucket for an operation.

        Args:
            operation: Operation name

        Returns:
            TokenBucket for the operation
        """
        if operation not in self._buckets:
            with self._lock:
                if operation not in self._buckets:
                    # Check for operation-specific config
                    if operation in self.config.per_operation_limits:
                        op_config = self.config.per_operation_limits[operation]
                        self._buckets[operation] = TokenBucket(
                            rate=op_config.requests_per_second,
                            capacity=op_config.burst_size,
                        )
                    else:
                        # Use global config
                        self._buckets[operation] = TokenBucket(
                            rate=self.config.requests_per_second,
                            capacity=self.config.burst_size,
                        )
        return self._buckets[operation]

    def check_rate_limit(self, operation: str = "default") -> None:
        """Check if operation is allowed under rate limit.

        Args:
            operation: Operation name for categorized limiting

        Raises:
            OpenZimMcpRateLimitError: If rate limit is exceeded
        """
        if not self.config.enabled:
            return

        cost = self.DEFAULT_COSTS.get(operation, self.DEFAULT_COSTS["default"])

        # Check global limit first
        if not self._global_bucket.acquire(cost):
            wait_time = self._global_bucket.get_wait_time(cost)
            raise OpenZimMcpRateLimitError(
                f"Rate limit exceeded for operation '{operation}'. "
                f"Please wait {wait_time:.2f} seconds before retrying.",
                details=(
                    f"operation={operation}, cost={cost}, wait_time={wait_time:.2f}s"
                ),
            )

        # Check operation-specific limit if configured
        if operation in self.config.per_operation_limits:
            bucket = self._get_bucket(operation)
            if not bucket.acquire(cost):
                wait_time = bucket.get_wait_time(cost)
                # Refund global tokens since we're rejecting
                self._global_bucket.refund(cost)
                raise OpenZimMcpRateLimitError(
                    f"Rate limit exceeded for operation '{operation}'. "
                    f"Please wait {wait_time:.2f} seconds before retrying.",
                    details=(
                        f"operation={operation}, cost={cost}, "
                        f"wait_time={wait_time:.2f}s"
                    ),
                )

        logger.debug(f"Rate limit check passed: operation={operation}, cost={cost}")

    def get_status(self) -> Dict[str, Any]:
        """Get current rate limiter status.

        Returns:
            Dictionary with rate limiter status information
        """
        return {
            "enabled": self.config.enabled,
            "global_tokens_available": self._global_bucket.available_tokens,
            "global_capacity": self.config.burst_size,
            "requests_per_second": self.config.requests_per_second,
            "operation_buckets": {
                op: bucket.available_tokens for op, bucket in self._buckets.items()
            },
        }

    def reset(self) -> None:
        """Reset all rate limit buckets to full capacity."""
        with self._lock:
            self._global_bucket = TokenBucket(
                rate=self.config.requests_per_second,
                capacity=self.config.burst_size,
            )
            self._buckets.clear()
        logger.info("Rate limiter reset to full capacity")
