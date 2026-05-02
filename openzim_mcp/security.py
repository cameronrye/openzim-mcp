"""Security and path validation for OpenZIM MCP server."""

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
            return path.is_relative_to(directory)
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
            OpenZimMcpSecurityError: If the path resolves outside allowed
                directories (e.g., a symlink was swapped between
                ``validate_path`` and this call)
        """
        if not file_path.exists():
            raise OpenZimMcpValidationError(f"File does not exist: {file_path}")

        if not file_path.is_file():
            raise OpenZimMcpValidationError(f"Path is not a file: {file_path}")

        if file_path.suffix.lower() != ZIM_FILE_EXTENSION:
            raise OpenZimMcpValidationError(f"File is not a ZIM file: {file_path}")

        # Re-resolve and re-check containment to close the TOCTOU window
        # between validate_path()'s resolve and the caller eventually opening
        # the file. If a symlink was swapped in to point outside the allowed
        # tree, resolve() will follow it to the new target.
        try:
            current_resolved = file_path.resolve(strict=True)
        except (OSError, ValueError) as e:
            raise OpenZimMcpValidationError(
                f"Failed to resolve file path: {file_path}"
            ) from e

        if not any(
            self._is_path_within_directory(current_resolved, allowed_dir)
            for allowed_dir in self.allowed_directories
        ):
            raise OpenZimMcpSecurityError(
                f"Access denied - Path resolves outside allowed directories: "
                f"{current_resolved}"
            )

        logger.debug(f"ZIM file validation successful: {file_path}")
        # Return the re-resolved path so callers open the exact inode whose
        # containment was just verified, not the original (possibly
        # symlinked) input.
        return current_resolved


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


# Match either Windows drive-letter paths (``C:\foo\bar``) or POSIX
# absolute paths (``/foo/bar``). Anchored at start-of-string or after
# whitespace so a relative path embedded mid-token (``test.zim/A/B``)
# does not have its ``/A/B`` suffix mistaken for an absolute path.
# Stops at whitespace; trailing punctuation is stripped by
# ``_strip_trailing_punct`` before being routed through
# :func:`sanitize_path_for_error`. Used by both
# :func:`sanitize_context_for_error` here and the redactor in
# ``server.py`` so we have a single source of truth.
_ABS_PATH_RE = re.compile(r"(?:(?<=\s)|^)(?:[A-Za-z]:[\\/][^\s]+|/[^\s]+)")

# Both ``/`` and ``\`` may appear as a separator in a leaked path.
# :class:`pathlib.Path` does not split on ``\`` on POSIX hosts, so we
# split manually to keep the redactor cross-platform.
_PATH_SEP_RE = re.compile(r"[\\/]")

# Trailing punctuation that often abuts a path token in prose
# (``... directories: /opt/foo.zim.``) and should not become part of
# the "filename" we keep.
_TRAILING_PUNCT = ".,;:)]"


def _strip_trailing_punct(token: str) -> tuple[str, str]:
    """Split off any trailing prose-style punctuation from ``token``.

    Returns ``(core, trailing)`` so callers can sanitize ``core`` and
    re-append ``trailing`` afterwards.
    """
    stripped = token.rstrip(_TRAILING_PUNCT)
    return stripped, token[len(stripped) :]


def sanitize_path_for_error(path: str, show_filename: bool = True) -> str:
    r"""Sanitize a file path for inclusion in error messages.

    This function obscures the full directory path while keeping the filename
    visible for debugging purposes. This helps prevent information disclosure
    of internal file system structure in production environments.

    Splits on both ``/`` and ``\`` so a Windows-style path leaked on a
    POSIX host (where :class:`pathlib.Path` would treat ``\`` as a
    regular character) still collapses to its basename.

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
        # Manual split on both separators so this works for Windows-style
        # paths even when the host OS is POSIX.
        parts = _PATH_SEP_RE.split(path)
        filename = parts[-1] if parts else ""
        if filename:
            return f"...{filename}"
        return PATH_HIDDEN_PLACEHOLDER
    except Exception:
        return PATH_HIDDEN_PLACEHOLDER


def redact_paths_in_message(raw_message: str) -> str:
    r"""Redact absolute filesystem paths from a free-form message.

    Single source of truth for path redaction shared between the
    server's enhanced-error formatter and :func:`sanitize_context_for_error`.
    Each absolute-path match (Unix ``/foo/bar`` or Windows ``C:\foo\bar``)
    is routed through :func:`sanitize_path_for_error` so the directory
    portion is hidden while the filename survives for debugging.

    Trailing prose punctuation (``.``, ``,``, ``;``, ``:``, ``)``, ``]``)
    is stripped before sanitization and re-appended afterwards so we do
    not accidentally fold sentence-ending punctuation into the
    "filename" we keep.

    Args:
        raw_message: The raw message, possibly containing one or more
            absolute paths.

    Returns:
        The same message with each absolute path replaced by its
        sanitized form (e.g. ``...wikipedia.zim``).
    """
    if not raw_message:
        return raw_message

    def _replace(match: "re.Match[str]") -> str:
        token = match.group(0)
        core, trailing = _strip_trailing_punct(token)
        return sanitize_path_for_error(core) + trailing

    return _ABS_PATH_RE.sub(_replace, raw_message)


def sanitize_context_for_error(context: str) -> str:
    """Sanitize context strings for error messages.

    Looks for absolute filesystem paths (POSIX or Windows drive-letter)
    and replaces each one with its sanitized form. URL-encoded paths
    are decoded first so encoded variants (``%2Fopt%2Fzims%2Ffoo.zim``)
    are caught alongside their bare counterparts.

    Args:
        context: The context string to sanitize

    Returns:
        Sanitized context string
    """
    if not context:
        return context

    # URL-decode the context to catch encoded paths (%2F = /, etc.).
    # Apply redaction to the decoded form so any encoded path token is
    # also stripped of its directory portion.
    try:
        decoded_context = unquote(context)
    except Exception:
        # Decoding may fail on malformed input; fall back to the original.
        decoded_context = context

    return redact_paths_in_message(decoded_context)
