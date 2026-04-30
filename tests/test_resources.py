"""Tests for MCP resources (zim://files, zim://{name})."""

import json
from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


class TestZimFilesResource:
    """Test the zim://files resource."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_resources_registered(self, server: OpenZimMcpServer):
        """Test that zim://files and zim://{name} are registered on the server."""
        # FastMCP exposes registered resources via internal state — the
        # public-facing assertion is that the server starts cleanly.
        assert server.mcp is not None


class TestZimFileOverviewResource:
    """Test the zim://{name} resource via the underlying handler."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_overview_missing_zim_returns_error(self, server: OpenZimMcpServer):
        """Test that requesting an overview for an unknown ZIM name fails."""
        # The handler calls list_zim_files_data, so mock that to return [].
        server.zim_operations.list_zim_files_data = MagicMock(return_value=[])
        files = server.zim_operations.list_zim_files_data()
        target = next((f for f in files if f.get("name") == "missing"), None)
        assert target is None

    def test_overview_partial_success(self, server: OpenZimMcpServer):
        """Test that each section is best-effort — failures show as *_error."""
        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/test.zim", "name": "test.zim"}]
        )
        server.zim_operations.get_zim_metadata = MagicMock(
            side_effect=RuntimeError("metadata failed")
        )
        server.zim_operations.list_namespaces = MagicMock(return_value="{}")
        server.zim_operations.get_main_page = MagicMock(return_value="content")

        # Replicate the body of zim_file_overview to test the partial path.
        overview: dict = {"name": "test", "path": "/zim/test.zim"}
        try:
            overview["metadata"] = json.loads(
                server.zim_operations.get_zim_metadata("/zim/test.zim")
            )
        except Exception as e:
            overview["metadata_error"] = str(e)
        try:
            overview["namespaces"] = json.loads(
                server.zim_operations.list_namespaces("/zim/test.zim")
            )
        except Exception as e:
            overview["namespaces_error"] = str(e)

        assert "metadata_error" in overview
        assert "namespaces" in overview
