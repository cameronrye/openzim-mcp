r"""Regression tests for the post-b6 beta-test sweep.

The post-b6 live-MCP verification sweep against v2.0.0b6 confirmed:

- All three b3 invariants (Einstein's theory, Plato's cave, Plato's
  Republic) still resolve canonically.
- The D2 fix lands cleanly for 3-token possessives: `Einstein's
  theory tourism` / `Einstein's theory history` correctly route to
  `Theory_of_relativity` via pass-2 windows promoting the
  `einstein's theory` 2-window.
- The D1 carve-out preserves the b4 win for non-possessive prose:
  `Berlin Germany` → `Berlin`.
- All no-regression possessives (Hubble's law / Achilles' heel /
  Photosythesis's reproduction / Newton's laws of motion) hold.
- All earlier b-series invariants (Tokyo if you would, lord of the
  rings, Köln+München+Berlin chain reject, Definately typo, walk
  namespace M, no-results reranker telemetry) hold.

Two new HIGH-severity defects unlocked by deeper probing:

## Z1 — D1 filter misses ``match_type="redirect"`` cases when the redirect target is unrelated to the possessor

The pass-1 D1 filter only rejects ``match_type="fuzzy_suggest"``. But
libzim's suggestion-search sometimes returns a result via a redirect
chain walk (``match_type="redirect"`` → ACCEPTED by the filter), even
when the redirect target is unrelated to the user's possessive entity:

- ``tell me about Darwin's evolution`` → ``Evolution`` (cert=0.85)
- ``tell me about Plato's republic philosophy`` → ``Czech_philosophy``
  (cert=0.85)

The fix: tighten the filter to also reject ``redirect`` rows whose
PRE-redirect path doesn't contain any of the topic's possessor
tokens. The shared filter lives in ``title_promotion`` as
``accept_possessive_promotion`` and is consulted by both the simple-
mode pass-0/pass-3 and the synthesize-mode pass-0.

## Z2 — Synthesize pass-0 produces malformed insert when canonical isn't in BM25 top hits

``_promote_title_match`` in ``synthesize.py`` previously inserted the
raw ``find_title_match`` dict (shape ``{path, title, zim_file,
match_type, pre_redirect_path}``) into ``top_hits``, which expects
``{path, snippet, score}``. When the canonical IS in ``top_hits``
already (the reorder branch), the existing properly-shaped entry was
moved to first. But when the canonical was NOT in ``top_hits``, the
malformed insert leaked through → downstream score-sort demoted it
to the bottom.

Live impact: ``Einstein's theory`` via ``synthesize=true`` returned
``Theory_of_relativity`` at rank 6 with score 0. Plato's cave worked
because Allegory_of_the_cave WAS in BM25 top hits.

The fix: re-probe via ``search_handler.title_match_hit(archive,
full_probe.title)`` to produce a ``{path, snippet, score: 1.0}``
shape; fall back to ``{path, snippet: "", score: 1.0}`` when the
re-probe handler misses (test stubs / degraded paths).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from tests._promote_fixtures import fake_find_title_match as _fake_find_title_match
from tests._promote_fixtures import run_promote_simple as _run_promote_simple

# ---------------------------------------------------------------------------
# Shared fixtures / mock-builders.
#
# Several tests share the same scaffold: a stub ``SimpleToolsHandler``-shaped
# object, a fake ``find_title_match`` driven by a ``{topic: result}``
# mapping, and a synthesize ``search_handler`` whose ``title_match_hit`` is
# also mapping-driven. Extract them once at module scope so each test only
# carries the per-case mapping / assertions — reduces noise AND fixes the
# Sonar new-code-duplication finding from the pass-1 push.
# ---------------------------------------------------------------------------


def _archive_stub() -> Any:
    """Lightweight stub for libzim ``Archive`` — only needs identity
    for ``zip(archives, archives_searched)`` iteration in synthesize."""

    class _Archive:
        pass

    return _Archive()


def _fake_title_match_hit(
    mapping: Dict[str, Optional[Dict[str, Any]]],
) -> Callable[[Any, str], Optional[Dict[str, Any]]]:
    """Build a ``title_match_hit`` stand-in from ``{title_lower: row}``."""

    def fake(archive: Any, title: str) -> Optional[Dict[str, Any]]:
        return mapping.get(title.lower())

    return fake


def _run_promote_synthesize(
    query: str,
    fake_find: Callable[..., Optional[Dict[str, Any]]],
    *,
    title_match_hit: Optional[Callable[[Any, str], Optional[Dict[str, Any]]]] = None,
    top_hits: Optional[List[tuple[str, Dict[str, Any]]]] = None,
) -> List[tuple[str, Dict[str, Any]]]:
    """Drive ``synthesize._promote_title_match`` with the given fakes."""
    from openzim_mcp.synthesize import _promote_title_match

    handler = MagicMock()
    handler.title_match_hit = title_match_hit or (lambda _a, _q: None)
    with patch("openzim_mcp.synthesize.find_title_match", side_effect=fake_find):
        return _promote_title_match(
            top_hits or [],
            query=query,
            archives=[(_archive_stub(), "/wiki.zim")],
            archives_searched=["wiki"],
            search_handler=handler,
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPreRedirectPathPropagation:
    """``find_title_match`` propagates ``pre_redirect_path`` so callers
    can distinguish semantic redirects (pre-path contains the user's
    possessor token) from associative redirects (pre-path is unrelated)."""

    def test_propagates_pre_redirect_path(self) -> None:
        from openzim_mcp.title_promotion import find_title_match

        mock = MagicMock()
        mock.find_entry_by_title_data.return_value = {
            "results": [
                {
                    "path": "Allegory_of_the_cave",
                    "title": "Allegory of the cave",
                    "score": 0.95,
                    "match_type": "redirect",
                    "pre_redirect_path": "Plato's_cave",
                }
            ]
        }
        result = find_title_match(mock, "/x.zim", "Plato's cave", min_score=0.95)
        assert result is not None
        assert result["pre_redirect_path"] == "Plato's_cave"

    def test_missing_pre_redirect_path_backwards_compat(self) -> None:
        """Old mocks / fixtures that don't set pre_redirect_path must
        still pass through cleanly (the field is optional)."""
        from openzim_mcp.title_promotion import find_title_match

        mock = MagicMock()
        mock.find_entry_by_title_data.return_value = {
            "results": [
                {
                    "path": "Berlin",
                    "title": "Berlin",
                    "score": 1.0,
                    "match_type": "direct",
                }
            ]
        }
        result = find_title_match(mock, "/x.zim", "Berlin")
        assert result is not None
        # pre_redirect_path not required — older callers don't set it.
        assert "pre_redirect_path" not in result or result["pre_redirect_path"] == ""


class TestPossessorTokenExtraction:
    """``extract_possessor_tokens`` extracts the bare possessor from
    each ``X's`` / ``X'`` shape in the topic."""

    @pytest.mark.parametrize(
        "topic, expected",
        [
            # Simple possessives
            ("Plato's cave", ["plato"]),
            ("Darwin's evolution", ["darwin"]),
            ("Einstein's theory", ["einstein"]),
            # Multiple possessives in one query
            ("John's and Mary's books", ["john", "mary"]),
            # Trailing apostrophe without 's
            ("Achilles' heel", ["achilles"]),
            # Curly apostrophe
            ("Einstein’s theory", ["einstein"]),
            # No possessive — names with apostrophes are not possessors
            ("Berlin Germany", []),
            ("Apollo 11", []),
            ("O'Brien", []),
            ("d'Artagnan", []),
        ],
    )
    def test_extraction(self, topic: str, expected: List[str]) -> None:
        from openzim_mcp.title_promotion import extract_possessor_tokens

        assert extract_possessor_tokens(topic) == expected


class TestRedirectFilterRejectsUnrelatedRedirect:
    """The D1 filter must reject ``match_type="redirect"`` when the
    pre-redirect path tokens don't contain any of the topic's
    possessor tokens — catching the Z1 silent-wrong-answer where
    libzim's suggest produces an associative redirect to an unrelated
    canonical."""

    @pytest.mark.parametrize(
        "topic, mapping, expected_path",
        [
            # Z1 repro: redirect to ``Evolution`` via an unrelated
            # pre-redirect path. ``darwin`` not in pre-path tokens →
            # filter REJECTS → no promotion → returns None.
            (
                "darwin's evolution",
                {
                    "darwin's evolution": {
                        "path": "Evolution",
                        "title": "Evolution",
                        "zim_file": "test.zim",
                        "match_type": "redirect",
                        "pre_redirect_path": "Evolutionary_theory",
                    }
                },
                None,
            ),
            # Live invariant: ``Plato's_cave`` redirect entry → walks to
            # ``Allegory_of_the_cave``. Pre-redirect path tokens contain
            # ``plato`` → filter ACCEPTS.
            (
                "plato's cave",
                {
                    "plato's cave": {
                        "path": "Allegory_of_the_cave",
                        "title": "Allegory of the cave",
                        "zim_file": "test.zim",
                        "match_type": "redirect",
                        "pre_redirect_path": "Plato's_cave",
                    }
                },
                "Allegory_of_the_cave",
            ),
            # ``match_type="direct"`` is always accepted — the user's
            # exact title is canonical. No possessor-token check.
            (
                "Hubble's law",
                {
                    "hubble's law": {
                        "path": "Hubble's_law",
                        "title": "Hubble's law",
                        "zim_file": "test.zim",
                        "match_type": "direct",
                        "pre_redirect_path": "Hubble's_law",
                    }
                },
                "Hubble's_law",
            ),
        ],
        ids=[
            "rejects_redirect_with_unrelated_pre_path",
            "accepts_redirect_with_possessor_in_pre_path",
            "accepts_direct_match_unconditionally",
        ],
    )
    def test_filter(
        self,
        topic: str,
        mapping: Dict[str, Dict[str, Any]],
        expected_path: Optional[str],
    ) -> None:
        result = _run_promote_simple(
            topic, _fake_find_title_match(mapping, min_score_floor=0.95)
        )
        if expected_path is None:
            assert (
                result is None
            ), f"filter must reject for topic={topic!r}; got {result!r}"
        else:
            assert result is not None and result["path"] == expected_path


class TestSynthesizePass0InsertShape:
    """Z2: synthesize pass-0 must produce ``search_top_k``-shaped
    inserts (``{path, snippet, score}``) so downstream score-based
    sorting doesn't demote the canonical to the bottom."""

    # Shared mapping the synthesize pass-0 sees for ``Einstein's theory``
    # → ``Theory_of_relativity`` (a redirect-walked canonical).
    _EINSTEIN_FIND_MAPPING: Dict[str, Dict[str, Any]] = {
        "einstein's theory": {
            "path": "Theory_of_relativity",
            "title": "Theory of relativity",
            "zim_file": "wiki",
            "match_type": "redirect",
            "pre_redirect_path": "Einstein's_theory",
        }
    }

    def test_promoted_hit_has_search_top_k_shape(self) -> None:
        """``Einstein's theory`` via synthesize → pass-0 inserts
        ``Theory_of_relativity``. The insert must have ``snippet`` and
        ``score`` fields so it survives downstream ranking."""
        # title_match_hit re-probe lands the resolved title via fast
        # path → returns ``{path, snippet, score: 1.0}``.
        title_match_hit = _fake_title_match_hit(
            {
                "theory of relativity": {
                    "path": "Theory_of_relativity",
                    "snippet": "The theory of relativity comprises two...",
                    "score": 1.0,
                }
            }
        )
        # Top hits do NOT contain Theory_of_relativity — the only way
        # it can end up at rank 1 is via pass-0 promotion.
        top_hits: List[tuple[str, Dict[str, Any]]] = [
            (
                "wiki",
                {
                    "path": "Einstein–Cartan_theory",
                    "snippet": "...alternative to general relativity...",
                    "score": 1.0,
                },
            ),
        ]
        result_hits = _run_promote_synthesize(
            "Einstein's theory",
            _fake_find_title_match(self._EINSTEIN_FIND_MAPPING),
            title_match_hit=title_match_hit,
            top_hits=top_hits,
        )
        assert len(result_hits) >= 1
        top_arch, top_hit = result_hits[0]
        assert top_arch == "wiki"
        assert top_hit["path"] == "Theory_of_relativity"
        # CRITICAL: snippet and score must be present for downstream
        # extraction and ranking to work correctly.
        assert "snippet" in top_hit, (
            "pass-0 insert must include ``snippet`` field for "
            "_extract_passages downstream — see Z2"
        )
        assert top_hit["snippet"], "snippet must be non-empty"
        assert "score" in top_hit, (
            "pass-0 insert must include ``score`` field for "
            "downstream score-based sorting — see Z2"
        )
        assert (
            top_hit["score"] >= 1.0
        ), f"pass-0 insert score must be 1.0; got {top_hit.get('score')}"

    def test_fallback_to_minimal_hit_when_reprobe_misses(self) -> None:
        """If ``title_match_hit`` re-probe misses (e.g., the fast-path
        case variants don't match the resolved title for some
        archives), pass-0 still produces a well-shaped minimal hit
        with the canonical path and an empty-but-present snippet
        rather than leaking the malformed find_title_match dict."""
        # Empty re-probe mapping → title_match_hit always returns None
        # → fallback minimal-hit path engages.
        top_hits: List[tuple[str, Dict[str, Any]]] = [
            (
                "wiki",
                {
                    "path": "Some_BM25_hit",
                    "snippet": "...",
                    "score": 1.0,
                },
            ),
        ]
        result_hits = _run_promote_synthesize(
            "Einstein's theory",
            _fake_find_title_match(self._EINSTEIN_FIND_MAPPING),
            title_match_hit=_fake_title_match_hit({}),
            top_hits=top_hits,
        )
        # Top hit must STILL be Theory_of_relativity with search_top_k
        # shape — even if the re-probe missed.
        assert len(result_hits) >= 1
        top_hit = result_hits[0][1]
        assert top_hit["path"] == "Theory_of_relativity"
        assert "snippet" in top_hit
        assert "score" in top_hit
        assert top_hit["score"] >= 1.0


class TestRegressionGuards:
    """Pin the post-b6 invariants so future contributors don't
    regress them."""

    def test_extract_possessor_tokens_exists(self) -> None:
        """The Z1 fix depends on this helper. If a refactor removes
        it, the filter falls back to the unconditional check that the
        post-b6 sweep refined."""
        from openzim_mcp import title_promotion

        assert hasattr(title_promotion, "extract_possessor_tokens")

    def test_promote_function_filter_checks_pre_redirect_path(self) -> None:
        """Structural pin: the shared filter
        ``title_promotion.accept_possessive_promotion`` consulted by
        both ``simple_tools._promote_topic_via_title_index`` (pass-0 +
        pass-3) and ``synthesize._promote_title_match`` (pass-0) must
        reference ``pre_redirect_path`` so an associative redirect on
        a possessive topic is rejected. The helper lives in
        ``title_promotion`` (single source of truth — fixes the
        post-b6 sweep-CI Sonar duplication finding).

        Post-b8 refactor: the dispatcher delegates to per-branch
        helpers; the pre_redirect_path check now lives in
        ``_accept_possessive_redirect``."""
        import inspect

        from openzim_mcp import title_promotion

        source = inspect.getsource(title_promotion._accept_possessive_redirect)
        assert "pre_redirect_path" in source, (
            "title_promotion._accept_possessive_redirect must consult "
            "pre_redirect_path to reject associative redirects on "
            "possessive topics — see Z1"
        )

    def test_synthesize_pass_0_constructs_proper_shape(self) -> None:
        """Structural pin: ``_promote_title_match`` source must
        re-probe via ``title_match_hit`` or otherwise construct a
        ``snippet``-carrying hit for the pass-0 insert."""
        import inspect

        from openzim_mcp.synthesize import _promote_title_match

        source = inspect.getsource(_promote_title_match)
        # The insert path must either call title_match_hit (the
        # canonical re-probe approach) or explicitly construct
        # ``snippet`` in the hit dict.
        assert "snippet" in source or "title_match_hit" in source.split("Pass-0")[0], (
            "_promote_title_match pass-0 insert must construct a "
            "search_top_k-shaped hit (path, snippet, score) so "
            "downstream ranking doesn't demote the canonical — see Z2"
        )
