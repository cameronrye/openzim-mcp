"""Tests for navigation_tools module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.server import OpenZimMcpServer


class TestRegisterNavigationTools:
    """Test navigation tools registration."""

    def test_register_navigation_tools(self, test_config: OpenZimMcpConfig):
        """Test that navigation tools are registered correctly."""
        server = OpenZimMcpServer(test_config)
        assert server.mcp is not None


class TestBrowseNamespaceTool:
    """Test browse_namespace tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_browse_namespace_success(self, server: OpenZimMcpServer):
        """Test successful namespace browsing."""
        server.async_zim_operations.browse_namespace = AsyncMock(
            return_value='{"entries": [{"path": "A/Article"}]}'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.browse_namespace(
            "/path/to/file.zim", "A", 50, 0
        )

        assert "entries" in result
        server.async_zim_operations.browse_namespace.assert_called_once_with(
            "/path/to/file.zim", "A", 50, 0
        )

    # NOTE: validation behaviour for browse_namespace (limit out of range,
    # negative offset) is exercised end-to-end against the registered MCP
    # tool handler in TestNavigationToolHandlers below — see
    # ``test_browse_namespace_with_invalid_limit`` and
    # ``test_browse_namespace_with_negative_offset``.

    @pytest.mark.asyncio
    async def test_browse_namespace_rate_limit_error(self, server: OpenZimMcpServer):
        """Test rate limit handling in browse_namespace."""
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="browse namespace",
            error=error,
            context="Namespace: A",
        )
        assert "browse namespace" in error_msg or "Operation" in error_msg


class TestSearchWithFiltersTool:
    """Test search_with_filters tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_search_with_filters_success(self, server: OpenZimMcpServer):
        """Test successful filtered search."""
        server.async_zim_operations.search_with_filters = AsyncMock(
            return_value='{"results": [{"title": "Article"}]}'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.search_with_filters(
            "/path/to/file.zim", "query", None, None, 10, 0
        )

        assert "results" in result

    @pytest.mark.asyncio
    async def test_search_with_filters_with_namespace(self, server: OpenZimMcpServer):
        """Test filtered search with namespace filter."""
        server.async_zim_operations.search_with_filters = AsyncMock(
            return_value='{"results": []}'
        )

        result = await server.async_zim_operations.search_with_filters(
            "/path/to/file.zim", "query", "A", None, 10, 0
        )

        assert "results" in result

    @pytest.mark.asyncio
    async def test_search_with_filters_with_content_type(
        self, server: OpenZimMcpServer
    ):
        """Test filtered search with content type filter."""
        server.async_zim_operations.search_with_filters = AsyncMock(
            return_value='{"results": []}'
        )

        result = await server.async_zim_operations.search_with_filters(
            "/path/to/file.zim", "query", None, "text/html", 10, 0
        )

        assert "results" in result

    # NOTE: search_with_filters validation (limit out of range, negative
    # offset) is exercised end-to-end via the registered MCP tool handler
    # in TestNavigationToolHandlers — ``test_search_with_filters_invalid_limit``
    # and ``test_search_with_filters_negative_offset``.


class TestGetSearchSuggestionsTool:
    """Test get_search_suggestions tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_get_search_suggestions_success(self, server: OpenZimMcpServer):
        """Test successful search suggestions retrieval."""
        server.async_zim_operations.get_search_suggestions = AsyncMock(
            return_value='{"suggestions": ["Article1", "Article2"]}'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.get_search_suggestions(
            "/path/to/file.zim", "Art", 10
        )

        assert "suggestions" in result
        server.async_zim_operations.get_search_suggestions.assert_called_once_with(
            "/path/to/file.zim", "Art", 10
        )

    # NOTE: get_search_suggestions limit-validation behaviour is exercised
    # against the real tool handler in
    # ``TestNavigationToolHandlers.test_get_search_suggestions_invalid_limit``.

    @pytest.mark.asyncio
    async def test_get_search_suggestions_rate_limit_error(
        self, server: OpenZimMcpServer
    ):
        """Test rate limit handling in get_search_suggestions."""
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="get search suggestions",
            error=error,
            context="Query: 'test'",
        )
        assert "search suggestions" in error_msg or "Operation" in error_msg


class TestInputSanitizationNavigation:
    """Test input sanitization in navigation tools."""

    def test_sanitize_all_inputs(self, test_config: OpenZimMcpConfig):
        """Test that all inputs are validated correctly."""
        from openzim_mcp.constants import (
            INPUT_LIMIT_CONTENT_TYPE,
            INPUT_LIMIT_FILE_PATH,
            INPUT_LIMIT_NAMESPACE,
            INPUT_LIMIT_PARTIAL_QUERY,
            INPUT_LIMIT_QUERY,
        )
        from openzim_mcp.exceptions import OpenZimMcpValidationError
        from openzim_mcp.security import sanitize_input

        # Test valid inputs pass
        assert sanitize_input("valid_path", INPUT_LIMIT_FILE_PATH) == "valid_path"
        assert sanitize_input("query", INPUT_LIMIT_QUERY) == "query"
        assert sanitize_input("A", INPUT_LIMIT_NAMESPACE) == "A"
        assert sanitize_input("text/html", INPUT_LIMIT_CONTENT_TYPE) == "text/html"
        assert sanitize_input("partial", INPUT_LIMIT_PARTIAL_QUERY) == "partial"

        # Test overly long inputs raise errors
        with pytest.raises(OpenZimMcpValidationError):
            sanitize_input("x" * 2000, INPUT_LIMIT_FILE_PATH)

        with pytest.raises(OpenZimMcpValidationError):
            sanitize_input("x" * 1000, INPUT_LIMIT_QUERY)

        with pytest.raises(OpenZimMcpValidationError):
            sanitize_input("x" * 200, INPUT_LIMIT_NAMESPACE)

        with pytest.raises(OpenZimMcpValidationError):
            sanitize_input("x" * 200, INPUT_LIMIT_CONTENT_TYPE)

        with pytest.raises(OpenZimMcpValidationError):
            sanitize_input("x" * 500, INPUT_LIMIT_PARTIAL_QUERY)


class TestNavigationToolsDirectInvocation:
    """Test navigation tools by directly invoking registered tool handlers."""

    @pytest.fixture
    def advanced_server(self, temp_dir):
        """Create a server in advanced mode."""
        from openzim_mcp.config import CacheConfig, OpenZimMcpConfig

        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        return OpenZimMcpServer(config)

    @pytest.mark.asyncio
    async def test_browse_namespace_tool_invocation(self, advanced_server, temp_dir):
        """Test invoking browse_namespace tool handler directly."""
        advanced_server.async_zim_operations.browse_namespace = AsyncMock(
            return_value='{"entries": [{"path": "C/Article", "title": "Article"}]}'
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "browse_namespace" in tools:
            tool_handler = tools["browse_namespace"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                namespace="C",
                limit=50,
                offset=0,
            )
            assert "entries" in result

    @pytest.mark.asyncio
    async def test_browse_namespace_with_invalid_limit(self, advanced_server, temp_dir):
        """Test browse_namespace with limit out of range."""
        tools = advanced_server.mcp._tool_manager._tools
        if "browse_namespace" in tools:
            tool_handler = tools["browse_namespace"].fn

            # Test limit too high
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                namespace="C",
                limit=300,  # > 200
                offset=0,
            )
            assert "must be between 1 and 200" in result

            # Test limit too low
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                namespace="C",
                limit=0,  # < 1
                offset=0,
            )
            assert "must be between 1 and 200" in result

    @pytest.mark.asyncio
    async def test_browse_namespace_with_negative_offset(
        self, advanced_server, temp_dir
    ):
        """Test browse_namespace with negative offset."""
        tools = advanced_server.mcp._tool_manager._tools
        if "browse_namespace" in tools:
            tool_handler = tools["browse_namespace"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                namespace="C",
                limit=50,
                offset=-1,  # Negative
            )
            assert "must be non-negative" in result

    @pytest.mark.asyncio
    async def test_browse_namespace_with_rate_limit(self, advanced_server, temp_dir):
        """Test browse_namespace when rate limited."""
        advanced_server.rate_limiter.check_rate_limit = MagicMock(
            side_effect=OpenZimMcpRateLimitError("Rate limit exceeded")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "browse_namespace" in tools:
            tool_handler = tools["browse_namespace"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                namespace="C",
                limit=50,
                offset=0,
            )
            assert "Error" in result or "Rate limit" in result

    @pytest.mark.asyncio
    async def test_browse_namespace_with_exception(self, advanced_server, temp_dir):
        """Test browse_namespace when an exception occurs."""
        advanced_server.async_zim_operations.browse_namespace = AsyncMock(
            side_effect=Exception("Namespace not found")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "browse_namespace" in tools:
            tool_handler = tools["browse_namespace"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                namespace="X",
                limit=50,
                offset=0,
            )
            # Error messages may be formatted with **Error** or **Resource Not Found**
            assert "**" in result and (
                "Error" in result or "Not Found" in result or "Operation" in result
            )

    @pytest.mark.asyncio
    async def test_search_with_filters_tool_invocation(self, advanced_server, temp_dir):
        """Test invoking search_with_filters tool handler directly."""
        advanced_server.async_zim_operations.search_with_filters = AsyncMock(
            return_value='{"results": [{"title": "Result 1", "path": "C/Result1"}]}'
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "search_with_filters" in tools:
            tool_handler = tools["search_with_filters"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                query="test query",
            )
            assert "results" in result

    @pytest.mark.asyncio
    async def test_search_with_filters_all_params(self, advanced_server, temp_dir):
        """Test search_with_filters with all parameters."""
        advanced_server.async_zim_operations.search_with_filters = AsyncMock(
            return_value='{"results": []}'
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "search_with_filters" in tools:
            tool_handler = tools["search_with_filters"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                query="test",
                namespace="C",
                content_type="text/html",
                limit=20,
                offset=10,
            )
            assert "results" in result

    @pytest.mark.asyncio
    async def test_search_with_filters_invalid_limit(self, advanced_server, temp_dir):
        """Test search_with_filters with invalid limit."""
        tools = advanced_server.mcp._tool_manager._tools
        if "search_with_filters" in tools:
            tool_handler = tools["search_with_filters"].fn

            # Limit > 100
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                query="test",
                limit=150,
            )
            assert "must be between 1 and 100" in result

    @pytest.mark.asyncio
    async def test_search_with_filters_negative_offset(self, advanced_server, temp_dir):
        """Test search_with_filters with negative offset."""
        tools = advanced_server.mcp._tool_manager._tools
        if "search_with_filters" in tools:
            tool_handler = tools["search_with_filters"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                query="test",
                offset=-5,
            )
            assert "must be non-negative" in result

    @pytest.mark.asyncio
    async def test_search_with_filters_with_exception(self, advanced_server, temp_dir):
        """Test search_with_filters when an exception occurs."""
        advanced_server.async_zim_operations.search_with_filters = AsyncMock(
            side_effect=RuntimeError("Search failed")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "search_with_filters" in tools:
            tool_handler = tools["search_with_filters"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                query="test",
            )
            assert "Error" in result or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_get_search_suggestions_tool_invocation(
        self, advanced_server, temp_dir
    ):
        """Test invoking get_search_suggestions tool handler directly."""
        advanced_server.async_zim_operations.get_search_suggestions = AsyncMock(
            return_value='{"suggestions": ["Python", "Python programming"]}'
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_search_suggestions" in tools:
            tool_handler = tools["get_search_suggestions"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                partial_query="Pyt",
                limit=10,
            )
            assert "suggestions" in result

    @pytest.mark.asyncio
    async def test_get_search_suggestions_invalid_limit(
        self, advanced_server, temp_dir
    ):
        """Test get_search_suggestions with invalid limit."""
        tools = advanced_server.mcp._tool_manager._tools
        if "get_search_suggestions" in tools:
            tool_handler = tools["get_search_suggestions"].fn

            # Limit too high
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                partial_query="test",
                limit=100,  # > 50
            )
            assert "must be between 1 and 50" in result

            # Limit too low
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                partial_query="test",
                limit=0,  # < 1
            )
            assert "must be between 1 and 50" in result

    @pytest.mark.asyncio
    async def test_get_search_suggestions_with_rate_limit(
        self, advanced_server, temp_dir
    ):
        """Test get_search_suggestions when rate limited."""
        advanced_server.rate_limiter.check_rate_limit = MagicMock(
            side_effect=OpenZimMcpRateLimitError("Rate limit exceeded")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_search_suggestions" in tools:
            tool_handler = tools["get_search_suggestions"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                partial_query="test",
            )
            assert "Error" in result or "Rate limit" in result

    @pytest.mark.asyncio
    async def test_get_search_suggestions_with_exception(
        self, advanced_server, temp_dir
    ):
        """Test get_search_suggestions when an exception occurs."""
        advanced_server.async_zim_operations.get_search_suggestions = AsyncMock(
            side_effect=ValueError("Invalid query")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_search_suggestions" in tools:
            tool_handler = tools["get_search_suggestions"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                partial_query="test",
            )
            assert "Error" in result or "error" in result.lower()


class TestWalkNamespaceLimitValidation:
    """walk_namespace must enforce its documented 1-500 limit bound."""

    @pytest.fixture
    def advanced_server(self, temp_dir):
        """Create a server in advanced mode."""
        from openzim_mcp.config import CacheConfig, OpenZimMcpConfig

        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        return OpenZimMcpServer(config)

    @pytest.mark.asyncio
    async def test_walk_namespace_rejects_limit_too_high(
        self, advanced_server, temp_dir
    ):
        """Reject limit > 500 with a validation error before backend access."""
        # Backend should never be reached; raise loudly if it is.
        advanced_server.async_zim_operations.walk_namespace = AsyncMock(
            side_effect=AssertionError("backend should not be called for invalid limit")
        )

        tools = advanced_server.mcp._tool_manager._tools
        assert "walk_namespace" in tools
        tool_handler = tools["walk_namespace"].fn
        result = await tool_handler(
            zim_file_path=str(temp_dir / "test.zim"),
            namespace="C",
            cursor=0,
            limit=100000,
        )
        assert "must be between 1 and 500" in result
        advanced_server.async_zim_operations.walk_namespace.assert_not_called()

    @pytest.mark.asyncio
    async def test_walk_namespace_rejects_limit_too_low(
        self, advanced_server, temp_dir
    ):
        """Reject limit < 1 with a validation error."""
        advanced_server.async_zim_operations.walk_namespace = AsyncMock(
            side_effect=AssertionError("backend should not be called for invalid limit")
        )

        tools = advanced_server.mcp._tool_manager._tools
        assert "walk_namespace" in tools
        tool_handler = tools["walk_namespace"].fn
        result = await tool_handler(
            zim_file_path=str(temp_dir / "test.zim"),
            namespace="C",
            cursor=0,
            limit=0,
        )
        assert "must be between 1 and 500" in result
        advanced_server.async_zim_operations.walk_namespace.assert_not_called()

    @pytest.mark.asyncio
    async def test_walk_namespace_rejects_negative_cursor(
        self, advanced_server, temp_dir
    ):
        """Negative cursor must produce a validation error."""
        advanced_server.async_zim_operations.walk_namespace = AsyncMock(
            side_effect=AssertionError(
                "backend should not be called for invalid cursor"
            )
        )

        tools = advanced_server.mcp._tool_manager._tools
        assert "walk_namespace" in tools
        tool_handler = tools["walk_namespace"].fn
        result = await tool_handler(
            zim_file_path=str(temp_dir / "test.zim"),
            namespace="C",
            cursor=-1,
            limit=200,
        )
        assert "must be non-negative" in result
        advanced_server.async_zim_operations.walk_namespace.assert_not_called()

    @pytest.mark.asyncio
    async def test_walk_namespace_accepts_valid_bounds(self, advanced_server, temp_dir):
        """Valid limit/cursor must reach the backend."""
        advanced_server.async_zim_operations.walk_namespace = AsyncMock(
            return_value='{"entries": [], "next_cursor": 200, "done": false}'
        )

        tools = advanced_server.mcp._tool_manager._tools
        assert "walk_namespace" in tools
        tool_handler = tools["walk_namespace"].fn
        result = await tool_handler(
            zim_file_path=str(temp_dir / "test.zim"),
            namespace="C",
            cursor=0,
            limit=200,
        )
        assert "entries" in result
        advanced_server.async_zim_operations.walk_namespace.assert_called_once()
