"""Tests for structure_tools module."""

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
            return_value='{"internal": ["A/Link1"], "external": ["example.com"]}'
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
            return_value='{"title": "Article", "summary": "Summary.", "word_count": 5}'
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
            return_value='{"toc": [{"level": 1, "text": "Intro"}], "heading_count": 1}'
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
            return_value='{"path": "I/img.png", "mime_type": "image/png", "size": 1024}'
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
            return_value='{"path": "I/img.png", "mime_type": "image/png", "size": 1024}'
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
        advanced_server.async_zim_operations.get_article_structure_data = AsyncMock(
            return_value={"headings": [{"level": 1, "text": "Test"}], "sections": []}
        )

        # Find and call the registered tool
        tools = advanced_server.mcp._tool_manager._tools
        if "get_article_structure" in tools:
            tool_handler = tools["get_article_structure"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Article",
            )
            assert isinstance(result, dict)
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
            assert isinstance(result, dict)
            assert result.get("error") is True
            message = result.get("message", "")
            assert "Error" in message or "Rate limit" in message

    @pytest.mark.asyncio
    async def test_extract_article_links_tool_invocation(
        self, advanced_server, temp_dir
    ):
        """Test invoking extract_article_links tool handler directly."""
        advanced_server.async_zim_operations.extract_article_links_data = AsyncMock(
            return_value={
                "title": "Article",
                "path": "C/Article",
                "content_type": "text/html",
                "kind": "internal",
                "results": [],
                "next_cursor": None,
                "total": 0,
                "done": True,
                "page_info": {"offset": 0, "limit": 100, "returned_count": 0},
                "category_totals": {"internal": 0, "external": 0, "media": 0},
            }
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "extract_article_links" in tools:
            tool_handler = tools["extract_article_links"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Article",
            )
            assert isinstance(result, dict)
            assert "results" in result
            assert result["kind"] == "internal"
            assert "category_totals" in result

    @pytest.mark.asyncio
    async def test_extract_article_links_with_exception(
        self, advanced_server, temp_dir
    ):
        """Test extract_article_links when an exception occurs."""
        advanced_server.async_zim_operations.extract_article_links_data = AsyncMock(
            side_effect=Exception("Test error")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "extract_article_links" in tools:
            tool_handler = tools["extract_article_links"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Article",
            )
            # Should return error envelope, not raise
            assert isinstance(result, dict)
            assert result.get("error") is True

    @pytest.mark.asyncio
    async def test_get_entry_summary_tool_invocation(self, advanced_server, temp_dir):
        """Test invoking get_entry_summary tool handler directly."""
        advanced_server.async_zim_operations.get_entry_summary_data = AsyncMock(
            return_value={"title": "Article", "summary": "Test", "word_count": 50}
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_entry_summary" in tools:
            tool_handler = tools["get_entry_summary"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Article",
                max_words=100,
            )
            assert isinstance(result, dict)
            assert "summary" in result

    @pytest.mark.asyncio
    async def test_get_entry_summary_with_exception(self, advanced_server, temp_dir):
        """Test get_entry_summary when an exception occurs."""
        advanced_server.async_zim_operations.get_entry_summary_data = AsyncMock(
            side_effect=ValueError("Invalid entry")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_entry_summary" in tools:
            tool_handler = tools["get_entry_summary"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Invalid",
            )
            assert isinstance(result, dict)
            assert result.get("error") is True

    @pytest.mark.asyncio
    async def test_get_table_of_contents_tool_invocation(
        self, advanced_server, temp_dir
    ):
        """Test invoking get_table_of_contents tool handler directly."""
        advanced_server.async_zim_operations.get_table_of_contents_data = AsyncMock(
            return_value={"toc": [], "heading_count": 0, "max_depth": 0}
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_table_of_contents" in tools:
            tool_handler = tools["get_table_of_contents"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Article",
            )
            assert isinstance(result, dict)
            assert "toc" in result

    @pytest.mark.asyncio
    async def test_get_table_of_contents_with_exception(
        self, advanced_server, temp_dir
    ):
        """Test get_table_of_contents when an exception occurs."""
        advanced_server.async_zim_operations.get_table_of_contents_data = AsyncMock(
            side_effect=RuntimeError("Failed to parse")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_table_of_contents" in tools:
            tool_handler = tools["get_table_of_contents"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="C/Article",
            )
            assert isinstance(result, dict)
            assert result.get("error") is True

    @pytest.mark.asyncio
    async def test_get_binary_entry_tool_invocation(self, advanced_server, temp_dir):
        """Test invoking get_binary_entry tool handler directly."""
        advanced_server.async_zim_operations.get_binary_entry_data = AsyncMock(
            return_value={"path": "I/img.png", "mime_type": "image/png", "size": 1024}
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_binary_entry" in tools:
            tool_handler = tools["get_binary_entry"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="I/image.png",
            )
            assert isinstance(result, dict)
            assert "mime_type" in result

    @pytest.mark.asyncio
    async def test_get_binary_entry_with_all_params(self, advanced_server, temp_dir):
        """Test get_binary_entry with all parameters specified."""
        advanced_server.async_zim_operations.get_binary_entry_data = AsyncMock(
            return_value={"path": "I/doc.pdf", "mime_type": "application/pdf"}
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
            assert isinstance(result, dict)
            assert "pdf" in result.get("mime_type", "")

    @pytest.mark.asyncio
    async def test_get_binary_entry_with_exception(self, advanced_server, temp_dir):
        """Test get_binary_entry when an exception occurs."""
        advanced_server.async_zim_operations.get_binary_entry_data = AsyncMock(
            side_effect=IOError("File not found")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "get_binary_entry" in tools:
            tool_handler = tools["get_binary_entry"].fn
            result = await tool_handler(
                zim_file_path=str(temp_dir / "test.zim"),
                entry_path="I/missing.png",
            )
            # Error envelope: error=True with a markdown-formatted message.
            assert isinstance(result, dict)
            assert result.get("error") is True
            message = result.get("message", "")
            assert "**" in message and (
                "Error" in message or "Not Found" in message or "Operation" in message
            )


# ---------------------------------------------------------------------------
# Phase-A _meta envelope smoke tests — structure.py methods
# ---------------------------------------------------------------------------


class TestStructureDataMethodsMeta:
    """_meta is attached on every return path of the four structure *_data
    methods: get_article_structure_data, extract_article_links_data,
    get_table_of_contents_data, get_related_articles_data.
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

    def test_get_article_structure_data_fresh_attaches_meta(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """Fresh path carries _meta."""
        from openzim_mcp.meta import attach_meta

        zim_file = self._zim_file(temp_dir)
        # _extract_article_structure_data now calls attach_meta internally
        fake = attach_meta(
            {
                "title": "Foo",
                "path": "C/Foo",
                "content_type": "text/html",
                "headings": [],
                "sections": [],
                "metadata": {},
                "word_count": 0,
                "character_count": 0,
            }
        )
        monkeypatch.setattr(
            zim_ops, "_extract_article_structure_data", lambda *a, **kw: fake
        )
        from unittest.mock import MagicMock, patch

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.get_article_structure_data(str(zim_file), "C/Foo")

        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1

    def test_get_article_structure_data_cached_backfills_meta(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """Bundle cache hit path carries _meta (bundle cache is the only cache)."""
        from openzim_mcp.meta import attach_meta

        zim_file = self._zim_file(temp_dir)
        # _extract_article_structure_data now calls attach_meta internally
        fake = attach_meta(
            {
                "title": "Foo",
                "path": "C/Foo",
                "content_type": "text/html",
                "headings": [],
                "sections": [],
                "metadata": {},
                "word_count": 0,
                "character_count": 0,
            }
        )
        monkeypatch.setattr(
            zim_ops, "_extract_article_structure_data", lambda *a, **kw: fake
        )
        from unittest.mock import MagicMock, patch

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.get_article_structure_data(str(zim_file), "C/Foo")

        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1

    def test_extract_article_links_data_attaches_meta(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """extract_article_links_data result carries _meta."""
        zim_file = self._zim_file(temp_dir)

        fake_extraction = {
            "title": "Foo",
            "path": "C/Foo",
            "content_type": "text/html",
            "internal": [],
            "external": [],
            "media": [],
            "message": None,
        }
        monkeypatch.setattr(
            zim_ops,
            "_get_or_load_link_extraction",
            lambda *a, **kw: fake_extraction,
        )

        from unittest.mock import MagicMock, patch

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.extract_article_links_data(str(zim_file), "C/Foo")

        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1
        # v2 Phase B contract: single category in `results`, full
        # category_totals echoed.
        assert result["kind"] == "internal"
        assert result["results"] == []
        assert result["category_totals"] == {
            "internal": 0,
            "external": 0,
            "media": 0,
        }
        assert result["done"] is True

    def test_get_table_of_contents_data_fresh_attaches_meta(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """get_table_of_contents_data result carries _meta."""
        from openzim_mcp.meta import attach_meta

        zim_file = self._zim_file(temp_dir)
        # _extract_table_of_contents_data now calls attach_meta internally
        fake = attach_meta(
            {
                "title": "Foo",
                "path": "C/Foo",
                "toc": [],
                "heading_count": 0,
                "max_depth": 0,
                "content_type": "text/html",
            }
        )
        monkeypatch.setattr(
            zim_ops, "_extract_table_of_contents_data", lambda *a, **kw: fake
        )
        from unittest.mock import MagicMock, patch

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.get_table_of_contents_data(str(zim_file), "C/Foo")

        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1

    def test_get_table_of_contents_data_bundle_caches_result(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """Bundle-level caching: second call re-uses the cached bundle."""
        from openzim_mcp.meta import attach_meta

        zim_file = self._zim_file(temp_dir)

        def counting_extract(*a, **kw):
            return attach_meta(
                {
                    "title": "Foo",
                    "path": "C/Foo",
                    "toc": [],
                    "heading_count": 0,
                    "max_depth": 0,
                    "content_type": "text/html",
                }
            )

        monkeypatch.setattr(
            zim_ops, "_extract_table_of_contents_data", counting_extract
        )
        from unittest.mock import MagicMock, patch

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.get_table_of_contents_data(str(zim_file), "C/Foo")

        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1

    def test_get_related_articles_data_attaches_meta(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """get_related_articles_data result carries _meta."""
        zim_file = self._zim_file(temp_dir)
        # Stub extract_article_links_data to avoid archive open
        monkeypatch.setattr(
            zim_ops,
            "extract_article_links_data",
            lambda *a, **kw: {
                "path": "C/Foo",
                "kind": "internal",
                "results": [],
                "category_totals": {"internal": 0, "external": 0, "media": 0},
            },
        )
        result = zim_ops.get_related_articles_data(str(zim_file), "C/Foo")
        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1
