"""Regression tests for code-review 2026-06-10 Phase 11 (coverage gaps).

M11 (PathValidator security branches), M13 (server_state health/config report
builders), L2 (async _data wrapper forwarding).
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openzim_mcp.async_operations import AsyncZimOperations
from openzim_mcp.exceptions import (
    OpenZimMcpSecurityError,
    OpenZimMcpValidationError,
)
from openzim_mcp.security import (
    PathValidator,
    sanitize_context_for_error,
    sanitize_input,
)
from openzim_mcp.zim_operations import ZimOperations


# ---------------------------------------------------------------------------
# M11 — PathValidator security-control branches
# ---------------------------------------------------------------------------
@pytest.fixture
def validator(tmp_path: Path) -> PathValidator:
    return PathValidator([str(tmp_path)])


def test_m11_url_encoded_traversal_rejected(validator):
    with pytest.raises(OpenZimMcpSecurityError):
        validator.validate_path("%2e%2e%2fetc/passwd")


def test_m11_double_encoded_traversal_rejected(validator):
    with pytest.raises(OpenZimMcpSecurityError):
        validator.validate_path("%252e%252e%252fetc%252fpasswd")


def test_m11_overlong_path_rejected(validator):
    with pytest.raises(OpenZimMcpValidationError, match="too long"):
        validator.validate_path("a" * 5000)


def test_m11_toctou_symlink_swap_rejected(tmp_path: Path):
    # A .zim symlink inside the allowed dir that resolves OUTSIDE must be
    # rejected by validate_zim_file's strict re-resolve (the TOCTOU guard).
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    real = outside / "evil.zim"
    real.write_bytes(b"ZIM\x04")
    link = allowed / "link.zim"
    link.symlink_to(real)

    pv = PathValidator([str(allowed)])
    with pytest.raises(OpenZimMcpSecurityError, match="resolves outside"):
        pv.validate_zim_file(link)


def test_m11_sanitize_input_empty_after_strip_raises():
    with pytest.raises(OpenZimMcpValidationError, match="empty"):
        sanitize_input("\x00\x01\x02")


def test_m11_sanitize_input_allow_empty_returns_empty():
    assert sanitize_input("\x00\x01", allow_empty=True) == ""


def test_m11_sanitize_context_truncated_with_ellipsis():
    out = sanitize_context_for_error("x" * 5000)
    assert out.endswith("...")
    assert len(out) <= 1024 + 3


# ---------------------------------------------------------------------------
# M13 — server_state report builders
# ---------------------------------------------------------------------------
def _make_server(tmp_path: Path):
    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.server import OpenZimMcpServer

    cfg = OpenZimMcpConfig(allowed_directories=[str(tmp_path)])
    return OpenZimMcpServer(cfg)


def test_m13_build_health_report_ok(tmp_path: Path):
    from openzim_mcp.server_state import _build_health_report

    server = _make_server(tmp_path)
    report = _build_health_report(server)
    assert "status" in report
    assert report["status"] in {"healthy", "warning", "degraded", "error"}


def test_m13_health_report_degrades_and_redacts_on_missing_dir(tmp_path: Path):
    from openzim_mcp.server_state import _build_health_report

    server = _make_server(tmp_path)
    # Point at a now-missing directory to drive the degradation branch.
    missing = tmp_path / "gone"
    server.config.allowed_directories = [str(missing)]
    report = _build_health_report(server)
    assert report["status"] in {"warning", "degraded", "error"}
    # The raw absolute path must NOT leak into warnings (redaction property).
    blob = repr(report)
    assert str(missing) not in blob


def test_m13_build_configuration_report_redacts_paths(tmp_path: Path):
    from openzim_mcp.server_state import _build_configuration_report

    server = _make_server(tmp_path)
    report = _build_configuration_report(server)
    assert isinstance(report, dict)
    # Allowed directories are redacted (basename only) in the report.
    assert str(tmp_path) not in repr(report)


# ---------------------------------------------------------------------------
# L2 — async _data wrappers forward their arguments to the sync ops layer
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,args",
    [
        ("search_zim_file_data", ("/a.zim", "query")),
        ("browse_namespace_data", ("/a.zim", "C")),
        ("get_zim_entry_data", ("/a.zim", "A/Foo")),
        ("get_zim_metadata_data", ("/a.zim",)),
        ("get_main_page_data", ("/a.zim",)),
        ("get_table_of_contents_data", ("/a.zim", "A/Foo")),
        ("get_article_structure_data", ("/a.zim", "A/Foo")),
        ("find_entry_by_title_data", ("/a.zim", "Foo")),
    ],
)
async def test_l2_async_data_wrapper_forwards(method, args):
    sync_ops = MagicMock(spec=ZimOperations)
    getattr(sync_ops, method).return_value = {"ok": True}
    async_ops = AsyncZimOperations(sync_ops)

    result = await getattr(async_ops, method)(*args)

    assert result == {"ok": True}
    getattr(sync_ops, method).assert_called_once()
    called_args = getattr(sync_ops, method).call_args.args
    assert called_args[: len(args)] == args


# ---------------------------------------------------------------------------
# L3 — the streamable-HTTP subscription watcher is started/stopped by lifespan
# ---------------------------------------------------------------------------
def test_l3_watcher_started_and_stopped_by_lifespan(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    import openzim_mcp.http_app as http_app
    import openzim_mcp.subscriptions as subs
    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.server import OpenZimMcpServer

    # Stub watcher whose start/stop we can assert on.
    stub = MagicMock()
    stub.start = AsyncMock()
    stub.stop = AsyncMock()
    monkeypatch.setattr(subs, "MtimeWatcher", lambda *a, **k: stub)
    monkeypatch.setattr(http_app, "check_safe_startup", lambda c: None)

    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        transport="http",
        subscriptions_enabled=True,
    )
    server = OpenZimMcpServer(cfg)
    assert server.subscriber_registry is not None

    # Swap FastMCP's streamable app for a plain Starlette app with a trivial
    # lifespan so the test exercises the watcher wrapper, not the session
    # manager. serve_streamable_http wraps this inner lifespan with the watcher.
    server.mcp.streamable_http_app = MagicMock(return_value=Starlette())
    server.mcp._custom_starlette_routes = []
    server.mcp.settings = MagicMock()

    captured: dict = {}
    http_app.serve_streamable_http(
        server, runner=lambda app, host, port: captured.update(app=app)
    )

    with TestClient(captured["app"]):
        pass  # entering/exiting the context runs the full lifespan.

    stub.start.assert_awaited_once()
    stub.stop.assert_awaited_once()
