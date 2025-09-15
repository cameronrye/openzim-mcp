"""
Integration tests for OpenZIM MCP server.
"""

from pathlib import Path

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


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
        with pytest.raises(Exception):  # Should raise security or validation error
            server.zim_operations.search_zim_file("/invalid/path.zim", "test")

    def test_get_zim_entry_invalid_path(self, server: OpenZimMcpServer):
        """Test getting entry with invalid ZIM file path."""
        with pytest.raises(Exception):  # Should raise security or validation error
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
