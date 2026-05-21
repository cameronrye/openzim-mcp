r"""Regression tests for the post-b1 beta-test sweep.

The post-b1 live-MCP sweep against the 118 GB Wikipedia ZIM after
v2.0.0b1 deployed surfaced SIX user-facing defects in the new Phase D
Tier-1 query-rewriting (sub-D-2) wiring, plus an in-band telemetry gap
for the new cross-encoder reranker (sub-D-1).

Defects span FOUR surfaces:

* **P1-D1 — title_probe built from caller-supplied zim_file_path BEFORE
  auto-archive-selection.** The handler builds the probe at the top of
  ``handle_zim_query`` from the raw caller argument; the auto-select
  fallback happens later (line ~776). When the caller follows the tool
  docstring's recommendation to OMIT ``zim_file_path``, the probe is
  built with ``None`` and returns ``None``, causing all probe-gated
  rules (Rule 2 misspellings, Rule 3 article-strip, Rule 4 X-of-Y) to
  silently degrade. Live impact:

    - ``the Beatles`` → ``**Multiple articles match "beatles"**`` disambig
      (Rule 3 stripped ``the`` instead of suppressing on probe-hit)
    - ``An American in Paris`` → 🚨 ``Niggas_in_Paris`` (offensive
      misroute; Rule 3 stripped ``an`` then fuzzy-matched the wrong song)
    - ``A Christmas Carol`` → ``Christmas_carol`` concept (Dickens
      novella destroyed)

  Fix: add ``_probe_archive_path()`` helper that calls
  ``_auto_select_zim_file()`` when the caller-supplied path is empty,
  then call it before ``_build_title_probe`` at both wiring sites
  (simple-branch line ~624, synthesize-branch line ~5071-72).

* **P1-D2 — Rule 1's full-query lowercase leaks into user-facing chain
  rejection bullets and soft-connector footer.** ``_multi_entity_chain
  _guidance`` and ``_soft_connector_footer`` echo entities from
  ``params["topic"]``, which is extracted from the lowercased query
  inside ``parse_intent``. Live impact: ``tell me about Köln, München,
  and Berlin`` → rejection bullets read ``tell me about köln`` /
  ``münchen`` / ``berlin``; the caller's recovery copy-paste path
  loses casing and diacritics. Fix: stash the pre-rewrite
  original-case query in ``params["_pre_rewrite_query"]`` at the
  wiring layer; thread it through both functions; new helper
  ``_recase_from_original()`` finds each lowercase token in the
  original query via case-insensitive substring lookup.

* **P1-D3 — Rule 4 ``_decompose_x_of_y`` has NO title-probe guard at
  all.** The decomposition regex ``^(?P<attr>\w+)\s+of\s+(?P<entity>
  .{1,200})$`` fires for every ``X of Y`` query whose attr isn't in
  the structural-intent skip-set (``structure``, ``summary``,
  ``list``...). Real-content nouns (``art``, ``lord``, ``origin``,
  ``birth``, ``death``, ``wealth``, ``state``, ``king``, ``history``,
  ``population``) decompose unconditionally — for canonical
  X-of-Y titles, the lookup goes to the bare entity. Live impact:

    - ``lord of the rings`` → ``The_Rings`` (1985 Iranian horror film)
    - ``the art of war`` → ``War`` concept (not Sun Tzu)
    - ``wealth of nations`` → ``Nation`` concept (not Adam Smith)
    - ``state of the union`` → ``The_Union`` disambig
    - ``origin of species`` → ``Species`` concept (not Darwin)
    - ``birth of venus`` → ``Venus`` disambig (not Botticelli painting)
    - ``death of stalin`` → ``Stalin`` disambig (not Iannucci film)
    - ``history of rome`` → ``Rome`` city (not ``History_of_Rome``)

  Fix: mirror Rule 3's probe gate inside Rule 4 — when ``title_probe
  (query)`` is True, return ``(query, None)`` and suppress
  decomposition. Forward the same probe from ``_apply_tier1_rewrites``
  alongside rules 2 and 3.

* **P1-D5 / P1-D6 — Rule 2 misses possessives and trailing
  punctuation.** ``_apply_misspelling_map`` splits on whitespace only.
  Tokens with attached punctuation (``bilogy.``, ``"recieve"``,
  ``photosythesis``'s possessive) don't match the bare-stem keys
  (``bilogy``, ``recieve``, ``photosythesis``). Live impact:

    - ``tell me about Photosythesis's reproduction`` → ``No search
      results found`` (no fallback path catches the possessive form)
    - ``tell me about bilogy.`` rescued accidentally by the post-a11
      fuzzy fallback, but the rewrite layer itself is silently
      ineffective for trailing punctuation

  Fix: when raw-token lookup misses, run ``_MISSPELL_AFFIX_RE``
  to split into ``(prefix, core, suffix)``, strip a trailing ``'s``
  possessive, retry the map on the core, and reattach the affixes
  to the substitution on hit.

* **(D-1 telemetry gap)**: reranker engagement state lives in
  ``self._telemetry`` Counter, surfaced only via the advanced
  ``get_server_health`` tool. Some HTTP-MCP hosts filter that tool
  out, leaving simple-tool callers with no in-band way to confirm
  whether D-1 reranking actually engaged for their request.
  ``bbda863`` already added INFO-level logging, but logs aren't
  reachable for external simple-tool callers. Fix: snapshot the
  four reranker counters at the start of ``handle_zim_query``; new
  ``_compute_rerank_state()`` returns a one-of-four engagement
  state from the post-call delta; appended as
  ``<!-- reranker=<state> -->`` in the response envelope
  (mirrors the existing ``<!-- intent=... cert=... -->`` shape).

Methodology continues to hold:
  * "Narrow-scope sibling" pattern reproduced at the FEATURE level:
    the new D-2 wiring shipped four probe-gated rules but the probe
    itself was gated narrower than the recommended usage — every
    rule that consults the probe is affected.
  * "Fix unlocks new paths" reproduced for the 6th sweep — D-2's
    Rule 4 LANDED (decomposes ``population of berlin`` cleanly to
    ``berlin``) but exposed the canonical-title-decomposition
    family that has no guard at all.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Callable, Dict, List, Optional

import pytest

from openzim_mcp.intent_parser import IntentParser

# ===========================================================================
# P1-D1: title_probe degrades when caller omits zim_file_path
# ===========================================================================


class _StubZimOps:
    """Minimal stub of ``ZimOperations`` for probe-archive tests. The
    real object has dozens of methods; we only need
    ``list_zim_files_data`` for ``_auto_select_zim_file`` plus a
    ``config`` shim. Mock-style frameworks would work too but a small
    stub stays readable and explicit about the contract being tested."""

    def __init__(self, files: List[Dict[str, Any]]) -> None:
        self._files = files

        class _RewriteCfg:
            enabled = True

        class _RerankerCfg:
            enabled = True

        class _MlCfg:
            reranker = _RerankerCfg()

        class _Cfg:
            query_rewrite = _RewriteCfg()
            ml = _MlCfg()

        self.config = _Cfg()

    def list_zim_files_data(self) -> List[Dict[str, Any]]:
        return self._files


class _ProbeHarness:
    """Adapter that exposes ONLY the methods the P1-D1 fix touches:
    ``_probe_archive_path``, ``_build_title_probe``, and
    ``_auto_select_zim_file``. Avoids constructing the full
    SimpleToolsHandler (which would require a real backend).

    Methods are called as unbound (``SimpleToolsHandler._probe_archive
    _path(harness, ...)``) so we can pass any duck-typed object as
    ``self``. mypy can't see that we're satisfying the structural
    contract, hence ``# type: ignore[arg-type]`` on each call site."""

    def __init__(self, files: List[Dict[str, Any]]) -> None:
        self.zim_operations = _StubZimOps(files)

    def _auto_select_zim_file(self) -> Optional[str]:
        # Mirror the real implementation's contract: single loaded
        # archive → return its path; zero or >1 → None.
        files = self.zim_operations.list_zim_files_data()
        if len(files) == 1:
            return str(files[0]["path"])
        return None

    def probe_archive_path(self, candidate: Optional[str]) -> Optional[str]:
        from openzim_mcp.simple_tools import SimpleToolsHandler

        return SimpleToolsHandler._probe_archive_path(self, candidate)  # type: ignore[arg-type]


class TestP1D1ProbeArchiveResolution:
    """P1-D1: pre-fix, ``title_probe`` was built from the raw caller-
    supplied ``zim_file_path`` BEFORE downstream auto-resolution. When
    the caller followed the docstring's recommendation to OMIT the
    path, the probe was ``None`` and every probe-gated rewrite (Rule
    2, Rule 3, post-fix Rule 4) silently degraded.

    Fix: ``_probe_archive_path`` falls back to
    ``_auto_select_zim_file`` when the caller-supplied path is None,
    so the probe sees the same archive ``handle_zim_query`` will
    auto-select downstream."""

    def test_explicit_path_passes_through_unchanged(self) -> None:
        harness = _ProbeHarness(
            [{"path": "/data/wikipedia.zim", "name": "wikipedia.zim"}]
        )
        assert (
            harness.probe_archive_path("/data/something_else.zim")
            == "/data/something_else.zim"
        )

    def test_none_input_falls_back_to_auto_select_single_archive(self) -> None:
        # Single-archive case: auto-select returns the only loaded archive.
        # Pre-fix this returned None and built a None probe.
        harness = _ProbeHarness(
            [{"path": "/data/wikipedia.zim", "name": "wikipedia.zim"}]
        )
        assert harness.probe_archive_path(None) == "/data/wikipedia.zim"

    def test_none_input_with_multiple_archives_stays_none(self) -> None:
        # Multi-archive without explicit path is genuinely ambiguous —
        # _auto_select_zim_file returns None, so the probe correctly
        # stays in degraded mode.
        harness = _ProbeHarness(
            [
                {"path": "/data/wiki_en.zim", "name": "wiki_en.zim"},
                {"path": "/data/wiki_de.zim", "name": "wiki_de.zim"},
            ]
        )
        assert harness.probe_archive_path(None) is None

    def test_none_input_with_zero_archives_stays_none(self) -> None:
        # No archives loaded — there is nothing for the probe to consult.
        harness = _ProbeHarness([])
        assert harness.probe_archive_path(None) is None

    def test_empty_string_input_treated_as_none(self) -> None:
        # Defence: an empty-string ``zim_file_path`` should NOT bypass
        # the auto-select fallback. ``if zim_file_path`` correctly
        # short-circuits on the empty string.
        harness = _ProbeHarness(
            [{"path": "/data/wikipedia.zim", "name": "wikipedia.zim"}]
        )
        assert harness.probe_archive_path("") == "/data/wikipedia.zim"


# ===========================================================================
# P1-D3: Rule 4 _decompose_x_of_y now consults title_probe to suppress
#        decomposition of canonical multi-word titles
# ===========================================================================


def _probe_factory(*canonical_titles: str) -> Callable[[str], bool]:
    """Build a title_probe that returns True iff ``query`` (case-
    insensitive) matches one of the canonical titles passed in."""
    lowered = {t.lower() for t in canonical_titles}

    def probe(q: str) -> bool:
        return q.lower() in lowered

    return probe


class TestP1D3Rule4ProbeGate:
    """P1-D3: Rule 4 used to fire unconditionally for any
    ``<word> of <stuff>`` query whose attribute word wasn't in the
    structural-intent skip-set. Canonical multi-word titles
    (``lord of the rings``, ``the art of war``, ``birth of venus``,
    ``history of rome``) were silently torn apart, with the resulting
    bare-entity lookup returning unrelated articles.

    Fix: probe the full query; on a canonical-title hit, return
    ``(query, None)`` and skip decomposition."""

    @pytest.mark.parametrize(
        "canonical_query",
        [
            "lord of the rings",
            "art of war",
            "the art of war",
            "wealth of nations",
            "state of the union",
            "origin of species",
            "birth of venus",
            "death of stalin",
            "history of rome",
            "king of england",
            "rise of the planet of the apes",
        ],
    )
    def test_probe_hit_suppresses_decomposition(self, canonical_query: str) -> None:
        # Probe returns True for the full query → no decomposition.
        probe = _probe_factory(canonical_query)
        rewritten, hint = IntentParser._decompose_x_of_y(
            canonical_query, title_probe=probe
        )
        assert rewritten == canonical_query
        assert hint is None

    def test_probe_miss_still_decomposes(self) -> None:
        # ``population of berlin`` is NOT a canonical title (the title
        # is just ``berlin``). The probe misses; decomposition still
        # fires and the hint flows through to _handle_tell_me_about.
        probe = _probe_factory("berlin")  # only ``berlin`` is canonical
        rewritten, hint = IntentParser._decompose_x_of_y(
            "population of berlin", title_probe=probe
        )
        assert rewritten == "berlin population"
        assert hint == {"entity": "berlin", "attribute": "population"}

    def test_no_probe_legacy_behavior(self) -> None:
        # Without a probe (degraded mode, e.g. multi-archive without
        # explicit path), Rule 4 falls back to its pre-fix behaviour
        # of decomposing everything. The DEGRADATION class P1-D1 is
        # the real fix; this test pins the legacy fall-through.
        rewritten, hint = IntentParser._decompose_x_of_y("lord of the rings")
        assert hint == {"entity": "the rings", "attribute": "lord"}
        assert rewritten == "the rings lord"

    def test_skip_attr_short_circuits_before_probe(self) -> None:
        # ``structure of biology`` — ``structure`` is in
        # _DECOMPOSE_SKIP_ATTRS, so the skip check returns early
        # before the probe is consulted. Doesn't matter if a probe is
        # passed; structural commands NEVER decompose.
        probe = _probe_factory("biology")  # entity probes True
        rewritten, hint = IntentParser._decompose_x_of_y(
            "structure of biology", title_probe=probe
        )
        assert hint is None
        assert rewritten == "structure of biology"

    def test_possessive_form_also_consults_probe(self) -> None:
        # The possessive shape ``berlin's population`` goes through
        # the SAME ``title_probe`` gate. If the FULL query (with
        # possessive) is canonical, suppress.
        probe = _probe_factory("berlin's population")  # contrived
        rewritten, hint = IntentParser._decompose_x_of_y(
            "berlin's population", title_probe=probe
        )
        assert rewritten == "berlin's population"
        assert hint is None

    def test_pipeline_forwards_probe_to_rule_4(self) -> None:
        # End-to-end: _apply_tier1_rewrites forwards the probe to all
        # three probe-gated rules. ``lord of the rings`` with a
        # canonical-title probe must return ``(query, None)``.
        probe = _probe_factory("lord of the rings")
        rewritten, hint = IntentParser._apply_tier1_rewrites(
            "Lord of the Rings",
            title_probe=probe,
            enabled=True,
        )
        # Rule 1 lowercases; Rule 4 probe-suppresses decomposition.
        assert rewritten == "lord of the rings"
        assert hint is None


# ===========================================================================
# P1-D5 / P1-D6: Rule 2 affix-stripped retry
# ===========================================================================


class TestP1D5PossessiveMisspelling:
    """P1-D5: ``photosythesis's reproduction`` previously didn't get
    fixed by Rule 2 because the possessive ``'s`` made the lookup
    key ``photosythesis's`` (not in map). Live: returned ``No search
    results found``. Fix: strip a trailing ``'s`` before map lookup,
    reattach on hit."""

    def test_possessive_misspelling_corrected(self) -> None:
        out = IntentParser._apply_misspelling_map(
            "photosythesis's reproduction", title_probe=None
        )
        assert out == "photosynthesis's reproduction"

    def test_possessive_misspelling_preserves_following_tokens(self) -> None:
        out = IntentParser._apply_misspelling_map(
            "tell me about photosythesis's reproduction",
            title_probe=None,
        )
        assert out == "tell me about photosynthesis's reproduction"

    def test_possessive_on_clean_word_no_change(self) -> None:
        # ``berlin's population`` — ``berlin`` isn't a misspelling
        # key. Lookup misses both raw and after-strip.
        out = IntentParser._apply_misspelling_map(
            "berlin's population", title_probe=None
        )
        assert out == "berlin's population"

    def test_possessive_on_excluded_word_preserved(self) -> None:
        # Exclusions check applies to the post-strip core too. If a
        # word is on the exclusions list, possessive form should also
        # be preserved.
        class _OverrideParser(IntentParser):
            pass

        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f_map:
            f_map.write("photosythesis=photosynthesis\n")
            mp = f_map.name
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f_excl:
            f_excl.write("photosythesis\n")
            ep = f_excl.name
        _OverrideParser._misspellings_path = mp  # type: ignore[assignment]
        _OverrideParser._exclusions_path = ep  # type: ignore[assignment]
        try:
            out = _OverrideParser._apply_misspelling_map(
                "photosythesis's reproduction", title_probe=None
            )
            assert (
                out == "photosythesis's reproduction"
            ), f"Exclusion should suppress possessive too; got {out!r}"
        finally:
            import os

            os.unlink(mp)
            os.unlink(ep)


class TestP1D6PunctuationMisspelling:
    """P1-D6: tokens with leading/trailing punctuation
    (``bilogy.``, ``"recieve"``, ``(photosythesis)``) previously
    bypassed Rule 2 because the lookup key included the punctuation.
    Fix: strip leading/trailing non-word characters before lookup,
    reattach on hit."""

    @pytest.mark.parametrize(
        "before, after",
        [
            ("tell me about bilogy.", "tell me about biology."),
            ("bilogy.", "biology."),
            ("bilogy?", "biology?"),
            ("bilogy!", "biology!"),
            ("bilogy,", "biology,"),
            ("bilogy;", "biology;"),
            ('"recieve"', '"receive"'),
            ("(recieve)", "(receive)"),
            ("'recieve'", "'receive'"),
            ("recieve.", "receive."),
        ],
    )
    def test_punctuation_attached_misspelling_corrected(
        self, before: str, after: str
    ) -> None:
        assert IntentParser._apply_misspelling_map(before, title_probe=None) == after

    def test_punctuation_then_possessive_combined(self) -> None:
        # ``"photosythesis's"`` — leading quote, possessive, trailing
        # quote all in one token. Affix regex strips the quotes, the
        # possessive-suffix step strips ``'s``, lookup matches.
        out = IntentParser._apply_misspelling_map(
            '"photosythesis\'s"', title_probe=None
        )
        assert out == '"photosynthesis\'s"'

    def test_punctuation_on_clean_word_no_change(self) -> None:
        # ``biology.`` — clean word with trailing period. Lookup
        # misses (it's not a misspelling). Affix retry strips the
        # period, looks up ``biology``, still misses. Token returns
        # unchanged.
        out = IntentParser._apply_misspelling_map("biology.", title_probe=None)
        assert out == "biology."

    def test_hyphenated_not_split(self) -> None:
        # ``photo-synthesis`` doesn't whitespace-split, isn't a
        # misspelling map key, hyphen isn't stripped by the affix
        # retry (it's interior to the word). Stays unchanged —
        # documented limitation; Rule 2 is not a hyphen-splitter.
        out = IntentParser._apply_misspelling_map(
            "tell me about photo-synthesis", title_probe=None
        )
        assert out == "tell me about photo-synthesis"

    def test_probe_suppresses_post_retry(self) -> None:
        # The title-probe gate consults the ORIGINAL token (not the
        # stripped core) so legitimate proper-noun-with-punctuation
        # tokens that happen to match a misspelling after-strip still
        # get suppressed if the original is a real entity.
        def probe(token: str) -> bool:
            return token == "Bilogy."  # contrived canonical title

        out = IntentParser._apply_misspelling_map("Bilogy.", title_probe=probe)
        assert out == "Bilogy."  # probe suppression wins


# ===========================================================================
# P1-D2: original-case topic preservation in chain rejection / footer
# ===========================================================================


class TestP1D2RecaseHelper:
    """P1-D2: ``_recase_from_original`` finds a (lowercase) token in
    the original-case query and returns the matched slice in its
    original casing. Falls back to the input token when no match."""

    def test_simple_recase_diacritics_preserved(self) -> None:
        from openzim_mcp.simple_tools import SimpleToolsHandler

        original = "tell me about Köln, München, and Berlin"
        assert SimpleToolsHandler._recase_from_original("köln", original) == "Köln"
        assert (
            SimpleToolsHandler._recase_from_original("münchen", original) == "München"
        )
        assert SimpleToolsHandler._recase_from_original("berlin", original) == "Berlin"

    def test_simple_recase_articles_preserved(self) -> None:
        from openzim_mcp.simple_tools import SimpleToolsHandler

        original = "tell me about The Beatles and The Rolling Stones"
        assert (
            SimpleToolsHandler._recase_from_original("the beatles", original)
            == "The Beatles"
        )
        assert (
            SimpleToolsHandler._recase_from_original("the rolling stones", original)
            == "The Rolling Stones"
        )

    def test_token_not_in_original_falls_back_to_input(self) -> None:
        # If the token doesn't appear in the original (e.g., Rule 4
        # reordered the words), the helper falls back to the
        # lowercase input — no recasing possible.
        from openzim_mcp.simple_tools import SimpleToolsHandler

        original = "Tell me about Berlin"
        assert SimpleToolsHandler._recase_from_original("munich", original) == "munich"

    def test_empty_inputs_handled(self) -> None:
        from openzim_mcp.simple_tools import SimpleToolsHandler

        assert SimpleToolsHandler._recase_from_original("", "anything") == ""
        assert SimpleToolsHandler._recase_from_original("token", "") == "token"


# ===========================================================================
# Reranker telemetry: in-band response-envelope comment
# ===========================================================================


class TestRerankerStateComment:
    """Post-b1: ``_compute_rerank_state`` returns the per-request
    reranker engagement state by comparing the current telemetry
    counter to a pre-call snapshot. Used to emit the
    ``<!-- reranker=<state> -->`` HTML comment in the response."""

    def _make_handler_stub(self) -> Any:
        """Build a minimal stub carrying just the ``_telemetry``
        Counter. The ``_compute_rerank_state`` method is called
        unbound (passing the stub as ``self``) so this stays decoupled
        from SimpleToolsHandler's heavier construction surface."""

        class _Stub:
            def __init__(self) -> None:
                self._telemetry: Counter[str] = Counter()

            def compute(self, before: Dict[str, int]) -> Optional[str]:
                from openzim_mcp.simple_tools import SimpleToolsHandler

                fn = SimpleToolsHandler._compute_rerank_state
                return fn(self, before)  # type: ignore[arg-type]

        return _Stub()

    def test_no_event_returns_none(self) -> None:
        from openzim_mcp.simple_tools import (
            _RERANKER_ENGAGED,
            _RERANKER_SKIPPED_NO_RESULTS,
            _RERANKER_SKIPPED_NOT_INSTALLED,
            _RERANKER_SKIPPED_PASSTHROUGH,
        )

        stub = self._make_handler_stub()
        before = {
            _RERANKER_ENGAGED: 0,
            _RERANKER_SKIPPED_NOT_INSTALLED: 0,
            _RERANKER_SKIPPED_NO_RESULTS: 0,
            _RERANKER_SKIPPED_PASSTHROUGH: 0,
        }
        # Counters unchanged — non-search intent, no rerank attempt.
        assert stub.compute(before) is None

    def test_engaged_detected(self) -> None:
        from openzim_mcp.simple_tools import _RERANKER_ENGAGED

        stub = self._make_handler_stub()
        before = {_RERANKER_ENGAGED: 0}
        stub._telemetry[_RERANKER_ENGAGED] = 1
        assert stub.compute(before) == "engaged"

    def test_skipped_not_installed_detected(self) -> None:
        from openzim_mcp.simple_tools import _RERANKER_SKIPPED_NOT_INSTALLED

        stub = self._make_handler_stub()
        before = {_RERANKER_SKIPPED_NOT_INSTALLED: 5}
        stub._telemetry[_RERANKER_SKIPPED_NOT_INSTALLED] = 6
        assert stub.compute(before) == "skipped:not_installed"

    def test_skipped_no_results_detected(self) -> None:
        from openzim_mcp.simple_tools import _RERANKER_SKIPPED_NO_RESULTS

        stub = self._make_handler_stub()
        before = {_RERANKER_SKIPPED_NO_RESULTS: 0}
        stub._telemetry[_RERANKER_SKIPPED_NO_RESULTS] = 1
        assert stub.compute(before) == "skipped:no_results"

    def test_skipped_passthrough_detected(self) -> None:
        from openzim_mcp.simple_tools import _RERANKER_SKIPPED_PASSTHROUGH

        stub = self._make_handler_stub()
        before = {_RERANKER_SKIPPED_PASSTHROUGH: 0}
        stub._telemetry[_RERANKER_SKIPPED_PASSTHROUGH] = 1
        assert stub.compute(before) == "skipped:passthrough"

    def test_engaged_priority_over_skip(self) -> None:
        # If both ``engaged`` and a skip counter bump (rare; cross-
        # archive partial failure), ``engaged`` wins so the caller
        # sees the most favourable summary.
        from openzim_mcp.simple_tools import (
            _RERANKER_ENGAGED,
            _RERANKER_SKIPPED_PASSTHROUGH,
        )

        stub = self._make_handler_stub()
        before = {
            _RERANKER_ENGAGED: 0,
            _RERANKER_SKIPPED_PASSTHROUGH: 0,
        }
        stub._telemetry[_RERANKER_ENGAGED] = 1
        stub._telemetry[_RERANKER_SKIPPED_PASSTHROUGH] = 1
        assert stub.compute(before) == "engaged"


# ===========================================================================
# Cross-feature integration: the six pass-1 fixes interact at the
# dispatcher level
# ===========================================================================


class TestPass2CrossFeatureIntegration:
    """Pass-2 source-level audit: the post-b1 fixes ride on the same
    dispatcher path. Verify the composition order:

      1. Rule 1 lowercases the query.
      2. Rule 2 applies misspelling map (with affix retry + probe).
      3. Rule 3 strips a leading article (probe-gated).
      4. Rule 4 decomposes X-of-Y (probe-gated).
      5. parse_intent runs the existing regex chain.

    Each rule sees the output of the previous; probes flow through
    rules 2-4. Cross-feature combinations should compose cleanly."""

    def test_rule_2_then_rule_4_with_probe(self) -> None:
        # ``population of bilogy`` — Rule 2 fixes ``bilogy`` →
        # ``biology``; Rule 4 then decomposes ``population of biology``.
        # Probe consulted for FULL post-Rule-3 query ``population of
        # biology`` — assume probe misses (not a canonical title).
        probe = _probe_factory("biology")  # only ``biology`` is canonical
        rewritten, hint = IntentParser._apply_tier1_rewrites(
            "population of bilogy",
            title_probe=probe,
            enabled=True,
        )
        assert rewritten == "biology population"
        assert hint == {"entity": "biology", "attribute": "population"}

    def test_rule_3_strip_unblocked_by_probe_suppression(self) -> None:
        # ``the beatles`` with probe returning True for the full query
        # → Rule 3 keeps the article, Rule 4 doesn't match (no `` of ``
        # in `the beatles`).
        probe = _probe_factory("the beatles")
        rewritten, hint = IntentParser._apply_tier1_rewrites(
            "The Beatles",
            title_probe=probe,
            enabled=True,
        )
        assert rewritten == "the beatles"
        assert hint is None

    def test_rule_3_strip_fires_when_probe_misses(self) -> None:
        # ``the goverment of berlin`` — Rule 3 strips ``the`` (probe
        # misses on the FULL query, even though ``berlin`` is canonical);
        # Rule 2 corrects ``goverment`` → ``government``; Rule 4
        # decomposes ``government of berlin`` to ``berlin government``.
        probe = _probe_factory("berlin")
        rewritten, hint = IntentParser._apply_tier1_rewrites(
            "the goverment of berlin",
            title_probe=probe,
            enabled=True,
        )
        # After Rule 2: ``the government of berlin``
        # After Rule 3: ``government of berlin`` (the stripped)
        # After Rule 4: ``berlin government``
        assert rewritten == "berlin government"
        assert hint == {"entity": "berlin", "attribute": "government"}

    def test_kill_switch_skips_all_four_rules_including_probe_gates(self) -> None:
        # Master switch off: query passes through unchanged regardless
        # of probe behaviour. This pins the existing kill-switch
        # contract — the new probe wiring must not break it.
        probe = _probe_factory("anything")
        rewritten, hint = IntentParser._apply_tier1_rewrites(
            "The Lord Of The Rings",
            title_probe=probe,
            enabled=False,
        )
        assert rewritten == "The Lord Of The Rings"
        assert hint is None

    def test_misspelling_with_possessive_then_x_of_y(self) -> None:
        # ``photosythesis's role`` doesn't match Rule 4 (only one ``of``
        # rule). But Rule 2 should fix the possessive misspelling
        # regardless. ``recieve's effect on biology`` exercises both
        # rules: Rule 2 fixes ``recieve``, Rule 4 doesn't fire (the
        # possessive shape is ``<word>'s <word>``, but `recieve` →
        # `receive` then matches `_POSSESSIVE_RE` as
        # `receive's effect on biology`? No — possessive regex needs
        # `entity's attr` with `attr` a single word; ``effect on
        # biology`` is 3 words.) So Rule 4 stays out.
        rewritten, hint = IntentParser._apply_tier1_rewrites(
            "recieve's effect",
            title_probe=None,
            enabled=True,
        )
        # Rule 2 fixes possessive: ``receive's effect``
        # Rule 4 possessive regex: attr=``effect``, entity=``receive`` →
        # decomposes to ``receive effect`` with hint.
        assert rewritten == "receive effect"
        assert hint == {"entity": "receive", "attribute": "effect"}


# ===========================================================================
# Regression guards: confirm the post-b1 fixes don't break prior contracts
# ===========================================================================


class TestPass3SearchBackendEchoPlumbing:
    """Pass-3 source-level audit followed pass-2's deferral. The 5
    user-facing echo strings in ``zim/search.py`` (``Found N matches
    for "X"``, ``No search results found for "X"``, recovery hints,
    filtered variants) all read ``payload["query"]`` / the function-
    local ``query`` arg, which the dispatcher passes as Rule-1-
    lowercased. Pass-2 documented these as backend-plumbing work;
    pass-3 lands the plumbing via a new optional ``display_query``
    kwarg threaded through ``_format_search_text`` →
    ``search_zim_file``, and ``_format_filtered_response`` →
    ``search_with_filters`` / ``_perform_filtered_search`` /
    ``search_with_filters_with_canonical_splice``.

    Backend matching is unchanged — Xapian is case-insensitive, so
    the query/cache key keep the lowercase form for stability; only
    the user-facing echoes pick up the original case."""

    def _make_format_payload(
        self,
        *,
        query: str = "biology",
        total: int = 0,
        results: Optional[list] = None,
    ) -> Dict[str, Any]:
        """Build a minimal SearchResponse-shaped dict for
        ``_format_search_text``. Only the keys the formatter reads
        need to be set."""
        return {
            "query": query,
            "total": total,
            "page_info": {"offset": 0, "limit": 5},
            "results": results or [],
            "done": True,
        }

    def test_format_search_text_no_results_uses_display_query(self) -> None:
        # Pre-fix: ``No search results found for "biology"``.
        # Post-fix: ``No search results found for "Biology"``.
        # Use _SearchMixin._format_search_text as an unbound function so
        # we don't have to construct the full backend.
        from openzim_mcp.zim.search import _SearchMixin

        payload = self._make_format_payload(query="biology", total=0)

        class _Stub:
            pass

        fn = _SearchMixin._format_search_text
        out = fn(_Stub(), payload, display_query="Biology")  # type: ignore[arg-type]
        assert 'No search results found for "Biology".' in out
        assert "biology" not in out  # the lowercase form is fully replaced

    def test_format_search_text_no_results_falls_back_when_no_display(
        self,
    ) -> None:
        # Legacy behaviour: when display_query is None, echo uses
        # payload["query"].
        from openzim_mcp.zim.search import _SearchMixin

        payload = self._make_format_payload(query="biology", total=0)

        class _Stub:
            pass

        fn = _SearchMixin._format_search_text
        out = fn(_Stub(), payload)  # type: ignore[arg-type]
        assert 'No search results found for "biology".' in out

    def test_format_search_text_with_results_uses_display_query(self) -> None:
        from openzim_mcp.zim.search import _SearchMixin

        payload = self._make_format_payload(
            query="biology",
            total=10,
            results=[
                {"title": "Biology", "path": "Biology", "snippet": "..."},
            ],
        )

        class _Stub:
            pass

        fn = _SearchMixin._format_search_text
        out = fn(_Stub(), payload, display_query="Biology")  # type: ignore[arg-type]
        assert 'Found 10 matches for "Biology"' in out

    def test_format_search_text_offset_exceeds_uses_display_query(self) -> None:
        from openzim_mcp.zim.search import _SearchMixin

        # offset >= total + empty results triggers the
        # "offset exceeds total" echo (line ~731).
        payload = {
            "query": "biology",
            "total": 5,
            "page_info": {"offset": 100, "limit": 5},
            "results": [],
            "done": True,
        }

        class _Stub:
            pass

        fn = _SearchMixin._format_search_text
        out = fn(_Stub(), payload, display_query="Biology")  # type: ignore[arg-type]
        assert 'Found 5 matches for "Biology"' in out

    def test_format_filtered_response_uses_display_query(self) -> None:
        # _format_filtered_response is a module-level free function;
        # call it directly with a minimal _FilteredScanState.
        from openzim_mcp.zim.search import _FilteredScanState, _format_filtered_response

        scan = _FilteredScanState(
            filtered_count=10,
            scanned=10,
            scan_cap_hit=False,
            total_filtered_is_lower_bound=False,
        )
        out = _format_filtered_response(
            query="biology",
            filter_text=" (namespace=C)",
            results=[
                {
                    "title": "Biology",
                    "path": "Biology",
                    "snippet": "...",
                    "namespace": "C",
                }
            ],
            scan=scan,
            total_results=10,
            offset=0,
            limit=5,
            display_query="Biology",
        )
        assert 'Found 10 filtered matches for "Biology"' in out
        # Original lowercase form should NOT appear in the echo header.
        assert 'matches for "biology"' not in out

    def test_format_filtered_response_falls_back_no_display(self) -> None:
        from openzim_mcp.zim.search import _FilteredScanState, _format_filtered_response

        scan = _FilteredScanState(
            filtered_count=10,
            scanned=10,
            scan_cap_hit=False,
            total_filtered_is_lower_bound=False,
        )
        out = _format_filtered_response(
            query="biology",
            filter_text="",
            results=[
                {
                    "title": "Biology",
                    "path": "Biology",
                    "snippet": "...",
                    "namespace": "C",
                }
            ],
            scan=scan,
            total_results=10,
            offset=0,
            limit=5,
        )
        assert 'Found 10 filtered matches for "biology"' in out


class TestPass2SiblingDefects:
    """Pass-2 source-level audit caught two additional lowercase-leak
    siblings to P1-D2 (chain rejection / soft-connector footer). Both
    echo a Rule-1-lowercased topic/query in a user-facing string. Live
    confirmation: P2-D1 reproduced in the original pass-1 smoke gate
    (``the Beatles`` → ``**Multiple articles match "beatles"**``); P2-D2
    affects every empty-result search whose original-case form differs
    from the lowercased extraction (``search for Biology xyz`` → ``No
    results for "biology xyz"``).

    Out of scope (separate change required): zim/search.py's ``Found N
    matches for "X"`` / ``No search results found for "X"`` /
    ``No filtered matches for "X"`` echoes (5 sites) — fixing them
    requires plumbing a separate ``display_query`` kwarg through the
    search backend's format functions. Higher cost, lower per-call
    impact than the dispatcher-edge cases fixed here."""

    def test_p2_d1_disambiguation_heading_recased(self) -> None:
        # Pre-fix: ``**Multiple articles match "stalin"**``.
        # Post-fix: ``**Multiple articles match "Stalin"**``.
        from openzim_mcp.simple_tools import SimpleToolsHandler

        out = SimpleToolsHandler._render_disambiguation(
            topic="stalin",
            candidates=[
                {"title": "Joseph Stalin", "path": "Joseph_Stalin", "score": 1.0},
                {
                    "title": "Stalin: Paradoxes of Power",
                    "path": "Stalin:_Paradoxes",
                    "score": 0.95,
                },
            ],
            original_query="tell me about Stalin",
        )
        assert '**Multiple articles match "Stalin"**' in out
        assert '**Multiple articles match "stalin"**' not in out

    def test_p2_d1_disambiguation_preserves_diacritics(self) -> None:
        from openzim_mcp.simple_tools import SimpleToolsHandler

        out = SimpleToolsHandler._render_disambiguation(
            topic="münchen",
            candidates=[
                {"title": "Munich", "path": "Munich", "score": 1.0},
                {"title": "FC München", "path": "FC_Munich", "score": 0.96},
            ],
            original_query="tell me about München",
        )
        assert '**Multiple articles match "München"**' in out

    def test_p2_d1_disambiguation_falls_back_when_no_original(self) -> None:
        # No original_query passed → legacy lowercase echo.
        from openzim_mcp.simple_tools import SimpleToolsHandler

        out = SimpleToolsHandler._render_disambiguation(
            topic="stalin",
            candidates=[
                {"title": "Joseph Stalin", "path": "Joseph_Stalin", "score": 1.0},
                {"title": "Stalin (film)", "path": "Stalin_(film)", "score": 0.96},
            ],
        )
        assert '**Multiple articles match "stalin"**' in out

    def test_p2_d1_disambiguation_falls_back_when_token_missing(self) -> None:
        # ``original_query`` doesn't contain the topic (e.g., Rule 4
        # reordered words) → helper returns the lowercase topic
        # unchanged. Documented graceful-degrade case.
        from openzim_mcp.simple_tools import SimpleToolsHandler

        out = SimpleToolsHandler._render_disambiguation(
            topic="population",  # decomposed entity, not in original
            candidates=[
                {"title": "Population", "path": "Population", "score": 1.0},
                {"title": "Population (statistics)", "path": "P_stats", "score": 0.96},
            ],
            original_query="tell me about Berlin's growth",
        )
        # No "population" substring in the original → falls back to lowercase.
        assert '**Multiple articles match "population"**' in out

    def test_p2_d2_no_results_heading_via_recase_helper(self) -> None:
        # Direct test of the _recase_from_original helper applied to
        # a search_query. The full integration via _handle_search
        # requires constructing the whole handler — the helper test
        # exercises the same logic the handler uses.
        from openzim_mcp.simple_tools import SimpleToolsHandler

        original = 'search for "Biology Phylogenetics"'
        recased = SimpleToolsHandler._recase_from_original(
            "biology phylogenetics", original
        )
        assert recased == "Biology Phylogenetics"


class TestRegressionGuards:
    """Pin the existing-contract behaviours that the post-b1 fixes
    must not regress. Each guard targets a code path the fixes
    touched but whose pre-fix behaviour is still correct."""

    def test_rule_3_section_command_guard_still_fires(self) -> None:
        # ``the X section of Y`` is a get_section command; Rule 3 must
        # NOT strip ``the`` because it's load-bearing for the
        # intent regex. Even with probe=None (degraded mode), the
        # section-command guard short-circuits before strip.
        out = IntentParser._detect_stopword_phrase(
            "the history section of biology", title_probe=None
        )
        assert out == "the history section of biology"

    def test_rule_4_skip_attr_still_short_circuits(self) -> None:
        # ``summary of berlin`` — ``summary`` is a structural-intent
        # keyword. Even with a probe (post-fix), the skip-set check
        # runs FIRST so structural commands never decompose.
        probe = _probe_factory("berlin")
        rewritten, hint = IntentParser._decompose_x_of_y(
            "summary of berlin", title_probe=probe
        )
        assert rewritten == "summary of berlin"
        assert hint is None

    def test_rule_2_correction_without_probe_still_works(self) -> None:
        # The probe-degraded path (multi-archive without explicit
        # path) still corrects plain misspellings — degraded only
        # means false-positive suppression isn't available, not that
        # correction is off entirely.
        out = IntentParser._apply_misspelling_map(
            "tell me about photosythesis", title_probe=None
        )
        assert out == "tell me about photosynthesis"

    def test_decompose_population_of_berlin_no_probe(self) -> None:
        # Without a probe, Rule 4 decomposes (legacy behaviour). This
        # is the path the integration tests in test_query_rewrite_tier1
        # already pin; the post-b1 fix must not regress it.
        rewritten, hint = IntentParser._decompose_x_of_y("population of berlin")
        assert rewritten == "berlin population"
        assert hint == {"entity": "berlin", "attribute": "population"}

    def test_existing_misspelling_lookup_still_idempotent(self) -> None:
        # A corrected word ("biology") is never itself a key in the
        # map. Running Rule 2 a second time is a no-op.
        once = IntentParser._apply_misspelling_map("bilogy", title_probe=None)
        twice = IntentParser._apply_misspelling_map(once, title_probe=None)
        assert once == "biology"
        assert twice == "biology"

    def test_multi_entity_chain_helper_unchanged_signature(self) -> None:
        # The helper still takes (intent, params, zim_file_path). New
        # behaviour reads params["_pre_rewrite_query"] but doesn't
        # require it (legacy callers see legacy output).
        import inspect

        from openzim_mcp.simple_tools import SimpleToolsHandler

        sig = inspect.signature(SimpleToolsHandler._multi_entity_chain_guidance)
        assert list(sig.parameters) == [
            "self",
            "intent",
            "params",
            "zim_file_path",
        ]
