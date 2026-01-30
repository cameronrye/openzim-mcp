"""Tests for defaults module."""

import pytest

from openzim_mcp.defaults import (
    CACHE,
    CACHE_PERFORMANCE,
    CONTENT,
    INPUT_LIMITS,
    NAMESPACE_SAMPLING,
    RATE_LIMIT,
    RATE_LIMIT_COSTS,
    SERVER,
    TIMEOUTS,
    TOOL_MODE_ADVANCED,
    TOOL_MODE_SIMPLE,
    UNWANTED_HTML_SELECTORS,
    VALID_TOOL_MODES,
    VALID_TRANSPORT_TYPES,
    ZIM_FILE_EXTENSION,
    CacheDefaults,
    CachePerformanceThresholds,
    ContentDefaults,
    InputLimitDefaults,
    NamespaceSamplingDefaults,
    RateLimitDefaults,
    ServerDefaults,
    TimeoutDefaults,
)


class TestCacheDefaults:
    """Test CacheDefaults dataclass."""

    def test_cache_defaults_values(self):
        """Test cache default values."""
        assert CacheDefaults.ENABLED is True
        assert CacheDefaults.MAX_SIZE == 100
        assert CacheDefaults.TTL_SECONDS == 3600
        assert CacheDefaults.PERSISTENCE_ENABLED is False
        assert CacheDefaults.PERSISTENCE_PATH == ".openzim_mcp_cache"

    def test_cache_instance(self):
        """Test CACHE instance has correct values."""
        assert CACHE.ENABLED is True
        assert CACHE.MAX_SIZE == 100
        assert CACHE.TTL_SECONDS == 3600

    def test_cache_dataclass_frozen(self):
        """Test that CacheDefaults is frozen (immutable)."""
        with pytest.raises(AttributeError):
            CACHE.ENABLED = False  # type: ignore


class TestContentDefaults:
    """Test ContentDefaults dataclass."""

    def test_content_defaults_values(self):
        """Test content default values."""
        assert ContentDefaults.SNIPPET_LENGTH == 1000
        assert ContentDefaults.MAX_CONTENT_LENGTH == 100000
        assert ContentDefaults.SEARCH_LIMIT == 10
        assert ContentDefaults.MAX_BINARY_SIZE == 10_000_000
        assert ContentDefaults.MAIN_PAGE_TRUNCATION == 5000

    def test_content_instance(self):
        """Test CONTENT instance has correct values."""
        assert CONTENT.SNIPPET_LENGTH == 1000
        assert CONTENT.MAX_CONTENT_LENGTH == 100000
        assert CONTENT.SEARCH_LIMIT == 10


class TestRateLimitDefaults:
    """Test RateLimitDefaults dataclass."""

    def test_rate_limit_defaults_values(self):
        """Test rate limit default values."""
        assert RateLimitDefaults.ENABLED is True
        assert RateLimitDefaults.REQUESTS_PER_SECOND == 10.0
        assert RateLimitDefaults.BURST_SIZE == 20

    def test_rate_limit_instance(self):
        """Test RATE_LIMIT instance has correct values."""
        assert RATE_LIMIT.ENABLED is True
        assert RATE_LIMIT.REQUESTS_PER_SECOND == 10.0
        assert RATE_LIMIT.BURST_SIZE == 20


class TestInputLimitDefaults:
    """Test InputLimitDefaults dataclass."""

    def test_input_limit_defaults_values(self):
        """Test input limit default values."""
        assert InputLimitDefaults.FILE_PATH == 1000
        assert InputLimitDefaults.QUERY == 500
        assert InputLimitDefaults.ENTRY_PATH == 500
        assert InputLimitDefaults.NAMESPACE == 100
        assert InputLimitDefaults.CONTENT_TYPE == 100
        assert InputLimitDefaults.PARTIAL_QUERY == 200
        assert InputLimitDefaults.NAMESPACE_MAX_LENGTH == 50

    def test_input_limits_instance(self):
        """Test INPUT_LIMITS instance has correct values."""
        assert INPUT_LIMITS.FILE_PATH == 1000
        assert INPUT_LIMITS.QUERY == 500


class TestCachePerformanceThresholds:
    """Test CachePerformanceThresholds dataclass."""

    def test_cache_performance_thresholds_values(self):
        """Test cache performance threshold values."""
        assert CachePerformanceThresholds.LOW_HIT_RATE == 0.3
        assert CachePerformanceThresholds.HIGH_HIT_RATE == 0.8

    def test_thresholds_are_valid(self):
        """Test that thresholds are in valid range."""
        assert 0 <= CACHE_PERFORMANCE.LOW_HIT_RATE <= 1
        assert 0 <= CACHE_PERFORMANCE.HIGH_HIT_RATE <= 1
        assert CACHE_PERFORMANCE.LOW_HIT_RATE < CACHE_PERFORMANCE.HIGH_HIT_RATE


class TestNamespaceSamplingDefaults:
    """Test NamespaceSamplingDefaults dataclass."""

    def test_namespace_sampling_defaults_values(self):
        """Test namespace sampling default values."""
        assert NamespaceSamplingDefaults.MAX_SAMPLE_SIZE == 1000
        assert NamespaceSamplingDefaults.MAX_NAMESPACE_ENTRIES == 200
        assert NamespaceSamplingDefaults.MAX_SAMPLE_ATTEMPTS_MULTIPLIER == 3

    def test_namespace_sampling_instance(self):
        """Test NAMESPACE_SAMPLING instance has correct values."""
        assert NAMESPACE_SAMPLING.MAX_SAMPLE_SIZE == 1000
        assert NAMESPACE_SAMPLING.MAX_NAMESPACE_ENTRIES == 200


class TestTimeoutDefaults:
    """Test TimeoutDefaults dataclass."""

    def test_timeout_defaults_values(self):
        """Test timeout default values."""
        assert TimeoutDefaults.REGEX_SECONDS == 1.0
        assert TimeoutDefaults.ARCHIVE_OPEN_SECONDS == 30.0

    def test_timeouts_instance(self):
        """Test TIMEOUTS instance has correct values."""
        assert TIMEOUTS.REGEX_SECONDS == 1.0
        assert TIMEOUTS.ARCHIVE_OPEN_SECONDS == 30.0


class TestServerDefaults:
    """Test ServerDefaults dataclass."""

    def test_server_defaults_values(self):
        """Test server default values."""
        assert ServerDefaults.NAME == "openzim-mcp"
        assert ServerDefaults.TOOL_MODE == "simple"
        assert ServerDefaults.LOG_LEVEL == "INFO"
        assert "%(asctime)s" in ServerDefaults.LOG_FORMAT

    def test_server_instance(self):
        """Test SERVER instance has correct values."""
        assert SERVER.NAME == "openzim-mcp"
        assert SERVER.TOOL_MODE == "simple"


class TestToolModeConstants:
    """Test tool mode constants."""

    def test_tool_mode_values(self):
        """Test tool mode constant values."""
        assert TOOL_MODE_ADVANCED == "advanced"
        assert TOOL_MODE_SIMPLE == "simple"

    def test_valid_tool_modes_set(self):
        """Test VALID_TOOL_MODES contains expected values."""
        assert TOOL_MODE_ADVANCED in VALID_TOOL_MODES
        assert TOOL_MODE_SIMPLE in VALID_TOOL_MODES
        assert len(VALID_TOOL_MODES) == 2


class TestFileConstants:
    """Test file-related constants."""

    def test_zim_file_extension(self):
        """Test ZIM file extension constant."""
        assert ZIM_FILE_EXTENSION == ".zim"


class TestTransportTypes:
    """Test transport type constants."""

    def test_valid_transport_types(self):
        """Test valid transport types set."""
        assert "stdio" in VALID_TRANSPORT_TYPES
        assert "sse" in VALID_TRANSPORT_TYPES
        assert "streamable-http" in VALID_TRANSPORT_TYPES
        assert len(VALID_TRANSPORT_TYPES) == 3


class TestUnwantedHtmlSelectors:
    """Test unwanted HTML selectors list."""

    def test_unwanted_selectors_exist(self):
        """Test that unwanted selectors list is populated."""
        assert len(UNWANTED_HTML_SELECTORS) > 0
        assert "script" in UNWANTED_HTML_SELECTORS
        assert "style" in UNWANTED_HTML_SELECTORS

    def test_expected_selectors_present(self):
        """Test that expected selectors are present."""
        expected = ["script", "style", "meta", "link", "head", "footer"]
        for selector in expected:
            assert selector in UNWANTED_HTML_SELECTORS


class TestRateLimitCosts:
    """Test rate limit costs dictionary."""

    def test_rate_limit_costs_exist(self):
        """Test that rate limit costs are defined."""
        assert len(RATE_LIMIT_COSTS) > 0

    def test_expected_operations_have_costs(self):
        """Test that expected operations have costs."""
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
            assert op in RATE_LIMIT_COSTS
            assert isinstance(RATE_LIMIT_COSTS[op], int)
            assert RATE_LIMIT_COSTS[op] > 0

    def test_cost_values_are_reasonable(self):
        """Test that cost values are in a reasonable range."""
        for op, cost in RATE_LIMIT_COSTS.items():
            assert 1 <= cost <= 10, f"Cost for {op} should be between 1 and 10"

    def test_binary_entry_has_highest_cost(self):
        """Test that binary entry has the highest cost."""
        max_cost = max(RATE_LIMIT_COSTS.values())
        assert RATE_LIMIT_COSTS["get_binary_entry"] == max_cost
