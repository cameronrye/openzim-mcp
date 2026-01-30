"""Tests for ZIM operations module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.exceptions import (
    OpenZimMcpArchiveError,
    OpenZimMcpSecurityError,
    OpenZimMcpValidationError,
)
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations


class TestZimOperations:
    """Test ZimOperations class."""

    @pytest.fixture
    def zim_operations(
        self,
        test_config: OpenZimMcpConfig,
        path_validator: PathValidator,
        openzim_mcp_cache: OpenZimMcpCache,
        content_processor: ContentProcessor,
    ) -> ZimOperations:
        """Create ZimOperations instance for testing."""
        return ZimOperations(
            test_config, path_validator, openzim_mcp_cache, content_processor
        )

    def test_initialization(
        self, zim_operations: ZimOperations, test_config: OpenZimMcpConfig
    ):
        """Test ZimOperations initialization."""
        assert zim_operations.config == test_config
        assert zim_operations.path_validator is not None
        assert zim_operations.cache is not None
        assert zim_operations.content_processor is not None

    def test_list_zim_files_empty_directory(self, zim_operations: ZimOperations):
        """Test listing ZIM files in empty directory."""
        result = zim_operations.list_zim_files()
        assert "No ZIM files found" in result

    def test_list_zim_files_with_files(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test listing ZIM files with actual files."""
        # Create test ZIM files
        zim_file1 = temp_dir / "test1.zim"
        zim_file2 = temp_dir / "test2.zim"
        zim_file1.write_text("test content 1")
        zim_file2.write_text("test content 2")

        result = zim_operations.list_zim_files()
        assert "Found 2 ZIM files" in result
        assert "test1.zim" in result
        assert "test2.zim" in result

    def test_list_zim_files_caching(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test that list_zim_files results are cached."""
        # Create a test ZIM file
        zim_file = temp_dir / "test.zim"
        zim_file.write_text("test content")

        # First call
        result1 = zim_operations.list_zim_files()

        # Second call should return cached result
        result2 = zim_operations.list_zim_files()

        assert result1 == result2

        # Check cache has entry
        cache_stats = zim_operations.cache.stats()
        assert cache_stats["size"] > 0

    def test_search_zim_file_invalid_path(self, zim_operations: ZimOperations):
        """Test search with invalid file path."""
        with pytest.raises(
            (OpenZimMcpValidationError, OpenZimMcpArchiveError, OpenZimMcpSecurityError)
        ):
            zim_operations.search_zim_file("/invalid/path.zim", "test query")

    def test_search_zim_file_non_zim_file(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test search with non-ZIM file."""
        # Create a non-ZIM file
        txt_file = temp_dir / "test.txt"
        txt_file.write_text("test content")

        with pytest.raises(OpenZimMcpValidationError, match="File is not a ZIM file"):
            zim_operations.search_zim_file(str(txt_file), "test query")

    @patch("openzim_mcp.zim_operations.Archive")
    def test_search_zim_file_mock_success(
        self, mock_archive, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test successful ZIM file search with mocked libzim."""
        # Create a test ZIM file
        zim_file = temp_dir / "test.zim"
        zim_file.write_text("test content")

        # Mock the libzim components
        mock_archive_instance = MagicMock()
        mock_archive.return_value = mock_archive_instance

        mock_searcher = MagicMock()
        mock_search = MagicMock()
        mock_search.getEstimatedMatches.return_value = 1
        mock_search.getResults.return_value = ["A/Test_Article"]
        mock_searcher.search.return_value = mock_search

        mock_entry = MagicMock()
        mock_entry.title = "Test Article"
        mock_item = MagicMock()
        mock_item.mimetype = "text/html"
        mock_item.content = b"<html><body>Test content</body></html>"
        mock_entry.get_item.return_value = mock_item
        mock_archive_instance.get_entry_by_path.return_value = mock_entry

        with (
            patch("openzim_mcp.zim_operations.Searcher", return_value=mock_searcher),
            patch("openzim_mcp.zim_operations.Query"),
        ):

            result = zim_operations.search_zim_file(str(zim_file), "test query")

            assert "Found 1 matches" in result
            assert "Test Article" in result
            assert "Test content" in result

    def test_get_zim_entry_invalid_path(self, zim_operations: ZimOperations):
        """Test get entry with invalid file path."""
        with pytest.raises(
            (OpenZimMcpValidationError, OpenZimMcpArchiveError, OpenZimMcpSecurityError)
        ):
            zim_operations.get_zim_entry("/invalid/path.zim", "A/Test")

    @patch("openzim_mcp.zim_operations.Archive")
    def test_get_zim_entry_mock_success(
        self, mock_archive, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test successful ZIM entry retrieval with mocked libzim."""
        # Create a test ZIM file
        zim_file = temp_dir / "test.zim"
        zim_file.write_text("test content")

        # Mock the libzim components
        mock_archive_instance = MagicMock()
        mock_archive.return_value = mock_archive_instance

        mock_entry = MagicMock()
        mock_entry.title = "Test Article"
        mock_item = MagicMock()
        mock_item.mimetype = "text/html"
        mock_item.content = (
            b"<html><body><h1>Test Article</h1><p>Test content</p></body></html>"
        )
        mock_entry.get_item.return_value = mock_item
        mock_archive_instance.get_entry_by_path.return_value = mock_entry

        result = zim_operations.get_zim_entry(str(zim_file), "A/Test_Article")

        assert "# Test Article" in result
        assert "Path: A/Test_Article" in result
        assert "Type: text/html" in result
        assert "Test content" in result

    def test_search_zim_file_caching(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test that search results are cached."""
        # Create a test ZIM file
        zim_file = temp_dir / "test.zim"
        zim_file.write_text("test content")

        with patch("openzim_mcp.zim_operations.Archive") as mock_archive:
            # Mock successful search
            mock_archive_instance = MagicMock()
            mock_archive.return_value = mock_archive_instance

            mock_searcher = MagicMock()
            mock_search = MagicMock()
            mock_search.getEstimatedMatches.return_value = 0
            mock_searcher.search.return_value = mock_search

            with (
                patch(
                    "openzim_mcp.zim_operations.Searcher", return_value=mock_searcher
                ),
                patch("openzim_mcp.zim_operations.Query"),
            ):

                # First call
                result1 = zim_operations.search_zim_file(
                    str(zim_file), "test", limit=10, offset=0
                )

                # Second call should use cache
                result2 = zim_operations.search_zim_file(
                    str(zim_file), "test", limit=10, offset=0
                )

                assert result1 == result2

                # Archive should only be opened once due to caching
                assert mock_archive.call_count == 1

    def test_get_zim_metadata(self, zim_operations: ZimOperations, temp_dir: Path):
        """Test ZIM metadata retrieval."""
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            # Mock archive with metadata
            mock_archive_instance = MagicMock()
            mock_archive_instance.entry_count = 100
            mock_archive_instance.all_entry_count = 120
            mock_archive_instance.article_count = 80
            mock_archive_instance.media_count = 20

            # Mock metadata entry
            mock_entry = MagicMock()
            mock_item = MagicMock()
            mock_item.content = b"Test Title"
            mock_entry.get_item.return_value = mock_item
            mock_archive_instance.get_entry_by_path.return_value = mock_entry

            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            result = zim_operations.get_zim_metadata(str(zim_file))

            assert "entry_count" in result
            assert "100" in result
            assert "metadata_entries" in result

    def test_get_main_page(self, zim_operations: ZimOperations, temp_dir: Path):
        """Test main page retrieval."""
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            # Mock archive with main page
            mock_archive_instance = MagicMock()
            mock_main_entry = MagicMock()
            mock_main_entry.title = "Main Page"
            mock_main_entry.path = "W/mainPage"

            mock_item = MagicMock()
            mock_item.content = b"<h1>Welcome</h1><p>This is the main page.</p>"
            mock_item.mimetype = "text/html"
            mock_main_entry.get_item.return_value = mock_item

            mock_archive_instance.main_entry = mock_main_entry
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            result = zim_operations.get_main_page(str(zim_file))

            assert "Main Page" in result
            assert "Welcome" in result

    def test_list_namespaces(self, zim_operations: ZimOperations, temp_dir: Path):
        """Test namespace listing."""
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            # Mock archive with entries in different namespaces
            mock_archive_instance = MagicMock()
            mock_archive_instance.entry_count = 3
            mock_archive_instance.has_new_namespace_scheme = (
                False  # Set to boolean value
            )

            # Mock entries
            mock_entries = []
            for _i, (path, title) in enumerate(
                [
                    ("C/Article1", "Article 1"),
                    ("M/Title", "Test ZIM"),
                    ("W/mainPage", "Main Page"),
                ]
            ):
                entry = MagicMock()
                entry.path = path
                entry.title = title
                mock_entries.append(entry)

            # Mock get_random_entry to return entries from our list
            def mock_get_random_entry():
                import random

                return random.choice(mock_entries)

            mock_archive_instance.get_random_entry = mock_get_random_entry
            mock_archive_instance.get_entry_by_id.side_effect = mock_entries
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            result = zim_operations.list_namespaces(str(zim_file))

            assert "namespaces" in result
            # Due to random sampling, we can't guarantee all namespaces will be found
            # but we should find at least some namespaces
            import json

            result_data = json.loads(result)
            assert "namespaces" in result_data
            assert len(result_data["namespaces"]) > 0
            # Check that at least one of our expected namespaces is found
            found_namespaces = set(result_data["namespaces"].keys())
            expected_namespaces = {"C", "M", "W"}
            assert len(found_namespaces.intersection(expected_namespaces)) > 0

    def test_browse_namespace(self, zim_operations: ZimOperations, temp_dir: Path):
        """Test namespace browsing."""
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            # Mock archive with entries
            mock_archive_instance = MagicMock()
            mock_archive_instance.entry_count = 5
            mock_archive_instance.has_new_namespace_scheme = (
                False  # Set to boolean value
            )

            # Mock entries - some in C namespace, some in other namespaces
            mock_entries = []
            for _i, (path, title) in enumerate(
                [
                    ("C/Article1", "Article 1"),
                    ("C/Article2", "Article 2"),
                    ("M/Title", "Test ZIM"),
                    ("C/Article3", "Article 3"),
                    ("W/mainPage", "Main Page"),
                ]
            ):
                entry = MagicMock()
                entry.path = path
                entry.title = title

                # Mock item for content preview
                item = MagicMock()
                item.mimetype = "text/html"
                item.content = b"<p>Sample content</p>"
                entry.get_item.return_value = item

                mock_entries.append(entry)

            # Mock get_random_entry to return entries from our list
            def mock_get_random_entry():
                import random

                return random.choice(mock_entries)

            mock_archive_instance.get_random_entry = mock_get_random_entry

            # Mock has_entry_by_path for common patterns
            def mock_has_entry_by_path(path):
                return any(entry.path == path for entry in mock_entries)

            mock_archive_instance.has_entry_by_path = mock_has_entry_by_path

            # Mock get_entry_by_path
            def mock_get_entry_by_path(path):
                for entry in mock_entries:
                    if entry.path == path:
                        return entry
                raise Exception(f"Entry not found: {path}")

            mock_archive_instance.get_entry_by_path = mock_get_entry_by_path
            mock_archive_instance.get_entry_by_id.side_effect = mock_entries
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            result = zim_operations.browse_namespace(
                str(zim_file), "C", limit=10, offset=0
            )

            assert "namespace" in result
            assert "C" in result
            assert "entries" in result
            assert "total_in_namespace" in result

    def test_browse_namespace_invalid_params(self, zim_operations: ZimOperations):
        """Test namespace browsing with invalid parameters."""
        with pytest.raises(
            OpenZimMcpArchiveError, match="Limit must be between 1 and 200"
        ):
            zim_operations.browse_namespace("test.zim", "C", limit=0)

        with pytest.raises(OpenZimMcpArchiveError, match="Offset must be non-negative"):
            zim_operations.browse_namespace("test.zim", "C", offset=-1)

        with pytest.raises(
            OpenZimMcpSecurityError,
            match="Access denied - Path is outside allowed directories",
        ):
            zim_operations.browse_namespace("test.zim", "ABC", limit=10)

    def test_search_with_filters(self, zim_operations: ZimOperations, temp_dir: Path):
        """Test filtered search functionality."""
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            # Mock search functionality
            mock_archive_instance = MagicMock()
            mock_searcher = MagicMock()
            mock_search = MagicMock()
            mock_search.getEstimatedMatches.return_value = 2
            mock_search.getResults.return_value = ["C/Article1", "M/Title"]
            mock_searcher.search.return_value = mock_search

            # Mock entries
            mock_entry1 = MagicMock()
            mock_entry1.path = "C/Article1"
            mock_entry1.title = "Article 1"
            mock_item1 = MagicMock()
            mock_item1.mimetype = "text/html"
            mock_item1.content = b"<p>Test content</p>"
            mock_entry1.get_item.return_value = mock_item1

            mock_entry2 = MagicMock()
            mock_entry2.path = "M/Title"
            mock_entry2.title = "Test ZIM"
            mock_item2 = MagicMock()
            mock_item2.mimetype = "text/plain"
            mock_item2.content = b"Test ZIM file"
            mock_entry2.get_item.return_value = mock_item2

            mock_archive_instance.get_entry_by_path.side_effect = [
                mock_entry1,
                mock_entry2,
            ]
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            with patch(
                "openzim_mcp.zim_operations.Searcher", return_value=mock_searcher
            ):
                result = zim_operations.search_with_filters(
                    str(zim_file), "test", namespace="C", limit=10
                )

                assert "filtered matches" in result
                assert "namespace=C" in result

    def test_get_search_suggestions(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test search suggestions functionality."""
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            # Mock archive with entries for suggestions
            mock_archive_instance = MagicMock()
            mock_archive_instance.entry_count = 3

            # Mock entries with titles that could match suggestions
            mock_entries = []
            for _i, (path, title) in enumerate(
                [
                    ("C/Biology", "Biology"),
                    ("C/Biochemistry", "Biochemistry"),
                    ("C/Physics", "Physics"),
                ]
            ):
                entry = MagicMock()
                entry.path = path
                entry.title = title
                mock_entries.append(entry)

            mock_archive_instance.get_entry_by_id.side_effect = mock_entries
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            result = zim_operations.get_search_suggestions(
                str(zim_file), "bio", limit=5
            )

            assert "suggestions" in result
            assert "partial_query" in result
            assert "bio" in result

    def test_get_search_suggestions_short_query(self, zim_operations: ZimOperations):
        """Test search suggestions with too short query."""
        result = zim_operations.get_search_suggestions("test.zim", "a", limit=5)
        assert "Query too short" in result

    def test_get_article_structure(self, zim_operations: ZimOperations, temp_dir: Path):
        """Test article structure extraction."""
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

    def test_list_zim_files_os_error_handling(self, zim_operations: ZimOperations):
        """Test list_zim_files with OSError during file stat operations."""
        from unittest.mock import MagicMock, patch

        # Mock Path.glob to return a file that will cause OSError on stat()
        mock_file = MagicMock()
        mock_file.is_file.return_value = True
        mock_file.stat.side_effect = OSError("Permission denied")
        mock_file.name = "test.zim"

        with (
            patch.object(zim_operations.config, "allowed_directories", ["/tmp"]),
            patch("pathlib.Path.glob", return_value=[mock_file]),
        ):
            # This should handle the OSError gracefully (lines 109-112)
            result = zim_operations.list_zim_files()
            # Should still return a result, just without the problematic file
            assert isinstance(result, str)

    def test_list_zim_files_directory_exception_handling(
        self, zim_operations: ZimOperations
    ):
        """Test list_zim_files with exception during directory processing."""
        from unittest.mock import patch

        with (
            patch.object(zim_operations.config, "allowed_directories", ["/tmp"]),
            patch("pathlib.Path.glob", side_effect=Exception("Directory access error")),
        ):
            # This should handle the exception gracefully (lines 114-115)
            result = zim_operations.list_zim_files()
            assert isinstance(result, str)

    def test_search_zim_file_exception_in_result_processing(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test search_zim_file with exception during result processing."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock searcher with proper return values
            mock_searcher = MagicMock()
            mock_search_result = MagicMock()
            mock_search_result.getEstimatedMatches.return_value = 1
            mock_searcher.search.return_value = mock_search_result

            # Mock getResults to return an iterator that yields the entry
            def mock_get_results(offset, count):
                return ["test_entry"]

            mock_search_result.getResults = mock_get_results
            mock_searcher.search.return_value = mock_search_result

            # Mock archive.get_entry_by_path to raise exception (lines 213-215)
            mock_archive_instance.get_entry_by_path.side_effect = Exception(
                "Entry access error"
            )

            with (
                patch(
                    "openzim_mcp.zim_operations.Searcher", return_value=mock_searcher
                ),
                patch("openzim_mcp.zim_operations.Query"),
            ):
                result = zim_operations.search_zim_file(str(zim_file), "test")
                # Should handle the exception and include error message
                assert "Error getting entry details" in result

    def test_zim_archive_context_manager_exception(self, temp_dir: Path):
        """Test zim_archive context manager exception handling."""
        from openzim_mcp.exceptions import OpenZimMcpArchiveError
        from openzim_mcp.zim_operations import zim_archive

        # Create a file that will cause Archive() to fail
        invalid_file = temp_dir / "invalid.zim"
        invalid_file.write_text("not a zim file")

        with (
            pytest.raises(OpenZimMcpArchiveError, match="Failed to open ZIM archive"),
            zim_archive(invalid_file),
        ):
            pass

    def test_get_zim_entry_exception_handling(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test get_zim_entry with exception during entry retrieval."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock get_entry_by_path to raise exception (lines 341-343)
            mock_archive_instance.get_entry_by_path.side_effect = Exception(
                "Entry not found"
            )

            with pytest.raises(OpenZimMcpArchiveError, match="Entry not found"):
                zim_operations.get_zim_entry(str(zim_file), "A/Test")

    def test_get_main_page_exception_handling(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test get_main_page with exception during retrieval."""
        from unittest.mock import patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            # Make the context manager itself raise an exception
            mock_archive.return_value.__enter__.side_effect = Exception(
                "Main page error"
            )

            with pytest.raises(
                OpenZimMcpArchiveError, match="Main page retrieval failed"
            ):
                zim_operations.get_main_page(str(zim_file))

    def test_search_with_filters_exception_handling(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test search_with_filters with exception during search."""
        from unittest.mock import patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.side_effect = Exception("Archive error")

            with pytest.raises(
                OpenZimMcpArchiveError, match="Filtered search operation failed"
            ):
                zim_operations.search_with_filters(str(zim_file), "test", namespace="A")

    def test_get_search_suggestions_exception_handling(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test get_search_suggestions with exception during suggestion generation."""
        from unittest.mock import patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.side_effect = Exception("Archive error")

            with pytest.raises(
                OpenZimMcpArchiveError, match="Suggestion generation failed"
            ):
                zim_operations.get_search_suggestions(str(zim_file), "test")

    def test_get_article_structure_exception_handling(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test get_article_structure with exception during structure extraction."""
        from unittest.mock import patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.side_effect = Exception("Archive error")

            with pytest.raises(
                OpenZimMcpArchiveError, match="Structure extraction failed"
            ):
                zim_operations.get_article_structure(str(zim_file), "A/Test")

    def test_browse_namespace_exception_handling(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test browse_namespace with exception during browsing."""
        from unittest.mock import patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.side_effect = Exception("Archive error")

            with pytest.raises(
                OpenZimMcpArchiveError, match="Namespace browsing failed"
            ):
                zim_operations.browse_namespace(str(zim_file), "A")

    def test_extract_article_links_exception_handling(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test extract_article_links with exception during link extraction."""
        from unittest.mock import patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.side_effect = Exception("Archive error")

            with pytest.raises(OpenZimMcpArchiveError, match="Link extraction failed"):
                zim_operations.extract_article_links(str(zim_file), "A/Test")

    def test_get_entry_snippet_exception_handling(self, zim_operations: ZimOperations):
        """Test _get_entry_snippet with exception during content processing."""
        from unittest.mock import MagicMock, patch

        mock_entry = MagicMock()
        mock_item = MagicMock()
        mock_item.content = b"test content"
        mock_item.mimetype = "text/html"
        mock_entry.get_item.return_value = mock_item

        # Mock content_processor to raise exception
        with patch.object(
            zim_operations.content_processor,
            "process_mime_content",
            side_effect=Exception("Processing error"),
        ):
            result = zim_operations._get_entry_snippet(mock_entry)
            # Should return error message when processing fails
            assert "Unable to get content preview" in result

    def test_perform_search_with_no_results(self, zim_operations: ZimOperations):
        """Test _perform_search with no search results."""
        from unittest.mock import MagicMock, patch

        mock_archive = MagicMock()
        mock_searcher = MagicMock()
        mock_search_result = MagicMock()
        mock_search_result.getEstimatedMatches.return_value = 0
        mock_searcher.search.return_value = mock_search_result

        with (
            patch("openzim_mcp.zim_operations.Searcher", return_value=mock_searcher),
            patch("openzim_mcp.zim_operations.Query"),
        ):
            result = zim_operations._perform_search(mock_archive, "test", 10, 0)
            assert "No search results found" in result

    def test_get_entry_content_with_redirect(self, zim_operations: ZimOperations):
        """Test _get_entry_content with redirect entry."""
        from unittest.mock import MagicMock

        mock_archive = MagicMock()
        mock_entry = MagicMock()
        mock_entry.is_redirect = True
        mock_entry.get_redirect_entry.return_value = mock_entry
        mock_entry.title = "Test Article"

        mock_item = MagicMock()
        mock_item.content = b"<html>Test content</html>"
        mock_item.mimetype = "text/html"
        mock_entry.get_item.return_value = mock_item

        mock_archive.get_entry_by_path.return_value = mock_entry

        result = zim_operations._get_entry_content(mock_archive, "A/Test", 1000)
        assert "Test Article" in result

    def test_get_metadata_with_missing_entries(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test get_zim_metadata when some metadata entries are missing."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive_instance.entry_count = 100
            mock_archive_instance.all_entry_count = 120
            mock_archive_instance.article_count = 80
            mock_archive_instance.media_count = 20

            # Mock get_entry_by_path to raise exception for some metadata
            def mock_get_entry_by_path(path):
                if path == "M/Title":
                    mock_entry = MagicMock()
                    mock_item = MagicMock()
                    mock_item.content = b"Test Title"
                    mock_entry.get_item.return_value = mock_item
                    return mock_entry
                else:
                    raise Exception("Entry not found")

            mock_archive_instance.get_entry_by_path.side_effect = mock_get_entry_by_path
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            result = zim_operations.get_zim_metadata(str(zim_file))
            assert "Test Title" in result
            assert "entry_count" in result

    def test_get_metadata_exception_in_metadata_extraction(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test get_zim_metadata with exception during metadata extraction."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive_instance.entry_count = 100
            mock_archive_instance.all_entry_count = 120
            mock_archive_instance.article_count = 80
            mock_archive_instance.media_count = 20

            # Mock get_entry_by_path to raise exception during metadata loop
            mock_archive_instance.get_entry_by_path.side_effect = Exception(
                "Metadata error"
            )
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            result = zim_operations.get_zim_metadata(str(zim_file))
            # Should still return basic metadata even if entries fail
            assert "entry_count" in result

    def test_browse_namespace_with_no_entries(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test browse_namespace when no entries are found."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive_instance.entry_count = 0
            mock_archive_instance.has_new_namespace_scheme = False

            # Mock get_random_entry to raise exception (no entries)
            def mock_get_random_entry():
                raise Exception("No entries available")

            mock_archive_instance.get_random_entry = mock_get_random_entry

            # Mock has_entry_by_path to return False
            mock_archive_instance.has_entry_by_path = lambda path: False

            # Mock iterator to return empty list
            mock_archive_instance.__iter__.return_value = iter([])
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            result = zim_operations.browse_namespace(str(zim_file), "A")
            assert 'total_in_namespace": 0' in result

    def test_search_with_filters_comprehensive(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test search_with_filters with various filter combinations."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock searcher with results
            mock_searcher = MagicMock()
            mock_search_result = MagicMock()
            mock_search_result.getEstimatedMatches.return_value = 1
            mock_searcher.search.return_value = mock_search_result

            def mock_get_results(offset, count):
                return ["A/Test_Entry"]

            mock_search_result.getResults = mock_get_results

            # Mock entry
            mock_entry = MagicMock()
            mock_entry.title = "Test Entry"
            mock_entry.path = "A/Test_Entry"
            mock_item = MagicMock()
            mock_item.mimetype = "text/html"
            mock_item.content = b"Test content"
            mock_entry.get_item.return_value = mock_item
            mock_archive_instance.get_entry_by_path.return_value = mock_entry

            with (
                patch(
                    "openzim_mcp.zim_operations.Searcher", return_value=mock_searcher
                ),
                patch("openzim_mcp.zim_operations.Query"),
            ):
                result = zim_operations.search_with_filters(
                    str(zim_file), "test", namespace="A", content_type="text/html"
                )
                assert "Test Entry" in result

    def test_get_search_suggestions_limit_validation(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test get_search_suggestions with invalid limit values."""
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        # Test limit too low
        with pytest.raises(
            OpenZimMcpArchiveError, match="Limit must be between 1 and 50"
        ):
            zim_operations.get_search_suggestions(str(zim_file), "test", limit=0)

        # Test limit too high
        with pytest.raises(
            OpenZimMcpArchiveError, match="Limit must be between 1 and 50"
        ):
            zim_operations.get_search_suggestions(str(zim_file), "test", limit=51)

    def test_cache_hit_scenarios(self, zim_operations: ZimOperations, temp_dir: Path):
        """Test cache hit scenarios to cover cache return lines."""
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        # Get the validated path that would be used in cache keys
        validated_path = zim_operations.path_validator.validate_path(str(zim_file))
        validated_path = zim_operations.path_validator.validate_zim_file(validated_path)

        # Test get_zim_entry cache hit (lines 283-284)
        cache_key = f"entry:{validated_path}:A/Test:1000"
        zim_operations.cache.set(cache_key, "cached entry content")

        result = zim_operations.get_zim_entry(str(zim_file), "A/Test", 1000)
        assert result == "cached entry content"

        # Test list_namespaces cache hit (lines 584-585)
        cache_key = f"namespaces:{validated_path}"
        zim_operations.cache.set(cache_key, '{"cached": "namespaces"}')

        result = zim_operations.list_namespaces(str(zim_file))
        assert result == '{"cached": "namespaces"}'

        # Test browse_namespace cache hit (lines 691-692)
        cache_key = f"browse_ns:{validated_path}:A:50:0"
        zim_operations.cache.set(cache_key, '{"cached": "browse"}')

        result = zim_operations.browse_namespace(str(zim_file), "A")
        assert result == '{"cached": "browse"}'

        # Test get_article_structure cache hit (lines 1228-1229)
        cache_key = f"structure:{validated_path}:A/Test"
        zim_operations.cache.set(cache_key, '{"cached": "structure"}')

        result = zim_operations.get_article_structure(str(zim_file), "A/Test")
        assert result == '{"cached": "structure"}'

        # Test extract_article_links cache hit (lines 1317-1318)
        cache_key = f"links:{validated_path}:A/Test"
        zim_operations.cache.set(cache_key, '{"cached": "links"}')

        result = zim_operations.extract_article_links(str(zim_file), "A/Test")
        assert result == '{"cached": "links"}'

    def test_complex_search_operations(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test complex search operations to cover missing search lines."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock searcher for complex search scenario
            mock_searcher = MagicMock()
            mock_search_result = MagicMock()
            mock_search_result.getEstimatedMatches.return_value = 100
            mock_searcher.search.return_value = mock_search_result

            # Mock getResults to return multiple entries
            def mock_get_results(offset, count):
                return [f"A/Entry_{i}" for i in range(offset, offset + count)]

            mock_search_result.getResults = mock_get_results

            # Mock entries with various scenarios
            def mock_get_entry_by_path(path):
                mock_entry = MagicMock()
                if "Entry_0" in path:
                    mock_entry.title = "Test Entry 0"
                    mock_entry.path = path
                    mock_item = MagicMock()
                    mock_item.content = b"Test content for entry 0"
                    mock_item.mimetype = "text/html"
                    mock_entry.get_item.return_value = mock_item
                elif "Entry_1" in path:
                    # This entry will cause an exception in snippet generation
                    mock_entry.title = "Test Entry 1"
                    mock_entry.path = path
                    mock_entry.get_item.side_effect = Exception("Item error")
                else:
                    mock_entry.title = "Test Entry"
                    mock_entry.path = path
                    mock_item = MagicMock()
                    mock_item.content = b"Test content"
                    mock_item.mimetype = "text/plain"
                    mock_entry.get_item.return_value = mock_item
                return mock_entry

            mock_archive_instance.get_entry_by_path.side_effect = mock_get_entry_by_path

            with (
                patch(
                    "openzim_mcp.zim_operations.Searcher", return_value=mock_searcher
                ),
                patch("openzim_mcp.zim_operations.Query"),
            ):
                # Test search with multiple results and error handling
                result = zim_operations.search_zim_file(
                    str(zim_file), "test", limit=5, offset=0
                )
                assert "Test Entry 0" in result
                assert "Unable to get content preview" in result

    def test_namespace_browsing_edge_cases(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test namespace browsing edge cases to cover missing lines."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive_instance.entry_count = 10
            mock_archive_instance.has_new_namespace_scheme = False
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock iterator with mixed namespace entries
            mock_entries = []
            for i in range(10):
                mock_entry = MagicMock()
                if i < 3:
                    mock_entry.path = f"A/Entry_{i}"
                    mock_entry.title = f"Entry {i}"
                elif i < 6:
                    mock_entry.path = f"C/Entry_{i}"
                    mock_entry.title = f"Entry {i}"
                else:
                    mock_entry.path = f"M/Entry_{i}"
                    mock_entry.title = f"Entry {i}"

                # Mock item for content preview
                item = MagicMock()
                item.mimetype = "text/html"
                item.content = b"<p>Sample content</p>"
                mock_entry.get_item.return_value = item

                mock_entries.append(mock_entry)

            # Mock get_random_entry to return entries from our list
            def mock_get_random_entry():
                import random

                return random.choice(mock_entries)

            mock_archive_instance.get_random_entry = mock_get_random_entry

            # Mock has_entry_by_path for common patterns
            def mock_has_entry_by_path(path):
                return any(entry.path == path for entry in mock_entries)

            mock_archive_instance.has_entry_by_path = mock_has_entry_by_path

            # Mock get_entry_by_path
            def mock_get_entry_by_path(path):
                for entry in mock_entries:
                    if entry.path == path:
                        return entry
                raise Exception(f"Entry not found: {path}")

            mock_archive_instance.get_entry_by_path = mock_get_entry_by_path
            mock_archive_instance.__iter__.return_value = iter(mock_entries)

            # Test browsing specific namespace with pagination
            result = zim_operations.browse_namespace(
                str(zim_file), "A", limit=2, offset=1
            )
            assert "namespace" in result
            assert "A" in result

    def test_content_processing_edge_cases(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test content processing edge cases to cover missing lines."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock entry with complex content scenarios
            mock_entry = MagicMock()
            mock_entry.title = "Test Article"
            mock_entry.path = "A/Test"

            # Test scenario where get_item() fails (lines 956-957)
            mock_entry.get_item.side_effect = Exception("Item access error")
            mock_archive_instance.get_entry_by_path.return_value = mock_entry

            # This should raise an exception since get_item() fails early
            with pytest.raises(
                OpenZimMcpArchiveError, match="Structure extraction failed"
            ):
                zim_operations.get_article_structure(str(zim_file), "A/Test")

    def test_structure_extraction_comprehensive(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test comprehensive structure extraction scenarios."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Test different content types
            test_cases = [
                (
                    "text/html",
                    b"<html><body><h1>Title</h1><p>Content</p></body></html>",
                ),
                ("text/plain", b"Plain text content for testing"),
                ("image/png", b"binary image data"),
                ("application/json", b'{"key": "value"}'),
            ]

            for mime_type, content in test_cases:
                mock_entry = MagicMock()
                mock_entry.title = f"Test {mime_type}"
                mock_entry.path = f"A/Test_{mime_type.replace('/', '_')}"
                mock_item = MagicMock()
                mock_item.content = content
                mock_item.mimetype = mime_type
                mock_entry.get_item.return_value = mock_item
                mock_archive_instance.get_entry_by_path.return_value = mock_entry

                result = zim_operations.get_article_structure(
                    str(zim_file), mock_entry.path
                )
                assert "path" in result
                assert "content_type" in result

    def test_link_extraction_comprehensive(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test comprehensive link extraction scenarios."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Test HTML content with links
            mock_entry = MagicMock()
            mock_entry.title = "Test Article with Links"
            mock_entry.path = "A/Test_Links"
            mock_item = MagicMock()
            mock_item.content = b"""
            <html>
                <body>
                    <a href="A/Internal_Link">Internal</a>
                    <a href="https://external.com">External</a>
                    <img src="I/image.png" alt="Image">
                </body>
            </html>
            """
            mock_item.mimetype = "text/html"
            mock_entry.get_item.return_value = mock_item
            mock_archive_instance.get_entry_by_path.return_value = mock_entry

            result = zim_operations.extract_article_links(str(zim_file), "A/Test_Links")
            assert "path" in result
            assert "content_type" in result

            # Test non-HTML content (lines 1361)
            mock_entry.path = "I/Image"
            mock_item.mimetype = "image/png"
            mock_item.content = b"binary image data"

            result = zim_operations.extract_article_links(str(zim_file), "I/Image")
            assert "Link extraction not supported" in result

    def test_smart_retrieval_direct_access_success(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test smart retrieval when direct access succeeds."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock successful direct entry access
            mock_entry = MagicMock()
            mock_entry.title = "Test Article"
            mock_item = MagicMock()
            mock_item.mimetype = "text/html"
            mock_item.content = b"<html><body>Test content</body></html>"
            mock_entry.get_item.return_value = mock_item
            mock_archive_instance.get_entry_by_path.return_value = mock_entry

            result = zim_operations.get_zim_entry(str(zim_file), "A/Test_Article")

            assert "# Test Article" in result
            assert "Path: A/Test_Article" in result
            assert "Test content" in result

            # Verify path mapping was cached
            cache_key = "path_mapping:A/Test_Article"
            cached_path = zim_operations.cache.get(cache_key)
            assert cached_path == "A/Test_Article"

    def test_smart_retrieval_fallback_to_search(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test smart retrieval fallback to search when direct access fails."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock direct access failure, then successful search
            def mock_get_entry_by_path(path):
                if path == "A/Test Article":  # Original request with space
                    raise Exception("Entry not found")
                elif path == "A/Test_Article":  # Found via search with underscore
                    mock_entry = MagicMock()
                    mock_entry.title = "Test Article"
                    mock_item = MagicMock()
                    mock_item.mimetype = "text/html"
                    mock_item.content = b"<html><body>Test content</body></html>"
                    mock_entry.get_item.return_value = mock_item
                    return mock_entry
                else:
                    raise Exception("Entry not found")

            mock_archive_instance.get_entry_by_path.side_effect = mock_get_entry_by_path

            # Mock the search functionality by patching _find_entry_by_search
            with patch.object(
                zim_operations, "_find_entry_by_search", return_value="A/Test_Article"
            ):
                result = zim_operations.get_zim_entry(str(zim_file), "A/Test Article")

                assert "# Test Article" in result
                assert "Requested Path: A/Test Article" in result
                assert "Actual Path: A/Test_Article" in result
                assert "Test content" in result

                # Verify path mapping was cached
                cache_key = "path_mapping:A/Test Article"
                cached_path = zim_operations.cache.get(cache_key)
                assert cached_path == "A/Test_Article"

    def test_smart_retrieval_cached_path_mapping(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test smart retrieval using cached path mapping."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        # Pre-populate cache with path mapping
        cache_key = "path_mapping:A/Test Article"
        zim_operations.cache.set(cache_key, "A/Test_Article")

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock successful access using cached path
            mock_entry = MagicMock()
            mock_entry.title = "Test Article"
            mock_item = MagicMock()
            mock_item.mimetype = "text/html"
            mock_item.content = b"<html><body>Cached content</body></html>"
            mock_entry.get_item.return_value = mock_item
            mock_archive_instance.get_entry_by_path.return_value = mock_entry

            result = zim_operations.get_zim_entry(str(zim_file), "A/Test Article")

            assert "# Test Article" in result
            assert "Requested Path: A/Test Article" in result
            assert "Actual Path: A/Test_Article" in result
            assert "Cached content" in result

            # Should only be called once with the cached path
            mock_archive_instance.get_entry_by_path.assert_called_once_with(
                "A/Test_Article"
            )

    def test_smart_retrieval_invalid_cached_path(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test smart retrieval when cached path becomes invalid."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        # Pre-populate cache with invalid path mapping
        cache_key = "path_mapping:A/Test Article"
        zim_operations.cache.set(cache_key, "A/Invalid_Path")

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock cached path failure, direct access failure, then search success
            def mock_get_entry_by_path(path):
                if path == "A/Invalid_Path":  # Cached path fails
                    raise Exception("Cached path invalid")
                elif path == "A/Test Article":  # Direct access fails
                    raise Exception("Direct access failed")
                elif path == "A/Test_Article":  # Found via search
                    mock_entry = MagicMock()
                    mock_entry.title = "Test Article"
                    mock_item = MagicMock()
                    mock_item.mimetype = "text/html"
                    mock_item.content = b"<html><body>Found content</body></html>"
                    mock_entry.get_item.return_value = mock_item
                    return mock_entry
                else:
                    raise Exception("Entry not found")

            mock_archive_instance.get_entry_by_path.side_effect = mock_get_entry_by_path

            # Mock the search functionality by patching _find_entry_by_search
            with patch.object(
                zim_operations, "_find_entry_by_search", return_value="A/Test_Article"
            ):
                result = zim_operations.get_zim_entry(str(zim_file), "A/Test Article")

                assert "# Test Article" in result
                assert "Found content" in result

                # Verify invalid cache was cleared and new mapping cached
                cached_path = zim_operations.cache.get(cache_key)
                assert cached_path == "A/Test_Article"

    def test_smart_retrieval_no_search_results(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test smart retrieval when search finds no results."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock direct access failure
            mock_archive_instance.get_entry_by_path.side_effect = Exception(
                "Entry not found"
            )

            # Mock search with no results
            mock_searcher = MagicMock()
            mock_search = MagicMock()
            mock_search.getEstimatedMatches.return_value = 0
            mock_searcher.search.return_value = mock_search

            with (
                patch(
                    "openzim_mcp.zim_operations.Searcher", return_value=mock_searcher
                ),
                patch("openzim_mcp.zim_operations.Query"),
                pytest.raises(OpenZimMcpArchiveError) as exc_info,
            ):
                zim_operations.get_zim_entry(str(zim_file), "A/Nonexistent")

            error_msg = str(exc_info.value)
            assert "Entry not found: 'A/Nonexistent'" in error_msg
            assert "Try using search_zim_file()" in error_msg
            assert "browse_namespace()" in error_msg

    def test_smart_retrieval_search_failure(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test smart retrieval when search itself fails."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock direct access failure
            mock_archive_instance.get_entry_by_path.side_effect = Exception(
                "Direct access failed"
            )

            # Mock search failure by patching _find_entry_by_search to raise exception
            with patch.object(
                zim_operations,
                "_find_entry_by_search",
                side_effect=Exception("Search failed"),
            ):
                with pytest.raises(OpenZimMcpArchiveError) as exc_info:
                    zim_operations.get_zim_entry(str(zim_file), "A/Test")

                error_msg = str(exc_info.value)
                assert "Failed to retrieve entry 'A/Test'" in error_msg
                assert "Direct access failed" in error_msg
                assert "Search-based fallback failed" in error_msg
                assert "Try using search_zim_file()" in error_msg

    def test_extract_search_terms_from_path(self, zim_operations: ZimOperations):
        """Test search term extraction from various path formats."""
        # Test with namespace prefix
        terms = zim_operations._extract_search_terms_from_path("A/Test_Article")
        assert "Test_Article" in terms
        assert "A/Test_Article" in terms
        assert "Test Article" in terms

        # Test with spaces
        terms = zim_operations._extract_search_terms_from_path("A/Test Article")
        assert "Test Article" in terms
        assert "Test_Article" in terms

        # Test URL encoded
        terms = zim_operations._extract_search_terms_from_path("A/Test%20Article")
        assert "Test Article" in terms

        # Test without namespace
        terms = zim_operations._extract_search_terms_from_path("Test_Article")
        assert "Test_Article" in terms
        assert "Test Article" in terms

    def test_is_path_match(self, zim_operations: ZimOperations):
        """Test path matching logic."""
        # Exact match
        assert zim_operations._is_path_match("A/Test", "A/Test")

        # Case insensitive
        assert zim_operations._is_path_match("A/test", "A/Test")

        # Underscore/space variations
        assert zim_operations._is_path_match("A/Test_Article", "A/Test Article")
        assert zim_operations._is_path_match("A/Test Article", "A/Test_Article")

        # URL encoding
        assert zim_operations._is_path_match("A/Test%20Article", "A/Test Article")

        # No match
        assert not zim_operations._is_path_match("A/Test", "A/Different")

    def test_advanced_search_operations(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test advanced search operations to cover more missing lines."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Test search with filters and complex scenarios
            mock_searcher = MagicMock()
            mock_search_result = MagicMock()
            mock_search_result.getEstimatedMatches.return_value = 50
            mock_searcher.search.return_value = mock_search_result

            # Mock getResults to return entries
            def mock_get_results(offset, count):
                return [f"A/Entry_{i}" for i in range(offset, offset + count)]

            mock_search_result.getResults = mock_get_results

            # Mock entries with different namespaces and content types
            def mock_get_entry_by_path(path):
                mock_entry = MagicMock()
                mock_entry.title = f"Title for {path}"
                mock_entry.path = path
                mock_item = MagicMock()

                # Vary content types and namespaces
                if "Entry_0" in path:
                    mock_item.content = b"<html><body>HTML content</body></html>"
                    mock_item.mimetype = "text/html"
                elif "Entry_1" in path:
                    mock_item.content = b"Plain text content"
                    mock_item.mimetype = "text/plain"
                else:
                    mock_item.content = b"Other content"
                    mock_item.mimetype = "application/octet-stream"

                mock_entry.get_item.return_value = mock_item
                return mock_entry

            mock_archive_instance.get_entry_by_path.side_effect = mock_get_entry_by_path

            with (
                patch(
                    "openzim_mcp.zim_operations.Searcher", return_value=mock_searcher
                ),
                patch("openzim_mcp.zim_operations.Query"),
            ):
                # Test search with filters
                result = zim_operations.search_with_filters(
                    str(zim_file),
                    "test",
                    namespace="A",
                    content_type="text/html",
                    limit=10,
                    offset=0,
                )
                assert "Title for" in result
                assert "namespace" in result

    def test_namespace_browsing_comprehensive(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test comprehensive namespace browsing to cover missing lines."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive_instance.entry_count = 100
            mock_archive_instance.has_new_namespace_scheme = (
                False  # Set to boolean value
            )
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock a large number of entries across different namespaces
            mock_entries = []
            for i in range(100):
                mock_entry = MagicMock()
                if i < 30:
                    mock_entry.path = f"A/Article_{i}"
                    mock_entry.title = f"Article {i}"
                elif i < 60:
                    mock_entry.path = f"C/Content_{i}"
                    mock_entry.title = f"Content {i}"
                elif i < 80:
                    mock_entry.path = f"M/Meta_{i}"
                    mock_entry.title = f"Meta {i}"
                else:
                    mock_entry.path = f"I/Image_{i}"
                    mock_entry.title = f"Image {i}"

                # Mock get_item to return serializable data
                mock_item = MagicMock()
                mock_item.mimetype = "text/html"
                mock_item.content = b"<html>Test content</html>"
                mock_entry.get_item.return_value = mock_item

                mock_entries.append(mock_entry)

            # Mock get_random_entry to return entries from our list
            def mock_get_random_entry():
                import random

                return random.choice(mock_entries)

            mock_archive_instance.get_random_entry = mock_get_random_entry

            # Mock has_entry_by_path for common patterns
            def mock_has_entry_by_path(path):
                return any(entry.path == path for entry in mock_entries)

            mock_archive_instance.has_entry_by_path = mock_has_entry_by_path

            # Mock get_entry_by_path
            def mock_get_entry_by_path(path):
                for entry in mock_entries:
                    if entry.path == path:
                        return entry
                raise Exception(f"Entry not found: {path}")

            mock_archive_instance.get_entry_by_path = mock_get_entry_by_path

            # Mock get_entry_by_id to return proper entries
            def mock_get_entry_by_id(entry_id):
                if entry_id < len(mock_entries):
                    return mock_entries[entry_id]
                raise Exception("Entry not found")

            mock_archive_instance.get_entry_by_id.side_effect = mock_get_entry_by_id

            mock_archive_instance.__iter__.return_value = iter(mock_entries)

            # Test browsing with different parameters
            result = zim_operations.browse_namespace(
                str(zim_file), "A", limit=10, offset=5
            )
            assert "namespace" in result
            assert "A" in result

            # Test list_namespaces - this should work now with proper mocking
            result = zim_operations.list_namespaces(str(zim_file))
            assert "namespaces" in result

    def test_search_suggestions_comprehensive(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test comprehensive search suggestions scenarios."""
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock suggestion searcher
            mock_searcher = MagicMock()
            mock_search_result = MagicMock()
            mock_search_result.getEstimatedMatches.return_value = 20
            mock_searcher.search.return_value = mock_search_result

            def mock_get_results(offset, count):
                return [f"A/Suggestion_{i}" for i in range(offset, offset + count)]

            mock_search_result.getResults = mock_get_results

            # Mock entries for suggestions
            def mock_get_entry_by_path(path):
                mock_entry = MagicMock()
                mock_entry.title = f"Suggestion {path.split('_')[-1]}"
                mock_entry.path = path
                return mock_entry

            mock_archive_instance.get_entry_by_path.side_effect = mock_get_entry_by_path

            # Mock archive entry iteration for suggestions
            mock_archive_instance.entry_count = 20

            def mock_get_entry_by_id(entry_id):
                mock_entry = MagicMock()
                mock_entry.title = f"Test Entry {entry_id}"
                mock_entry.path = f"A/Test_{entry_id}"
                return mock_entry

            mock_archive_instance.get_entry_by_id.side_effect = mock_get_entry_by_id

            result = zim_operations.get_search_suggestions(
                str(zim_file), "test", limit=15
            )
            assert "suggestions" in result

    def test_additional_edge_cases_for_coverage(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test additional edge cases to push coverage over 90%."""
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        # Test search suggestions with short query
        result = zim_operations.get_search_suggestions(str(zim_file), "a")
        assert "Query too short for suggestions" in result

        # Test search suggestions with invalid limit
        with pytest.raises(
            OpenZimMcpArchiveError, match="Limit must be between 1 and 50"
        ):
            zim_operations.get_search_suggestions(str(zim_file), "test", limit=0)

        with pytest.raises(
            OpenZimMcpArchiveError, match="Limit must be between 1 and 50"
        ):
            zim_operations.get_search_suggestions(str(zim_file), "test", limit=51)

        # Test browse_namespace with invalid parameters
        with pytest.raises(
            OpenZimMcpArchiveError, match="Limit must be between 1 and 200"
        ):
            zim_operations.browse_namespace(str(zim_file), "A", limit=0)

        with pytest.raises(
            OpenZimMcpArchiveError, match="Limit must be between 1 and 200"
        ):
            zim_operations.browse_namespace(str(zim_file), "A", limit=201)

        with pytest.raises(OpenZimMcpArchiveError, match="Offset must be non-negative"):
            zim_operations.browse_namespace(str(zim_file), "A", offset=-1)

        with pytest.raises(
            OpenZimMcpArchiveError, match="Namespace must be a non-empty string"
        ):
            zim_operations.browse_namespace(str(zim_file), "")

        with pytest.raises(
            OpenZimMcpArchiveError, match="Namespace must be a non-empty string"
        ):
            zim_operations.browse_namespace(str(zim_file), "   ")

        # Test search_with_filters with invalid parameters
        with pytest.raises(
            OpenZimMcpArchiveError, match="Limit must be between 1 and 100"
        ):
            zim_operations.search_with_filters(str(zim_file), "test", limit=0)

        with pytest.raises(
            OpenZimMcpArchiveError, match="Limit must be between 1 and 100"
        ):
            zim_operations.search_with_filters(str(zim_file), "test", limit=101)

        with pytest.raises(OpenZimMcpArchiveError, match="Offset must be non-negative"):
            zim_operations.search_with_filters(str(zim_file), "test", offset=-1)

        # Test parameter validation that exists in the actual methods
        # Note: max_content_length validation happens in server.py,
        # not zim_operations.py

    def test_extract_article_links(self, zim_operations: ZimOperations, temp_dir: Path):
        """Test article link extraction."""
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            # Mock archive with HTML article containing links
            mock_archive_instance = MagicMock()
            mock_entry = MagicMock()
            mock_entry.title = "Test Article"
            mock_entry.path = "C/Test_Article"

            mock_item = MagicMock()
            mock_item.mimetype = "text/html"
            mock_item.content = b"""
            <html>
            <body>
                <p>This article links to <a href="C/Other_Article">
                    another article</a>.</p>
                <p>External link: <a href="https://example.com">Example</a></p>
                <img src="I/image.jpg" alt="Test image">
            </body>
            </html>
            """
            mock_entry.get_item.return_value = mock_item
            mock_archive_instance.get_entry_by_path.return_value = mock_entry
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            result = zim_operations.extract_article_links(
                str(zim_file), "C/Test_Article"
            )

            assert "internal_links" in result
            assert "external_links" in result
            assert "media_links" in result
            assert "total_links" in result


class TestZimOperationsUtilityFunctions:
    """Test utility functions in ZimOperations that don't require complex mocking."""

    @pytest.fixture
    def zim_operations(
        self,
        test_config: OpenZimMcpConfig,
        path_validator: PathValidator,
        openzim_mcp_cache: OpenZimMcpCache,
        content_processor: ContentProcessor,
    ) -> ZimOperations:
        """Create ZimOperations instance for testing."""
        return ZimOperations(
            test_config, path_validator, openzim_mcp_cache, content_processor
        )

    def test_extract_namespace_from_path_new_scheme_with_slash(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction from path with new scheme (has slash)."""
        result = zim_operations._extract_namespace_from_path(
            "content/article/test", True
        )
        assert result == "C"  # content gets mapped to C

    def test_extract_namespace_from_path_new_scheme_no_slash(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction from path with new scheme (no slash)."""
        result = zim_operations._extract_namespace_from_path("A", True)
        assert result == "A"

    def test_extract_namespace_from_path_old_scheme_with_slash(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction from path with old scheme (has slash)."""
        result = zim_operations._extract_namespace_from_path("A/Article_Title", False)
        assert result == "A"

    def test_extract_namespace_from_path_old_scheme_no_slash(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction from path with old scheme (no slash)."""
        result = zim_operations._extract_namespace_from_path("M", False)
        assert result == "M"

    def test_extract_namespace_from_path_empty_string(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction from empty path."""
        result = zim_operations._extract_namespace_from_path("", True)
        assert result == "Unknown"

    def test_extract_namespace_from_path_empty_string_old_scheme(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction from empty path with old scheme."""
        result = zim_operations._extract_namespace_from_path("", False)
        assert result == "Unknown"

    def test_get_common_namespace_patterns_content(self, zim_operations: ZimOperations):
        """Test common namespace patterns for content namespace."""
        patterns = zim_operations._get_common_namespace_patterns("content")

        # content namespace doesn't have specific patterns, should return empty
        assert len(patterns) == 0

    def test_get_common_namespace_patterns_a_namespace(
        self, zim_operations: ZimOperations
    ):
        """Test common namespace patterns for A namespace."""
        patterns = zim_operations._get_common_namespace_patterns("A")

        # Should include various common patterns for A namespace
        assert len(patterns) > 0
        # Check for some expected patterns
        expected_patterns = ["A/index.html", "A/main.html", "A/home.html"]
        for pattern in expected_patterns:
            assert pattern in patterns

    def test_get_common_namespace_patterns_m_namespace(
        self, zim_operations: ZimOperations
    ):
        """Test common namespace patterns for M namespace (metadata)."""
        patterns = zim_operations._get_common_namespace_patterns("M")

        # Should include metadata patterns
        assert len(patterns) > 0
        # Check for some metadata patterns
        metadata_patterns = ["M/Title", "M/Description", "M/Language", "M/Creator"]
        for pattern in metadata_patterns:
            assert pattern in patterns

    def test_get_common_namespace_patterns_unknown_namespace(
        self, zim_operations: ZimOperations
    ):
        """Test common namespace patterns for unknown namespace."""
        patterns = zim_operations._get_common_namespace_patterns("XYZ")

        # Unknown namespaces return empty list
        assert len(patterns) == 0

    def test_extract_namespace_from_path_metadata_mapping(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction for metadata paths."""
        result = zim_operations._extract_namespace_from_path("metadata/title", True)
        assert result == "M"  # metadata gets mapped to M

    def test_extract_namespace_from_path_wellknown_mapping(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction for wellknown paths."""
        result = zim_operations._extract_namespace_from_path("wellknown/mainPage", True)
        assert result == "W"  # wellknown gets mapped to W

    def test_extract_namespace_from_path_search_mapping(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction for search paths."""
        result = zim_operations._extract_namespace_from_path("search/fulltext", True)
        assert result == "X"  # search gets mapped to X

    def test_extract_namespace_from_path_single_char_uppercase(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction for single character paths."""
        result = zim_operations._extract_namespace_from_path("c/article", True)
        assert result == "C"  # single char gets uppercased

    def test_extract_namespace_from_path_unknown_namespace(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction for unknown namespace."""
        result = zim_operations._extract_namespace_from_path("unknown/path", True)
        assert result == "unknown"  # unknown namespace returned as-is

    def test_get_common_namespace_patterns_c_namespace(
        self, zim_operations: ZimOperations
    ):
        """Test common namespace patterns for C namespace."""
        patterns = zim_operations._get_common_namespace_patterns("C")

        # Should include content patterns
        assert len(patterns) > 0
        expected_patterns = [
            "index.html",
            "main.html",
            "home.html",
            "C/index.html",
            "C/main.html",
            "content/index.html",
        ]
        for pattern in expected_patterns:
            assert pattern in patterns

    def test_get_common_namespace_patterns_w_namespace(
        self, zim_operations: ZimOperations
    ):
        """Test common namespace patterns for W namespace."""
        patterns = zim_operations._get_common_namespace_patterns("W")

        # Should include wellknown patterns
        assert len(patterns) > 0
        expected_patterns = ["W/mainPage", "W/favicon", "W/navigation"]
        for pattern in expected_patterns:
            assert pattern in patterns

    def test_get_common_namespace_patterns_x_namespace(
        self, zim_operations: ZimOperations
    ):
        """Test common namespace patterns for X namespace."""
        patterns = zim_operations._get_common_namespace_patterns("X")

        # Should include search patterns
        assert len(patterns) > 0
        expected_patterns = ["X/fulltext", "X/title", "X/search"]
        for pattern in expected_patterns:
            assert pattern in patterns

    def test_get_common_namespace_patterns_i_namespace(
        self, zim_operations: ZimOperations
    ):
        """Test common namespace patterns for I namespace."""
        patterns = zim_operations._get_common_namespace_patterns("I")

        # Should include image patterns
        assert len(patterns) > 0
        expected_patterns = ["I/favicon.png", "I/logo.png", "I/image.jpg"]
        for pattern in expected_patterns:
            assert pattern in patterns


class TestGetBinaryEntry:
    """Test get_binary_entry functionality for binary content retrieval."""

    @pytest.fixture
    def zim_operations(
        self,
        test_config: OpenZimMcpConfig,
        path_validator: PathValidator,
        openzim_mcp_cache: OpenZimMcpCache,
        content_processor: ContentProcessor,
    ) -> ZimOperations:
        """Create ZimOperations instance for testing."""
        return ZimOperations(
            test_config, path_validator, openzim_mcp_cache, content_processor
        )

    def test_get_binary_entry_invalid_path(self, zim_operations: ZimOperations):
        """Test get_binary_entry with invalid file path."""
        with pytest.raises(
            (OpenZimMcpValidationError, OpenZimMcpArchiveError, OpenZimMcpSecurityError)
        ):
            zim_operations.get_binary_entry("/invalid/path.zim", "I/test.png")

    @patch("openzim_mcp.zim_operations.zim_archive")
    def test_get_binary_entry_success(
        self, mock_archive, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test successful binary entry retrieval."""
        import base64
        import json

        # Create a test ZIM file
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        # Mock the archive
        mock_archive_instance = MagicMock()
        mock_entry = MagicMock()
        mock_entry.title = "Test Image"
        mock_item = MagicMock()
        mock_item.mimetype = "image/png"
        # Create a small binary content
        binary_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        mock_item.content = binary_content
        mock_entry.get_item.return_value = mock_item
        mock_archive_instance.get_entry_by_path.return_value = mock_entry
        mock_archive.return_value.__enter__.return_value = mock_archive_instance

        result = zim_operations.get_binary_entry(str(zim_file), "I/test.png")

        # Parse result as JSON
        result_data = json.loads(result)
        assert result_data["path"] == "I/test.png"
        assert result_data["title"] == "Test Image"
        assert result_data["mime_type"] == "image/png"
        assert result_data["size"] == len(binary_content)
        assert result_data["encoding"] == "base64"
        assert result_data["truncated"] is False
        # Verify the data is correct base64
        decoded = base64.b64decode(result_data["data"])
        assert decoded == binary_content

    @patch("openzim_mcp.zim_operations.zim_archive")
    def test_get_binary_entry_metadata_only(
        self, mock_archive, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test binary entry retrieval with metadata only."""
        import json

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        mock_archive_instance = MagicMock()
        mock_entry = MagicMock()
        mock_entry.title = "Test PDF"
        mock_item = MagicMock()
        mock_item.mimetype = "application/pdf"
        mock_item.content = b"%PDF-1.4 test content"
        mock_entry.get_item.return_value = mock_item
        mock_archive_instance.get_entry_by_path.return_value = mock_entry
        mock_archive.return_value.__enter__.return_value = mock_archive_instance

        result = zim_operations.get_binary_entry(
            str(zim_file), "I/doc.pdf", include_data=False
        )

        result_data = json.loads(result)
        assert result_data["path"] == "I/doc.pdf"
        assert result_data["mime_type"] == "application/pdf"
        assert result_data["data"] is None
        assert result_data["encoding"] is None
        assert "Data not included" in result_data.get("message", "")

    @patch("openzim_mcp.zim_operations.zim_archive")
    def test_get_binary_entry_size_limit(
        self, mock_archive, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test binary entry retrieval with content exceeding size limit."""
        import json

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        mock_archive_instance = MagicMock()
        mock_entry = MagicMock()
        mock_entry.title = "Large Video"
        mock_item = MagicMock()
        mock_item.mimetype = "video/mp4"
        # Create content larger than the limit we'll set
        mock_item.content = b"x" * 1000
        mock_entry.get_item.return_value = mock_item
        mock_archive_instance.get_entry_by_path.return_value = mock_entry
        mock_archive.return_value.__enter__.return_value = mock_archive_instance

        # Set a small size limit
        result = zim_operations.get_binary_entry(
            str(zim_file), "I/video.mp4", max_size_bytes=100
        )

        result_data = json.loads(result)
        assert result_data["path"] == "I/video.mp4"
        assert result_data["size"] == 1000
        assert result_data["truncated"] is True
        assert result_data["data"] is None
        assert "exceeds max_size_bytes" in result_data.get("message", "")

    @patch("openzim_mcp.zim_operations.zim_archive")
    def test_get_binary_entry_not_found(
        self, mock_archive, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Test binary entry retrieval when entry not found."""
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        mock_archive_instance = MagicMock()
        mock_archive_instance.get_entry_by_path.side_effect = Exception(
            "Entry not found"
        )
        mock_archive.return_value.__enter__.return_value = mock_archive_instance

        with pytest.raises(OpenZimMcpArchiveError, match="Entry not found"):
            zim_operations.get_binary_entry(str(zim_file), "I/nonexistent.png")

    def test_format_size_bytes(self, zim_operations: ZimOperations):
        """Test _format_size helper with bytes."""
        assert zim_operations._format_size(0) == "0 B"
        assert zim_operations._format_size(500) == "500 B"
        assert zim_operations._format_size(1023) == "1023 B"

    def test_format_size_kilobytes(self, zim_operations: ZimOperations):
        """Test _format_size helper with kilobytes."""
        assert zim_operations._format_size(1024) == "1.00 KB"
        assert zim_operations._format_size(1536) == "1.50 KB"
        assert zim_operations._format_size(10240) == "10.00 KB"

    def test_format_size_megabytes(self, zim_operations: ZimOperations):
        """Test _format_size helper with megabytes."""
        assert zim_operations._format_size(1024 * 1024) == "1.00 MB"
        assert zim_operations._format_size(5 * 1024 * 1024) == "5.00 MB"

    def test_format_size_gigabytes(self, zim_operations: ZimOperations):
        """Test _format_size helper with gigabytes."""
        assert zim_operations._format_size(1024 * 1024 * 1024) == "1.00 GB"
        assert zim_operations._format_size(2 * 1024 * 1024 * 1024) == "2.00 GB"
