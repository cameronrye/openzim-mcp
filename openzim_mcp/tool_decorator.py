"""
Tool decorator for standardizing error handling and rate limiting.

This module provides a decorator that wraps MCP tool handlers with:
- Rate limiting checks
- Standardized error handling
- Conflict warning appending

NOTE: This decorator expects `server` as the first positional argument.
The current tool implementations in openzim_mcp/tools/ use a closure pattern
where `server` is captured from the enclosing `register_*_tools` function.
To use this decorator with those tools would require architectural changes.

Future refactoring could:
1. Modify tools to accept server as explicit parameter
2. Or modify this decorator to support closure-based server access
"""

import functools
import logging
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar

if TYPE_CHECKING:
    from .server import OpenZimMcpServer

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def zim_tool(
    operation_name: str,
    rate_limit_operation: Optional[str] = None,
    check_conflicts: bool = True,
) -> Callable[[F], F]:
    """Decorate MCP tool handlers with standardized behavior.

    This decorator wraps tool handlers with:
    - Rate limiting (if enabled)
    - Standardized error handling with enhanced messages
    - Conflict warning appending (if enabled)

    Args:
        operation_name: Human-readable name for the operation (for errors)
        rate_limit_operation: Operation name for rate limiting (default: operation_name)
        check_conflicts: Whether to check for and append conflict warnings

    Returns:
        Decorated function

    Example:
        @zim_tool("search", rate_limit_operation="search")
        async def search_zim_file(server, zim_file_path: str, query: str) -> str:
            return await server.async_zim_operations.search_zim_file(...)
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(server: "OpenZimMcpServer", *args: Any, **kwargs: Any) -> str:
            # Determine rate limit operation
            rl_operation = rate_limit_operation or operation_name.lower().replace(
                " ", "_"
            )

            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit(rl_operation)
            except Exception as e:
                logger.warning(f"Rate limit exceeded for {rl_operation}: {e}")
                return server._create_enhanced_error_message(
                    operation=operation_name,
                    error=e,
                    context=f"Operation: {operation_name}",
                )

            # Execute the tool
            try:
                result: str = await func(server, *args, **kwargs)

                # Append conflict warnings if enabled
                if check_conflicts:
                    result = server._check_and_append_conflict_warnings(result)

                return result

            except Exception as e:
                logger.error(f"Error in {operation_name}: {e}")
                # Build context from arguments
                context_parts = []
                if args:
                    context_parts.append(f"args={args[:2]}")  # Limit for brevity
                if kwargs:
                    # Filter sensitive info and limit size
                    safe_kwargs = {
                        k: v
                        for k, v in kwargs.items()
                        if k not in ("password", "secret", "token")
                    }
                    context_parts.append(f"kwargs={safe_kwargs}")
                context = ", ".join(context_parts) if context_parts else ""

                return server._create_enhanced_error_message(
                    operation=operation_name,
                    error=e,
                    context=context,
                )

        return wrapper  # type: ignore[return-value]

    return decorator


def sync_zim_tool(
    operation_name: str,
    rate_limit_operation: Optional[str] = None,
    check_conflicts: bool = True,
) -> Callable[[F], F]:
    """Decorate synchronous tool handlers with standardized behavior.

    Use for synchronous tool handlers that don't need async operations.

    Args:
        operation_name: Human-readable name for the operation
        rate_limit_operation: Operation name for rate limiting
        check_conflicts: Whether to check for and append conflict warnings

    Returns:
        Decorated function
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(server: "OpenZimMcpServer", *args: Any, **kwargs: Any) -> str:
            # Determine rate limit operation
            rl_operation = rate_limit_operation or operation_name.lower().replace(
                " ", "_"
            )

            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit(rl_operation)
            except Exception as e:
                logger.warning(f"Rate limit exceeded for {rl_operation}: {e}")
                return server._create_enhanced_error_message(
                    operation=operation_name,
                    error=e,
                    context=f"Operation: {operation_name}",
                )

            # Execute the tool
            try:
                result: str = func(server, *args, **kwargs)

                # Append conflict warnings if enabled
                if check_conflicts:
                    result = server._check_and_append_conflict_warnings(result)

                return result

            except Exception as e:
                logger.error(f"Error in {operation_name}: {e}")
                context_parts = []
                if args:
                    context_parts.append(f"args={args[:2]}")
                if kwargs:
                    safe_kwargs = {
                        k: v
                        for k, v in kwargs.items()
                        if k not in ("password", "secret", "token")
                    }
                    context_parts.append(f"kwargs={safe_kwargs}")
                context = ", ".join(context_parts) if context_parts else ""

                return server._create_enhanced_error_message(
                    operation=operation_name,
                    error=e,
                    context=context,
                )

        return wrapper  # type: ignore[return-value]

    return decorator
