"""Integration tests for OpenZIM MCP server."""

from pathlib import Path

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.zim_operations import ZimOperations


class TestListZimFilesNameFilter:
    """name_filter narrows the listing without depending on the MCP server."""

    @pytest.fixture
    def zim_ops(
        self,
        test_config: OpenZimMcpConfig,
        path_validator: PathValidator,
        openzim_mcp_cache: OpenZimMcpCache,
        content_processor: ContentProcessor,
    ) -> ZimOperations:
        """Build a ZimOperations bound to the test config + cache."""
        return ZimOperations(
            test_config, path_validator, openzim_mcp_cache, content_processor
        )

    def test_filter_is_case_insensitive_substring(
        self, zim_ops: ZimOperations, temp_dir: Path
    ):
        """name_filter matches as a case-insensitive substring of the filename."""
        (temp_dir / "wikipedia_en.zim").write_text("a")
        (temp_dir / "nginx_docs.zim").write_text("b")
        (temp_dir / "Nginx_Tutorial.zim").write_text("c")

        result = zim_ops.list_zim_files(name_filter="NGINX")

        assert "Found 2 ZIM files" in result
        assert "nginx_docs.zim" in result
        assert "Nginx_Tutorial.zim" in result
        assert "wikipedia_en.zim" not in result

    def test_filter_with_no_matches(self, zim_ops: ZimOperations, temp_dir: Path):
        """A filter with no hits returns the empty-listing message."""
        (temp_dir / "wikipedia_en.zim").write_text("a")

        result = zim_ops.list_zim_files(name_filter="nginx")

        assert "No ZIM files" in result

    def test_empty_filter_behaves_like_no_filter(
        self, zim_ops: ZimOperations, temp_dir: Path
    ):
        """Empty string is documented as 'no filter' and must match the default."""
        (temp_dir / "a.zim").write_text("a")
        (temp_dir / "b.zim").write_text("b")

        assert zim_ops.list_zim_files() == zim_ops.list_zim_files(name_filter="")

    def test_filter_matches_filename_not_directory(
        self, zim_ops: ZimOperations, temp_dir: Path
    ):
        """The filter is applied to the file's own name, not its parent directory."""
        nginx_dir = temp_dir / "nginx_archive"
        nginx_dir.mkdir()
        (nginx_dir / "wikipedia.zim").write_text("a")

        result = zim_ops.list_zim_files(name_filter="nginx")

        assert "No ZIM files" in result

    def test_filter_strips_surrounding_whitespace(
        self, zim_ops: ZimOperations, temp_dir: Path
    ):
        """Padding whitespace is trimmed before matching."""
        (temp_dir / "nginx.zim").write_text("a")

        result = zim_ops.list_zim_files(name_filter="  nginx  ")

        assert "Found 1 ZIM files" in result
        assert "nginx.zim" in result

    def test_repeated_filtered_calls_share_one_cache_entry(
        self,
        zim_ops: ZimOperations,
        temp_dir: Path,
        openzim_mcp_cache: OpenZimMcpCache,
    ):
        """Filtered queries reuse one cached scan instead of one entry per filter."""
        (temp_dir / "wikipedia_en.zim").write_text("a")
        (temp_dir / "nginx.zim").write_text("b")
        (temp_dir / "kiwix.zim").write_text("c")

        zim_ops.list_zim_files_data(name_filter="nginx")
        zim_ops.list_zim_files_data(name_filter="kiwix")
        zim_ops.list_zim_files_data(name_filter="wikipedia")
        zim_ops.list_zim_files_data()

        assert openzim_mcp_cache.stats()["size"] == 1


class TestOpenZimMcpServerIntegration:
    """Integration tests for OpenZimMcpServer."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_server_initialization(self, server: OpenZimMcpServer):
        """Test server initializes correctly."""
        assert server.config is not None
        assert server.path_validator is not None
        assert server.cache is not None
        assert server.content_processor is not None
        assert server.zim_operations is not None
        assert server.mcp is not None

    def test_list_zim_files_empty_directory(self, server: OpenZimMcpServer):
        """Test listing ZIM files in empty directory."""
        result = server.zim_operations.list_zim_files()
        assert "No ZIM files found" in result

    def test_list_zim_files_with_files(self, server: OpenZimMcpServer, temp_dir: Path):
        """Test listing ZIM files with actual files."""
        # Create test ZIM files
        zim_file1 = temp_dir / "test1.zim"
        zim_file2 = temp_dir / "test2.zim"
        zim_file1.write_text("test content 1")
        zim_file2.write_text("test content 2")

        result = server.zim_operations.list_zim_files()
        assert "Found 2 ZIM files" in result
        assert "test1.zim" in result
        assert "test2.zim" in result

    def test_search_zim_file_invalid_path(self, server: OpenZimMcpServer):
        """Test searching with invalid ZIM file path."""
        with pytest.raises(Exception, match="Access denied|does not exist"):
            server.zim_operations.search_zim_file("/invalid/path.zim", "test")

    def test_get_zim_entry_invalid_path(self, server: OpenZimMcpServer):
        """Test getting entry with invalid ZIM file path."""
        with pytest.raises(Exception, match="Access denied|does not exist"):
            server.zim_operations.get_zim_entry("/invalid/path.zim", "A/Test")

    def test_server_health_check(self, server: OpenZimMcpServer):
        """Test server health check functionality."""
        # Access the health check tool through the server's tools
        # This would require accessing the registered MCP tools
        # For now, test the cache stats directly
        stats = server.cache.stats()
        assert "enabled" in stats
        assert "size" in stats
        assert "max_size" in stats
        assert "ttl_seconds" in stats

    def test_cache_integration(self, server: OpenZimMcpServer, temp_dir: Path):
        """Test cache integration with ZIM operations."""
        # Create a test ZIM file
        zim_file = temp_dir / "test.zim"
        zim_file.write_text("test content")

        # First call should populate cache
        result1 = server.zim_operations.list_zim_files()

        # Second call should use cache
        result2 = server.zim_operations.list_zim_files()

        # Results should be identical
        assert result1 == result2

        # Cache should have entries
        stats = server.cache.stats()
        assert stats["size"] > 0
