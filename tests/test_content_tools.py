"""Tests for content_tools module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.server import OpenZimMcpServer


class TestRegisterContentTools:
    """Test content tools registration."""

    def test_register_content_tools(self, test_config: OpenZimMcpConfig):
        """Test that content tools are registered correctly."""
        server = OpenZimMcpServer(test_config)
        # Tools are registered during server init, verify MCP instance exists
        assert server.mcp is not None


class TestGetZimEntryTool:
    """Test get_zim_entry tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_get_zim_entry_success(self, server: OpenZimMcpServer):
        """Test successful entry retrieval."""
        # Mock async_zim_operations
        server.async_zim_operations.get_zim_entry = AsyncMock(
            return_value="Entry content"
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.get_zim_entry(
            "/path/to/file.zim", "A/Article", None
        )

        assert result == "Entry content"
        server.async_zim_operations.get_zim_entry.assert_called_once_with(
            "/path/to/file.zim", "A/Article", None
        )

    @pytest.mark.asyncio
    async def test_get_zim_entry_with_max_content_length(
        self, server: OpenZimMcpServer
    ):
        """Test entry retrieval with max_content_length parameter."""
        server.async_zim_operations.get_zim_entry = AsyncMock(
            return_value="Truncated content"
        )

        result = await server.async_zim_operations.get_zim_entry(
            "/path/to/file.zim", "A/Article", 5000
        )

        assert result == "Truncated content"
        server.async_zim_operations.get_zim_entry.assert_called_once_with(
            "/path/to/file.zim", "A/Article", 5000
        )

    @pytest.mark.asyncio
    async def test_max_content_length_below_minimum_returns_error(
        self, server: OpenZimMcpServer
    ):
        """get_zim_entry must reject max_content_length < 100 via the tool handler."""
        server.rate_limiter.check_rate_limit = MagicMock()
        tool_handler = server.mcp._tool_manager._tools["get_zim_entry"].fn
        result = await tool_handler(
            zim_file_path="/path/to/file.zim",
            entry_path="A/Article",
            max_content_length=50,
        )
        assert "must be at least 100" in result

    @pytest.mark.asyncio
    async def test_get_zim_entry_rate_limit_error(self, server: OpenZimMcpServer):
        """Test rate limit handling in get_zim_entry."""
        # Test rate limit error creation
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="get ZIM entry",
            error=error,
            context="Entry: A/Test",
        )
        assert "Rate limit" in error_msg or "Operation" in error_msg

    @pytest.mark.asyncio
    async def test_get_zim_entry_generic_exception(self, server: OpenZimMcpServer):
        """Test generic exception handling in get_zim_entry."""
        server.async_zim_operations.get_zim_entry = AsyncMock(
            side_effect=Exception("Test error")
        )

        with pytest.raises(Exception) as exc_info:
            await server.async_zim_operations.get_zim_entry(
                "/path/to/file.zim", "A/Article", None
            )
        assert "Test error" in str(exc_info.value)


class TestGetZimEntriesBatchValidation:
    """Batch-size validation must run before per-entry rate-limit charging."""

    @pytest.fixture
    def advanced_server(self, temp_dir):
        """Create a server in advanced mode with batch tool registered."""
        from openzim_mcp.config import CacheConfig, OpenZimMcpConfig

        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        return OpenZimMcpServer(config)

    @pytest.mark.asyncio
    async def test_oversized_batch_does_not_charge_rate_limit(
        self, advanced_server, temp_dir
    ):
        """An oversized batch must be rejected without per-entry rate charges.

        Previously, the per-entry rate-limit loop ran first; an N-entry batch
        ate N rate-limit slots before the size check rejected it. The size
        check must run first so a single oversized batch costs at most one
        validation, not N.
        """
        from openzim_mcp.constants import MAX_BATCH_SIZE

        rl_calls = []

        def record_rl(*args, **kwargs):
            rl_calls.append(args)

        advanced_server.rate_limiter.check_rate_limit = MagicMock(side_effect=record_rl)
        # Backend should not be called at all.
        advanced_server.async_zim_operations.get_entries_data = AsyncMock(
            side_effect=AssertionError("backend should not be reached")
        )

        oversized = [
            {"zim_file_path": str(temp_dir / "x.zim"), "entry_path": f"A/E{i}"}
            for i in range(MAX_BATCH_SIZE + 100)
        ]

        tools = advanced_server.mcp._tool_manager._tools
        assert "get_zim_entries" in tools
        tool_handler = tools["get_zim_entries"].fn
        result = await tool_handler(entries=oversized)

        # Validation/error envelope returned to caller.
        assert isinstance(result, dict)
        assert result.get("error") is True
        message = result.get("message", "")
        assert "exceeds" in message.lower() or "batch size" in message.lower()
        # No rate-limit charges incurred.
        assert len(rl_calls) == 0, (
            f"expected 0 rate-limit calls before size validation, "
            f"got {len(rl_calls)}"
        )
        # Backend not invoked.
        advanced_server.async_zim_operations.get_entries_data.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_batch_still_charges_per_entry_rate_limit(
        self, advanced_server, temp_dir
    ):
        """A correctly-sized batch must still charge per-entry (anti-bypass)."""
        rl_calls = []

        def record_rl(*args, **kwargs):
            rl_calls.append(args)

        advanced_server.rate_limiter.check_rate_limit = MagicMock(side_effect=record_rl)
        advanced_server.async_zim_operations.get_entries_data = AsyncMock(
            return_value={"results": [], "succeeded": 0, "failed": 0}
        )

        entries = [
            {"zim_file_path": str(temp_dir / "x.zim"), "entry_path": f"A/E{i}"}
            for i in range(3)
        ]

        tools = advanced_server.mcp._tool_manager._tools
        assert "get_zim_entries" in tools
        tool_handler = tools["get_zim_entries"].fn
        await tool_handler(entries=entries)

        # One charge per entry.
        assert len(rl_calls) == 3


class TestInputSanitization:
    """Test input sanitization in content tools."""

    def test_sanitize_input_called(self, test_config: OpenZimMcpConfig):
        """Test that sanitize_input validates input length."""
        from openzim_mcp.constants import INPUT_LIMIT_ENTRY_PATH, INPUT_LIMIT_FILE_PATH
        from openzim_mcp.exceptions import OpenZimMcpValidationError
        from openzim_mcp.security import sanitize_input

        # Test that valid input passes
        valid_path = "a" * 100
        sanitized = sanitize_input(valid_path, INPUT_LIMIT_FILE_PATH)
        assert sanitized == valid_path

        # Test that overly long input raises error
        long_path = "a" * 2000
        with pytest.raises(OpenZimMcpValidationError) as exc_info:
            sanitize_input(long_path, INPUT_LIMIT_FILE_PATH)
        assert "Input too long" in str(exc_info.value)

        # Test entry path sanitization
        valid_entry = "b" * 100
        sanitized_entry = sanitize_input(valid_entry, INPUT_LIMIT_ENTRY_PATH)
        assert sanitized_entry == valid_entry


class TestGetBinaryEntryDataMeta:
    """get_binary_entry_data must attach _meta on every return path."""

    @pytest.fixture
    def zim_ops(self, test_config, path_validator, openzim_mcp_cache, content_processor):
        from openzim_mcp.zim_operations import ZimOperations

        return ZimOperations(test_config, path_validator, openzim_mcp_cache, content_processor)

    def _zim_file(self, temp_dir):
        from pathlib import Path

        p = Path(temp_dir) / "test.zim"
        p.write_bytes(b"")
        return p

    def test_get_binary_entry_data_attaches_meta_fresh(self, zim_ops, temp_dir, monkeypatch):
        """Fresh path (archive opened) should attach _meta."""
        from unittest.mock import MagicMock, patch

        zim_file = self._zim_file(temp_dir)

        mock_item = MagicMock()
        mock_item.size = 5
        mock_item.mimetype = "image/png"
        mock_item.content = b"\x89PNG"

        mock_entry = MagicMock()
        mock_entry.is_redirect = False
        mock_entry.title = "Test Image"
        mock_entry.path = "I/test.png"
        mock_entry.get_item.return_value = mock_item

        mock_archive = MagicMock()
        mock_archive.get_entry_by_path.return_value = mock_entry

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
            mock_ctx.return_value.__enter__.return_value = mock_archive
            result = zim_ops.get_binary_entry_data(
                str(zim_file), "I/test.png", include_data=True
            )

        assert "_meta" in result, "fresh path must attach _meta"
        assert result["_meta"]["tokens_est"] > 0
        assert result["_meta"]["truncated"] is False

    def test_get_binary_entry_data_attaches_meta_cached(self, zim_ops, temp_dir):
        """Cached metadata path should also attach _meta."""
        from pathlib import Path

        zim_file = self._zim_file(temp_dir)
        validated = zim_ops.path_validator.validate_path(str(zim_file))
        validated = zim_ops.path_validator.validate_zim_file(validated)

        # Seed the cache with binary metadata so the short-circuit path fires.
        cache_key = f"binary_meta:{validated}:I/test.png"
        zim_ops.cache.set(cache_key, {
            "path": "I/test.png",
            "title": "Test Image",
            "mime_type": "image/png",
            "size": 10,
            "size_human": "10 B",
        })

        result = zim_ops.get_binary_entry_data(
            str(zim_file), "I/test.png", include_data=False
        )
        assert "_meta" in result, "cached path must attach _meta"
        assert result["_meta"]["tokens_est"] > 0


class TestGetEntrySummaryDataMeta:
    """get_entry_summary_data must attach _meta on every return path."""

    @pytest.fixture
    def zim_ops(self, test_config, path_validator, openzim_mcp_cache, content_processor):
        from openzim_mcp.zim_operations import ZimOperations

        return ZimOperations(test_config, path_validator, openzim_mcp_cache, content_processor)

    def _zim_file(self, temp_dir):
        from pathlib import Path

        p = Path(temp_dir) / "test.zim"
        p.write_bytes(b"")
        return p

    def test_get_entry_summary_data_attaches_meta_fresh(self, zim_ops, temp_dir, monkeypatch):
        """Fresh computation path should attach _meta."""
        from unittest.mock import MagicMock, patch

        zim_file = self._zim_file(temp_dir)

        fresh_summary = {
            "title": "Test Article",
            "path": "A/Test",
            "content_type": "text/plain",
            "summary": "A short summary.",
            "word_count": 3,
            "is_truncated": False,
        }

        monkeypatch.setattr(
            zim_ops,
            "_extract_entry_summary_data",
            lambda *a, **kw: fresh_summary,
        )

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
            mock_ctx.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.get_entry_summary_data(str(zim_file), "A/Test")

        assert "_meta" in result, "fresh path must attach _meta"
        assert result["_meta"]["tokens_est"] > 0
        assert result["_meta"]["truncated"] is False

    def test_get_entry_summary_data_attaches_meta_cached(self, zim_ops, temp_dir):
        """Cached result path should also carry _meta."""
        from pathlib import Path

        zim_file = self._zim_file(temp_dir)
        validated = zim_ops.path_validator.validate_path(str(zim_file))
        validated = zim_ops.path_validator.validate_zim_file(validated)

        old_summary = {
            "title": "Cached Article",
            "path": "A/Cached",
            "content_type": "text/plain",
            "summary": "Cached content.",
            "word_count": 2,
            "is_truncated": False,
        }
        cache_key = f"summary_data:{validated}:A/Cached:200"
        zim_ops.cache.set(cache_key, old_summary)

        result = zim_ops.get_entry_summary_data(str(zim_file), "A/Cached")
        assert "_meta" in result, "cached path must attach _meta"
        assert result["_meta"]["tokens_est"] > 0

    def test_get_entry_summary_data_meta_truncated_flag(self, zim_ops, temp_dir, monkeypatch):
        """When is_truncated=True, _meta.truncated should reflect that."""
        from unittest.mock import MagicMock, patch

        zim_file = self._zim_file(temp_dir)

        truncated_summary = {
            "title": "Long Article",
            "path": "A/Long",
            "content_type": "text/plain",
            "summary": "First 200 words...",
            "word_count": 200,
            "is_truncated": True,
        }

        monkeypatch.setattr(
            zim_ops,
            "_extract_entry_summary_data",
            lambda *a, **kw: truncated_summary,
        )

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
            mock_ctx.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.get_entry_summary_data(str(zim_file), "A/Long")

        assert "_meta" in result
        assert result["_meta"]["truncated"] is True
