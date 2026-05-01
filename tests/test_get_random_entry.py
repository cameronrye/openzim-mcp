"""Tests for get_random_entry tool."""

import json
from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


class TestGetRandomEntry:
    """Test get_random_entry operation."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_random_entry_in_namespace(self, server: OpenZimMcpServer, monkeypatch):
        """First random pick lands in the requested namespace and returns."""
        mock_archive = MagicMock()
        mock_archive.has_new_namespace_scheme = True
        mock_entry = MagicMock()
        mock_entry.path = "C/Some_Article"
        mock_entry.title = "Some Article"
        mock_item = MagicMock()
        mock_item.content = b"<p>Article content</p>"
        mock_item.mimetype = "text/html"
        mock_entry.get_item.return_value = mock_item
        mock_archive.get_random_entry.return_value = mock_entry

        monkeypatch.setattr(
            "openzim_mcp.zim_operations.zim_archive",
            lambda *a, **kw: _ctx(mock_archive),
        )
        server.zim_operations.path_validator = MagicMock()
        server.zim_operations.path_validator.validate_path.return_value = (
            "/zim/test.zim"
        )
        server.zim_operations.path_validator.validate_zim_file.return_value = (
            "/zim/test.zim"
        )

        result_json = server.zim_operations.get_random_entry("/zim/test.zim", "C")
        result = json.loads(result_json)
        assert result["path"] == "C/Some_Article"
        assert result["namespace"] == "C"

    def test_random_entry_default_namespace_auto_relaxes_on_new_scheme(
        self, server: OpenZimMcpServer, monkeypatch
    ):
        """Default 'C' on a new-scheme archive auto-relaxes to "any namespace".

        Pre-v1.0 a default-namespace call against a domain-scheme archive
        (e.g. medlineplus.gov) burned all retries and returned an error,
        because the legacy 'C' namespace simply doesn't exist there. v1.0
        treats the legacy default as a soft constraint and falls through
        to "any namespace" so default callers get useful results without
        needing to know the archive's namespace conventions.
        """
        mock_archive = MagicMock()
        mock_archive.has_new_namespace_scheme = True
        mock_other = MagicMock()
        mock_other.path = "M/Title"
        mock_other.title = "Title"
        mock_item = MagicMock()
        mock_item.content = b"some text"
        mock_item.mimetype = "text/plain"
        mock_other.get_item.return_value = mock_item
        mock_archive.get_random_entry.return_value = mock_other

        monkeypatch.setattr(
            "openzim_mcp.zim_operations.zim_archive",
            lambda *a, **kw: _ctx(mock_archive),
        )
        server.zim_operations.path_validator = MagicMock()
        server.zim_operations.path_validator.validate_path.return_value = (
            "/zim/test.zim"
        )
        server.zim_operations.path_validator.validate_zim_file.return_value = (
            "/zim/test.zim"
        )

        result_json = server.zim_operations.get_random_entry("/zim/test.zim", "C")
        result = json.loads(result_json)
        assert result["path"] == "M/Title"
        assert "error" not in result

    def test_random_entry_explicit_namespace_not_found(
        self, server: OpenZimMcpServer, monkeypatch
    ):
        """Explicit non-default namespace mismatch still returns an error."""
        mock_archive = MagicMock()
        mock_archive.has_new_namespace_scheme = False
        mock_other = MagicMock()
        mock_other.path = "M/Title"  # Never lands in 'A'.
        mock_other.title = "Title"
        mock_archive.get_random_entry.return_value = mock_other

        monkeypatch.setattr(
            "openzim_mcp.zim_operations.zim_archive",
            lambda *a, **kw: _ctx(mock_archive),
        )
        server.zim_operations.path_validator = MagicMock()
        server.zim_operations.path_validator.validate_path.return_value = (
            "/zim/test.zim"
        )
        server.zim_operations.path_validator.validate_zim_file.return_value = (
            "/zim/test.zim"
        )

        result_json = server.zim_operations.get_random_entry("/zim/test.zim", "A")
        result = json.loads(result_json)
        assert "error" in result
        assert "A" in result["error"]

    def test_random_entry_namespace_any(self, server: OpenZimMcpServer, monkeypatch):
        """Test that namespace='' accepts any namespace on the first random pick."""
        mock_archive = MagicMock()
        mock_archive.has_new_namespace_scheme = True
        mock_entry = MagicMock()
        mock_entry.path = "M/Title"
        mock_entry.title = "Title"
        mock_item = MagicMock()
        mock_item.content = b"Some metadata"
        mock_item.mimetype = "text/plain"
        mock_entry.get_item.return_value = mock_item
        mock_archive.get_random_entry.return_value = mock_entry

        monkeypatch.setattr(
            "openzim_mcp.zim_operations.zim_archive",
            lambda *a, **kw: _ctx(mock_archive),
        )
        server.zim_operations.path_validator = MagicMock()
        server.zim_operations.path_validator.validate_path.return_value = (
            "/zim/test.zim"
        )
        server.zim_operations.path_validator.validate_zim_file.return_value = (
            "/zim/test.zim"
        )

        result_json = server.zim_operations.get_random_entry("/zim/test.zim", "")
        result = json.loads(result_json)
        assert result["namespace"] == "M"
        assert result["path"] == "M/Title"


def _ctx(value):
    """Build a context manager that yields the given value."""

    class _C:
        def __enter__(self):
            return value

        def __exit__(self, *a):
            return False

    return _C()
