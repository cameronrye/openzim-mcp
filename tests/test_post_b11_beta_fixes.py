r"""Regression tests for the post-b11 beta-test sweep.

The post-b11 live-MCP sweep against v2.0.0b11 confirmed the b10
probe-based multi-entity discriminator delivers on its 3-entity
single-token-tail target shape (4/6 historical Z3 repros now route
to the correct head). Two new defect classes surfaced:

## Z4 (HIGH, silent-wrong cert=0.85) — multi-token canonical tangential

``is_tail_hijack_shape`` only fires when canonical is single-token
AND topic has 3+ tokens. When the silent-wrong-answer pattern
manifests with a multi-token canonical or a 2-token topic, the b11
discriminator never fires and the wrong promotion ships at cert=0.85.

Live repros at v2.0.0b11 (all cert=0.85, all silent-wrong):

  * ``Lenin Russia`` → ``Leninist_Komsomol_of_the_Russian_Federation``
    (head ``Vladimir_Lenin`` skipped). 2-token topic + multi-token
    canonical with stem-overlap on both tokens.
  * ``Tesla electricity`` → ``Tesla's_Wireless_Electricity``
    (head ``Nikola_Tesla`` skipped). Canonical contains head as
    possessive subordinate + adds modifier ``wireless`` not in topic.
  * ``Mozart Vienna`` → ``Mozarthaus_Vienna``
    (head ``Wolfgang_Amadeus_Mozart`` skipped). Canonical contains
    head as prefix of subordinate token + adds modifier ``haus``.
  * ``Beethoven symphony`` → ``Symphony_No._1_(Beethoven)``
    (head ``Ludwig_van_Beethoven`` skipped). Canonical contains head
    as parenthetical + adds specific-instance digit not in topic.
  * ``Marie Curie radioactivity`` → ``Radioactive_(Redniss_book)``
    (head ``Marie_Curie`` skipped). Canonical surfaces via tail-stem
    only; rest of canonical is unrelated graphic-novel metadata.
  * ``Shakespeare England plays`` → ``Shakespeare's_Kings``
    (head ``William_Shakespeare`` skipped). Canonical contains head
    as possessive subordinate; topic modifier tokens not covered.
  * ``Darwin evolution Galapagos`` → ``Galápagos_Islands``
    (head ``Charles_Darwin`` skipped). Canonical surfaces via tail
    only (place name); rest of topic ignored.
  * ``Mao China revolution`` → ``History_of_the_People's_Republic_of_China_(1949–1976)``
    (head ``Mao_Zedong`` skipped). Canonical shares only the middle
    topic token ``china``.

## Fix shape — Z4 tangential promotion check with two exemptions

Three new helpers in ``title_promotion``:

  * ``is_tangential_multi_token_shape(promoted, topic)`` — pure-logic
    shape: canonical is multi-token AND not a token-set subset of
    topic. The subset rule preserves the b8 ``Apollo 11 moon landing``
    → ``Moon_landing`` invariant (canonical ⊆ topic = generalization,
    not tangential) and the b4 ``Lincoln Gettysburg Address`` →
    ``Gettysburg_Address`` invariant (same shape).
  * ``probed_head_matches_promoted(topic, promoted, title_probe)`` —
    biographical-canonical exemption: probes the topic's first non-
    stop-word token. If the head probe's canonical path (or pre-
    redirect path) equals the promoted candidate's path, the
    promotion IS the head's biographical article (e.g.,
    ``Picasso Paris cubism`` → ``Pablo_Picasso`` because probing
    ``picasso`` returns ``Pablo_Picasso`` via redirect). Exempt.
  * ``has_digit_specificity_match(promoted, topic)`` — digit
    specificity exemption: when canonical's extras (tokens not in
    topic) include a digit AND topic also has a digit/ordinal token,
    the user explicitly signaled they want a numbered instance
    (``Beethoven 9th symphony`` → ``Symphony_No._9_(Beethoven)``).
    Without this exemption Z4 over-rejects the legitimate numbered
    sub-article case.

``_promote_topic_via_title_index``'s ``_accept_with_multi_entity_check``
layers the Z4 check after the existing Z3 logic. The same gate is now
applied at Pass 0 (full-topic probe) and Pass 3 (typo-tolerant) — Z4
defects surface across all four passes, so the gate must be
consistent.

## Decision matrix

  +-----------------------------------+--------+-------+-------+----------+
  | Topic                             | Multi- | Bio   | Digit | Decision |
  |                                   | token  | exem  | exem  |          |
  |                                   | tangent|       |       |          |
  +-----------------------------------+--------+-------+-------+----------+
  | Tesla electricity                 | yes    | no    | no    | REJECT   |
  | Mozart Vienna                     | yes    | no    | no    | REJECT   |
  | Beethoven symphony                | yes    | no    | no    | REJECT   |
  | Lenin Russia                      | yes    | no    | no    | REJECT   |
  | Marie Curie radioactivity         | yes    | no    | no    | REJECT   |
  | Shakespeare England plays         | yes    | no    | no    | REJECT   |
  | Darwin evolution Galapagos        | yes    | no    | no    | REJECT   |
  | Mao China revolution              | yes    | no    | no    | REJECT   |
  | Picasso Paris cubism              | yes    | YES   | -     | ACCEPT   |
  | Beethoven 9th symphony            | yes    | no    | YES   | ACCEPT   |
  | Apollo 11 moon landing            | no(⊆)  | -     | -     | ACCEPT   |
  | Lincoln Gettysburg Address        | no(⊆)  | -     | -     | ACCEPT   |
  | Newton's gravity (possessive)     | -      | -     | -     | ACCEPT   |
  |   (Z4 doesn't apply to possessive — OPP-1 handles)                    |
  | Hamlet Denmark prince             | no(1tk)| -     | -     | ACCEPT   |
  | Berlin Germany                    | no(1tk)| -     | -     | ACCEPT   |
  | what is the population of detroit | no(1tk)| -     | -     | ACCEPT   |
  +-----------------------------------+--------+-------+-------+----------+
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import patch

from tests._promote_fixtures import fake_find_title_match as _fake_find_title_match
from tests._promote_fixtures import make_disambig_handler as _make_disambig_handler
from tests._promote_fixtures import make_simple_handler as _make_simple_handler


def _run_promote(
    topic: str, mapping: Dict[str, Optional[Dict[str, Any]]]
) -> Optional[Dict[str, Any]]:
    """Drive ``_promote_topic_via_title_index`` with the mapping
    serving as the find_title_match stand-in for every probe."""
    from openzim_mcp.simple_tools import SimpleToolsHandler

    fake = _fake_find_title_match(mapping)
    # Phase F: live ``find_title_match`` binding moved to
    # ``openzim_mcp.topic_preprocessing`` during the extraction refactor.
    with patch("openzim_mcp.topic_preprocessing.find_title_match", side_effect=fake):
        return SimpleToolsHandler._promote_topic_via_title_index(
            _make_simple_handler(),
            "test.zim",
            topic,
        )


# ---------------------------------------------------------------------------
# Live Z4 silent-wrong-answer cases — must reject tangential multi-token
# canonical when the head's biographical article exists and differs.
# ---------------------------------------------------------------------------


class TestZ4MultiTokenCanonicalRejected:
    """When the promoted canonical is multi-token AND NOT a token-set
    subset of topic AND the topic head's biographical article exists
    and differs, the promotion is tangential and must be rejected. Pass
    2 then tries head-token windows; when those resolve cleanly, that's
    the auto-fetched result instead."""

    def test_lenin_russia_rejects_leninist_komsomol(self) -> None:
        """2-token topic, multi-token canonical with stem-overlap on
        both tokens (lenin→leninist, russia→russian). Head ``lenin``
        probes to ``Vladimir_Lenin`` (distinct from promoted) →
        tangential → reject."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "lenin russia": {
                "path": "Leninist_Komsomol_of_the_Russian_Federation",
                "title": "Leninist Komsomol of the Russian Federation",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "russia": {
                "path": "Russia",
                "title": "Russia",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "lenin": {
                "path": "Vladimir_Lenin",
                "title": "Vladimir Lenin",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Lenin",
            },
        }
        result = _run_promote("lenin russia", mapping)
        assert result is None or (
            result["path"] != "Leninist_Komsomol_of_the_Russian_Federation"
        ), (
            "Z4 must reject tangential multi-token canonical "
            f"`Leninist_Komsomol_...` when head probe `Vladimir_Lenin` "
            f"differs. Got: {result!r}"
        )

    def test_tesla_electricity_rejects_wireless_electricity(self) -> None:
        """2-token topic, canonical contains head as possessive + adds
        modifier ``wireless`` not in topic. Head probe distinct →
        tangential → reject."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "tesla electricity": {
                "path": "Tesla's_Wireless_Electricity",
                "title": "Tesla's Wireless Electricity",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "electricity": {
                "path": "Electricity",
                "title": "Electricity",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "tesla": {
                "path": "Nikola_Tesla",
                "title": "Nikola Tesla",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Tesla",
            },
        }
        result = _run_promote("tesla electricity", mapping)
        assert result is None or result["path"] != "Tesla's_Wireless_Electricity"

    def test_mozart_vienna_rejects_mozarthaus(self) -> None:
        """Canonical ``Mozarthaus_Vienna`` adds ``mozarthaus`` extra
        not in topic; head probe ``mozart`` differs."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "mozart vienna": {
                "path": "Mozarthaus_Vienna",
                "title": "Mozarthaus Vienna",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "vienna": {
                "path": "Vienna",
                "title": "Vienna",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "mozart": {
                "path": "Wolfgang_Amadeus_Mozart",
                "title": "Wolfgang Amadeus Mozart",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Mozart",
            },
        }
        result = _run_promote("mozart vienna", mapping)
        assert result is None or result["path"] != "Mozarthaus_Vienna"

    def test_beethoven_symphony_rejects_specific_symphony(self) -> None:
        """Canonical ``Symphony_No._1_(Beethoven)`` has digit extra ``1``
        but topic ``beethoven symphony`` has NO digit → digit-specificity
        exemption does NOT apply → tangential → reject."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "beethoven symphony": {
                "path": "Symphony_No._1_(Beethoven)",
                "title": "Symphony No. 1 (Beethoven)",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "symphony": {
                "path": "Symphony",
                "title": "Symphony",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "beethoven": {
                "path": "Ludwig_van_Beethoven",
                "title": "Ludwig van Beethoven",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Beethoven",
            },
        }
        result = _run_promote("beethoven symphony", mapping)
        assert result is None or result["path"] != "Symphony_No._1_(Beethoven)"

    def test_marie_curie_radioactivity_rejects_redniss_book(self) -> None:
        """3-token topic, multi-token canonical with NO token-set
        overlap on raw tokens (radioactive ≠ radioactivity). Head
        probe distinct → tangential → reject."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "marie curie radioactivity": {
                "path": "Radioactive_(Redniss_book)",
                "title": "Radioactive (Redniss book)",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "radioactivity": {
                "path": "Radioactive_decay",
                "title": "Radioactive decay",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Radioactivity",
            },
            "marie curie": {
                "path": "Marie_Curie",
                "title": "Marie Curie",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "curie radioactivity": None,
            "marie": {
                "path": "Marie",
                "title": "Marie",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "curie": {
                "path": "Curie",
                "title": "Curie",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote("marie curie radioactivity", mapping)
        assert result is None or result["path"] != "Radioactive_(Redniss_book)"

    def test_shakespeare_england_plays_rejects_shakespeare_kings(self) -> None:
        """Canonical has head as possessive (``Shakespeare's``) +
        adds non-topic noun ``kings``."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "shakespeare england plays": {
                "path": "Shakespeare's_Kings",
                "title": "Shakespeare's Kings",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "shakespeare england": None,
            "england plays": None,
            "plays": {
                "path": "Plays",
                "title": "Plays",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "shakespeare": {
                "path": "William_Shakespeare",
                "title": "William Shakespeare",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Shakespeare",
            },
            "england": {
                "path": "England",
                "title": "England",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote("shakespeare england plays", mapping)
        assert result is None or result["path"] != "Shakespeare's_Kings"

    def test_darwin_evolution_galapagos_rejects_galapagos_islands(self) -> None:
        """Multi-token canonical surfaces via tail-only; head ``darwin``
        biographical article exists and differs."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "darwin evolution galapagos": {
                "path": "Galápagos_Islands",
                "title": "Galápagos Islands",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "evolution galapagos": None,
            "galapagos": {
                "path": "Galápagos_Islands",
                "title": "Galápagos Islands",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "darwin": {
                "path": "Charles_Darwin",
                "title": "Charles Darwin",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Darwin",
            },
            "evolution": {
                "path": "Evolution",
                "title": "Evolution",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote("darwin evolution galapagos", mapping)
        assert result is None or result["path"] != "Galápagos_Islands"

    def test_mao_china_revolution_rejects_china_history(self) -> None:
        """Multi-token canonical shares only the middle topic token
        (``china``); head ``mao`` biographical article differs."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "mao china revolution": {
                "path": "History_of_the_People's_Republic_of_China_(1949-1976)",
                "title": "History of the People's Republic of China (1949-1976)",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "china revolution": None,
            "revolution": {
                "path": "Revolution",
                "title": "Revolution",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "mao": {
                "path": "Mao_Zedong",
                "title": "Mao Zedong",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Mao",
            },
            "china": {
                "path": "China",
                "title": "China",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote("mao china revolution", mapping)
        assert (
            result is None
            or result["path"] != "History_of_the_People's_Republic_of_China_(1949-1976)"
        )


# ---------------------------------------------------------------------------
# Counter-cases: legitimate multi-token canonicals must still promote.
# ---------------------------------------------------------------------------


class TestZ4PreservedCases:
    """Z4 must NOT over-reject the documented preserved cases.

    Three exemption paths protect legitimate multi-token promotions:
    (1) subset rule (canonical ⊆ topic = generalization),
    (2) biographical exemption (head probe matches promoted path),
    (3) digit-specificity exemption (canonical extras digit ∧ topic digit).
    """

    def test_apollo_11_moon_landing_subset_accepts(self) -> None:
        """``Moon_landing`` tokens ⊆ ``apollo 11 moon landing`` tokens →
        subset rule → canonical is generalization → accept."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "apollo 11 moon landing": {
                "path": "Moon_landing",
                "title": "Moon landing",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "11 moon landing": None,
            "moon landing": {
                "path": "Moon_landing",
                "title": "Moon landing",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "apollo": {
                "path": "Apollo",
                "title": "Apollo",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote("apollo 11 moon landing", mapping)
        assert result is not None and result["path"] == "Moon_landing"

    def test_lincoln_gettysburg_address_subset_accepts(self) -> None:
        """``Gettysburg_Address`` tokens ⊆ ``lincoln gettysburg address``
        tokens → subset rule → accept."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "lincoln gettysburg address": {
                "path": "Gettysburg_Address",
                "title": "Gettysburg Address",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "gettysburg address": {
                "path": "Gettysburg_Address",
                "title": "Gettysburg Address",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "lincoln": {
                "path": "Lincoln",
                "title": "Lincoln",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote("lincoln gettysburg address", mapping)
        assert result is not None and result["path"] == "Gettysburg_Address"

    def test_picasso_paris_cubism_biographical_accepts(self) -> None:
        """Head probe ``picasso`` resolves to ``Pablo_Picasso`` = the
        promoted candidate → biographical exemption → accept."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "picasso paris cubism": {
                "path": "Pablo_Picasso",
                "title": "Pablo Picasso",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Picasso",
            },
            "picasso": {
                "path": "Pablo_Picasso",
                "title": "Pablo Picasso",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Picasso",
            },
            "paris": {
                "path": "Paris",
                "title": "Paris",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "cubism": {
                "path": "Cubism",
                "title": "Cubism",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote("picasso paris cubism", mapping)
        assert result is not None and result["path"] == "Pablo_Picasso"

    def test_beethoven_9th_symphony_digit_accepts(self) -> None:
        """Canonical extras ``{no, 9}`` include digit AND topic
        ``{beethoven, 9th, symphony}`` includes a digit token →
        digit-specificity exemption → accept the specific symphony."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "beethoven 9th symphony": {
                "path": "Symphony_No._9_(Beethoven)",
                "title": "Symphony No. 9 (Beethoven)",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "9th symphony": {
                "path": "Symphony_No._9_(Beethoven)",
                "title": "Symphony No. 9 (Beethoven)",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "symphony": {
                "path": "Symphony",
                "title": "Symphony",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "beethoven": {
                "path": "Ludwig_van_Beethoven",
                "title": "Ludwig van Beethoven",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Beethoven",
            },
        }
        result = _run_promote("beethoven 9th symphony", mapping)
        assert result is not None and result["path"] == "Symphony_No._9_(Beethoven)"

    def test_hamlet_denmark_prince_single_token_canonical(self) -> None:
        """Single-token canonical is not Z4 tangential shape (b9
        invariant: HEAD-position single token accepted)."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "hamlet denmark prince": {
                "path": "Hamlet",
                "title": "Hamlet",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "denmark prince": None,
            "prince": None,
            "hamlet": {
                "path": "Hamlet",
                "title": "Hamlet",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "denmark": None,
        }
        result = _run_promote("hamlet denmark prince", mapping)
        assert result is not None and result["path"] == "Hamlet"

    def test_berlin_germany_two_token_topic_single_canonical(self) -> None:
        """2-token topic with single-token canonical = head → b4
        carve-out preserved."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "berlin germany": {
                "path": "Berlin",
                "title": "Berlin",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "germany": None,
            "berlin": {
                "path": "Berlin",
                "title": "Berlin",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote("berlin germany", mapping)
        assert result is not None and result["path"] == "Berlin"

    def test_population_of_detroit_filler_prose_accepts(self) -> None:
        """Filler prose with single-token tail-canonical: b11 Z3 multi-
        entity discriminator returns count<2 (only ``population``
        probes) → tail accepted."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "detroit": {
                "path": "Detroit",
                "title": "Detroit",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "population": {
                "path": "Population",
                "title": "Population",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote("what is the population of detroit", mapping)
        assert result is not None and result["path"] == "Detroit"

    def test_newtons_gravity_possessive_unaffected(self) -> None:
        """Possessive topics route through OPP-1 (accept_possessive_promotion),
        not Z4. ``Newton's gravity`` → ``Newton's_law_of_universal_gravitation``
        accepted because canonical contains possessor token ``newton``."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "newton's gravity": {
                "path": "Newton's_law_of_universal_gravitation",
                "title": "Newton's law of universal gravitation",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Newton's_law_of_gravity",
            },
        }
        result = _run_promote("newton's gravity", mapping)
        assert (
            result is not None
            and result["path"] == "Newton's_law_of_universal_gravitation"
        )

    def test_quantum_mechanics_einstein_tail_subject_accepts(self) -> None:
        """Post-b11 second-pass: the user's pinned counter-case
        ``quantum mechanics Einstein`` → ``Albert_Einstein`` has the
        subject at the TAIL of the topic, not the head. The
        biographical exemption must probe ALL non-stop-word tokens
        (not just the first) so the tail-position ``einstein`` probe
        catches the match. Token-in-canonical guard prevents
        accidental over-acceptance: ``einstein`` is literally in
        ``Albert_Einstein`` tokens, AND ``einstein`` probes to the
        same canonical."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "quantum mechanics einstein": {
                "path": "Albert_Einstein",
                "title": "Albert Einstein",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "mechanics einstein": None,
            "einstein": {
                "path": "Albert_Einstein",
                "title": "Albert Einstein",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Einstein",
            },
            "quantum": {
                "path": "Quantum_mechanics",
                "title": "Quantum mechanics",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "mechanics": {
                "path": "Mechanics",
                "title": "Mechanics",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote("quantum mechanics einstein", mapping)
        assert result is not None and result["path"] == "Albert_Einstein"

    def test_jfk_assassination_canonical_with_of_extra_accepts(self) -> None:
        """Post-b11 second-pass: canonical extras of pure function
        words (``of``, ``the``, ``and``) shouldn't flag the canonical
        as tangential. ``Assassination_of_John_F._Kennedy`` for topic
        ``John F Kennedy assassination`` — canonical's only extra is
        ``of`` (a preposition); after the canonical-subset stop-word
        filter, canonical {assassination, john, f, kennedy} ⊆ topic
        → subset → accept via subset rule (no exemption needed)."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "john f kennedy assassination": {
                "path": "Assassination_of_John_F._Kennedy",
                "title": "Assassination of John F. Kennedy",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "f kennedy assassination": None,
            "kennedy assassination": {
                "path": "Assassination_of_John_F._Kennedy",
                "title": "Assassination of John F. Kennedy",
                "zim_file": "test.zim",
                "match_type": "fuzzy_suggest",
            },
            "kennedy": {
                "path": "John_F._Kennedy",
                "title": "John F. Kennedy",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Kennedy",
            },
            "assassination": {
                "path": "Assassination",
                "title": "Assassination",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "john": {
                "path": "John",
                "title": "John",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "f": None,
        }
        result = _run_promote("john f kennedy assassination", mapping)
        assert (
            result is not None and result["path"] == "Assassination_of_John_F._Kennedy"
        )

    def test_ferris_state_type_extension_accepts(self) -> None:
        """Type-extension exemption: ``Ferris_State_University`` for
        topic ``Big Rapids Michigan Ferris State`` — canonical's leading
        2 tokens (``ferris state``) form a contiguous slice of topic,
        canonical's suffix (``university``) is the type-word extra.
        Without this exemption Z4 would over-reject the b8/b9 motivating
        case where the user's TAIL is the canonical's entity-name
        without the type-word suffix."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "big rapids michigan ferris state": None,
            "rapids michigan ferris state": None,
            "michigan ferris state": None,
            "ferris state": {
                "path": "Ferris_State_University",
                "title": "Ferris State University",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "big": None,
            "rapids": None,
            "michigan": {
                "path": "Michigan",
                "title": "Michigan",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "ferris": None,
            "state": None,
        }
        result = _run_promote("Big Rapids Michigan Ferris State", mapping)
        assert result is not None and result["path"] == "Ferris_State_University"


# ---------------------------------------------------------------------------
# Direct unit tests on the type-extension helper.
# ---------------------------------------------------------------------------


class TestHasTopicPrefixCanonicalExtension:
    """Z4 type-extension exemption: canonical's leading tokens form a
    contiguous slice of topic (length ≥ 2), canonical's suffix tokens
    are all extras (not in topic)."""

    def test_ferris_state_university_accepts(self) -> None:
        from openzim_mcp.title_promotion import has_topic_prefix_canonical_extension

        promoted = {"path": "Ferris_State_University"}
        assert (
            has_topic_prefix_canonical_extension(
                promoted, "big rapids michigan ferris state"
            )
            is True
        )

    def test_tesla_wireless_electricity_rejects(self) -> None:
        """``tesla's`` ≠ ``tesla`` (raw token comparison) — no contiguous
        topic slice matches canonical prefix."""
        from openzim_mcp.title_promotion import has_topic_prefix_canonical_extension

        promoted = {"path": "Tesla's_Wireless_Electricity"}
        assert (
            has_topic_prefix_canonical_extension(promoted, "tesla electricity") is False
        )

    def test_short_canonical_returns_false(self) -> None:
        """Single-token canonical: type-extension shape requires
        canonical of length 2+ (the matched slice + at least 1
        extra)."""
        from openzim_mcp.title_promotion import has_topic_prefix_canonical_extension

        promoted = {"path": "Hamlet"}
        assert (
            has_topic_prefix_canonical_extension(promoted, "hamlet denmark prince")
            is False
        )

    def test_short_topic_returns_false(self) -> None:
        from openzim_mcp.title_promotion import has_topic_prefix_canonical_extension

        promoted = {"path": "Pablo_Picasso"}
        assert has_topic_prefix_canonical_extension(promoted, "picasso") is False

    def test_suffix_overlap_with_topic_rejects(self) -> None:
        """If any canonical suffix token ALSO appears in topic, it's
        not a clean type-extension — the canonical's "extras" aren't
        all extras. Falls back to the shorter prefix search."""
        from openzim_mcp.title_promotion import has_topic_prefix_canonical_extension

        # Topic "alpha beta gamma delta epsilon", canonical "alpha beta delta":
        # canonical prefix [alpha, beta] matches topic slice [alpha, beta],
        # but suffix [delta] is ALSO in topic → not clean → fall through.
        # No other prefix matches → False.
        promoted = {"path": "Alpha_Beta_Delta"}
        assert (
            has_topic_prefix_canonical_extension(
                promoted, "alpha beta gamma delta epsilon"
            )
            is False
        )

    def test_canonical_prefix_anywhere_in_topic(self) -> None:
        """The matched slice can appear anywhere in topic, not just at
        the tail. Topic ``tourist Ferris State Michigan`` → canonical
        ``Ferris_State_University`` matches at topic positions 1-2."""
        from openzim_mcp.title_promotion import has_topic_prefix_canonical_extension

        promoted = {"path": "Ferris_State_University"}
        assert (
            has_topic_prefix_canonical_extension(
                promoted, "tourist ferris state michigan"
            )
            is True
        )


# ---------------------------------------------------------------------------
# Direct unit tests on the new helpers
# ---------------------------------------------------------------------------


class TestIsTangentialMultiTokenShape:
    """Pure-logic shape predicate: canonical is multi-token AND NOT a
    token-set subset of topic. Excludes single-token canonicals (covered
    by ``is_tail_hijack_shape``) and topic-subset canonicals (the
    generalization pattern preserved by Apollo / Lincoln / Gettysburg
    tests)."""

    def test_multi_token_with_extras_returns_true(self) -> None:
        from openzim_mcp.title_promotion import is_tangential_multi_token_shape

        promoted = {"path": "Tesla's_Wireless_Electricity"}
        assert is_tangential_multi_token_shape(promoted, "tesla electricity") is True

    def test_subset_returns_false(self) -> None:
        """Canonical tokens ⊆ topic tokens → generalization, not tangential."""
        from openzim_mcp.title_promotion import is_tangential_multi_token_shape

        promoted = {"path": "Moon_landing"}
        assert (
            is_tangential_multi_token_shape(promoted, "apollo 11 moon landing") is False
        )

    def test_single_token_canonical_returns_false(self) -> None:
        """Single-token canonicals are is_tail_hijack_shape territory."""
        from openzim_mcp.title_promotion import is_tangential_multi_token_shape

        promoted = {"path": "Russia"}
        assert is_tangential_multi_token_shape(promoted, "stalin ussr russia") is False

    def test_short_topic_returns_false(self) -> None:
        """Topic with <2 tokens has no head/modifier distinction."""
        from openzim_mcp.title_promotion import is_tangential_multi_token_shape

        promoted = {"path": "Pablo_Picasso"}
        assert is_tangential_multi_token_shape(promoted, "picasso") is False

    def test_empty_promoted_path_returns_false(self) -> None:
        """Defensive: empty path defaults to no shape."""
        from openzim_mcp.title_promotion import is_tangential_multi_token_shape

        assert is_tangential_multi_token_shape({}, "tesla electricity") is False

    def test_canonical_function_word_extras_filtered(self) -> None:
        """Function-word extras (``of``, ``the``, ``and``, ``in``) in
        canonical don't flag the canonical as tangential — they're
        structural tokens that smear into paths like
        ``Constitution_of_the_United_States`` or
        ``Assassination_of_John_F._Kennedy`` without changing the
        canonical's identity."""
        from openzim_mcp.title_promotion import is_tangential_multi_token_shape

        # ``Assassination_of_John_F._Kennedy`` has only ``of`` as a
        # non-topic extra; after the canonical-function-word filter,
        # the canonical reduces to {assassination, john, f, kennedy}
        # which IS a subset of the topic.
        promoted = {"path": "Assassination_of_John_F._Kennedy"}
        assert (
            is_tangential_multi_token_shape(promoted, "john f kennedy assassination")
            is False
        )

    def test_canonical_lexical_word_extra_stays_tangential(self) -> None:
        """Lexical-word extras (verbs like ``made``, ``lived``) ARE
        kept — they carry meaning. Topic ``USA products`` →
        ``Made_in_USA`` would over-accept if we filtered ``made`` from
        canonical; the user didn't ask for the ``Made in USA`` label
        specifically."""
        from openzim_mcp.title_promotion import is_tangential_multi_token_shape

        promoted = {"path": "Made_in_USA"}
        # ``in`` is filtered (preposition); ``made`` is NOT (verb).
        # Filtered canonical = {made, usa}; topic = {usa, products};
        # ``made`` is not in topic → NOT subset → tangential.
        assert is_tangential_multi_token_shape(promoted, "usa products") is True


class TestProbedHeadMatchesPromoted:
    """Biographical-canonical exemption: probe the topic's first non-
    stop-word token; True iff the probe path (or pre_redirect_path)
    equals the promoted candidate's path."""

    def test_head_probe_matches_promoted_via_redirect(self) -> None:
        from openzim_mcp.title_promotion import probed_head_matches_promoted

        def probe(token: str) -> Optional[Dict[str, Any]]:
            return {
                "picasso": {
                    "path": "Pablo_Picasso",
                    "pre_redirect_path": "Picasso",
                }
            }.get(token)

        promoted = {"path": "Pablo_Picasso"}
        assert (
            probed_head_matches_promoted("picasso paris cubism", promoted, probe)
            is True
        )

    def test_head_probe_matches_promoted_via_pre_path(self) -> None:
        """If the probe's pre_redirect_path equals promoted's path (the
        promoted IS the redirect entry), accept."""
        from openzim_mcp.title_promotion import probed_head_matches_promoted

        def probe(token: str) -> Optional[Dict[str, Any]]:
            return {
                "tesla": {
                    "path": "Nikola_Tesla",
                    "pre_redirect_path": "Tesla",
                }
            }.get(token)

        promoted = {"path": "Tesla"}
        assert (
            probed_head_matches_promoted("tesla electricity", promoted, probe) is True
        )

    def test_head_probe_differs_returns_false(self) -> None:
        from openzim_mcp.title_promotion import probed_head_matches_promoted

        def probe(token: str) -> Optional[Dict[str, Any]]:
            return {
                "lenin": {
                    "path": "Vladimir_Lenin",
                    "pre_redirect_path": "Lenin",
                }
            }.get(token)

        promoted = {"path": "Leninist_Komsomol_of_the_Russian_Federation"}
        assert probed_head_matches_promoted("lenin russia", promoted, probe) is False

    def test_head_probe_returns_none_returns_false(self) -> None:
        from openzim_mcp.title_promotion import probed_head_matches_promoted

        def probe(token: str) -> Optional[Dict[str, Any]]:
            return None

        promoted = {"path": "Some_Multi_Token_Article"}
        assert (
            probed_head_matches_promoted("obscure entity word", promoted, probe)
            is False
        )

    def test_stop_word_head_skipped(self) -> None:
        """Topic starting with stop words: head is first content token."""
        from openzim_mcp.title_promotion import probed_head_matches_promoted

        def probe(token: str) -> Optional[Dict[str, Any]]:
            # ``the`` is a stop word → skipped; ``picasso`` is the
            # effective head.
            if token == "picasso":
                return {
                    "path": "Pablo_Picasso",
                    "pre_redirect_path": "Picasso",
                }
            return None

        promoted = {"path": "Pablo_Picasso"}
        assert (
            probed_head_matches_promoted("the picasso paintings", promoted, probe)
            is True
        )

    def test_tail_position_subject_matches(self) -> None:
        """Subject at tail of topic (not head). ``quantum mechanics
        einstein`` — head ``quantum`` doesn't match promoted, but
        tail ``einstein`` probes to the same canonical AND is
        literally in canonical tokens."""
        from openzim_mcp.title_promotion import probed_head_matches_promoted

        def probe(token: str) -> Optional[Dict[str, Any]]:
            return {
                "quantum": {"path": "Quantum_mechanics"},
                "mechanics": {"path": "Mechanics"},
                "einstein": {
                    "path": "Albert_Einstein",
                    "pre_redirect_path": "Einstein",
                },
            }.get(token)

        promoted = {"path": "Albert_Einstein"}
        assert (
            probed_head_matches_promoted("quantum mechanics einstein", promoted, probe)
            is True
        )

    def test_token_in_canonical_guard_blocks_accent_mismatch(self) -> None:
        """Token-in-canonical guard: ``galapagos`` probes to
        ``Galápagos_Islands`` (path match) BUT ``galapagos`` ≠
        ``galápagos`` raw token → not in canonical → not exempt.
        This is what saves ``Darwin evolution Galapagos`` from being
        over-accepted by an accent-tolerant title-suggest hit."""
        from openzim_mcp.title_promotion import probed_head_matches_promoted

        def probe(token: str) -> Optional[Dict[str, Any]]:
            return {
                "darwin": {"path": "Charles_Darwin"},
                "evolution": {"path": "Evolution"},
                "galapagos": {"path": "Galápagos_Islands"},
            }.get(token)

        promoted = {"path": "Galápagos_Islands"}
        # ``galapagos`` (no accent) is not in canonical tokens
        # ``{galápagos, islands}`` due to accent → guard fails → False.
        assert (
            probed_head_matches_promoted("darwin evolution galapagos", promoted, probe)
            is False
        )

    def test_probe_exception_swallowed_returns_false(self) -> None:
        """Defensive: a flaky probe must not blow up the gate. The
        token-in-canonical pre-filter normally short-circuits before
        the probe is called, so this test uses a topic where a token
        IS in canonical (``some`` in ``Some_Article``) so the probe
        actually runs and the exception path is exercised."""
        from openzim_mcp.title_promotion import probed_head_matches_promoted

        def probe(token: str) -> Optional[Dict[str, Any]]:
            raise RuntimeError("transient libzim error")

        promoted = {"path": "Some_Article"}
        assert (
            probed_head_matches_promoted("some other topic", promoted, probe) is False
        )


class TestHasDigitSpecificityMatch:
    """Digit-specificity exemption: canonical's extras (tokens not in
    topic) include a digit AND topic also has a digit-bearing token.
    Without this exemption Z4 over-rejects numbered sub-articles like
    ``Symphony_No._9_(Beethoven)`` for ``beethoven 9th symphony``."""

    def test_both_have_digits_returns_true(self) -> None:
        from openzim_mcp.title_promotion import has_digit_specificity_match

        promoted = {"path": "Symphony_No._9_(Beethoven)"}
        assert has_digit_specificity_match(promoted, "beethoven 9th symphony") is True

    def test_neither_has_digit_returns_false(self) -> None:
        from openzim_mcp.title_promotion import has_digit_specificity_match

        promoted = {"path": "Tesla's_Wireless_Electricity"}
        assert has_digit_specificity_match(promoted, "tesla electricity") is False

    def test_canonical_has_digit_topic_does_not_returns_false(self) -> None:
        """User did NOT signal numeric specificity but canonical narrows
        to a specific instance → reject (no exemption)."""
        from openzim_mcp.title_promotion import has_digit_specificity_match

        promoted = {"path": "Symphony_No._1_(Beethoven)"}
        assert has_digit_specificity_match(promoted, "beethoven symphony") is False

    def test_topic_has_digit_canonical_does_not_returns_false(self) -> None:
        from openzim_mcp.title_promotion import has_digit_specificity_match

        promoted = {"path": "Some_Multi_Word_Article"}
        assert has_digit_specificity_match(promoted, "apollo 11 mission") is False

    def test_digit_in_topic_but_canonical_extra_digits_all_in_topic(self) -> None:
        """If canonical's digit tokens are ALL already in topic (no
        extras have digits), the digit isn't an extra-narrowing signal.
        Subset rule should catch this case before Z4 fires anyway."""
        from openzim_mcp.title_promotion import has_digit_specificity_match

        # canonical {apollo, 11} ⊆ topic {apollo, 11, mission} → no
        # extras with digits → False (no narrowing claim to exempt).
        promoted = {"path": "Apollo_11"}
        assert has_digit_specificity_match(promoted, "apollo 11 mission") is False


# ---------------------------------------------------------------------------
# Synthesize Pass 0 Z4 protection — symmetric to simple_tools Pass 0.
# synthesize.py's Pass 0 ``_promote_title_match`` calls
# ``find_title_match`` + ``accept_possessive_promotion`` with the same
# vulnerability shape as simple_tools. Z4 layer must apply here too.
# ---------------------------------------------------------------------------


def _archive_stub_synthesize() -> Any:
    class _Archive:
        pass

    return _Archive()


def _run_promote_synthesize(
    query: str,
    mapping: Dict[str, Optional[Dict[str, Any]]],
    top_hits: Optional[list] = None,
) -> list:
    """Drive ``synthesize._promote_title_match`` with the mapping
    serving as the find_title_match stand-in for both Pass 0 (full
    query) and Z4 head/tail probes."""
    from unittest.mock import MagicMock

    from openzim_mcp.synthesize import _promote_title_match

    fake = _fake_find_title_match(mapping)
    handler = MagicMock()
    handler.title_match_hit = lambda _a, _q: None
    with patch("openzim_mcp.synthesize.find_title_match", side_effect=fake):
        return _promote_title_match(
            top_hits or [],
            query=query,
            archives=[(_archive_stub_synthesize(), "/wiki.zim")],
            archives_searched=["wiki"],
            search_handler=handler,
        )


class TestSynthesizeZ4Protection:
    """Pre-existing gap: synthesize.py Pass 0 (line 1022) consults
    ``accept_possessive_promotion`` but lacks the b11 Z4 layer. The
    same multi-token tangential silent-wrong-answer pattern can
    surface via synthesize=True. This class pins the fix shape:
    Z4 rejects in synthesize symmetrically with simple_tools."""

    def test_tesla_electricity_rejected_in_synthesize(self) -> None:
        """Synthesize Pass 0 must reject ``Tesla's_Wireless_Electricity``
        for ``tesla electricity`` — the canonical contains the head as
        possessive subordinate + adds modifier ``wireless`` not in topic.
        Head probe ``tesla`` returns ``Nikola_Tesla`` ≠ promoted →
        biographical exemption fails → reject."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "tesla electricity": {
                "path": "Tesla's_Wireless_Electricity",
                "title": "Tesla's Wireless Electricity",
                "zim_file": "/wiki.zim",
                "match_type": "fuzzy_suggest",
            },
            "tesla": {
                "path": "Nikola_Tesla",
                "title": "Nikola Tesla",
                "zim_file": "/wiki.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Tesla",
            },
            "electricity": {
                "path": "Electricity",
                "title": "Electricity",
                "zim_file": "/wiki.zim",
                "match_type": "direct",
            },
        }
        original_top = [
            ("wiki", {"path": "Nikola_Tesla", "snippet": "...", "score": 0.7}),
            (
                "wiki",
                {"path": "Electrical_engineering", "snippet": "...", "score": 0.5},
            ),
        ]
        promoted = _run_promote_synthesize(
            "tesla electricity", mapping, top_hits=original_top
        )
        # Z4 rejects → either top_hits unchanged OR Pass-1/2 finds a
        # different canonical; either way Tesla's_Wireless_Electricity
        # must NOT be at rank 0.
        assert (
            len(promoted) == 0
            or promoted[0][1].get("path") != "Tesla's_Wireless_Electricity"
        ), (
            "Z4 must reject `Tesla's_Wireless_Electricity` in synthesize "
            f"Pass 0; got {promoted!r}"
        )

    def test_picasso_paris_cubism_biographical_accepts_in_synthesize(self) -> None:
        """Counter-case: biographical exemption fires in synthesize
        too. ``picasso paris cubism`` head probe ``picasso`` resolves
        to ``Pablo_Picasso`` = promoted candidate → exempt → accept."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "picasso paris cubism": {
                "path": "Pablo_Picasso",
                "title": "Pablo Picasso",
                "zim_file": "/wiki.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Picasso",
            },
            "picasso": {
                "path": "Pablo_Picasso",
                "title": "Pablo Picasso",
                "zim_file": "/wiki.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Picasso",
            },
            "paris": {
                "path": "Paris",
                "title": "Paris",
                "zim_file": "/wiki.zim",
                "match_type": "direct",
            },
            "cubism": {
                "path": "Cubism",
                "title": "Cubism",
                "zim_file": "/wiki.zim",
                "match_type": "direct",
            },
        }
        promoted = _run_promote_synthesize("picasso paris cubism", mapping)
        # Biographical exemption accepts → Pablo_Picasso promoted to rank 0.
        assert len(promoted) >= 1
        assert promoted[0][1].get("path") == "Pablo_Picasso"

    def test_possessive_query_unaffected_in_synthesize(self) -> None:
        """Possessive queries bypass Z4 in synthesize (OPP-1 path):
        ``Newton's gravity`` → ``Newton's_law_of_universal_gravitation``
        still promotes."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "newton's gravity": {
                "path": "Newton's_law_of_universal_gravitation",
                "title": "Newton's law of universal gravitation",
                "zim_file": "/wiki.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Newton's_law_of_gravity",
            },
        }
        promoted = _run_promote_synthesize("newton's gravity", mapping)
        assert len(promoted) >= 1
        assert promoted[0][1].get("path") == "Newton's_law_of_universal_gravitation"


# ---------------------------------------------------------------------------
# Sub-pattern C: disambig promotion at tell_me_about. When the auto-
# picked canonical's body IS a disambig page AND the topic has 2+
# meaningful (non-stop-word) tokens, fall back to BM25 search.
# ---------------------------------------------------------------------------


_LINCOLN_DISAMBIG_PRE_H2 = (
    "Look up _**Lincoln**_ in Wiktionary, the free dictionary.\n\n"
    "**Lincoln** most commonly refers to: \n\n"
    "  * Abraham Lincoln (1809–1865), the 16th president of the "
    "United States\n"
    "  * Lincoln, England, cathedral city and county town of "
    "Lincolnshire, England\n"
    "  * Lincoln, Nebraska, the capital of Nebraska, U.S.\n"
    "  * Lincoln (name), a surname and given name\n"
    "  * Lincoln Motor Company, a Ford brand\n\n"
    "**Lincoln** may also refer to:"
)


class TestSubPatternCDisambigRejection:
    """Sub-pattern C: ``Lincoln slavery emancipation`` →
    ``Lincoln`` (disambig page). When the auto-picked canonical body
    matches the disambig-lead pattern AND the topic has 2+
    meaningful tokens, the user wanted a specific article — fall
    back to BM25 search so the LLM sees the ranked specific articles
    instead of the disambig list."""

    _make_handler = staticmethod(_make_disambig_handler)

    def test_lincoln_multi_token_falls_to_search(self) -> None:
        """Multi-content-token topic + disambig body → fall back."""
        disambig_body = (
            f"# Lincoln\n\n{_LINCOLN_DISAMBIG_PRE_H2}\n\n"
            "## Places\n  * Lincoln, Alabama\n"
        )
        handler, mock = self._make_handler(
            article_body=disambig_body,
            search_results=[
                {"path": "Lincoln", "title": "Lincoln", "score": 100},
            ],
            title_index={"path": "Lincoln", "title": "Lincoln", "score": 1.0},
        )
        out = handler.handle_zim_query(
            "tell me about Lincoln slavery emancipation",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        # The disambig auto-fetch must NOT win — caller sees BM25
        # search fallback instead.
        assert "## BM25 fallback rendered" in out
        mock.search_zim_file.assert_called()

    def test_lincoln_single_content_token_returns_disambig(self) -> None:
        """Single-content-token topic (``tell me about Lincoln``)
        legitimately wants the disambig — don't override."""
        disambig_body = (
            f"# Lincoln\n\n{_LINCOLN_DISAMBIG_PRE_H2}\n\n"
            "## Places\n  * Lincoln, Alabama\n"
        )
        handler, mock = self._make_handler(
            article_body=disambig_body,
            search_results=[
                {"path": "Lincoln", "title": "Lincoln", "score": 100},
            ],
            title_index={"path": "Lincoln", "title": "Lincoln", "score": 1.0},
        )
        out = handler.handle_zim_query(
            "tell me about Lincoln",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        # Bare-head single-content-token topic: serve the disambig
        # as the answer (the user asked for it).
        assert "_Source: `Lincoln`_" in out
        # Fallback search must NOT have fired for this case.
        mock.search_zim_file.assert_not_called()

    def test_lincoln_stop_words_only_filter_counts_correctly(self) -> None:
        """Topic ``what is Lincoln`` — ``what`` and ``is`` are stop
        words; effective content tokens = [``lincoln``] (1). Don't
        override; serve disambig."""
        disambig_body = (
            f"# Lincoln\n\n{_LINCOLN_DISAMBIG_PRE_H2}\n\n"
            "## Places\n  * Lincoln, Alabama\n"
        )
        handler, mock = self._make_handler(
            article_body=disambig_body,
            search_results=[
                {"path": "Lincoln", "title": "Lincoln", "score": 100},
            ],
            title_index={"path": "Lincoln", "title": "Lincoln", "score": 1.0},
        )
        out = handler.handle_zim_query(
            "what is Lincoln",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        # Effective content token count is 1 (lincoln) — keep
        # disambig.
        assert "_Source: `Lincoln`_" in out
        mock.search_zim_file.assert_not_called()

    def test_non_disambig_body_unaffected(self) -> None:
        """Counter-case: when the auto-picked canonical body is NOT a
        disambig page, the rejection logic doesn't fire even with
        multi-content-token topics."""
        normal_body = (
            "# Berlin\n\n# Berlin\n\n**Berlin** is the capital of Germany.\n\n"
            "## History\nFounded in the 13th century...\n"
        )
        handler, mock = self._make_handler(
            article_body=normal_body,
            search_results=[
                {"path": "Berlin", "title": "Berlin", "score": 100},
            ],
            title_index={"path": "Berlin", "title": "Berlin", "score": 1.0},
        )
        out = handler.handle_zim_query(
            "tell me about Berlin Germany capital",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        # Body isn't disambig — serve normally.
        assert "_Source: `Berlin`_" in out
        mock.search_zim_file.assert_not_called()
