"""Tests for diagnostic functionality in the OpenZIM MCP server."""

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.instance_tracker import InstanceTracker, ServerInstance
from openzim_mcp.server import OpenZimMcpServer


class TestDiagnosticTools:
    """Test the diagnostic MCP tools."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def test_config(self, temp_dir):
        """Create a test configuration."""
        return OpenZimMcpConfig(
            allowed_directories=[str(temp_dir)],
            cache=CacheConfig(enabled=True, max_size=10, ttl_seconds=60),
            content=ContentConfig(max_content_length=1000, snippet_length=100),
            logging=LoggingConfig(level="DEBUG"),
            server_name="test_server",
        )

    @pytest.fixture
    def mock_instance_tracker(self):
        """Create a mock instance tracker."""
        tracker = Mock(spec=InstanceTracker)
        tracker.get_active_instances.return_value = []
        tracker.detect_conflicts.return_value = []
        tracker.cleanup_stale_instances.return_value = 0
        return tracker

    @pytest.fixture
    def server(self, test_config, mock_instance_tracker):
        """Create a OpenZimMcpServer instance for testing."""
        with patch("openzim_mcp.server.ZimOperations"):
            server = OpenZimMcpServer(test_config, mock_instance_tracker)
            return server

    @pytest.mark.asyncio
    async def test_diagnose_server_state_healthy(self, server, mock_instance_tracker):
        """Test diagnose_server_state with healthy server."""
        # Mock healthy state
        mock_instance_tracker.get_active_instances.return_value = []
        mock_instance_tracker.detect_conflicts.return_value = []

        # Call the tool directly
        result = await server.mcp.call_tool("diagnose_server_state", {})
        result_str = str(result)

        # Check that the result contains expected diagnostic information
        # Should be warning when no ZIM files are found
        assert "warning" in result_str
        assert "timestamp" in result_str
        assert "server_info" in result_str
        assert "environment_checks" in result_str
        assert "test_server" in result_str

    @pytest.mark.asyncio
    async def test_diagnose_server_state_with_conflicts(
        self, server, mock_instance_tracker
    ):
        """Test diagnose_server_state with server conflicts."""
        # Mock conflict state
        conflict_instance = ServerInstance(
            pid=12345,
            config_hash="different_hash",
            allowed_directories=["/different/dir"],
            server_name="other_server",
            start_time=1234567890.0,
        )

        mock_instance_tracker.get_active_instances.return_value = [conflict_instance]
        mock_instance_tracker.detect_conflicts.return_value = [
            {
                "type": "configuration_mismatch",
                "instance": conflict_instance.to_dict(),
                "description": "Configuration mismatch detected",
            }
        ]

        # Call the tool
        result = await server.mcp.call_tool("diagnose_server_state", {})

        # Parse the JSON result
        diagnostics = json.loads(result[0][0].text)

        assert diagnostics["status"] in ["warning", "error"]
        assert len(diagnostics["conflicts"]) > 0
        assert len(diagnostics["recommendations"]) > 0
        assert "conflict" in str(diagnostics).lower()

    @pytest.mark.asyncio
    async def test_resolve_server_conflicts_no_conflicts(
        self, server, mock_instance_tracker
    ):
        """Test resolve_server_conflicts with no conflicts."""
        # Mock no conflicts
        mock_instance_tracker.cleanup_stale_instances.return_value = 0
        mock_instance_tracker.detect_conflicts.return_value = []
        mock_instance_tracker.get_active_instances.return_value = []

        # Call the tool
        result = await server.mcp.call_tool("resolve_server_conflicts", {})

        # Parse the JSON result
        resolution = json.loads(result[0][0].text)

        assert resolution["status"] == "success"
        assert resolution["cleanup_results"]["stale_instances_removed"] == 0
        assert len(resolution["conflicts_found"]) == 0
        assert "No active conflicts detected" in str(resolution["recommendations"])

    @pytest.mark.asyncio
    async def test_resolve_server_conflicts_with_cleanup(
        self, server, mock_instance_tracker
    ):
        """Test resolve_server_conflicts with stale instances to clean up."""
        # Mock cleanup scenario
        mock_instance_tracker.cleanup_stale_instances.return_value = 2
        mock_instance_tracker.detect_conflicts.return_value = []
        mock_instance_tracker.get_active_instances.return_value = []

        # Call the tool
        result = await server.mcp.call_tool("resolve_server_conflicts", {})

        # Parse the JSON result
        resolution = json.loads(result[0][0].text)

        assert resolution["status"] == "success"
        assert resolution["cleanup_results"]["stale_instances_removed"] == 2
        assert "Removed 2 stale instance files" in resolution["actions_taken"]

    @pytest.mark.asyncio
    async def test_get_server_health_healthy(self, server, mock_instance_tracker):
        """Test get_server_health with healthy server."""
        # Mock healthy state
        mock_instance_tracker.get_active_instances.return_value = []
        mock_instance_tracker.detect_conflicts.return_value = []

        # Call the tool
        result = await server.mcp.call_tool("get_server_health", {})

        # Parse the JSON result
        health = json.loads(result[0][0].text)

        # Should be warning when no ZIM files are found
        assert health["status"] == "warning"
        assert "timestamp" in health
        assert "server_name" in health
        assert "configuration" in health
        assert "cache_performance" in health
        assert "instance_tracking" in health
        assert "health_checks" in health

    @pytest.mark.asyncio
    async def test_get_server_health_with_warnings(self, server, mock_instance_tracker):
        """Test get_server_health with warnings."""
        # Mock warning state
        mock_instance_tracker.get_active_instances.return_value = []
        mock_instance_tracker.detect_conflicts.return_value = [
            {
                "type": "multiple_instances",
                "instance": {"pid": 12345},
                "description": "Multiple instances detected",
            }
        ]

        # Call the tool
        result = await server.mcp.call_tool("get_server_health", {})

        # Parse the JSON result
        health = json.loads(result[0][0].text)

        assert health["status"] == "warning"
        assert len(health["warnings"]) > 0
        assert len(health["recommendations"]) > 0

    @pytest.mark.asyncio
    async def test_enhanced_error_messages(self, server):
        """Test enhanced error message creation."""
        from openzim_mcp.exceptions import (
            OpenZimMcpArchiveError,
            OpenZimMcpFileNotFoundError,
        )

        # Test file not found error
        error = OpenZimMcpFileNotFoundError("Test file not found")
        message = server._create_enhanced_error_message(
            "test operation", error, "test context"
        )

        assert "**File Not Found Error**" in message
        assert "**Operation**: test operation" in message
        assert "**Context**: test context" in message
        assert "**Troubleshooting Steps**:" in message
        assert "list_zim_files()" in message

        # Test archive error
        error = OpenZimMcpArchiveError("Archive operation failed")
        message = server._create_enhanced_error_message(
            "archive operation", error, "archive context"
        )

        assert "**Archive Operation Error**" in message
        assert "diagnose_server_state()" in message

    @pytest.mark.asyncio
    async def test_proactive_conflict_detection_in_search(
        self, server, mock_instance_tracker
    ):
        """Test proactive conflict detection in search tools."""
        # Mock conflict detection
        mock_instance_tracker.detect_conflicts.return_value = [
            {
                "type": "configuration_mismatch",
                "instance": {"pid": 12345},
                "description": "Configuration mismatch",
            }
        ]

        # Mock search operation
        with patch.object(
            server.zim_operations, "search_zim_file", return_value="Search results"
        ):
            result = await server.mcp.call_tool(
                "search_zim_file", {"zim_file_path": "test.zim", "query": "test query"}
            )

            content = result[0][0].text
            assert "Search results" in content
            assert "**Server Conflict Detected**" in content
            assert "resolve_server_conflicts()" in content

    def test_environment_validation_comprehensive(self, server, temp_dir):
        """Test comprehensive environment validation."""
        # Create test ZIM file
        test_zim = temp_dir / "test.zim"
        with open(test_zim, "wb") as f:
            f.write(b"ZIM\x04")  # Valid ZIM magic number
            f.write(b"\x00" * 100)  # Padding

        # Create invalid ZIM file
        invalid_zim = temp_dir / "invalid.zim"
        with open(invalid_zim, "wb") as f:
            f.write(b"INVALID")  # Invalid magic number

        # Test environment validation logic
        # This would be tested through the diagnose_server_state tool
        # which includes comprehensive environment checks

    @pytest.mark.asyncio
    async def test_diagnostic_tools_error_handling(self, server):
        """Test error handling in diagnostic tools."""
        # Test with instance tracker disabled
        server.instance_tracker = None

        result = await server.mcp.call_tool("diagnose_server_state", {})
        diagnostics = json.loads(result[0][0].text)

        # Should handle missing instance tracker gracefully
        assert "status" in diagnostics
        # When instance tracker is None, there should be no instance_tracking section
        assert "instance_tracking" not in diagnostics

    @pytest.mark.asyncio
    async def test_parameter_validation_enhanced_messages(self, server):
        """Test enhanced parameter validation messages."""
        # Test invalid limit parameter
        result = await server.mcp.call_tool(
            "search_zim_file",
            {
                "zim_file_path": "test.zim",
                "query": "test",
                "limit": 200,  # Invalid limit
            },
        )

        content = result[0][0].text
        assert "**Parameter Validation Error**" in content
        assert "limit must be between 1 and 100" in content
        assert "**Troubleshooting**:" in content
        assert "**Example**:" in content

    @pytest.mark.asyncio
    async def test_configuration_fingerprinting(self, server, temp_dir):
        """Test configuration fingerprinting functionality."""
        config_hash = server.config.get_config_hash()

        # Hash should be consistent
        assert config_hash == server.config.get_config_hash()

        # Hash should be a valid SHA-256 hex string
        assert len(config_hash) == 64
        assert all(c in "0123456789abcdef" for c in config_hash)

        # Different configs should have different hashes
        # Create a different directory for the test
        different_dir = temp_dir / "different"
        different_dir.mkdir()

        other_config = OpenZimMcpConfig(
            allowed_directories=[str(different_dir)],
            cache=CacheConfig(enabled=False),
            content=ContentConfig(max_content_length=2000),
            logging=LoggingConfig(level="INFO"),
            server_name="different_server",
        )

        assert config_hash != other_config.get_config_hash()
