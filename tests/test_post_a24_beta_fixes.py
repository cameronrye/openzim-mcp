r"""Regression tests for the post-a24 beta-test sweep (a25 candidate fixes).

The post-a24 live-MCP sweep against the 118 GB Wikipedia ZIM after
v2.0.0a24 deployed surfaced SIX defects across the attack surface that
a24's four fixes unlocked. The "narrow-scope sibling" pattern is now 5
sweeps strong — 6 of 6 defects this sweep are sibling shapes of the
matching a24 fix.

Defects span four surfaces:

* **Slashed-compound helper digit-half / mixed-case widening (P1-D1
  + P1-D2).** Post-a23 ``_looks_like_slashed_compound`` only accepted
  letter-only halves with ``min(len) ≤ 2`` — tuned for short ALL-CAPS
  acronyms (``TCP/IP``, ``AC/DC``). Two sibling classes leaked through:

    - **P1-D1 — digit-only halves.** ``9/11``, ``24/7``, ``5/4``,
      ``12/24``, ``2024/25`` are single-entity shapes (date / ratio /
      sports season). Pre-fix, the letter-only check returned False,
      the slash pass split them into digit-only halves which then PASSED
      substantive (the digit clause in ``_is_substantive_topic`` accepts
      any string containing a digit). Live a24 probe:
      ``tell me about 9/11 and World War II`` → 3-entity chain rejection
      naming ``9``, ``11``, ``World War II``. Fix: helper now accepts
      digit-only halves with ``min ≤ 2``.

    - **P1-D2 — short mixed-case TitleCase halves.** ``Yin/Yang``,
      ``Hot/Cold``, ``Wet/Dry``, ``Mac/Cheese`` are paired-concept
      compounds whose halves are 3-4 char letter-only TitleCase. Pre-fix
      the letter check passed but ``min ≤ 2`` failed; the slash pass
      split into halves which then FAILED substantive (3-4 char mixed-
      case ASCII no digit no non-Latin); ``_split_multi_entity`` returned
      None and the chain rejection abandoned silently. Live a24 probe:
      ``tell me about Yin/Yang and the Tao`` → returned ``Tao`` with
      Yin/Yang silently dropped. Fix: widen letter-only floor to
      ``min ≤ 4``.

* **Politeness regex third-wave multilingual extension (P1-D3 +
  P1-D4).** Post-a23 P1-D2 added multi-word English (``thanks a million``,
  ``thank you very much``) plus second-wave multilingual (``obrigado``,
  ``arigatou``, ``spasibo``). Two sibling classes leaked through:

    - **P1-D3 — multi-word multilingual.** The post-a23 multilingual
      tokens are all single words. Live a24 probes showed multi-word
      counterparts leak: ``merci beaucoup`` (French), ``vielen dank``
      (German), ``muchas gracias`` (Spanish — ``gracias`` peeled but
      ``muchas`` left), ``arigatou gozaimasu`` (Japanese formal),
      ``domo arigato`` (Mr. Roboto), ``terima kasih`` (Malay/Indonesian).

    - **P1-D4 — more single-word multilingual.** Live a24 probes:
      ``mahalo`` (Hawaiian), ``xie xie``/``xièxie`` (Chinese romaji),
      ``shukran`` (Arabic), ``kiitos`` (Finnish), ``tack`` (Swedish),
      ``gomawo``/``kamsahamnida`` (Korean romaji), ``dhanyavad``
      (Hindi romaji), ``domo``/``gozaimasu`` (Japanese remainders).

* **Param-leak strip token-set widening (P1-D5).** Post-a23 P1-D3
  introduced ``_strip_param_leaks`` covering 13 of the 14 public
  ``zim_query`` arguments. The 14th — ``query`` — was missing. Live a24
  probe: ``tell me about Photosynthesis query=biology`` returned the
  ``Biology`` disambig (the ``=biology`` suffix prevented title
  promotion from cleanly resolving ``Photosynthesis``). Fix: add
  ``query`` to the strip token set.

* **Param-leak strip not applied before chained-intent detection
  (P1-D6).** Post-a23 P1-D3's strip runs inside ``parse_intent``, but
  the dispatcher's ``_chained_intent_guidance`` call runs upstream of
  that on the raw user query. Live a24 probe: ``tell me about Berlin
  limit=5 then list namespaces`` surfaced a chained-intent rejection
  whose ``**First op (left)**: tell me about Berlin limit=5`` carried
  the leaked param verbatim. Fix: mirror the existing politeness-strip
  pattern inside ``_chained_intent_guidance`` with a param-strip call.

Methodology continues to hold:
  * "Narrow-scope sibling" pattern is now strong enough to flag preemptively
    for every new guard / regex / token list — 6 of 6 defects this sweep
    are sibling shapes of an a24 fix.
  * "Fix unlocks new paths" reproduced for the 5th sweep — a24's
    ``_looks_like_slashed_compound`` LANDED correctly but exposed two
    sibling classes (digit halves, mixed-case short halves) that the
    a24 letter+≤2 threshold didn't cover.
"""

from __future__ import annotations

import pytest

from openzim_mcp.intent_parser import IntentParser
from openzim_mcp.simple_tools import SimpleToolsHandler

# ===========================================================================
# P1-D1: slashed-compound helper accepts digit-only short halves
# ===========================================================================


class TestP1D1SlashedDigitCompounds:
    """P1-D1: ``_looks_like_slashed_compound`` pre-fix rejected any half
    that contained a digit (its letter-only branch returned False for
    ``9/11``, ``24/7``, ``5/4``). The slash-pattern pass then split these
    into digit-only halves, which DID pass substantive (the digit clause
    in ``_is_substantive_topic`` accepts any digit-bearing string), so
    the chain rejection fired naming the individual numbers as separate
    entities — semantically wrong for ``9/11`` (single event), ``24/7``
    (single phrase), or ``5/4`` (single time signature / fraction).

    Fix: detect all-digit halves and accept the compound when both
    halves are ≤ 2 chars (catches the common date / ratio / sports-
    season shapes; rejects ``2024/2025`` which is more naturally two
    distinct years).
    """

    @pytest.mark.parametrize(
        "compound",
        [
            "9/11",  # single event
            "24/7",  # single phrase
            "5/4",  # time signature / fraction
            "3/4",  # fraction
            "1/2",  # fraction
            "12/24",  # date (December 24)
            "2024/25",  # sports season notation (min=2, max=4 — still compound)
            "1980/81",  # season
        ],
    )
    def test_digit_compound_detected(self, compound: str) -> None:
        assert SimpleToolsHandler._looks_like_slashed_compound(
            compound
        ), f"{compound!r} should be treated as a single-entity slashed compound"

    @pytest.mark.parametrize(
        "compound",
        [
            "2024/2025",  # both halves 4-digit — splits to two years
            "1000/2000",  # min=4, splits
            "12345/67890",  # both halves 5+ digits
        ],
    )
    def test_long_digit_pair_still_splits(self, compound: str) -> None:
        assert not SimpleToolsHandler._looks_like_slashed_compound(
            compound
        ), f"{compound!r} should split (both halves > 2 digits)"

    def test_mixed_alphanumeric_halves_still_split(self) -> None:
        # Mixed letter+digit halves: not a date shape, not a letter
        # acronym. Treat as splittable (typically e.g. ``A/4`` model
        # numbers — semantically two separate entities).
        assert not SimpleToolsHandler._looks_like_slashed_compound("A/4")
        assert not SimpleToolsHandler._looks_like_slashed_compound("H1/H2O")
        assert not SimpleToolsHandler._looks_like_slashed_compound("X/12")

    def test_9_11_chain_treats_compound_as_single_entity(self) -> None:
        # End-to-end: ``9/11 and World War II`` should be a 2-entity
        # case (the soft-connector footer path handles 2-entity, not the
        # ``Multi-Entity Chain Detected`` rejection which fires only at
        # 3+ substantive halves). ``_split_multi_entity`` returns None
        # here because the cleaned halves count is < 3.
        result = SimpleToolsHandler._split_multi_entity("9/11 and World War II")
        # After fix: "9/11" stays compound, only one connector → 2 halves
        # → < 3 substantive → returns None.
        assert result is None, (
            f"Expected None (only 2 halves once 9/11 is preserved); " f"got {result!r}"
        )

    def test_24_7_chain_treats_compound_as_single_entity(self) -> None:
        # ``24/7 and 9 to 5`` → halves are ``["24/7", "9 to 5"]``. Both
        # substantive (24/7 multi-token-shaped via slash, 9 to 5
        # multi-token). But 2 halves < 3 so returns None.
        result = SimpleToolsHandler._split_multi_entity("24/7 and 9 to 5")
        assert result is None

    def test_three_entity_chain_with_digit_compound_first(self) -> None:
        # ``9/11 and World War II and Pearl Harbor`` → 3 entities, all
        # substantive. The 9/11 compound stays as one entity in the
        # chain.
        result = SimpleToolsHandler._split_multi_entity(
            "9/11 and World War II and Pearl Harbor"
        )
        assert result is not None
        assert result == ["9/11", "World War II", "Pearl Harbor"]


# ===========================================================================
# P1-D2: slashed-compound helper accepts short letter-only TitleCase halves
# ===========================================================================


class TestP1D2SlashedShortLetterCompounds:
    """P1-D2: ``_looks_like_slashed_compound`` pre-fix required ``min ≤ 2``
    for letter halves, missing 3-4 char paired-concept compounds:

      - ``Yin/Yang``, ``Hot/Cold``, ``Wet/Dry``, ``On/Off``, ``Up/Down``,
        ``Light/Dark``, ``Day/Night`` (all min 3-4)
      - ``Mac/Cheese``, ``Salt/Pepper``, ``Sandy/Hook`` (mixed long+short
        with min ≤ 4)

    Live a24 probe: ``tell me about Yin/Yang and the Tao`` → split to
    ``["Yin", "Yang", "the Tao"]``; Yin and Yang failed substantive
    (3-4 char ASCII TitleCase, no digit, no non-Latin); ``_split_multi
    _entity`` returned None and the chain abandoned silently, returning
    the Tao article with Yin/Yang silently dropped.

    Fix: widen letter floor to ``min ≤ 4``.
    """

    @pytest.mark.parametrize(
        "compound",
        [
            "Yin/Yang",  # min=3
            "Hot/Cold",  # min=3
            "Wet/Dry",  # min=3
            "Up/Down",  # min=2 — already covered by old ≤2
            "On/Off",  # min=2
            "Day/Night",  # min=3 (Day=3, Night=5)
            "Light/Dark",  # min=4 (Light=5, Dark=4)
            "Mac/Cheese",  # min=3 (Mac=3, Cheese=6)
            "Salt/Pepper",  # min=4 (Salt=4, Pepper=6)
            "Sandy/Hook",  # min=4
            "Cat/Dog",  # min=3
            "Lock/Key",  # min=3
        ],
    )
    def test_short_letter_compound_detected(self, compound: str) -> None:
        assert SimpleToolsHandler._looks_like_slashed_compound(
            compound
        ), f"{compound!r} should be treated as a single-entity compound"

    @pytest.mark.parametrize(
        "pair",
        [
            "Berlin/Munich",  # min=6 — real 2-entity chain
            "Tokyo/Kyoto",  # min=5
            "Apple/Microsoft",  # min=5
            "Lions/Tigers",  # min=5
            "London/Paris",  # min=5
        ],
    )
    def test_long_letter_pair_still_splits(self, pair: str) -> None:
        assert not SimpleToolsHandler._looks_like_slashed_compound(
            pair
        ), f"{pair!r} should split (both halves are real proper nouns)"

    def test_yin_yang_chain_preserves_compound(self) -> None:
        # End-to-end: ``Yin/Yang and the Tao`` → ``Yin/Yang`` stays
        # compound, only 2 halves, returns None (falls through to
        # single-topic resolution which probably hits the Tao article
        # via fuzzy match — same live outcome as before but now WITHOUT
        # the silent abandonment of Yin/Yang as separate entities).
        result = SimpleToolsHandler._split_multi_entity("Yin/Yang and the Tao")
        # 2 halves → returns None. The user's compound entity is now
        # preserved in case the dispatcher's title-promotion path can
        # match it to an article.
        assert result is None, f"Expected None (2-entity case); got {result!r}"

    def test_three_entity_chain_with_short_compound(self) -> None:
        # ``Hot/Cold and Wet/Dry and Pressure`` → halves are
        # ``["Hot/Cold", "Wet/Dry", "Pressure"]``. Hot/Cold and Wet/Dry
        # are now compound (both min ≤ 4 letter halves); Pressure is
        # substantive (≥5). But Hot/Cold and Wet/Dry need to pass
        # substantive too — ``_is_substantive_topic("Hot/Cold")``: the
        # string contains ``/`` which isn't a token separator, so
        # ``split()`` returns 1 token of 8 chars ≥ 5 → substantive ✓.
        # Same for Wet/Dry (7 chars).
        result = SimpleToolsHandler._split_multi_entity(
            "Hot/Cold and Wet/Dry and Pressure"
        )
        assert result is not None
        assert result == ["Hot/Cold", "Wet/Dry", "Pressure"]


# ===========================================================================
# P1-D3: politeness regex multi-word multilingual extension
# ===========================================================================


class TestP1D3MultiWordMultilingualPoliteness:
    """P1-D3: the post-a23 multilingual politeness tokens were all single
    words (``bitte``, ``danke``, ``merci``, ``gracias``, ``obrigado``,
    ``arigatou``, ``spasibo``). Live a24 probes showed multi-word
    counterparts leak entirely or partially:

      - ``merci beaucoup`` → leaked entirely (regex didn't match)
      - ``vielen dank`` → leaked entirely (``dank`` without ``e`` not in
        token list)
      - ``muchas gracias`` → ``gracias`` peeled, ``muchas`` left
      - ``arigatou gozaimasu`` → leaked entirely
      - ``domo arigato`` → ``arigato`` peeled, ``domo`` left
      - ``terima kasih`` (Malay/Indonesian) → leaked entirely

    Fix: add each multi-word phrase as an explicit alternation entry,
    listed before single-word forms so the maximal phrase wins.
    """

    @pytest.mark.parametrize(
        "token",
        [
            "merci beaucoup",
            "vielen dank",
            "muchas gracias",
            "arigatou gozaimasu",
            "arigato gozaimasu",  # arigatou? optional u
            "domo arigato",
            "domo arigatou",
            "terima kasih",
        ],
    )
    def test_multi_word_multilingual_strips(self, token: str) -> None:
        cleaned = IntentParser._strip_trailing_politeness(f"biology {token}")
        assert (
            cleaned == "biology"
        ), f"Multi-word politeness {token!r} should strip cleanly; got {cleaned!r}"


# ===========================================================================
# P1-D4: politeness regex third-wave single-word multilingual extension
# ===========================================================================


class TestP1D4SingleWordMultilingualPoliteness:
    """P1-D4: more single-word multilingual tokens observed in live a24
    probes:

      - ``mahalo`` (Hawaiian)
      - ``xie xie`` / ``xièxie`` (Chinese romaji)
      - ``shukran`` (Arabic)
      - ``kiitos`` (Finnish)
      - ``tack`` (Swedish — 4-char, leading anchor protects against
        embedded matches in ``attack`` / ``thumbtack``)
      - ``gomawo`` / ``kamsahamnida`` (Korean romaji)
      - ``dhanyavad`` (Hindi romaji)
      - ``domo`` / ``gozaimasu`` (Japanese remainder fragments — also
        covered by P1-D3's multi-word combos, but listed singly for
        defence-in-depth)
    """

    @pytest.mark.parametrize(
        "token",
        [
            "mahalo",
            "xie xie",
            "xiexie",  # no-space form
            "xièxie",  # accented form
            "shukran",
            "kiitos",
            "tack",
            "gomawo",
            "kamsahamnida",
            "dhanyavad",
            "domo",
            "gozaimasu",
        ],
    )
    def test_single_word_multilingual_strips(self, token: str) -> None:
        cleaned = IntentParser._strip_trailing_politeness(f"biology {token}")
        assert (
            cleaned == "biology"
        ), f"Single-word politeness {token!r} should strip cleanly; got {cleaned!r}"

    @pytest.mark.parametrize(
        "embedding_word",
        [
            "attack",  # embeds ``tack``
            "thumbtack",  # embeds ``tack``
            "Komodo",  # embeds ``domo``
            "Quasimodo",  # embeds ``modo``
            "manta",  # embeds ``ta`` (already covered)
            "pasta",  # embeds ``ta``
            "shogun",  # embeds nothing politeness-shaped
        ],
    )
    def test_embedded_short_tokens_not_eaten(self, embedding_word: str) -> None:
        # The leading anchor ``(?:^|\s+|[,;.!?]\s*)`` requires whitespace
        # or punctuation before the politeness candidate, so mid-word
        # matches are impossible.
        cleaned = IntentParser._strip_trailing_politeness(embedding_word)
        assert cleaned == embedding_word, (
            f"{embedding_word!r} must not have politeness eaten from its "
            f"tail; got {cleaned!r}"
        )

    def test_case_insensitive_for_new_tokens(self) -> None:
        # ``re.IGNORECASE`` is set; mixed-case + ALL-CAPS variants
        # should strip identically.
        for variant in ("MAHALO", "Shukran", "KIITOS", "Tack"):
            cleaned = IntentParser._strip_trailing_politeness(f"biology {variant}")
            assert (
                cleaned == "biology"
            ), f"Case-variant {variant!r} should strip; got {cleaned!r}"


# ===========================================================================
# P1-D5: param-leak strip covers ``query`` token
# ===========================================================================


class TestP1D5ParamLeakQuery:
    """P1-D5: ``_strip_param_leaks`` covered 13 of the 14 public
    ``zim_query`` arguments but missed ``query`` itself. Live a24 probe:
    ``tell me about Photosynthesis query=biology`` returned the
    ``Biology`` disambig (the ``=biology`` suffix prevented title
    promotion from cleanly resolving ``Photosynthesis``). Fix: add
    ``query`` to the strip set.
    """

    def test_query_param_strips_cleanly(self) -> None:
        cleaned = IntentParser._strip_param_leaks(
            "tell me about Photosynthesis query=biology"
        )
        assert cleaned == "tell me about Photosynthesis"

    def test_query_param_strips_in_parse_intent(self) -> None:
        intent, params, _conf = IntentParser.parse_intent(
            "tell me about Photosynthesis query=biology"
        )
        assert intent == "tell_me_about"
        assert params.get("topic") == "Photosynthesis", (
            f"Pre-fix topic was 'Photosynthesis query=biology' → title-"
            f"promotion resolved to 'Biology' (fuzzy match); got "
            f"{params.get('topic')!r}"
        )

    def test_query_not_in_middle_of_topic_does_not_strip(self) -> None:
        # ``tell me about query language`` — ``query`` followed by
        # ``language`` (no ``=``). Strip pattern requires ``\s*=\s*``,
        # so prose containing the word ``query`` is not affected.
        cleaned = IntentParser._strip_param_leaks("tell me about query language")
        assert cleaned == "tell me about query language"


# ===========================================================================
# P1-D6: chained-intent guidance strips param leaks before connector split
# ===========================================================================


class TestP1D6ChainedIntentParamStrip:
    """P1-D6: ``_chained_intent_guidance`` runs upstream of
    ``parse_intent`` (the dispatcher calls it on the raw user query
    before parse_intent's own strip). Live a24 probe:
    ``tell me about Berlin limit=5 then list namespaces`` surfaced a
    chained-intent rejection whose ``**First op (left)**: tell me about
    Berlin limit=5`` carried the leaked param verbatim. Fix: mirror the
    existing politeness-strip pattern with a param-strip call at the
    same point in ``_chained_intent_guidance``.
    """

    def test_chained_intent_strips_left_op_param_leak(self) -> None:
        result = SimpleToolsHandler._chained_intent_guidance(
            "tell me about Berlin limit=5 then list namespaces"
        )
        assert result is not None, "expected chained-intent rejection to fire"
        assert "limit=5" not in result, (
            f"left-op should be cleaned to 'tell me about Berlin' "
            f"before display; got {result!r}"
        )
        assert (
            "tell me about Berlin" in result
        ), f"left-op should still display the cleaned operation; got {result!r}"

    def test_chained_intent_strips_right_op_param_leak(self) -> None:
        result = SimpleToolsHandler._chained_intent_guidance(
            "tell me about Berlin then list namespaces limit=10"
        )
        assert result is not None
        assert "limit=10" not in result

    def test_chained_intent_strips_multiple_param_leaks(self) -> None:
        result = SimpleToolsHandler._chained_intent_guidance(
            "tell me about Berlin limit=5 compact_budget=200 then list namespaces"
        )
        assert result is not None
        assert "limit=5" not in result
        assert "compact_budget=200" not in result
        assert "tell me about Berlin" in result

    def test_chained_intent_clean_query_unchanged(self) -> None:
        # Defensive: a chained query without param leaks should still
        # be detected (the strip is idempotent on clean input).
        result = SimpleToolsHandler._chained_intent_guidance(
            "tell me about Berlin then list namespaces"
        )
        assert result is not None
        assert "tell me about Berlin" in result
        assert "list namespaces" in result


# ===========================================================================
# Regression guards: post-a24 fixes must not break post-a17 → a23 behaviour
# ===========================================================================


class TestRegressionGuards:
    """Defensive checks for prior-alpha fixes."""

    def test_a23_tcp_ip_chain_still_fires(self) -> None:
        # Post-a23 P1-D1 smoke gate.
        result = SimpleToolsHandler._split_multi_entity("TCP/IP and HTTP and HTTPS")
        assert result == ["TCP/IP", "HTTP", "HTTPS"]

    def test_a23_ac_dc_chain_still_fires(self) -> None:
        result = SimpleToolsHandler._split_multi_entity(
            "AC/DC and Iron Maiden and Metallica"
        )
        assert result == ["AC/DC", "Iron Maiden", "Metallica"]

    def test_a23_either_or_still_compound(self) -> None:
        # ``Either/Or`` halves: Either=6, Or=2. Pre-a24: min=2 ≤ 2 ✓.
        # Post-a24: min=2 ≤ 4 ✓. Still compound either way.
        assert SimpleToolsHandler._looks_like_slashed_compound("Either/Or")

    def test_a23_a_b_still_compound(self) -> None:
        # ``A/B`` halves: A=1, B=1. min=1 ≤ 4 → compound.
        assert SimpleToolsHandler._looks_like_slashed_compound("A/B")

    def test_a23_berlin_munich_still_splits(self) -> None:
        # min=6 → splits both pre- and post-a24.
        assert not SimpleToolsHandler._looks_like_slashed_compound("Berlin/Munich")

    def test_a23_short_allcaps_still_substantive(self) -> None:
        # Post-a23 P1-D1 ALL-CAPS clause.
        for token in ("TCP", "IP", "HTTP", "EU", "USA", "R&B"):
            assert SimpleToolsHandler._is_substantive_topic(token)

    def test_a23_existing_politeness_tokens_still_strip(self) -> None:
        # Sanity: the a24 third-wave additions don't regress prior
        # tokens.
        for token in (
            "please",
            "thanks",
            "thanks a million",
            "thank you very much",
            "tyvm",
            "kthxbye",
            "obrigado",
            "arigato",
            "spasibo",
            "bitte",
            "danke",
            "merci",
            "gracias",
            "por favor",
        ):
            cleaned = IntentParser._strip_trailing_politeness(f"biology {token}")
            assert (
                cleaned == "biology"
            ), f"Pre-a24 token {token!r} regressed; got {cleaned!r}"

    def test_a23_param_leaks_still_strip(self) -> None:
        # Defensive: every pre-a24 param-leak shape still strips.
        for param, value in (
            ("limit", "10"),
            ("offset", "5"),
            ("content_offset", "100"),
            ("compact_budget", "200"),
            ("cursor", "abc123"),
            ("zim_file_path", "/data/wiki.zim"),
            ("entry_path", "C/Biology"),
            ("namespace", "C"),
        ):
            cleaned = IntentParser._strip_param_leaks(
                f"tell me about Photosynthesis {param}={value}"
            )
            assert (
                cleaned == "tell me about Photosynthesis"
            ), f"Pre-a24 param {param}={value} regressed; got {cleaned!r}"

    def test_a22_first_word_and_still_preserved(self) -> None:
        # Post-a22 P1-D1 smoke gate.
        result = SimpleToolsHandler._split_multi_entity(
            "And Then There Were None and Hercule Poirot and "
            "Murder on the Orient Express"
        )
        assert result is not None
        assert result[0] == "And Then There Were None"

    def test_a22_earth_wind_and_fire_still_returns_none(self) -> None:
        # Post-a22 / a23 regression guard for legitimate multi-entity
        # title resolution — the chain detector must NOT fire here.
        result = SimpleToolsHandler._split_multi_entity("Earth, Wind & Fire")
        assert result is None

    def test_a19_unicode_substantive_still_works(self) -> None:
        assert SimpleToolsHandler._is_substantive_topic("東京")
        assert SimpleToolsHandler._is_substantive_topic("Köln")

    def test_a16_english_sentence_words_still_rejected(self) -> None:
        for token in ("Now", "Both", "Here", "Then", "Many", "Some"):
            assert not SimpleToolsHandler._is_substantive_topic(token)
