"""Inbound lookup keys must name the same entry the sidecar builder indexed.

These exercise a real (tiny) archive rather than a ``MagicMock`` because the
defects they pin only appear against real libzim lookup semantics: libzim
resolves a namespace-prefixed spelling leniently (``C/main.html`` returns the
entry stored as ``main.html``), so a mock archive keyed on exact strings
cannot reproduce the divergence between the caller's spelling and the
builder's index key.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, cast

import pytest

from openzim_mcp.exceptions import OpenZimMcpArchiveError
from openzim_mcp.linkgraph.builder import build_from_link_stream
from openzim_mcp.linkgraph.reader import sidecar_path_for
from openzim_mcp.zim.structure import _StructureMixin


class _StubSelf:
    """A minimal ``self`` exposing only the seams the method calls."""

    def __init__(self, archive_path: Path) -> None:
        self._archive_path = archive_path

    def _validate_zim_path(self, zim_file_path: str) -> Path:
        return self._archive_path

    _resolve_outbound_titles = staticmethod(_StructureMixin._resolve_outbound_titles)


@pytest.fixture
def small_archive(zim_test_data_dir: Optional[Path], tmp_path: Path) -> Path:
    """A private copy of the nons ``small.zim`` (the sidecar lands beside it)."""
    if zim_test_data_dir is None:
        pytest.skip("test ZIM corpus absent")
    source = zim_test_data_dir / "nons" / "small.zim"
    if not source.exists():
        pytest.skip("test ZIM corpus absent")
    target = tmp_path / "small.zim"
    shutil.copy(source, target)
    return target


def _build_sidecar(
    archive_path: Path, stream: List[Tuple[str, List[Tuple[str, str]]]]
) -> None:
    """Build a real sidecar next to ``archive_path`` from a synthetic stream."""
    from libzim.reader import Archive

    def _iter() -> Iterator[Tuple[str, List[Tuple[str, str]]]]:
        yield from stream

    build_from_link_stream(
        sidecar_path_for(archive_path),
        archive_uuid=str(Archive(str(archive_path)).uuid),
        link_stream=_iter(),
    )


def _inbound(archive_path: Path, entry_path: str) -> Dict[str, Any]:
    return dict(
        _StructureMixin.get_inbound_links_data(
            cast(_StructureMixin, _StubSelf(archive_path)),
            str(archive_path),
            entry_path,
            limit=10,
            offset=0,
        )
    )


class TestInboundLookupKey:
    """The lookup key follows the entry libzim serves, not the caller's spelling."""

    def test_stored_spelling_finds_the_linker(self, small_archive: Path) -> None:
        _build_sidecar(small_archive, [("index.html", [("main.html", "Main")])])

        assert _inbound(small_archive, "main.html")["total"] == 1

    def test_namespace_prefixed_spelling_finds_the_same_linker(
        self, small_archive: Path
    ) -> None:
        """``C/main.html`` and ``main.html`` are one entry to libzim."""
        _build_sidecar(small_archive, [("index.html", [("main.html", "Main")])])

        assert _inbound(small_archive, "C/main.html")["total"] == 1

    def test_namespace_prefixed_spelling_reports_the_canonical_path(
        self, small_archive: Path
    ) -> None:
        _build_sidecar(small_archive, [("index.html", [("main.html", "Main")])])

        result = _inbound(small_archive, "C/main.html")

        assert result["resolved_path"] == "main.html"

    def test_canonical_target_path_agrees_with_the_builder(
        self, small_archive: Path
    ) -> None:
        """The outbound/related ``path`` is the key the sidecar indexes under."""
        from openzim_mcp.zim.archive import zim_archive

        with zim_archive(small_archive) as archive:
            canonical = _StructureMixin._canonical_target_path(archive, "C/main.html")
            edges = _StructureMixin._parse_internal_link_edges(
                '<a href="C/main.html">Main</a>',
                source_path="index.html",
                archive=archive,
            )

        assert canonical == edges[0][0]


class TestInboundExistenceGate:
    """Not-found is for targets nothing knows about, not for dangling ones."""

    def test_dangling_target_still_lists_its_linkers(self, small_archive: Path) -> None:
        """Red links are indexed on purpose; "what links here" must still answer."""
        _build_sidecar(
            small_archive, [("index.html", [("missing_page.html", "Missing")])]
        )

        assert _inbound(small_archive, "missing_page.html")["total"] == 1

    def test_dangling_target_names_its_linker(self, small_archive: Path) -> None:
        _build_sidecar(
            small_archive, [("index.html", [("missing_page.html", "Missing")])]
        )

        result = _inbound(small_archive, "missing_page.html")

        assert result["results"][0]["path"] == "index.html"

    def test_unknown_target_raises_not_found(self, small_archive: Path) -> None:
        """Neither the archive nor the sidecar knows it -> still a hard miss."""
        _build_sidecar(small_archive, [("index.html", [("main.html", "Main")])])

        with pytest.raises(OpenZimMcpArchiveError, match="Entry not found"):
            _inbound(small_archive, "nowhere.html")
