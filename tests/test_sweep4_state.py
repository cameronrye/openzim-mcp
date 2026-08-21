"""Regression tests for sweep 4 (server-state redaction, build CLI exit codes).

Covers the ``openzim-mcp build`` help exit status and the transport-gated
redaction of the cache persistence path in the ``zim_health`` report.
"""

from pathlib import Path

import pytest

from openzim_mcp.cli.build import build_main
from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.server_state import _build_health_report

# ---------------------------------------------------------------------------
# build CLI — argparse's SystemExit code must survive the translation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("argv", [["--help"], ["-h"], ["link-graph", "--help"]])
def test_build_help_exits_zero(argv, capsys):
    rc = build_main(argv)
    out = capsys.readouterr().out
    assert "usage:" in out
    assert rc == 0


@pytest.mark.parametrize(
    "argv",
    [
        [],  # missing required artifact
        ["embeddings", "/x.zim"],  # unknown artifact
        ["link-graph"],  # missing required archive
        ["link-graph", "/x.zim", "--nope"],  # unknown option
    ],
)
def test_build_bad_args_still_exit_two(argv):
    assert build_main(argv) == 2


# ---------------------------------------------------------------------------
# zim_health — cache persistence path follows the same redaction rule as the
# PID and the allowed directories
# ---------------------------------------------------------------------------


def _server(tmp_path: Path, transport: str) -> OpenZimMcpServer:
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        transport=transport,
        tool_mode="advanced",
        cache=CacheConfig(
            enabled=True,
            persistence_enabled=True,
            persistence_path=str(tmp_path / "secretdir" / "oz-cache"),
        ),
    )
    return OpenZimMcpServer(cfg)


def test_health_report_http_redacts_persistence_path(tmp_path: Path):
    server = _server(tmp_path, "http")
    try:
        report = _build_health_report(server)
        cache = report["cache_performance"]
        assert cache["persistence_enabled"] is True
        assert "secretdir" not in cache["persistence_path"]
        assert str(tmp_path) not in repr(report)
        # The uptime PID is masked in the same payload — the persistence
        # path must not be the one absolute host path that survives.
        assert report["uptime_info"]["process_id"] == "[REDACTED]"
    finally:
        server.cache.shutdown()


def test_health_report_stdio_keeps_real_persistence_path(tmp_path: Path):
    server = _server(tmp_path, "stdio")
    try:
        report = _build_health_report(server)
        cache = report["cache_performance"]
        assert cache["persistence_path"] == str(
            tmp_path / "secretdir" / "oz-cache.json"
        )
        assert cache["persistence_file_exists"] is False
    finally:
        server.cache.shutdown()


def test_health_report_does_not_mutate_cache_stats(tmp_path: Path, monkeypatch):
    """Redaction must not write back into the dict the cache handed us."""
    server = _server(tmp_path, "http")
    try:
        stats = server.cache.stats()
        monkeypatch.setattr(server.cache, "stats", lambda: stats)
        _build_health_report(server)
        assert stats["persistence_path"] == str(
            tmp_path / "secretdir" / "oz-cache.json"
        )
    finally:
        server.cache.shutdown()
