"""
Tests for rate_limiter module.
"""

import threading
import time

import pytest

from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.rate_limiter import (
    RateLimitConfig,
    RateLimiter,
    TokenBucket,
)


class TestRateLimitConfig:
    """Test RateLimitConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RateLimitConfig()

        assert config.enabled is True
        assert config.requests_per_second == 10.0
        assert config.burst_size == 20
        assert config.per_operation_limits == {}

    def test_custom_config(self):
        """Test custom configuration values."""
        config = RateLimitConfig(
            enabled=False,
            requests_per_second=5.0,
            burst_size=10,
        )

        assert config.enabled is False
        assert config.requests_per_second == 5.0
        assert config.burst_size == 10

    def test_invalid_requests_per_second(self):
        """Test that non-positive requests_per_second raises error."""
        with pytest.raises(ValueError) as exc_info:
            RateLimitConfig(requests_per_second=0)
        assert "requests_per_second must be positive" in str(exc_info.value)

        with pytest.raises(ValueError):
            RateLimitConfig(requests_per_second=-1)

    def test_invalid_burst_size(self):
        """Test that non-positive burst_size raises error."""
        with pytest.raises(ValueError) as exc_info:
            RateLimitConfig(burst_size=0)
        assert "burst_size must be positive" in str(exc_info.value)

        with pytest.raises(ValueError):
            RateLimitConfig(burst_size=-1)


class TestTokenBucket:
    """Test TokenBucket class."""

    def test_initialization(self):
        """Test token bucket initialization."""
        bucket = TokenBucket(rate=10.0, capacity=20)

        assert bucket.rate == 10.0
        assert bucket.capacity == 20
        assert bucket.tokens == 20.0  # Starts full

    def test_acquire_success(self):
        """Test successful token acquisition."""
        bucket = TokenBucket(rate=10.0, capacity=20)

        assert bucket.acquire(1) is True
        assert bucket.available_tokens < 20

    def test_acquire_multiple_tokens(self):
        """Test acquiring multiple tokens at once."""
        bucket = TokenBucket(rate=10.0, capacity=20)

        assert bucket.acquire(5) is True
        # After acquiring 5 tokens, should have approximately 15 (may refill slightly)
        assert bucket.available_tokens <= 16  # Allow small margin for refill

    def test_acquire_failure_when_empty(self):
        """Test that acquisition fails when tokens are exhausted."""
        bucket = TokenBucket(rate=1.0, capacity=2)

        # Acquire all tokens
        assert bucket.acquire(2) is True
        # Should fail now
        assert bucket.acquire(1) is False

    def test_refund(self):
        """Test token refund."""
        bucket = TokenBucket(rate=10.0, capacity=20)

        # Acquire some tokens
        bucket.acquire(5)
        initial_tokens = bucket.available_tokens

        # Refund tokens
        bucket.refund(3)
        assert bucket.available_tokens >= initial_tokens + 3

    def test_refund_does_not_exceed_capacity(self):
        """Test that refund doesn't exceed capacity."""
        bucket = TokenBucket(rate=10.0, capacity=20)

        # Try to refund more than capacity
        bucket.refund(100)
        assert bucket.available_tokens <= bucket.capacity

    def test_get_wait_time_when_available(self):
        """Test wait time is 0 when tokens are available."""
        bucket = TokenBucket(rate=10.0, capacity=20)

        wait_time = bucket.get_wait_time(1)
        assert wait_time == 0.0

    def test_get_wait_time_when_not_available(self):
        """Test wait time calculation when tokens are not available."""
        bucket = TokenBucket(rate=10.0, capacity=2)

        # Exhaust tokens
        bucket.acquire(2)

        # Calculate wait time for 1 token
        wait_time = bucket.get_wait_time(1)
        assert wait_time > 0
        # With rate=10, 1 token should take ~0.1 seconds
        assert wait_time <= 0.15

    def test_token_refill_over_time(self):
        """Test that tokens refill over time."""
        bucket = TokenBucket(rate=100.0, capacity=10)  # Fast refill for testing

        # Exhaust tokens
        bucket.acquire(10)
        initial_tokens = bucket.available_tokens

        # Wait a short time
        time.sleep(0.05)

        # Should have more tokens now
        assert bucket.available_tokens > initial_tokens

    def test_thread_safety(self):
        """Test that token bucket is thread-safe."""
        bucket = TokenBucket(rate=1000.0, capacity=100)
        results = []

        def acquire_tokens():
            for _ in range(10):
                results.append(bucket.acquire(1))

        threads = [threading.Thread(target=acquire_tokens) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All acquisitions should have been recorded
        assert len(results) == 50
        # Most should have succeeded (bucket had 100 capacity)
        assert sum(results) > 0


class TestRateLimiter:
    """Test RateLimiter class."""

    def test_initialization_default(self):
        """Test rate limiter initialization with defaults."""
        limiter = RateLimiter()

        assert limiter.config.enabled is True
        assert limiter.config.requests_per_second == 10.0
        assert limiter.config.burst_size == 20

    def test_initialization_custom_config(self):
        """Test rate limiter initialization with custom config."""
        config = RateLimitConfig(
            enabled=True,
            requests_per_second=5.0,
            burst_size=10,
        )
        limiter = RateLimiter(config)

        assert limiter.config.requests_per_second == 5.0
        assert limiter.config.burst_size == 10

    def test_check_rate_limit_success(self):
        """Test successful rate limit check."""
        limiter = RateLimiter(RateLimitConfig(burst_size=100))

        # Should not raise
        limiter.check_rate_limit("default")

    def test_check_rate_limit_disabled(self):
        """Test rate limit check when disabled."""
        config = RateLimitConfig(enabled=False, burst_size=1)
        limiter = RateLimiter(config)

        # Should never raise when disabled
        for _ in range(100):
            limiter.check_rate_limit("default")

    def test_check_rate_limit_exceeded(self):
        """Test rate limit exceeded error."""
        config = RateLimitConfig(
            enabled=True,
            requests_per_second=1.0,
            burst_size=2,
        )
        limiter = RateLimiter(config)

        # Exhaust the limit
        limiter.check_rate_limit("default")
        limiter.check_rate_limit("default")

        # Should raise now
        with pytest.raises(OpenZimMcpRateLimitError) as exc_info:
            limiter.check_rate_limit("default")

        assert "Rate limit exceeded" in str(exc_info.value)

    def test_operation_costs(self):
        """Test that different operations have different costs."""
        from openzim_mcp.defaults import RATE_LIMIT_COSTS

        assert "search" in RATE_LIMIT_COSTS
        assert "get_entry" in RATE_LIMIT_COSTS
        assert "default" in RATE_LIMIT_COSTS

        # Search should cost more than default
        assert RATE_LIMIT_COSTS["search"] >= RATE_LIMIT_COSTS["default"]

    def test_per_operation_limits(self):
        """Test per-operation rate limits."""
        op_config = RateLimitConfig(
            requests_per_second=1.0,
            burst_size=1,
        )
        config = RateLimitConfig(
            enabled=True,
            requests_per_second=100.0,
            burst_size=100,
            per_operation_limits={"expensive_op": op_config},
        )
        limiter = RateLimiter(config)

        # First call should succeed
        limiter.check_rate_limit("expensive_op")

        # Second call should fail (per-operation limit)
        with pytest.raises(OpenZimMcpRateLimitError):
            limiter.check_rate_limit("expensive_op")

    def test_get_status(self):
        """Test getting rate limiter status."""
        limiter = RateLimiter()

        status = limiter.get_status()

        assert "enabled" in status
        assert "global_tokens_available" in status
        assert "global_capacity" in status
        assert "requests_per_second" in status
        assert "operation_buckets" in status

    def test_reset(self):
        """Test resetting rate limiter."""
        config = RateLimitConfig(burst_size=5)
        limiter = RateLimiter(config)

        # Consume some tokens
        for _ in range(3):
            limiter.check_rate_limit("default")

        # Verify tokens were consumed before reset
        assert limiter.get_status()["global_tokens_available"] < config.burst_size

        # Reset
        limiter.reset()

        # Should be back to full capacity
        assert limiter.get_status()["global_tokens_available"] == config.burst_size

    def test_rate_limit_error_details(self):
        """Test that rate limit error includes useful details."""
        config = RateLimitConfig(
            enabled=True,
            requests_per_second=1.0,
            burst_size=2,  # Need at least 2 to consume search cost
        )
        limiter = RateLimiter(config)

        # Exhaust the limit (search costs 2 tokens)
        limiter.check_rate_limit("search")

        # Should raise with details
        with pytest.raises(OpenZimMcpRateLimitError) as exc_info:
            limiter.check_rate_limit("search")

        error = exc_info.value
        # Check that error message contains operation info
        assert "search" in str(error)
        # Check details attribute if it exists
        if hasattr(error, "details"):
            assert "search" in error.details


class TestDefaultCosts:
    """Test default operation costs."""

    def test_default_costs_exist(self):
        """Test that all expected operations have costs defined."""
        from openzim_mcp.defaults import RATE_LIMIT_COSTS

        expected_operations = [
            "search",
            "search_with_filters",
            "get_entry",
            "get_binary_entry",
            "browse_namespace",
            "get_metadata",
            "get_structure",
            "suggestions",
            "default",
        ]

        for op in expected_operations:
            assert op in RATE_LIMIT_COSTS, f"Missing cost for operation: {op}"
            assert isinstance(RATE_LIMIT_COSTS[op], int)
            assert RATE_LIMIT_COSTS[op] > 0

    def test_binary_entry_most_expensive(self):
        """Test that binary entry retrieval is the most expensive operation."""
        from openzim_mcp.defaults import RATE_LIMIT_COSTS

        binary_cost = RATE_LIMIT_COSTS["get_binary_entry"]
        for op, cost in RATE_LIMIT_COSTS.items():
            if op != "get_binary_entry":
                assert (
                    cost <= binary_cost
                ), f"{op} should not cost more than get_binary_entry"
