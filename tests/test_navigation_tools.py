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
    """Test search_with_filters tool functionality.

    Phase B: ``search_with_filters`` returns a structured
    ``SearchWithFiltersResponse`` dict (was markdown text). Async-op
    layer now exposes ``search_with_filters_data`` for the structured
    path; the legacy markdown ``search_with_filters`` method is retained
    as a compat surface.
    """

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_search_with_filters_success(self, server: OpenZimMcpServer):
        """Test successful filtered search returns structured payload."""
        server.async_zim_operations.search_with_filters_data = AsyncMock(
            return_value={
                "query": "query",
                "namespace_filter": None,
                "content_type_filter": None,
                "results": [{"path": "C/Article", "title": "Article", "snippet": ""}],
                "next_cursor": None,
                "total": 1,
                "done": True,
                "page_info": {"offset": 0, "limit": 10, "returned_count": 1},
                "_meta": {},
            }
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.search_with_filters_data(
            "/path/to/file.zim", "query", None, None, 10, 0
        )

        assert "results" in result
        assert result["results"][0]["title"] == "Article"

    @pytest.mark.asyncio
    async def test_search_with_filters_with_namespace(self, server: OpenZimMcpServer):
        """Test filtered search with namespace filter."""
        server.async_zim_operations.search_with_filters_data = AsyncMock(
            return_value={
                "query": "query",
                "namespace_filter": "A",
                "content_type_filter": None,
                "results": [],
                "next_cursor": None,
                "total": 0,
                "done": True,
                "page_info": {"offset": 0, "limit": 10, "returned_count": 0},
                "_meta": {},
            }
        )

        result = await server.async_zim_operations.search_with_filters_data(
            "/path/to/file.zim", "query", "A", None, 10, 0
        )

        assert "results" in result
        assert result["namespace_filter"] == "A"

    @pytest.mark.asyncio
    async def test_search_with_filters_with_content_type(
        self, server: OpenZimMcpServer
    ):
        """Test filtered search with content type filter."""
        server.async_zim_operations.search_with_filters_data = AsyncMock(
            return_value={
                "query": "query",
                "namespace_filter": None,
                "content_type_filter": "text/html",
                "results": [],
                "next_cursor": None,
                "total": 0,
                "done": True,
                "page_info": {"offset": 0, "limit": 10, "returned_count": 0},
                "_meta": {},
            }
        )

        result = await server.async_zim_operations.search_with_filters_data(
            "/path/to/file.zim", "query", None, "text/html", 10, 0
        )

        assert "results" in result
        assert result["content_type_filter"] == "text/html"

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
            return_value='{"results": ["Article1", "Article2"]}'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.get_search_suggestions(
            "/path/to/file.zim", "Art", 10
        )

        assert "results" in result
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
        advanced_server.async_zim_operations.browse_namespace_data = AsyncMock(
            return_value={
                "namespace": "C",
                "results": [{"path": "C/Article", "title": "Article"}],
                "next_cursor": None,
                "total": 1,
                "done": True,
                "page_info": {"offset": 0, "limit": 50, "returned_count": 1},
                "_meta": {},
            }
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
            assert isinstance(result, dict)
            assert "results" in result

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
            assert isinstance(result, dict)
            assert result.get("error") is True
            assert "must be between 1 and 200" in result.get("message", "")

            # Test limit too low
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                namespace="C",
                limit=0,  # < 1
                offset=0,
            )
            assert isinstance(result, dict)
            assert result.get("error") is True
            assert "must be between 1 and 200" in result.get("message", "")

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
            assert isinstance(result, dict)
            assert result.get("error") is True
            assert "must be non-negative" in result.get("message", "")

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
            assert isinstance(result, dict)
            assert result.get("error") is True
            message = result.get("message", "")
            assert "Rate limit" in message or "Operation" in message

    @pytest.mark.asyncio
    async def test_browse_namespace_with_exception(self, advanced_server, temp_dir):
        """Test browse_namespace when an exception occurs."""
        advanced_server.async_zim_operations.browse_namespace_data = AsyncMock(
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
            assert isinstance(result, dict)
            assert result.get("error") is True
            message = result.get("message", "")
            # Error messages may be formatted with **Error** / **Resource Not Found**
            # / **Operation** depending on the underlying exception classification.
            assert "**" in message and (
                "Error" in message or "Not Found" in message or "Operation" in message
            )

    @pytest.mark.asyncio
    async def test_search_with_filters_tool_invocation(self, advanced_server, temp_dir):
        """Test invoking search_with_filters tool handler directly."""
        advanced_server.async_zim_operations.search_with_filters_data = AsyncMock(
            return_value={
                "query": "test query",
                "namespace_filter": None,
                "content_type_filter": None,
                "results": [{"path": "C/Result1", "title": "Result 1", "snippet": ""}],
                "next_cursor": None,
                "total": 1,
                "done": True,
                "page_info": {"offset": 0, "limit": 10, "returned_count": 1},
                "_meta": {},
            }
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "search_with_filters" in tools:
            tool_handler = tools["search_with_filters"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                query="test query",
            )
            assert isinstance(result, dict)
            assert "results" in result
            assert result["results"][0]["path"] == "C/Result1"

    @pytest.mark.asyncio
    async def test_search_with_filters_all_params(self, advanced_server, temp_dir):
        """Test search_with_filters with all parameters."""
        advanced_server.async_zim_operations.search_with_filters_data = AsyncMock(
            return_value={
                "query": "test",
                "namespace_filter": "C",
                "content_type_filter": "text/html",
                "results": [],
                "next_cursor": None,
                "total": 0,
                "done": True,
                "page_info": {"offset": 10, "limit": 20, "returned_count": 0},
                "_meta": {},
            }
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
            assert isinstance(result, dict)
            assert "results" in result
            assert result["namespace_filter"] == "C"
            assert result["content_type_filter"] == "text/html"

    @pytest.mark.asyncio
    async def test_search_with_filters_invalid_limit(self, advanced_server, temp_dir):
        """Test search_with_filters with invalid limit returns error envelope."""
        tools = advanced_server.mcp._tool_manager._tools
        if "search_with_filters" in tools:
            tool_handler = tools["search_with_filters"].fn

            # Limit > 100
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                query="test",
                limit=150,
            )
            assert isinstance(result, dict)
            assert result.get("error") is True
            assert "must be between 1 and 100" in result.get("message", "")

    @pytest.mark.asyncio
    async def test_search_with_filters_negative_offset(self, advanced_server, temp_dir):
        """Test search_with_filters with negative offset returns error envelope."""
        tools = advanced_server.mcp._tool_manager._tools
        if "search_with_filters" in tools:
            tool_handler = tools["search_with_filters"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                query="test",
                offset=-5,
            )
            assert isinstance(result, dict)
            assert result.get("error") is True
            assert "must be non-negative" in result.get("message", "")

    @pytest.mark.asyncio
    async def test_search_with_filters_with_exception(self, advanced_server, temp_dir):
        """Test search_with_filters when an exception occurs."""
        advanced_server.async_zim_operations.search_with_filters_data = AsyncMock(
            side_effect=RuntimeError("Search failed")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "search_with_filters" in tools:
            tool_handler = tools["search_with_filters"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                query="test",
            )
            assert isinstance(result, dict)
            assert result.get("error") is True
            message = result.get("message", "")
            assert "**" in message and ("Error" in message or "Operation" in message)

    @pytest.mark.asyncio
    async def test_search_with_filters_returns_paginated_response(
        self, advanced_server, temp_dir
    ):
        """Smoke test: top-level Phase B contract keys are present."""
        advanced_server.async_zim_operations.search_with_filters_data = AsyncMock(
            return_value={
                "query": "evolution",
                "namespace_filter": "C",
                "content_type_filter": None,
                "results": [],
                "next_cursor": None,
                "total": 0,
                "done": True,
                "page_info": {"offset": 0, "limit": 10, "returned_count": 0},
                "_meta": {},
            }
        )
        tools = advanced_server.mcp._tool_manager._tools
        if "search_with_filters" not in tools:
            pytest.skip("search_with_filters tool not registered")
        tool_handler = tools["search_with_filters"].fn
        result = await tool_handler(
            zim_file_path=str(temp_dir / "test.zim"),
            query="evolution",
            namespace="C",
        )
        assert isinstance(result, dict)
        for key in ("results", "next_cursor", "total", "done", "page_info"):
            assert key in result
        assert result["query"] == "evolution"
        assert result["namespace_filter"] == "C"
        assert result["content_type_filter"] is None

    @pytest.mark.asyncio
    async def test_search_with_filters_cursor_round_trip(
        self, advanced_server, temp_dir
    ):
        """Cursor decoding overrides offset/limit/query/namespace/content_type."""
        from openzim_mcp.pagination import Cursor

        captured: dict = {}

        async def _capture(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return {
                "query": "evolution",
                "namespace_filter": "C",
                "content_type_filter": "text/html",
                "results": [],
                "next_cursor": None,
                "total": 0,
                "done": True,
                "page_info": {"offset": 50, "limit": 25, "returned_count": 0},
                "_meta": {},
            }

        advanced_server.async_zim_operations.search_with_filters_data = AsyncMock(
            side_effect=_capture
        )
        tools = advanced_server.mcp._tool_manager._tools
        if "search_with_filters" not in tools:
            pytest.skip("search_with_filters tool not registered")
        cursor = Cursor.encode(
            tool="search_with_filters",
            state={
                "o": 50,
                "l": 25,
                "q": "evolution",
                "ns": "C",
                "ct": "text/html",
            },
        )
        tool_handler = tools["search_with_filters"].fn
        result = await tool_handler(
            zim_file_path=str(temp_dir / "test.zim"),
            cursor=cursor,
        )
        assert isinstance(result, dict)
        assert result.get("error") is not True
        # _data should have been called with the cursor-decoded values.
        # signature: (zim_file_path, query, namespace, content_type, limit, offset)
        called_args = captured["args"]
        assert called_args[1] == "evolution"  # query
        assert called_args[2] == "C"  # namespace
        assert called_args[3] == "text/html"  # content_type
        assert called_args[4] == 25  # limit
        assert called_args[5] == 50  # offset

    @pytest.mark.asyncio
    async def test_search_with_filters_cursor_mismatch(self, advanced_server, temp_dir):
        """A cursor issued by a different tool is rejected."""
        from openzim_mcp.pagination import Cursor

        wrong_cursor = Cursor.encode(
            tool="search_zim_file",
            state={"o": 0, "l": 10, "q": "test"},
        )
        tools = advanced_server.mcp._tool_manager._tools
        if "search_with_filters" not in tools:
            pytest.skip("search_with_filters tool not registered")
        tool_handler = tools["search_with_filters"].fn
        result = await tool_handler(
            zim_file_path=str(temp_dir / "test.zim"),
            cursor=wrong_cursor,
        )
        assert isinstance(result, dict)
        assert result.get("error") is True
        assert "search_zim_file" in result.get(
            "message", ""
        ) or "cannot be used" in result.get("message", "")

    @pytest.mark.asyncio
    async def test_get_search_suggestions_tool_invocation(
        self, advanced_server, temp_dir
    ):
        """Test invoking get_search_suggestions tool handler directly."""
        advanced_server.async_zim_operations.get_search_suggestions_data = AsyncMock(
            return_value={
                "partial_query": "Pyt",
                "results": [
                    {"text": "Python", "path": "C/Python", "type": "title_start_match"},
                    {
                        "text": "Python programming",
                        "path": "C/Python_programming",
                        "type": "title_start_match",
                    },
                ],
                "next_cursor": None,
                "total": 2,
                "done": True,
                "page_info": {"offset": 0, "limit": 10, "returned_count": 2},
            }
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_search_suggestions" in tools:
            tool_handler = tools["get_search_suggestions"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                partial_query="Pyt",
                limit=10,
            )
            assert isinstance(result, dict)
            assert "results" in result
            assert isinstance(result["results"], list)
            assert result["next_cursor"] is None
            assert result["done"] is True
            assert result["total"] == len(result["results"])

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
            assert isinstance(result, dict)
            assert result.get("error") is True
            assert "must be between 1 and 50" in result.get("message", "")

            # Limit too low
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                partial_query="test",
                limit=0,  # < 1
            )
            assert isinstance(result, dict)
            assert result.get("error") is True
            assert "must be between 1 and 50" in result.get("message", "")

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
            assert isinstance(result, dict)
            assert result.get("error") is True
            message = result.get("message", "")
            assert "Rate limit" in message or "Operation" in message

    @pytest.mark.asyncio
    async def test_get_search_suggestions_with_exception(
        self, advanced_server, temp_dir
    ):
        """Test get_search_suggestions when an exception occurs."""
        advanced_server.async_zim_operations.get_search_suggestions_data = AsyncMock(
            side_effect=ValueError("Invalid query")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_search_suggestions" in tools:
            tool_handler = tools["get_search_suggestions"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                partial_query="test",
            )
            assert isinstance(result, dict)
            assert result.get("error") is True
            message = result.get("message", "")
            assert "Error" in message or "error" in message.lower()


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
        advanced_server.async_zim_operations.walk_namespace_data = AsyncMock(
            side_effect=AssertionError("backend should not be called for invalid limit")
        )

        tools = advanced_server.mcp._tool_manager._tools
        assert "walk_namespace" in tools
        tool_handler = tools["walk_namespace"].fn
        result = await tool_handler(
            zim_file_path=str(temp_dir / "test.zim"),
            namespace="C",
            cursor=None,
            limit=100000,
        )
        assert isinstance(result, dict)
        assert result.get("error") is True
        assert "must be between 1 and 500" in result.get("message", "")
        advanced_server.async_zim_operations.walk_namespace_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_walk_namespace_rejects_limit_too_low(
        self, advanced_server, temp_dir
    ):
        """Reject limit < 1 with a validation error."""
        advanced_server.async_zim_operations.walk_namespace_data = AsyncMock(
            side_effect=AssertionError("backend should not be called for invalid limit")
        )

        tools = advanced_server.mcp._tool_manager._tools
        assert "walk_namespace" in tools
        tool_handler = tools["walk_namespace"].fn
        result = await tool_handler(
            zim_file_path=str(temp_dir / "test.zim"),
            namespace="C",
            cursor=None,
            limit=0,
        )
        assert isinstance(result, dict)
        assert result.get("error") is True
        assert "must be between 1 and 500" in result.get("message", "")
        advanced_server.async_zim_operations.walk_namespace_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_walk_namespace_rejects_cross_tool_cursor(
        self, advanced_server, temp_dir
    ):
        """A cursor issued by another tool must be rejected before backend access.

        v2 Phase B: cursors are tool-bound. A cursor encoded with
        ``tool="browse_namespace"`` cannot be used by ``walk_namespace``.
        """
        from openzim_mcp.pagination import Cursor

        advanced_server.async_zim_operations.walk_namespace_data = AsyncMock(
            side_effect=AssertionError(
                "backend should not be called for cross-tool cursor"
            )
        )

        tools = advanced_server.mcp._tool_manager._tools
        assert "walk_namespace" in tools
        tool_handler = tools["walk_namespace"].fn
        wrong_cursor = Cursor.encode(
            tool="browse_namespace", state={"o": 0, "l": 50, "ns": "C"}
        )
        result = await tool_handler(
            zim_file_path=str(temp_dir / "test.zim"),
            namespace="C",
            cursor=wrong_cursor,
            limit=200,
        )
        assert isinstance(result, dict)
        assert result.get("error") is True
        advanced_server.async_zim_operations.walk_namespace_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_walk_namespace_rejects_malformed_cursor(
        self, advanced_server, temp_dir
    ):
        """A non-base64 / non-JSON cursor must surface a validation error."""
        advanced_server.async_zim_operations.walk_namespace_data = AsyncMock(
            side_effect=AssertionError(
                "backend should not be called for malformed cursor"
            )
        )

        tools = advanced_server.mcp._tool_manager._tools
        tool_handler = tools["walk_namespace"].fn
        result = await tool_handler(
            zim_file_path=str(temp_dir / "test.zim"),
            namespace="C",
            cursor="!!!not-base64!!!",
            limit=200,
        )
        assert isinstance(result, dict)
        assert result.get("error") is True
        advanced_server.async_zim_operations.walk_namespace_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_walk_namespace_accepts_valid_bounds(self, advanced_server, temp_dir):
        """Valid limit/cursor must reach the backend."""
        advanced_server.async_zim_operations.walk_namespace_data = AsyncMock(
            return_value={
                "namespace": "C",
                "results": [],
                "next_cursor": None,
                "total": None,
                "done": True,
                "page_info": {"offset": 0, "limit": 200, "returned_count": 0},
                "scanned_count": 0,
                "scanned_through_id": None,
                "archive_entry_count": 0,
                "_meta": {},
            }
        )

        tools = advanced_server.mcp._tool_manager._tools
        assert "walk_namespace" in tools
        tool_handler = tools["walk_namespace"].fn
        result = await tool_handler(
            zim_file_path=str(temp_dir / "test.zim"),
            namespace="C",
            cursor=None,
            limit=200,
        )
        assert isinstance(result, dict)
        assert "results" in result
        advanced_server.async_zim_operations.walk_namespace_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_walk_namespace_decodes_opaque_cursor(
        self, advanced_server, temp_dir
    ):
        """An opaque cursor encoded with t='walk_namespace' decodes to scan_at/limit.

        The decoded ``s.l`` overrides the function-arg ``limit`` (cursor wins
        on conflict per response-contract spec) and ``s.scan_at`` becomes
        the starting point for the backend scan.
        """
        from openzim_mcp.pagination import Cursor

        captured: dict = {}

        async def _fake_walk(zim_file_path, namespace, cursor_state=None, limit=200):
            captured["cursor_state"] = cursor_state
            captured["limit"] = limit
            return {
                "namespace": "C",
                "results": [],
                "next_cursor": None,
                "total": None,
                "done": True,
                "page_info": {"offset": 42, "limit": 50, "returned_count": 0},
                "scanned_count": 0,
                "scanned_through_id": None,
                "archive_entry_count": 0,
                "_meta": {},
            }

        advanced_server.async_zim_operations.walk_namespace_data = AsyncMock(
            side_effect=_fake_walk
        )

        tools = advanced_server.mcp._tool_manager._tools
        tool_handler = tools["walk_namespace"].fn
        good_cursor = Cursor.encode(
            tool="walk_namespace", state={"scan_at": 42, "l": 50}
        )
        result = await tool_handler(
            zim_file_path=str(temp_dir / "test.zim"),
            namespace="C",
            cursor=good_cursor,
            # Function-arg limit must be overridden by the cursor's "l".
            limit=200,
        )
        assert isinstance(result, dict)
        assert "results" in result
        # cursor's "l" wins over function-arg limit.
        assert captured["limit"] == 50
        assert captured["cursor_state"] == {"scan_at": 42, "l": 50}


# ---------------------------------------------------------------------------
# Phase-A _meta envelope smoke tests
# ---------------------------------------------------------------------------


class TestNamespaceDataMethodsMeta:
    """Verify that _meta is attached on every return path of the three
    namespace *_data methods (list_namespaces_data, browse_namespace_data,
    walk_namespace_data).
    """

    @pytest.fixture
    def zim_ops(
        self,
        test_config: OpenZimMcpConfig,
        path_validator,
        openzim_mcp_cache,
        content_processor,
    ):
        from openzim_mcp.zim_operations import ZimOperations

        return ZimOperations(
            test_config, path_validator, openzim_mcp_cache, content_processor
        )

    def _zim_file(self, temp_dir):
        from pathlib import Path

        p = Path(temp_dir) / "test.zim"
        p.write_bytes(b"")
        return p

    def test_list_namespaces_data_fresh_attaches_meta(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """Fresh path attaches _meta envelope."""
        zim_file = self._zim_file(temp_dir)
        fake_ns = {
            "total_entries": 10,
            "sampled_entries": 10,
            "has_new_namespace_scheme": False,
            "is_total_authoritative": True,
            "discovery_method": "full_iteration",
            "namespaces": {},
        }
        monkeypatch.setattr(
            zim_ops, "_list_archive_namespaces", lambda *a, **kw: fake_ns
        )
        from unittest.mock import MagicMock, patch

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.list_namespaces_data(str(zim_file))

        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1

    def test_list_namespaces_data_cached_payload_returned_verbatim(
        self, zim_ops, temp_dir
    ):
        """Cache stores the post-attach payload; cache hit returns it
        verbatim (Phase B #12 fix — no recomputation on read)."""
        zim_file = self._zim_file(temp_dir)
        validated = zim_ops.path_validator.validate_path(str(zim_file))
        validated = zim_ops.path_validator.validate_zim_file(validated)
        cache_key = f"namespaces_data:v2b:{validated}"
        seeded = {
            "total_entries": 5,
            "namespaces": {},
            "_meta": {"tokens_est": 12, "chars": 40, "truncated": False},
        }
        zim_ops.cache.set(cache_key, seeded)

        result = zim_ops.list_namespaces_data(str(zim_file))
        assert result is seeded
        assert result["_meta"]["tokens_est"] == 12

    def test_browse_namespace_data_fresh_attaches_meta(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """browse_namespace_data fresh path attaches _meta."""
        zim_file = self._zim_file(temp_dir)
        # _browse_namespace_entries still returns the inner shape with
        # legacy keys (entries/total_in_namespace/...); the contract
        # rename is performed in browse_namespace_data after this call.
        fake_result = {
            "namespace": "C",
            "entries": [],
            "total_in_namespace": 0,
            "total_in_namespace_is_lower_bound": False,
            "offset": 0,
            "limit": 50,
            "returned_count": 0,
            "sampling_based": False,
            "discovery_method": "full_iteration",
            "is_total_authoritative": True,
            "results_may_be_incomplete": False,
        }
        monkeypatch.setattr(
            zim_ops,
            "_browse_namespace_entries",
            lambda *a, **kw: fake_result,
        )
        from unittest.mock import MagicMock, patch

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.browse_namespace_data(str(zim_file), "C")

        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1

    def test_browse_namespace_data_cached_payload_returned_verbatim(
        self, zim_ops, temp_dir
    ):
        """Cache stores the post-attach payload; cache hit returns it
        verbatim (Phase B #12 fix — no recomputation on read)."""
        zim_file = self._zim_file(temp_dir)
        validated = zim_ops.path_validator.validate_path(str(zim_file))
        validated = zim_ops.path_validator.validate_zim_file(validated)
        cache_key = f"browse_ns_data:v2b:{validated}:C:50:0"
        seeded = {
            "namespace": "C",
            "results": [],
            "next_cursor": None,
            "total": 0,
            "done": True,
            "page_info": {"offset": 0, "limit": 50, "returned_count": 0},
            "_meta": {"tokens_est": 19, "chars": 110, "truncated": False},
        }
        zim_ops.cache.set(cache_key, seeded)

        result = zim_ops.browse_namespace_data(str(zim_file), "C")
        assert result is seeded
        assert result["_meta"]["tokens_est"] >= 1

    def test_walk_namespace_data_attaches_meta(self, zim_ops, temp_dir, monkeypatch):
        """walk_namespace_data attaches _meta on the main return path."""
        zim_file = self._zim_file(temp_dir)
        from unittest.mock import MagicMock, patch

        mock_archive_obj = MagicMock()
        mock_archive_obj.has_new_namespace_scheme = False
        mock_archive_obj.entry_count = 0
        # _get_entry_by_id is never called for empty archive

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = mock_archive_obj
            result = zim_ops.walk_namespace_data(
                str(zim_file), "C", cursor_state=None, limit=10
            )

        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1
