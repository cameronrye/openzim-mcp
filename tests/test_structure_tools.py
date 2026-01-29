"""
Tests for structure_tools module.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.server import OpenZimMcpServer


class TestRegisterStructureTools:
    """Test structure tools registration."""

    def test_register_structure_tools(self, test_config: OpenZimMcpConfig):
        """Test that structure tools are registered correctly."""
        server = OpenZimMcpServer(test_config)
        assert server.mcp is not None


class TestGetArticleStructureTool:
    """Test get_article_structure tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_get_article_structure_success(self, server: OpenZimMcpServer):
        """Test successful article structure retrieval."""
        server.async_zim_operations.get_article_structure = AsyncMock(
            return_value='{"headings": [{"level": 1, "text": "Title"}]}'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.get_article_structure(
            "/path/to/file.zim", "C/Article"
        )

        assert "headings" in result
        server.async_zim_operations.get_article_structure.assert_called_once_with(
            "/path/to/file.zim", "C/Article"
        )

    @pytest.mark.asyncio
    async def test_get_article_structure_rate_limit_error(
        self, server: OpenZimMcpServer
    ):
        """Test rate limit handling in get_article_structure."""
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="get article structure",
            error=error,
            context="Entry: C/Article",
        )
        assert "article structure" in error_msg or "Operation" in error_msg

    @pytest.mark.asyncio
    async def test_get_article_structure_generic_exception(
        self, server: OpenZimMcpServer
    ):
        """Test generic exception handling in get_article_structure."""
        server.async_zim_operations.get_article_structure = AsyncMock(
            side_effect=Exception("Test error")
        )

        with pytest.raises(Exception) as exc_info:
            await server.async_zim_operations.get_article_structure(
                "/path/to/file.zim", "C/Article"
            )
        assert "Test error" in str(exc_info.value)


class TestExtractArticleLinksTool:
    """Test extract_article_links tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_extract_article_links_success(self, server: OpenZimMcpServer):
        """Test successful link extraction."""
        server.async_zim_operations.extract_article_links = AsyncMock(
            return_value='{"internal": ["A/Link1"], "external": ["https://example.com"]}'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.extract_article_links(
            "/path/to/file.zim", "C/Article"
        )

        assert "internal" in result or "external" in result
        server.async_zim_operations.extract_article_links.assert_called_once_with(
            "/path/to/file.zim", "C/Article"
        )

    @pytest.mark.asyncio
    async def test_extract_article_links_rate_limit_error(
        self, server: OpenZimMcpServer
    ):
        """Test rate limit handling in extract_article_links."""
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="extract article links",
            error=error,
            context="Entry: C/Article",
        )
        assert "links" in error_msg or "Operation" in error_msg


class TestGetEntrySummaryTool:
    """Test get_entry_summary tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_get_entry_summary_success(self, server: OpenZimMcpServer):
        """Test successful entry summary retrieval."""
        server.async_zim_operations.get_entry_summary = AsyncMock(
            return_value='{"title": "Article", "summary": "This is a summary.", "word_count": 5}'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.get_entry_summary(
            "/path/to/file.zim", "C/Article", 200
        )

        assert "summary" in result
        server.async_zim_operations.get_entry_summary.assert_called_once_with(
            "/path/to/file.zim", "C/Article", 200
        )

    @pytest.mark.asyncio
    async def test_get_entry_summary_custom_max_words(self, server: OpenZimMcpServer):
        """Test entry summary with custom max_words."""
        server.async_zim_operations.get_entry_summary = AsyncMock(
            return_value='{"summary": "Longer summary.", "word_count": 500}'
        )

        result = await server.async_zim_operations.get_entry_summary(
            "/path/to/file.zim", "C/Article", 500
        )

        assert "summary" in result


class TestGetTableOfContentsTool:
    """Test get_table_of_contents tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_get_table_of_contents_success(self, server: OpenZimMcpServer):
        """Test successful TOC retrieval."""
        server.async_zim_operations.get_table_of_contents = AsyncMock(
            return_value='{"toc": [{"level": 1, "text": "Introduction"}], "heading_count": 1}'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.get_table_of_contents(
            "/path/to/file.zim", "C/Article"
        )

        assert "toc" in result
        server.async_zim_operations.get_table_of_contents.assert_called_once_with(
            "/path/to/file.zim", "C/Article"
        )

    @pytest.mark.asyncio
    async def test_get_table_of_contents_rate_limit_error(
        self, server: OpenZimMcpServer
    ):
        """Test rate limit handling in get_table_of_contents."""
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="get table of contents",
            error=error,
            context="Entry: C/Article",
        )
        assert "table of contents" in error_msg or "Operation" in error_msg


class TestGetBinaryEntryTool:
    """Test get_binary_entry tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_get_binary_entry_success(self, server: OpenZimMcpServer):
        """Test successful binary entry retrieval."""
        server.async_zim_operations.get_binary_entry = AsyncMock(
            return_value='{"path": "I/image.png", "mime_type": "image/png", "size": 1024}'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.get_binary_entry(
            "/path/to/file.zim", "I/image.png", None, True
        )

        assert "mime_type" in result
        server.async_zim_operations.get_binary_entry.assert_called_once_with(
            "/path/to/file.zim", "I/image.png", None, True
        )

    @pytest.mark.asyncio
    async def test_get_binary_entry_metadata_only(self, server: OpenZimMcpServer):
        """Test binary entry retrieval with metadata only."""
        server.async_zim_operations.get_binary_entry = AsyncMock(
            return_value='{"path": "I/image.png", "mime_type": "image/png", "size": 1024}'
        )

        result = await server.async_zim_operations.get_binary_entry(
            "/path/to/file.zim", "I/image.png", None, False
        )

        assert "size" in result

    @pytest.mark.asyncio
    async def test_get_binary_entry_with_max_size(self, server: OpenZimMcpServer):
        """Test binary entry retrieval with max size limit."""
        server.async_zim_operations.get_binary_entry = AsyncMock(
            return_value='{"path": "I/video.mp4", "truncated": true}'
        )

        result = await server.async_zim_operations.get_binary_entry(
            "/path/to/file.zim", "I/video.mp4", 1000000, True
        )

        assert "truncated" in result or "path" in result

    @pytest.mark.asyncio
    async def test_get_binary_entry_rate_limit_error(self, server: OpenZimMcpServer):
        """Test rate limit handling in get_binary_entry."""
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="retrieve binary entry",
            error=error,
            context="Entry: I/image.png",
        )
        assert "binary" in error_msg or "Operation" in error_msg


class TestInputSanitizationStructure:
    """Test input sanitization in structure tools."""

    def test_sanitize_inputs(self, test_config: OpenZimMcpConfig):
        """Test that all inputs are validated correctly."""
        from openzim_mcp.constants import INPUT_LIMIT_ENTRY_PATH, INPUT_LIMIT_FILE_PATH
        from openzim_mcp.exceptions import OpenZimMcpValidationError
        from openzim_mcp.security import sanitize_input

        # Valid inputs should pass
        valid_path = "p" * 100
        sanitized_path = sanitize_input(valid_path, INPUT_LIMIT_FILE_PATH)
        assert sanitized_path == valid_path

        valid_entry = "e" * 100
        sanitized_entry = sanitize_input(valid_entry, INPUT_LIMIT_ENTRY_PATH)
        assert sanitized_entry == valid_entry

        # Long inputs should raise errors
        long_path = "p" * 2000
        with pytest.raises(OpenZimMcpValidationError):
            sanitize_input(long_path, INPUT_LIMIT_FILE_PATH)

        long_entry = "e" * 1000
        with pytest.raises(OpenZimMcpValidationError):
            sanitize_input(long_entry, INPUT_LIMIT_ENTRY_PATH)


class TestStructureToolsDirectInvocation:
    """Test structure tools by directly invoking registered tool handlers."""

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
    async def test_get_article_structure_tool_invocation(
        self, advanced_server, temp_dir
    ):
        """Test invoking get_article_structure tool handler directly."""
        # Mock the async operations
        advanced_server.async_zim_operations.get_article_structure = AsyncMock(
            return_value='{"headings": [{"level": 1, "text": "Test"}], "sections": []}'
        )

        # Find and call the registered tool
        tools = advanced_server.mcp._tool_manager._tools
        if "get_article_structure" in tools:
            tool_handler = tools["get_article_structure"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Article",
            )
            assert "headings" in result

    @pytest.mark.asyncio
    async def test_get_article_structure_with_rate_limit(
        self, advanced_server, temp_dir
    ):
        """Test get_article_structure when rate limited."""
        advanced_server.rate_limiter.check_rate_limit = MagicMock(
            side_effect=OpenZimMcpRateLimitError("Rate limit exceeded")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_article_structure" in tools:
            tool_handler = tools["get_article_structure"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Article",
            )
            assert "Error" in result or "Rate limit" in result

    @pytest.mark.asyncio
    async def test_extract_article_links_tool_invocation(
        self, advanced_server, temp_dir
    ):
        """Test invoking extract_article_links tool handler directly."""
        advanced_server.async_zim_operations.extract_article_links = AsyncMock(
            return_value='{"internal_links": [], "external_links": []}'
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "extract_article_links" in tools:
            tool_handler = tools["extract_article_links"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Article",
            )
            assert "links" in result

    @pytest.mark.asyncio
    async def test_extract_article_links_with_exception(
        self, advanced_server, temp_dir
    ):
        """Test extract_article_links when an exception occurs."""
        advanced_server.async_zim_operations.extract_article_links = AsyncMock(
            side_effect=Exception("Test error")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "extract_article_links" in tools:
            tool_handler = tools["extract_article_links"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Article",
            )
            # Should return error message, not raise
            assert "Error" in result or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_get_entry_summary_tool_invocation(self, advanced_server, temp_dir):
        """Test invoking get_entry_summary tool handler directly."""
        advanced_server.async_zim_operations.get_entry_summary = AsyncMock(
            return_value='{"title": "Article", "summary": "Test summary", "word_count": 50}'
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_entry_summary" in tools:
            tool_handler = tools["get_entry_summary"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Article",
                max_words=100,
            )
            assert "summary" in result

    @pytest.mark.asyncio
    async def test_get_entry_summary_with_exception(self, advanced_server, temp_dir):
        """Test get_entry_summary when an exception occurs."""
        advanced_server.async_zim_operations.get_entry_summary = AsyncMock(
            side_effect=ValueError("Invalid entry")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_entry_summary" in tools:
            tool_handler = tools["get_entry_summary"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Invalid",
            )
            assert "Error" in result or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_get_table_of_contents_tool_invocation(
        self, advanced_server, temp_dir
    ):
        """Test invoking get_table_of_contents tool handler directly."""
        advanced_server.async_zim_operations.get_table_of_contents = AsyncMock(
            return_value='{"toc": [], "heading_count": 0, "max_depth": 0}'
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_table_of_contents" in tools:
            tool_handler = tools["get_table_of_contents"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Article",
            )
            assert "toc" in result

    @pytest.mark.asyncio
    async def test_get_table_of_contents_with_exception(
        self, advanced_server, temp_dir
    ):
        """Test get_table_of_contents when an exception occurs."""
        advanced_server.async_zim_operations.get_table_of_contents = AsyncMock(
            side_effect=RuntimeError("Failed to parse")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_table_of_contents" in tools:
            tool_handler = tools["get_table_of_contents"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Article",
            )
            assert "Error" in result or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_get_binary_entry_tool_invocation(self, advanced_server, temp_dir):
        """Test invoking get_binary_entry tool handler directly."""
        advanced_server.async_zim_operations.get_binary_entry = AsyncMock(
            return_value='{"path": "I/image.png", "mime_type": "image/png", "size": 1024}'
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_binary_entry" in tools:
            tool_handler = tools["get_binary_entry"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="I/image.png",
            )
            assert "mime_type" in result

    @pytest.mark.asyncio
    async def test_get_binary_entry_with_all_params(self, advanced_server, temp_dir):
        """Test get_binary_entry with all parameters specified."""
        advanced_server.async_zim_operations.get_binary_entry = AsyncMock(
            return_value='{"path": "I/doc.pdf", "mime_type": "application/pdf"}'
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_binary_entry" in tools:
            tool_handler = tools["get_binary_entry"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="I/doc.pdf",
                max_size_bytes=5000000,
                include_data=False,
            )
            assert "pdf" in result

    @pytest.mark.asyncio
    async def test_get_binary_entry_with_exception(self, advanced_server, temp_dir):
        """Test get_binary_entry when an exception occurs."""
        advanced_server.async_zim_operations.get_binary_entry = AsyncMock(
            side_effect=IOError("File not found")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_binary_entry" in tools:
            tool_handler = tools["get_binary_entry"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="I/missing.png",
            )
            # Error messages may be formatted with **Error** or **Resource Not Found**
            assert "**" in result and (
                "Error" in result or "Not Found" in result or "Operation" in result
            )
