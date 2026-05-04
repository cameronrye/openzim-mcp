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

    def test_list_zim_files_skips_symlinks_outside_allowed_root(
        self, zim_operations: ZimOperations, temp_dir: Path, tmp_path_factory
    ):
        """A symlink inside the allowed dir pointing outside MUST be skipped.

        Without this guard, ``Path.glob("**/*.zim")`` follows symlinks and
        the resolved target — which can live anywhere on the filesystem —
        gets included in the listing, defeating the allowed-directories
        access boundary.
        """
        # Make a real ZIM file outside the allowed directory.
        outside_dir = tmp_path_factory.mktemp("outside")
        outside_zim = outside_dir / "secret.zim"
        outside_zim.write_text("outside content")

        # Plant a symlink inside the allowed dir pointing at the outside file.
        link_inside = temp_dir / "evil.zim"
        try:
            link_inside.symlink_to(outside_zim)
        except (OSError, NotImplementedError):
            pytest.skip("filesystem does not support symlinks")

        # Also drop a normal ZIM file inside so we know the scan worked.
        legit = temp_dir / "ok.zim"
        legit.write_text("inside content")

        result = zim_operations.list_zim_files()
        assert "ok.zim" in result, "scan must surface legitimate inside file"
        assert "evil.zim" not in result, "symlink to outside path must be filtered out"
        assert (
            "secret.zim" not in result
        ), "resolved target outside allowed root must not appear"

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
        mock_entry.is_redirect = False
        mock_entry.path = "A/Test_Article"
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
        """Test that successful search results are cached.

        Note: zero-result responses are intentionally not cached (see
        ``tests/test_cache_control.py``); this test exercises a non-empty
        result set to verify the caching path.
        """
        # Create a test ZIM file
        zim_file = temp_dir / "test.zim"
        zim_file.write_text("test content")

        with patch("openzim_mcp.zim_operations.Archive") as mock_archive:
            # Mock successful search with at least one result so the response
            # is cacheable.
            mock_archive_instance = MagicMock()
            mock_archive.return_value = mock_archive_instance

            mock_searcher = MagicMock()
            mock_search = MagicMock()
            mock_search.getEstimatedMatches.return_value = 1
            mock_search.getResults.return_value = ["A/Hit"]
            mock_searcher.search.return_value = mock_search

            mock_entry = MagicMock()
            mock_entry.title = "Hit"
            mock_item = MagicMock()
            mock_item.mimetype = "text/html"
            mock_item.content = b"<html><body>hello</body></html>"
            mock_entry.get_item.return_value = mock_item
            mock_archive_instance.get_entry_by_path.return_value = mock_entry

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

            # Mock metadata entry. ``is_redirect`` defaults to a truthy
            # MagicMock; the metadata extractor now follows redirect chains
            # so an unset value sends every metadata lookup down the
            # redirect-resolution path and skips it as runaway.
            mock_entry = MagicMock()
            mock_entry.is_redirect = False
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
            mock_main_entry.is_redirect = False
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
            mock_archive_instance._get_entry_by_id.side_effect = lambda i: mock_entries[
                i
            ]
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            result = zim_operations.list_namespaces(str(zim_file))

            assert "namespaces" in result
            # entry_count=3 triggers full iteration; counts are exact.
            import json

            result_data = json.loads(result)
            assert "namespaces" in result_data
            assert result_data["is_total_authoritative"] is True
            assert result_data["discovery_method"] == "full_iteration"
            found_namespaces = set(result_data["namespaces"].keys())
            assert found_namespaces == {"C", "M", "W"}

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
        """Test namespace browsing with invalid parameters.

        Parameter-validation failures raise ``OpenZimMcpValidationError``,
        distinct from archive failures so the tool layer can surface a
        targeted error message to callers.
        """
        with pytest.raises(
            OpenZimMcpValidationError, match="Limit must be between 1 and 200"
        ):
            zim_operations.browse_namespace("test.zim", "C", limit=0)

        with pytest.raises(
            OpenZimMcpValidationError, match="Offset must be non-negative"
        ):
            zim_operations.browse_namespace("test.zim", "C", offset=-1)

        with pytest.raises(
            OpenZimMcpSecurityError,
            match="Access denied - Path is outside allowed directories",
        ):
            zim_operations.browse_namespace("test.zim", "ABC", limit=10)

    def test_browse_namespace_raises_validation_error_for_bad_limit(
        self, zim_operations: ZimOperations
    ):
        """Parameter validation should raise OpenZimMcpValidationError, not Archive."""
        with pytest.raises(OpenZimMcpValidationError):
            zim_operations.browse_namespace("test.zim", "A", limit=0, offset=0)

    def test_browse_namespace_raises_validation_error_for_bad_namespace(
        self, zim_operations: ZimOperations
    ):
        """Empty namespace should raise OpenZimMcpValidationError."""
        with pytest.raises(OpenZimMcpValidationError):
            zim_operations.browse_namespace("test.zim", "", limit=10, offset=0)

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
            pass  # NOSONAR  -- body unreachable; zim_archive's __enter__ raises

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
            result, total = zim_operations._perform_search(mock_archive, "test", 10, 0)
            assert "No search results found" in result
            assert total == 0

    def test_get_entry_content_with_redirect(
        self, zim_operations: ZimOperations, tmp_path: Path
    ):
        """Test _get_entry_content with a single-step redirect.

        Single-hop redirects must resolve to the target's path/title and
        return the target's content.
        """
        from unittest.mock import MagicMock

        mock_archive = MagicMock()

        # Target (resolved) entry.
        target_entry = MagicMock()
        target_entry.is_redirect = False
        target_entry.path = "A/United_States"
        target_entry.title = "United States"
        target_item = MagicMock()
        target_item.content = b"<html>Target content</html>"
        target_item.mimetype = "text/html"
        target_entry.get_item.return_value = target_item

        # Redirect entry pointing at the target.
        redirect_entry = MagicMock()
        redirect_entry.is_redirect = True
        redirect_entry.path = "A/USA"
        redirect_entry.title = "USA"
        redirect_entry.get_redirect_entry.return_value = target_entry

        mock_archive.get_entry_by_path.return_value = redirect_entry

        result, content_ok = zim_operations._get_entry_content(
            mock_archive, "A/USA", 1000, tmp_path / "test.zim"
        )
        # Response should reflect the resolved target, not the redirect.
        assert "United States" in result
        assert "A/United_States" in result
        assert content_ok is True

    def test_get_entry_content_redirect_resolution_display(
        self, zim_operations: ZimOperations, tmp_path: Path
    ):
        """Redirect resolution should surface target's Actual Path and Title."""
        from unittest.mock import MagicMock

        mock_archive = MagicMock()

        target_entry = MagicMock()
        target_entry.is_redirect = False
        target_entry.path = "A/United_States"
        target_entry.title = "United States"
        target_item = MagicMock()
        target_item.content = b"Target body"
        target_item.mimetype = "text/plain"
        target_entry.get_item.return_value = target_item

        redirect_entry = MagicMock()
        redirect_entry.is_redirect = True
        redirect_entry.path = "A/USA"
        redirect_entry.title = "USA"
        redirect_entry.get_redirect_entry.return_value = target_entry

        mock_archive.get_entry_by_path.return_value = redirect_entry

        result, content_ok = zim_operations._get_entry_content(
            mock_archive, "A/USA", 1000, tmp_path / "test.zim"
        )

        # Title heading should reflect the target.
        assert result.startswith("# United States")
        # When requested != actual, Requested Path / Actual Path are shown.
        assert "Requested Path: A/USA" in result
        assert "Actual Path: A/United_States" in result
        # The redirect's title must NOT appear as the heading.
        assert not result.startswith("# USA")
        assert content_ok is True

    def test_get_entry_content_redirect_cycle_detection(
        self, zim_operations: ZimOperations, tmp_path: Path
    ):
        """A redirect cycle (A->B->A) must raise OpenZimMcpArchiveError."""
        from unittest.mock import MagicMock

        mock_archive = MagicMock()

        entry_a = MagicMock()
        entry_a.is_redirect = True
        entry_a.path = "A/A"
        entry_a.title = "A"

        entry_b = MagicMock()
        entry_b.is_redirect = True
        entry_b.path = "A/B"
        entry_b.title = "B"

        # A -> B -> A (cycle).
        entry_a.get_redirect_entry.return_value = entry_b
        entry_b.get_redirect_entry.return_value = entry_a

        mock_archive.get_entry_by_path.return_value = entry_a

        with pytest.raises(OpenZimMcpArchiveError) as exc_info:
            zim_operations._get_entry_content(
                mock_archive, "A/A", 1000, tmp_path / "test.zim"
            )

        msg = str(exc_info.value).lower()
        assert "cycle" in msg or "redirect" in msg

    def test_get_entry_content_redirect_depth_limit(
        self, zim_operations: ZimOperations, tmp_path: Path
    ):
        """A redirect chain longer than MAX_REDIRECT_DEPTH must raise."""
        from unittest.mock import MagicMock

        mock_archive = MagicMock()

        # Build a long chain of distinct redirects that never resolves.
        entries = []
        for i in range(20):
            e = MagicMock()
            e.is_redirect = True
            e.path = f"A/r{i}"
            e.title = f"r{i}"
            entries.append(e)
        for i in range(len(entries) - 1):
            entries[i].get_redirect_entry.return_value = entries[i + 1]
        # Last one keeps redirecting to itself's neighbour to keep chain growing.
        entries[-1].get_redirect_entry.return_value = entries[-2]

        mock_archive.get_entry_by_path.return_value = entries[0]

        with pytest.raises(OpenZimMcpArchiveError) as exc_info:
            zim_operations._get_entry_content(
                mock_archive, "A/r0", 1000, tmp_path / "test.zim"
            )

        # Tighten: must hit the depth-limit branch, not the cycle-detection
        # branch. The depth-limit message reads "Redirect chain too deep".
        msg = str(exc_info.value)
        assert "too deep" in msg

    def test_redirect_resolved_path_is_cached(
        self, zim_operations: ZimOperations, tmp_path: Path
    ):
        """The path-mapping cache must store the *resolved* target path.

        For a redirect ``A/USA -> A/United_States``, looking up ``A/USA`` once
        should populate the cache slot with ``"A/United_States"`` so the next
        request for ``A/USA`` skips the redirect chain entirely.
        """
        from unittest.mock import MagicMock

        mock_archive = MagicMock()

        # Resolved target.
        target_entry = MagicMock()
        target_entry.is_redirect = False
        target_entry.path = "A/United_States"
        target_entry.title = "United States"
        target_item = MagicMock()
        target_item.content = b"<html>Target content</html>"
        target_item.mimetype = "text/html"
        target_entry.get_item.return_value = target_item

        # Redirect stub.
        redirect_entry = MagicMock()
        redirect_entry.is_redirect = True
        redirect_entry.path = "A/USA"
        redirect_entry.title = "USA"
        redirect_entry.get_redirect_entry.return_value = target_entry

        mock_archive.get_entry_by_path.return_value = redirect_entry

        zim_file = tmp_path / "test.zim"
        zim_operations._get_entry_content(mock_archive, "A/USA", 1000, zim_file)

        cache_key = f"path_mapping:{zim_file}:A/USA"
        cached = zim_operations.cache.get(cache_key)
        assert cached == "A/United_States", (
            "Cache must store the resolved path so subsequent "
            "lookups skip the redirect chain."
        )

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
                    mock_entry.is_redirect = False
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

    def test_get_metadata_resolves_redirect_entries(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Metadata redirects must be resolved before calling get_item().

        libzim raises RuntimeError if get_item() is invoked on a redirect entry,
        so the extractor walks the redirect chain first.
        """
        from unittest.mock import MagicMock, patch

        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive_instance.entry_count = 1
            mock_archive_instance.all_entry_count = 1
            mock_archive_instance.article_count = 0
            mock_archive_instance.media_count = 0

            target_item = MagicMock()
            target_item.content = b"Resolved Title"
            target_entry = MagicMock()
            target_entry.is_redirect = False
            target_entry.get_item.return_value = target_item

            redirect_entry = MagicMock()
            redirect_entry.is_redirect = True
            redirect_entry.get_redirect_entry.return_value = target_entry

            def mock_get_entry_by_path(path):
                if path == "M/Title":
                    return redirect_entry
                raise Exception("Entry not found")

            mock_archive_instance.get_entry_by_path.side_effect = mock_get_entry_by_path
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            result = zim_operations.get_zim_metadata(str(zim_file))
            assert "Resolved Title" in result
            redirect_entry.get_item.assert_not_called()
            target_entry.get_item.assert_called_once()

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
            # Old-scheme paths are namespace-prefixed (A/Test_Entry); declare
            # the scheme explicitly so the new-scheme short-circuit doesn't
            # fire and skip the search results.
            mock_archive_instance.has_new_namespace_scheme = False
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
            OpenZimMcpValidationError, match="Limit must be between 1 and 50"
        ):
            zim_operations.get_search_suggestions(str(zim_file), "test", limit=0)

        # Test limit too high
        with pytest.raises(
            OpenZimMcpValidationError, match="Limit must be between 1 and 50"
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
        cache_key = f"entry:{validated_path}:A/Test:1000:0"
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

        # Test extract_article_links cache hit. The cache key now includes
        # pagination and kind so different page requests don't collide; match
        # the default-arg call site below.
        cache_key = f"links:{validated_path}:A/Test:100:0:"
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
            mock_entry.is_redirect = False
            mock_entry.title = "Test Article"
            mock_entry.path = "A/Test"

            # Test scenario where get_item() fails (lines 956-957)
            mock_entry.get_item.side_effect = Exception("Item access error")
            mock_archive_instance.get_entry_by_path.return_value = mock_entry

            # The public method re-raises typed inner OpenZimMcpArchiveError
            # without re-wrapping (so the message no longer carries the
            # "Structure extraction failed:" outer prefix), but the inner
            # helper still attaches its own "Failed to extract article
            # structure: ..." prefix, which is what we match here.
            with pytest.raises(
                OpenZimMcpArchiveError,
                match="Failed to extract article structure",
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
                mock_entry.is_redirect = False
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
            mock_entry.is_redirect = False
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
            mock_entry.is_redirect = False
            mock_entry.path = "A/Test_Article"
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

            # Verify path mapping was cached (key includes resolved archive path)
            cache_key = f"path_mapping:{zim_file.resolve()}:A/Test_Article"
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
                    mock_entry.is_redirect = False
                    mock_entry.path = "A/Test_Article"
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

                # Verify path mapping was cached (key includes resolved archive path)
                cache_key = f"path_mapping:{zim_file.resolve()}:A/Test Article"
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
        cache_key = f"path_mapping:{zim_file.resolve()}:A/Test Article"
        zim_operations.cache.set(cache_key, "A/Test_Article")

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            # Mock successful access using cached path
            mock_entry = MagicMock()
            mock_entry.is_redirect = False
            mock_entry.path = "A/Test_Article"
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
        cache_key = f"path_mapping:{zim_file.resolve()}:A/Test Article"
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
                    mock_entry.is_redirect = False
                    mock_entry.path = "A/Test_Article"
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
            # Test paths use the old-scheme A/Entry_N convention; declare it
            # so the new-scheme short-circuit doesn't skip them.
            mock_archive_instance.has_new_namespace_scheme = False
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

            # Mock _get_entry_by_id to return proper entries
            def mock_get_entry_by_id(entry_id):
                if entry_id < len(mock_entries):
                    return mock_entries[entry_id]
                raise Exception("Entry not found")

            mock_archive_instance._get_entry_by_id.side_effect = mock_get_entry_by_id

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
            OpenZimMcpValidationError, match="Limit must be between 1 and 50"
        ):
            zim_operations.get_search_suggestions(str(zim_file), "test", limit=0)

        with pytest.raises(
            OpenZimMcpValidationError, match="Limit must be between 1 and 50"
        ):
            zim_operations.get_search_suggestions(str(zim_file), "test", limit=51)

        # Test browse_namespace with invalid parameters. Parameter-validation
        # failures raise OpenZimMcpValidationError, which is distinct from
        # OpenZimMcpArchiveError raised by archive-access failures.
        with pytest.raises(
            OpenZimMcpValidationError, match="Limit must be between 1 and 200"
        ):
            zim_operations.browse_namespace(str(zim_file), "A", limit=0)

        with pytest.raises(
            OpenZimMcpValidationError, match="Limit must be between 1 and 200"
        ):
            zim_operations.browse_namespace(str(zim_file), "A", limit=201)

        with pytest.raises(
            OpenZimMcpValidationError, match="Offset must be non-negative"
        ):
            zim_operations.browse_namespace(str(zim_file), "A", offset=-1)

        with pytest.raises(
            OpenZimMcpValidationError, match="Namespace must be a non-empty string"
        ):
            zim_operations.browse_namespace(str(zim_file), "")

        with pytest.raises(
            OpenZimMcpValidationError, match="Namespace must be a non-empty string"
        ):
            zim_operations.browse_namespace(str(zim_file), "   ")

        # Test search_with_filters with invalid parameters. Parameter
        # validation surfaces as OpenZimMcpValidationError so the tool
        # layer can render targeted "bad parameter" messages.
        with pytest.raises(
            OpenZimMcpValidationError, match="Limit must be between 1 and 100"
        ):
            zim_operations.search_with_filters(str(zim_file), "test", limit=0)

        with pytest.raises(
            OpenZimMcpValidationError, match="Limit must be between 1 and 100"
        ):
            zim_operations.search_with_filters(str(zim_file), "test", limit=101)

        with pytest.raises(
            OpenZimMcpValidationError, match="Offset must be non-negative"
        ):
            zim_operations.search_with_filters(str(zim_file), "test", offset=-1)

        # Test parameter validation that exists in the actual methods
        # Note: max_content_length validation happens in server.py,
        # not zim_operations.py

    def test_filtered_search_does_not_materialize_offset_window(
        self, zim_operations: ZimOperations, temp_dir: Path
    ):
        """Skip-counter pagination must not materialise the offset window.

        With ``offset=900, limit=10`` and 1000 raw matches all in a single
        namespace, the old "accumulate then slice" code calls
        ``get_entry_by_path`` for ~910 entries (offset + limit). The
        skip-counter implementation should only need to materialize entries
        for the collected page (about ~limit entries when no filter is
        applied), giving a generous upper bound well below 910.
        """
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive_instance = MagicMock()
            mock_archive.return_value.__enter__.return_value = mock_archive_instance

            mock_searcher = MagicMock()
            mock_search_result = MagicMock()
            mock_search_result.getEstimatedMatches.return_value = 1000

            def mock_get_results(start, count):
                # libzim returns paths as strings; namespace is derivable
                # from the leading prefix without needing an Entry.
                return [f"A/Entry_{i}" for i in range(start, start + count)]

            mock_search_result.getResults = mock_get_results
            mock_searcher.search.return_value = mock_search_result

            # Track every get_entry_by_path call so we can assert no
            # over-fetch for skipped entries.
            calls: list[str] = []

            def make_entry(path: str):
                e = MagicMock()
                e.path = path
                e.title = f"Title for {path}"
                item = MagicMock()
                item.mimetype = "text/html"
                item.content = b"<p>x</p>"
                e.get_item.return_value = item
                return e

            def tracked_get(path):
                calls.append(path)
                return make_entry(path)

            mock_archive_instance.get_entry_by_path.side_effect = tracked_get

            with (
                patch(
                    "openzim_mcp.zim_operations.Searcher", return_value=mock_searcher
                ),
                patch("openzim_mcp.zim_operations.Query"),
            ):
                zim_operations.search_with_filters(
                    str(zim_file),
                    "test",
                    namespace=None,
                    content_type=None,
                    limit=10,
                    offset=900,
                )

            # Old materialise-then-slice would call get_entry_by_path ~910
            # times (offset + limit). Skip-counter should keep this much
            # lower — generous slack for snippet rendering, MIME re-reads,
            # etc.
            assert len(calls) < 200, (
                f"get_entry_by_path called {len(calls)} times; "
                "expected skip-counter to skip the offset window without "
                "materialising entries"
            )

    def test_extract_article_links(self, zim_operations: ZimOperations, temp_dir: Path):
        """Test article link extraction."""
        zim_file = temp_dir / "test.zim"
        zim_file.touch()

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            # Mock archive with HTML article containing links
            mock_archive_instance = MagicMock()
            mock_entry = MagicMock()
            mock_entry.is_redirect = False
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
        result = zim_operations._extract_namespace_from_path("content/article/test")
        assert result == "C"  # content gets mapped to C

    def test_extract_namespace_from_path_new_scheme_no_slash(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction from path with new scheme (no slash)."""
        result = zim_operations._extract_namespace_from_path("A")
        assert result == "A"

    def test_extract_namespace_from_path_old_scheme_with_slash(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction from path with old scheme (has slash)."""
        result = zim_operations._extract_namespace_from_path("A/Article_Title")
        assert result == "A"

    def test_extract_namespace_from_path_old_scheme_no_slash(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction from path with old scheme (no slash)."""
        result = zim_operations._extract_namespace_from_path("M")
        assert result == "M"

    def test_extract_namespace_from_path_empty_string(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction from empty path."""
        result = zim_operations._extract_namespace_from_path("")
        assert result == "Unknown"

    def test_extract_namespace_from_path_empty_string_old_scheme(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction from empty path with old scheme."""
        result = zim_operations._extract_namespace_from_path("")
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
        result = zim_operations._extract_namespace_from_path("metadata/title")
        assert result == "M"  # metadata gets mapped to M

    def test_extract_namespace_from_path_wellknown_mapping(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction for wellknown paths."""
        result = zim_operations._extract_namespace_from_path("wellknown/mainPage")
        assert result == "W"  # wellknown gets mapped to W

    def test_extract_namespace_from_path_search_mapping(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction for search paths."""
        result = zim_operations._extract_namespace_from_path("search/fulltext")
        assert result == "X"  # search gets mapped to X

    def test_extract_namespace_from_path_single_char_uppercase(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction for single character paths."""
        result = zim_operations._extract_namespace_from_path("c/article")
        assert result == "C"  # single char gets uppercased

    def test_extract_namespace_from_path_unknown_namespace(
        self, zim_operations: ZimOperations
    ):
        """Test namespace extraction for unknown namespace."""
        result = zim_operations._extract_namespace_from_path("unknown/path")
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
        mock_entry.is_redirect = False
        mock_entry.title = "Test Image"
        mock_item = MagicMock()
        mock_item.mimetype = "image/png"
        # Create a small binary content
        binary_content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        mock_item.content = binary_content
        mock_item.size = len(binary_content)
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
        mock_entry.is_redirect = False
        mock_entry.title = "Test PDF"
        mock_item = MagicMock()
        mock_item.mimetype = "application/pdf"
        mock_item.content = b"%PDF-1.4 test content"
        mock_item.size = len(b"%PDF-1.4 test content")
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
        mock_entry.is_redirect = False
        mock_entry.title = "Large Video"
        mock_item = MagicMock()
        mock_item.mimetype = "video/mp4"
        # Create content larger than the limit we'll set
        mock_item.content = b"x" * 1000
        mock_item.size = 1000
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


class TestGetEntrySummaryMaxWords:
    """Tests that get_entry_summary honors the documented max_words range.

    The tool layer enforces a [1, 1000] contract; the operation layer must
    not silently floor low values.
    """

    @pytest.fixture
    def zim_operations(
        self,
        test_config: OpenZimMcpConfig,
        path_validator: PathValidator,
        openzim_mcp_cache: OpenZimMcpCache,
        content_processor: ContentProcessor,
    ) -> ZimOperations:
        """Provide a ZimOperations instance for max_words tests."""
        return ZimOperations(
            test_config, path_validator, openzim_mcp_cache, content_processor
        )

    @patch("openzim_mcp.zim_operations.zim_archive")
    def test_get_entry_summary_max_words_one_returns_one_word(
        self, mock_archive, zim_operations: ZimOperations, temp_dir: Path
    ):
        """max_words=1 must return exactly 1 word, not silently bumped to 10."""
        import json as _json

        zim_file = temp_dir / "test.zim"
        zim_file.write_bytes(b"")

        mock_archive_instance = MagicMock()
        mock_entry = MagicMock()
        mock_entry.is_redirect = False
        # _resolve_entry_with_fallback returns ``resolved.path`` so callers
        # surface the post-redirect canonical path. Tests that mock the
        # entry must set ``.path`` to a real string — leaving it as a
        # MagicMock breaks json.dumps when the path is written into the
        # response payload.
        mock_entry.path = "A/Plain"
        mock_entry.title = "Plain"
        mock_item = MagicMock()
        mock_item.mimetype = "text/plain"
        body = b"alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"
        mock_item.content = body
        mock_item.size = len(body)
        mock_entry.get_item.return_value = mock_item
        mock_archive_instance.get_entry_by_path.return_value = mock_entry
        mock_archive.return_value.__enter__.return_value = mock_archive_instance

        result = zim_operations.get_entry_summary(str(zim_file), "A/Plain", max_words=1)
        data = _json.loads(result)

        assert data["word_count"] == 1
        assert data["summary"] == "alpha..."
        assert data["is_truncated"] is True


class TestZimOperationsGetEntries:
    """Tests for ZimOperations.get_entries (batch retrieval)."""

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

    def test_get_entries_empty_list_raises(self, zim_operations: ZimOperations):
        """Empty entries list is rejected at the boundary."""
        with pytest.raises(OpenZimMcpValidationError):
            zim_operations.get_entries([])

    def test_get_entries_over_limit_raises(self, zim_operations: ZimOperations):
        """Batches above MAX_BATCH_SIZE are rejected at the boundary."""
        too_many = [{"zim_file_path": "/x", "entry_path": "y"} for _ in range(51)]
        with pytest.raises(OpenZimMcpValidationError):
            zim_operations.get_entries(too_many)

    @patch("openzim_mcp.zim_operations.Archive")
    def test_get_entries_happy_path(
        self,
        mock_archive,
        zim_operations: ZimOperations,
        temp_dir: Path,
    ):
        """Two entries succeed; results preserve input order via index."""
        import json

        zim_file = temp_dir / "test.zim"
        zim_file.write_text("test content")

        mock_archive_instance = MagicMock()
        mock_archive.return_value = mock_archive_instance
        entry = MagicMock()
        entry.title = "Article"
        item = MagicMock()
        item.mimetype = "text/html"
        item.content = b"<html><body><p>hello</p></body></html>"
        entry.get_item.return_value = item
        mock_archive_instance.get_entry_by_path.return_value = entry

        result = zim_operations.get_entries(
            [
                {"zim_file_path": str(zim_file), "entry_path": "A/One"},
                {"zim_file_path": str(zim_file), "entry_path": "A/Two"},
            ]
        )
        data = json.loads(result)

        assert len(data["results"]) == 2
        assert [r["index"] for r in data["results"]] == [0, 1]
        assert data["succeeded"] + data["failed"] == 2

    @patch("openzim_mcp.zim_operations.Archive")
    def test_get_entries_partial_success(
        self,
        mock_archive,
        zim_operations: ZimOperations,
        temp_dir: Path,
    ):
        """A failing entry doesn't abort the batch — it's reported as failed."""
        import json

        zim_file = temp_dir / "test.zim"
        zim_file.write_text("test content")

        # First call returns a real entry, second raises.
        good = MagicMock()
        good.is_redirect = False
        good.path = "A/Good"
        good.title = "ok"
        good_item = MagicMock()
        good_item.mimetype = "text/html"
        good_item.content = b"<html><body><p>x</p></body></html>"
        good.get_item.return_value = good_item

        archive_instance = MagicMock()
        archive_instance.get_entry_by_path.side_effect = [
            good,
            Exception("not found"),
        ]
        mock_archive.return_value = archive_instance

        result = zim_operations.get_entries(
            [
                {"zim_file_path": str(zim_file), "entry_path": "A/Good"},
                {"zim_file_path": str(zim_file), "entry_path": "A/Missing"},
            ]
        )
        data = json.loads(result)
        assert len(data["results"]) == 2
        assert data["succeeded"] == 1
        assert data["failed"] == 1
        # Failure is recorded with success=False and an error string
        bad = next(r for r in data["results"] if not r["success"])
        assert "error" in bad

    def test_get_entries_opens_archive_once_per_file(
        self,
        zim_operations: ZimOperations,
        temp_dir: Path,
        monkeypatch,
    ):
        """N entries from a single ZIM file open the archive exactly once.

        Performance-driven invariant: ``get_entries`` must group requests by
        ``zim_file_path`` and open each archive once for the whole group,
        rather than re-opening per entry through ``get_zim_entry``.
        """
        from contextlib import contextmanager

        import openzim_mcp.zim_operations as zo_mod

        zim_file = temp_dir / "test.zim"
        zim_file.write_text("test content")

        opens: list[Path] = []
        original = zo_mod.zim_archive

        @contextmanager
        def tracking(path, *args, **kwargs):
            opens.append(path)
            archive_instance = MagicMock()
            entry = MagicMock()
            entry.is_redirect = False
            entry.path = "A/Entry"
            entry.title = "Entry"
            item = MagicMock()
            item.mimetype = "text/html"
            item.content = b"<html><body><p>x</p></body></html>"
            entry.get_item.return_value = item
            archive_instance.get_entry_by_path.return_value = entry
            yield archive_instance

        monkeypatch.setattr(zo_mod, "zim_archive", tracking)

        # Four entries from the same ZIM file
        entries = [
            {"zim_file_path": str(zim_file), "entry_path": f"A/E{i}"} for i in range(4)
        ]
        zim_operations.get_entries(entries)

        assert (
            len(opens) == 1
        ), f"opened archive {len(opens)} times for one file, expected 1"
        # Sanity: original is unchanged so other tests still work
        assert zo_mod.zim_archive is tracking
        # Avoid lint warning about unused
        _ = original

    def test_get_entries_groups_by_zim_file(
        self,
        zim_operations: ZimOperations,
        temp_dir: Path,
        monkeypatch,
    ):
        """Two ZIM files in the input should each be opened exactly once."""
        from contextlib import contextmanager

        import openzim_mcp.zim_operations as zo_mod

        zim_a = temp_dir / "a.zim"
        zim_a.write_text("aaa")
        zim_b = temp_dir / "b.zim"
        zim_b.write_text("bbb")

        opens: list[Path] = []

        @contextmanager
        def tracking(path, *args, **kwargs):
            opens.append(path)
            archive_instance = MagicMock()
            entry = MagicMock()
            entry.is_redirect = False
            entry.path = "A/Entry"
            entry.title = "Entry"
            item = MagicMock()
            item.mimetype = "text/html"
            item.content = b"<p>x</p>"
            entry.get_item.return_value = item
            archive_instance.get_entry_by_path.return_value = entry
            yield archive_instance

        monkeypatch.setattr(zo_mod, "zim_archive", tracking)

        # 3 entries in a.zim, 2 in b.zim — interleaved input order to verify
        # grouping doesn't depend on adjacency.
        entries = [
            {"zim_file_path": str(zim_a), "entry_path": "A/1"},
            {"zim_file_path": str(zim_b), "entry_path": "A/1"},
            {"zim_file_path": str(zim_a), "entry_path": "A/2"},
            {"zim_file_path": str(zim_b), "entry_path": "A/2"},
            {"zim_file_path": str(zim_a), "entry_path": "A/3"},
        ]
        zim_operations.get_entries(entries)

        assert (
            len(opens) == 2
        ), f"expected one open per file (2), got {len(opens)}: {opens}"


class TestZimOperationsPerfFixes:
    """Performance hardening tests for v1.0 review tasks 7.4, 7.5, 7.6."""

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

    # ----- Task 7.4: namespace listing cached once per (file, namespace) ----

    def test_browse_namespace_caches_full_listing_once_per_archive_namespace(
        self,
        zim_operations: ZimOperations,
        temp_dir: Path,
        monkeypatch,
    ):
        """Different (limit, offset) pages must not re-scan the namespace."""
        from contextlib import contextmanager

        import openzim_mcp.zim_operations as zo_mod

        zim_file = temp_dir / "ns.zim"
        zim_file.write_text("z")

        archive_instance = MagicMock()
        archive_instance.has_new_namespace_scheme = False

        # Build a deterministic entry-path → entry mapping. Pagination must
        # all be served from the same scan.
        paths = [f"A/Article_{i}" for i in range(30)]

        def make_entry(path: str):
            entry = MagicMock()
            entry.path = path
            entry.title = path.split("/", 1)[1]
            item = MagicMock()
            item.mimetype = "text/html"
            item.content = b"<p>x</p>"
            entry.get_item.return_value = item
            return entry

        def get_by_path(p):
            return make_entry(p)

        archive_instance.get_entry_by_path.side_effect = get_by_path

        @contextmanager
        def fake_zim_archive(path, *args, **kwargs):
            yield archive_instance

        monkeypatch.setattr(zo_mod, "zim_archive", fake_zim_archive)

        # Force _find_entries_in_namespace to return the deterministic list
        # and count invocations.
        scan_calls = {"count": 0}

        def fake_find(archive, namespace, has_new_scheme):
            scan_calls["count"] += 1
            return list(paths), True

        monkeypatch.setattr(zim_operations, "_find_entries_in_namespace", fake_find)

        zim_operations.browse_namespace(str(zim_file), "A", limit=10, offset=0)
        zim_operations.browse_namespace(str(zim_file), "A", limit=10, offset=10)
        zim_operations.browse_namespace(str(zim_file), "A", limit=10, offset=20)

        # The expensive namespace scan should run exactly once even though we
        # paginated three different windows.
        assert (
            scan_calls["count"] == 1
        ), f"expected one full namespace scan, got {scan_calls['count']}"

    # ----- Task 7.5: Searcher reused across path-fallback search terms -----

    def test_find_entry_by_search_reuses_searcher_across_terms(
        self,
        zim_operations: ZimOperations,
        monkeypatch,
    ):
        """Searcher() construction must be hoisted out of the per-term loop."""
        construct_count = {"count": 0}

        class CountingSearcher:
            """Plain stand-in for libzim.Searcher.

            libzim.Searcher binds via C++ and refuses non-Archive arguments,
            so we replace it wholesale rather than subclassing it.
            """

            def __init__(self, archive):
                construct_count["count"] += 1
                self._archive = archive

            def search(self, query):
                fake_search = MagicMock()
                # Return zero matches so every fallback term is tried,
                # exercising the loop fully.
                fake_search.getEstimatedMatches.return_value = 0
                fake_search.getResults.return_value = []
                return fake_search

        # Patch both the libzim.search module (the source of the
        # function-local ``from libzim.search import Searcher`` rebinding)
        # and the libzim package re-export.
        monkeypatch.setattr("libzim.search.Searcher", CountingSearcher)

        archive = MagicMock()
        # A path that yields multiple search-term variants — the loop will
        # iterate every one. Searcher must still only be built once.
        zim_operations._find_entry_by_search(archive, "A/Some_Test_Path")

        assert (
            construct_count["count"] == 1
        ), f"expected Searcher to be built once, got {construct_count['count']}"

    # ----- Task 7.6: SuggestionSearcher replaces strided ID scan ------------

    def test_generate_search_suggestions_uses_suggestion_searcher(
        self,
        zim_operations: ZimOperations,
        monkeypatch,
    ):
        """Strategy 2 must use SuggestionSearcher, not stride over entry IDs."""
        suggest_called = {"count": 0}
        get_entry_by_id_calls = {"count": 0}

        class CountingSS:
            """Plain stand-in for libzim.SuggestionSearcher.

            libzim.SuggestionSearcher binds via C++ and refuses non-Archive
            arguments, so we substitute the whole class.
            """

            def __init__(self, archive):
                suggest_called["count"] += 1
                self._archive = archive

            def suggest(self, text):
                fake = MagicMock()
                fake.getEstimatedMatches.return_value = 0
                fake.getResults.return_value = []
                return fake

        # The module under test imports SuggestionSearcher at module level,
        # so patch the rebound symbol there as well.
        monkeypatch.setattr("libzim.suggestion.SuggestionSearcher", CountingSS)
        monkeypatch.setattr("openzim_mcp.zim_operations.SuggestionSearcher", CountingSS)

        # Force Strategy 1 to return zero suggestions so Strategy 2 fires.
        monkeypatch.setattr(
            zim_operations,
            "_get_suggestions_from_search",
            lambda *a, **kw: [],
        )

        archive = MagicMock()
        archive.entry_count = 100_000

        # Track strided ID scan as a regression sentinel — the previous
        # implementation called _get_entry_by_id once per stride.
        def boom(*_a, **_kw):
            get_entry_by_id_calls["count"] += 1
            raise AssertionError(
                "Strategy 2 must not call archive._get_entry_by_id; "
                "use SuggestionSearcher instead"
            )

        archive._get_entry_by_id.side_effect = boom

        result = zim_operations._generate_search_suggestions(archive, "bio", limit=10)

        assert (
            suggest_called["count"] >= 1
        ), "expected SuggestionSearcher to be used in Strategy 2"
        assert (
            get_entry_by_id_calls["count"] == 0
        ), "Strategy 2 must not stride-scan via _get_entry_by_id"
        # Result still has to be valid JSON describing zero matches.
        import json as _json

        parsed = _json.loads(result)
        assert parsed["partial_query"] == "bio"
        assert "suggestions" in parsed
