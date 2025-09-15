"""
Tests for security module.
"""

from pathlib import Path

import pytest

from openzim_mcp.exceptions import OpenZimMcpSecurityError, OpenZimMcpValidationError
from openzim_mcp.security import PathValidator, sanitize_input


class TestPathValidator:
    """Test PathValidator class."""

    def test_init_valid_directory(self, temp_dir: Path):
        """Test initialization with valid directory."""
        validator = PathValidator([str(temp_dir)])
        assert len(validator.allowed_directories) == 1
        assert validator.allowed_directories[0] == temp_dir.resolve()

    def test_init_nonexistent_directory(self):
        """Test initialization with non-existent directory."""
        with pytest.raises(OpenZimMcpValidationError, match="Directory does not exist"):
            PathValidator(["/nonexistent/directory"])

    def test_init_file_instead_of_directory(self, temp_dir: Path):
        """Test initialization with file instead of directory."""
        test_file = temp_dir / "test.txt"
        test_file.write_text("test")

        with pytest.raises(OpenZimMcpValidationError, match="Path is not a directory"):
            PathValidator([str(test_file)])

    def test_validate_path_within_allowed(
        self, path_validator: PathValidator, temp_dir: Path
    ):
        """Test validating path within allowed directory."""
        test_file = temp_dir / "test.zim"
        test_file.write_text("test content")

        result = path_validator.validate_path(str(test_file))
        assert result == test_file.resolve()

    def test_validate_path_outside_allowed(self, path_validator: PathValidator):
        """Test validating path outside allowed directory."""
        with pytest.raises(OpenZimMcpSecurityError, match="Access denied"):
            path_validator.validate_path("/etc/passwd")

    def test_validate_path_traversal_attack(
        self, path_validator: PathValidator, temp_dir: Path
    ):
        """Test protection against path traversal attacks."""
        with pytest.raises(OpenZimMcpSecurityError, match="suspicious pattern"):
            path_validator.validate_path(str(temp_dir / "../../../etc/passwd"))

    def test_validate_zim_file_valid(
        self, path_validator: PathValidator, temp_dir: Path
    ):
        """Test validating valid ZIM file."""
        zim_file = temp_dir / "test.zim"
        zim_file.write_text("test content")

        result = path_validator.validate_zim_file(zim_file)
        assert result == zim_file

    def test_validate_zim_file_wrong_extension(
        self, path_validator: PathValidator, temp_dir: Path
    ):
        """Test validating file with wrong extension."""
        txt_file = temp_dir / "test.txt"
        txt_file.write_text("test content")

        with pytest.raises(OpenZimMcpValidationError, match="File is not a ZIM file"):
            path_validator.validate_zim_file(txt_file)

    def test_validate_zim_file_nonexistent(
        self, path_validator: PathValidator, temp_dir: Path
    ):
        """Test validating non-existent file."""
        nonexistent_file = temp_dir / "nonexistent.zim"

        with pytest.raises(OpenZimMcpValidationError, match="File does not exist"):
            path_validator.validate_zim_file(nonexistent_file)


class TestSanitizeInput:
    """Test sanitize_input function."""

    def test_sanitize_normal_string(self):
        """Test sanitizing normal string."""
        result = sanitize_input("Hello, World!")
        assert result == "Hello, World!"

    def test_sanitize_string_with_control_chars(self):
        """Test sanitizing string with control characters."""
        result = sanitize_input("Hello\x00\x01World\x7f")
        assert result == "HelloWorld"

    def test_sanitize_string_too_long(self):
        """Test sanitizing string that's too long."""
        long_string = "a" * 1001
        with pytest.raises(OpenZimMcpValidationError, match="Input too long"):
            sanitize_input(long_string, max_length=1000)

    def test_normalize_path_empty_string(self, temp_dir: Path):
        """Test _normalize_path with empty string."""
        validator = PathValidator([str(temp_dir)])
        with pytest.raises(
            OpenZimMcpValidationError, match="Path must be a non-empty string"
        ):
            validator._normalize_path("")

    def test_normalize_path_none_input(self, temp_dir: Path):
        """Test _normalize_path with None input."""
        validator = PathValidator([str(temp_dir)])
        with pytest.raises(
            OpenZimMcpValidationError, match="Path must be a non-empty string"
        ):
            validator._normalize_path(None)  # type: ignore

    def test_normalize_path_with_home_directory(self, temp_dir: Path):
        """Test _normalize_path with home directory expansion."""
        validator = PathValidator([str(temp_dir)])
        # Test with ~ path (this should trigger line 80)
        import os
        import platform

        # Handle both Unix (HOME) and Windows (USERPROFILE) environment variables
        if platform.system() == "Windows":
            env_var = "USERPROFILE"
        else:
            env_var = "HOME"

        original_home = os.environ.get(env_var)
        try:
            os.environ[env_var] = str(temp_dir)
            result = validator._normalize_path("~/test")
            # Use Path.resolve() for proper cross-platform path comparison
            assert Path(result).resolve().is_relative_to(temp_dir.resolve())
        finally:
            if original_home:
                os.environ[env_var] = original_home
            elif env_var in os.environ:
                del os.environ[env_var]

    def test_validate_path_with_os_error(self, temp_dir: Path):
        """Test validate_path when OSError occurs during path resolution."""
        validator = PathValidator([str(temp_dir)])

        # Mock Path.resolve to raise OSError
        from unittest.mock import patch

        with patch("pathlib.Path.resolve", side_effect=OSError("Test error")):
            with pytest.raises(OpenZimMcpValidationError, match="Invalid path"):
                validator.validate_path("valid_path")

    def test_is_path_within_directory_exception_handling(self, temp_dir: Path):
        """Test _is_path_within_directory exception handling."""
        validator = PathValidator([str(temp_dir)])

        # Create a mock Path that raises an exception
        from unittest.mock import MagicMock

        mock_path = MagicMock()
        mock_path.is_relative_to.side_effect = OSError("Test error")
        mock_path.relative_to.side_effect = OSError("Test error")

        # This should return False when exceptions occur (line 140-141)
        result = validator._is_path_within_directory(mock_path, temp_dir)
        assert result is False

    def test_sanitize_non_string_input(self):
        """Test sanitizing non-string input."""
        with pytest.raises(OpenZimMcpValidationError, match="Input must be a string"):
            sanitize_input(123)

    def test_sanitize_preserves_newlines_and_tabs(self):
        """Test that sanitization preserves newlines and tabs."""
        result = sanitize_input("Hello\nWorld\tTest")
        assert result == "Hello\nWorld\tTest"
