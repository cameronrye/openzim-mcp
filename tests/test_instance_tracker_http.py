"""Instance tracker schema extension for HTTP transport."""

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
