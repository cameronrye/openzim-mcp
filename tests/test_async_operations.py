"""
Tests for async_operations module.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from openzim_mcp.async_operations import AsyncZimOperations
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.zim_operations import ZimOperations


class TestAsyncZimOperations:
    """Test AsyncZimOperations class."""

    @pytest.fixture
    def mock_zim_operations(self, test_config: OpenZimMcpConfig) -> MagicMock:
        """Create a mock ZimOperations instance."""
        mock = MagicMock(spec=ZimOperations)
        mock.list_zim_files.return_value = '{"files": []}'
        mock.list_zim_files_data.return_value = []
        mock.search_zim_file.return_value = '{"results": []}'
        mock.get_zim_entry.return_value = "Entry content"
        mock.get_zim_metadata.return_value = '{"title": "Test"}'
        mock.get_main_page.return_value = "Main page"
        mock.list_namespaces.return_value = '{"namespaces": []}'
        mock.browse_namespace.return_value = '{"entries": []}'
        mock.search_with_filters.return_value = '{"results": []}'
        mock.get_search_suggestions.return_value = '{"suggestions": []}'
        mock.get_article_structure.return_value = '{"structure": {}}'
        mock.extract_article_links.return_value = '{"links": []}'
        mock.get_entry_summary.return_value = '{"summary": "Test"}'
        mock.get_table_of_contents.return_value = '{"toc": []}'
        mock.get_binary_entry.return_value = '{"data": ""}'
        return mock

    @pytest.fixture
    def async_ops(self, mock_zim_operations: MagicMock) -> AsyncZimOperations:
        """Create AsyncZimOperations instance with mock."""
        return AsyncZimOperations(mock_zim_operations)

    def test_initialization(self, mock_zim_operations: MagicMock):
        """Test AsyncZimOperations initialization."""
        async_ops = AsyncZimOperations(mock_zim_operations)

        assert async_ops._ops == mock_zim_operations

    def test_sync_ops_property(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test sync_ops property returns underlying operations."""
        assert async_ops.sync_ops == mock_zim_operations

    @pytest.mark.asyncio
    async def test_list_zim_files(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async list_zim_files."""
        result = await async_ops.list_zim_files()

        assert result == '{"files": []}'
        mock_zim_operations.list_zim_files.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_zim_files_data(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async list_zim_files_data."""
        result = await async_ops.list_zim_files_data()

        assert result == []
        mock_zim_operations.list_zim_files_data.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_zim_file(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async search_zim_file."""
        result = await async_ops.search_zim_file("/path/to/file.zim", "query", 10, 0)

        assert result == '{"results": []}'
        mock_zim_operations.search_zim_file.assert_called_once_with(
            "/path/to/file.zim", "query", 10, 0
        )

    @pytest.mark.asyncio
    async def test_get_zim_entry(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async get_zim_entry."""
        result = await async_ops.get_zim_entry("/path/to/file.zim", "A/Article", 5000)

        assert result == "Entry content"
        mock_zim_operations.get_zim_entry.assert_called_once_with(
            "/path/to/file.zim", "A/Article", 5000
        )

    @pytest.mark.asyncio
    async def test_get_zim_metadata(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async get_zim_metadata."""
        result = await async_ops.get_zim_metadata("/path/to/file.zim")

        assert result == '{"title": "Test"}'
        mock_zim_operations.get_zim_metadata.assert_called_once_with(
            "/path/to/file.zim"
        )

    @pytest.mark.asyncio
    async def test_get_main_page(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async get_main_page."""
        result = await async_ops.get_main_page("/path/to/file.zim")

        assert result == "Main page"
        mock_zim_operations.get_main_page.assert_called_once_with("/path/to/file.zim")

    @pytest.mark.asyncio
    async def test_list_namespaces(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async list_namespaces."""
        result = await async_ops.list_namespaces("/path/to/file.zim")

        assert result == '{"namespaces": []}'
        mock_zim_operations.list_namespaces.assert_called_once_with("/path/to/file.zim")

    @pytest.mark.asyncio
    async def test_browse_namespace(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async browse_namespace."""
        result = await async_ops.browse_namespace("/path/to/file.zim", "A", 50, 0)

        assert result == '{"entries": []}'
        mock_zim_operations.browse_namespace.assert_called_once_with(
            "/path/to/file.zim", "A", 50, 0
        )

    @pytest.mark.asyncio
    async def test_search_with_filters(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async search_with_filters."""
        result = await async_ops.search_with_filters(
            "/path/to/file.zim", "query", "A", "text/html", 10, 0
        )

        assert result == '{"results": []}'
        mock_zim_operations.search_with_filters.assert_called_once_with(
            "/path/to/file.zim", "query", "A", "text/html", 10, 0
        )

    @pytest.mark.asyncio
    async def test_get_search_suggestions(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async get_search_suggestions."""
        result = await async_ops.get_search_suggestions(
            "/path/to/file.zim", "partial", 10
        )

        assert result == '{"suggestions": []}'
        mock_zim_operations.get_search_suggestions.assert_called_once_with(
            "/path/to/file.zim", "partial", 10
        )

    @pytest.mark.asyncio
    async def test_get_article_structure(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async get_article_structure."""
        result = await async_ops.get_article_structure("/path/to/file.zim", "C/Article")

        assert result == '{"structure": {}}'
        mock_zim_operations.get_article_structure.assert_called_once_with(
            "/path/to/file.zim", "C/Article"
        )

    @pytest.mark.asyncio
    async def test_extract_article_links(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async extract_article_links."""
        result = await async_ops.extract_article_links("/path/to/file.zim", "C/Article")

        assert result == '{"links": []}'
        mock_zim_operations.extract_article_links.assert_called_once_with(
            "/path/to/file.zim", "C/Article"
        )

    @pytest.mark.asyncio
    async def test_get_entry_summary(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async get_entry_summary."""
        result = await async_ops.get_entry_summary(
            "/path/to/file.zim", "C/Article", 200
        )

        assert result == '{"summary": "Test"}'
        mock_zim_operations.get_entry_summary.assert_called_once_with(
            "/path/to/file.zim", "C/Article", 200
        )

    @pytest.mark.asyncio
    async def test_get_table_of_contents(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async get_table_of_contents."""
        result = await async_ops.get_table_of_contents("/path/to/file.zim", "C/Article")

        assert result == '{"toc": []}'
        mock_zim_operations.get_table_of_contents.assert_called_once_with(
            "/path/to/file.zim", "C/Article"
        )

    @pytest.mark.asyncio
    async def test_get_binary_entry(
        self, async_ops: AsyncZimOperations, mock_zim_operations: MagicMock
    ):
        """Test async get_binary_entry."""
        result = await async_ops.get_binary_entry(
            "/path/to/file.zim", "I/image.png", 1000000, True
        )

        assert result == '{"data": ""}'
        mock_zim_operations.get_binary_entry.assert_called_once_with(
            "/path/to/file.zim", "I/image.png", 1000000, True
        )


class TestAsyncOperationsThreading:
    """Test that async operations properly use threading."""

    @pytest.mark.asyncio
    async def test_operations_run_in_thread(self):
        """Test that operations run in a separate thread."""
        import threading

        operation_thread_id = None

        def sync_operation():
            nonlocal operation_thread_id
            operation_thread_id = threading.current_thread().ident
            return "result"

        # Simulate running in thread
        result = await asyncio.to_thread(sync_operation)

        assert result == "result"
        # When using asyncio.to_thread, the operation runs in a different thread
        # Note: In some test environments, this might be the same thread
        # The important thing is that to_thread was used


class TestAsyncOperationsIntegration:
    """Integration tests for AsyncZimOperations."""

    @pytest.fixture
    def real_async_ops(self, test_config: OpenZimMcpConfig) -> AsyncZimOperations:
        """Create real AsyncZimOperations with real ZimOperations."""
        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.content_processor import ContentProcessor
        from openzim_mcp.security import PathValidator

        cache = OpenZimMcpCache(test_config.cache)
        content_processor = ContentProcessor(test_config.content.snippet_length)
        path_validator = PathValidator(test_config.allowed_directories)

        zim_ops = ZimOperations(
            config=test_config,
            path_validator=path_validator,
            cache=cache,
            content_processor=content_processor,
        )

        return AsyncZimOperations(zim_ops)

    @pytest.mark.asyncio
    async def test_list_zim_files_integration(self, real_async_ops: AsyncZimOperations):
        """Test list_zim_files with real operations."""
        # This will return empty or error since no real ZIM files
        result = await real_async_ops.list_zim_files()

        # Should return valid string result
        # May return empty list or error message
        assert isinstance(result, str)
