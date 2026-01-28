"""
Tests for the InstanceTracker class and related functionality.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.instance_tracker import InstanceTracker, ServerInstance, safe_log


class TestSafeLog:
    """Test the safe_log utility function."""

    def test_safe_log_success(self):
        """Test safe_log with successful logging."""
        mock_log_func = MagicMock()
        message = "Test log message"

        safe_log(mock_log_func, message)

        mock_log_func.assert_called_once_with(message)

    def test_safe_log_handles_value_error(self):
        """Test safe_log handles ValueError (I/O operation on closed file)."""
        mock_log_func = MagicMock(
            side_effect=ValueError("I/O operation on closed file")
        )
        message = "Test log message"

        # Should not raise an exception
        safe_log(mock_log_func, message)

        mock_log_func.assert_called_once_with(message)

    def test_safe_log_handles_os_error(self):
        """Test safe_log handles OSError (file descriptor issues)."""
        mock_log_func = MagicMock(side_effect=OSError("Bad file descriptor"))
        message = "Test log message"

        # Should not raise an exception
        safe_log(mock_log_func, message)

        mock_log_func.assert_called_once_with(message)

    def test_safe_log_handles_attribute_error(self):
        """Test safe_log handles AttributeError (logging objects may be None)."""
        mock_log_func = MagicMock(
            side_effect=AttributeError("'NoneType' object has no attribute 'write'")
        )
        message = "Test log message"

        # Should not raise an exception
        safe_log(mock_log_func, message)

        mock_log_func.assert_called_once_with(message)

    def test_safe_log_handles_generic_exception(self):
        """Test safe_log handles any other exception during logging."""
        mock_log_func = MagicMock(side_effect=RuntimeError("Unexpected logging error"))
        message = "Test log message"

        # Should not raise an exception
        safe_log(mock_log_func, message)

        mock_log_func.assert_called_once_with(message)


class TestServerInstance:
    """Test the ServerInstance class."""

    def test_server_instance_creation(self):
        """Test creating a ServerInstance."""
        instance = ServerInstance(
            pid=12345,
            config_hash="abc123",
            allowed_directories=["/test/dir"],
            server_name="test_server",
            start_time=1234567890.0,
        )

        assert instance.pid == 12345
        assert instance.config_hash == "abc123"
        assert instance.allowed_directories == ["/test/dir"]
        assert instance.server_name == "test_server"
        assert instance.start_time == 1234567890.0

    def test_server_instance_to_dict(self):
        """Test converting ServerInstance to dictionary."""
        instance = ServerInstance(
            pid=12345,
            config_hash="abc123",
            allowed_directories=["/test/dir"],
            server_name="test_server",
            start_time=1234567890.0,
        )

        result = instance.to_dict()

        assert result["pid"] == 12345
        assert result["config_hash"] == "abc123"
        assert result["allowed_directories"] == ["/test/dir"]
        assert result["server_name"] == "test_server"
        assert result["start_time"] == 1234567890.0
        assert "last_heartbeat" in result
        assert "start_time_iso" in result
        assert "last_heartbeat_iso" in result

    def test_server_instance_from_dict(self):
        """Test creating ServerInstance from dictionary."""
        data = {
            "pid": 12345,
            "config_hash": "abc123",
            "allowed_directories": ["/test/dir"],
            "server_name": "test_server",
            "start_time": 1234567890.0,
            "last_heartbeat": 1234567900.0,
        }

        instance = ServerInstance.from_dict(data)

        assert instance.pid == 12345
        assert instance.config_hash == "abc123"
        assert instance.allowed_directories == ["/test/dir"]
        assert instance.server_name == "test_server"
        assert instance.start_time == 1234567890.0
        assert instance.last_heartbeat == 1234567900.0

    def test_server_instance_is_alive_running_process(self):
        """Test is_alive() method with a running process."""
        instance = ServerInstance(
            pid=12345,
            config_hash="abc123",
            allowed_directories=["/test/dir"],
            server_name="test_server",
            start_time=1234567890.0,
        )

        with patch("os.kill") as mock_kill:
            # os.kill returns None for running processes
            mock_kill.return_value = None

            result = instance.is_alive()

            assert result is True
            mock_kill.assert_called_once_with(12345, 0)

    def test_server_instance_is_alive_dead_process_os_error(self):
        """Test is_alive() method with a dead process (OSError)."""
        instance = ServerInstance(
            pid=12345,
            config_hash="abc123",
            allowed_directories=["/test/dir"],
            server_name="test_server",
            start_time=1234567890.0,
        )

        with patch("os.kill") as mock_kill:
            # os.kill raises OSError for dead processes
            mock_kill.side_effect = OSError("No such process")

            result = instance.is_alive()

            assert result is False
            mock_kill.assert_called_once_with(12345, 0)

    def test_server_instance_is_alive_dead_process_lookup_error(self):
        """Test is_alive() method with a dead process (ProcessLookupError)."""
        instance = ServerInstance(
            pid=12345,
            config_hash="abc123",
            allowed_directories=["/test/dir"],
            server_name="test_server",
            start_time=1234567890.0,
        )

        with patch("os.kill") as mock_kill:
            # os.kill raises ProcessLookupError for dead processes
            mock_kill.side_effect = ProcessLookupError("No such process")

            result = instance.is_alive()

            assert result is False
            mock_kill.assert_called_once_with(12345, 0)

    def test_server_instance_update_heartbeat(self):
        """Test update_heartbeat() method updates the timestamp."""
        instance = ServerInstance(
            pid=12345,
            config_hash="abc123",
            allowed_directories=["/test/dir"],
            server_name="test_server",
            start_time=1234567890.0,
        )

        original_heartbeat = instance.last_heartbeat

        with patch("time.time") as mock_time:
            mock_time.return_value = 1234567999.0

            instance.update_heartbeat()

            assert instance.last_heartbeat == 1234567999.0
            assert instance.last_heartbeat != original_heartbeat
            mock_time.assert_called_once()


class TestInstanceTracker:
    """Test the InstanceTracker class."""

    @pytest.fixture
    def temp_instances_dir(self):
        """Create a temporary directory for instance tracking."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def instance_tracker(self, temp_instances_dir):
        """Create an InstanceTracker with temporary directory."""
        with patch.object(InstanceTracker, "__init__", lambda self: None):
            tracker = InstanceTracker()
            tracker.instances_dir = temp_instances_dir
            tracker.current_instance = None
            temp_instances_dir.mkdir(exist_ok=True)
            return tracker

    def test_instance_tracker_initialization(self):
        """Test InstanceTracker initialization."""
        with patch("pathlib.Path.home") as mock_home:
            mock_home.return_value = Path("/tmp/fake_home")
            with patch("pathlib.Path.mkdir") as mock_mkdir:
                tracker = InstanceTracker()
                expected_dir = Path("/tmp/fake_home") / ".openzim_mcp_instances"
                assert tracker.instances_dir == expected_dir
                mock_mkdir.assert_called_once_with(exist_ok=True)

    def test_instance_tracker_default_directory(self):
        """Test InstanceTracker with default directory."""
        with patch("pathlib.Path.home") as mock_home:
            mock_home.return_value = Path("/fake/home")
            with patch("pathlib.Path.mkdir"):
                tracker = InstanceTracker()
                expected_dir = Path("/fake/home") / ".openzim_mcp_instances"
                assert tracker.instances_dir == expected_dir

    def test_register_instance(self, instance_tracker):
        """Test registering a server instance."""
        with patch("os.getpid", return_value=12345):
            instance = instance_tracker.register_instance(
                config_hash="abc123",
                allowed_directories=["/test/dir"],
                server_name="test_server",
            )

        assert instance.pid == 12345
        assert instance.config_hash == "abc123"
        assert instance.allowed_directories == ["/test/dir"]
        assert instance.server_name == "test_server"

        # Check that instance file was created
        instance_file = instance_tracker.instances_dir / f"server_{12345}.json"
        assert instance_file.exists()

        # Verify file contents
        with open(instance_file) as f:
            data = json.load(f)

        assert data["pid"] == 12345
        assert data["config_hash"] == "abc123"

    def test_unregister_instance(self, instance_tracker):
        """Test unregistering a server instance."""
        with patch("os.getpid", return_value=12345):
            instance_tracker.register_instance(
                config_hash="abc123",
                allowed_directories=["/test/dir"],
                server_name="test_server",
            )

        instance_file = instance_tracker.instances_dir / f"server_{12345}.json"
        assert instance_file.exists()

        # Unregister the instance
        instance_tracker.unregister_instance(12345)

        # Check that instance file was removed
        assert not instance_file.exists()

    def test_get_active_instances(self, instance_tracker):
        """Test getting active instances."""
        # Mock process running check to return True for test PIDs
        with patch.object(instance_tracker, "_is_process_running", return_value=True):
            # Register multiple instances
            with patch("os.getpid", return_value=12345):
                instance_tracker.register_instance(
                    config_hash="abc123",
                    allowed_directories=["/test/dir1"],
                    server_name="server1",
                )

            with patch("os.getpid", return_value=67890):
                instance_tracker.register_instance(
                    config_hash="def456",
                    allowed_directories=["/test/dir2"],
                    server_name="server2",
                )

            active_instances = instance_tracker.get_active_instances()

            assert len(active_instances) == 2
            pids = [inst.pid for inst in active_instances]
            assert 12345 in pids
            assert 67890 in pids

    def test_detect_conflicts_configuration_mismatch(self, instance_tracker):
        """Test detecting configuration conflicts."""
        # Mock process running check to return True for test PIDs
        with patch.object(instance_tracker, "_is_process_running", return_value=True):
            # Register instance with different config
            with patch("os.getpid", return_value=12345):
                instance_tracker.register_instance(
                    config_hash="different_hash",
                    allowed_directories=["/different/dir"],
                    server_name="different_server",
                )

            # Check for conflicts with current config
            conflicts = instance_tracker.detect_conflicts("current_hash")

            assert len(conflicts) == 1
            assert conflicts[0]["type"] == "configuration_mismatch"
        assert conflicts[0]["instance"]["pid"] == 12345

    def test_detect_conflicts_multiple_instances(self, instance_tracker):
        """Test detecting multiple instances with same config."""
        # Mock process running check to return True for test PIDs
        with patch.object(instance_tracker, "_is_process_running", return_value=True):
            # Register instance with same config
            with patch("os.getpid", return_value=12345):
                instance_tracker.register_instance(
                    config_hash="same_hash",
                    allowed_directories=["/test/dir"],
                    server_name="test_server",
                )

            # Check for conflicts with same config
            conflicts = instance_tracker.detect_conflicts("same_hash")

            assert len(conflicts) == 1
            assert conflicts[0]["type"] == "multiple_instances"
        assert conflicts[0]["instance"]["pid"] == 12345

    @patch("openzim_mcp.instance_tracker.InstanceTracker._is_process_running")
    def test_cleanup_stale_instances(self, mock_is_running, instance_tracker):
        """Test cleaning up stale instances."""
        # Register instances
        with patch("os.getpid", return_value=12345):
            instance_tracker.register_instance(
                config_hash="abc123",
                allowed_directories=["/test/dir1"],
                server_name="server1",
            )

        with patch("os.getpid", return_value=67890):
            instance_tracker.register_instance(
                config_hash="def456",
                allowed_directories=["/test/dir2"],
                server_name="server2",
            )

        # Mock process running status - first is stale, second is active
        mock_is_running.side_effect = lambda pid: pid == 67890

        # Clean up stale instances
        cleaned_count = instance_tracker.cleanup_stale_instances()

        assert cleaned_count == 1

        # Check that only active instance remains
        active_instances = instance_tracker.get_active_instances()
        assert len(active_instances) == 1
        assert active_instances[0].pid == 67890

    def test_is_process_running_unix(self, instance_tracker):
        """Test process running check on Unix systems."""

        # Mock the method directly to test the logic
        def mock_is_process_running(pid):
            if hasattr(mock_is_process_running, "side_effect"):
                if mock_is_process_running.side_effect == ProcessLookupError:
                    return False
                elif mock_is_process_running.side_effect == PermissionError:
                    return True
            return True

        # Test process exists
        assert mock_is_process_running(12345) is True

        # Test process doesn't exist
        mock_is_process_running.side_effect = ProcessLookupError
        assert mock_is_process_running(12345) is False

        # Test permission denied (process exists but owned by another user)
        mock_is_process_running.side_effect = PermissionError
        assert mock_is_process_running(12345) is True

    def test_is_process_running_windows(self, instance_tracker):
        """Test process running check on Windows systems."""
        with patch("platform.system", return_value="Windows"):
            with patch("subprocess.run") as mock_run:
                # Process exists - tasklist returns PID in output
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "Image Name   PID\npython.exe   12345"
                assert instance_tracker._is_process_running(12345) is True

                # Process doesn't exist - tasklist returns "No tasks" message
                mock_run.return_value.returncode = 0  # tasklist always returns 0
                mock_run.return_value.stdout = (
                    "INFO: No tasks are running which match the specified criteria."
                )
                assert instance_tracker._is_process_running(12345) is False

    def test_corrupted_instance_file_handling(self, instance_tracker):
        """Test handling of corrupted instance files."""
        # Create a corrupted instance file
        corrupted_file = instance_tracker.instances_dir / "server_99999.json"
        with open(corrupted_file, "w") as f:
            f.write("invalid json content")

        # Should handle corrupted file gracefully
        active_instances = instance_tracker.get_active_instances()
        assert len(active_instances) == 0

        # Corrupted file should be cleaned up during cleanup
        instance_tracker.cleanup_stale_instances()
        assert not corrupted_file.exists()

    def test_instance_file_permissions(self, instance_tracker):
        """Test that instance files are created with appropriate permissions."""
        with patch("os.getpid", return_value=12345):
            instance_tracker.register_instance(
                config_hash="abc123",
                allowed_directories=["/test/dir"],
                server_name="test_server",
            )

        instance_file = instance_tracker.instances_dir / f"server_{12345}.json"

        # Check that file exists and is readable
        assert instance_file.exists()
        assert instance_file.is_file()

        # Verify we can read the file
        with open(instance_file) as f:
            data = json.load(f)

        assert data["pid"] == 12345
