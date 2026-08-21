"""Sweep-4 regression tests for ``openzim_mcp.zim.search``.

Three defects, each pinned by the smallest end-to-end assertion that
distinguishes the fixed behavior from the old one:

1. ``search_zim_file_data`` built its zero-hit ``alt_spelling`` pool from
   the path basename, which is empty / opaque on URL-pathed (zimit,
   warc2zim) archives.
2. ``search_with_filters_with_canonical_splice``'s namespace gate parsed a
   namespace out of the canonical path without consulting
   ``has_new_namespace_scheme``, so the splice was dead on every
   new-scheme archive with hierarchical paths.
3. ``_canonical_via_shortest_title`` filtered already-present rows out
   BEFORE taking the minimum, so it promoted a longer non-canonical title
   instead of concluding the canonical was already on the page.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim.namespace import _NamespaceMixin
from openzim_mcp.zim.search import _SearchMixin
from openzim_mcp.zim_operations import ZimOperations


class _FakeEntry:
    """Minimal libzim ``Entry`` stand-in (title + path only)."""

    def __init__(self, path: str, title: str) -> None:
        self.path = path
        self.title = title


class _FakeArchive:
    """Archive stand-in exposing just the surface the probes read."""

    def __init__(
        self,
        entries: Dict[str, str],
        *,
        has_new_namespace_scheme: bool = True,
    ) -> None:
        self._entries = entries
        self.has_fulltext_index = True
        self.has_new_namespace_scheme = has_new_namespace_scheme

    def has_entry_by_path(self, path: str) -> bool:
        return path in self._entries

    def get_entry_by_path(self, path: str) -> _FakeEntry:
        if path not in self._entries:
            raise KeyError(path)
        return _FakeEntry(path, self._entries[path])


@pytest.fixture
def ops(
    test_config: OpenZimMcpConfig,
    path_validator: PathValidator,
    openzim_mcp_cache: OpenZimMcpCache,
    content_processor: ContentProcessor,
) -> ZimOperations:
    return ZimOperations(
        test_config, path_validator, openzim_mcp_cache, content_processor
    )


# ---------------------------------------------------------------------------
# Finding 1: zero-hit alt_spelling suggestions built from the path basename.
# ---------------------------------------------------------------------------


def _zero_hit_suggestions(
    ops: ZimOperations,
    zim_file: Path,
    query: str,
    entries: Dict[str, str],
    candidate_paths: List[str],
) -> List[Dict[str, str]]:
    """Run ``search_zim_file_data`` with 0 Xapian hits and the given
    SuggestionSearcher candidates; return the ``_meta`` suggestions."""
    archive = _FakeArchive(entries)

    zero_search = MagicMock()
    zero_search.getEstimatedMatches.return_value = 0

    sugg = MagicMock()
    sugg.getResults.return_value = list(candidate_paths)

    with (
        patch("openzim_mcp.zim_operations.zim_archive") as mock_archive,
        patch("openzim_mcp.zim_operations.Searcher") as mock_searcher_cls,
        patch("openzim_mcp.zim_operations.Query"),
        patch("openzim_mcp.zim_operations.SuggestionSearcher") as mock_sugg_cls,
    ):
        mock_archive.return_value.__enter__.return_value = archive
        mock_searcher_cls.return_value.search.return_value = zero_search
        mock_sugg_cls.return_value.suggest.return_value = sugg
        out = ops.search_zim_file_data(str(zim_file), query, limit=5, offset=0)

    assert out["_meta"]["reason"] == "0_hits"
    return list(out["_meta"].get("suggestions") or [])


def test_alt_spelling_uses_entry_titles_for_url_paths(
    ops: ZimOperations, temp_dir: Path
) -> None:
    """warc2zim paths end in ``/``, so the basename is the empty string:
    the first ``""`` poisoned the dedup set and collapsed the whole pool
    to one useless ``{"value": ""}``."""
    zim_file = temp_dir / "iep.zim"
    zim_file.touch()
    entries = {
        "iep.utm.edu/aristotle/": "Aristotle",
        "iep.utm.edu/aristippus/": "Aristippus",
    }
    suggestions = _zero_hit_suggestions(
        ops, zim_file, "Aristotl", entries, list(entries)
    )

    assert suggestions == [
        {"type": "alt_spelling", "value": "Aristotle"},
        {"type": "alt_spelling", "value": "Aristippus"},
    ]


def test_alt_spelling_uses_entry_titles_for_filename_paths(
    ops: ZimOperations, temp_dir: Path
) -> None:
    """Opaque filenames (``a682878.html``) are not re-issuable as a query;
    the entry's real title is."""
    zim_file = temp_dir / "medline.zim"
    zim_file.touch()
    entries = {
        "medlineplus.gov/druginfo/meds/a682878.html": "Aspirin",
        "medlineplus.gov/druginfo/meds/a621021.html": "Aspirin and Omeprazole",
    }
    suggestions = _zero_hit_suggestions(ops, zim_file, "aspiri", entries, list(entries))

    assert [s["value"] for s in suggestions] == [
        "Aspirin",
        "Aspirin and Omeprazole",
    ]


def test_alt_spelling_falls_back_to_path_segment_when_title_unresolvable(
    ops: ZimOperations, temp_dir: Path
) -> None:
    """Old-scheme ``C/Title`` paths whose entry can't be resolved keep the
    humanized last non-empty path segment."""
    zim_file = temp_dir / "wiki.zim"
    zim_file.touch()
    suggestions = _zero_hit_suggestions(
        ops,
        zim_file,
        "Photosyn",
        {},  # no entry resolves
        ["C/Photosynthesis", "C/Photosynthesis_(song)"],
    )

    assert [s["value"] for s in suggestions] == [
        "Photosynthesis",
        "Photosynthesis (song)",
    ]


def test_alt_spelling_skips_candidates_with_no_usable_value(
    ops: ZimOperations, temp_dir: Path
) -> None:
    """A candidate that resolves to neither a title nor a usable path
    segment is dropped instead of emitting an empty suggestion."""
    zim_file = temp_dir / "empty.zim"
    zim_file.touch()
    suggestions = _zero_hit_suggestions(
        ops,
        zim_file,
        "Aristotl",
        {"iep.utm.edu/aristotle/": "Aristotle"},
        ["/", "iep.utm.edu/aristotle/"],
    )

    assert suggestions == [{"type": "alt_spelling", "value": "Aristotle"}]


# ---------------------------------------------------------------------------
# Finding 2: canonical splice namespace gate ignores the archive's scheme.
# ---------------------------------------------------------------------------

_LEGACY_SENTINEL = "<<LEGACY search_with_filters OUTPUT>>"


class _SpliceStub(_SearchMixin):
    """``_SearchMixin`` stand-in that records legacy delegation."""

    _canonicalise_namespace = staticmethod(_NamespaceMixin._canonicalise_namespace)

    def __init__(self, *, canonical_path: str, validated: Optional[Path]) -> None:
        self._canonical_path = canonical_path
        self._validated = validated
        self.legacy_calls: List[Dict[str, Any]] = []

        class _Content:
            default_search_limit = 10

        class _Config:
            content = _Content()

        self.config = _Config()  # type: ignore[assignment]

    def _validate_zim_path(self, zim_file_path: str) -> Path:  # type: ignore[override]
        if self._validated is None:
            raise OSError("unresolvable")
        return self._validated

    def search_with_filters(  # type: ignore[override]
        self,
        zim_file_path: str,
        query: str,
        namespace: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        display_query: Optional[str] = None,
    ) -> str:
        self.legacy_calls.append({"namespace": namespace, "limit": limit})
        return _LEGACY_SENTINEL

    def search_with_filters_data(  # type: ignore[override]
        self, *_args: Any, **_kwargs: Any
    ) -> Dict[str, Any]:
        return {
            "query": "plato",
            "namespace_filter": "C",
            "content_type_filter": None,
            "results": [],
            "next_cursor": None,
            "total": 0,
            "done": True,
            "page_info": {"offset": 0, "limit": 10, "returned_count": 0},
        }

    def find_entry_by_title_data(  # type: ignore[override]
        self, *_args: Any, **_kwargs: Any
    ) -> Dict[str, Any]:
        return {
            "results": [{"path": self._canonical_path, "title": "Plato", "score": 1.0}]
        }


def test_splice_gate_treats_new_scheme_paths_as_namespace_c(temp_dir: Path) -> None:
    """``iep.utm.edu/meno-2/`` is namespace C on a new-scheme archive —
    the same verdict ``_matches_cheap_namespace`` gives it — so the
    canonical must splice instead of falling through to the legacy path.
    """
    zim_file = temp_dir / "iep.zim"
    zim_file.touch()
    stub = _SpliceStub(canonical_path="iep.utm.edu/meno-2/", validated=zim_file)
    archive = _FakeArchive({}, has_new_namespace_scheme=True)

    with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
        mock_archive.return_value.__enter__.return_value = archive
        out = stub.search_with_filters_with_canonical_splice(
            "/x.zim", "plato", namespace="C", limit=3, offset=0
        )

    assert stub.legacy_calls == []
    assert out != _LEGACY_SENTINEL
    assert "Match type: canonical title match" in out


def test_splice_gate_still_rejects_old_scheme_foreign_namespace(
    temp_dir: Path,
) -> None:
    """Old-scheme archives keep the ``X/`` prefix convention: an ``M/``
    canonical must NOT splice into a namespace-C search."""
    zim_file = temp_dir / "wiki.zim"
    zim_file.touch()
    stub = _SpliceStub(canonical_path="M/Plato", validated=zim_file)
    archive = _FakeArchive({}, has_new_namespace_scheme=False)

    with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
        mock_archive.return_value.__enter__.return_value = archive
        out = stub.search_with_filters_with_canonical_splice(
            "/x.zim", "plato", namespace="C", limit=3, offset=0
        )

    assert out == _LEGACY_SENTINEL
    assert len(stub.legacy_calls) == 1


def test_splice_gate_falls_back_to_path_prefix_when_archive_unreadable() -> None:
    """An unopenable archive degrades to the historical path-prefix
    derivation rather than blanket-admitting the canonical."""
    stub = _SpliceStub(canonical_path="M/Plato", validated=None)
    out = stub.search_with_filters_with_canonical_splice(
        "/x.zim", "plato", namespace="C", limit=3, offset=0
    )
    assert out == _LEGACY_SENTINEL


# ---------------------------------------------------------------------------
# Finding 3: shortest-title canonical probe promotes a non-canonical row.
# ---------------------------------------------------------------------------


class _ProbeStub(_SearchMixin):
    """Bare ``_SearchMixin`` for exercising the canonical prefix probe."""


def _probe(
    entries: Dict[str, str],
    partial: str,
    existing: List[Dict[str, str]],
) -> Optional[Dict[str, str]]:
    stub = _ProbeStub()
    archive = _FakeArchive(entries)
    return stub._find_canonical_prefix_match(
        archive,  # type: ignore[arg-type]
        partial,
        existing,
        result_paths=list(entries),
    )


def test_probe_returns_none_when_shortest_prefix_title_already_present() -> None:
    """``Aristotle`` (47 ch) is already on the page, so the canonical gap
    the probe exists to fill is closed — it must not promote the longer
    ``Aristippus`` above it."""
    entries = {
        "iep.utm.edu/aristotle/": "Aristotle | Internet Encyclopedia of Philosophy",
        "iep.utm.edu/aristippus/": "Aristippus | Internet Encyclopedia of Philosophy",
    }
    existing = [
        {
            "text": "Aristotle | Internet Encyclopedia of Philosophy",
            "path": "iep.utm.edu/aristotle/",
            "type": "title_start_match",
        }
    ]
    assert _probe(entries, "Aris", existing) is None


def test_probe_still_promotes_when_canonical_is_absent() -> None:
    """The probe's actual job is unaffected: when the shortest
    prefix-matching title is missing from the page, promote it."""
    entries = {
        "Photosynthesis": "Photosynthesis",
        "Photosynthetic_efficiency": "Photosynthetic efficiency",
    }
    existing = [
        {
            "text": "Photosynthetic efficiency",
            "path": "Photosynthetic_efficiency",
            "type": "title_start_match",
        }
    ]
    canonical = _probe(entries, "Photosyn", existing)
    assert canonical == {
        "text": "Photosynthesis",
        "path": "Photosynthesis",
        "type": "title_start_match",
    }


def test_suggestions_page_keeps_last_genuine_row_when_canonical_present() -> None:
    """End-to-end consequence: a full page no longer loses its lowest
    genuine suggestion to a spurious rank-1 promotion."""
    entries = {
        "iep.utm.edu/kant/": "Kant, Immanuel",
        "iep.utm.edu/kantaest/": "Kant: Aesthetics",
        "iep.utm.edu/kantmeta/": "Kant: Metaphysics",
        "iep.utm.edu/kantmind/": "Kant: Philosophy of Mind",
        "iep.utm.edu/k-logic/": "Kant: Logic and Judgement",
        "iep.utm.edu/kantview/": "Kant's Views on Space",
    }
    page = [
        {"text": title, "path": path, "type": "title_start_match"}
        for path, title in list(entries.items())[:5]
    ]

    class _Stub(_SearchMixin):
        def _get_suggestions_from_search(  # type: ignore[override]
            self, archive: Any, partial_query: str, limit: int
        ) -> List[Dict[str, Any]]:
            return [dict(row) for row in page]

    stub = _Stub()
    archive: Any = _FakeArchive(entries)
    with patch("openzim_mcp.zim_operations.SuggestionSearcher") as mock_sugg_cls:
        sugg = MagicMock()
        sugg.getEstimatedMatches.return_value = len(entries)
        sugg.getResults.return_value = list(entries)
        mock_sugg_cls.return_value.suggest.return_value = sugg
        out = stub._generate_search_suggestions(archive, "Kant", 5)

    texts = [s["text"] for s in out["suggestions"]]
    assert texts == [row["text"] for row in page]
