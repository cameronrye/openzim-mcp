"""
Error message templates for OpenZIM MCP server.

This module centralizes all error message templates, making it easier to
maintain consistent error messages and potentially support localization.
"""

from dataclasses import dataclass
from typing import Dict, List, Type

from .exceptions import (
    OpenZimMcpArchiveError,
    OpenZimMcpError,
    OpenZimMcpFileNotFoundError,
    OpenZimMcpRateLimitError,
    OpenZimMcpSecurityError,
    OpenZimMcpValidationError,
)


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
            "Use `list_zim_files()` to see available ZIM files",
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
            "Use `diagnose_server_state()` to check for server conflicts",
        ],
    ),
    OpenZimMcpSecurityError: ErrorConfig(
        title="Security Validation Error",
        issue="The request was blocked for security reasons.",
        steps=[
            "Ensure the file path is within allowed directories",
            "Check for path traversal attempts (../ sequences)",
            "Verify the file path doesn't contain suspicious characters",
            "Use `get_server_configuration()` to see allowed directories",
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

# Permission-related error configuration
PERMISSION_ERROR_CONFIG = ErrorConfig(
    title="Permission Error",
    issue="Insufficient permissions to access the resource.",
    steps=[
        "Check file and directory permissions",
        "Ensure the server process has read access",
        "Verify the file is not locked by another process",
        "Try running with appropriate permissions",
        "Use `diagnose_server_state()` for environment validation",
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

# Generic error template
GENERIC_ERROR_TEMPLATE = """**Operation Failed**

**Operation**: {operation}
**Error Type**: {error_type}
**Context**: {context}

**Troubleshooting Steps**:
1. Try the operation again (temporary issues may resolve)
2. Use `diagnose_server_state()` to check for server issues
3. Verify your input parameters are correct
4. Check if other operations work with the same file
5. Consider using alternative tools or approaches

**Technical Details**: {details}

**Need Help?** Use `get_server_configuration()` to check server status or try simpler operations first."""


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
        f"**Technical Details**: {details}"
    )


def format_generic_error(
    operation: str,
    error_type: str,
    context: str,
    details: str,
) -> str:
    """Format a generic error message.

    Args:
        operation: The operation that failed
        error_type: The type of error
        context: Additional context (sanitized)
        details: Technical error details

    Returns:
        Formatted generic error message
    """
    return GENERIC_ERROR_TEMPLATE.format(
        operation=operation,
        error_type=error_type,
        context=context,
        details=details,
    )


def get_error_config(error: Exception) -> ErrorConfig | None:
    """Get the error configuration for an exception type.

    Also checks for common error patterns in the message content.

    Args:
        error: The exception to get configuration for

    Returns:
        ErrorConfig if found, None otherwise
    """
    # Check for exact type match first
    # Note: type(error) returns type[Exception] but ERROR_CONFIGS keys are
    # type[OpenZimMcpError] - this is safe since .get() returns None for non-matching
    config = ERROR_CONFIGS.get(type(error))  # type: ignore[arg-type]
    if config:
        return config

    # Check for common error patterns in message
    message = str(error).lower()

    if "permission" in message or "access" in message:
        return PERMISSION_ERROR_CONFIG

    if "not found" in message or "does not exist" in message:
        return NOT_FOUND_ERROR_CONFIG

    return None
