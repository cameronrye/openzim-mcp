"""Tests for ``_StructureMixin.get_inbound_links_data`` (reads a real sidecar).

A real sidecar is built via ``build_from_link_stream``; the archive-open and
path-validation seams are stubbed so no real ZIM is needed. The archive-open
context manager is monkeypatched to yield a ``MagicMock`` whose ``.uuid``
matches the sidecar's built-in UUID, so ``LinkGraphReader.open_for``'s
fingerprint check passes. ``get_entry_by_path`` raises so title resolution
falls back to the path (keeping ``title == path`` deterministic).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, List, Tuple, cast
from unittest.mock import MagicMock

import pytest

import openzim_mcp.zim.structure as structure_mod
from openzim_mcp.linkgraph.builder import build_from_link_stream
from openzim_mcp.linkgraph.reader import LinkGraphUnavailable, sidecar_path_for
from openzim_mcp.zim.structure import _StructureMixin


class _StubSelf:
    """A minimal ``self`` exposing only the seams the method calls.

    ``_validate_zim_path`` echoes the archive path; ``_resolve_outbound_titles``
    is the real (static) implementation, which is harmless because the patched
    archive's ``get_entry_by_path`` raises (titles stay at their path fallback).
    """

    def __init__(self, archive_path: Path) -> None:
        self._archive_path = archive_path

    def _validate_zim_path(self, zim_file_path: str) -> Path:
        return self._archive_path

    _resolve_outbound_titles = staticmethod(_StructureMixin._resolve_outbound_titles)


def _stub_self(archive_path: Path) -> _StructureMixin:
    """Build a stub ``self`` carrying the method's required seams."""
    return cast(_StructureMixin, _StubSelf(archive_path))


def _patch_archive_open(monkeypatch: pytest.MonkeyPatch, *, uuid: str) -> None:
    """Patch the module-level archive-open to yield a MagicMock with ``.uuid``.

    ``get_entry_by_path`` raises so title resolution falls back to path.
    """
    archive = MagicMock()
    archive.uuid = uuid
    archive.get_entry_by_path.side_effect = RuntimeError("no real archive")

    class _Ctx:
        def __enter__(self) -> MagicMock:
            return archive

        def __exit__(self, *a: object) -> bool:
            return False

    monkeypatch.setattr(
        structure_mod._zim_ops_mod,
        "zim_archive",
        lambda *_a, **_kw: _Ctx(),
    )


def _build_sidecar(
    archive_path: Path,
    *,
    uuid: str,
    stream: List[Tuple[str, List[Tuple[str, str]]]],
) -> None:
    """Build a real sidecar next to ``archive_path`` from a synthetic stream."""

    def _iter() -> Iterator[Tuple[str, List[Tuple[str, str]]]]:
        yield from stream

    build_from_link_stream(
        sidecar_path_for(archive_path),
        archive_uuid=uuid,
        link_stream=_iter(),
    )


def test_inbound_returns_ranked_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T linked by A and B; A outranks B by inbound_degree → A first."""
    archive = tmp_path / "x.zim"
    # A->T, B->T, A->B, B->A so A has inbound_degree 1 and B has 1; give A a
    # second inbound (C->A) so A outranks B.
    _build_sidecar(
        archive,
        uuid="u1",
        stream=[
            ("C/A", [("C/T", "")]),
            ("C/B", [("C/T", "")]),
            ("C/C1", [("C/A", "")]),
            ("C/C2", [("C/A", "")]),
            ("C/C3", [("C/B", "")]),
        ],
    )
    _patch_archive_open(monkeypatch, uuid="u1")

    result = _StructureMixin.get_inbound_links_data(
        _stub_self(archive), str(archive), "C/T", limit=10, offset=0
    )

    assert result["entry_path"] == "C/T"
    assert [r["path"] for r in result["results"]] == ["C/A", "C/B"]
    assert result["results"][0]["inbound_degree"] == 2
    assert result["results"][1]["inbound_degree"] == 1
    # Title falls back to path since the stubbed archive lookup raises.
    assert result["results"][0]["title"] == "C/A"
    assert result["total"] == 2
    assert result["done"] is True
    assert result["next_cursor"] is None


def test_inbound_missing_sidecar_raises_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No sidecar built → LinkGraphUnavailable."""
    archive = tmp_path / "x.zim"
    _patch_archive_open(monkeypatch, uuid="u1")

    with pytest.raises(LinkGraphUnavailable):
        _StructureMixin.get_inbound_links_data(
            _stub_self(archive), str(archive), "C/T", limit=10, offset=0
        )


def test_inbound_paginates_emits_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A short limit emits a non-None cursor and done=False; full page closes."""
    archive = tmp_path / "x.zim"
    _build_sidecar(
        archive,
        uuid="u1",
        stream=[
            ("C/A", [("C/T", "")]),
            ("C/B", [("C/T", "")]),
        ],
    )
    _patch_archive_open(monkeypatch, uuid="u1")

    first = _StructureMixin.get_inbound_links_data(
        _stub_self(archive), str(archive), "C/T", limit=1, offset=0
    )
    assert first["total"] == 2
    assert len(first["results"]) == 1
    assert first["done"] is False
    assert first["next_cursor"] is not None

    full = _StructureMixin.get_inbound_links_data(
        _stub_self(archive), str(archive), "C/T", limit=10, offset=0
    )
    assert len(full["results"]) == 2
    assert full["done"] is True
    assert full["next_cursor"] is None
