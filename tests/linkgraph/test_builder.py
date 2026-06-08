"""Tests for the link-graph builder core (synthetic link streams)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openzim_mcp.linkgraph.builder import build_from_link_stream
from openzim_mcp.linkgraph.reader import sidecar_path_for


def _stream():
    # A->T, B->T, A->B  =>  T linked by {A,B}; B linked by {A}
    yield ("C/A", ["C/T", "C/B"])
    yield ("C/B", ["C/T"])
    yield ("C/T", [])


def test_build_inverts_and_computes_degree(tmp_path: Path) -> None:
    """Building inverts edges and precomputes each node's inbound_degree."""
    archive = tmp_path / "x.zim"
    out = sidecar_path_for(archive)
    stats = build_from_link_stream(out, archive_uuid="u1", link_stream=_stream())
    assert stats.edge_count == 3
    conn = sqlite3.connect(out)
    rows = conn.execute(
        """SELECT n.path, n.inbound_degree FROM edges e
           JOIN nodes n ON n.id=e.source_id
           JOIN nodes t ON t.id=e.target_id
           WHERE t.path='C/T'
           ORDER BY n.inbound_degree DESC, n.path""",
    ).fetchall()
    # A is linked by nobody (deg 0); B is linked by A (deg 1) -> B ranks first.
    assert rows == [("C/B", 1), ("C/A", 0)]
    assert (
        conn.execute("SELECT value FROM meta WHERE key='archive_uuid'").fetchone()[0]
        == "u1"
    )
    conn.close()


def test_build_rejects_self_links_and_dedups(tmp_path: Path) -> None:
    """Self-links are dropped and duplicate targets within a source collapse."""
    out = sidecar_path_for(tmp_path / "x.zim")

    def stream():
        yield ("C/A", ["C/A", "C/T", "C/T"])  # self-link + duplicate

    stats = build_from_link_stream(out, archive_uuid="u1", link_stream=stream())
    assert stats.edge_count == 1  # only A->T survives


def test_build_refuses_existing_without_force(tmp_path: Path) -> None:
    """Building over an existing sidecar without force raises FileExistsError."""
    out = sidecar_path_for(tmp_path / "x.zim")
    Path(out).write_text("existing")
    with pytest.raises(FileExistsError):
        build_from_link_stream(out, archive_uuid="u1", link_stream=iter([]))


def test_build_force_overwrites_atomically(tmp_path: Path) -> None:
    """force=True overwrites and leaves no temp file behind."""
    out = sidecar_path_for(tmp_path / "x.zim")
    Path(out).write_text("existing")
    build_from_link_stream(out, archive_uuid="u1", link_stream=iter([]), force=True)
    assert not Path(out + ".tmp").exists()
