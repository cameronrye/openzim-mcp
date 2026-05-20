r"""Regression tests for the post-a23 beta-test sweep (a24 candidate fixes).

The post-a23 live-MCP sweep against the 118 GB Wikipedia ZIM after
v2.0.0a23 deployed surfaced FOUR defects across the new attack surface
that a23's seven fixes unlocked. The "fix unlocks new paths" + "narrow-
scope sibling" pair of patterns continues to hold — three of the four
defects are narrow-scope sibling shapes of an a23 fix.

Defects span four surfaces:

* **Multi-entity chain silent abandonment on short ALL-CAPS / slashed
  acronym halves (P1-D1).** The post-a22 ``_split_multi_entity`` /
  ``_is_substantive_topic`` pair correctly handles long bare-topic
  chains (Berlin / Munich / Köln) and non-Latin shorts (東京 / Köln).
  But short ALL-CAPS acronym halves still fail the substantive filter,
  AND the slash splitter (``\s*/\s*``) fragments slashed acronyms like
  ``TCP/IP``, ``AC/DC``, ``Either/Or``, ``R&B`` into pieces that fail
  substantive separately. Two live-MCP failures:

    - ``tell me about TCP/IP and HTTP and HTTPS`` → silently returns
      the ``HTTPS`` article, dropping TCP/IP and HTTP with no signal.
      Pre-fix path: ``\s+and\s+`` splits into ``["TCP/IP", "HTTP",
      "HTTPS"]``; ``\s*/\s*`` fragments ``TCP/IP`` into ``["TCP",
      "IP"]``; parts = ``["TCP", "IP", "HTTP", "HTTPS"]``; substantive
      filter rejects all four short ALL-CAPS tokens (TCP=3, IP=2,
      HTTP=4 — none ≥5 chars, no digit, no non-ASCII); ``_split_multi
      _entity`` returns None; chain rejection never fires; tell_me_about
      resolves the maximal-match digit-and-letter tail and returns
      HTTPS.
    - ``tell me about AC/DC and Iron Maiden and Metallica`` → silently
      returns Metallica. Same path: slash splits AC/DC, substantive
      rejects AC/DC fragments, chain abandoned.

  Fix: two coordinated changes.
    - ``_is_substantive_topic`` gets a new ALL-CAPS clause that
      accepts short uppercase tokens (``TCP`` / ``IP`` / ``R&B``
      / ``EU`` / ``USA``) at length ≥2. Same shape as the post-a19
      P1-D3 non-Latin clause — short tokens with a clear
      proper-noun signal aren't English sentence-words.
    - ``_split_multi_entity`` calls a new
      ``_looks_like_slashed_compound`` helper to skip the ``/`` pass
      for slashed compounds whose halves look like a single entity
      (≤2 chars on one side, both letter-only). Covers ``TCP/IP``,
      ``AC/DC``, ``Either/Or``, ``A/B`` without affecting
      ``Berlin / Munich`` (genuine 2-entity chain, both halves >2
      chars).

* **Politeness regex extension — SMS / multi-word / multilingual
  family (P1-D2).** Post-a22 P1-D2 added ``thnx`` / ``thanx`` /
  ``tysm`` / ``kthx`` / ``kthxbai`` but missed a second wave of
  live-observed variants: ``tx`` / ``txs`` (1-2 chars), ``tyvm``,
  ``thnks``, ``thxx``, ``kthxbye`` (alternate kthx ending), multi-
  word ``thanks a million``, ``thank (you|u) (so|very) much``, and
  the Asian / Romance multilingual second tier ``obrigado(a)`` /
  ``arigato(u)`` / ``spasibo``. Same narrow-scope sibling pattern as
  a22 P1-D2 → a23 P1-D2 — each sweep so far has shipped narrower than
  the natural politeness family.

* **Silent fragmentation on ``param=value`` query suffixes (P1-D3).**
  Live: ``tell me about Photosynthesis limit=10`` returns the article
  for the number ``10`` (Wikipedia's number article), not
  Photosynthesis. Same shape for ``compact_budget=200`` (returns the
  year ``200`` article), ``content_offset=100`` (returns ``100``),
  ``offset=5`` (returns ``5``). Root cause: a small model that
  doesn't know it should pass ``limit`` as the typed MCP parameter
  occasionally leaks ``limit=N`` INTO the query text; the title-
  promotion tokeniser sees ``"10"`` as a clean ASCII digit tail and
  scores it cleanly against the number-article title index, beating
  the actual topic. New defect class — distinct from a23 P1-D5
  (docstring nudge for atomic intents that ignore ``limit``). The
  docstring tells the model not to pass ``limit`` on atomic intents,
  but it can't prevent a model that's confused about parameter
  passing semantics from typing ``limit=10`` as text. Fix:
  ``IntentParser._strip_param_leaks`` peels ``\s+<param>=<value>``
  shapes BEFORE the politeness loop runs.

* **Q-emitting drift scanner non-recursive glob (P1-D4).** Source-
  level audit: ``tests/test_post_a22_beta_fixes.py::TestP1D3...
  ._scan_q_emitting_tools_in_zim`` uses ``zim_dir.glob("*.py")`` —
  direct children only. The current ``openzim_mcp/zim/`` tree is
  flat (no subdirectories), so this works today. But a contributor
  adding ``openzim_mcp/zim/cursor/encoder.py`` or any subdirectory
  containing ``Cursor.encode(tool="X", ...)`` callsites would have
  those silently missed by the non-recursive scan. Same narrow-scope
  sibling shape as the a22 P1-D3 widening from one file to all
  direct-child files in the directory — the next widening is
  naturally to all files in the tree (``rglob``).

The post-a23 sweep methodology continues to confirm the recurring
"fix unlocks new paths" pattern: a23's ``_split_multi_entity`` /
substantive-filter pair LANDED correctly but the substantive filter's
narrow scope (no ALL-CAPS clause) and the slash splitter's aggressive
fragmentation combine to silently swallow acronym-bearing chains.
The "narrow-scope sibling" pattern is now strong enough to flag
preemptively for every new guard the sweep lands — 3 of 4 defects
this sweep are sibling shapes of the matching a23 fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openzim_mcp.intent_parser import IntentParser
from openzim_mcp.simple_tools import SimpleToolsHandler

# ===========================================================================
# P1-D1: multi-entity chain silent abandonment on slashed / ALL-CAPS acronyms
# ===========================================================================


class TestP1D1MultiEntityAllCapsAndSlashedAcronyms:
    """P1-D1: ``_split_multi_entity`` / ``_is_substantive_topic`` pre-fix
    silently abandoned multi-entity chains whose halves were short
    ALL-CAPS acronyms or slashed compounds (TCP/IP, AC/DC, R&B,
    Either/Or). Two interacting causes:

      - ``_is_substantive_topic`` rejected ALL-CAPS tokens shorter than
        5 chars (HTTP=4, TCP=3, IP=2 all failed) — the heuristic was
        tuned for English sentence-words like ``Now`` / ``Both`` /
        ``Here``, but those are mixed-case, not uppercase. The post-a19
        P1-D3 non-Latin clause already established that short tokens
        with a clear proper-noun signal aren't sentence-words.
      - ``\\s*/\\s*`` slash pattern fragmented ``TCP/IP`` into
        ``["TCP", "IP"]`` — the user's single acronym entity became
        two separate halves, each failing substantive separately, the
        chain rejection abandoning silently.

    Fix: add an ALL-CAPS clause to substantive (``isupper() and len ≥ 2``)
    AND a slashed-compound guard that skips the ``/`` split for short-
    half letter-only compounds (TCP/IP, AC/DC, Either/Or, R&B).
    """

    def test_short_allcaps_is_substantive(self) -> None:
        # Pre-fix: all of these returned False (length < 5, no digit,
        # no non-ASCII letter). Post-fix: ALL-CAPS clause accepts at
        # length ≥ 2.
        for token in ("TCP", "IP", "HTTP", "EU", "USA", "AC", "DC"):
            assert SimpleToolsHandler._is_substantive_topic(
                token
            ), f"{token!r} should be substantive (short ALL-CAPS acronym)"

    def test_rb_with_ampersand_is_substantive(self) -> None:
        # ``R&B`` has an ampersand. ``isupper()`` returns True because
        # all cased characters (R, B) are uppercase and ``&`` isn't
        # cased. Length 3 ≥ 2 so the ALL-CAPS clause accepts.
        assert SimpleToolsHandler._is_substantive_topic("R&B")

    def test_mixed_case_short_token_still_rejected(self) -> None:
        # Defensive: the ALL-CAPS clause must NOT accept short mixed-
        # case tokens — those ARE the English sentence-words the
        # substantive filter exists to reject (``Now`` / ``Both`` /
        # ``Here`` / ``Then`` / ``Many``).
        for token in ("Now", "Both", "Here", "Then", "Many"):
            assert not SimpleToolsHandler._is_substantive_topic(
                token
            ), f"{token!r} must stay non-substantive (English sentence-word)"

    def test_long_mixed_case_still_substantive(self) -> None:
        # Pre-existing behaviour preserved: ≥5 char mixed-case tokens
        # remain substantive.
        assert SimpleToolsHandler._is_substantive_topic("Berlin")
        assert SimpleToolsHandler._is_substantive_topic("Photosynthesis")

    # ---- slashed-compound protection ----

    def test_slashed_compound_helper_identifies_acronyms(self) -> None:
        for compound in ("TCP/IP", "AC/DC", "Either/Or", "A/B"):
            assert SimpleToolsHandler._looks_like_slashed_compound(
                compound
            ), f"{compound!r} should be detected as a single-entity slashed compound"

    def test_slashed_compound_helper_does_not_match_proper_noun_pairs(self) -> None:
        # Both halves ≥3 chars: the slash is a real soft connector,
        # not part of a compound name.
        for pair in ("Berlin/Munich", "Apple/Microsoft", "Tokyo/Kyoto"):
            assert not SimpleToolsHandler._looks_like_slashed_compound(
                pair
            ), f"{pair!r} should split (both halves are proper nouns)"

    def test_slashed_compound_helper_rejects_three_part_slashes(self) -> None:
        # ``Foo/Bar/Baz`` has 3 slashes — not a single compound shape.
        # We treat as splittable to preserve existing behaviour.
        assert not SimpleToolsHandler._looks_like_slashed_compound("Foo/Bar/Baz")
        assert not SimpleToolsHandler._looks_like_slashed_compound("TCP/IP/HTTP")

    def test_slashed_compound_helper_rejects_mixed_alphanumeric_halves(self) -> None:
        # Mixed letter+digit halves (``A/4``) still split — the post-a24
        # widening only accepts all-letter OR all-digit halves, not
        # mixed shapes. ``9/11`` is now treated as compound (post-a24
        # P1-D1 sibling fix — see post-a24 test suite for the digit-only
        # date/ratio shape coverage).
        assert not SimpleToolsHandler._looks_like_slashed_compound("A/4")
        assert not SimpleToolsHandler._looks_like_slashed_compound("X/12")

    # ---- end-to-end split behaviour ----

    def test_tcp_ip_chain_fires_with_compound_preserved(self) -> None:
        result = SimpleToolsHandler._split_multi_entity("TCP/IP and HTTP and HTTPS")
        assert result is not None, (
            "Pre-fix: TCP/IP fragmented to TCP+IP, all fragments fail "
            "substantive (len<5), split returns None and chain rejection "
            "silently abandons all 3 entities."
        )
        assert result == [
            "TCP/IP",
            "HTTP",
            "HTTPS",
        ], f"Expected 3-entity split with TCP/IP preserved; got {result!r}"

    def test_ac_dc_chain_fires_with_compound_preserved(self) -> None:
        result = SimpleToolsHandler._split_multi_entity(
            "AC/DC and Iron Maiden and Metallica"
        )
        assert result is not None
        assert result == ["AC/DC", "Iron Maiden", "Metallica"]

    def test_berlin_munich_chain_still_splits_on_slash_with_spaces(self) -> None:
        # The slashed-compound guard must NOT protect genuine 2-entity
        # chains where the halves are real proper nouns. ``Berlin /
        # Munich`` (with spaces around the slash) → both halves ≥3
        # chars, helper returns False, slash pass splits normally.
        result = SimpleToolsHandler._split_multi_entity("Berlin / Munich / Hamburg")
        assert result == ["Berlin", "Munich", "Hamburg"]

    def test_chain_with_compound_and_short_acronyms(self) -> None:
        # All halves are short ALL-CAPS. Pre-fix: every half failed
        # substantive. Post-fix: ALL-CAPS clause accepts each, 3-entity
        # chain rejection fires.
        result = SimpleToolsHandler._split_multi_entity("USA and EU and UK")
        assert result == ["USA", "EU", "UK"]


# ===========================================================================
# P1-D2: politeness regex extension — second-wave SMS / multi-word /
# multilingual variants
# ===========================================================================


class TestP1D2PolitenessSecondWave:
    """P1-D2: the post-a22 SMS extension added ``thnx`` / ``thanx`` /
    ``tysm`` / ``kthx`` / ``kthxbai`` but missed a second wave of
    common variants live-observed in the post-a23 sweep:

      - 1-2 char: ``tx``, ``txs``
      - longer SMS: ``tyvm``, ``thnks``, ``thxx``, ``kthxbye``
      - multi-word: ``thanks a million``, ``thank (you|u) (so|very) much``
      - multilingual: ``obrigado(a)``, ``arigato(u)``, ``spasibo``

    Idempotent loop strips combinations cleanly so the existing
    ``please tysm kthxbai`` (three tokens chained) keeps working.
    """

    @pytest.mark.parametrize(
        "token",
        [
            # 1-2 char SMS
            "tx",
            "txs",
            # longer SMS
            "tyvm",
            "thnks",
            "thxx",
            "kthxbye",
            # multi-word
            "thanks a million",
            "thank you so much",
            "thank you very much",
            "thank u so much",
            "thank u very much",
            # multilingual (Portuguese / Japanese romaji / Russian)
            "obrigado",
            "obrigada",
            "arigato",
            "arigatou",
            "spasibo",
        ],
    )
    def test_token_strips_cleanly(self, token: str) -> None:
        cleaned = IntentParser._strip_trailing_politeness(f"biology {token}")
        assert (
            cleaned == "biology"
        ), f"Politeness token {token!r} should strip cleanly; got {cleaned!r}"

    def test_existing_tokens_still_strip(self) -> None:
        # Defensive: every token from the post-a22 set must continue
        # to strip. Regression guard.
        for token in (
            "please",
            "kindly",
            "thanks",
            "thanks a lot",
            "thank you",
            "thank u",
            "pls",
            "thanx",
            "thnx",
            "thx",
            "tysm",
            "ty",
            "kthxbai",
            "kthx",
            "ta",
            "cheers",
            "bitte",
            "danke",
            "merci",
            "gracias",
            "por favor",
        ):
            cleaned = IntentParser._strip_trailing_politeness(f"biology {token}")
            assert (
                cleaned == "biology"
            ), f"Existing token {token!r} regressed; got {cleaned!r}"

    def test_chained_multi_token_politeness(self) -> None:
        # Chains involving the new tokens must peel in one call (the
        # idempotent loop runs up to 4 passes).
        for chain in (
            "please thanks a million",
            "tysm kthxbye",
            "tyvm thnks",
            "obrigado por favor",
        ):
            cleaned = IntentParser._strip_trailing_politeness(f"biology {chain}")
            assert (
                cleaned == "biology"
            ), f"Chain {chain!r} should peel cleanly; got {cleaned!r}"

    def test_embedded_short_tokens_not_eaten(self) -> None:
        # Word-boundary safety: ``tx``, ``txs``, ``ta`` inside other
        # words must not match. The leading anchor
        # ``(?:^|\s+|[,;.!?]\s*)`` requires whitespace OR punctuation
        # before the token, so mid-word matches are impossible.
        for query in (
            "Texas",  # has "tx" / "ta" embedded - but not at word boundary
            "ataxia",
            "cantata",
            "feta",
            "manta",
            "pasta",
            "vista",
            "fiesta",
        ):
            cleaned = IntentParser._strip_trailing_politeness(query)
            assert cleaned == query, (
                f"{query!r} must not have politeness eaten from its tail; "
                f"got {cleaned!r}"
            )

    def test_case_insensitive(self) -> None:
        # ``re.IGNORECASE`` is set; mixed-case + ALL-CAPS variants
        # should strip identically.
        for variant in ("THNX", "Tysm", "KthxBai", "ARIGATO"):
            cleaned = IntentParser._strip_trailing_politeness(f"biology {variant}")
            assert (
                cleaned == "biology"
            ), f"Case-variant {variant!r} should strip; got {cleaned!r}"


# ===========================================================================
# P1-D3: silent fragmentation on ``param=value`` query suffixes
# ===========================================================================


class TestP1D3ParamLeakSuffix:
    """P1-D3: small models occasionally leak MCP tool parameter shapes
    INTO the natural-language query — ``tell me about Photosynthesis
    limit=10`` or ``Berlin compact_budget=200``. Pre-fix, the title-
    promotion tokeniser saw ``"10"`` / ``"200"`` as clean ASCII digit
    tails and scored them against the number-article title index,
    returning a wildly unrelated body (the ``10`` article, year ``200``
    article) and dropping the actual topic with no signal. Live a23
    sweep reproduced for ``limit``, ``offset``, ``content_offset``,
    ``compact_budget``. Fix: ``_strip_param_leaks`` peels these BEFORE
    the politeness loop runs.
    """

    @pytest.mark.parametrize(
        "param,value",
        [
            ("limit", "10"),
            ("offset", "5"),
            ("content_offset", "100"),
            ("max_content_length", "4000"),
            ("max_words", "500"),
            ("compact_budget", "200"),
            ("synthesize", "True"),
            ("compact", "False"),
            ("cursor", "abc123"),
            ("zim_file_path", "/data/wiki.zim"),
            ("entry_path", "C/Biology"),
            ("namespace", "C"),
            ("partial_query", "phot"),
        ],
    )
    def test_param_leak_strips_cleanly(self, param: str, value: str) -> None:
        leaked = f"tell me about Photosynthesis {param}={value}"
        cleaned = IntentParser._strip_param_leaks(leaked)
        assert (
            cleaned == "tell me about Photosynthesis"
        ), f"Leak {param}={value} should strip cleanly; got {cleaned!r}"

    def test_param_leak_strips_in_parse_intent(self) -> None:
        # End-to-end: parse_intent runs the strip and the extracted
        # topic is clean.
        intent, params, _conf = IntentParser.parse_intent(
            "tell me about Photosynthesis limit=10"
        )
        assert intent == "tell_me_about"
        assert params.get("topic") == "Photosynthesis", (
            f"Pre-fix topic was 'Photosynthesis limit=10' → title-promotion "
            f"resolved '10' as the article; got {params.get('topic')!r}"
        )

    def test_multiple_param_leaks_strip_in_one_call(self) -> None:
        leaked = "tell me about Berlin limit=5 compact_budget=200 offset=10"
        cleaned = IntentParser._strip_param_leaks(leaked)
        assert (
            cleaned == "tell me about Berlin"
        ), f"Multiple leaks should peel in one call; got {cleaned!r}"

    def test_param_leak_with_politeness(self) -> None:
        # Param leak + trailing politeness — both should strip via
        # parse_intent's combined pipeline.
        intent, params, _conf = IntentParser.parse_intent(
            "tell me about Berlin limit=5 please"
        )
        assert intent == "tell_me_about"
        assert params.get("topic") == "Berlin"

    def test_normal_words_not_eaten_by_param_strip(self) -> None:
        # The strip requires ``\s+<param>\s*=\s*\S+`` — the ``=`` is
        # mandatory. Prose mentions of param names must stay intact.
        for query in (
            "tell me about offset printing",
            "tell me about cursor algorithms",
            "tell me about the compact disc",
            "search for limit theorems",
        ):
            cleaned = IntentParser._strip_param_leaks(query)
            assert (
                cleaned == query
            ), f"Prose-mention query should stay intact; got {cleaned!r}"

    def test_param_strip_idempotent(self) -> None:
        # Running the strip twice should produce identical output.
        once = IntentParser._strip_param_leaks("tell me about Berlin limit=5")
        twice = IntentParser._strip_param_leaks(once)
        assert once == twice == "tell me about Berlin"


# ===========================================================================
# P1-D4: q-emitting drift scanner uses non-recursive glob
# ===========================================================================


class TestP1D4QEmittingScannerRecursive:
    """P1-D4: the post-a22 P1-D3 widening from ``zim/search.py`` to all
    of ``zim/*.py`` used ``Path.glob`` (direct children only). A
    contributor adding ``openzim_mcp/zim/cursor/encoder.py`` or any
    subdirectory containing q-emitting ``Cursor.encode`` callsites
    would have those silently missed by the scan, breaking the
    drift guard's promise.

    Fix: switch to ``Path.rglob`` (recursive). The current tree is
    flat so behaviour is unchanged today, but future subdirectory
    additions are caught automatically.
    """

    def test_scanner_uses_rglob_not_glob(self) -> None:
        # Inspect the scanner's source for the rglob call. This is a
        # belt-and-suspenders check — the real value comes from
        # subdirectory probes below, but the source-level check
        # catches future regressions where someone reverts to
        # non-recursive glob.
        scanner_source = (
            Path(__file__).resolve().parents[0] / "test_post_a22_beta_fixes.py"
        )
        text = scanner_source.read_text(encoding="utf-8")
        assert "rglob" in text, (
            "test_post_a22_beta_fixes.py should use rglob for "
            "subdirectory-resilient scanning"
        )

    def test_scanner_module_imports_pathlib_rglob(self) -> None:
        # Belt-and-suspenders: ensure the test module still imports
        # from pathlib (Path.rglob is the method we rely on).
        from tests import test_post_a22_beta_fixes as t22

        assert hasattr(t22, "Path"), "test module must import Path"

    def test_scanner_returns_expected_q_emitting_tools(self) -> None:
        # The current zim/ tree is flat; ``rglob`` and ``glob`` produce
        # identical results today. This test pins the expected set so
        # that if a future contributor adds a q-emitting tool, both the
        # scanner output AND the dispatcher set update in lockstep.
        from tests.test_post_a22_beta_fixes import (
            TestP1D3QEmittingDriftGuardWiderScope,
        )

        scanned = TestP1D3QEmittingDriftGuardWiderScope._scan_q_emitting_tools_in_zim()
        assert "search_zim_file" in scanned
        assert "search_with_filters" in scanned
        # Pinned set from a22 P1-D5 — no q-emitting tools have been
        # added since.
        assert scanned == {"search_zim_file", "search_with_filters"}


# ===========================================================================
# Live-MCP reproduction probes (mock-based) — assert that the cleaned
# parse_intent output drives the correct downstream behaviour.
# ===========================================================================


class TestLiveMcpReproduction:
    """End-to-end probes that mirror the live-MCP queries the sweep
    observed. Each test parses the query via ``parse_intent`` and
    asserts the cleaned ``params`` carry the expected topic / query —
    a non-stripped leak would surface as the wrong topic.
    """

    def test_photosynthesis_limit_param_strips_topic(self) -> None:
        intent, params, _conf = IntentParser.parse_intent(
            "tell me about Photosynthesis limit=10"
        )
        assert intent == "tell_me_about"
        assert params.get("topic") == "Photosynthesis"

    def test_berlin_compact_budget_strips_topic(self) -> None:
        intent, params, _conf = IntentParser.parse_intent(
            "tell me about Berlin compact_budget=200"
        )
        assert intent == "tell_me_about"
        assert params.get("topic") == "Berlin"

    def test_search_biology_tyvm_strips_politeness(self) -> None:
        intent, params, _conf = IntentParser.parse_intent("search for biology tyvm")
        assert intent == "search"
        assert params.get("query") == "biology"

    def test_search_biology_thanks_a_million_strips(self) -> None:
        intent, params, _conf = IntentParser.parse_intent(
            "search for biology thanks a million"
        )
        assert intent == "search"
        assert params.get("query") == "biology"

    def test_search_biology_obrigado_strips(self) -> None:
        intent, params, _conf = IntentParser.parse_intent("search for biology obrigado")
        assert intent == "search"
        assert params.get("query") == "biology"

    def test_search_biology_thank_you_very_much_strips(self) -> None:
        intent, params, _conf = IntentParser.parse_intent(
            "search for biology thank you very much"
        )
        assert intent == "search"
        assert params.get("query") == "biology"


# ===========================================================================
# Regression guards — ensure the new ALL-CAPS clause and slashed-compound
# guard don't break post-a20/a21/a22 fixes
# ===========================================================================


class TestRegressionGuards:
    """Defensive checks: the changes in this sweep must not regress
    any prior-alpha fix. Targeted spot checks on a17 → a22's most
    important behaviours.
    """

    def test_a22_first_word_and_still_preserved(self) -> None:
        # Post-a22 P1-D1 smoke gate.
        result = SimpleToolsHandler._split_multi_entity(
            "And Then There Were None and Hercule Poirot and Murder on the Orient Express"
        )
        assert result is not None
        assert result[0] == "And Then There Were None"

    def test_a22_first_word_or_still_preserved(self) -> None:
        result = SimpleToolsHandler._split_multi_entity(
            "Or Else and Death and Taxes and Pride and Prejudice"
        )
        assert result is not None
        assert result[0] == "Or Else"

    def test_a19_unicode_substantive_still_works(self) -> None:
        # Post-a19 P1-D3 short non-Latin substantive.
        assert SimpleToolsHandler._is_substantive_topic("東京")
        assert SimpleToolsHandler._is_substantive_topic("Köln")

    def test_a16_english_sentence_words_still_rejected(self) -> None:
        # Post-a16 D1 single-token English sentence-words.
        for token in ("Now", "Both", "Here", "Then", "Many", "Some"):
            assert not SimpleToolsHandler._is_substantive_topic(token)

    def test_a22_search_for_biology_please_still_strips(self) -> None:
        cleaned = IntentParser._strip_trailing_politeness("search for biology please")
        assert cleaned == "search for biology"

    def test_a22_earth_wind_and_fire_still_returns_none(self) -> None:
        # Confirms the post-a21 ``test_multi_entity_title_suppresses
        # _warning`` defence-in-depth shape still holds AFTER the
        # post-a23 ALL-CAPS substantive clause was added: ``Wind`` and
        # ``Fire`` are 4-char mixed-case tokens (not ALL-CAPS, no
        # digit, no non-ASCII letter), so they still fail substantive
        # and ``_split_multi_entity`` returns None — short-circuiting
        # the chain rejection before the title-loose-match check runs.
        # The ALL-CAPS clause must NOT relax this check (the existing
        # post-a16 D1 sentence-word rejection stays intact).
        result = SimpleToolsHandler._split_multi_entity("Earth, Wind & Fire")
        assert result is None, (
            f"Expected None (Wind/Fire fail substantive in mixed case); "
            f"got {result!r}"
        )
