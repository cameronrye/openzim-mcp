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
tokens. For ``Plato's_cave`` → ``Allegory_of_the_cave``, the
pre-redirect path is ``Plato's_cave`` whose tokens contain ``plato``
(the possessor) → ACCEPT. For ``Darwin's evolution`` → some
unrelated-redirect-path → ``Evolution``, the pre-redirect path tokens
don't contain ``darwin`` → REJECT.

Implementation:
- ``find_entry_by_title_data`` annotates each result row with
  ``pre_redirect_path`` (the path libzim's suggest emitted before
  ``_follow_redirect_chain`` resolved it).
- ``find_title_match`` propagates ``pre_redirect_path``.
- New ``extract_possessor_tokens(topic)`` helper extracts the bare
  possessor token from each ``X's``/``X'`` shape (e.g.,
  ``"Plato's cave"`` → ``["plato"]``; ``"John's and Mary's books"``
  → ``["john", "mary"]``).
- The D1 filter in ``_promote_topic_via_title_index`` (pass-0 +
  pass-3) and ``_promote_title_match`` (synthesize pass-0) rejects
  when ``match_type ∈ {fuzzy_suggest, redirect}`` AND the topic has
  a possessive AND the pre-redirect path's tokens contain NONE of
  the possessor tokens.

## Z2 — Synthesize pass-0 produces malformed insert when canonical isn't in BM25 top hits

``_promote_title_match`` in ``synthesize.py:_promote_title_match``
inserts the raw ``find_title_match`` dict (shape
``{path, title, zim_file, match_type, ...}``) into ``top_hits``,
which expects the ``search_top_k`` shape
``{path, snippet, score}``. When the canonical IS in ``top_hits``
already (the reorder branch), the existing properly-shaped entry is
moved to first. But when the canonical is NOT in ``top_hits`` (no
intersection with BM25), the malformed insert leaks through →
downstream score-sort demotes it to the bottom because ``score`` is
missing.

Live impact: ``Einstein's theory`` via ``synthesize=true`` returns
``Theory_of_relativity`` at rank 6 with score 0 (instead of rank 1).
``Plato's cave`` happens to work because ``Allegory_of_the_cave``
IS in BM25 top hits (the reorder branch fires).

The fix: when ``find_title_match`` accepts a pass-0 promotion, re-probe
via ``search_handler.title_match_hit(archive, full_probe.title)`` to
produce a ``{path, snippet, score: 1.0}`` shaped hit. If the
title_match_hit re-probe misses (rare — only when fast-path can't
find the resolved title), fall back to constructing the minimal hit
with the canonical title's lead text as the snippet.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch


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

    def test_simple_possessive(self) -> None:
        from openzim_mcp.title_promotion import extract_possessor_tokens

        assert extract_possessor_tokens("Plato's cave") == ["plato"]
        assert extract_possessor_tokens("Darwin's evolution") == ["darwin"]
        assert extract_possessor_tokens("Einstein's theory") == ["einstein"]

    def test_multiple_possessives(self) -> None:
        from openzim_mcp.title_promotion import extract_possessor_tokens

        tokens = extract_possessor_tokens("John's and Mary's books")
        assert tokens == ["john", "mary"]

    def test_trailing_apostrophe(self) -> None:
        """``Achilles'`` (trailing apostrophe without 's') is a
        possessor."""
        from openzim_mcp.title_promotion import extract_possessor_tokens

        assert extract_possessor_tokens("Achilles' heel") == ["achilles"]

    def test_curly_apostrophe(self) -> None:
        from openzim_mcp.title_promotion import extract_possessor_tokens

        assert extract_possessor_tokens("Einstein’s theory") == ["einstein"]

    def test_no_possessive(self) -> None:
        from openzim_mcp.title_promotion import extract_possessor_tokens

        assert extract_possessor_tokens("Berlin Germany") == []
        assert extract_possessor_tokens("Apollo 11") == []
        # ``O'Brien`` and ``d'Artagnan`` are names, not possessives.
        assert extract_possessor_tokens("O'Brien") == []
        assert extract_possessor_tokens("d'Artagnan") == []


class TestRedirectFilterRejectsUnrelatedRedirect:
    """The D1 filter must reject ``match_type="redirect"`` when the
    pre-redirect path tokens don't contain any of the topic's
    possessor tokens — catching the Z1 silent-wrong-answer where
    libzim's suggest produces an associative redirect to an unrelated
    canonical."""

    def _make_handler(self) -> Any:
        class _StubOps:
            pass

        class _Handler:
            zim_operations = _StubOps()

        return _Handler()

    def test_rejects_redirect_with_unrelated_pre_path(self) -> None:
        """Live repro: ``darwin's evolution`` → some-unrelated-redirect
        → ``Evolution``. Pre-redirect path doesn't contain ``darwin``
        → filter REJECTS."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        def fake(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            if topic.lower() == "darwin's evolution" and min_score <= 0.95:
                # Simulate libzim returning a redirect that walks to
                # Evolution but whose pre-redirect path doesn't
                # contain the possessor token "darwin".
                return {
                    "path": "Evolution",
                    "title": "Evolution",
                    "zim_file": "test.zim",
                    "match_type": "redirect",
                    "pre_redirect_path": "Evolutionary_theory",
                }
            return None

        with patch("openzim_mcp.simple_tools.find_title_match", side_effect=fake):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                self._make_handler(),
                "test.zim",
                "darwin's evolution",
            )
        assert result is None, (
            f"redirect with unrelated pre-path must be rejected for "
            f"possessive topics; got {result!r}"
        )

    def test_accepts_redirect_with_possessor_in_pre_path(self) -> None:
        """Live invariant: ``plato's cave`` → ``Plato's_cave`` redirect
        → ``Allegory_of_the_cave``. Pre-redirect path ``Plato's_cave``
        tokens contain ``plato`` → filter ACCEPTS."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        def fake(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            if topic.lower() == "plato's cave" and min_score <= 0.95:
                return {
                    "path": "Allegory_of_the_cave",
                    "title": "Allegory of the cave",
                    "zim_file": "test.zim",
                    "match_type": "redirect",
                    "pre_redirect_path": "Plato's_cave",
                }
            return None

        with patch("openzim_mcp.simple_tools.find_title_match", side_effect=fake):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                self._make_handler(),
                "test.zim",
                "plato's cave",
            )
        assert result is not None
        assert result["path"] == "Allegory_of_the_cave"

    def test_accepts_direct_match_unconditionally(self) -> None:
        """``match_type="direct"`` is always accepted — the user's
        exact title is canonical. No possessor-token check needed."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        def fake(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            if topic.lower() == "hubble's law":
                return {
                    "path": "Hubble's_law",
                    "title": "Hubble's law",
                    "zim_file": "test.zim",
                    "match_type": "direct",
                    "pre_redirect_path": "Hubble's_law",
                }
            return None

        with patch("openzim_mcp.simple_tools.find_title_match", side_effect=fake):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                self._make_handler(),
                "test.zim",
                "Hubble's law",
            )
        assert result is not None
        assert result["path"] == "Hubble's_law"


class TestSynthesizePass0InsertShape:
    """Z2: synthesize pass-0 must produce ``search_top_k``-shaped
    inserts (``{path, snippet, score}``) so downstream score-based
    sorting doesn't demote the canonical to the bottom."""

    def test_promoted_hit_has_search_top_k_shape(self) -> None:
        """``Einstein's theory`` via synthesize → pass-0 inserts
        ``Theory_of_relativity``. The insert must have ``snippet`` and
        ``score`` fields so it survives downstream ranking."""
        from openzim_mcp.synthesize import _promote_title_match

        class _Archive:
            pass

        archive_obj = _Archive()

        def fake_title_match_hit(archive: Any, title: str) -> Optional[Dict[str, Any]]:
            # The re-probe after pass-0 accept: looks up the resolved
            # title via fast path and returns the ``search_top_k`` shape.
            if title.lower() == "theory of relativity":
                return {
                    "path": "Theory_of_relativity",
                    "snippet": "The theory of relativity comprises two...",
                    "score": 1.0,
                }
            return None

        def fake_find_title_match(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            if topic.lower() == "einstein's theory":
                return {
                    "path": "Theory_of_relativity",
                    "title": "Theory of relativity",
                    "zim_file": "wiki",
                    "match_type": "redirect",
                    "pre_redirect_path": "Einstein's_theory",
                }
            return None

        handler = MagicMock()
        handler.title_match_hit = fake_title_match_hit

        with patch(
            "openzim_mcp.synthesize.find_title_match",
            side_effect=fake_find_title_match,
        ):
            # Top hits do NOT contain Theory_of_relativity — the only
            # way it can end up at rank 1 is via pass-0 promotion.
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
            result_hits = _promote_title_match(
                top_hits,
                query="Einstein's theory",
                archives=[(archive_obj, "/wiki.zim")],
                archives_searched=["wiki"],
                search_handler=handler,
            )
        # Rank 0: must be Theory_of_relativity with search_top_k shape.
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
        assert top_hit["score"] >= 1.0, (
            f"pass-0 insert score must be 1.0 (highest); got " f"{top_hit.get('score')}"
        )

    def test_fallback_to_minimal_hit_when_reprobe_misses(self) -> None:
        """If ``title_match_hit`` re-probe misses (e.g., the fast-path
        case variants don't match the resolved title for some
        archives), pass-0 still produces a well-shaped minimal hit
        with the canonical path and an empty-but-present snippet
        rather than leaking the malformed find_title_match dict."""
        from openzim_mcp.synthesize import _promote_title_match

        class _Archive:
            pass

        archive_obj = _Archive()

        def fake_title_match_hit(archive: Any, title: str) -> Optional[Dict[str, Any]]:
            # Re-probe miss — fast path doesn't find the resolved title.
            return None

        def fake_find_title_match(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            if topic.lower() == "einstein's theory":
                return {
                    "path": "Theory_of_relativity",
                    "title": "Theory of relativity",
                    "zim_file": "wiki",
                    "match_type": "redirect",
                    "pre_redirect_path": "Einstein's_theory",
                }
            return None

        handler = MagicMock()
        handler.title_match_hit = fake_title_match_hit

        with patch(
            "openzim_mcp.synthesize.find_title_match",
            side_effect=fake_find_title_match,
        ):
            result_hits = _promote_title_match(
                [
                    (
                        "wiki",
                        {
                            "path": "Some_BM25_hit",
                            "snippet": "...",
                            "score": 1.0,
                        },
                    ),
                ],
                query="Einstein's theory",
                archives=[(archive_obj, "/wiki.zim")],
                archives_searched=["wiki"],
                search_handler=handler,
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
        """Structural pin: the filter helper consulted by
        ``_promote_topic_via_title_index`` (pass-0 + pass-3) must
        reference ``pre_redirect_path`` so an associative redirect on
        a possessive topic is rejected. The helper lives in
        ``simple_tools`` as ``_accept_possessive_promotion`` and
        ``synthesize`` as ``_accept_synthesize_possessive_promotion``."""
        import inspect

        from openzim_mcp import simple_tools, synthesize

        simple_source = inspect.getsource(simple_tools._accept_possessive_promotion)
        assert "pre_redirect_path" in simple_source, (
            "simple_tools._accept_possessive_promotion must consult "
            "pre_redirect_path to reject associative redirects on "
            "possessive topics — see Z1"
        )
        synth_source = inspect.getsource(
            synthesize._accept_synthesize_possessive_promotion
        )
        assert "pre_redirect_path" in synth_source, (
            "synthesize._accept_synthesize_possessive_promotion must "
            "consult pre_redirect_path to reject associative redirects "
            "on possessive topics — see Z1"
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
