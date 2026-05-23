r"""Regression tests for the post-b7 beta-test sweep.

The post-b7 live-MCP sweep against v2.0.0b7 verified:

- **Z2 fix landed cleanly**: ``Einstein's theory`` via
  ``synthesize=true`` now correctly promotes ``Theory_of_relativity``
  to rank 1 with score=1.0 (was rank 6 / score 0 in v2.0.0b6).
- **Z1 fix landed for one of two original repros**: ``Plato's
  republic philosophy`` now correctly falls to BM25 rendered search
  (was auto-fetching ``Czech_philosophy`` in v2.0.0b6).
- All other invariants still hold: b3 Einstein/Plato canonicals, b4
  Berlin Germany carve-out, D2 pass-2 windows for
  ``Einstein's theory tourism`` / ``... history``, no-regression
  possessives (Hubble / Achilles / Photosythesis / Newton's laws of
  motion), earlier b-series invariants (Tokyo if you would / lord of
  rings / Köln+München+Berlin chain reject / Definately typo / walk
  M / reranker telemetry on no-results).

ONE HIGH-severity defect unlocked by deeper probing:

## Z1.1 — Pre-redirect-path *containment* check is too lenient

The post-b6 Z1 filter rejected ``match_type="redirect"`` rows whose
pre-redirect path tokens didn't *contain* any of the topic's
possessor tokens. That correctly caught
``Plato's republic philosophy`` (libzim returned a redirect to
``Czech_philosophy`` whose pre-path didn't contain ``plato``).

But the post-b7 live probe surfaced a sibling shape: 2-token
possessive queries where the user typed a TRUNCATED form of a longer
canonical redirect. The pre-redirect path DOES contain the possessor
token (so the containment check accepts), but the pre-path has
EXTRAS that aren't in the user's query — meaning the user actually
typed a SUBSET of a longer phrase, and the redirect target loses the
specific scope the user asked about.

Live repro (still wrong after v2.0.0b7):

  ``tell me about Darwin's evolution`` → ``Evolution`` (cert=0.85)

The pre-redirect path tokens look like ``{darwin, s, theory, of,
evolution}`` (the entry's name is a longer phrase like
``Darwin's_Theory_of_Evolution``). The current filter accepts
because ``darwin`` is in the pre-path — but the pre-path's EXTRAS
``{theory, of}`` aren't in the topic, signalling that the user
typed an abbreviated form and the resolved canonical (``Evolution``)
drops the possessor entirely.

## Fix — subset rule

Tighten the filter from "any possessor token in pre-path" to
"pre-path tokens are a SUBSET of topic tokens". Strictly tighter
than the containment check: every previously-accepted case where
pre-path was equal to or shorter than the topic continues to be
accepted; cases where pre-path has tokens not in the topic
(truncation shape) are now rejected.

Shape-by-shape decision matrix (for possessive topics +
``match_type="redirect"``):

  +---------------------+------------------------------+---------+
  | Topic               | Pre-path                     | Decision |
  +---------------------+------------------------------+---------+
  | ``Plato's cave``    | ``Plato's_cave``             | ACCEPT  |
  | ``Einstein's theory`` | ``Einstein's_theory``      | ACCEPT  |
  | ``Newton's gravity``  | ``Newton's_gravity``       | ACCEPT  |
  | ``Darwin's evolution`` | ``Darwin's_Theory_of_Evolution`` | **REJECT** |
  +---------------------+------------------------------+---------+

The first three have ``pre_tokens ⊆ topic_tokens`` (pre and topic
share the same token set, or pre is a subset). The fourth has pre
extras (``theory``, ``of``) not in the topic.

Non-possessive topics, ``match_type="direct"``, and
``match_type="fuzzy_suggest"`` decisions are unchanged from b6.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Shared fixtures (mirror post-b6 conventions — see
# tests/test_post_b6_beta_fixes.py for the rationale)
# ---------------------------------------------------------------------------


def _make_simple_handler() -> Any:
    """Return a stub ``SimpleToolsHandler``-shaped object."""

    class _StubOps:
        pass

    class _Handler:
        zim_operations = _StubOps()

    return _Handler()


def _fake_find_title_match(
    mapping: Dict[str, Optional[Dict[str, Any]]],
    *,
    min_score_floor: float = 0.0,
) -> Callable[..., Optional[Dict[str, Any]]]:
    """Build a ``find_title_match`` stand-in from ``{topic_lower: row}``."""

    def fake(
        zim_ops: Any,
        zim_file_path: str,
        topic: str,
        *,
        cross_file: bool = False,
        min_score: float = 1.0,
    ) -> Optional[Dict[str, Any]]:
        if min_score > min_score_floor and min_score_floor > 0.0:
            return None
        return mapping.get(topic.lower())

    return fake


def _run_promote_simple(
    topic: str, fake_find: Callable[..., Optional[Dict[str, Any]]]
) -> Optional[Dict[str, Any]]:
    """Drive ``_promote_topic_via_title_index`` with ``fake_find`` patched."""
    from openzim_mcp.simple_tools import SimpleToolsHandler

    with patch("openzim_mcp.simple_tools.find_title_match", side_effect=fake_find):
        return SimpleToolsHandler._promote_topic_via_title_index(
            _make_simple_handler(),
            "test.zim",
            topic,
        )


# ---------------------------------------------------------------------------
# Direct unit tests on accept_possessive_promotion
# ---------------------------------------------------------------------------


class TestSubsetRule:
    """``accept_possessive_promotion`` must require pre-redirect path
    tokens to be a SUBSET of topic tokens (not merely contain a
    possessor token) — refines the post-b6 Z1 filter to catch the
    Z1.1 truncation shape."""

    @pytest.mark.parametrize(
        "topic, pre_redirect_path, expected_accept",
        [
            # Live invariants (post-b7 verified ACCEPTED): pre-path
            # tokens equal topic tokens → subset YES → ACCEPT.
            ("Plato's cave", "Plato's_cave", True),
            ("Einstein's theory", "Einstein's_theory", True),
            ("Newton's gravity", "Newton's_gravity", True),
            ("Mary's lamb", "Mary's_lamb", True),
            # Z1.1 attack surface: pre-path has EXTRAS not in topic →
            # subset NO → REJECT. The live ``Darwin's evolution`` ->
            # ``Evolution`` silent-wrong-answer was caused by libzim's
            # suggest returning a redirect entry whose path was a
            # longer phrase like ``Darwin's_Theory_of_Evolution``;
            # the b6 containment check accepted because ``darwin`` is
            # present, but the user's topic doesn't contain
            # ``theory`` / ``of``.
            (
                "Darwin's evolution",
                "Darwin's_Theory_of_Evolution",
                False,
            ),
            # Another truncation-shape repro: a 2-token possessive
            # whose libzim redirect target is a longer canonical
            # phrase. Whatever the specific entry, the principle is
            # the same — extras in pre-path → REJECT.
            (
                "Einstein's photoelectric",
                "Einstein's_photoelectric_effect",
                False,
            ),
        ],
        ids=[
            "platos_cave_subset_equal_accept",
            "einsteins_theory_subset_equal_accept",
            "newtons_gravity_subset_equal_accept",
            "marys_lamb_subset_equal_accept",
            "darwins_evolution_subset_extras_reject",
            "einsteins_photoelectric_subset_extras_reject",
        ],
    )
    def test_subset_rule(
        self, topic: str, pre_redirect_path: str, expected_accept: bool
    ) -> None:
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "ResolvedCanonical",
            "title": "Resolved Canonical",
            "match_type": "redirect",
            "pre_redirect_path": pre_redirect_path,
        }
        assert accept_possessive_promotion(promoted, topic) is expected_accept

    def test_direct_match_unconditional_accept(self) -> None:
        """``match_type="direct"`` continues to be accepted
        unconditionally — the user typed an exact title and the
        post-redirect title matched case-insensitively. No
        pre-redirect-path check needed."""
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "Hubble's_law",
            "title": "Hubble's law",
            "match_type": "direct",
            "pre_redirect_path": "Hubble's_law",
        }
        assert accept_possessive_promotion(promoted, "Hubble's law") is True

    def test_fuzzy_suggest_still_rejected_on_possessive(self) -> None:
        """The b6 D1 attack surface: ``match_type="fuzzy_suggest"`` on
        a possessive topic is REJECTED regardless of pre-redirect-path
        content."""
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "Evolution",
            "title": "Evolution",
            "match_type": "fuzzy_suggest",
            "pre_redirect_path": "Evolution",
        }
        assert accept_possessive_promotion(promoted, "Darwin's evolution") is False

    def test_non_possessive_always_accepted(self) -> None:
        """The b4 carve-out: non-possessive topics accept all
        match_types so ``Berlin Germany`` → ``Berlin`` (fuzzy_suggest
        at 0.95) keeps the b4 improvement."""
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "Berlin",
            "title": "Berlin",
            "match_type": "fuzzy_suggest",
            "pre_redirect_path": "Berlin",
        }
        assert accept_possessive_promotion(promoted, "Berlin Germany") is True

    def test_missing_match_type_backwards_compat(self) -> None:
        """Older callers / mocks that don't annotate match_type are
        accepted (legacy behaviour)."""
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "Theory_of_relativity",
            "title": "Theory of relativity",
        }
        assert accept_possessive_promotion(promoted, "Einstein's theory") is True


# ---------------------------------------------------------------------------
# Integration test through _promote_topic_via_title_index
# ---------------------------------------------------------------------------


class TestPromoteIntegration:
    """End-to-end shape: the Z1.1 fix must reject the actual live
    repro path through ``_promote_topic_via_title_index``."""

    def test_darwins_evolution_rejected_at_pass_0(self) -> None:
        """Live repro: ``tell me about Darwin's evolution`` → libzim
        returns ``Evolution`` at 0.95 via a redirect chain whose
        pre-path is a longer phrase. With the Z1.1 subset rule, pass-0
        rejects → tail iteration finds nothing strict → return None →
        BM25 fallback."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "darwin's evolution": {
                "path": "Evolution",
                "title": "Evolution",
                "zim_file": "test.zim",
                "match_type": "redirect",
                # Simulates libzim's suggest returning a longer
                # redirect entry whose pre-path contains "darwin" but
                # has EXTRAS not in the topic.
                "pre_redirect_path": "Darwin's_Theory_of_Evolution",
            },
        }
        result = _run_promote_simple(
            "darwin's evolution", _fake_find_title_match(mapping, min_score_floor=0.95)
        )
        # Z1.1: subset rule rejects → promotion fails → caller falls
        # back to BM25.
        assert result is None, (
            f"Z1.1 must reject the Darwin's_Theory_of_Evolution truncation "
            f"redirect; got {result!r}"
        )

    def test_platos_cave_still_accepted_at_pass_0(self) -> None:
        """Live invariant: ``tell me about Plato's cave`` →
        ``Allegory_of_the_cave`` via a redirect whose pre-path
        ``Plato's_cave`` has tokens equal to the topic tokens.
        Subset rule ACCEPTS."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "plato's cave": {
                "path": "Allegory_of_the_cave",
                "title": "Allegory of the cave",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Plato's_cave",
            },
        }
        result = _run_promote_simple(
            "plato's cave", _fake_find_title_match(mapping, min_score_floor=0.95)
        )
        assert result is not None and result["path"] == "Allegory_of_the_cave"


class TestRegressionGuards:
    """Pin the post-b7 invariants."""

    def test_accept_possessive_promotion_uses_subset_check(self) -> None:
        """Structural pin: the shared filter source must reference
        ``issubset`` (or equivalent subset check) so the Z1.1
        refinement isn't accidentally reverted.

        Post-b8 refactor: the dispatcher delegates to per-branch
        helpers; the subset check now lives in
        ``_accept_possessive_redirect``."""
        import inspect

        from openzim_mcp import title_promotion

        source = inspect.getsource(title_promotion._accept_possessive_redirect)
        # Either ``.issubset(...)`` or ``set(...) <= set(...)``
        # qualifies as a subset check. Reject the bare ``&``
        # (containment) form alone — that was the b6 implementation
        # the Z1.1 sweep tightened.
        assert (".issubset(" in source) or ("<=" in source), (
            "_accept_possessive_redirect must use a SUBSET check on "
            "pre-redirect-path tokens vs topic tokens — see Z1.1"
        )
