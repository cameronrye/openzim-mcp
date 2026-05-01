"""Tests for warm_cache tool."""

import json
from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


class TestWarmCache:
    """Test warm_cache operation."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_warm_cache_happy_path(self, server: OpenZimMcpServer):
        """Test that all 4 lookups succeed and are recorded."""
        server.zim_operations.path_validator = MagicMock()
        server.zim_operations.path_validator.validate_path.return_value = (
            "/zim/test.zim"
        )
        server.zim_operations.path_validator.validate_zim_file.return_value = (
            "/zim/test.zim"
        )
        server.zim_operations.list_zim_files = MagicMock(return_value="[]")
        server.zim_operations.get_zim_metadata = MagicMock(return_value="{}")
        server.zim_operations.list_namespaces = MagicMock(return_value="{}")
        server.zim_operations.get_main_page = MagicMock(return_value="content")

        result_json = server.zim_operations.warm_cache("/zim/test.zim")
        result = json.loads(result_json)
        assert "list_zim_files" in result["warmed"]
        assert "get_zim_metadata" in result["warmed"]
        assert "list_namespaces" in result["warmed"]
        assert "get_main_page" in result["warmed"]
        assert result["failed"] == []

    def test_warm_cache_partial_failure(self, server: OpenZimMcpServer):
        """Test that a failure on one step doesn't abort the rest."""
        server.zim_operations.path_validator = MagicMock()
        server.zim_operations.path_validator.validate_path.return_value = (
            "/zim/test.zim"
        )
        server.zim_operations.path_validator.validate_zim_file.return_value = (
            "/zim/test.zim"
        )
        server.zim_operations.list_zim_files = MagicMock(return_value="[]")
        server.zim_operations.get_zim_metadata = MagicMock(return_value="{}")
        server.zim_operations.list_namespaces = MagicMock(return_value="{}")
        server.zim_operations.get_main_page = MagicMock(
            side_effect=RuntimeError("no main page")
        )

        result_json = server.zim_operations.warm_cache("/zim/test.zim")
        result = json.loads(result_json)
        assert "list_zim_files" in result["warmed"]
        assert "get_zim_metadata" in result["warmed"]
        assert "list_namespaces" in result["warmed"]
        failed_steps = [f["step"] for f in result["failed"]]
        assert "get_main_page" in failed_steps
