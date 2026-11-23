"""Tests for metadata_tools module."""

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


class TestRegisterMetadataTools:
    """Test metadata tools registration."""

    def test_register_metadata_tools(self, test_config: OpenZimMcpConfig):
        """Test that metadata tools are registered correctly."""
        server = OpenZimMcpServer(test_config)
        assert server.mcp is not None


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

    def test_get_zim_metadata_data_cached_payload_returned_verbatim(
        self, zim_ops, temp_dir
    ):
        """Cache stores the post-attach payload. A cache hit returns it
        verbatim — _meta is NOT recomputed on every read (Phase B #12
        fix; non-determinism between cold/warm was eliminated).
        """
        zim_file = self._zim_file(temp_dir)
        validated = zim_ops.path_validator.validate_path(str(zim_file))
        validated = zim_ops.path_validator.validate_zim_file(validated)
        # Key bumped to v2c when the metadata shape gained identity/index/
        # counter fields (see get_zim_metadata_data); the stat token makes an
        # in-place archive replacement a cache miss (archive_stat_token).
        from openzim_mcp.bundle import archive_stat_token

        cache_key = f"metadata_data:v2c:{validated}:{archive_stat_token(validated)}"
        seeded = {
            "title": "Test",
            "language": "eng",
            "_meta": {"tokens_est": 17, "chars": 32, "truncated": False},
        }
        zim_ops.cache.set(cache_key, seeded)

        result = zim_ops.get_zim_metadata_data(str(zim_file))
        assert result is seeded
        assert result["_meta"]["tokens_est"] == 17
