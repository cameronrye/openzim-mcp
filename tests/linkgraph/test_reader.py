"""Tests for LinkGraphReader (built against a hand-made sidecar)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from openzim_mcp.linkgraph.reader import LinkGraphReader, sidecar_path_for
from openzim_mcp.linkgraph.schema import SCHEMA_VERSION, create_schema


def _make_sidecar(archive: Path, *, uuid: str, schema_version: int = SCHEMA_VERSION):
    """Build a minimal sidecar: target T has linkers A(deg2), B(deg1)."""
    conn = sqlite3.connect(sidecar_path_for(archive))
    create_schema(conn)
    conn.executemany(
        "INSERT INTO nodes(id, path, inbound_degree) VALUES (?,?,?)",
        [(1, "C/T", 0), (2, "C/A", 2), (3, "C/B", 1)],
    )
    conn.executemany(
        "INSERT INTO edges(target_id, source_id) VALUES (?,?)",
        [(1, 2), (1, 3)],  # A->T, B->T
    )
    conn.executemany(
        "INSERT INTO meta(key, value) VALUES (?,?)",
        [("schema_version", str(schema_version)), ("archive_uuid", uuid)],
    )
    conn.commit()
    conn.close()


def test_sidecar_path_is_sibling(tmp_path: Path) -> None:
    """Sidecar path is the archive path + .linkgraph.sqlite."""
    archive = tmp_path / "wikipedia.zim"
    assert sidecar_path_for(archive) == str(tmp_path / "wikipedia.zim.linkgraph.sqlite")


def test_open_for_returns_none_when_absent(tmp_path: Path) -> None:
    """A missing sidecar yields None."""
    archive = tmp_path / "x.zim"
    assert LinkGraphReader.open_for(str(archive), live_archive_uuid="u1") is None


def test_open_for_returns_none_on_uuid_mismatch(tmp_path: Path) -> None:
    """A sidecar built for a different archive UUID yields None."""
    archive = tmp_path / "x.zim"
    archive.write_bytes(b"")
    _make_sidecar(archive, uuid="built-uuid")
    assert LinkGraphReader.open_for(str(archive), live_archive_uuid="other") is None


def test_open_for_returns_none_on_schema_mismatch(tmp_path: Path) -> None:
    """A sidecar with a different schema version yields None."""
    archive = tmp_path / "x.zim"
    archive.write_bytes(b"")
    _make_sidecar(archive, uuid="u1", schema_version=SCHEMA_VERSION + 99)
    assert LinkGraphReader.open_for(str(archive), live_archive_uuid="u1") is None


def test_query_inbound_ranks_by_degree_then_path(tmp_path: Path) -> None:
    """Inbound linkers are ordered by inbound_degree desc, then path."""
    archive = tmp_path / "x.zim"
    archive.write_bytes(b"")
    _make_sidecar(archive, uuid="u1")
    reader = LinkGraphReader.open_for(str(archive), live_archive_uuid="u1")
    assert reader is not None
    page = reader.query_inbound("C/T", limit=10, offset=0)
    assert [r["path"] for r in page.rows] == ["C/A", "C/B"]
    assert page.rows[0]["inbound_degree"] == 2
    assert page.total == 2
    reader.close()


def test_query_inbound_paginates(tmp_path: Path) -> None:
    """Limit/offset slice the ranked inbound list; total is unpaginated."""
    archive = tmp_path / "x.zim"
    archive.write_bytes(b"")
    _make_sidecar(archive, uuid="u1")
    reader = LinkGraphReader.open_for(str(archive), live_archive_uuid="u1")
    assert reader is not None
    page = reader.query_inbound("C/T", limit=1, offset=1)
    assert [r["path"] for r in page.rows] == ["C/B"]
    assert page.total == 2
    reader.close()


def test_open_for_handles_archive_path_with_spaces(tmp_path: Path) -> None:
    """A valid sidecar opens even when the archive path contains a space."""
    spaced = tmp_path / "My Archives"
    spaced.mkdir()
    archive = spaced / "wiki test.zim"
    archive.write_bytes(b"")
    _make_sidecar(archive, uuid="u1")
    reader = LinkGraphReader.open_for(str(archive), live_archive_uuid="u1")
    assert reader is not None
    assert reader.query_inbound("C/T", limit=10, offset=0).total == 2
    reader.close()


def test_query_inbound_unknown_target_is_empty_not_error(tmp_path: Path) -> None:
    """An unknown target returns an empty page, not an error."""
    archive = tmp_path / "x.zim"
    archive.write_bytes(b"")
    _make_sidecar(archive, uuid="u1")
    reader = LinkGraphReader.open_for(str(archive), live_archive_uuid="u1")
    assert reader is not None
    page = reader.query_inbound("C/Nonexistent", limit=10, offset=0)
    assert page.rows == [] and page.total == 0
    reader.close()


def test_query_inbound_includes_anchor_text(tmp_path: Path) -> None:
    """Row dicts include anchor_text from the edge that linked to the target."""
    import sqlite3 as _sqlite3

    from openzim_mcp.linkgraph.builder import build_from_link_stream

    out = str(tmp_path / "a.zim.linkgraph.sqlite")
    stream = [("A/Src", [("A/Tgt", "anchor for tgt")])]
    build_from_link_stream(out, archive_uuid="u", link_stream=iter(stream))
    reader = LinkGraphReader(_sqlite3.connect(out))
    try:
        page = reader.query_inbound("A/Tgt", limit=10, offset=0)
    finally:
        reader.close()
    assert page.total == 1
    assert page.rows[0]["path"] == "A/Src"
    assert page.rows[0]["anchor_text"] == "anchor for tgt"
