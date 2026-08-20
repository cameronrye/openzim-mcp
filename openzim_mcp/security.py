"""Security and path validation for OpenZIM MCP server."""

import logging
import os
import re
import threading
from pathlib import Path
from typing import List, Optional
from urllib.parse import unquote

from .constants import ZIM_FILE_EXTENSION
from .exceptions import (
    OpenZimMcpArchiveNameError,
    OpenZimMcpArchivePathError,
    OpenZimMcpSecurityError,
    OpenZimMcpValidationError,
)

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

        # Give the message redactor the exact strings it cannot infer: a
        # configured root containing spaces would otherwise leak every
        # component after the first space (see ``_ALLOWED_DIRECTORY_HINTS``).
        register_redaction_directories([str(p) for p in self.allowed_directories])

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
            r"\.\.",  # Any embedded ``..`` — superset of the four below.
            #          Catches mid-path ``..`` between non-separator chars
            #          (``foo..bar``) that would otherwise slip past the
            #          slash-anchored variants and reach ``is_relative_to``
            #          alone. Kept above the more specific patterns so the
            #          first match terminates fastest.
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

        Relative inputs are resolved against the allowed directories first —
        the bare ``name`` that ``zim_health()`` publishes in
        ``loaded_archives[]`` is the form LLM clients most often echo back.
        A relative input that matches nothing is reported as
        :class:`OpenZimMcpArchiveNameError` (a not-found), not as a security
        violation: ``..`` was already rejected by ``_normalize_path`` and a
        relative path cannot name a host directory, so the security framing
        is reserved for absolute escapes.

        Raises:
            OpenZimMcpSecurityError: When an absolute path is outside allowed
                directories (or any input carries a traversal pattern)
            OpenZimMcpArchiveNameError: When a relative path matches no
                loaded archive, or matches more than one
            OpenZimMcpValidationError: When path is invalid
        """
        try:
            normalized_path = self._normalize_path(requested_path)
            relative_input = not os.path.isabs(normalized_path)
            resolved_path = Path(normalized_path).resolve()
            if relative_input:
                matched = self._resolve_relative_archive(normalized_path)
                if matched is not None:
                    resolved_path = matched
        except (OSError, ValueError) as e:
            raise OpenZimMcpValidationError(f"Invalid path: {requested_path}") from e

        # Use secure path checking (Python 3.9+)
        is_allowed = any(
            self._is_path_within_directory(resolved_path, allowed_dir)
            for allowed_dir in self.allowed_directories
        )

        if not is_allowed:
            if relative_input:
                # No traversal and no absolute escape: the name simply isn't
                # one the server serves. The input is the client's own string
                # (no host layout in it), so it can be echoed.
                raise OpenZimMcpArchiveNameError(
                    f"Path did not match any loaded archive: {requested_path}"
                )
            # Defence in depth: the client already knows what it asked for, but
            # ``resolved_path`` is the *server-side* canonicalisation — for a
            # symlinked or ``~``-expanded input it names host directories the
            # client never supplied and cannot otherwise observe. Keep the full
            # path in the debug log only.
            logger.debug(f"Path outside allowed directories: {resolved_path}")
            raise OpenZimMcpSecurityError(
                f"Access denied - Path is outside allowed directories: "
                f"{sanitize_path_for_error(str(resolved_path))}"
            )

        logger.debug(f"Path validation successful: {resolved_path}")
        return resolved_path

    def _resolve_relative_archive(self, relative: str) -> Optional[Path]:
        """Match a relative input against the archives the server serves.

        Tries ``<allowed_dir>/<relative>`` first, then — for a bare
        ``*.zim`` filename — the same ``**/*.zim`` walk ``list_zim_files``
        uses, so every name that listing publishes resolves. Returns the
        single match, ``None`` when nothing matches (the caller decides how
        to report that), and raises when the name is ambiguous rather than
        guessing between same-named archives in different subdirectories.
        """
        rel = Path(relative)
        is_bare_zim_name = (
            len(rel.parts) == 1 and rel.suffix.lower() == ZIM_FILE_EXTENSION
        )
        candidates: set[Path] = set()
        for directory in self.allowed_directories:
            try:
                direct = directory / rel
                if direct.exists():
                    candidates.add(direct.resolve())
                    continue
                if is_bare_zim_name:
                    candidates.update(
                        p.resolve()
                        for p in directory.glob("**/*.zim")
                        if p.name == rel.name and p.is_file()
                    )
            except (OSError, ValueError) as exc:
                # A directory that can't be walked is skipped, mirroring the
                # listing scan's resilience; the caller falls back to the
                # cwd-resolved path and the containment check.
                logger.debug("Relative archive match failed in %s: %s", directory, exc)
        if not candidates:
            return None
        if len(candidates) > 1:
            raise OpenZimMcpArchiveNameError(
                f"Relative name matches {len(candidates)} loaded archives; pass "
                f"the absolute path instead: {relative}"
            )
        return next(iter(candidates))

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
            OpenZimMcpArchivePathError: If the archive is missing or unusable.
                A subclass of ``OpenZimMcpValidationError``, so broad handlers
                still catch it, but callers rendering argument-level recovery
                advice can tell "no such archive" from "bad argument".
            OpenZimMcpSecurityError: If the path resolves outside allowed
                directories (e.g., a symlink was swapped between
                ``validate_path`` and this call)
        """
        if not file_path.exists():
            raise OpenZimMcpArchivePathError(f"File does not exist: {file_path}")

        if not file_path.is_file():
            raise OpenZimMcpArchivePathError(f"Path is not a file: {file_path}")

        if file_path.suffix.lower() != ZIM_FILE_EXTENSION:
            raise OpenZimMcpArchivePathError(f"File is not a ZIM file: {file_path}")

        # Re-resolve and re-check containment to close the TOCTOU window
        # between validate_path()'s resolve and the caller eventually opening
        # the file. If a symlink was swapped in to point outside the allowed
        # tree, resolve() will follow it to the new target.
        try:
            current_resolved = file_path.resolve(strict=True)
        except (OSError, ValueError) as e:
            raise OpenZimMcpArchivePathError(
                f"Failed to resolve file path: {file_path}"
            ) from e

        if not any(
            self._is_path_within_directory(current_resolved, allowed_dir)
            for allowed_dir in self.allowed_directories
        ):
            # See ``validate_path``: the resolved path is a server-side fact
            # (symlink target) the client never supplied. Log it, don't ship it.
            logger.debug(
                f"Path resolves outside allowed directories: " f"{current_resolved}"
            )
            raise OpenZimMcpSecurityError(
                f"Access denied - Path resolves outside allowed directories: "
                f"{sanitize_path_for_error(str(current_resolved))}"
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
# absolute paths (``/foo/bar``). The negative lookbehind guarantees the
# path is not preceded by another path-continuation character, so a
# relative path embedded mid-token (``test.zim/A/B``) does not have its
# ``/A/B`` suffix mistaken for an absolute path -- yet a path wrapped by
# punctuation (``(/opt/foo)``, ``"/opt/foo"``, ``file=/opt/foo``) still
# matches because ``(``, ``"``, ``=`` are not path-continuation chars.
# The body stops at whitespace **and** at common wrapper delimiters (``'``,
# ``"``, ``)``, ``]``, ``<``, ``>``) so wrapped paths collapse cleanly without
# absorbing the surrounding wrapper characters. Trailing prose punctuation
# (``.``, ``,``, ``;``, ``:``) is stripped by ``_strip_trailing_punct``
# before being routed through :func:`sanitize_path_for_error`. Used by
# both :func:`sanitize_context_for_error` here and the redactor in
# ``server.py`` so we have a single source of truth.
#
# The body deliberately does NOT try to infer that a space is path-internal.
# A regex cannot tell ``/Users/John Smith/x.zim`` (space inside a directory
# name) from ``/data/wiki.zim: I/O error`` (space, then prose that happens to
# contain a slash): any relaxation keyed on "a separator appears later" merges
# adjacent paths and slash-bearing prose into one token, which destroys the
# filename this redactor is contracted to keep. Directories that really do
# contain spaces are handled with real information instead — see
# ``_ALLOWED_DIRECTORY_HINTS`` and :func:`register_redaction_directories`.
_PATH_BODY = r"[^\s'\")\]<>]+"
_ABS_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9._\-/\\])"  # not preceded by a path-continuation char
    r"(?:[A-Za-z]:[\\/]"
    + _PATH_BODY  # Windows drive path
    + r"|/"
    + _PATH_BODY
    + r")"  # POSIX absolute path
)

# Directories the server has been configured to serve. They are known exact
# strings at runtime, so a path rooted at one of them can be redacted by
# LITERAL prefix match — no guessing required, which is what makes
# space-bearing roots (``/Users/John Smith/Library/Application Support/Claude``)
# tractable at all. Populated by :meth:`PathValidator.__init__`.
_MAX_ALLOWED_DIRECTORY_HINTS = 64
_ALLOWED_DIRECTORY_HINTS: List[str] = []
_ALLOWED_DIRECTORY_HINTS_LOCK = threading.Lock()
_ALLOWED_DIRECTORY_RE: "re.Pattern[str] | None" = None


def register_redaction_directories(directories: List[str]) -> None:
    """Record configured directories so the redactor can match them literally.

    Only directories whose string form contains a space are worth recording:
    every other absolute path is already matched by ``_ABS_PATH_RE``, whose
    body is whitespace-terminated. Restricting the registry this way keeps it
    tiny and keeps redaction behaviour identical to the plain-regex path for
    the overwhelmingly common case.

    Args:
        directories: Absolute directory paths (already resolved).
    """
    global _ALLOWED_DIRECTORY_RE

    with _ALLOWED_DIRECTORY_HINTS_LOCK:
        changed = False
        for directory in directories:
            text = str(directory)
            if " " not in text or text in _ALLOWED_DIRECTORY_HINTS:
                continue
            if len(_ALLOWED_DIRECTORY_HINTS) >= _MAX_ALLOWED_DIRECTORY_HINTS:
                # Bounded: a long-lived process that keeps building validators
                # must not grow this list without limit. Oldest hint retires.
                _ALLOWED_DIRECTORY_HINTS.pop(0)
            _ALLOWED_DIRECTORY_HINTS.append(text)
            changed = True

        if not changed:
            return

        # Longest first so a nested root wins over its parent.
        alternation = "|".join(
            re.escape(d)
            for d in sorted(_ALLOWED_DIRECTORY_HINTS, key=len, reverse=True)
        )
        _ALLOWED_DIRECTORY_RE = re.compile(
            r"(?<![A-Za-z0-9._\-/\\])(?:"
            + alternation
            + r")"
            # The tail (``/wikipedia.zim``) is ordinary path text, so it stops
            # at whitespace exactly like ``_PATH_BODY``. Only the *root* needed
            # the literal treatment.
            + r"[^\s'\")\]<>]*"
        )


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

    # First collapse anything rooted at a configured directory. Those roots are
    # known verbatim, so this is the one place a space-bearing directory can be
    # redacted without guessing. ``_ABS_PATH_RE`` then handles everything else.
    known_dirs_re = _ALLOWED_DIRECTORY_RE
    message = raw_message
    if known_dirs_re is not None:
        message = known_dirs_re.sub(_replace, message)

    return _ABS_PATH_RE.sub(_replace, message)


# Every C0 control character plus DEL — including tab, LF, and CR. Unlike
# ``sanitize_input`` (which cleans legitimately multi-line query text and
# keeps newlines/tabs on purpose), a context string is a one-line label
# inside a markdown message; a caller-supplied LF here splits the
# ``**Context**`` line, and a log sink that captures the rendered message
# gets a forged second line (D61).
_CONTEXT_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]+")
_CONTEXT_MAX_LENGTH = 1024


def sanitize_control_chars(text: str) -> str:
    """Collapse every run of C0 control characters / DEL to one space.

    The one-line-label contract behind ``sanitize_context_for_error``,
    exposed on its own for text that must stay a single line but must NOT
    be path-redacted: the ``**Technical Details**`` echo (already redacted
    upstream) and the server-side ERROR log line, where the operator needs
    the real path. A caller-supplied LF in a ``zim_file_path`` otherwise
    reaches the client inside the exception text and forges a second
    physical line in the log (R2-3, D61 residual).
    """
    if not text:
        return text
    return _CONTEXT_CONTROL_CHARS_RE.sub(" ", text)


def sanitize_context_for_error(context: str) -> str:
    """Sanitize context strings for error messages.

    Looks for absolute filesystem paths (POSIX or Windows drive-letter)
    and replaces each one with its sanitized form. URL-encoded paths
    are decoded first so encoded variants (``%2Fopt%2Fzims%2Ffoo.zim``)
    are caught alongside their bare counterparts.

    Also strips ASCII control characters and caps overall length so that
    raw user-supplied values (e.g. a query that reaches the rate-limit
    error branch before ``sanitize_input`` has had a chance to clean it)
    cannot embed control characters or oversized payloads in the response
    or in any log line that captures the rendered message.

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

    # Strip control characters before redaction so a bytes-rendered
    # control char inside a path doesn't survive into the error message.
    decoded_context = sanitize_control_chars(decoded_context)

    redacted = redact_paths_in_message(decoded_context)

    if len(redacted) > _CONTEXT_MAX_LENGTH:
        redacted = redacted[:_CONTEXT_MAX_LENGTH].rstrip() + "..."

    return redacted
