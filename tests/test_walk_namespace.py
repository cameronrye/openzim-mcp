"""Tests for walk_namespace tool."""

import json
from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpValidationError
from openzim_mcp.server import OpenZimMcpServer


class TestWalkNamespace:
    """Test walk_namespace operation."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_walk_namespace_limit_validation_low(self, server: OpenZimMcpServer):
        """Test that limit < 1 raises OpenZimMcpValidationError."""
        with pytest.raises(
            OpenZimMcpValidationError, match="limit must be between 1 and 500"
        ):
            server.zim_operations.walk_namespace("/path/to/file.zim", "C", limit=0)

    def test_walk_namespace_limit_validation_high(self, server: OpenZimMcpServer):
        """Test that limit > 500 raises OpenZimMcpValidationError."""
        with pytest.raises(
            OpenZimMcpValidationError, match="limit must be between 1 and 500"
        ):
            server.zim_operations.walk_namespace("/path/to/file.zim", "C", limit=10000)

    def test_walk_namespace_raises_validation_error_for_bad_limit(
        self, server: OpenZimMcpServer
    ):
        """Mirror the explicit acceptance test from the fix plan (Task 6.4)."""
        with pytest.raises(OpenZimMcpValidationError):
            server.zim_operations.walk_namespace("/path/to/file.zim", "A", limit=10000)

    def test_walk_namespace_lowercase_namespace_normalized(
        self, server: OpenZimMcpServer, monkeypatch
    ):
        """Lowercase user input must be canonicalised before path-prefix matching.

        ``_extract_namespace_from_path`` always returns the canonical
        uppercase form (``c/foo`` -> ``"C"``). If the caller passes ``"c"``,
        the comparison would silently miss every entry. Ensure normalised
        input matches the same entries as the canonical form.
        """
        # Build a mock archive whose paths use uppercase ``C/...``
        # (the canonical form). With normalisation, lowercase ``"c"``
        # input must surface those entries.
        mock_archive = MagicMock()
        mock_archive.entry_count = 1
        mock_archive.has_new_namespace_scheme = True

        mock_entry = MagicMock()
        mock_entry.path = "C/Foo"
        mock_entry.title = "Foo"
        mock_archive._get_entry_by_id.return_value = mock_entry

        monkeypatch.setattr(
            "openzim_mcp.zim_operations.zim_archive",
            lambda *a, **kw: _ctx(mock_archive),
        )
        server.zim_operations.path_validator = MagicMock()
        server.zim_operations.path_validator.validate_path.return_value = (
            "/path/to/file.zim"
        )
        server.zim_operations.path_validator.validate_zim_file.return_value = (
            "/path/to/file.zim"
        )

        result_json = server.zim_operations.walk_namespace(
            "/path/to/file.zim", "c", limit=10
        )
        result = json.loads(result_json)
        # Without normalisation, results=[] silently. With normalisation,
        # the canonical "C" is matched and we surface the entry.
        assert len(result["results"]) == 1
        assert result["results"][0]["path"] == "C/Foo"

    def test_walk_namespace_first_page_no_cursor(
        self, server: OpenZimMcpServer, monkeypatch
    ):
        """First page with cursor=None walks from scan_at=0 and reports done."""
        # Build a minimal mock archive that the walk loop can iterate.
        mock_archive = MagicMock()
        mock_archive.entry_count = 0
        mock_archive.has_new_namespace_scheme = True

        monkeypatch.setattr(
            "openzim_mcp.zim_operations.zim_archive",
            lambda *a, **kw: _ctx(mock_archive),
        )
        # validate_path/validate_zim_file return the input as-is for the test
        server.zim_operations.path_validator = MagicMock()
        server.zim_operations.path_validator.validate_path.return_value = (
            "/path/to/file.zim"
        )
        server.zim_operations.path_validator.validate_zim_file.return_value = (
            "/path/to/file.zim"
        )

        result_json = server.zim_operations.walk_namespace(
            "/path/to/file.zim", "C", limit=10
        )
        result = json.loads(result_json)
        # New v2 contract: page_info.offset replaces top-level cursor (int).
        assert result["page_info"]["offset"] == 0
        assert result["done"] is True
        assert result["next_cursor"] is None
        assert result["total"] is None  # walk never knows per-namespace total


def _ctx(value):
    """Tiny context-manager wrapper for monkeypatching zim_archive."""

    class _C:
        def __enter__(self):
            return value

        def __exit__(self, *a):
            return False

    return _C()
