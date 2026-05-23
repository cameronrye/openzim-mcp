r"""Regression tests for the post-b8 beta-test sweep.

The post-b8 live-MCP sweep against v2.0.0b8 verified ALL prior fixes
land cleanly:

- Z1.1 subset rule (b8): ``Darwin's evolution`` no longer auto-fetches
  ``Evolution`` — falls to BM25 search.
- Z1 associative-redirect filter (b6): ``Plato's republic philosophy``
  no longer auto-fetches ``Czech_philosophy``.
- Z2 synthesize pass-0 (b6): ``Einstein's theory`` via
  ``synthesize=true`` ranks ``Theory_of_relativity`` at #1 score 1.0.
- B6 reorder branch (b6): ``Plato's cave`` auto-fetches
  ``Allegory_of_the_cave``.
- Plus every b3/b4/b5/b6/b7 invariant.

ONE HIGH-severity defect + ONE MEDIUM opportunity unlocked by deeper
probing.

## Z3 (HIGH) — Non-possessive multi-token tail-hijack

The b4 D2 fix raised the ``iter_query_tails`` ``min_len`` floor to 2
only for ``has_apostrophe_possessive(topic)``. Non-possessive
multi-token queries still leak the same hijack at Pass 0
(``_promote_topic_via_title_index``): libzim's title-suggest fuzzy-
matches a STRONG single token in the topic at score 0.95 and returns
just that token's canonical article. The full-topic probe at
min_score=0.95 (added in b3 to catch ``Einstein's theory`` /
``Plato's Republic``) accepts the row unconditionally because
``accept_possessive_promotion`` returns True for any non-possessive
topic.

Live silent-wrong-answer repros (cert=0.85):

  * ``Stalin USSR Russia`` → ``Russia`` (user wanted Stalin)
  * ``Hitler Germany Berlin`` → ``Berlin`` (user wanted Hitler)
  * ``Marie Curie polonium discovery`` → ``Discovery`` (a
    disambiguation page!)
  * ``Marie Curie radioactivity`` → ``Radioactive_(Redniss_book)``
    (obscure 2010 graphic novel surfaced via stemming match)
  * ``Big Rapids Michigan tourism`` → ``Tourism`` (contradicts the
    iter_query_windows docstring's own canonical example,
    ``Big_Rapids,_Michigan``)
  * ``O'Brien character 1984`` → ``1984`` (the year article)

Counter-cases that work correctly today (regression guards):

  * ``Hamlet Denmark prince`` → ``Hamlet`` (single-token canonical
    at HEAD position of topic)
  * ``Napoleon France emperor`` → ``Napoleon`` (head position)
  * ``Apollo 11 moon landing`` → ``Moon_landing`` (multi-token
    canonical — not a tail hijack)
  * ``quantum mechanics Einstein`` → ``Albert_Einstein``
    (canonical's tokens include topic's last token but canonical
    itself is multi-token via redirect)
  * ``Lincoln Gettysburg Address`` → ``Gettysburg_Address``
    (multi-token canonical)
  * ``Berlin Germany`` → ``Berlin`` (resolves via
    ``is_strong_title_match`` at BM25 stage; 2-token topic doesn't
    trigger Z3 rule anyway)

## Fix — Z3 rule in accept_possessive_promotion's non-possessive branch

For non-possessive topics with ``match_type="fuzzy_suggest"`` where the
topic has 3+ tokens:

  1. **Tail-token hijack**: canonical is a single token AND that token
     equals the topic's LAST token → REJECT.
  2. **Zero-overlap stemming hit**: canonical's tokens have zero exact-
     overlap with topic's tokens (the match was via stemming alone) →
     REJECT.

For non-possessive topics with ``match_type="direct"`` or
``match_type="redirect"``, accept-as-before.

For possessive topics, the existing b6 D1 + b8 Z1.1 logic is
unchanged (modulo OPP-1, below).

## OPP-1 (MEDIUM) — possessive fuzzy_suggest carve-out

The b6 D1 rule REJECTS every ``match_type="fuzzy_suggest"`` row for a
possessive topic. Live probe found this is too strict: ``Newton's
gravity`` falls to BM25 even though ``Newton's_law_of_universal_
gravitation`` is the obvious rank-1 BM25 canonical AND contains the
possessor token ``Newton`` literally.

Refinement: for possessive topics + ``fuzzy_suggest``, ACCEPT iff the
canonical path contains ANY of the topic's possessor tokens (lowered
case). The matched canonical literally preserves the user's named
entity, signalling it's a longer-form expansion (not the
``Darwin's evolution`` → ``Evolution`` shape that drops the possessor).

Decision matrix for possessive + fuzzy_suggest:

  +---------------------------+-----------------------------------+--------+
  | Topic                     | Canonical                         | Decide |
  +---------------------------+-----------------------------------+--------+
  | ``Newton's gravity``      | ``Newton's_law_of_universal_grav…`` | ACCEPT |
  | ``Mary's lamb``           | ``Mary_Had_a_Little_Lamb``        | ACCEPT |
  | ``Darwin's evolution``    | ``Evolution``                     | REJECT |
  | ``Plato's republic philos…`` | ``Czech_philosophy``           | REJECT |
  +---------------------------+-----------------------------------+--------+

Direct/redirect/missing branches are unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from tests._promote_fixtures import (
    fake_find_title_match as _fake_find_title_match,
)
from tests._promote_fixtures import (
    run_promote_simple as _run_promote_simple,
)

# ---------------------------------------------------------------------------
# Z3: non-possessive multi-token tail-hijack — direct unit tests
# ---------------------------------------------------------------------------


class TestZ3NonPossessiveTailHijack:
    """``accept_possessive_promotion`` must reject the non-possessive
    fuzzy_suggest hijack patterns the post-b8 live sweep surfaced.

    The b4 D2 raised-min_len protection covered only possessive
    topics; non-possessive multi-token queries leak the same hijack
    via Pass 0's full-topic probe at min_score=0.95.
    """

    @pytest.mark.parametrize(
        "topic, canonical_path",
        [
            # Live silent-wrong-answer repros at v2.0.0b8 (cert=0.85).
            # Each row's canonical is a single token equal to the
            # topic's last token — the tail-hijack pattern.
            ("Stalin USSR Russia", "Russia"),
            ("Hitler Germany Berlin", "Berlin"),
            ("Marie Curie polonium discovery", "Discovery"),
            ("Big Rapids Michigan tourism", "Tourism"),
            ("O'Brien character 1984", "1984"),
            # Generic disambiguator-style topics that share the
            # hijack shape.
            ("Apollo 11 mission year 1984", "1984"),
        ],
        ids=[
            "stalin_ussr_russia_tail_hijack",
            "hitler_germany_berlin_tail_hijack",
            "marie_curie_polonium_discovery_tail_hijack",
            "big_rapids_michigan_tourism_tail_hijack",
            "obrien_character_1984_tail_hijack",
            "apollo_11_mission_year_1984_tail_hijack",
        ],
    )
    def test_single_token_tail_hijack_rejected(
        self, topic: str, canonical_path: str
    ) -> None:
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": canonical_path,
            "title": canonical_path.replace("_", " "),
            "match_type": "fuzzy_suggest",
            "pre_redirect_path": canonical_path,
        }
        assert accept_possessive_promotion(promoted, topic) is False, (
            f"Z3 must reject {canonical_path!r} for topic {topic!r}: "
            f"canonical is a single token equal to topic's last token, "
            f"signalling libzim's fuzzy-suggest tail-token hijack."
        )

    def test_zero_overlap_stemming_match_rejected(self) -> None:
        """``Marie Curie radioactivity`` → ``Radioactive_(Redniss_book)``
        the live repro where libzim's stemming matches ``radioactive``
        to ``radioactivity`` and returns an obscure 2010 graphic novel.
        The canonical's tokens have ZERO exact overlap with the topic
        tokens (radioactive ≠ radioactivity exactly).
        """
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "Radioactive_(Redniss_book)",
            "title": "Radioactive (Redniss book)",
            "match_type": "fuzzy_suggest",
            "pre_redirect_path": "Radioactive_(Redniss_book)",
        }
        assert (
            accept_possessive_promotion(promoted, "Marie Curie radioactivity") is False
        )


# ---------------------------------------------------------------------------
# Z3: regression guards — counter-cases that MUST keep working
# ---------------------------------------------------------------------------


class TestZ3RegressionGuards:
    """Pin the non-possessive multi-token cases the live sweep
    confirmed currently work — Z3's fix must NOT regress these."""

    @pytest.mark.parametrize(
        "topic, canonical_path",
        [
            # Single-token canonical at the HEAD position of the topic
            # — the user's primary subject. ACCEPT.
            ("Hamlet Denmark prince", "Hamlet"),
            ("Napoleon France emperor", "Napoleon"),
            # Multi-token canonical, even when it matches the topic's
            # tail — ACCEPT. (The single-token rule fires only on
            # 1-token canonicals; multi-token canonicals signal a real
            # phrase match, not a hijack.)
            ("Apollo 11 moon landing", "Moon_landing"),
            ("Lincoln Gettysburg Address", "Gettysburg_Address"),
            # 2-token topic — the Z3 rule requires topic_tokens ≥ 3 so
            # this case (which already works via is_strong_title_match
            # at BM25 stage) stays unchanged. ACCEPT at the promotion
            # gate level too.
            ("Berlin Germany", "Berlin"),
        ],
        ids=[
            "hamlet_at_head_accept",
            "napoleon_at_head_accept",
            "apollo_11_moon_landing_multi_token_canonical_accept",
            "lincoln_gettysburg_address_multi_token_accept",
            "berlin_germany_2token_topic_accept",
        ],
    )
    def test_non_possessive_legitimate_match_accepted(
        self, topic: str, canonical_path: str
    ) -> None:
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": canonical_path,
            "title": canonical_path.replace("_", " "),
            "match_type": "fuzzy_suggest",
            "pre_redirect_path": canonical_path,
        }
        assert accept_possessive_promotion(promoted, topic) is True

    def test_quantum_mechanics_einstein_via_redirect(self) -> None:
        """``quantum mechanics Einstein`` → ``Albert_Einstein`` via a
        redirect from ``Einstein`` to ``Albert_Einstein``. Even though
        the canonical's tokens include the topic's last token, the
        match_type=redirect signals a semantic entity reference, not
        a tail hijack — and the canonical is 2 tokens (not 1)."""
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "Albert_Einstein",
            "title": "Albert Einstein",
            "match_type": "redirect",
            "pre_redirect_path": "Einstein",
        }
        assert (
            accept_possessive_promotion(promoted, "quantum mechanics Einstein") is True
        )

    def test_direct_match_unconditional(self) -> None:
        """``match_type="direct"`` is the strongest libzim signal —
        post-redirect title equals user input case-insensitively.
        Always ACCEPT, even for multi-token topics, regardless of
        canonical token count."""
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": "Russia",
            "title": "Russia",
            "match_type": "direct",
            "pre_redirect_path": "Russia",
        }
        # When the user literally types "Russia" (1 token), direct
        # match accepts (this is the existing single-token-topic
        # behavior; Z3 doesn't change it).
        assert accept_possessive_promotion(promoted, "Russia") is True


# ---------------------------------------------------------------------------
# OPP-1: possessive fuzzy_suggest carve-out
# ---------------------------------------------------------------------------


class TestOPP1PossessorInCanonical:
    """Possessive + fuzzy_suggest should ACCEPT iff the canonical path
    contains any of the topic's possessor tokens (the canonical
    preserves the user's named entity)."""

    @pytest.mark.parametrize(
        "topic, canonical_path, expected_accept",
        [
            # Live OPP-1 repro: canonical preserves the possessor →
            # ACCEPT, replaces blanket b6 D1 reject.
            (
                "Newton's gravity",
                "Newton's_law_of_universal_gravitation",
                True,
            ),
            # Another carve-out shape: canonical preserves the
            # possessor token (no apostrophe in canonical itself).
            ("Mary's lamb", "Mary_Had_a_Little_Lamb", True),
            # b6 D1 attack surface preserved: canonical DROPS the
            # possessor entirely → REJECT.
            ("Darwin's evolution", "Evolution", False),
            # Original b6 Z1 attack surface preserved: associative
            # canonical that shares a different token but not the
            # possessor → REJECT.
            (
                "Plato's republic philosophy",
                "Czech_philosophy",
                False,
            ),
            # Multi-possessor carve-out: canonical contains at least
            # ONE of the possessors → ACCEPT.
            (
                "John's and Mary's books",
                "Mary_Shelley_bibliography",
                True,
            ),
        ],
        ids=[
            "newtons_gravity_canonical_preserves_possessor_accept",
            "marys_lamb_canonical_preserves_possessor_accept",
            "darwins_evolution_possessor_dropped_reject",
            "platos_philosophy_associative_reject",
            "multi_possessor_one_match_accept",
        ],
    )
    def test_possessive_fuzzy_suggest_canonical_possessor_carveout(
        self, topic: str, canonical_path: str, expected_accept: bool
    ) -> None:
        from openzim_mcp.title_promotion import accept_possessive_promotion

        promoted = {
            "path": canonical_path,
            "title": canonical_path.replace("_", " "),
            "match_type": "fuzzy_suggest",
            "pre_redirect_path": canonical_path,
        }
        assert accept_possessive_promotion(promoted, topic) is expected_accept, (
            f"OPP-1: possessor-in-canonical carve-out wrong for "
            f"topic={topic!r}, canonical={canonical_path!r}"
        )

    def test_possessive_redirect_b8_subset_rule_unchanged(self) -> None:
        """The b8 Z1.1 subset rule must remain in force for
        possessive + redirect — OPP-1's fuzzy_suggest carve-out
        doesn't touch the redirect branch."""
        from openzim_mcp.title_promotion import accept_possessive_promotion

        # b8 Z1.1 truncation-redirect shape: pre_path has extras not in
        # topic → REJECT (existing b8 behavior, unchanged by post-b8).
        promoted = {
            "path": "Evolution",
            "title": "Evolution",
            "match_type": "redirect",
            "pre_redirect_path": "Darwin's_Theory_of_Evolution",
        }
        assert accept_possessive_promotion(promoted, "Darwin's evolution") is False


# ---------------------------------------------------------------------------
# Integration through _promote_topic_via_title_index
# ---------------------------------------------------------------------------


class TestZ3PromoteIntegration:
    """End-to-end shape: Pass 0's full-topic probe at min_score=0.95
    must REJECT the Z3 hijack canonicals and fall through to
    BM25 (None return)."""

    def test_stalin_ussr_russia_rejected_at_pass_0(self) -> None:
        """Live repro: Pass 0 returns ``Russia`` (fuzzy_suggest) at
        0.95 for ``Stalin USSR Russia``. Z3 rejects → no other tail/
        window resolves → return None → BM25 fallback."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "stalin ussr russia": {
                "path": "Russia",
                "title": "Russia",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
                "pre_redirect_path": "Russia",
            },
        }
        result = _run_promote_simple(
            "Stalin USSR Russia",
            _fake_find_title_match(mapping, min_score_floor=0.95),
        )
        assert (
            result is None
        ), f"Z3 must reject Russia for Stalin USSR Russia; got {result!r}"

    def test_hamlet_denmark_prince_still_accepts_at_pass_0(self) -> None:
        """Counter-case: Pass 0 returns ``Hamlet`` (fuzzy_suggest, but
        the canonical token equals topic's HEAD token, not tail).
        Z3's tail-hijack rule does NOT fire → accept → return Hamlet."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "hamlet denmark prince": {
                "path": "Hamlet",
                "title": "Hamlet",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
                "pre_redirect_path": "Hamlet",
            },
        }
        result = _run_promote_simple(
            "Hamlet Denmark prince",
            _fake_find_title_match(mapping, min_score_floor=0.95),
        )
        assert result is not None and result["path"] == "Hamlet"

    def test_newtons_gravity_accepted_at_pass_0_via_opp1(self) -> None:
        """OPP-1 carve-out: Pass 0 returns
        ``Newton's_law_of_universal_gravitation`` (fuzzy_suggest) for
        ``Newton's gravity``. Pre-OPP-1: b6 D1 blanket-rejected.
        Post-OPP-1: canonical contains the possessor ``Newton`` →
        accept → return canonical."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "newton's gravity": {
                "path": "Newton's_law_of_universal_gravitation",
                "title": "Newton's law of universal gravitation",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
                "pre_redirect_path": "Newton's_law_of_universal_gravitation",
            },
        }
        result = _run_promote_simple(
            "Newton's gravity",
            _fake_find_title_match(mapping, min_score_floor=0.95),
        )
        assert (
            result is not None
            and result["path"] == "Newton's_law_of_universal_gravitation"
        )


# ---------------------------------------------------------------------------
# Structural pins
# ---------------------------------------------------------------------------


class TestStructuralGuards:
    """Lightweight pins that catch accidental revert of the Z3 / OPP-1
    refinements at the source level."""

    def test_accept_possessive_promotion_dispatches_to_per_branch_helpers(
        self,
    ) -> None:
        """Structural pin: ``accept_possessive_promotion`` dispatches
        to dedicated per-branch helpers. Catches an accidental revert
        that re-inlines the Z3 / OPP-1 logic (and re-raises Sonar
        cognitive-complexity over 15).

        The function should resolve the topic-shape (non-possessive
        vs possessive) and the match_type, then delegate to the
        helper for that combination. Each helper owns its own
        comment block explaining the safety reasoning.
        """
        import inspect

        from openzim_mcp import title_promotion

        # Per-branch helpers must exist (importable from the module).
        assert hasattr(title_promotion, "_accept_non_possessive")
        assert hasattr(title_promotion, "_accept_possessive_fuzzy_suggest")
        assert hasattr(title_promotion, "_accept_possessive_redirect")

        # The dispatcher's source must reference each helper at least
        # once — keeps the dispatch table from atrophying.
        source = inspect.getsource(title_promotion.accept_possessive_promotion)
        assert "_accept_non_possessive" in source
        assert "_accept_possessive_fuzzy_suggest" in source
        assert "_accept_possessive_redirect" in source

    def test_non_possessive_helper_handles_fuzzy_suggest_branch(self) -> None:
        """Structural pin: ``_accept_non_possessive`` must reference
        ``fuzzy_suggest`` so the Z3 rule (the non-possessive branch
        Z3 fix lives in) isn't accidentally short-circuited back to
        ``return True``. Earlier b6 D1 reference lives in the
        ``_accept_possessive_fuzzy_suggest`` helper."""
        import inspect

        from openzim_mcp import title_promotion

        np_source = inspect.getsource(title_promotion._accept_non_possessive)
        assert "fuzzy_suggest" in np_source, (
            "_accept_non_possessive must check match_type=fuzzy_suggest "
            "(the Z3 gate) — see post-b8 sweep"
        )
