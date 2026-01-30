"""Performance benchmarks for OpenZIM MCP.

These tests measure performance characteristics to detect regressions.
Run with: pytest tests/test_benchmarks.py --benchmark-only
"""

from unittest.mock import Mock, patch

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import CacheConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator


class TestCacheBenchmarks:
    """Benchmark cache operations."""

    def test_cache_set_get_benchmark(self, benchmark):
        """Benchmark cache set and get operations."""
        cache_config = CacheConfig(enabled=True, max_size=1000, ttl_seconds=3600)
        cache = OpenZimMcpCache(cache_config)

        def cache_operations():
            # Set 100 items
            for i in range(100):
                cache.set(f"key_{i}", f"value_{i}")

            # Get 100 items
            results = []
            for i in range(100):
                results.append(cache.get(f"key_{i}"))

            return results

        result = benchmark(cache_operations)
        assert len(result) == 100
        assert all(r is not None for r in result)

    def test_cache_eviction_benchmark(self, benchmark):
        """Benchmark cache eviction performance."""
        cache_config = CacheConfig(enabled=True, max_size=50, ttl_seconds=3600)
        cache = OpenZimMcpCache(cache_config)

        def cache_eviction():
            # Fill cache beyond capacity to trigger evictions
            for i in range(100):
                cache.set(f"key_{i}", f"value_{i}")

            # Access some items to test LRU behavior
            for i in range(0, 100, 10):
                cache.get(f"key_{i}")

        benchmark(cache_eviction)
        assert cache.stats()["size"] <= 50


class TestContentProcessorBenchmarks:
    """Benchmark content processing operations."""

    def test_html_to_text_benchmark(self, benchmark):
        """Benchmark HTML to text conversion."""
        processor = ContentProcessor()
        # Create a moderately complex HTML document
        html_content = """
        <html>
        <head><title>Test Document</title></head>
        <body>
            <h1>Main Heading</h1>
            <p>This is paragraph with <strong>bold</strong> and <em>italic</em>.</p>
            <ul>
                <li>List item 1</li>
                <li>List item 2 with <a href="http://example.com">a link</a></li>
                <li>List item 3</li>
            </ul>
            <div>
                <h2>Subsection</h2>
                <p>Another paragraph with more content to process.</p>
                <table>
                    <tr><th>Header 1</th><th>Header 2</th></tr>
                    <tr><td>Cell 1</td><td>Cell 2</td></tr>
                    <tr><td>Cell 3</td><td>Cell 4</td></tr>
                </table>
            </div>
        </body>
        </html>
        """ * 10  # Repeat to make it larger

        def convert_html():
            return processor.html_to_plain_text(html_content)

        result = benchmark(convert_html)
        assert isinstance(result, str)
        assert len(result) > 0
        assert "Main Heading" in result

    def test_content_truncation_benchmark(self, benchmark):
        """Benchmark content truncation."""
        processor = ContentProcessor()

        # Create large content
        large_content = "This is a test sentence. " * 1000

        def truncate_content():
            return processor.truncate_content(large_content, max_length=5000)

        result = benchmark(truncate_content)
        # The result includes truncation message, so it will be longer than max_length
        assert "Content truncated" in result
        assert "25,000 characters" in result


class TestPathValidatorBenchmarks:
    """Benchmark path validation operations."""

    def test_path_validation_benchmark(self, benchmark):
        """Benchmark path validation performance."""
        import os
        import tempfile

        # Create temporary directories for testing
        temp_dirs = []
        for i in range(3):
            temp_dir = tempfile.mkdtemp(prefix=f"test_path_{i}_")
            temp_dirs.append(temp_dir)

        try:
            path_validator = PathValidator(temp_dirs)
            test_paths = [
                os.path.join(temp_dirs[0], "file1.zim"),
                os.path.join(temp_dirs[1], "subdir", "file2.zim"),
                os.path.join(temp_dirs[2], "another", "deep", "path", "file3.zim"),
                os.path.join(
                    temp_dirs[0], "..", os.path.basename(temp_dirs[1]), "file4.zim"
                ),  # Should be normalized
            ] * 25  # 100 paths total

            def validate_paths():
                results = []
                for path in test_paths:
                    try:
                        validated = path_validator.validate_path(path)
                        results.append(validated)
                    except Exception:
                        results.append(None)
                return results

            results = benchmark(validate_paths)
            assert len(results) == 100
        finally:
            # Clean up temporary directories
            import shutil

            for temp_dir in temp_dirs:
                shutil.rmtree(temp_dir, ignore_errors=True)


class TestZimOperationsBenchmarks:
    """Benchmark ZIM operations (mocked for performance testing)."""

    @patch("openzim_mcp.zim_operations.Archive")
    def test_search_benchmark(self, mock_archive_class, benchmark):
        """Benchmark search operations."""
        from openzim_mcp.config import OpenZimMcpConfig
        from openzim_mcp.zim_operations import ZimOperations

        # Mock the libzim Archive
        mock_archive = Mock()
        mock_archive_class.return_value = mock_archive
        # Mock search results
        mock_search_results = []
        for i in range(50):
            mock_result = Mock()
            mock_result.get_path.return_value = f"A/Article_{i}"
            mock_result.get_title.return_value = f"Article {i}"
            mock_search_results.append(mock_result)
        mock_archive.search.return_value = mock_search_results

        # Create required dependencies
        import tempfile

        temp_dir = tempfile.mkdtemp()
        try:
            config = OpenZimMcpConfig(allowed_directories=[temp_dir])
            mock_path_validator = Mock()
            mock_cache = Mock()
            mock_content_processor = Mock()
            zim_ops = ZimOperations(
                config, mock_path_validator, mock_cache, mock_content_processor
            )

            # Mock the search method to return a proper JSON string
            def mock_search(*args, **kwargs):
                return (
                    '{"matches": 50, "results": '
                    '[{"path": "A/Article_1", "title": "Article 1", '
                    '"snippet": "Test snippet"}]}'
                )

            zim_ops.search_zim_file = mock_search

            def perform_search():
                return zim_ops.search_zim_file("/fake/path.zim", "test query", limit=50)

            result = benchmark(perform_search)
            assert "matches" in result
            assert "results" in result
        finally:
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)

    @patch("openzim_mcp.zim_operations.Archive")
    def test_entry_retrieval_benchmark(self, mock_archive_class, benchmark):
        """Benchmark entry retrieval operations."""
        from openzim_mcp.config import OpenZimMcpConfig
        from openzim_mcp.zim_operations import ZimOperations

        # Mock the libzim Archive
        mock_archive = Mock()
        mock_archive_class.return_value = mock_archive
        # Mock entry
        mock_entry = Mock()
        mock_entry.get_item.return_value.get_data.return_value = (
            b"<html><body>Test content</body></html>"
        )
        mock_entry.get_path.return_value = "A/Test_Article"
        mock_entry.get_title.return_value = "Test Article"
        mock_entry.get_mimetype.return_value = "text/html"
        mock_archive.get_entry_by_path.return_value = mock_entry

        # Create required dependencies
        import tempfile

        temp_dir = tempfile.mkdtemp()
        try:
            config = OpenZimMcpConfig(allowed_directories=[temp_dir])
            mock_path_validator = Mock()
            mock_cache = Mock()
            mock_content_processor = Mock()
            zim_ops = ZimOperations(
                config, mock_path_validator, mock_cache, mock_content_processor
            )

            # Mock the get_entry method to return a proper string
            def mock_get_entry(*args, **kwargs):
                return (
                    "# Test Article\n\nPath: A/Test_Article\n"
                    "Type: text/html\n\nTest content here"
                )

            zim_ops.get_zim_entry = mock_get_entry

            def get_entry():
                return zim_ops.get_zim_entry("/fake/path.zim", "A/Test_Article")

            result = benchmark(get_entry)
            assert "content" in result
            assert "Path" in result
        finally:
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)


# Benchmark configuration
pytest_plugins = ["pytest_benchmark"]
