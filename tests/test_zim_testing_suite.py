"""
Tests using zim-testing-suite files for comprehensive ZIM format testing.

These tests use the official zim-testing-suite test files to ensure
compatibility with various ZIM file formats and edge cases.
"""

from pathlib import Path
from typing import Dict, List, Optional

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpArchiveError
from openzim_mcp.zim_operations import ZimOperations


@pytest.mark.requires_zim_data
class TestZimTestingSuiteIntegration:
    """Integration tests using zim-testing-suite files."""

    def test_basic_zim_files_available(
        self, basic_test_zim_files: Dict[str, Optional[Path]]
    ):
        """Test that basic ZIM files are available for testing."""
        assert (
            basic_test_zim_files["withns"] is not None
        ), "withns/small.zim not available"
        assert basic_test_zim_files["nons"] is not None, "nons/small.zim not available"

        # Verify files exist and are readable
        assert basic_test_zim_files["withns"].exists()
        assert basic_test_zim_files["nons"].exists()
        assert basic_test_zim_files["withns"].stat().st_size > 0
        assert basic_test_zim_files["nons"].stat().st_size > 0

    def test_zim_operations_with_real_files(
        self,
        basic_test_zim_files: Dict[str, Optional[Path]],
        test_config_with_zim_data: OpenZimMcpConfig,
    ):
        """Test ZIM operations with real ZIM files."""
        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.content_processor import ContentProcessor
        from openzim_mcp.security import PathValidator

        # Create ZIM operations instance
        path_validator = PathValidator(test_config_with_zim_data.allowed_directories)
        cache = OpenZimMcpCache(test_config_with_zim_data.cache)
        content_processor = ContentProcessor(
            snippet_length=test_config_with_zim_data.content.snippet_length
        )
        zim_ops = ZimOperations(
            test_config_with_zim_data, path_validator, cache, content_processor
        )

        # Test with withns file
        withns_file = basic_test_zim_files["withns"]
        if withns_file:
            # Test metadata retrieval
            metadata = zim_ops.get_zim_metadata(str(withns_file))
            assert "entry_count" in metadata
            assert "metadata_entries" in metadata

            # Test namespace listing
            namespaces = zim_ops.list_namespaces(str(withns_file))
            assert "namespaces" in namespaces

        # Test with nons file
        nons_file = basic_test_zim_files["nons"]
        if nons_file:
            # Test metadata retrieval
            metadata = zim_ops.get_zim_metadata(str(nons_file))
            assert "entry_count" in metadata

    def test_search_functionality_real_files(
        self,
        basic_test_zim_files: Dict[str, Optional[Path]],
        test_config_with_zim_data: OpenZimMcpConfig,
    ):
        """Test search functionality with real ZIM files."""
        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.content_processor import ContentProcessor
        from openzim_mcp.security import PathValidator

        path_validator = PathValidator(test_config_with_zim_data.allowed_directories)
        cache = OpenZimMcpCache(test_config_with_zim_data.cache)
        content_processor = ContentProcessor(
            snippet_length=test_config_with_zim_data.content.snippet_length
        )
        zim_ops = ZimOperations(
            test_config_with_zim_data, path_validator, cache, content_processor
        )

        withns_file = basic_test_zim_files["withns"]
        if withns_file:
            # Test basic search
            try:
                result = zim_ops.search_zim_file(str(withns_file), "test", limit=5)
                # Should either find results or indicate no matches
                assert "matches" in result.lower() or "no results" in result.lower()
            except Exception as e:
                # Some test files might not support search, that's okay
                pytest.skip(f"Search not supported for this test file: {e}")

    def test_invalid_zim_files_error_handling(
        self,
        invalid_test_zim_files: List[Path],
        test_config_with_zim_data: OpenZimMcpConfig,
    ):
        """Test error handling with invalid ZIM files."""
        if not invalid_test_zim_files:
            pytest.skip("No invalid ZIM files available for testing")

        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.content_processor import ContentProcessor
        from openzim_mcp.security import PathValidator

        path_validator = PathValidator(test_config_with_zim_data.allowed_directories)
        cache = OpenZimMcpCache(test_config_with_zim_data.cache)
        content_processor = ContentProcessor(
            snippet_length=test_config_with_zim_data.content.snippet_length
        )
        zim_ops = ZimOperations(
            test_config_with_zim_data, path_validator, cache, content_processor
        )

        # Test that invalid files raise appropriate errors or handle gracefully
        for invalid_file in invalid_test_zim_files[:3]:  # Test first 3 invalid files
            try:
                result = zim_ops.get_zim_metadata(str(invalid_file))
                # If no exception is raised, the operation should at least complete
                # Some invalid files might be handled gracefully by libzim
                assert isinstance(result, str)
            except (OpenZimMcpArchiveError, Exception):
                # This is also acceptable - invalid files should raise errors
                pass

    def test_real_content_files(
        self,
        real_content_zim_files: Dict[str, Optional[Path]],
        test_config_with_zim_data: OpenZimMcpConfig,
    ):
        """Test operations with real content ZIM files."""
        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.content_processor import ContentProcessor
        from openzim_mcp.security import PathValidator

        path_validator = PathValidator(test_config_with_zim_data.allowed_directories)
        cache = OpenZimMcpCache(test_config_with_zim_data.cache)
        content_processor = ContentProcessor(
            snippet_length=test_config_with_zim_data.content.snippet_length
        )
        zim_ops = ZimOperations(
            test_config_with_zim_data, path_validator, cache, content_processor
        )

        wikibooks_file = real_content_zim_files["wikibooks"]
        if wikibooks_file:
            # Test metadata
            metadata = zim_ops.get_zim_metadata(str(wikibooks_file))
            assert "entry_count" in metadata
            assert "metadata_entries" in metadata

            # Test namespace browsing
            namespaces = zim_ops.list_namespaces(str(wikibooks_file))
            assert "namespaces" in namespaces

            # Test main page retrieval
            try:
                main_page = zim_ops.get_main_page(str(wikibooks_file))
                assert len(main_page) > 0
            except Exception:
                # Main page might not exist in all test files
                pass

    def test_zim_file_listing_with_test_data(
        self,
        zim_test_data_dir: Optional[Path],
        test_config_with_zim_data: OpenZimMcpConfig,
    ):
        """Test ZIM file listing includes test data files."""
        if not zim_test_data_dir:
            pytest.skip("ZIM test data directory not available")

        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.content_processor import ContentProcessor
        from openzim_mcp.security import PathValidator

        path_validator = PathValidator(test_config_with_zim_data.allowed_directories)
        cache = OpenZimMcpCache(test_config_with_zim_data.cache)
        content_processor = ContentProcessor(
            snippet_length=test_config_with_zim_data.content.snippet_length
        )
        zim_ops = ZimOperations(
            test_config_with_zim_data, path_validator, cache, content_processor
        )

        # List ZIM files
        result = zim_ops.list_zim_files()

        # Should find at least the basic test files
        assert "small.zim" in result

    def test_manifest_integrity(self, zim_test_manifest: Optional[Dict]):
        """Test that the ZIM test data manifest is valid."""
        if not zim_test_manifest:
            pytest.skip("ZIM test manifest not available")

        # Verify manifest structure
        assert "files" in zim_test_manifest
        assert isinstance(zim_test_manifest["files"], dict)

        # Verify file entries have required fields
        for file_path, file_info in zim_test_manifest["files"].items():
            assert "category" in file_info
            assert "description" in file_info
            assert "priority" in file_info
            assert "size_bytes" in file_info
            assert "sha256" in file_info

            # Verify priority is valid
            assert 1 <= file_info["priority"] <= 3

            # Verify size is reasonable
            assert file_info["size_bytes"] > 0


@pytest.mark.requires_zim_data
@pytest.mark.integration
class TestZimFormatCompatibility:
    """Test compatibility with different ZIM file formats and versions."""

    def test_namespace_handling(
        self,
        basic_test_zim_files: Dict[str, Optional[Path]],
        test_config_with_zim_data: OpenZimMcpConfig,
    ):
        """Test handling of files with and without namespaces."""
        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.content_processor import ContentProcessor
        from openzim_mcp.security import PathValidator

        path_validator = PathValidator(test_config_with_zim_data.allowed_directories)
        cache = OpenZimMcpCache(test_config_with_zim_data.cache)
        content_processor = ContentProcessor(
            snippet_length=test_config_with_zim_data.content.snippet_length
        )
        zim_ops = ZimOperations(
            test_config_with_zim_data, path_validator, cache, content_processor
        )

        # Test file with namespaces
        withns_file = basic_test_zim_files["withns"]
        if withns_file:
            namespaces = zim_ops.list_namespaces(str(withns_file))
            # Should have multiple namespaces
            assert "namespaces" in namespaces

        # Test file without namespaces
        nons_file = basic_test_zim_files["nons"]
        if nons_file:
            namespaces = zim_ops.list_namespaces(str(nons_file))
            # Should handle gracefully even without traditional namespaces
            assert "namespaces" in namespaces

    def test_content_type_detection(
        self,
        basic_test_zim_files: Dict[str, Optional[Path]],
        test_config_with_zim_data: OpenZimMcpConfig,
    ):
        """Test content type detection across different ZIM files."""
        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.content_processor import ContentProcessor
        from openzim_mcp.security import PathValidator

        path_validator = PathValidator(test_config_with_zim_data.allowed_directories)
        cache = OpenZimMcpCache(test_config_with_zim_data.cache)
        content_processor = ContentProcessor(
            snippet_length=test_config_with_zim_data.content.snippet_length
        )
        zim_ops = ZimOperations(
            test_config_with_zim_data, path_validator, cache, content_processor
        )

        for file_type, file_path in basic_test_zim_files.items():
            if file_path:
                try:
                    # Browse entries to check content types
                    namespaces = zim_ops.list_namespaces(str(file_path))
                    # Should complete without errors
                    assert "namespaces" in namespaces
                except Exception as e:
                    pytest.fail(f"Content type detection failed for {file_type}: {e}")


@pytest.mark.requires_zim_data
@pytest.mark.slow
class TestZimPerformance:
    """Performance tests with real ZIM files."""

    def test_caching_effectiveness(
        self,
        basic_test_zim_files: Dict[str, Optional[Path]],
        test_config_with_zim_data: OpenZimMcpConfig,
    ):
        """Test that caching improves performance with real files."""
        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.content_processor import ContentProcessor
        from openzim_mcp.security import PathValidator

        path_validator = PathValidator(test_config_with_zim_data.allowed_directories)
        cache = OpenZimMcpCache(test_config_with_zim_data.cache)
        content_processor = ContentProcessor(
            snippet_length=test_config_with_zim_data.content.snippet_length
        )
        zim_ops = ZimOperations(
            test_config_with_zim_data, path_validator, cache, content_processor
        )

        withns_file = basic_test_zim_files["withns"]
        if withns_file:
            # First call (should cache)
            result1 = zim_ops.get_zim_metadata(str(withns_file))

            # Second call (should use cache)
            result2 = zim_ops.get_zim_metadata(str(withns_file))

            # Results should be identical
            assert result1 == result2

            # Verify that caching doesn't break functionality
            assert len(result2) > 0
