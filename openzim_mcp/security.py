"""
Security and path validation for OpenZIM MCP server.
"""

import logging
import os
import re
from pathlib import Path
from typing import List

from .constants import ZIM_FILE_EXTENSION
from .exceptions import OpenZimMcpSecurityError, OpenZimMcpValidationError

logger = logging.getLogger(__name__)


class PathValidator:
    """Secure path validation and access control."""

    def __init__(self, allowed_directories: List[str]):
        """
        Initialize path validator with allowed directories.

        Args:
            allowed_directories: List of directories allowed for access

        Raises:
            OpenZimMcpValidationError: If any directory is invalid
        """
        self.allowed_directories = []

        for directory in allowed_directories:
            normalized_path = self._normalize_path(directory)
            resolved_path = Path(normalized_path).resolve()

            if not resolved_path.exists():
                raise OpenZimMcpValidationError(f"Directory does not exist: {resolved_path}")
            if not resolved_path.is_dir():
                raise OpenZimMcpValidationError(f"Path is not a directory: {resolved_path}")

            self.allowed_directories.append(resolved_path)

        logger.info(
            f"Initialized PathValidator with {len(self.allowed_directories)} "
            "allowed directories"
        )

    def _normalize_path(self, filepath: str) -> str:
        """
        Normalize and sanitize file path.

        Args:
            filepath: Path to normalize

        Returns:
            Normalized path string

        Raises:
            OpenZimMcpValidationError: If path contains invalid characters
        """
        if not filepath or not isinstance(filepath, str):
            raise OpenZimMcpValidationError("Path must be a non-empty string")

        # Check for suspicious patterns
        suspicious_patterns = [
            r"\.\./",  # Directory traversal
            r"\.\.\\",  # Windows directory traversal
            r'[<>"|?*]',  # Invalid filename characters (excluding colon for Windows)
            r"[\x00-\x1f]",  # Control characters
        ]

        for pattern in suspicious_patterns:
            if re.search(pattern, filepath):
                raise OpenZimMcpSecurityError(
                    f"Path contains suspicious pattern: {filepath}"
                )

        # Expand home directory and normalize
        if filepath.startswith("~"):
            filepath = os.path.expanduser(filepath)

        return os.path.normpath(filepath)

    def validate_path(self, requested_path: str) -> Path:
        """
        Validate if the requested path is within allowed directories.

        Args:
            requested_path: Path requested for access

        Returns:
            Validated Path object

        Raises:
            OpenZimMcpSecurityError: When path is outside allowed directories
            OpenZimMcpValidationError: When path is invalid
        """
        try:
            normalized_path = self._normalize_path(requested_path)
            resolved_path = Path(normalized_path).resolve()
        except (OSError, ValueError) as e:
            raise OpenZimMcpValidationError(f"Invalid path: {requested_path}") from e

        # Use secure path checking (Python 3.9+)
        is_allowed = any(
            self._is_path_within_directory(resolved_path, allowed_dir)
            for allowed_dir in self.allowed_directories
        )

        if not is_allowed:
            raise OpenZimMcpSecurityError(
                f"Access denied - Path is outside allowed directories: {resolved_path}"
            )

        logger.debug(f"Path validation successful: {resolved_path}")
        return resolved_path

    def _is_path_within_directory(self, path: Path, directory: Path) -> bool:
        """
        Securely check if path is within directory.

        Args:
            path: Path to check
            directory: Directory to check against

        Returns:
            True if path is within directory
        """
        try:
            # Use is_relative_to for secure path checking (Python 3.9+)
            if hasattr(path, "is_relative_to"):
                return path.is_relative_to(directory)
            else:
                # Fallback for older Python versions
                try:
                    path.relative_to(directory)
                    return True
                except ValueError:
                    return False
        except (OSError, ValueError):
            return False

    def validate_zim_file(self, file_path: Path) -> Path:
        """
        Validate that the file is a valid ZIM file.

        Args:
            file_path: Path to validate

        Returns:
            Validated Path object

        Raises:
            OpenZimMcpValidationError: If file is not valid
        """
        if not file_path.exists():
            raise OpenZimMcpValidationError(f"File does not exist: {file_path}")

        if not file_path.is_file():
            raise OpenZimMcpValidationError(f"Path is not a file: {file_path}")

        if file_path.suffix.lower() != ZIM_FILE_EXTENSION:
            raise OpenZimMcpValidationError(f"File is not a ZIM file: {file_path}")

        logger.debug(f"ZIM file validation successful: {file_path}")
        return file_path


def sanitize_input(input_string: str, max_length: int = 1000) -> str:
    """
    Sanitize user input string.

    Args:
        input_string: String to sanitize
        max_length: Maximum allowed length

    Returns:
        Sanitized string

    Raises:
        OpenZimMcpValidationError: If input is invalid
    """
    if not isinstance(input_string, str):
        raise OpenZimMcpValidationError("Input must be a string")

    if len(input_string) > max_length:
        raise OpenZimMcpValidationError(
            f"Input too long: {len(input_string)} > {max_length}"
        )

    # Remove control characters except newlines and tabs
    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", input_string)

    return sanitized.strip()
