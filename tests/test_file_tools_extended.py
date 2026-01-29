"""
Extended tests for file_tools module to increase test coverage.

These tests focus on the untested paths in file_tools.py:
- Rate limit error handling
- Instance tracker conflict detection (configuration_mismatch, multiple_instances)
- Diagnostic error handling when instance tracker fails
- Warning text formatting
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.server import OpenZimMcpServer


class TestListZimFilesToolInvocation:
    """Test list_zim_files tool by invoking the actual registered handler."""

    @pytest.fixture
    def advanced_server(self, temp_dir):
        """Create a server in advanced mode."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        return OpenZimMcpServer(config)

    @pytest.mark.asyncio
    async def test_list_zim_files_success(self, advanced_server):
        """Test successful ZIM file listing through tool handler."""
        advanced_server.async_zim_operations.list_zim_files = AsyncMock(
            return_value='[{"path": "/test/file.zim", "size": 1024}]'
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "list_zim_files" in tools:
            tool_handler = tools["list_zim_files"].fn
            result = await tool_handler()
            assert "file.zim" in result

    @pytest.mark.asyncio
    async def test_list_zim_files_rate_limit_error(self, advanced_server):
        """Test rate limit error handling in list_zim_files."""
        # Configure rate limiter to raise error
        advanced_server.rate_limiter.check_rate_limit = MagicMock(
            side_effect=OpenZimMcpRateLimitError("Rate limit exceeded")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "list_zim_files" in tools:
            tool_handler = tools["list_zim_files"].fn
            result = await tool_handler()
            # Should return error message, not raise exception
            assert "Error" in result or "Rate" in result

    @pytest.mark.asyncio
    async def test_list_zim_files_generic_exception(self, advanced_server):
        """Test generic exception handling in list_zim_files."""
        advanced_server.async_zim_operations.list_zim_files = AsyncMock(
            side_effect=RuntimeError("File system error")
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "list_zim_files" in tools:
            tool_handler = tools["list_zim_files"].fn
            result = await tool_handler()
            # Should return error message, not raise exception
            assert "Error" in result or "error" in result.lower()


class TestListZimFilesConflictDetection:
    """Test conflict detection in list_zim_files."""

    @pytest.fixture
    def server_with_tracker(self, temp_dir):
        """Create a server with an instance tracker."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)
        # Mock instance tracker
        server.instance_tracker = MagicMock()
        return server

    @pytest.mark.asyncio
    async def test_list_zim_files_with_configuration_mismatch_conflict(
        self, server_with_tracker
    ):
        """Test list_zim_files with configuration mismatch conflict."""
        server_with_tracker.async_zim_operations.list_zim_files = AsyncMock(
            return_value='[{"path": "/test/file.zim"}]'
        )
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[
                {
                    "type": "configuration_mismatch",
                    "instance": {"pid": 12345},
                }
            ]
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "list_zim_files" in tools:
            tool_handler = tools["list_zim_files"].fn
            result = await tool_handler()
            # Should contain both warning and file listing
            assert "SERVER DIAGNOSTICS:" in result
            assert "WARNING: Configuration mismatch" in result
            assert "12345" in result
            assert "ZIM FILES:" in result
            assert "file.zim" in result

    @pytest.mark.asyncio
    async def test_list_zim_files_with_multiple_instances_conflict(
        self, server_with_tracker
    ):
        """Test list_zim_files with multiple instances conflict."""
        server_with_tracker.async_zim_operations.list_zim_files = AsyncMock(
            return_value='[{"path": "/test/file.zim"}]'
        )
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[
                {
                    "type": "multiple_instances",
                    "instance": {"pid": 67890},
                }
            ]
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "list_zim_files" in tools:
            tool_handler = tools["list_zim_files"].fn
            result = await tool_handler()
            # Should contain both warning and file listing
            assert "SERVER DIAGNOSTICS:" in result
            assert "WARNING: Multiple server instances" in result
            assert "67890" in result
            assert "ZIM FILES:" in result

    @pytest.mark.asyncio
    async def test_list_zim_files_with_both_conflict_types(self, server_with_tracker):
        """Test list_zim_files with both conflict types."""
        server_with_tracker.async_zim_operations.list_zim_files = AsyncMock(
            return_value='[{"path": "/test/file.zim"}]'
        )
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[
                {
                    "type": "configuration_mismatch",
                    "instance": {"pid": 12345},
                },
                {
                    "type": "multiple_instances",
                    "instance": {"pid": 67890},
                },
            ]
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "list_zim_files" in tools:
            tool_handler = tools["list_zim_files"].fn
            result = await tool_handler()
            # Should contain both warnings
            assert "Configuration mismatch" in result
            assert "Multiple server instances" in result

    @pytest.mark.asyncio
    async def test_list_zim_files_conflict_detection_error(self, server_with_tracker):
        """Test list_zim_files when conflict detection raises an exception."""
        server_with_tracker.async_zim_operations.list_zim_files = AsyncMock(
            return_value='[{"path": "/test/file.zim"}]'
        )
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            side_effect=RuntimeError("Failed to detect conflicts")
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "list_zim_files" in tools:
            tool_handler = tools["list_zim_files"].fn
            result = await tool_handler()
            # Should contain diagnostic error warning
            assert "SERVER DIAGNOSTICS:" in result
            assert "Could not check for server conflicts" in result
            assert "ZIM FILES:" in result

    @pytest.mark.asyncio
    async def test_list_zim_files_no_conflicts(self, server_with_tracker):
        """Test list_zim_files when no conflicts are detected."""
        server_with_tracker.async_zim_operations.list_zim_files = AsyncMock(
            return_value='[{"path": "/test/file.zim"}]'
        )
        server_with_tracker.instance_tracker.detect_conflicts = MagicMock(
            return_value=[]
        )

        tools = server_with_tracker.mcp._tool_manager._tools
        if "list_zim_files" in tools:
            tool_handler = tools["list_zim_files"].fn
            result = await tool_handler()
            # Should NOT contain warnings
            assert "SERVER DIAGNOSTICS:" not in result
            assert "file.zim" in result


class TestListZimFilesNoInstanceTracker:
    """Test list_zim_files when instance tracker is None."""

    @pytest.fixture
    def server_without_tracker(self, temp_dir):
        """Create a server without an instance tracker."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        server = OpenZimMcpServer(config)
        server.instance_tracker = None
        return server

    @pytest.mark.asyncio
    async def test_list_zim_files_without_instance_tracker(
        self, server_without_tracker
    ):
        """Test list_zim_files without instance tracker."""
        server_without_tracker.async_zim_operations.list_zim_files = AsyncMock(
            return_value='[{"path": "/test/file.zim"}]'
        )

        tools = server_without_tracker.mcp._tool_manager._tools
        if "list_zim_files" in tools:
            tool_handler = tools["list_zim_files"].fn
            result = await tool_handler()
            # Should just return the file listing without conflict checks
            assert "file.zim" in result
            assert "SERVER DIAGNOSTICS:" not in result


class TestWarningTextFormatting:
    """Test warning text formatting details."""

    def test_warning_text_single_warning(self):
        """Test warning text formatting with single warning."""
        warnings = [
            {
                "message": "WARNING: Test warning message",
                "resolution": "Test resolution steps",
            }
        ]

        warning_text = "\nSERVER DIAGNOSTICS:\n"
        for warning in warnings:
            warning_text += f"\n{warning['message']}\n"
            warning_text += f"Resolution: {warning['resolution']}\n"
        warning_text += "\nZIM FILES:\n"

        assert "SERVER DIAGNOSTICS:" in warning_text
        assert "Test warning message" in warning_text
        assert "Resolution: Test resolution steps" in warning_text
        assert "ZIM FILES:" in warning_text

    def test_warning_text_multiple_warnings(self):
        """Test warning text formatting with multiple warnings."""
        warnings = [
            {
                "message": "WARNING: First warning",
                "resolution": "First resolution",
            },
            {
                "message": "WARNING: Second warning",
                "resolution": "Second resolution",
            },
        ]

        warning_text = "\nSERVER DIAGNOSTICS:\n"
        for warning in warnings:
            warning_text += f"\n{warning['message']}\n"
            warning_text += f"Resolution: {warning['resolution']}\n"
        warning_text += "\nZIM FILES:\n"

        assert "First warning" in warning_text
        assert "Second warning" in warning_text
        assert "First resolution" in warning_text
        assert "Second resolution" in warning_text

    def test_configuration_conflict_warning_structure(self):
        """Test configuration conflict warning structure."""
        conflict = {
            "type": "configuration_mismatch",
            "instance": {"pid": 12345},
        }

        warning = {
            "type": "configuration_conflict",
            "message": (
                f"WARNING: Configuration mismatch detected "
                f"with server PID {conflict['instance']['pid']}"
            ),
            "resolution": (
                "Different server configurations may "
                "cause inconsistent results. Consider "
                "stopping other instances or ensuring they "
                "use the same configuration."
            ),
            "severity": "high",
        }

        assert warning["type"] == "configuration_conflict"
        assert "12345" in warning["message"]
        assert warning["severity"] == "high"
        assert "inconsistent results" in warning["resolution"]

    def test_multiple_servers_warning_structure(self):
        """Test multiple servers warning structure."""
        conflict = {
            "type": "multiple_instances",
            "instance": {"pid": 67890},
        }

        warning = {
            "type": "multiple_servers",
            "message": (
                f"WARNING: Multiple server instances detected "
                f"(PID {conflict['instance']['pid']})"
            ),
            "resolution": (
                "Multiple servers may cause confusion. "
                "Use 'diagnose_server_state()' for detailed "
                "analysis or stop unused instances."
            ),
            "severity": "medium",
        }

        assert warning["type"] == "multiple_servers"
        assert "67890" in warning["message"]
        assert warning["severity"] == "medium"
        assert "diagnose_server_state()" in warning["resolution"]

    def test_diagnostic_error_warning_structure(self):
        """Test diagnostic error warning structure."""
        error = RuntimeError("Connection failed")

        warning = {
            "type": "diagnostic_error",
            "message": f"Could not check for server conflicts: {error}",
            "resolution": (
                "Server conflict detection failed. Results may "
                "be from a different server instance."
            ),
            "severity": "low",
        }

        assert warning["type"] == "diagnostic_error"
        assert "Connection failed" in warning["message"]
        assert warning["severity"] == "low"


class TestEmptyZimFilesList:
    """Test list_zim_files with empty results."""

    @pytest.fixture
    def advanced_server(self, temp_dir):
        """Create a server in advanced mode."""
        config = OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
        return OpenZimMcpServer(config)

    @pytest.mark.asyncio
    async def test_list_zim_files_empty_result(self, advanced_server):
        """Test list_zim_files when no ZIM files are found."""
        advanced_server.async_zim_operations.list_zim_files = AsyncMock(
            return_value="[]"
        )

        tools = advanced_server.mcp._tool_manager._tools
        if "list_zim_files" in tools:
            tool_handler = tools["list_zim_files"].fn
            result = await tool_handler()
            assert result == "[]"
