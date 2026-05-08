"""Tests for metadata_tools module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.server import OpenZimMcpServer


class TestRegisterMetadataTools:
    """Test metadata tools registration."""

    def test_register_metadata_tools(self, test_config: OpenZimMcpConfig):
        """Test that metadata tools are registered correctly."""
        server = OpenZimMcpServer(test_config)
        assert server.mcp is not None


class TestGetZimMetadataTool:
    """Test get_zim_metadata tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_get_zim_metadata_success(self, server: OpenZimMcpServer):
        """Test successful metadata retrieval."""
        server.async_zim_operations.get_zim_metadata = AsyncMock(
            return_value='{"title": "Test", "language": "en"}'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.get_zim_metadata("/path/to/file.zim")

        assert "title" in result
        server.async_zim_operations.get_zim_metadata.assert_called_once_with(
            "/path/to/file.zim"
        )

    @pytest.mark.asyncio
    async def test_get_zim_metadata_rate_limit_error(self, server: OpenZimMcpServer):
        """Test rate limit handling in get_zim_metadata."""
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="get ZIM metadata",
            error=error,
            context="File: /test/file.zim",
        )
        assert "get ZIM metadata" in error_msg or "Operation" in error_msg

    @pytest.mark.asyncio
    async def test_get_zim_metadata_generic_exception(self, server: OpenZimMcpServer):
        """Test generic exception handling in get_zim_metadata."""
        server.async_zim_operations.get_zim_metadata = AsyncMock(
            side_effect=Exception("Test error")
        )

        with pytest.raises(Exception) as exc_info:
            await server.async_zim_operations.get_zim_metadata("/path/to/file.zim")
        assert "Test error" in str(exc_info.value)


class TestGetMainPageTool:
    """Test get_main_page tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_get_main_page_success(self, server: OpenZimMcpServer):
        """Test successful main page retrieval."""
        server.async_zim_operations.get_main_page = AsyncMock(
            return_value="Main page content"
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.get_main_page("/path/to/file.zim")

        assert result == "Main page content"
        server.async_zim_operations.get_main_page.assert_called_once_with(
            "/path/to/file.zim"
        )

    @pytest.mark.asyncio
    async def test_get_main_page_rate_limit_error(self, server: OpenZimMcpServer):
        """Test rate limit handling in get_main_page."""
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="get main page",
            error=error,
            context="File: /test/file.zim",
        )
        assert "get main page" in error_msg or "Operation" in error_msg


class TestListNamespacesTool:
    """Test list_namespaces tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_list_namespaces_success(self, server: OpenZimMcpServer):
        """Test successful namespace listing."""
        server.async_zim_operations.list_namespaces = AsyncMock(
            return_value='{"namespaces": ["A", "C", "M"]}'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.list_namespaces("/path/to/file.zim")

        assert "namespaces" in result
        server.async_zim_operations.list_namespaces.assert_called_once_with(
            "/path/to/file.zim"
        )

    @pytest.mark.asyncio
    async def test_list_namespaces_rate_limit_error(self, server: OpenZimMcpServer):
        """Test rate limit handling in list_namespaces."""
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="list namespaces",
            error=error,
            context="File: /test/file.zim",
        )
        assert "list namespaces" in error_msg or "Operation" in error_msg

    @pytest.mark.asyncio
    async def test_list_namespaces_generic_exception(self, server: OpenZimMcpServer):
        """Test generic exception handling in list_namespaces."""
        server.async_zim_operations.list_namespaces = AsyncMock(
            side_effect=Exception("Test error")
        )

        with pytest.raises(Exception) as exc_info:
            await server.async_zim_operations.list_namespaces("/path/to/file.zim")
        assert "Test error" in str(exc_info.value)


class TestInputSanitizationMetadata:
    """Test input sanitization in metadata tools."""

    def test_sanitize_file_path(self, test_config: OpenZimMcpConfig):
        """Test that file paths are validated correctly."""
        from openzim_mcp.constants import INPUT_LIMIT_FILE_PATH
        from openzim_mcp.exceptions import OpenZimMcpValidationError
        from openzim_mcp.security import sanitize_input

        # Valid path should pass
        valid_path = "x" * 100
        sanitized = sanitize_input(valid_path, INPUT_LIMIT_FILE_PATH)
        assert sanitized == valid_path

        # Long path should raise error
        long_path = "x" * 2000
        with pytest.raises(OpenZimMcpValidationError):
            sanitize_input(long_path, INPUT_LIMIT_FILE_PATH)


# ---------------------------------------------------------------------------
# Phase-A _meta envelope smoke tests — archive.py get_zim_metadata_data
# ---------------------------------------------------------------------------


class TestGetZimMetadataDataMeta:
    """get_zim_metadata_data must attach a _meta envelope on every return path."""

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

    def test_get_zim_metadata_data_fresh_attaches_meta(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """Fresh path attaches _meta envelope."""
        zim_file = self._zim_file(temp_dir)
        fake_meta = {"title": "Test", "language": "eng", "description": "A test ZIM"}
        monkeypatch.setattr(
            zim_ops, "_extract_zim_metadata", lambda *a, **kw: fake_meta
        )
        from unittest.mock import MagicMock, patch

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.get_zim_metadata_data(str(zim_file))

        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1

    def test_get_zim_metadata_data_cached_backfills_meta(self, zim_ops, temp_dir):
        """Cached entry without _meta is backfilled on read."""
        zim_file = self._zim_file(temp_dir)
        validated = zim_ops.path_validator.validate_path(str(zim_file))
        validated = zim_ops.path_validator.validate_zim_file(validated)
        cache_key = f"metadata_data:{validated}"
        old = {"title": "Test", "language": "eng"}
        zim_ops.cache.set(cache_key, old)

        result = zim_ops.get_zim_metadata_data(str(zim_file))
        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1
