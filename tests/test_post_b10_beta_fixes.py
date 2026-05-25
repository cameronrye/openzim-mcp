r"""Regression tests for the post-b10 beta-test sweep.

The post-b10 live-MCP sweep against v2.0.0b10 confirmed OPP-1's
redirect extension lands cleanly (``Newton's gravity`` now auto-
fetches ``Newton's_law_of_universal_gravitation``) but ALL SIX Z3
silent-wrong-answer repros STILL fire.

## Root cause — Tier 1 Rule 1 lowercases the topic upstream

The b10 Z3 discriminator (``_is_specific_token`` counting
capitalized + digit tokens) was designed to distinguish multi-
entity proper-noun queries (``Stalin USSR Russia``) from filler-
prose + tail-entity (``what is the population of detroit``). It
counted capitalized tokens in the ORIGINAL-case topic.

But ``IntentParser._normalize_topic_case`` (Tier 1 Rule 1,
``intent_parser.py:1540``) lowercases the query BEFORE topic
extraction. By the time the discriminator sees the topic string,
``"Stalin USSR Russia"`` is ``"stalin ussr russia"`` — zero
capitalized tokens — the discriminator doesn't fire — tail-hijack
escapes.

## Fix — case-independent probe-based discriminator

The discriminator must use a signal that survives Tier 1's case
normalization. Probe each non-tail topic token via
``find_title_match``. The silent-wrong-answer pattern stacks
multiple individually-strong title-index tokens (``Stalin``,
``USSR``, ``Russia`` all resolve standalone); legitimate filler-
prose queries have at most one (``population`` resolves, ``what``
/ ``is`` / ``the`` / ``of`` do not).

Two new helpers in ``title_promotion``:

  * ``is_tail_hijack_shape(promoted, topic)`` — pure-logic check
    for the 1-token-canonical-equals-topic-last-token shape (no
    discriminator).
  * ``count_non_tail_strong_entities(topic, title_probe, limit=2)``
    — probes each non-tail token via the supplied callback;
    returns the count, short-circuiting at ``limit``.

``_promote_topic_via_title_index`` Pass 1 / Pass 2 now consult
both: when the candidate is a tail-hijack shape AND the topic
probes as multi-entity (2+ strong non-tail matches), the
candidate is skipped. When it's a tail-hijack shape but the
topic probes as single-entity (filler-prose), the candidate is
accepted — preserving the documented ``population of detroit``
behavior.

``_accept_non_possessive`` no longer carries the case-based
discriminator; its tail-hijack rejection is unconditional (any
match_type, regardless of case). The call site overrides the
rejection when single-entity is confirmed.

## Decision matrix

  +---------------------------------+----------+------------+----------+
  | Topic                           | Tail-    | Multi-     | Decision |
  |                                 | hijack   | entity     |          |
  |                                 | shape?   | probe ≥2?  |          |
  +---------------------------------+----------+------------+----------+
  | Stalin USSR Russia              | yes      | yes        | REJECT   |
  | Hitler Germany Berlin           | yes      | yes        | REJECT   |
  | Marie Curie polonium discovery  | yes      | yes        | REJECT   |
  | Big Rapids Michigan tourism     | yes      | yes        | REJECT   |
  | O'Brien character 1984          | yes      | yes        | REJECT   |
  | what is the population of detroit| yes      | no (1 match)| ACCEPT |
  | people who live in michigan     | yes      | no         | ACCEPT   |
  | Berlin Germany                  | no (<3 tk)| -         | ACCEPT   |
  +---------------------------------+----------+------------+----------+
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import patch

from tests._promote_fixtures import fake_find_title_match as _fake_find_title_match
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
# Live Z3 silent-wrong-answer cases — must reject tail-hijack when
# multi-entity probing succeeds.
# ---------------------------------------------------------------------------


class TestZ3TailHijackMultiEntityRejected:
    """When the topic probes as multi-entity (2+ non-tail tokens
    individually resolve to strong title matches), the tail-hijack
    candidate must be rejected. Pass 2 then tries head-token windows;
    when those resolve cleanly to a HEAD entity, that's the auto-
    fetched result instead."""

    def test_stalin_ussr_russia_rejects_tail_accepts_head(self) -> None:
        """Live repro: topic arrives lowercased as ``stalin ussr
        russia``. Pass 1 tail ``russia`` returns Russia direct (tail-
        hijack). Probing ``stalin`` and ``ussr`` returns strong
        matches → multi-entity → reject Russia. Pass 2 head probes
        ``stalin`` → Stalin → auto-fetched."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "russia": {
                "path": "Russia",
                "title": "Russia",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "stalin": {
                "path": "Stalin",
                "title": "Stalin",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "ussr": {
                "path": "Soviet_Union",
                "title": "Soviet Union",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "USSR",
            },
        }
        result = _run_promote("stalin ussr russia", mapping)
        # Russia must be rejected (it's the tail-hijack); Pass 2 should
        # find Stalin via head-position window probe.
        assert result is None or result["path"] != "Russia", (
            f"Z3 post-b10 must reject tail-hijack `Russia` when "
            f"non-tail tokens probe as multi-entity. Got: {result!r}"
        )

    def test_hitler_germany_berlin_rejects_tail(self) -> None:
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "berlin": {
                "path": "Berlin",
                "title": "Berlin",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "hitler": {
                "path": "Adolf_Hitler",
                "title": "Adolf Hitler",
                "zim_file": "test.zim",
                "match_type": "redirect",
                "pre_redirect_path": "Hitler",
            },
            "germany": {
                "path": "Germany",
                "title": "Germany",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote("hitler germany berlin", mapping)
        assert result is None or result["path"] != "Berlin"

    def test_marie_curie_polonium_discovery_rejects_tail(self) -> None:
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "discovery": {
                "path": "Discovery",
                "title": "Discovery",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
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
            "polonium": {
                "path": "Polonium",
                "title": "Polonium",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote("marie curie polonium discovery", mapping)
        assert result is None or result["path"] != "Discovery"

    def test_obrien_character_1984_rejects_tail(self) -> None:
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "1984": {
                "path": "1984",
                "title": "1984",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "o'brien": {
                "path": "O'Brien",
                "title": "O'Brien",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            "character": {
                "path": "Character",
                "title": "Character",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote("o'brien character 1984", mapping)
        assert result is None or result["path"] != "1984"


# ---------------------------------------------------------------------------
# Counter-cases: filler-prose queries with a single non-tail entity
# must keep the documented Pass 1 1-token-tail auto-fetch behavior.
# ---------------------------------------------------------------------------


class TestFillerProseSingleEntityPreserved:
    """When the topic probes as single-entity (only one non-tail
    token resolves), the tail-hijack rule is a false positive; the
    candidate must be accepted."""

    def test_population_of_detroit_accepts_tail(self) -> None:
        """Documented Pass 1 1-token-tail feature: filler prose +
        entity at tail. ``what`` / ``is`` / ``the`` / ``of`` don't
        resolve; only ``population`` does (1 non-tail match) →
        single-entity → accept tail ``detroit``."""
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
            # Others (what, is, the, of) deliberately absent from
            # mapping → probe returns None → not counted.
        }
        result = _run_promote("what is the population of detroit", mapping)
        assert result is not None and result["path"] == "Detroit"

    def test_people_who_live_in_michigan_accepts_tail(self) -> None:
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "michigan": {
                "path": "Michigan",
                "title": "Michigan",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
            # who / live / in / people deliberately absent → single
            # entity (only michigan probes positively).
        }
        result = _run_promote("people who live in michigan", mapping)
        assert result is not None and result["path"] == "Michigan"

    def test_zero_strong_non_tail_entities_accepts_tail(self) -> None:
        """Defensive: when ZERO non-tail tokens resolve, the topic
        is pure filler; the tail-entity must be accepted."""
        mapping: Dict[str, Optional[Dict[str, Any]]] = {
            "detroit": {
                "path": "Detroit",
                "title": "Detroit",
                "zim_file": "test.zim",
                "match_type": "direct",
            },
        }
        result = _run_promote("info about detroit ok", mapping)
        assert result is not None and result["path"] == "Detroit"


# ---------------------------------------------------------------------------
# Direct unit tests on the new helpers
# ---------------------------------------------------------------------------


class TestIsTailHijackShape:
    """Pure-logic check (no probing): canonical is single token
    equal to topic's LAST token, topic has 3+ tokens."""

    def test_tail_hijack_3_token_topic(self) -> None:
        from openzim_mcp.title_promotion import is_tail_hijack_shape

        promoted = {"path": "Russia", "match_type": "direct"}
        assert is_tail_hijack_shape(promoted, "stalin ussr russia") is True

    def test_not_tail_hijack_head_position(self) -> None:
        """Canonical at HEAD position (not tail) is NOT a hijack."""
        from openzim_mcp.title_promotion import is_tail_hijack_shape

        promoted = {"path": "Hamlet"}
        assert is_tail_hijack_shape(promoted, "hamlet denmark prince") is False

    def test_not_tail_hijack_multi_token_canonical(self) -> None:
        """Multi-token canonical is never a 1-token-tail hijack."""
        from openzim_mcp.title_promotion import is_tail_hijack_shape

        promoted = {"path": "Moon_landing"}
        assert is_tail_hijack_shape(promoted, "apollo 11 moon landing") is False

    def test_not_tail_hijack_2_token_topic(self) -> None:
        """Topics with <3 tokens are exempt (b4 carve-out invariant)."""
        from openzim_mcp.title_promotion import is_tail_hijack_shape

        promoted = {"path": "Berlin"}
        assert is_tail_hijack_shape(promoted, "berlin germany") is False


class TestCountNonTailStrongEntities:
    """Probe-based multi-entity discriminator — case-independent."""

    def test_multi_entity_counts(self) -> None:
        """Stalin USSR Russia: non-tail ``stalin`` + ``ussr`` both
        resolve → count = 2."""
        from openzim_mcp.title_promotion import count_non_tail_strong_entities

        def probe(token: str) -> Optional[Dict[str, Any]]:
            return {"stalin": {"path": "Stalin"}, "ussr": {"path": "USSR"}}.get(token)

        assert count_non_tail_strong_entities("stalin ussr russia", probe) == 2

    def test_filler_prose_counts(self) -> None:
        """population of detroit: only ``population`` resolves of
        non-tail tokens → count = 1."""
        from openzim_mcp.title_promotion import count_non_tail_strong_entities

        def probe(token: str) -> Optional[Dict[str, Any]]:
            return {"population": {"path": "Population"}}.get(token)

        assert (
            count_non_tail_strong_entities("what is the population of detroit", probe)
            == 1
        )

    def test_short_circuits_at_limit(self) -> None:
        """Probe stops counting at ``limit`` to avoid wasted probes.

        Uses entity-shaped tokens (not stop-words) so the filter
        doesn't drop them, and returns a canonical that contains
        the probed token so the in-canonical check counts the hit.
        """
        from openzim_mcp.title_promotion import count_non_tail_strong_entities

        calls = []

        def probe(token: str) -> Optional[Dict[str, Any]]:
            calls.append(token)
            return {"path": token}  # canonical = probed token

        # 4-token topic "alpha beta gamma delta": 3 non-tail tokens,
        # limit=2, should stop after counting the first 2.
        result = count_non_tail_strong_entities(
            "alpha beta gamma delta", probe, limit=2
        )
        assert result == 2
        assert len(calls) == 2

    def test_two_token_topic_returns_zero(self) -> None:
        """Topics with <3 tokens: the discriminator is moot (the
        tail-hijack rule doesn't fire either). Return 0."""
        from openzim_mcp.title_promotion import count_non_tail_strong_entities

        def probe(token: str) -> Optional[Dict[str, Any]]:
            return {"path": "X"}

        assert count_non_tail_strong_entities("berlin germany", probe) == 0


class TestProbeExceptionsSwallowed:
    """If a probe raises (transient libzim error), the count
    keeps going. A flaky probe must not blow up the gate."""

    def test_probe_exception_treated_as_no_match(self) -> None:
        from openzim_mcp.title_promotion import count_non_tail_strong_entities

        def probe(token: str) -> Optional[Dict[str, Any]]:
            if token == "ussr":
                raise RuntimeError("transient")
            return {"stalin": {"path": "Stalin"}}.get(token)

        # stalin resolves, ussr raises (skipped), russia is tail (not probed).
        # Only stalin counts → 1.
        assert count_non_tail_strong_entities("stalin ussr russia", probe) == 1
