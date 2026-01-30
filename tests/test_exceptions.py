"""Tests for exceptions module."""

from openzim_mcp.exceptions import (
    OpenZimMcpArchiveError,
    OpenZimMcpConfigurationError,
    OpenZimMcpError,
    OpenZimMcpFileNotFoundError,
    OpenZimMcpSecurityError,
    OpenZimMcpValidationError,
)


class TestOpenZimMcpExceptions:
    """Test custom exception classes."""

    def test_openzim_mcp_error_base(self):
        """Test base OpenZimMcpError exception."""
        error = OpenZimMcpError("Test message", "Test details")
        assert str(error) == "Test message"
        assert error.message == "Test message"
        assert error.details == "Test details"

    def test_openzim_mcp_error_without_details(self):
        """Test OpenZimMcpError without details."""
        error = OpenZimMcpError("Test message")
        assert str(error) == "Test message"
        assert error.message == "Test message"
        assert error.details is None

    def test_openzim_mcp_security_error(self):
        """Test OpenZimMcpSecurityError inheritance."""
        error = OpenZimMcpSecurityError("Security violation")
        assert isinstance(error, OpenZimMcpError)
        assert str(error) == "Security violation"

    def test_openzim_mcp_validation_error(self):
        """Test OpenZimMcpValidationError inheritance."""
        error = OpenZimMcpValidationError("Validation failed")
        assert isinstance(error, OpenZimMcpError)
        assert str(error) == "Validation failed"

    def test_openzim_mcp_file_not_found_error(self):
        """Test OpenZimMcpFileNotFoundError inheritance."""
        error = OpenZimMcpFileNotFoundError("File not found")
        assert isinstance(error, OpenZimMcpError)
        assert str(error) == "File not found"

    def test_openzim_mcp_archive_error(self):
        """Test OpenZimMcpArchiveError inheritance."""
        error = OpenZimMcpArchiveError("Archive error")
        assert isinstance(error, OpenZimMcpError)
        assert str(error) == "Archive error"

    def test_openzim_mcp_configuration_error(self):
        """Test OpenZimMcpConfigurationError inheritance."""
        error = OpenZimMcpConfigurationError("Configuration error")
        assert isinstance(error, OpenZimMcpError)
        assert str(error) == "Configuration error"

    def test_exception_chaining(self):
        """Test exception chaining works properly."""
        original_error = ValueError("Original error")

        try:
            raise OpenZimMcpError("Wrapped error") from original_error
        except OpenZimMcpError as e:
            assert e.__cause__ == original_error
            assert str(e) == "Wrapped error"
