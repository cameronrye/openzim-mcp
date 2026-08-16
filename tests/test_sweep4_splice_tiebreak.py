"""The canonical splice must not displace an equally exact title match.

Enabling the splice on new-scheme archives (sweep-4) exposed a case the
old-scheme gate had kept out of reach: archives that suffix every title
with the site name (``Plato | Internet Encyclopedia of Philosophy``).
There the only entry whose title matches a query *exactly* is whichever
page happens to carry a stripped title, so ``find_title_match`` hands
back a side page and the splice prepends it above the article the caller
actually asked for.

When a filtered result already carries the queried title, the splice's
goal — that title at rank 1 — is met, and BM25's ordering is the better
tiebreak between two entries claiming the same name.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from openzim_mcp.zim.namespace import _NamespaceMixin
from openzim_mcp.zim.search import _SearchMixin
from tests.test_sweep4_search import _FakeArchive

_LEGACY_SENTINEL = "<<LEGACY search_with_filters OUTPUT>>"


class _Stub(_SearchMixin):
    """Splice stand-in over a new-scheme archive with a suffixed corpus."""

    _canonicalise_namespace = staticmethod(_NamespaceMixin._canonicalise_namespace)

    def __init__(
        self,
        *,
        results: List[Dict[str, Any]],
        canonical: Dict[str, Any],
        query: str,
        validated: Path,
    ) -> None:
        self._results = results
        self._canonical = canonical
        self._query = query
        self._validated = validated
        self.legacy_calls: List[Dict[str, Any]] = []

        class _Content:
            default_search_limit = 10

        class _Config:
            content = _Content()

        self.config = _Config()  # type: ignore[assignment]

    def _validate_zim_path(self, zim_file_path: str) -> Path:  # type: ignore[override]
        return self._validated

    def search_with_filters(  # type: ignore[override]
        self, *args: Any, **kwargs: Any
    ) -> str:
        self.legacy_calls.append(kwargs)
        return _LEGACY_SENTINEL

    def search_with_filters_data(  # type: ignore[override]
        self, *_args: Any, **_kwargs: Any
    ) -> Dict[str, Any]:
        return {
            "query": self._query,
            "namespace_filter": "C",
            "content_type_filter": None,
            "results": self._results,
            "next_cursor": None,
            "total": len(self._results),
            "done": True,
            "page_info": {
                "offset": 0,
                "limit": 10,
                "returned_count": len(self._results),
            },
        }

    def find_entry_by_title_data(  # type: ignore[override]
        self, *_args: Any, **_kwargs: Any
    ) -> Dict[str, Any]:
        return {"results": [self._canonical]}


def _hit(path: str, title: str) -> Dict[str, Any]:
    return {
        "path": path,
        "title": title,
        "snippet": f"About {title}.",
        "namespace": "C",
        "content_type": "text/html",
    }


def _run(stub: _Stub, query: str, limit: Optional[int] = 10) -> str:
    archive = _FakeArchive({}, has_new_namespace_scheme=True)
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
        mock_archive.return_value.__enter__.return_value = archive
        return stub.search_with_filters_with_canonical_splice(
            "/x.zim", query, namespace="C", limit=limit, offset=0
        )


def test_splice_yields_to_an_equally_exact_title_already_on_the_page(
    temp_dir: Path,
) -> None:
    """``iep.utm.edu/meno-2/`` is titled "Plato"; it must not outrank the
    Plato article, which carries the same title under a site suffix."""
    zim_file = temp_dir / "iep.zim"
    zim_file.touch()
    stub = _Stub(
        results=[
            _hit("iep.utm.edu/plato/", "Plato | Internet Encyclopedia of Philosophy"),
            _hit(
                "iep.utm.edu/plato-org/",
                "Plato: Organicism | Internet Encyclopedia of Philosophy",
            ),
        ],
        canonical={"path": "iep.utm.edu/meno-2/", "title": "Plato", "score": 1.0},
        query="plato",
        validated=zim_file,
    )

    out = _run(stub, "plato")

    assert "## 1. Plato | Internet Encyclopedia of Philosophy" in out
    assert "iep.utm.edu/meno-2/" not in out


def test_splice_still_prepends_when_no_result_carries_the_queried_title(
    temp_dir: Path,
) -> None:
    """The splice's own purpose is untouched: a canonical the filtered
    page missed entirely still lands at rank 1."""
    zim_file = temp_dir / "iep.zim"
    zim_file.touch()
    stub = _Stub(
        results=[
            _hit(
                "iep.utm.edu/plato-org/",
                "Plato: Organicism | Internet Encyclopedia of Philosophy",
            )
        ],
        canonical={"path": "iep.utm.edu/meno-2/", "title": "Plato", "score": 1.0},
        query="plato",
        validated=zim_file,
    )

    out = _run(stub, "plato")

    assert "## 1. Plato" in out
    assert "iep.utm.edu/meno-2/" in out
    assert "Match type: canonical title match" in out


def test_splice_ignores_a_partial_title_overlap(temp_dir: Path) -> None:
    """A result merely *starting* with the query is not the queried title,
    so ``cats`` -> ``Cats (musical)`` must not suppress the ``Cat``
    canonical the splice exists to surface."""
    zim_file = temp_dir / "wiki.zim"
    zim_file.touch()
    stub = _Stub(
        results=[_hit("Cats_(musical)", "Cats (musical)")],
        canonical={"path": "Cat", "title": "Cat", "score": 1.0},
        query="cats",
        validated=zim_file,
    )

    out = _run(stub, "cats")

    assert "## 1. Cat" in out
    assert "Match type: canonical title match" in out
