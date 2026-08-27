"""Version discoverability: the CLI flag and the health report.

A stale ``uv tool install`` served an old server for weeks while looking
current, because neither the CLI nor ``zim_health`` would say what version
was actually running — ``serverInfo.version`` exists in the initialize
result, but most clients never surface it to the operator. These tests pin
the two places a human can ask.
"""

from pathlib import Path

import pytest

from openzim_mcp import __version__
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.main import _build_arg_parser
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.server_state import _build_health_report


def test_version_flag_prints_version_and_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc_info:
        _build_arg_parser().parse_args(["--version"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "openzim-mcp" in out
    assert __version__ in out


def test_version_flag_works_without_directories(capsys):
    # argparse must answer --version before enforcing the required
    # positional, or the flag is unreachable in practice.
    with pytest.raises(SystemExit) as exc_info:
        _build_arg_parser().parse_args(["--version"])
    assert exc_info.value.code == 0


def test_health_report_carries_server_version(tmp_path: Path):
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        transport="stdio",
        tool_mode="advanced",
    )
    server = OpenZimMcpServer(cfg)
    try:
        report = _build_health_report(server)
        assert report["version"] == __version__
    finally:
        server.cache.shutdown()
