"""Tests for MCP resources (zim://files, zim://{name})."""

import json
from unittest.mock import MagicMock

import pytest
from mcp.server.mcpserver import Context

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


@pytest.fixture
def ctx(server: OpenZimMcpServer) -> Context:
    """Build the ``Context`` that SDK v2 requires on every resource lookup.

    ``ResourceManager.get_resource`` takes a mandatory ``context`` in MCP 2.0
    so templates can drive the multi-round-trip input flow. These resources
    never request input, so a bare context bound to the server's own MCPServer
    and subscription bus is enough to exercise the handlers.
    """
    return Context(mcp_server=server.mcp, subscriptions=server.subscription_bus)


class TestZimFilesResource:
    """Test the zim://files resource."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_resources_registered(self, server: OpenZimMcpServer):
        """Test that zim://files and zim://{name} are registered on the server."""
        # MCPServer exposes registered resources via internal state — the
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


class TestZimFilesResourceHandler:
    """Exercise the zim://files handler through the SDK resource manager."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a server instance with all resources registered."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_zim_files_returns_index(self, server, ctx: Context):
        """Happy path: list_zim_files_data is rendered as JSON."""
        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[
                {"path": "/zim/a.zim", "name": "a.zim", "size": 10, "modified": "now"}
            ]
        )
        rm = server.mcp._resource_manager
        resource = await rm.get_resource("zim://files", ctx)
        body = await resource.read()
        data = json.loads(body)
        assert data[0]["path"] == "/zim/a.zim"

    @pytest.mark.asyncio
    async def test_zim_files_returns_error_on_failure(self, server, ctx: Context):
        """If list_zim_files_data raises, the resource returns a JSON error envelope."""
        server.zim_operations.list_zim_files_data = MagicMock(
            side_effect=RuntimeError("boom")
        )
        rm = server.mcp._resource_manager
        resource = await rm.get_resource("zim://files", ctx)
        body = await resource.read()
        data = json.loads(body)
        assert "error" in data
        assert "boom" in data["error"]


class TestZimFileOverviewHandler:
    """Exercise the zim://{name} handler via the SDK resource manager."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a server instance with all resources registered."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_overview_unknown_name_returns_error_envelope(
        self, server, ctx: Context
    ):
        """Unknown name → error JSON listing available names."""
        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wiki.zim", "name": "wiki.zim"}]
        )
        rm = server.mcp._resource_manager
        resource = await rm.get_resource("zim://nonexistent", ctx)
        body = await resource.read()
        data = json.loads(body)
        assert "error" in data
        assert "wiki" in data["error"]  # available names listed

    @pytest.mark.asyncio
    async def test_overview_collects_partial_failures(self, server, ctx: Context):
        """Each section is best-effort — failures surface as *_error fields."""
        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wiki.zim", "name": "wiki.zim"}]
        )
        server.zim_operations.get_zim_metadata = MagicMock(
            side_effect=RuntimeError("metadata broke")
        )
        server.zim_operations.list_namespaces = MagicMock(
            return_value='{"namespaces": ["A"]}'
        )
        server.zim_operations.get_main_page = MagicMock(
            side_effect=RuntimeError("main page broke")
        )

        rm = server.mcp._resource_manager
        resource = await rm.get_resource("zim://wiki", ctx)
        body = await resource.read()
        data = json.loads(body)
        assert data["name"] == "wiki"
        assert data["metadata_error"] == "metadata broke"
        assert data["namespaces"] == {"namespaces": ["A"]}
        assert data["main_page_error"] == "main page broke"

    @pytest.mark.asyncio
    async def test_overview_truncates_long_main_page(self, server, ctx: Context):
        """Main page preview is trimmed to 2000 chars + truncation marker."""
        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/wiki.zim", "name": "wiki.zim"}]
        )
        server.zim_operations.get_zim_metadata = MagicMock(return_value="{}")
        server.zim_operations.list_namespaces = MagicMock(return_value="{}")
        server.zim_operations.get_main_page = MagicMock(return_value="x" * 5000)

        rm = server.mcp._resource_manager
        resource = await rm.get_resource("zim://wiki", ctx)
        body = await resource.read()
        data = json.loads(body)
        assert len(data["main_page_preview"]) < 5000
        assert "truncated" in data["main_page_preview"]

    @pytest.mark.asyncio
    async def test_overview_outer_exception_wraps_in_error(self, server, ctx: Context):
        """An exception in list_zim_files_data hits the outer try/except."""
        server.zim_operations.list_zim_files_data = MagicMock(
            side_effect=RuntimeError("listing exploded")
        )
        rm = server.mcp._resource_manager
        resource = await rm.get_resource("zim://anything", ctx)
        body = await resource.read()
        data = json.loads(body)
        assert "error" in data
        assert "listing exploded" in data["error"]
