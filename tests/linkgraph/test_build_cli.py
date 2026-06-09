"""Tests for `openzim-mcp build link-graph` argument handling."""

from __future__ import annotations

import sqlite3
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


def test_build_missing_archive(tmp_path, capsys):
    """A non-existent archive path is reported as 'archive not found' (exit 1)."""
    missing = tmp_path / "nope.zim"
    with patch("openzim_mcp.cli.build.build_link_graph") as mock_build:
        rc = build_main(["link-graph", str(missing)])
    assert rc == 1
    assert "archive not found" in capsys.readouterr().err
    mock_build.assert_not_called()


def test_build_not_a_valid_zim(tmp_path, capsys):
    """A real file that is not a ZIM is reported as 'not a valid ZIM' (exit 1)."""
    bogus = tmp_path / "bogus.zim"
    bogus.write_bytes(b"not a zim file at all")
    rc = build_main(["link-graph", str(bogus)])
    assert rc == 1
    assert "not a valid ZIM archive" in capsys.readouterr().err


def test_build_sidecar_exists_message_mentions_force(tmp_path, capsys):
    """A FileExistsError from the builder yields a --force hint (exit 1)."""
    archive = tmp_path / "wiki.zim"
    archive.write_bytes(b"")
    with patch(
        "openzim_mcp.cli.build.build_link_graph",
        side_effect=FileExistsError("exists"),
    ):
        rc = build_main(["link-graph", str(archive)])
    assert rc == 1
    assert "pass --force" in capsys.readouterr().err


def test_build_cannot_write_sidecar(tmp_path, capsys):
    """A SQLite/OS write failure is reported with output context (exit 1)."""
    archive = tmp_path / "wiki.zim"
    archive.write_bytes(b"")
    with patch(
        "openzim_mcp.cli.build.build_link_graph",
        side_effect=sqlite3.OperationalError("unable to open database file"),
    ):
        rc = build_main(["link-graph", str(archive)])
    assert rc == 1
    assert "cannot write sidecar" in capsys.readouterr().err
