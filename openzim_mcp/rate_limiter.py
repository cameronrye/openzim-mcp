"""
Rate limiting utilities for OpenZIM MCP server.

Provides a token bucket rate limiter to protect expensive operations
from abuse and ensure fair resource usage.
"""

import logging
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

from .defaults import RATE_LIMIT, RATE_LIMIT_COSTS
from .exceptions import OpenZimMcpRateLimitError

logger = logging.getLogger(__name__)


class RateLimitConfig(BaseModel):
    """Configuration for rate limiting.

    This is the single source of truth for rate-limit configuration. It
    is referenced both by the rate limiter and by ``OpenZimMcpConfig``
    (under the ``rate_limit`` field), so settings such as
    ``per_operation_limits`` are reachable from env vars / JSON config
    via pydantic-settings (M4).

    Attributes:
        enabled: Whether rate limiting is enabled
        requests_per_second: Maximum requests per second (token refill rate)
        burst_size: Maximum burst size (token bucket capacity)
        per_operation_limits: Optional per-operation overrides keyed by
            operation name. Each value is itself a ``RateLimitConfig``
            so an operation can have its own bucket parameters.
    """

    enabled: bool = Field(default=RATE_LIMIT.ENABLED)
    requests_per_second: float = Field(default=RATE_LIMIT.REQUESTS_PER_SECOND)
    burst_size: int = Field(default=RATE_LIMIT.BURST_SIZE, le=1000)
    per_operation_limits: Dict[str, "RateLimitConfig"] = Field(default_factory=dict)

    @field_validator("requests_per_second")
    @classmethod
    def _validate_requests_per_second(cls, v: float) -> float:
        """Reject non-positive refill rates."""
        if v <= 0:
            raise ValueError("requests_per_second must be positive")
        return v

    @field_validator("burst_size")
    @classmethod
    def _validate_burst_size(cls, v: int) -> int:
        """Reject non-positive bucket capacities."""
        if v <= 0:
            raise ValueError("burst_size must be positive")
        return v


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
    """Rate limiter with support for multiple operation types and clients.

    Provides separate rate limits for different operation categories
    (e.g., search, content retrieval) and per-client isolation so a single
    abusive caller cannot starve everyone else.

    Buckets are keyed by (client_id, operation) for the per-operation tier
    and by client_id alone for the global tier. To bound memory under a
    flood of distinct client_ids we use OrderedDicts and LRU-evict the
    oldest client once max_clients is reached. When a client is evicted
    its buckets are dropped entirely; if it returns later it gets a fresh
    full burst, which is acceptable because eviction only kicks in under
    cardinality far above any realistic concurrent client count.
    """

    # Operation costs imported from centralized defaults
    DEFAULT_COSTS: Dict[str, int] = RATE_LIMIT_COSTS

    def __init__(
        self,
        config: Optional[RateLimitConfig] = None,
        max_clients: int = 10_000,
    ):
        """Initialize rate limiter.

        Args:
            config: Rate limit configuration (uses defaults if None)
            max_clients: Maximum number of distinct client_ids to track
                before LRU-evicting the oldest. Bounds memory under high
                client cardinality.
        """
        self.config = config or RateLimitConfig()
        self._max_clients = max_clients
        # Per-(client_id, operation) buckets, used only when an operation
        # has a per_operation_limits override.
        self._buckets: "OrderedDict[Tuple[str, str], TokenBucket]" = OrderedDict()
        # Per-client global buckets — replaces the previous single
        # process-wide global bucket so one client can't starve everyone.
        self._global_buckets: "OrderedDict[str, TokenBucket]" = OrderedDict()
        self._lock = threading.Lock()
        # Coarse lock held across the global+per-op acquire pair so the
        # composite check is atomic. Without it, two threads can both
        # consume the global bucket, then one is refunded after losing
        # the per-op race — but during the gap a third caller can be
        # spuriously denied at the global layer (H5).
        self._coarse_lock = threading.Lock()

        logger.info(
            f"Rate limiter initialized: enabled={self.config.enabled}, "
            f"rate={self.config.requests_per_second}/s, "
            f"burst={self.config.burst_size}, "
            f"max_clients={self._max_clients}"
        )

    def _evict_client_if_needed(self) -> None:
        """Evict the LRU client when over capacity (must hold _lock).

        When the global-bucket map is full, drop the oldest client and
        also remove every per-(client_id, op) bucket carrying that same
        client_id so per-op state for an evicted client doesn't outlive
        its global counterpart.
        """
        while len(self._global_buckets) > self._max_clients:
            evicted_id, _ = self._global_buckets.popitem(last=False)
            # Drop any per-op buckets for this client. Materialize the
            # keys-to-delete list first to avoid mutating during iteration.
            stale = [k for k in self._buckets if k[0] == evicted_id]
            for k in stale:
                del self._buckets[k]

    def _get_global_bucket(self, client_id: str) -> TokenBucket:
        """Get or create the per-client global bucket (must hold _lock).

        Note: this does NOT update LRU order. Recency is tracked by
        ``_touch_client``, which the caller invokes only after a
        successful acquire — so a flood of failed calls from one client
        cannot keep that client artificially warm and starve eviction
        of genuinely-idle clients.

        Args:
            client_id: Client identifier

        Returns:
            The TokenBucket for this client's global tier
        """
        bucket = self._global_buckets.get(client_id)
        if bucket is not None:
            return bucket
        bucket = TokenBucket(
            rate=self.config.requests_per_second,
            capacity=self.config.burst_size,
        )
        self._global_buckets[client_id] = bucket
        self._evict_client_if_needed()
        return bucket

    def _touch_client(self, client_id: str) -> None:
        """Mark client as recently used for LRU (must hold _lock).

        Called only after a successful acquire so failed/denied calls
        don't count as activity.
        """
        if client_id in self._global_buckets:
            self._global_buckets.move_to_end(client_id)

    def _get_op_bucket(self, client_id: str, operation: str) -> TokenBucket:
        """Get or create the per-(client_id, operation) bucket (must hold _lock).

        Args:
            client_id: Client identifier
            operation: Operation name

        Returns:
            The TokenBucket for this client's per-operation tier
        """
        key = (client_id, operation)
        bucket = self._buckets.get(key)
        if bucket is not None:
            return bucket
        # Pick the operation-specific config when defined, otherwise fall
        # back to the global config (matches the legacy behavior).
        if operation in self.config.per_operation_limits:
            op_config = self.config.per_operation_limits[operation]
            bucket = TokenBucket(
                rate=op_config.requests_per_second,
                capacity=op_config.burst_size,
            )
        else:
            bucket = TokenBucket(
                rate=self.config.requests_per_second,
                capacity=self.config.burst_size,
            )
        self._buckets[key] = bucket
        return bucket

    def check_rate_limit(
        self,
        operation: str = "default",
        cost: Optional[int] = None,
        client_id: str = "default",
    ) -> None:
        """Check if operation is allowed under the rate limit.

        Args:
            operation: Operation name for categorized limiting
            cost: Token cost for this call. When None (default), looks up
                the canonical cost in DEFAULT_COSTS. Tests pass an explicit
                value to decouple from the cost table.
            client_id: Identifier for the calling client. Buckets are keyed
                on (client_id, operation) so abuse from one client doesn't
                starve others. Stdio callers pass "default" (single client);
                HTTP callers should pass a stable per-connection identifier
                derived from the auth token or remote address.

        Raises:
            OpenZimMcpRateLimitError: If rate limit is exceeded
        """
        if not self.config.enabled:
            return

        if cost is None:
            cost = self.DEFAULT_COSTS.get(operation, self.DEFAULT_COSTS["default"])

        # Hold the coarse lock so the global + per-op acquire pair is one
        # atomic critical section. The per-bucket _lock inside
        # TokenBucket.acquire/refund still guards individual bucket state,
        # but only this outer lock prevents the refund-after-deny race
        # where two threads transiently over-consume the global bucket.
        with self._coarse_lock:
            # Resolve buckets under self._lock so concurrent reset() doesn't
            # race the OrderedDict mutations. Acquisition itself happens
            # outside the inner lock — TokenBucket has its own.
            with self._lock:
                global_bucket = self._get_global_bucket(client_id)
                op_bucket = (
                    self._get_op_bucket(client_id, operation)
                    if operation in self.config.per_operation_limits
                    else None
                )

            # Check global limit first
            if not global_bucket.acquire(cost):
                wait_time = global_bucket.get_wait_time(cost)
                raise OpenZimMcpRateLimitError(
                    f"Rate limit exceeded for operation '{operation}'. "
                    f"Please wait {wait_time:.2f} seconds before retrying.",
                    details=(
                        f"operation={operation}, cost={cost}, "
                        f"wait_time={wait_time:.2f}s"
                    ),
                )

            # Check operation-specific limit if configured
            if op_bucket is not None and not op_bucket.acquire(cost):
                wait_time = op_bucket.get_wait_time(cost)
                # Refund global tokens since we're rejecting
                global_bucket.refund(cost)
                raise OpenZimMcpRateLimitError(
                    f"Per-operation rate limit exceeded for "
                    f"'{operation}'. Please wait {wait_time:.2f} "
                    f"seconds before retrying.",
                    details=(
                        f"operation={operation}, cost={cost}, "
                        f"wait_time={wait_time:.2f}s"
                    ),
                )

            # Mark client as recently used. Done only on full success so
            # denied calls don't count as activity for LRU purposes.
            with self._lock:
                self._touch_client(client_id)

        logger.debug(
            f"Rate limit check passed: client={client_id}, "
            f"operation={operation}, cost={cost}"
        )

    def get_status(self) -> Dict[str, Any]:
        """Get current rate limiter status.

        Returns:
            Dictionary with rate limiter status information.

            For backwards compatibility, ``global_tokens_available`` reports
            the available tokens for the "default" client (if present), and
            ``operation_buckets`` flattens the per-(client, op) view into
            ``"<client_id>:<operation>": tokens``.
        """
        # Snapshot under the lock — reset() clears these under the same
        # lock, and iterating concurrently raises
        # "dictionary changed size during iteration".
        with self._lock:
            operation_buckets = {
                f"{cid}:{op}": bucket.available_tokens
                for (cid, op), bucket in self._buckets.items()
            }
            default_bucket = self._global_buckets.get("default")
            default_tokens = (
                default_bucket.available_tokens
                if default_bucket is not None
                else float(self.config.burst_size)
            )
            client_count = len(self._global_buckets)
        return {
            "enabled": self.config.enabled,
            "global_tokens_available": default_tokens,
            "global_capacity": self.config.burst_size,
            "requests_per_second": self.config.requests_per_second,
            "operation_buckets": operation_buckets,
            "client_count": client_count,
            "max_clients": self._max_clients,
        }

    def reset(self) -> None:
        """Reset all rate limit buckets to full capacity."""
        with self._lock:
            self._buckets.clear()
            self._global_buckets.clear()
        logger.info("Rate limiter reset to full capacity")
