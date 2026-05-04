"""Tests for configuration module."""

import json
import tempfile
from pathlib import Path

import pytest
from pydantic import SecretStr

from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.exceptions import OpenZimMcpConfigurationError

# Use the platform's tempdir so allowed_directories validation passes on
# Windows runners where "/tmp" resolves to "D:\tmp" (not present).
TMP_DIR = tempfile.gettempdir()


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

    def test_persistence_path_defaults_to_absolute_under_user_cache(self):
        """Default persistence_path lives under ~/.cache so it's CWD-independent."""
        config = CacheConfig()
        path = Path(config.persistence_path)
        assert path.is_absolute(), f"default persistence_path is not absolute: {path}"
        # Default lives under the platform's user cache directory.
        expected = (Path.home() / ".cache" / "openzim-mcp").resolve()
        assert path == expected

    def test_persistence_path_is_normalized_to_absolute(self, tmp_path, monkeypatch):
        """User-supplied relative paths are resolved to an absolute path."""
        monkeypatch.chdir(tmp_path)
        config = CacheConfig(persistence_path="my_cache")
        path = Path(config.persistence_path)
        assert path.is_absolute()
        assert path == (tmp_path / "my_cache").resolve()

    def test_persistence_path_expands_tilde(self):
        """Tilde in persistence_path is expanded."""
        config = CacheConfig(persistence_path="~/some-cache")
        path = Path(config.persistence_path)
        assert path.is_absolute()
        assert "~" not in str(path)
        assert path == (Path.home() / "some-cache").resolve()


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
            ContentConfig(max_content_length=50)  # Should be >= 100

        # 100 is now the floor (lowered from 1000 to enable short previews).
        ContentConfig(max_content_length=100)

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
        with pytest.raises(
            OpenZimMcpConfigurationError, match="Directory does not exist"
        ):
            OpenZimMcpConfig(allowed_directories=["/nonexistent/path"])

    def test_openzim_mcp_config_file_instead_of_directory(self, temp_dir: Path):
        """Test OpenZimMcpConfig with file instead of directory."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("test")

        with pytest.raises(
            OpenZimMcpConfigurationError, match="Path is not a directory"
        ):
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


def test_config_defaults_to_stdio_transport():
    """Default transport is stdio when not specified."""
    from openzim_mcp.config import OpenZimMcpConfig

    cfg = OpenZimMcpConfig(allowed_directories=[TMP_DIR])
    assert cfg.transport == "stdio"


def test_config_accepts_http_transport():
    """Transport accepts 'http' value."""
    from openzim_mcp.config import OpenZimMcpConfig

    cfg = OpenZimMcpConfig(allowed_directories=[TMP_DIR], transport="http")
    assert cfg.transport == "http"


def test_config_accepts_sse_transport():
    """Transport accepts 'sse' value."""
    from openzim_mcp.config import OpenZimMcpConfig

    cfg = OpenZimMcpConfig(allowed_directories=[TMP_DIR], transport="sse")
    assert cfg.transport == "sse"


def test_config_rejects_invalid_transport():
    """Transport rejects values outside the Literal."""
    from openzim_mcp.config import OpenZimMcpConfig

    with pytest.raises(ValueError):
        OpenZimMcpConfig(allowed_directories=[TMP_DIR], transport="websocket")


def test_config_default_host_and_port():
    """Default host is loopback and default port is 8000."""
    from openzim_mcp.config import OpenZimMcpConfig

    cfg = OpenZimMcpConfig(allowed_directories=[TMP_DIR])
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8000


def test_config_rejects_port_out_of_range():
    """Port must be within 1..65535."""
    from openzim_mcp.config import OpenZimMcpConfig

    with pytest.raises(ValueError):
        OpenZimMcpConfig(allowed_directories=[TMP_DIR], port=70000)
    with pytest.raises(ValueError):
        OpenZimMcpConfig(allowed_directories=[TMP_DIR], port=0)


def test_config_default_auth_token_is_none():
    """Default auth_token is None."""
    from openzim_mcp.config import OpenZimMcpConfig

    cfg = OpenZimMcpConfig(allowed_directories=[TMP_DIR])
    assert cfg.auth_token is None


def test_config_auth_token_is_secret():
    """auth_token must use SecretStr to avoid leaking in repr/logs."""
    from openzim_mcp.config import OpenZimMcpConfig

    cfg = OpenZimMcpConfig(allowed_directories=[TMP_DIR], auth_token="abc123")
    assert isinstance(cfg.auth_token, SecretStr)
    assert "abc123" not in repr(cfg)
    assert cfg.auth_token.get_secret_value() == "abc123"


def test_config_default_cors_origins_empty():
    """Default cors_origins is an empty list."""
    from openzim_mcp.config import OpenZimMcpConfig

    cfg = OpenZimMcpConfig(allowed_directories=[TMP_DIR])
    assert cfg.cors_origins == []


def test_config_rejects_wildcard_cors():
    """Wildcard '*' rejected at startup as a footgun."""
    from openzim_mcp.config import OpenZimMcpConfig

    with pytest.raises(OpenZimMcpConfigurationError):
        OpenZimMcpConfig(allowed_directories=[TMP_DIR], cors_origins=["*"])


def test_config_default_allowed_hosts_empty():
    """Default allowed_hosts is an empty list."""
    from openzim_mcp.config import OpenZimMcpConfig

    cfg = OpenZimMcpConfig(allowed_directories=[TMP_DIR])
    assert cfg.allowed_hosts == []


def test_config_rejects_wildcard_allowed_hosts():
    """Wildcard '*' rejected at startup as a footgun.

    The point of an allow-list is DNS rebinding protection; accepting
    '*' would defeat it.
    """
    from openzim_mcp.config import OpenZimMcpConfig

    with pytest.raises(OpenZimMcpConfigurationError):
        OpenZimMcpConfig(allowed_directories=[TMP_DIR], allowed_hosts=["*"])


def test_config_rejects_wildcard_allowed_hosts_with_padding():
    """Whitespace-padded ' * ' is also rejected (mirrors cors_origins)."""
    from openzim_mcp.config import OpenZimMcpConfig

    with pytest.raises(OpenZimMcpConfigurationError):
        OpenZimMcpConfig(allowed_directories=[TMP_DIR], allowed_hosts=[" * "])


def test_config_hash_includes_allowed_hosts():
    """allowed_hosts changes alter the config hash (used for conflict detection)."""
    from openzim_mcp.config import OpenZimMcpConfig

    base = OpenZimMcpConfig(allowed_directories=[TMP_DIR])
    extended = OpenZimMcpConfig(
        allowed_directories=[TMP_DIR],
        allowed_hosts=["mcp.example.com"],
    )
    assert base.get_config_hash() != extended.get_config_hash()


def test_config_default_watch_interval():
    """Default watch_interval_seconds is 5."""
    from openzim_mcp.config import OpenZimMcpConfig

    cfg = OpenZimMcpConfig(allowed_directories=[TMP_DIR])
    assert cfg.watch_interval_seconds == 5


def test_config_rejects_watch_interval_out_of_range():
    """watch_interval_seconds must be in [1, 60]."""
    from openzim_mcp.config import OpenZimMcpConfig

    with pytest.raises(ValueError):
        OpenZimMcpConfig(allowed_directories=[TMP_DIR], watch_interval_seconds=0)
    with pytest.raises(ValueError):
        OpenZimMcpConfig(allowed_directories=[TMP_DIR], watch_interval_seconds=120)


def test_config_default_subscriptions_enabled():
    """Default subscriptions_enabled is True."""
    from openzim_mcp.config import OpenZimMcpConfig

    cfg = OpenZimMcpConfig(allowed_directories=[TMP_DIR])
    assert cfg.subscriptions_enabled is True


def test_per_operation_limits_round_trip_through_env_vars(monkeypatch):
    """per_operation_limits must be reachable from env-var/JSON config (M4)."""
    from openzim_mcp.config import OpenZimMcpConfig

    monkeypatch.setenv("OPENZIM_MCP_ALLOWED_DIRECTORIES", json.dumps([TMP_DIR]))
    monkeypatch.setenv(
        "OPENZIM_MCP_RATE_LIMIT__PER_OPERATION_LIMITS",
        '{"search": {"requests_per_second": 1.0, "burst_size": 1}}',
    )
    cfg = OpenZimMcpConfig()
    assert "search" in cfg.rate_limit.per_operation_limits
    op_cfg = cfg.rate_limit.per_operation_limits["search"]
    assert op_cfg.requests_per_second == pytest.approx(1.0)
    assert op_cfg.burst_size == 1


def test_rate_limit_config_is_single_class():
    """Verify RateLimitConfig is a single class (M4).

    The class exposed via openzim_mcp.config and openzim_mcp.rate_limiter
    must be the same object so per_operation_limits is reachable from
    env-var/JSON config.
    """
    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.config import RateLimitConfig as ConfigRateLimitConfig
    from openzim_mcp.rate_limiter import RateLimitConfig as RLRateLimitConfig

    assert ConfigRateLimitConfig is RLRateLimitConfig
    cfg = OpenZimMcpConfig(allowed_directories=[TMP_DIR])
    assert isinstance(cfg.rate_limit, RLRateLimitConfig)


def test_rate_limit_config_per_operation_limits_default_empty():
    """Default per_operation_limits is an empty dict, not None."""
    from openzim_mcp.config import OpenZimMcpConfig

    cfg = OpenZimMcpConfig(allowed_directories=[TMP_DIR])
    assert cfg.rate_limit.per_operation_limits == {}
