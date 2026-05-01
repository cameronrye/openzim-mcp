"""Instance tracker schema extension for HTTP transport."""

from unittest.mock import patch

from openzim_mcp.instance_tracker import InstanceTracker


def test_register_records_transport_host_port(tmp_path):
    """register_instance accepts transport/host/port and persists them."""
    tracker = InstanceTracker(registry_dir=tmp_path)
    tracker.register_instance(
        config_hash="abc",
        allowed_directories=["/data"],
        server_name="test",
        transport="http",
        host="0.0.0.0",  # nosec B104 - test value
        port=8000,
    )
    instances = tracker.list_running_instances()
    assert len(instances) == 1
    inst = instances[0]
    assert inst.transport == "http"
    assert inst.host == "0.0.0.0"  # nosec B104 - test value
    assert inst.port == 8000


def test_legacy_records_default_to_stdio(tmp_path):
    """Existing call sites without transport/host/port default to stdio."""
    tracker = InstanceTracker(registry_dir=tmp_path)
    tracker.register_instance(
        config_hash="abc",
        allowed_directories=["/data"],
        server_name="test",
    )
    instances = tracker.list_running_instances()
    assert len(instances) == 1
    inst = instances[0]
    assert inst.transport == "stdio"
    assert inst.host is None
    assert inst.port is None


def test_stdio_stdio_same_config_still_conflicts(tmp_path):
    """stdio↔stdio same config still flagged as conflict."""
    tracker = InstanceTracker(registry_dir=tmp_path)
    with patch.object(tracker, "_is_process_running", return_value=True):
        with patch("os.getpid", return_value=12345):
            tracker.register_instance(
                config_hash="same",
                allowed_directories=["/d"],
                server_name="s",
                transport="stdio",
            )
        # find_conflicts runs from a different PID (the test process).
        conflicts = tracker.find_conflicts(config_hash="same", transport="stdio")
    assert len(conflicts) == 1


def test_http_http_same_config_does_not_conflict(tmp_path):
    """Two http instances with the same config never conflict in tracker logic."""
    tracker = InstanceTracker(registry_dir=tmp_path)
    with patch.object(tracker, "_is_process_running", return_value=True):
        with patch("os.getpid", return_value=12345):
            tracker.register_instance(
                config_hash="same",
                allowed_directories=["/d"],
                server_name="s",
                transport="http",
                host="127.0.0.1",
                port=8000,
            )
        conflicts = tracker.find_conflicts(
            config_hash="same",
            transport="http",
            host="127.0.0.1",
            port=8001,
        )
    assert len(conflicts) == 0


def test_stdio_and_http_coexist_same_config(tmp_path):
    """A new http instance ignores existing stdio with same config."""
    tracker = InstanceTracker(registry_dir=tmp_path)
    with patch.object(tracker, "_is_process_running", return_value=True):
        with patch("os.getpid", return_value=12345):
            tracker.register_instance(
                config_hash="same",
                allowed_directories=["/d"],
                server_name="s",
                transport="stdio",
            )
        conflicts = tracker.find_conflicts(
            config_hash="same",
            transport="http",
            host="127.0.0.1",
            port=8000,
        )
    assert len(conflicts) == 0
