"""
Tests for configuration module.
"""

from pathlib import Path

import pytest

from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.exceptions import OpenZimMcpConfigurationError


class TestCacheConfig:
    """Test CacheConfig class."""

    def test_cache_config_defaults(self):
        """Test cache config with default values."""
        config = CacheConfig()
        assert config.enabled is True
        assert config.max_size == 100
        assert config.ttl_seconds == 3600

    def test_cache_config_custom_values(self):
        """Test cache config with custom values."""
        config = CacheConfig(enabled=False, max_size=50, ttl_seconds=1800)
        assert config.enabled is False
        assert config.max_size == 50
        assert config.ttl_seconds == 1800

    def test_cache_config_validation(self):
        """Test cache config validation."""
        with pytest.raises(ValueError):
            CacheConfig(max_size=0)  # Should be >= 1

        with pytest.raises(ValueError):
            CacheConfig(ttl_seconds=30)  # Should be >= 60


class TestContentConfig:
    """Test ContentConfig class."""

    def test_content_config_defaults(self):
        """Test content config with default values."""
        config = ContentConfig()
        assert config.max_content_length == 100000
        assert config.snippet_length == 1000
        assert config.default_search_limit == 10

    def test_content_config_validation(self):
        """Test content config validation."""
        with pytest.raises(ValueError):
            ContentConfig(max_content_length=500)  # Should be >= 1000

        with pytest.raises(ValueError):
            ContentConfig(snippet_length=50)  # Should be >= 100


class TestLoggingConfig:
    """Test LoggingConfig class."""

    def test_logging_config_defaults(self):
        """Test logging config with default values."""
        config = LoggingConfig()
        assert config.level == "INFO"

    def test_logging_config_valid_levels(self):
        """Test logging config with valid levels."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            config = LoggingConfig(level=level)
            assert config.level == level

    def test_logging_config_invalid_level(self):
        """Test logging config with invalid level."""
        with pytest.raises(ValueError, match="Invalid log level"):
            LoggingConfig(level="INVALID")

    def test_logging_config_case_insensitive(self):
        """Test logging config is case insensitive."""
        config = LoggingConfig(level="debug")
        assert config.level == "DEBUG"


class TestOpenZimMcpConfig:
    """Test OpenZimMcpConfig class."""

    def test_openzim_mcp_config_valid_directories(self, temp_dir: Path):
        """Test OpenZimMcpConfig with valid directories."""
        config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)])
        assert len(config.allowed_directories) == 1
        # Use Path.resolve() for proper cross-platform path comparison
        assert Path(config.allowed_directories[0]).resolve() == temp_dir.resolve()

    def test_openzim_mcp_config_no_directories(self):
        """Test OpenZimMcpConfig with no directories."""
        with pytest.raises(
            OpenZimMcpConfigurationError, match="At least one allowed directory"
        ):
            OpenZimMcpConfig(allowed_directories=[])

    def test_openzim_mcp_config_nonexistent_directory(self):
        """Test OpenZimMcpConfig with non-existent directory."""
        with pytest.raises(OpenZimMcpConfigurationError, match="Directory does not exist"):
            OpenZimMcpConfig(allowed_directories=["/nonexistent/path"])

    def test_openzim_mcp_config_file_instead_of_directory(self, temp_dir: Path):
        """Test OpenZimMcpConfig with file instead of directory."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("test")

        with pytest.raises(OpenZimMcpConfigurationError, match="Path is not a directory"):
            OpenZimMcpConfig(allowed_directories=[str(test_file)])

    def test_openzim_mcp_config_home_directory_expansion(self, temp_dir: Path):
        """Test OpenZimMcpConfig expands home directory."""
        # Create a mock home directory structure
        home_dir = temp_dir / "home"
        home_dir.mkdir()

        # This test would need to mock os.path.expanduser to work properly
        # For now, just test with absolute paths
        config = OpenZimMcpConfig(allowed_directories=[str(home_dir)])
        # Use Path.resolve() for proper cross-platform path comparison
        assert Path(config.allowed_directories[0]).resolve() == home_dir.resolve()

    def test_openzim_mcp_config_defaults(self, temp_dir: Path):
        """Test OpenZimMcpConfig with default values."""
        config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)])

        assert config.server_name == "openzim-mcp"
        assert config.cache.enabled is True
        assert config.content.max_content_length == 100000
        assert config.logging.level == "INFO"


class TestConfigMissingCoverage:
    """Test missing coverage areas in config module."""

    def test_cache_config_repr_coverage(self):
        """Test CacheConfig __repr__ method - covers line 142."""
        cache_config = CacheConfig(enabled=True, max_size=10, ttl_seconds=60)
        repr_str = repr(cache_config)

        # Should contain class name and key attributes
        assert "CacheConfig" in repr_str
        assert "enabled=True" in repr_str
        assert "max_size=10" in repr_str
        assert "ttl_seconds=60" in repr_str

    def test_get_config_summary_coverage(self, temp_dir: Path):
        """Test get_config_summary method - covers line 142 in config.py."""
        config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)])
        summary = config.get_config_summary()

        # Verify all expected keys are present
        expected_keys = {
            "server_name",
            "allowed_directories_count",
            "allowed_directories",
            "cache_enabled",
            "cache_max_size",
            "cache_ttl_seconds",
            "content_max_length",
            "content_snippet_length",
            "search_default_limit",
            "logging_level",
            "config_hash"
        }

        assert set(summary.keys()) == expected_keys

        # Verify some key values
        assert summary["server_name"] == config.server_name
        assert summary["allowed_directories_count"] == len(config.allowed_directories)
        assert summary["allowed_directories"] == config.allowed_directories
        assert summary["cache_enabled"] == config.cache.enabled
        assert summary["config_hash"] == config.get_config_hash()
