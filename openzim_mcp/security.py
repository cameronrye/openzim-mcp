"""Security and path validation for OpenZIM MCP server."""

import contextlib
import logging
import os
import re
from pathlib import Path
from typing import List
from urllib.parse import unquote

from .constants import ZIM_FILE_EXTENSION
from .exceptions import OpenZimMcpSecurityError, OpenZimMcpValidationError

logger = logging.getLogger(__name__)

# Maximum allowed path length to prevent buffer exhaustion attacks
MAX_PATH_LENGTH = 4096

# Placeholder for hidden/sanitized paths in error messages
PATH_HIDDEN_PLACEHOLDER = "<path-hidden>"
NO_PATH_PLACEHOLDER = "<no-path>"


class PathValidator:
    """Secure path validation and access control."""

    def __init__(self, allowed_directories: List[str]):
        """Initialize path validator with allowed directories.

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
                raise OpenZimMcpValidationError(
                    f"Directory does not exist: {resolved_path}"
                )
            if not resolved_path.is_dir():
                raise OpenZimMcpValidationError(
                    f"Path is not a directory: {resolved_path}"
                )

            self.allowed_directories.append(resolved_path)

        logger.info(
            f"Initialized PathValidator with {len(self.allowed_directories)} "
            "allowed directories"
        )

    def _normalize_path(self, filepath: str) -> str:
        """Normalize and sanitize file path.

        Args:
            filepath: Path to normalize

        Returns:
            Normalized path string

        Raises:
            OpenZimMcpValidationError: If path contains invalid characters or
                exceeds length limit
            OpenZimMcpSecurityError: If path contains traversal attempts
        """
        if not filepath or not isinstance(filepath, str):
            raise OpenZimMcpValidationError("Path must be a non-empty string")

        # Check path length to prevent buffer exhaustion attacks
        if len(filepath) > MAX_PATH_LENGTH:
            raise OpenZimMcpValidationError(
                f"Path too long: {len(filepath)} chars exceeds max {MAX_PATH_LENGTH}"
            )

        # URL-decode the path to catch encoded traversal attempts (%2e%2e, %2f, etc.)
        # We decode multiple times to handle double-encoding attacks
        decoded_path = filepath
        for _ in range(3):  # Handle up to triple encoding
            new_decoded = unquote(decoded_path)
            if new_decoded == decoded_path:
                break
            decoded_path = new_decoded

        # Check for suspicious patterns in both original and decoded paths
        suspicious_patterns = [
            r"\.\./",  # Directory traversal (Unix)
            r"\.\.\\",  # Directory traversal (Windows)
            r"\.\.$",  # Trailing ..
            r"^\.\.",  # Leading ..
            r'[<>"|?*]',  # Invalid filename characters (excluding colon for Windows)
            r"[\x00-\x1f]",  # Control characters
        ]

        # Check both original and decoded path for traversal attempts
        for path_to_check in [filepath, decoded_path]:
            for pattern in suspicious_patterns:
                if re.search(pattern, path_to_check):
                    raise OpenZimMcpSecurityError(
                        f"Path contains suspicious pattern: {filepath}"
                    )

        # Expand home directory and normalize
        if filepath.startswith("~"):
            filepath = os.path.expanduser(filepath)

        return os.path.normpath(filepath)

    def validate_path(self, requested_path: str) -> Path:
        """Validate if the requested path is within allowed directories.

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
        """Securely check if path is within directory.

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
        """Validate that the file is a valid ZIM file.

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


def sanitize_input(
    input_string: str, max_length: int = 1000, allow_empty: bool = False
) -> str:
    """Sanitize user input string.

    Args:
        input_string: String to sanitize
        max_length: Maximum allowed length
        allow_empty: If False (default), raises error if result is empty
            after sanitization

    Returns:
        Sanitized string

    Raises:
        OpenZimMcpValidationError: If input is invalid or empty
            (when allow_empty=False)
    """
    if not isinstance(input_string, str):
        raise OpenZimMcpValidationError("Input must be a string")

    if len(input_string) > max_length:
        raise OpenZimMcpValidationError(
            f"Input too long: {len(input_string)} > {max_length}"
        )

    # Remove control characters except newlines and tabs
    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", input_string)
    sanitized = sanitized.strip()

    # Check for empty result after sanitization
    if not allow_empty and not sanitized:
        raise OpenZimMcpValidationError(
            "Input is empty or contains only whitespace/control characters"
        )

    return sanitized


def sanitize_path_for_error(path: str, show_filename: bool = True) -> str:
    """Sanitize a file path for inclusion in error messages.

    This function obscures the full directory path while keeping the filename
    visible for debugging purposes. This helps prevent information disclosure
    of internal file system structure in production environments.

    Args:
        path: The file path to sanitize
        show_filename: If True, show the filename; if False, completely obscure

    Returns:
        Sanitized path string

    Example:
        >>> sanitize_path_for_error("/home/user/data/wikipedia.zim")
        '...wikipedia.zim'
        >>> sanitize_path_for_error(
        ...     "/home/user/data/wikipedia.zim", show_filename=False
        ... )
        '<path-hidden>'
    """
    if not path:
        return NO_PATH_PLACEHOLDER

    if not show_filename:
        return PATH_HIDDEN_PLACEHOLDER

    try:
        # Extract just the filename
        path_obj = Path(path)
        filename = path_obj.name
        if filename:
            return f"...{filename}"
        return PATH_HIDDEN_PLACEHOLDER
    except Exception:
        return PATH_HIDDEN_PLACEHOLDER


def sanitize_context_for_error(context: str) -> str:
    """Sanitize context strings for error messages.

    Looks for patterns that might be file paths and sanitizes them.
    Also handles URL-encoded paths to prevent information leakage.

    Args:
        context: The context string to sanitize

    Returns:
        Sanitized context string
    """
    if not context:
        return context

    # URL-decode the context to catch encoded paths (%2F = /, etc.)
    decoded_context = context
    with contextlib.suppress(Exception):  # nosec B110
        decoded_context = unquote(context)

    # Common patterns indicating file paths
    path_indicators = [
        "File:",
        "Path:",
        "Directory:",
        "/home/",
        "/Users/",
        "/var/",
        "/tmp/",  # nosec B108 - string pattern for detection, not temp file usage
        "C:\\",
        "D:\\",
    ]

    sanitized = context

    # Check if context (original or decoded) contains file path indicators
    context_to_check = decoded_context if decoded_context != context else context
    for indicator in path_indicators:
        if indicator in context_to_check:
            # Try to extract and sanitize any paths
            # Split by common delimiters and check each part
            parts = context_to_check.replace(",", " ").split()
            sanitized_parts = []
            for part in parts:
                # Check if this part looks like a file path (also check decoded version)
                try:
                    decoded_part = unquote(part)
                except ValueError:
                    decoded_part = part  # Keep original if decoding fails
                if (
                    decoded_part.startswith("/")
                    or decoded_part.startswith("C:\\")
                    or decoded_part.startswith("D:\\")
                    or ".zim" in decoded_part.lower()
                ):
                    sanitized_parts.append(sanitize_path_for_error(decoded_part))
                else:
                    sanitized_parts.append(part)
            sanitized = " ".join(sanitized_parts)
            break

    return sanitized
