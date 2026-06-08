"""Tests for `openzim-mcp build link-graph` argument handling."""

from __future__ import annotations

from unittest.mock import patch

from openzim_mcp.cli.build import build_main
from openzim_mcp.linkgraph.builder import BuildStats


def test_build_link_graph_invokes_builder(tmp_path):
    """`build link-graph <archive>` calls the builder with force=False."""
    archive = tmp_path / "wiki.zim"
    archive.write_bytes(b"")
    fake = BuildStats(node_count=3, edge_count=2, bytes_written=4096)
    with patch(
        "openzim_mcp.cli.build.build_link_graph", return_value=fake
    ) as mock_build:
        rc = build_main(["link-graph", str(archive)])
    assert rc == 0
    mock_build.assert_called_once()
    assert mock_build.call_args.kwargs["force"] is False


def test_build_force_flag_forwarded(tmp_path):
    """The --force flag is forwarded to the builder."""
    archive = tmp_path / "wiki.zim"
    archive.write_bytes(b"")
    with patch(
        "openzim_mcp.cli.build.build_link_graph",
        return_value=BuildStats(0, 0, 0),
    ) as mock_build:
        rc = build_main(["link-graph", str(archive), "--force"])
    assert rc == 0
    assert mock_build.call_args.kwargs["force"] is True


def test_build_existing_without_force_returns_nonzero(tmp_path):
    """A FileExistsError from the builder maps to a nonzero exit code."""
    archive = tmp_path / "wiki.zim"
    archive.write_bytes(b"")
    with patch(
        "openzim_mcp.cli.build.build_link_graph", side_effect=FileExistsError("exists")
    ):
        rc = build_main(["link-graph", str(archive)])
    assert rc != 0


def test_unknown_artifact_returns_nonzero():
    """An unknown build artifact returns a nonzero exit code."""
    assert build_main(["embeddings", "/x.zim"]) != 0
