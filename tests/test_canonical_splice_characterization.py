"""Characterization tests for
``_SearchMixin.search_with_filters_with_canonical_splice``.

Added ahead of the Tier-3 method-decomposition refactor (Task 3.3) to
pin the observable OUTPUT of every guard / splice branch BEFORE the
228-line method is decomposed into a ``_delegate`` closure plus a
``_splice_canonical_into_filtered`` helper. Behavior must stay
byte-identical, so each test asserts on the rendered string the method
returns (or the exact delegation it performs), not on internal shape.

Pre-existing coverage (see test_post_a11_beta_fixes ::
``test_filtered_search_empty_xapian_still_surfaces_canonical`` and
test_post_a16_beta_fixes :: ``test_splice_reorder_path_renders_without_crash``)
exercised only the empty-results and the reorder sub-branches of the
splice body. The four early-return delegation gates (``offset != 0``,
``canonical is None``, namespace-prefix mismatch, ``content_type`` set)
and the synthetic-prepend splice sub-branch had NO direct coverage —
those are what these tests lock down.
"""

from typing import Any, Dict, List, Optional
from unittest.mock import patch

from openzim_mcp.zim.search import _SearchMixin

# A delegation sentinel the stub's ``search_with_filters`` returns so a
# test can assert the splice method bailed to the legacy path verbatim.
_LEGACY_SENTINEL = "<<LEGACY search_with_filters OUTPUT>>"


class _SpliceStub(_SearchMixin):
    """Minimal ``_SearchMixin`` stand-in exercising the production
    splice / render path with mocked I/O hooks.

    - ``search_with_filters`` returns a sentinel and records the args it
      was called with, so delegation gates are observable AND the
      ``limit`` value seen at call time can be asserted.
    - ``search_with_filters_data`` returns a caller-supplied payload.
    - ``find_entry_by_title_data`` feeds ``find_title_match`` (module
      function under ``openzim_mcp.zim.search``).
    """

    def __init__(
        self,
        *,
        data_payload: Optional[Dict[str, Any]] = None,
        title_results: Optional[List[Dict[str, Any]]] = None,
        default_search_limit: int = 10,
    ) -> None:
        self._data_payload = data_payload or {
            "query": "berlin",
            "namespace_filter": None,
            "content_type_filter": None,
            "results": [],
            "next_cursor": None,
            "total": 0,
            "done": True,
            "page_info": {"offset": 0, "limit": 10, "returned_count": 0},
        }
        self._title_results = title_results
        self.legacy_calls: List[Dict[str, Any]] = []

        # ``self.config.content.default_search_limit`` — only read on the
        # ``limit is None`` default path.
        class _Content:
            pass

        class _Config:
            pass

        content = _Content()
        content.default_search_limit = default_search_limit  # type: ignore[attr-defined]
        cfg = _Config()
        cfg.content = content  # type: ignore[attr-defined]
        self.config = cfg  # type: ignore[assignment]

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
        self.legacy_calls.append(
            {
                "zim_file_path": zim_file_path,
                "query": query,
                "namespace": namespace,
                "content_type": content_type,
                "limit": limit,
                "offset": offset,
                "display_query": display_query,
            }
        )
        return _LEGACY_SENTINEL

    def search_with_filters_data(  # type: ignore[override]
        self, *_args: Any, **_kwargs: Any
    ) -> Dict[str, Any]:
        return self._data_payload

    def find_entry_by_title_data(  # type: ignore[override]
        self, *_args: Any, **_kwargs: Any
    ) -> Dict[str, Any]:
        return {"results": self._title_results or []}


def _berlin_title_results() -> List[Dict[str, Any]]:
    return [{"path": "Berlin", "title": "Berlin", "score": 1.0}]


class TestCanonicalSpliceDelegationGates:
    """The four early-return guards each delegate to the legacy
    ``search_with_filters`` with an identical 7-arg call and perform NO
    splice. These were uncovered before the refactor.
    """

    def test_offset_nonzero_delegates_without_splice(self) -> None:
        """(a) ``offset != 0`` bails to the legacy path immediately —
        BEFORE the ``limit`` default and BEFORE the title probe.
        """
        stub = _SpliceStub(title_results=_berlin_title_results())
        out = stub.search_with_filters_with_canonical_splice(
            "/x.zim", "berlin", namespace="C", limit=None, offset=5
        )
        assert out == _LEGACY_SENTINEL
        assert len(stub.legacy_calls) == 1
        call = stub.legacy_calls[0]
        # CRITICAL ordering pin: the offset!=0 guard runs BEFORE the
        # ``limit is None`` default, so the delegate sees the ORIGINAL
        # ``limit`` (None here), not the defaulted value.
        assert call["limit"] is None
        assert call["offset"] == 5
        assert call["namespace"] == "C"

    def test_canonical_none_delegates(self) -> None:
        """(b) ``find_title_match`` → None bails to the legacy path."""
        stub = _SpliceStub(title_results=[])  # no canonical
        out = stub.search_with_filters_with_canonical_splice(
            "/x.zim", "berlin", namespace="C", limit=10, offset=0
        )
        assert out == _LEGACY_SENTINEL
        assert len(stub.legacy_calls) == 1
        # ``limit`` default already applied (offset == 0 path).
        assert stub.legacy_calls[0]["limit"] == 10
        assert stub.legacy_calls[0]["display_query"] is None

    def test_canonical_none_via_probe_exception_delegates(self) -> None:
        """(b') a raising probe is swallowed to ``canonical = None`` and
        still delegates — the defensive ``except`` path.
        """
        stub = _SpliceStub(title_results=_berlin_title_results())
        with patch(
            "openzim_mcp.zim.search.find_title_match",
            side_effect=RuntimeError("boom"),
        ):
            out = stub.search_with_filters_with_canonical_splice(
                "/x.zim", "berlin", namespace="C", limit=10, offset=0
            )
        assert out == _LEGACY_SENTINEL
        assert len(stub.legacy_calls) == 1

    def test_namespace_prefix_mismatch_delegates(self) -> None:
        """(c) canonical path lives in a different namespace than the
        requested filter → no splice, delegate.
        """
        # Canonical path ``M/Berlin`` → prefix ``M`` != requested ``C``.
        stub = _SpliceStub(
            title_results=[{"path": "M/Berlin", "title": "Berlin", "score": 1.0}]
        )
        out = stub.search_with_filters_with_canonical_splice(
            "/x.zim", "berlin", namespace="C", limit=10, offset=0
        )
        assert out == _LEGACY_SENTINEL
        assert len(stub.legacy_calls) == 1

    def test_content_type_set_delegates(self) -> None:
        """(d) a ``content_type`` filter disables the splice (the title
        probe carries no mimetype) → delegate.
        """
        stub = _SpliceStub(title_results=_berlin_title_results())
        out = stub.search_with_filters_with_canonical_splice(
            "/x.zim",
            "berlin",
            namespace="C",
            content_type="text/html",
            limit=10,
            offset=0,
        )
        assert out == _LEGACY_SENTINEL
        assert len(stub.legacy_calls) == 1
        assert stub.legacy_calls[0]["content_type"] == "text/html"

    def test_offset_guard_runs_before_limit_default(self) -> None:
        """Explicit ordering lock: with ``offset != 0`` AND
        ``limit=None``, the delegate must observe ``limit is None``.
        Were the ``limit`` default hoisted above the offset guard, this
        would see ``default_search_limit`` (7 here) instead.
        """
        stub = _SpliceStub(
            title_results=_berlin_title_results(), default_search_limit=7
        )
        stub.search_with_filters_with_canonical_splice(
            "/x.zim", "berlin", limit=None, offset=3
        )
        assert stub.legacy_calls[0]["limit"] is None


class TestCanonicalSpliceHappyPath:
    """The splice path: canonical found, in-namespace, no content_type,
    offset 0 → the canonical is spliced/prepended into the filtered
    render. Covers the synthetic-prepend sub-branch (canonical NOT
    already present in the BM25 results), which had no direct coverage.
    """

    def test_canonical_prepended_when_absent_from_results(self) -> None:
        payload = {
            "query": "berlin",
            "namespace_filter": "C",
            "content_type_filter": None,
            "results": [
                {
                    "path": "Berlin_Wall",
                    "title": "Berlin Wall",
                    "snippet": "The Berlin Wall was a guarded concrete...",
                    "namespace": "C",
                    "content_type": "text/html",
                },
                {
                    "path": "List_of_songs_about_Berlin",
                    "title": "List of songs about Berlin",
                    "snippet": "This is a list ...",
                    "namespace": "C",
                    "content_type": "text/html",
                },
            ],
            "next_cursor": None,
            "total": 2,
            "done": True,
            "page_info": {"offset": 0, "limit": 10, "returned_count": 2},
        }
        stub = _SpliceStub(data_payload=payload, title_results=_berlin_title_results())
        out = stub.search_with_filters_with_canonical_splice(
            "/x.zim", "berlin", namespace="C", limit=10, offset=0
        )
        # NOT the legacy path — the splice rendered a fresh response.
        assert out != _LEGACY_SENTINEL
        assert not stub.legacy_calls
        # The canonical ``Berlin`` row was spliced in with its badge,
        # ahead of the other hits, which are still present.
        assert "Match type: canonical title match" in out
        assert "Berlin Wall" in out
        # Splice row precedes the existing first hit in the rendering.
        assert out.index("Berlin") < out.index("Berlin Wall")

    def test_canonical_is_top_hit_renders_payload_without_rescan(self) -> None:
        """M33: when the BM25 top hit IS the canonical (exact path match), the
        method renders the structured payload it already computed instead of
        re-running the entire filtered search via the legacy markdown path (a
        second Xapian scan). The legacy delegate must NOT be called.
        """
        payload = {
            "query": "berlin",
            "namespace_filter": "C",
            "content_type_filter": None,
            "results": [
                {
                    "path": "Berlin",
                    "title": "Berlin",
                    "snippet": "Berlin is the capital of Germany.",
                    "namespace": "C",
                    "content_type": "text/html",
                },
            ],
            "next_cursor": None,
            "total": 1,
            "done": True,
            "page_info": {"offset": 0, "limit": 10, "returned_count": 1},
        }
        stub = _SpliceStub(data_payload=payload, title_results=_berlin_title_results())
        out = stub.search_with_filters_with_canonical_splice(
            "/x.zim", "berlin", namespace="C", limit=10, offset=0
        )
        # No second filtered scan; the canonical (already top) is rendered
        # straight from the structured payload.
        assert stub.legacy_calls == []
        assert out != _LEGACY_SENTINEL
        assert "Berlin" in out

    def test_empty_results_surfaces_canonical(self) -> None:
        """Empty BM25 page + reachable canonical → canonical surfaces as
        the single result (re-pins the pre-existing a11 behavior here so
        the refactor can't silently regress it).
        """
        stub = _SpliceStub(title_results=_berlin_title_results())
        out = stub.search_with_filters_with_canonical_splice(
            "/x.zim", "berlin", namespace="C", limit=10, offset=0
        )
        assert out != _LEGACY_SENTINEL
        assert "Berlin" in out
        assert "Match type: canonical title match" in out
        assert "Snippet: (canonical title match)" not in out
