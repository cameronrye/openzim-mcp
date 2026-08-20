"""Tests for the link-graph builder core (synthetic link streams)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, Optional
from unittest.mock import MagicMock

import pytest

from openzim_mcp.linkgraph.builder import build_from_link_stream, iter_article_links
from openzim_mcp.linkgraph.reader import sidecar_path_for


def _stream():
    # A->T, B->T, A->B  =>  T linked by {A,B}; B linked by {A}
    yield ("C/A", [("C/T", ""), ("C/B", "")])
    yield ("C/B", [("C/T", "")])
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
        yield ("C/A", [("C/A", ""), ("C/T", ""), ("C/T", "")])  # self-link + duplicate

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


class _FakeEntry:
    """Minimal stand-in for a libzim entry."""

    def __init__(self, path: str, html: str, is_redirect: bool = False) -> None:
        """Store the entry's path, HTML body, and redirect flag."""
        self.path = path
        self._html = html
        self.is_redirect = is_redirect

    def get_item(self) -> MagicMock:
        """Return an item whose ``.content`` is the encoded HTML bytes."""
        # Mirrors the real idiom: bytes(entry.get_item().content).decode(...)
        item = MagicMock()
        item.content = self._html.encode()
        return item


def test_iter_article_links_walks_content_entries() -> None:
    """Walk yields (source, internal targets) for C entries, skipping non-C + redirects."""
    # The href is relative to the source entry's directory (C/A lives in C/),
    # so "T" resolves to the canonical target path "C/T" — matching how real
    # ZIM HTML stores intra-namespace links.
    entries = [
        _FakeEntry("C/A", '<a href="T">t</a>'),
        _FakeEntry("M/Counter", "metadata"),  # non-content: skipped
        _FakeEntry("C/Redir", "", is_redirect=True),  # redirect: skipped as source
    ]
    archive = MagicMock()
    # Old-scheme archive: paths are namespace-prefixed (``C/``, ``M/``). A bare
    # MagicMock would auto-return a truthy ``has_new_namespace_scheme``, so set
    # it explicitly to exercise the old-scheme content filter.
    archive.has_new_namespace_scheme = False
    archive.entry_count = len(entries)
    archive._get_entry_by_id.side_effect = lambda i: entries[i]
    # _parse_internal_link_edges canonicalizes each target through the
    # redirect chain via archive.get_entry_by_path. With no such entry in
    # this fake archive the lookup raises and the path-normalized target
    # ("C/T") survives unchanged — the honest "target not found" path.
    archive.get_entry_by_path.side_effect = KeyError("no entry")

    pairs = list(iter_article_links(archive))
    assert ("C/A", [("C/T", "t")]) in pairs
    assert all(src.startswith("C/") for src, _ in pairs)
    assert not any(src == "C/Redir" for src, _ in pairs)


def test_iter_article_links_old_scheme_accepts_a_namespace() -> None:
    """Old-scheme A-namespace articles are content sources.

    Real pre-2020 ("withns") archives store articles under ``A/`` and have no
    ``C`` namespace at all; a C-only filter builds an empty sidecar for every
    such archive and inbound queries silently return zero.
    """
    entries = [
        _FakeEntry("A/Src", '<a href="Tgt">t</a>'),
        _FakeEntry("M/Counter", "metadata"),  # non-content: skipped
    ]
    archive = MagicMock()
    archive.has_new_namespace_scheme = False
    archive.entry_count = len(entries)
    archive._get_entry_by_id.side_effect = lambda i: entries[i]
    # No such entry for canonicalization -> path-normalized target survives.
    archive.get_entry_by_path.side_effect = KeyError("no entry")

    pairs = list(iter_article_links(archive))
    assert ("A/Src", [("A/Tgt", "t")]) in pairs
    assert not any(src == "M/Counter" for src, _ in pairs)


def test_build_link_graph_real_old_scheme_archive_is_nonempty(
    tmp_path: Path, real_content_zim_files: Dict[str, Optional[Path]]
) -> None:
    """Building against a real old-scheme (withns) archive yields nodes/edges."""
    from openzim_mcp.linkgraph.builder import build_link_graph

    archive_path = real_content_zim_files.get("wikibooks")
    if archive_path is None:
        pytest.skip("wikibooks withns test archive not available")

    out = str(tmp_path / "wikibooks.zim.linkgraph.sqlite")
    stats = build_link_graph(str(archive_path), out)
    assert stats.node_count > 0
    assert stats.edge_count > 0


def test_build_link_graph_warns_on_empty_result_for_nonempty_archive(
    tmp_path: Path,
    basic_test_zim_files: Dict[str, Optional[Path]],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A non-empty archive that builds to zero nodes logs a warning."""
    import logging

    import openzim_mcp.linkgraph.builder as builder_module

    archive_path = basic_test_zim_files.get("withns")
    if archive_path is None:
        pytest.skip("withns small.zim test archive not available")

    monkeypatch.setattr(builder_module, "iter_article_links", lambda archive: iter([]))
    out = str(tmp_path / "small.zim.linkgraph.sqlite")
    with caplog.at_level(logging.WARNING, logger="openzim_mcp.linkgraph.builder"):
        stats = builder_module.build_link_graph(str(archive_path), out)
    assert stats.node_count == 0
    assert any("0 nodes" in rec.message for rec in caplog.records)


def test_iter_article_links_new_scheme_has_no_prefix() -> None:
    """New-scheme entries carry no namespace prefix; all are content sources.

    In new-scheme ZIMs libzim's iterable surface IS the C namespace, and entry
    paths have no prefix (``Evolution`` not ``C/Evolution``). The walk must
    accept every prefix-less entry as a content source and still skip
    redirects — the old ``startswith("C/")`` filter dropped them all.
    """
    # href "Photosynthesis" is relative to the source entry's directory (root),
    # so it path-normalizes to "Photosynthesis" — the prefix-less canonical
    # target form libzim returns for new-scheme content.
    entries = [
        _FakeEntry("Evolution", '<a href="Photosynthesis">p</a>'),
        _FakeEntry("Redir", "", is_redirect=True),  # redirect: skipped as source
    ]
    archive = MagicMock()
    archive.has_new_namespace_scheme = True
    archive.entry_count = len(entries)
    archive._get_entry_by_id.side_effect = lambda i: entries[i]
    # No such entry for canonicalization -> path-normalized target survives.
    archive.get_entry_by_path.side_effect = KeyError("no entry")

    pairs = list(iter_article_links(archive))
    assert ("Evolution", [("Photosynthesis", "p")]) in pairs
    assert all(not src.startswith("C/") for src, _ in pairs)
    assert not any(src == "Redir" for src, _ in pairs)


def test_builder_writes_anchor_text_and_builder_version(tmp_path: Path) -> None:
    """Builder stores anchor_text per edge and writes a builder_version meta row."""
    import openzim_mcp

    out = str(tmp_path / "a.zim.linkgraph.sqlite")
    stream = [("A/Src", [("A/Tgt", "see Tgt")])]
    build_from_link_stream(out, archive_uuid="uuid-1", link_stream=iter(stream))

    conn = sqlite3.connect(out)
    anchors = conn.execute("SELECT anchor_text FROM edges").fetchall()
    assert anchors == [("see Tgt",)]
    meta = dict(conn.execute("SELECT key, value FROM meta"))
    assert meta["builder_version"] == openzim_mcp.__version__
    assert meta["schema_version"] == "3"
    conn.close()
