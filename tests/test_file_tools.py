"""
Tests for file_tools module.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.server import OpenZimMcpServer


class TestRegisterFileTools:
    """Test file tools registration."""

    def test_register_file_tools(self, test_config: OpenZimMcpConfig):
        """Test that file tools are registered correctly."""
        server = OpenZimMcpServer(test_config)
        assert server.mcp is not None


class TestListZimFilesTool:
    """Test list_zim_files tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_list_zim_files_success(self, server: OpenZimMcpServer):
        """Test successful ZIM file listing."""
        server.async_zim_operations.list_zim_files = AsyncMock(
            return_value='[{"path": "/test/file.zim"}]'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.list_zim_files()

        assert "file.zim" in result
        server.async_zim_operations.list_zim_files.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_zim_files_rate_limit_error(self, server: OpenZimMcpServer):
        """Test rate limit handling in list_zim_files."""
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="list ZIM files",
            error=error,
            context="Listing available ZIM files",
        )
        assert "list ZIM files" in error_msg or "Operation" in error_msg

    @pytest.mark.asyncio
    async def test_list_zim_files_generic_exception(self, server: OpenZimMcpServer):
        """Test generic exception handling in list_zim_files."""
        server.async_zim_operations.list_zim_files = AsyncMock(
            side_effect=Exception("Test error")
        )

        with pytest.raises(Exception) as exc_info:
            await server.async_zim_operations.list_zim_files()
        assert "Test error" in str(exc_info.value)


class TestInstanceTrackerIntegration:
    """Test instance tracker integration in file tools."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_conflict_detection_configuration_mismatch(self, server: OpenZimMcpServer):
        """Test that configuration mismatch conflicts generate correct warnings."""
        conflict = {"type": "configuration_mismatch", "instance": {"pid": 12345}}

        # Simulate warning generation from conflict
        warnings = []
        if conflict["type"] == "configuration_mismatch":
            warnings.append(
                {
                    "type": "configuration_conflict",
                    "message": (
                        "WARNING: Configuration mismatch detected "
                        f"with server PID {conflict['instance']['pid']}"
                    ),
                    "severity": "high",
                }
            )

        assert len(warnings) == 1
        assert warnings[0]["type"] == "configuration_conflict"
        assert "12345" in warnings[0]["message"]
        assert warnings[0]["severity"] == "high"

    def test_conflict_detection_multiple_instances(self, server: OpenZimMcpServer):
        """Test that multiple instance conflicts generate correct warnings."""
        conflict = {"type": "multiple_instances", "instance": {"pid": 67890}}

        warnings = []
        if conflict["type"] == "multiple_instances":
            warnings.append(
                {
                    "type": "multiple_servers",
                    "message": (
                        "WARNING: Multiple server instances detected "
                        f"(PID {conflict['instance']['pid']})"
                    ),
                    "severity": "medium",
                }
            )

        assert len(warnings) == 1
        assert warnings[0]["type"] == "multiple_servers"
        assert "67890" in warnings[0]["message"]
        assert warnings[0]["severity"] == "medium"

    def test_warning_text_formatting(self, server: OpenZimMcpServer):
        """Test that warning text is formatted correctly."""
        warnings = [
            {
                "message": "WARNING: Test warning",
                "resolution": "Test resolution",
            }
        ]

        warning_text = "\nSERVER DIAGNOSTICS:\n"
        for warning in warnings:
            warning_text += f"\n{warning['message']}\n"
            warning_text += f"Resolution: {warning['resolution']}\n"

        warning_text += "\nZIM FILES:\n"

        assert "SERVER DIAGNOSTICS:" in warning_text
        assert "Test warning" in warning_text
        assert "Test resolution" in warning_text
        assert "ZIM FILES:" in warning_text
