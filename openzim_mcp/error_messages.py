"""
Error message templates for OpenZIM MCP server.

This module centralizes all error message templates, making it easier to
maintain consistent error messages and potentially support localization.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Type

from .exceptions import (
    OpenZimMcpArchiveError,
    OpenZimMcpArchiveNameError,
    OpenZimMcpArchivePathError,
    OpenZimMcpEntryNotFoundError,
    OpenZimMcpError,
    OpenZimMcpFileNotFoundError,
    OpenZimMcpRateLimitError,
    OpenZimMcpSecurityError,
    OpenZimMcpValidationError,
)
from .security import sanitize_control_chars

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ErrorConfig:
    """Configuration for an error message template."""

    title: str
    issue: str
    steps: List[str]


# Error message configurations mapped by exception type
ERROR_CONFIGS: Dict[Type[OpenZimMcpError], ErrorConfig] = {
    OpenZimMcpFileNotFoundError: ErrorConfig(
        title="File Not Found Error",
        issue="The specified ZIM file could not be found.",
        steps=[
            "Verify the file path is correct",
            "Check that the file exists in one of the allowed directories",
            'Use `zim_query("list available ZIM files")` to see available files',
            "Ensure you have read permissions for the file",
        ],
    ),
    OpenZimMcpArchiveError: ErrorConfig(
        title="Archive Operation Error",
        issue="The ZIM archive operation failed.",
        steps=[
            "Verify the ZIM file is not corrupted",
            "Check if the file is currently being written to",
            "Ensure sufficient system resources (memory/disk space)",
            "Try with a different ZIM file to isolate the issue",
            "Use `zim_health()` to check overall server status",
        ],
    ),
    OpenZimMcpSecurityError: ErrorConfig(
        title="Security Validation Error",
        issue="The request was blocked for security reasons.",
        steps=[
            "Ensure the file path is within allowed directories",
            "Check for path traversal attempts (../ sequences)",
            "Verify the file path doesn't contain suspicious characters",
            "Use `zim_health()` to see server state and allowed directories",
        ],
    ),
    # ``OpenZimMcpArchivePathError`` subclasses ``OpenZimMcpValidationError``,
    # but this lookup is by EXACT type, so it needs its own entry — otherwise
    # "Path is not a file" / "File is not a ZIM file" / "Failed to resolve file
    # path" resolve to no template at all. It also deserves better guidance
    # than the input-validation steps: nothing is wrong with the arguments.
    # The "omit `zim_file_path`" step is NOT part of this base list: only the
    # tools in ``_ARCHIVE_OMITTABLE_OPERATIONS`` accept omission, and
    # auto-select only works with exactly one archive loaded, so the step is
    # composed per call by ``get_error_config``.
    OpenZimMcpArchivePathError: ErrorConfig(
        title="Archive Not Available",
        issue="The ZIM archive itself could not be opened.",
        steps=[
            'Use `zim_query("list available ZIM files")` to see the real paths',
            "Pass one of those paths verbatim as `zim_file_path`",
            "Confirm the file is a readable `.zim` file, not a directory",
        ],
    ),
    # A relative ``zim_file_path`` that matched nothing. Not a security
    # event (``..`` and absolute escapes raise ``OpenZimMcpSecurityError``
    # instead), so the advice is "copy the real path", not "check for
    # traversal". Shares the archive-path omission logic above.
    OpenZimMcpArchiveNameError: ErrorConfig(
        title="Archive Not Found",
        issue="`zim_file_path` did not match any loaded archive.",
        steps=[
            (
                "Use `zim_health()` and pass a `loaded_archives[].path` value "
                "verbatim as `zim_file_path`"
            ),
            (
                "Relative names resolve only against the server's archive "
                "directories — check the spelling and the `.zim` extension"
            ),
        ],
    ),
    OpenZimMcpValidationError: ErrorConfig(
        title="Input Validation Error",
        issue="The provided input parameters are invalid.",
        steps=[
            "Check parameter formats and ranges",
            "Ensure required parameters are provided",
            "Verify string lengths are within limits",
            "Check for special characters that might need escaping",
        ],
    ),
    OpenZimMcpRateLimitError: ErrorConfig(
        title="Rate Limit Exceeded",
        issue="Too many requests in a short period.",
        steps=[
            "Wait a few seconds before retrying",
            "Reduce the frequency of requests",
            "Consider batching multiple queries",
            "Use caching for repeated queries",
        ],
    ),
}

# Tools whose input schema declares ``zim_file_path`` as optional. Every other
# advanced tool (zim_get, zim_get_section, zim_links, zim_browse, zim_metadata)
# marks it required, so "omit it" advice there sends the caller straight into a
# raw pydantic "Field required" rejection.
_ARCHIVE_OMITTABLE_OPERATIONS = frozenset({"zim_query", "zim_search", "zim_health"})

# ...and of those, the ones that answer the SAME question with the path left
# out. ``zim_health(None)`` does not auto-select the failing archive: it
# branches to ``get_health_data`` and reports combined server state, so
# promising auto-select there sends the caller to a different answer.
_ARCHIVE_AUTOSELECT_OPERATIONS = frozenset({"zim_query", "zim_search"})


def _archive_path_config(
    base: ErrorConfig,
    operation: Optional[str],
    count_archives: Optional[Callable[[], int]],
) -> ErrorConfig:
    """Compose the archive-path template's recovery steps for one tool.

    The omission step is advertised only to tools that can honour it, and
    only claims auto-select when exactly one archive is loaded. ``count_archives``
    is a zero-arg callable so the (filesystem-walking) listing runs only on
    this error path; a failing or absent counter degrades to conditional
    wording rather than a false promise.
    """
    if operation not in _ARCHIVE_OMITTABLE_OPERATIONS:
        return base

    if operation not in _ARCHIVE_AUTOSELECT_OPERATIONS:
        return _with_omission_step(
            base,
            "Omit `zim_file_path` entirely for the server-state report "
            "(it lists every loaded archive rather than validating one)",
        )

    count: Optional[int] = None
    if count_archives is not None:
        try:
            count = int(count_archives())
        except Exception as exc:  # noqa: BLE001 — advice must never raise
            logger.debug("Archive count unavailable for error advice: %s", exc)
            count = None

    if count is None:
        extra = (
            "Omit `zim_file_path` entirely to auto-select when exactly one "
            "archive is loaded"
        )
    elif count == 1:
        extra = "Omit `zim_file_path` entirely to auto-select the only loaded archive"
    elif count == 0:
        extra = (
            "No ZIM files are loaded — check the allowed directories via `zim_health()`"
        )
    else:
        extra = (
            f"{count} archives are loaded, so `zim_file_path` must name one of them "
            "(auto-select needs exactly one)"
        )
    return _with_omission_step(base, extra)


def _with_omission_step(base: ErrorConfig, extra: str) -> ErrorConfig:
    """Splice the omission step in after "pass one of those paths verbatim"
    so the list still reads list → pick → (omit) → confirm."""
    steps = list(base.steps)
    steps.insert(2, extra)
    return ErrorConfig(title=base.title, issue=base.issue, steps=steps)


# Permission-related error configuration
PERMISSION_ERROR_CONFIG = ErrorConfig(
    title="Permission Error",
    issue="Insufficient permissions to access the resource.",
    steps=[
        "Check file and directory permissions",
        "Ensure the server process has read access",
        "Verify the file is not locked by another process",
        "Try running with appropriate permissions",
        "Use `zim_health()` for environment validation",
    ],
)

# Resource not found error configuration
NOT_FOUND_ERROR_CONFIG = ErrorConfig(
    title="Resource Not Found",
    issue="The requested resource could not be located.",
    steps=[
        "Double-check the spelling and path",
        "Use browsing tools to explore available content",
        "Check if the resource exists in a different namespace",
        "Verify the ZIM file contains the expected content",
        "Try using search tools to locate similar content",
    ],
)

# Generic error template. ``{status_check}`` / ``{help_hint}`` are the two
# spots that named a tool; they are filled per ``tool_mode`` from
# ``_GENERIC_FILLS`` so a simple-mode client (registry: ``zim_query`` alone)
# is never told to call ``zim_health()``.
GENERIC_ERROR_TEMPLATE = """**Operation Failed**

**Operation**: {operation}
**Error Type**: {error_type}
**Context**: {context}

**Troubleshooting Steps**:
1. Try the operation again (temporary issues may resolve)
2. {status_check}
3. Verify your input parameters are correct
4. Check if other operations work with the same file
5. Consider using alternative tools or approaches

**Technical Details**: {details}

**Need Help?** {help_hint}"""

# Per-mode fills for the two tool-naming slots above.
_GENERIC_FILLS: Dict[str, Dict[str, str]] = {
    "advanced": {
        "status_check": "Use `zim_health()` to check for server issues",
        "help_hint": (
            "Use `zim_health()` to check server status "
            "or try simpler operations first."
        ),
    },
    "simple": {
        "status_check": (
            "Ask for `list available ZIM files` to check the server responds"
        ),
        "help_hint": (
            "Ask for `list available ZIM files` to check the server responds, "
            "or try simpler operations first."
        ),
    },
}

# Recovery steps that name a tool only the ADVANCED registry exposes, paired
# with wording a simple-mode client can act on. Simple mode registers
# ``zim_query`` alone, so ``Use `zim_health()`...`` there describes a tool the
# client cannot see — the same defect the recovery footers in
# ``openzim_mcp.meta`` carried. Each replacement is a query the intent parser
# actually resolves (``list available ZIM files`` -> ``list_files``), not a
# plain-English paraphrase that would parse as a literal search.
# ``tests/test_recovery_advice_tool_names.py`` renders every template in both
# modes and fails if a step names an unregistered tool.
_SIMPLE_MODE_STEPS: Dict[str, str] = {
    "Use `zim_health()` to check overall server status": (
        "Ask for `list available ZIM files` to confirm the server sees " "the archive"
    ),
    "Use `zim_health()` to see server state and allowed directories": (
        "Ask for `list available ZIM files` to see the paths the server " "will accept"
    ),
    (
        "Use `zim_health()` and pass a `loaded_archives[].path` value "
        "verbatim as `zim_file_path`"
    ): (
        "Ask for `list available ZIM files` and pass one of those paths "
        "verbatim as `zim_file_path`"
    ),
    "Use `zim_health()` for environment validation": (
        "Ask for `list available ZIM files` to see which archives the "
        "server can actually read"
    ),
    "No ZIM files are loaded — check the allowed directories via `zim_health()`": (
        "No ZIM files are loaded — ask an operator to check the server's "
        "allowed directories"
    ),
}


def _for_tool_mode(config: ErrorConfig, tool_mode: str) -> ErrorConfig:
    """Rewrite advanced-only recovery steps for a simple-mode client.

    ``ERROR_CONFIGS`` is written in advanced-mode terms because that is the
    surface where every named tool exists. Returns ``config`` unchanged when
    nothing needed rewriting, so identity comparisons in existing tests keep
    working.
    """
    if tool_mode == "advanced":
        return config
    steps = [_SIMPLE_MODE_STEPS.get(step, step) for step in config.steps]
    if steps == list(config.steps):
        return config
    return ErrorConfig(title=config.title, issue=config.issue, steps=steps)


# Cap on the "Technical Details" echo. Matches ``security._CONTEXT_MAX_LENGTH``
# so the two user-influenced fields of an envelope are bounded alike: the
# exception text often embeds the offending argument verbatim (the data
# layer's "Entry not found: '<path>'"), and without a cap a 1 MB ``entry_path``
# came back as a 1 MB error body.
_DETAILS_MAX_LENGTH = 1024


def _bound_details(details: str) -> str:
    """Keep the details echo a single bounded line.

    Control characters are collapsed first (the same C0/DEL class
    ``sanitize_context_for_error`` strips from ``context``): the exception
    text embeds the offending argument verbatim, so a ``zim_file_path`` of
    ``foo\\n\\tbar.zim`` otherwise split the ``**Technical Details**`` line
    even after the context line was cleaned (R2-3). Then truncate, marking
    the cut with ``...``.
    """
    details = sanitize_control_chars(details)
    if len(details) <= _DETAILS_MAX_LENGTH:
        return details
    return details[:_DETAILS_MAX_LENGTH].rstrip() + "..."


def url_shaped_path_hint(entry_path: str) -> str:
    """Corrective clause for an ``entry_path`` that was handed a URL.

    Pasting the article's web address is the most natural wrong guess a
    client makes, and the generic not-found steps ("check the spelling",
    "try a different namespace") never mention the real mistake. Returns
    ``""`` for an ordinary path so callers can append unconditionally.

    Bare-host paths are deliberately NOT matched: zimit/warc2zim archives
    genuinely file entries under host-shaped paths like
    ``medlineplus.gov/druginfo/meds/a682878.html``, so only an explicit
    scheme is evidence of the mistake.

    That is also why the suggestion keeps the host and strips only the
    scheme. Telling the caller to drop the host produces a path that does
    not exist on exactly the archives this hint fires for most:
    ``https://iep.utm.edu/stoicism/`` is filed at
    ``iep.utm.edu/stoicism/``, not at ``stoicism/``.
    """
    scheme, separator, remainder = entry_path.partition("://")
    if not separator or not scheme.isalpha():
        return ""
    suggestion = f" (e.g. '{remainder}')" if remainder else ""
    return (
        " Entry paths are archive-relative, never URLs: drop the scheme"
        f"{suggestion}."
    )


def format_error_message(
    config: ErrorConfig,
    operation: str,
    context: str,
    details: str,
) -> str:
    """Format an error message using a configuration template.

    Args:
        config: Error configuration with title, issue, and steps
        operation: The operation that failed
        context: Additional context (sanitized)
        details: Technical error details

    Returns:
        Formatted error message string
    """
    steps_text = "\n".join(f"{i+1}. {step}" for i, step in enumerate(config.steps))
    return (
        f"**{config.title}**\n\n"
        f"**Operation**: {operation}\n"
        f"**Issue**: {config.issue}\n"
        f"**Context**: {context}\n\n"
        f"**Troubleshooting Steps**:\n{steps_text}\n\n"
        f"**Technical Details**: {_bound_details(details)}"
    )


def format_generic_error(
    operation: str,
    error_type: str,
    context: str,
    details: str,
    *,
    tool_mode: str = "simple",
) -> str:
    """Format a generic error message.

    Args:
        operation: The operation that failed
        error_type: The type of error
        context: Additional context (sanitized)
        details: Technical error details
        tool_mode: Which registry the client can see. Defaults to the
            fail-safe mode — a caller that forgets to thread it gets advice
            phrased for the one-tool surface rather than a tool name that
            may not exist there.

    Returns:
        Formatted generic error message
    """
    fills = _GENERIC_FILLS.get(tool_mode, _GENERIC_FILLS["simple"])
    return GENERIC_ERROR_TEMPLATE.format(
        operation=operation,
        error_type=error_type,
        context=context,
        details=_bound_details(details),
        **fills,
    )


def get_error_config(
    error: Exception,
    *,
    operation: Optional[str] = None,
    count_archives: Optional[Callable[[], int]] = None,
    tool_mode: str = "simple",
) -> ErrorConfig | None:
    """Get the error configuration for an exception type.

    Message-pattern checks run first so a specific failure mode (entry not
    found, permission denied) gets a focused template even when the
    exception type is a broad category like OpenZimMcpArchiveError. That
    avoids advising the caller to "check disk space" when the real issue
    is a missing entry path.

    Args:
        error: The exception to get configuration for
        operation: The tool that is rendering the error (``zim_get``, ...).
            Lets archive-path advice name only recovery steps that tool can
            honour — see ``_archive_path_config``.
        count_archives: Zero-arg callable returning the number of loaded
            archives; consulted only for archive-path errors.
        tool_mode: Which registry the client can see. The templates are
            written in advanced-mode terms; ``_for_tool_mode`` rewrites the
            steps that name an advanced-only tool for a simple-mode client.
            Defaults to the fail-safe mode.

    Returns:
        ErrorConfig if found, None otherwise
    """
    config = _resolve_error_config(error, operation, count_archives)
    return None if config is None else _for_tool_mode(config, tool_mode)


def _resolve_error_config(
    error: Exception,
    operation: Optional[str],
    count_archives: Optional[Callable[[], int]],
) -> ErrorConfig | None:
    """Pick the template for ``error``, in advanced-mode wording."""
    message = str(error).lower()

    # M5: security rejections (security.py raises "Access denied - Path is
    # outside allowed directories" / "... resolves outside ...") must render
    # the security template. Check the type BEFORE the "access denied" /
    # "permission" message-pattern shortcut below — otherwise both primary
    # raise sites were routed to the generic Permission template, whose
    # guidance ("try running with appropriate permissions") is actively wrong
    # for a blocked path traversal.
    if isinstance(error, OpenZimMcpSecurityError):
        return ERROR_CONFIGS[OpenZimMcpSecurityError]

    # Same ordering hazard: ``validate_zim_file``'s most common rejection is
    # "File does not exist: <path>", which the "does not exist" pattern below
    # would route to the entry-level not-found template — five steps telling
    # the caller to browse and search inside an archive that was never opened.
    if isinstance(error, OpenZimMcpArchiveNameError):
        return _archive_path_config(
            ERROR_CONFIGS[OpenZimMcpArchiveNameError], operation, count_archives
        )
    if isinstance(error, OpenZimMcpArchivePathError):
        return _archive_path_config(
            ERROR_CONFIGS[OpenZimMcpArchivePathError], operation, count_archives
        )

    # A typed not-found beats the prose check below it. The type-mapping fall
    # back at the bottom is by EXACT type, so this subclass would otherwise
    # reach the client only for as long as its message keeps saying "entry not
    # found" — one rephrase at a raise site and a missing page would start
    # rendering "verify the ZIM file is not corrupted".
    if isinstance(error, OpenZimMcpEntryNotFoundError):
        return NOT_FOUND_ERROR_CONFIG

    # Specific failure modes detectable from the message take priority.
    if "entry not found" in message or "does not exist" in message:
        return NOT_FOUND_ERROR_CONFIG
    if "permission" in message or "access denied" in message:
        return PERMISSION_ERROR_CONFIG

    # Fall back to exception-type mapping for the broad categories.
    # Note: type(error) returns type[Exception] but ERROR_CONFIGS keys are
    # type[OpenZimMcpError] - this is safe since .get() returns None for
    # non-matching keys.
    config = ERROR_CONFIGS.get(type(error))  # type: ignore[arg-type]
    if config:
        return config

    # Last resort: a generic "not found" hint if the message looks that way.
    if "not found" in message:
        return NOT_FOUND_ERROR_CONFIG

    return None
