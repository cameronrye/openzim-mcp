"""
Tests for tool_decorator module.
"""

import logging
from unittest.mock import MagicMock

import pytest

from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.tool_decorator import sync_zim_tool, zim_tool


class MockServer:
    """Mock server for testing decorators."""

    def __init__(self, rate_limit_enabled: bool = True):
        self.rate_limiter = MagicMock()
        self.rate_limit_enabled = rate_limit_enabled
        if not rate_limit_enabled:
            self.rate_limiter.check_rate_limit = MagicMock()
        else:
            self.rate_limiter.check_rate_limit = MagicMock()

    def _create_enhanced_error_message(
        self, operation: str, error: Exception, context: str
    ) -> str:
        return f"Error in {operation}: {error} [{context}]"

    def _check_and_append_conflict_warnings(self, result: str) -> str:
        return result + " [conflict check done]"


class TestZimToolDecorator:
    """Test zim_tool async decorator."""

    @pytest.mark.asyncio
    async def test_basic_async_tool_success(self):
        """Test that a basic async tool executes successfully."""
        server = MockServer()

        @zim_tool("test operation")
        async def test_tool(server, arg1: str, arg2: int) -> str:
            return f"result: {arg1}, {arg2}"

        result = await test_tool(server, "hello", 42)

        assert "result: hello, 42" in result
        assert "[conflict check done]" in result
        server.rate_limiter.check_rate_limit.assert_called_once_with("test_operation")

    @pytest.mark.asyncio
    async def test_async_tool_with_custom_rate_limit_operation(self):
        """Test that custom rate limit operation name is used."""
        server = MockServer()

        @zim_tool("search", rate_limit_operation="search")
        async def search_tool(server, query: str) -> str:
            return f"searching: {query}"

        result = await search_tool(server, "test query")

        assert "searching: test query" in result
        server.rate_limiter.check_rate_limit.assert_called_once_with("search")

    @pytest.mark.asyncio
    async def test_async_tool_rate_limit_exceeded(self):
        """Test that rate limit errors are handled correctly."""
        server = MockServer()
        server.rate_limiter.check_rate_limit.side_effect = OpenZimMcpRateLimitError(
            "Rate limit exceeded"
        )

        @zim_tool("expensive operation")
        async def expensive_tool(server) -> str:
            return "should not reach here"

        result = await expensive_tool(server)

        assert "Error in expensive operation" in result
        assert "Rate limit exceeded" in result

    @pytest.mark.asyncio
    async def test_async_tool_exception_handling(self):
        """Test that exceptions in the tool are handled correctly."""
        server = MockServer()

        @zim_tool("failing operation")
        async def failing_tool(server) -> str:
            raise ValueError("Something went wrong")

        result = await failing_tool(server)

        assert "Error in failing operation" in result
        assert "Something went wrong" in result

    @pytest.mark.asyncio
    async def test_async_tool_without_conflict_check(self):
        """Test that conflict check can be disabled."""
        server = MockServer()

        @zim_tool("no conflict check", check_conflicts=False)
        async def no_conflict_tool(server) -> str:
            return "result without conflict check"

        result = await no_conflict_tool(server)

        assert "result without conflict check" == result
        assert "[conflict check done]" not in result

    @pytest.mark.asyncio
    async def test_async_tool_with_kwargs(self):
        """Test that kwargs are properly passed and logged."""
        server = MockServer()

        @zim_tool("kwargs operation")
        async def kwargs_tool(server, *, name: str = "default") -> str:
            return f"name: {name}"

        result = await kwargs_tool(server, name="custom")

        assert "name: custom" in result

    @pytest.mark.asyncio
    async def test_async_tool_filters_sensitive_kwargs(self):
        """Test that sensitive kwargs are filtered from error context."""
        server = MockServer()

        @zim_tool("sensitive operation")
        async def sensitive_tool(server, username: str, password: str) -> str:
            raise ValueError("Test error")

        result = await sensitive_tool(server, username="user", password="secret123")

        # The password should not appear in the error message context
        assert "secret123" not in result
        assert "user" in result or "username" in result

    @pytest.mark.asyncio
    async def test_async_tool_operation_name_to_rate_limit_operation(self):
        """Test that operation name is converted to rate limit operation correctly."""
        server = MockServer()

        @zim_tool("Get Article Structure")  # Has spaces and caps
        async def structure_tool(server) -> str:
            return "structure"

        await structure_tool(server)

        # Should be converted to lowercase with underscores
        server.rate_limiter.check_rate_limit.assert_called_once_with(
            "get_article_structure"
        )


class TestSyncZimToolDecorator:
    """Test sync_zim_tool synchronous decorator."""

    def test_basic_sync_tool_success(self):
        """Test that a basic sync tool executes successfully."""
        server = MockServer()

        @sync_zim_tool("sync operation")
        def sync_test_tool(server, arg1: str) -> str:
            return f"sync result: {arg1}"

        result = sync_test_tool(server, "hello")

        assert "sync result: hello" in result
        assert "[conflict check done]" in result
        server.rate_limiter.check_rate_limit.assert_called_once_with("sync_operation")

    def test_sync_tool_rate_limit_exceeded(self):
        """Test that rate limit errors are handled in sync tools."""
        server = MockServer()
        server.rate_limiter.check_rate_limit.side_effect = OpenZimMcpRateLimitError(
            "Rate limit exceeded"
        )

        @sync_zim_tool("sync expensive")
        def sync_expensive_tool(server) -> str:
            return "should not reach"

        result = sync_expensive_tool(server)

        assert "Error in sync expensive" in result

    def test_sync_tool_exception_handling(self):
        """Test that exceptions in sync tools are handled correctly."""
        server = MockServer()

        @sync_zim_tool("sync failing")
        def sync_failing_tool(server) -> str:
            raise RuntimeError("Sync failure")

        result = sync_failing_tool(server)

        assert "Error in sync failing" in result
        assert "Sync failure" in result

    def test_sync_tool_without_conflict_check(self):
        """Test that conflict check can be disabled in sync tools."""
        server = MockServer()

        @sync_zim_tool("sync no conflict", check_conflicts=False)
        def sync_no_conflict_tool(server) -> str:
            return "sync result"

        result = sync_no_conflict_tool(server)

        assert result == "sync result"
        assert "[conflict check done]" not in result

    def test_sync_tool_with_custom_rate_limit(self):
        """Test sync tool with custom rate limit operation."""
        server = MockServer()

        @sync_zim_tool("list files", rate_limit_operation="list")
        def sync_list_tool(server) -> str:
            return "files listed"

        sync_list_tool(server)

        server.rate_limiter.check_rate_limit.assert_called_once_with("list")

    def test_sync_tool_with_args_in_error(self):
        """Test that args are included in error context for sync tools."""
        server = MockServer()

        @sync_zim_tool("sync args")
        def sync_args_tool(server, path: str, name: str) -> str:
            raise ValueError("Args test error")

        result = sync_args_tool(server, "/some/path", "test_name")

        assert "Error in sync args" in result
        # Args should be in context (limited to first 2)
        assert "Args test error" in result


class TestDecoratorPreservesMetadata:
    """Test that decorators preserve function metadata."""

    @pytest.mark.asyncio
    async def test_async_decorator_preserves_name(self):
        """Test that async decorator preserves function name."""

        @zim_tool("test")
        async def my_named_function(server) -> str:
            """My docstring."""
            return "result"

        # functools.wraps should preserve these
        assert my_named_function.__name__ == "my_named_function"
        assert "My docstring" in my_named_function.__doc__

    def test_sync_decorator_preserves_name(self):
        """Test that sync decorator preserves function name."""

        @sync_zim_tool("test")
        def my_sync_function(server) -> str:
            """Sync docstring."""
            return "result"

        assert my_sync_function.__name__ == "my_sync_function"
        assert "Sync docstring" in my_sync_function.__doc__


class TestDecoratorLogging:
    """Test that decorators log appropriately."""

    @pytest.mark.asyncio
    async def test_async_tool_logs_rate_limit_warning(self, caplog):
        """Test that rate limit exceeded is logged as warning."""
        server = MockServer()
        server.rate_limiter.check_rate_limit.side_effect = OpenZimMcpRateLimitError(
            "Rate limit exceeded"
        )

        @zim_tool("logged operation")
        async def logged_tool(server) -> str:
            return "result"

        with caplog.at_level(logging.WARNING):
            await logged_tool(server)

        assert any("Rate limit exceeded" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_async_tool_logs_error(self, caplog):
        """Test that exceptions are logged as errors."""
        server = MockServer()

        @zim_tool("error operation")
        async def error_tool(server) -> str:
            raise ValueError("Test error for logging")

        with caplog.at_level(logging.ERROR):
            await error_tool(server)

        assert any(
            "Error in error operation" in record.message for record in caplog.records
        )

    def test_sync_tool_logs_rate_limit_warning(self, caplog):
        """Test that sync tool rate limit exceeded is logged as warning."""
        server = MockServer()
        server.rate_limiter.check_rate_limit.side_effect = OpenZimMcpRateLimitError(
            "Sync rate limit exceeded"
        )

        @sync_zim_tool("sync logged")
        def sync_logged_tool(server) -> str:
            return "result"

        with caplog.at_level(logging.WARNING):
            sync_logged_tool(server)

        assert any("Rate limit exceeded" in record.message for record in caplog.records)


class TestDecoratorEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_empty_operation_name(self):
        """Test decorator with empty operation name."""
        server = MockServer()

        @zim_tool("")
        async def empty_op_tool(server) -> str:
            return "result"

        result = await empty_op_tool(server)
        assert "result" in result

    @pytest.mark.asyncio
    async def test_operation_name_with_special_chars(self):
        """Test decorator with special characters in operation name."""
        server = MockServer()

        @zim_tool("get entry (binary)")
        async def special_tool(server) -> str:
            return "result"

        await special_tool(server)

        # The rate limit operation should have spaces replaced with underscores
        server.rate_limiter.check_rate_limit.assert_called_once_with(
            "get_entry_(binary)"
        )

    @pytest.mark.asyncio
    async def test_tool_returning_empty_string(self):
        """Test that tools can return empty strings."""
        server = MockServer()

        @zim_tool("empty return")
        async def empty_return_tool(server) -> str:
            return ""

        result = await empty_return_tool(server)
        # Should have conflict check appended to empty string
        assert "[conflict check done]" in result

    @pytest.mark.asyncio
    async def test_tool_with_none_in_kwargs(self):
        """Test that tools handle None values in kwargs."""
        server = MockServer()

        @zim_tool("none kwargs")
        async def none_kwargs_tool(server, value=None) -> str:
            raise ValueError("None test")

        result = await none_kwargs_tool(server, value=None)
        assert "Error in none kwargs" in result

    def test_sync_tool_returning_empty_string(self):
        """Test that sync tools can return empty strings."""
        server = MockServer()

        @sync_zim_tool("sync empty")
        def sync_empty_tool(server) -> str:
            return ""

        result = sync_empty_tool(server)
        assert "[conflict check done]" in result
