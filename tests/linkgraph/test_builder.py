"""Tests for the link-graph builder core (synthetic link streams)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openzim_mcp.linkgraph.builder import build_from_link_stream, iter_article_links
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
    # _parse_internal_link_targets canonicalizes each target through the
    # redirect chain via archive.get_entry_by_path. With no such entry in
    # this fake archive the lookup raises and the path-normalized target
    # ("C/T") survives unchanged — the honest "target not found" path.
    archive.get_entry_by_path.side_effect = KeyError("no entry")

    pairs = list(iter_article_links(archive))
    assert ("C/A", ["C/T"]) in pairs
    assert all(src.startswith("C/") for src, _ in pairs)
    assert not any(src == "C/Redir" for src, _ in pairs)


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
    assert ("Evolution", ["Photosynthesis"]) in pairs
    assert all(not src.startswith("C/") for src, _ in pairs)
    assert not any(src == "Redir" for src, _ in pairs)
