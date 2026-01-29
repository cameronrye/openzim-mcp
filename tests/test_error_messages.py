"""
Tests for error_messages module.
"""

import pytest

from openzim_mcp.error_messages import (
    ERROR_CONFIGS,
    GENERIC_ERROR_TEMPLATE,
    NOT_FOUND_ERROR_CONFIG,
    PERMISSION_ERROR_CONFIG,
    ErrorConfig,
    format_error_message,
    format_generic_error,
    get_error_config,
)
from openzim_mcp.exceptions import (
    OpenZimMcpArchiveError,
    OpenZimMcpFileNotFoundError,
    OpenZimMcpRateLimitError,
    OpenZimMcpSecurityError,
    OpenZimMcpValidationError,
)


class TestErrorConfig:
    """Test ErrorConfig dataclass."""

    def test_error_config_creation(self):
        """Test ErrorConfig creation."""
        config = ErrorConfig(
            title="Test Error",
            issue="Something went wrong",
            steps=["Step 1", "Step 2"],
        )

        assert config.title == "Test Error"
        assert config.issue == "Something went wrong"
        assert len(config.steps) == 2

    def test_error_config_frozen(self):
        """Test that ErrorConfig is frozen (immutable)."""
        config = ErrorConfig(
            title="Test",
            issue="Issue",
            steps=["Step"],
        )

        with pytest.raises(AttributeError):
            config.title = "New Title"  # type: ignore


class TestErrorConfigs:
    """Test ERROR_CONFIGS dictionary."""

    def test_file_not_found_config_exists(self):
        """Test FileNotFoundError config exists."""
        assert OpenZimMcpFileNotFoundError in ERROR_CONFIGS
        config = ERROR_CONFIGS[OpenZimMcpFileNotFoundError]
        assert "File Not Found" in config.title
        assert len(config.steps) > 0

    def test_archive_error_config_exists(self):
        """Test ArchiveError config exists."""
        assert OpenZimMcpArchiveError in ERROR_CONFIGS
        config = ERROR_CONFIGS[OpenZimMcpArchiveError]
        assert "Archive" in config.title
        assert len(config.steps) > 0

    def test_security_error_config_exists(self):
        """Test SecurityError config exists."""
        assert OpenZimMcpSecurityError in ERROR_CONFIGS
        config = ERROR_CONFIGS[OpenZimMcpSecurityError]
        assert "Security" in config.title
        assert len(config.steps) > 0

    def test_validation_error_config_exists(self):
        """Test ValidationError config exists."""
        assert OpenZimMcpValidationError in ERROR_CONFIGS
        config = ERROR_CONFIGS[OpenZimMcpValidationError]
        assert "Validation" in config.title
        assert len(config.steps) > 0

    def test_rate_limit_error_config_exists(self):
        """Test RateLimitError config exists."""
        assert OpenZimMcpRateLimitError in ERROR_CONFIGS
        config = ERROR_CONFIGS[OpenZimMcpRateLimitError]
        assert "Rate Limit" in config.title
        assert len(config.steps) > 0


class TestSpecialErrorConfigs:
    """Test special error configurations."""

    def test_permission_error_config(self):
        """Test PERMISSION_ERROR_CONFIG."""
        assert PERMISSION_ERROR_CONFIG.title == "Permission Error"
        assert "permission" in PERMISSION_ERROR_CONFIG.issue.lower()
        assert len(PERMISSION_ERROR_CONFIG.steps) > 0

    def test_not_found_error_config(self):
        """Test NOT_FOUND_ERROR_CONFIG."""
        assert NOT_FOUND_ERROR_CONFIG.title == "Resource Not Found"
        assert "not" in NOT_FOUND_ERROR_CONFIG.issue.lower()
        assert len(NOT_FOUND_ERROR_CONFIG.steps) > 0


class TestGenericErrorTemplate:
    """Test generic error template."""

    def test_generic_error_template_has_placeholders(self):
        """Test that generic error template has expected placeholders."""
        assert "{operation}" in GENERIC_ERROR_TEMPLATE
        assert "{error_type}" in GENERIC_ERROR_TEMPLATE
        assert "{context}" in GENERIC_ERROR_TEMPLATE
        assert "{details}" in GENERIC_ERROR_TEMPLATE

    def test_generic_error_template_structure(self):
        """Test generic error template structure."""
        assert "**Operation Failed**" in GENERIC_ERROR_TEMPLATE
        assert "**Troubleshooting Steps**" in GENERIC_ERROR_TEMPLATE
        assert "**Technical Details**" in GENERIC_ERROR_TEMPLATE


class TestFormatErrorMessage:
    """Test format_error_message function."""

    def test_format_error_message_basic(self):
        """Test basic error message formatting."""
        config = ErrorConfig(
            title="Test Error",
            issue="Test issue description",
            steps=["First step", "Second step"],
        )

        result = format_error_message(
            config=config,
            operation="test operation",
            context="test context",
            details="test details",
        )

        assert "**Test Error**" in result
        assert "test operation" in result
        assert "Test issue description" in result
        assert "test context" in result
        assert "First step" in result
        assert "Second step" in result
        assert "test details" in result

    def test_format_error_message_numbered_steps(self):
        """Test that steps are numbered."""
        config = ErrorConfig(
            title="Error",
            issue="Issue",
            steps=["Step A", "Step B", "Step C"],
        )

        result = format_error_message(
            config=config,
            operation="op",
            context="ctx",
            details="det",
        )

        assert "1. Step A" in result
        assert "2. Step B" in result
        assert "3. Step C" in result


class TestFormatGenericError:
    """Test format_generic_error function."""

    def test_format_generic_error_basic(self):
        """Test basic generic error formatting."""
        result = format_generic_error(
            operation="test operation",
            error_type="TestError",
            context="test context",
            details="test details",
        )

        assert "test operation" in result
        assert "TestError" in result
        assert "test context" in result
        assert "test details" in result

    def test_format_generic_error_includes_troubleshooting(self):
        """Test that generic error includes troubleshooting steps."""
        result = format_generic_error(
            operation="op",
            error_type="type",
            context="ctx",
            details="det",
        )

        assert "Troubleshooting" in result
        assert "diagnose_server_state" in result


class TestGetErrorConfig:
    """Test get_error_config function."""

    def test_get_error_config_exact_match(self):
        """Test getting config for exact exception type."""
        error = OpenZimMcpFileNotFoundError("Test")
        config = get_error_config(error)

        assert config is not None
        assert "File Not Found" in config.title

    def test_get_error_config_archive_error(self):
        """Test getting config for archive error."""
        error = OpenZimMcpArchiveError("Archive failed")
        config = get_error_config(error)

        assert config is not None
        assert "Archive" in config.title

    def test_get_error_config_security_error(self):
        """Test getting config for security error."""
        error = OpenZimMcpSecurityError("Security violation")
        config = get_error_config(error)

        assert config is not None
        assert "Security" in config.title

    def test_get_error_config_validation_error(self):
        """Test getting config for validation error."""
        error = OpenZimMcpValidationError("Invalid input")
        config = get_error_config(error)

        assert config is not None
        assert "Validation" in config.title

    def test_get_error_config_rate_limit_error(self):
        """Test getting config for rate limit error."""
        error = OpenZimMcpRateLimitError("Too many requests")
        config = get_error_config(error)

        assert config is not None
        assert "Rate Limit" in config.title

    def test_get_error_config_permission_pattern(self):
        """Test getting config for permission error pattern."""
        error = Exception("Permission denied accessing file")
        config = get_error_config(error)

        assert config is not None
        assert config == PERMISSION_ERROR_CONFIG

    def test_get_error_config_access_pattern(self):
        """Test getting config for access error pattern."""
        error = Exception("Access denied to resource")
        config = get_error_config(error)

        assert config is not None
        assert config == PERMISSION_ERROR_CONFIG

    def test_get_error_config_not_found_pattern(self):
        """Test getting config for not found error pattern."""
        error = Exception("Resource not found")
        config = get_error_config(error)

        assert config is not None
        assert config == NOT_FOUND_ERROR_CONFIG

    def test_get_error_config_does_not_exist_pattern(self):
        """Test getting config for does not exist error pattern."""
        error = Exception("File does not exist")
        config = get_error_config(error)

        assert config is not None
        assert config == NOT_FOUND_ERROR_CONFIG

    def test_get_error_config_unknown_error(self):
        """Test getting config for unknown error type."""
        error = Exception("Some random error")
        config = get_error_config(error)

        assert config is None

    def test_get_error_config_case_insensitive(self):
        """Test that pattern matching is case insensitive."""
        error = Exception("PERMISSION DENIED")
        config = get_error_config(error)

        assert config is not None
        assert config == PERMISSION_ERROR_CONFIG


class TestErrorConfigSteps:
    """Test that error configs have useful steps."""

    def test_file_not_found_steps_are_actionable(self):
        """Test that file not found steps are actionable."""
        config = ERROR_CONFIGS[OpenZimMcpFileNotFoundError]

        # Should mention checking the path
        steps_text = " ".join(config.steps).lower()
        assert "path" in steps_text or "file" in steps_text

    def test_archive_error_steps_mention_diagnostics(self):
        """Test that archive error steps mention diagnostics."""
        config = ERROR_CONFIGS[OpenZimMcpArchiveError]

        steps_text = " ".join(config.steps).lower()
        # Should mention some form of verification or diagnostics
        assert (
            "verify" in steps_text or "check" in steps_text or "diagnose" in steps_text
        )

    def test_security_error_steps_mention_paths(self):
        """Test that security error steps mention paths."""
        config = ERROR_CONFIGS[OpenZimMcpSecurityError]

        steps_text = " ".join(config.steps).lower()
        assert "path" in steps_text or "directory" in steps_text

    def test_rate_limit_steps_mention_waiting(self):
        """Test that rate limit error steps mention waiting."""
        config = ERROR_CONFIGS[OpenZimMcpRateLimitError]

        steps_text = " ".join(config.steps).lower()
        assert "wait" in steps_text or "retry" in steps_text
