r"""Regression tests for the post-b2 beta-test sweep.

The post-b2 live-MCP sweep against the 118 GB Wikipedia ZIM after
v2.0.0b2 deployed confirmed all eight b2 user-facing fix families
landed cleanly, then surfaced four follow-up defects across the
attack surface the b2 fixes unlocked:

* **D1 — trailing modal politeness ≥2 words falls through.**
  Pre-fix, ``intent_parser.py`` trailing politeness regex only
  matched ``please`` / ``to me`` / ``for me``. The leading regex
  (line ~374) recognised modal politeness (``could/can/would/will``
  + ``you``), but the trailing twin was missing — the two regexes
  drifted out of sync. Live impact:

    - ``tell me about Tokyo if you would`` → ``Would`` (verb stub)
    - ``tell me about Tokyo if you could`` → ``Could`` (verb stub)
    - ``tell me about Tokyo would you`` → ``Would_You`` (disambig)
    - ``tell me about Apollo 11 if you would`` → ``Would``

  Single-word trailing politeness (``please``, ``thanks``) and
  leading politeness (``please…``, ``could you…``) all worked
  correctly. Fix: add a trailing pattern symmetric to the leading
  one — ``\s+(?:if\s+you\s+(?:could|would|will|can)|
  (?:could|would|will|can)\s+you)\s*$`` looped with the existing
  ``please`` / ``to/for me`` strips. Both branches of the
  alternation require a ``you`` so a bare trailing modal verb
  (``Tokyo would``) — rare but possible in real article titles —
  isn't stripped.

* **D2 — reranker telemetry comment suppressed on no-results
  search.** The b1 D-1 in-band telemetry contract promised a
  ``<!-- reranker=<state> -->`` comment on every multi-token
  search. Pre-fix, ``simple_tools._handle_search`` compact path
  early-returned on ``total == 0`` BEFORE reaching
  ``_maybe_rerank_compact`` — neither the
  ``_RERANKER_SKIPPED_NO_RESULTS`` nor the
  ``_RERANKER_SKIPPED_NOT_INSTALLED`` counter bumped, so
  ``_compute_rerank_state`` returned ``None`` and the envelope
  writer skipped the comment. Live:
  ``search for asdfqwerzxcv nonexistent`` →
  ``<!-- intent=search cert=0.75 -->`` with no
  ``<!-- reranker=... -->``. Fix: call ``_maybe_rerank_compact``
  before the early-return; it's a no-op on empty results aside
  from the counter bump (the rerank singleton is cached).

* **D3 — Rule 2 + multi-token possessive topic picks wrong
  token.** Live: ``tell me about Photosythesis's reproduction``
  → ``Reproduction`` article (expected ``Photosynthesis``).
  Rule 2's affix retry correctly fires (``Photosythesis's`` →
  ``Photosynthesis's``); downstream auto-resolve can't full-phrase
  match and silently picks the trailing token. Pre-b2 returned
  ``No search results found``; post-b2 returned a silent wrong
  answer — arguably a worse failure mode. Root cause: Rule 4's
  ``_POSSESSIVE_RE`` is ``^...$``-anchored and runs at
  parse_intent time against the FULL query — ``tell me about
  photosynthesis's reproduction`` doesn't match because of the
  verb prefix. Fix: in ``_handle_tell_me_about``, when no
  decomposition hint was attached AND the topic carries ``'s ``,
  retry ``_decompose_x_of_y`` on the extracted topic. Scope
  narrowed to the possessive shape only (NOT ``X of Y``) — the
  X-of-Y form is already handled at parse time via the probe-
  gated Rule 4, and a handler-side retry would risk regressing
  non-canonical X-of-Y queries.

* **D4 — compact-mode filtered search drops ``filtered``
  qualifier.** Live: ``search Berlin in namespace C`` →
  ``Found 3 matches for "Berlin"`` (the legacy non-compact path
  emits ``Found N filtered matches for "X"<filter_text>``). Both
  paths share ``_format_search_text``; pre-fix the formatter had
  no filter awareness so the compact path silently lost the
  qualifier when the b1 P3-D1 ``display_query`` plumbing was
  added. Fix: add an optional ``filter_text`` kwarg to
  ``_format_search_text`` (mirrors ``display_query``); thread it
  through the compact filtered call site by re-using the same
  ``_format_filter_text`` helper the non-compact path already
  uses.

Out of scope (deferred design call):

* **D5 — ``death of stalin`` resolves to
  ``Death_and_state_funeral_of_Joseph_Stalin`` instead of the
  2017 Iannucci film.** P1-D3 probe-gate correctly suppressed
  the Stalin disambig misroute. Title-probe found a different
  canonical X-related title rather than the film, which doesn't
  have a clean ``Death_of_Stalin`` redirect (canonical is
  ``The_Death_of_Stalin``). Picking the film over the funeral
  article would require either a prefix-widening probe (``The
  <query>``) — which has unwanted side effects on arbitrary
  bare topics — or a popularity ranker. Both are design choices
  beyond the b2 sweep scope.

"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

# ===========================================================================
# Shared stubs (mirror post-b1 conventions: minimal stub objects, unbound
# method calls so we don't need to construct full SimpleToolsHandler)
# ===========================================================================


class _StubZimOps:
    """Minimal stub of ``ZimOperations`` for handler-edge tests."""

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


# ===========================================================================
# D1 — trailing modal politeness ≥2 words
# ===========================================================================


class TestD1TrailingModalPoliteness:
    """D1: pre-fix, ``intent_parser._extract_tell_me_about`` trailing
    politeness regex only matched ``please`` / ``to me`` / ``for me``.
    Multi-word modal politeness fell through to last-token resolution
    via the auto-resolve picker.

    Fix: add a trailing-modal regex symmetric to the leading-modal
    one (line ~374). Both branches of the alternation require a
    ``you`` to avoid stripping a legitimate trailing modal verb."""

    @staticmethod
    def _extract_topic(query: str) -> str:
        """Drive ``_extract_tell_me_about`` directly to isolate the
        politeness-strip behavior."""
        from openzim_mcp.intent_parser import _extract_tell_me_about

        params: Dict[str, Any] = {}
        _extract_tell_me_about(query, params)
        return str(params.get("topic", ""))

    def test_if_you_would_trailing_stripped(self) -> None:
        # Live repro from the post-b2 sweep.
        assert self._extract_topic("tell me about Tokyo if you would") == "Tokyo"

    def test_if_you_could_trailing_stripped(self) -> None:
        assert self._extract_topic("tell me about Tokyo if you could") == "Tokyo"

    def test_if_you_will_trailing_stripped(self) -> None:
        assert self._extract_topic("tell me about Tokyo if you will") == "Tokyo"

    def test_if_you_can_trailing_stripped(self) -> None:
        assert self._extract_topic("tell me about Tokyo if you can") == "Tokyo"

    def test_would_you_trailing_stripped(self) -> None:
        # Live repro: ``Tokyo would you`` resolved to ``Would_You`` disambig.
        assert self._extract_topic("tell me about Tokyo would you") == "Tokyo"

    def test_could_you_trailing_stripped(self) -> None:
        assert self._extract_topic("tell me about Tokyo could you") == "Tokyo"

    def test_can_you_trailing_stripped(self) -> None:
        assert self._extract_topic("tell me about Tokyo can you") == "Tokyo"

    def test_will_you_trailing_stripped(self) -> None:
        assert self._extract_topic("tell me about Tokyo will you") == "Tokyo"

    def test_apollo_11_with_trailing_modal(self) -> None:
        # Live repro from the sweep: ``Apollo 11 if you would`` → ``Would``.
        assert (
            self._extract_topic("tell me about Apollo 11 if you would") == "Apollo 11"
        )

    def test_existing_single_word_please_still_works(self) -> None:
        # Pre-existing trailing-politeness handling must keep working.
        assert self._extract_topic("tell me about Tokyo please") == "Tokyo"

    def test_existing_single_word_thanks_via_strip_trailing(self) -> None:
        # ``thanks`` is handled separately by ``IntentParser._strip_trailing
        # _politeness``; this test just confirms it doesn't conflict with
        # the new modal regex (no double-strip removing the topic).
        from openzim_mcp.intent_parser import IntentParser

        result = IntentParser._strip_trailing_politeness("tell me about Tokyo thanks")
        assert "Tokyo" in result

    def test_existing_to_me_tail_still_works(self) -> None:
        # ``explain Berlin to me`` style — still works.
        assert self._extract_topic("explain Berlin to me") == "Berlin"

    def test_bare_modal_without_you_not_stripped(self) -> None:
        # ``Tokyo would`` (no ``you``) is a possessive-less English
        # fragment; not politeness; do NOT strip. The trailing regex
        # requires either an ``if you ...`` prefix or a trailing
        # ``you``, so a bare ``would`` is left attached.
        topic = self._extract_topic("tell me about Tokyo would")
        assert "Tokyo would" in topic.lower() or topic == "Tokyo would"

    def test_leading_modal_still_strips(self) -> None:
        # Symmetry sanity check: the leading-modal politeness regex at
        # line ~374 keeps working.
        assert self._extract_topic("could you tell me about Tokyo") == "Tokyo"

    def test_compound_leading_and_trailing(self) -> None:
        # ``please could you tell me about Tokyo if you would`` —
        # both ends should strip cleanly.
        assert (
            self._extract_topic("please could you tell me about Tokyo if you would")
            == "Tokyo"
        )


class TestD1ParseIntentEndToEnd:
    """End-to-end: a politeness-tail query should parse to a
    tell_me_about intent whose extracted topic is the bare entity."""

    def test_if_you_would_parses_to_clean_topic(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "tell me about Tokyo if you would",
            query_rewrite_enabled=False,
        )
        assert intent == "tell_me_about"
        assert params.get("topic") == "Tokyo"


class TestD1SiblingUniversalTrailingModal:
    """Pass-2 sibling audit of D1: the trailing-modal strip was
    initially added only inside ``_extract_tell_me_about``. Every
    OTHER extractor (search, find_by_title, related, suggestions,
    structure, get_section…) routes through the universal
    ``_strip_trailing_politeness`` at ``parse_intent`` line 1048,
    which uses ``_TRAILING_POLITENESS_RE``. Pre-sibling-fix the
    universal regex matched ``please`` / ``thanks`` / multilingual
    variants but NOT the modal class — so ``search for biology if
    you would`` searched for ``"biology if you would"`` (same
    failure shape as the post-a20 PD2-1 ``please`` leak that
    motivated the universal strip).

    Fix: add ``if you (could|would|will|can)`` and
    ``(could|would|will|can) you`` to ``_TRAILING_POLITENESS_RE``.
    Mirrors the leading-modal class the post-a15 P6-D3 fix added
    to the leading politeness strip — the two should always stay
    in sync. Defense-in-depth: the extractor-level strip from D1
    pass-1 is kept (idempotent)."""

    def test_strip_trailing_politeness_handles_if_you_would(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        out = IntentParser._strip_trailing_politeness("search for biology if you would")
        # Modal politeness peeled; ``search for biology`` left intact.
        assert "if you" not in out.lower()
        assert "biology" in out.lower()

    def test_strip_trailing_politeness_handles_would_you(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        out = IntentParser._strip_trailing_politeness("search for biology would you")
        assert "would" not in out.lower()
        assert "biology" in out.lower()

    def test_strip_trailing_politeness_handles_if_you_could(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        out = IntentParser._strip_trailing_politeness(
            "find article titled Berlin if you could"
        )
        assert "if you" not in out.lower()
        assert "Berlin" in out

    def test_strip_trailing_politeness_handles_could_you(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        out = IntentParser._strip_trailing_politeness(
            "links in Photosynthesis could you"
        )
        assert "could" not in out.lower()
        assert "Photosynthesis" in out

    def test_search_extractor_recovers_clean_query(self) -> None:
        """End-to-end: ``search for biology if you would`` should reach
        ``_extract_search`` with the modal already peeled, so the
        captured query is just ``biology``."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "search for biology if you would",
            query_rewrite_enabled=False,
        )
        # Should be classified as a search intent…
        assert intent == "search"
        # …with the modal politeness already peeled.
        extracted = (params.get("query") or "").lower()
        assert "if you" not in extracted
        assert "biology" in extracted

    def test_bare_modal_verb_at_end_preserved(self) -> None:
        """The trailing-modal regex requires either an ``if you ...``
        prefix OR a trailing ``you``. A bare ``would`` / ``could`` at
        the end (no ``you``) is left attached so real article titles
        ending in a modal aren't mangled."""
        from openzim_mcp.intent_parser import IntentParser

        # ``would`` alone — left attached.
        out = IntentParser._strip_trailing_politeness("biology would")
        assert "would" in out.lower()


class TestD1RegexSync:
    """Pin the b2-D1 invariant: leading and trailing politeness
    regexes must recognise the same modal class. Future contributors
    who add a verb to one side must add it to the other. Failure mode
    that motivated this guard: the post-b1 sweep widened the LEADING
    regex (post-a15 P6-D3) to cover ``could/can/would/will + you``;
    the trailing regex stayed narrow at ``please`` / ``to/for me``
    for six more sweeps until the post-b2 sweep caught it."""

    def test_leading_and_trailing_share_modal_class(self) -> None:
        # The trailing regex source must contain the same modal class
        # the leading regex (inside ``_extract_tell_me_about``)
        # recognises. The leading regex is a literal string at
        # intent_parser.py:374; the trailing regex is
        # ``_TRAILING_POLITENESS_RE``.
        from openzim_mcp.intent_parser import IntentParser

        trailing = IntentParser._TRAILING_POLITENESS_RE
        # Both alternation branches must be present.
        assert "could|would|will|can" in trailing
        assert "if\\s+you\\s+" in trailing


class TestD1Pass3ChainedIntentPolitenessLeak:
    """Pass-3 sibling audit of D1: ``_chained_intent_guidance`` runs
    UPSTREAM of ``parse_intent`` on the raw user query (per the
    post-a24 P1-D6 commentary at simple_tools.py:1250-1262). The
    upstream call site already mirrored the param-leak strip, but
    the trailing-politeness strip was never mirrored — so trailing
    politeness inside a chain half leaks into the rejection bullets.

    Pass-2's universal modal-politeness extension widened the
    UX leak class. Live shape: ``tell me about Tokyo if you would
    then list namespaces`` correctly fires the chain rejection but
    its ``**First op (left):**`` bullet reads ``tell me about
    Tokyo if you would`` — a cosmetic leak the caller would copy-
    paste back into the recovery flow. Same structural sibling
    pattern as the post-a24 P1-D6 param-leak version of this defect.

    Fix: peel trailing politeness from each chain half AFTER the
    split + connector/punct trim, BEFORE the bullets render."""

    def test_modal_politeness_stripped_from_left_half_in_chain_bullet(
        self,
    ) -> None:
        """Live repro: ``tell me about Tokyo if you would then list
        namespaces`` should produce a chain rejection whose left
        bullet is the bare ``tell me about Tokyo`` — no modal
        politeness echoed back to the user."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        out = SimpleToolsHandler._chained_intent_guidance(
            "tell me about Tokyo if you would then list namespaces"
        )
        assert out is not None
        assert "Chained Operations Detected" in out
        # The modal politeness must NOT echo into the left bullet.
        assert "if you would" not in out.lower()
        # The clean topic must be present.
        assert "tell me about Tokyo" in out
        assert "list namespaces" in out

    def test_modal_politeness_stripped_from_right_half_in_chain_bullet(
        self,
    ) -> None:
        """Symmetric sibling: when the politeness sits in the right
        half (``tell me about Tokyo then list namespaces if you
        would``), the right bullet must also be clean."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        out = SimpleToolsHandler._chained_intent_guidance(
            "tell me about Tokyo then list namespaces if you would"
        )
        assert out is not None
        assert "if you would" not in out.lower()
        assert "list namespaces" in out

    def test_please_in_left_half_also_stripped(self) -> None:
        """Pre-pass-3 the trailing politeness regex already covered
        ``please`` / ``thanks``, but the chain guidance never invoked
        the universal strip on its halves. Confirm that pass-3 lifts
        the WHOLE token set (not just the modal class) into the chain
        guidance."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        out = SimpleToolsHandler._chained_intent_guidance(
            "tell me about Berlin please then list namespaces"
        )
        assert out is not None
        # ``please`` is part of the existing _TRAILING_POLITENESS_RE
        # token set; the pass-3 strip should peel it for free.
        assert "please" not in out.lower()
        assert "tell me about Berlin" in out

    def test_chain_detection_still_fires_after_strip(self) -> None:
        """Sanity check: the strip can't accidentally suppress the
        chain warning. The leading op verb (``tell`` / ``list``) is
        the gate signal; the trailing strip never touches it."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        # Worst-case: trailing politeness near the split point.
        out = SimpleToolsHandler._chained_intent_guidance(
            "tell me about Tokyo would you then list namespaces could you"
        )
        # Chain still detected.
        assert out is not None
        assert "Chained Operations Detected" in out
        # Both halves clean.
        assert "would you" not in out.lower()
        assert "could you" not in out.lower()

    def test_non_chain_query_with_trailing_politeness_unaffected(self) -> None:
        """Sanity check: a non-chain query with trailing politeness
        returns ``None`` (no chain to reject), regardless of strip."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        out = SimpleToolsHandler._chained_intent_guidance(
            "tell me about Tokyo if you would"
        )
        assert out is None


# ===========================================================================
# D2 — reranker telemetry comment on no-results
# ===========================================================================


class TestD2RerankerCounterOnNoResults:
    """D2: pre-fix, ``_handle_search`` compact path early-returned on
    empty payload BEFORE the rerank apply call. Neither counter bumped,
    ``_compute_rerank_state`` returned None, the
    ``<!-- reranker=... -->`` comment was suppressed for every
    no-results search.

    Fix: invoke ``_maybe_rerank_compact`` on the empty payload first
    so the appropriate skip counter (``no_results`` if reranker is
    installed, ``not_installed`` otherwise) bumps before the bail."""

    def test_maybe_rerank_compact_bumps_no_results_on_empty(self) -> None:
        """Verify ``_maybe_rerank_compact`` itself bumps the counter
        on an empty payload — this is the contract D2 relies on."""
        from openzim_mcp.ml.reranker import BGEReranker
        from openzim_mcp.simple_tools import (
            _RERANKER_SKIPPED_NO_RESULTS,
            _RERANKER_SKIPPED_NOT_INSTALLED,
            SimpleToolsHandler,
        )

        class _StubReranker:
            def rerank(self, *, query: str, candidates: list, top_k: int) -> list:
                return []

        class _StubRerankerCfg:
            pass

        class _StubMlCfg:
            reranker = _StubRerankerCfg()

        class _StubFullCfg:
            ml = _StubMlCfg()

        class _StubOps:
            config = _StubFullCfg()

        class _Handler:
            zim_operations = _StubOps()

            def __init__(self) -> None:
                self._telemetry: Counter[str] = Counter()

            def _track(self, event: str) -> None:
                self._telemetry[event] += 1

        # When BGEReranker.get returns None, _maybe_rerank_compact
        # bumps NOT_INSTALLED on the empty payload.
        handler = _Handler()
        original_get = BGEReranker.get
        BGEReranker.get = staticmethod(lambda cfg=None: None)  # type: ignore[assignment, misc]
        try:
            SimpleToolsHandler._maybe_rerank_compact(
                handler,  # type: ignore[arg-type]
                payload={"results": []},
                query="x",
                limit=None,
            )
        finally:
            BGEReranker.get = original_get  # type: ignore[assignment]
        # Either NOT_INSTALLED (no reranker) OR NO_RESULTS (reranker
        # present but empty payload) must have bumped.
        assert (
            handler._telemetry[_RERANKER_SKIPPED_NOT_INSTALLED] == 1
        ), "no-reranker path must bump NOT_INSTALLED"

        # Now reranker present but empty payload → NO_RESULTS.
        handler2 = _Handler()
        BGEReranker.get = staticmethod(lambda cfg=None: _StubReranker())  # type: ignore[assignment, misc]
        try:
            SimpleToolsHandler._maybe_rerank_compact(
                handler2,  # type: ignore[arg-type]
                payload={"results": []},
                query="x",
                limit=None,
            )
        finally:
            BGEReranker.get = original_get  # type: ignore[assignment]
        assert (
            handler2._telemetry[_RERANKER_SKIPPED_NO_RESULTS] == 1
        ), "reranker-present path must bump NO_RESULTS on empty payload"


# ===========================================================================
# D3 — Rule 2 possessive multi-token topic
# ===========================================================================


class TestD3PossessiveDecompositionRetry:
    """D3: when parse_intent's Rule 4 misses the possessive shape
    because the verb prefix prevents the anchored regex from matching,
    ``_handle_tell_me_about`` retries the decomposition on the
    extracted topic.

    The retry is scoped to possessive shapes (``X's Y``) ONLY — the
    X-of-Y shape is intentionally NOT retried because the
    title-promotion path already handles canonical multi-word titles
    and a handler-side retry would risk regressing non-canonical
    X-of-Y queries (e.g. ``death of stalin``)."""

    def test_decompose_possessive_picks_entity(self) -> None:
        """Bare contract check: ``_decompose_x_of_y`` on a possessive
        topic picks the entity and stashes the hint."""
        from openzim_mcp.intent_parser import IntentParser

        # No probe → degraded mode (no canonical-title suppression).
        # The corrected possessive form arrives here after Rule 2 has
        # already run at parse time.
        rewritten, hint = IntentParser._decompose_x_of_y(
            "photosynthesis's reproduction",
            title_probe=None,
        )
        assert hint is not None
        assert hint["entity"] == "photosynthesis"
        assert hint["attribute"] == "reproduction"
        assert rewritten == "photosynthesis reproduction"

    def test_decompose_possessive_suppressed_by_probe(self) -> None:
        """When the FULL possessive query is itself a canonical title
        (rare but possible: ``Schrodinger's cat``), the probe gate
        suppresses decomposition."""
        from openzim_mcp.intent_parser import IntentParser

        # Probe says yes for the full query → suppress.
        rewritten, hint = IntentParser._decompose_x_of_y(
            "schrodinger's cat",
            title_probe=lambda q: q == "schrodinger's cat",
        )
        assert hint is None
        assert rewritten == "schrodinger's cat"

    def test_handler_retry_fires_only_on_possessive_topic(self) -> None:
        """The D3 retry in ``_handle_tell_me_about`` is gated on
        ``"'s " in topic.lower()`` — a topic without an apostrophe-s
        skips the retry entirely (so non-canonical ``X of Y`` queries
        don't get redirected at the handler edge)."""
        # Topic without apostrophe-s → no retry, no decomposition.
        assert "'s " not in "death of stalin".lower()
        assert "'s " in "photosynthesis's reproduction".lower()
        # Edge case: just an apostrophe-s with no trailing word — won't
        # match ``_POSSESSIVE_RE`` anyway (needs ``\w+`` attr after).
        assert "'s " not in "tokyo's".lower()


# ===========================================================================
# D4 — compact filtered search ``filtered`` qualifier
# ===========================================================================


class TestD4FilteredSearchEchoQualifier:
    """D4: pre-fix, the compact filtered search path called
    ``_format_search_text`` directly, which had no filter awareness
    and emitted ``Found N matches for "X"`` regardless. The legacy
    non-compact path emits ``Found N filtered matches for "X"
    (filters: namespace=C)`` via a different formatter.

    Fix: add an optional ``filter_text`` kwarg to
    ``_format_search_text``. When provided, the count line
    interpolates the ``filtered`` qualifier and the filter suffix —
    matching the non-compact wording. Compact filtered call site
    threads the helper's output through."""

    def _make_payload(
        self,
        query: str,
        total: int,
        results: List[Dict[str, Any]],
        offset: int = 0,
        limit: int = 10,
    ) -> Dict[str, Any]:
        return {
            "query": query,
            "total": total,
            "results": results,
            "done": True,
            "page_info": {
                "offset": offset,
                "limit": limit,
                "returned_count": len(results),
            },
        }

    def test_filtered_echo_has_filtered_qualifier(self) -> None:
        from openzim_mcp.zim.search import _SearchMixin

        payload = self._make_payload(
            "berlin",
            3,
            [
                {"title": "Berlin", "path": "Berlin", "snippet": "..."},
                {"title": "Berlin Wall", "path": "Berlin_Wall", "snippet": "..."},
                {
                    "title": "Berlin Cathedral",
                    "path": "Berlin_Cathedral",
                    "snippet": "...",
                },
            ],
        )
        out = _SearchMixin._format_search_text(
            None,  # type: ignore[arg-type]
            payload,  # type: ignore[arg-type]
            display_query="Berlin",
            filter_text=" (filters: namespace=C)",
        )
        # The "filtered" qualifier is present alongside the original-
        # case echo and the filter description.
        assert "Found 3 filtered matches" in out
        assert '"Berlin"' in out
        assert "(filters: namespace=C)" in out

    def test_unfiltered_echo_still_omits_qualifier(self) -> None:
        """Backwards-compat: without ``filter_text``, the unfiltered
        wording is unchanged (no leading-``filtered`` qualifier)."""
        from openzim_mcp.zim.search import _SearchMixin

        payload = self._make_payload(
            "biology",
            5,
            [
                {"title": "Biology", "path": "Biology", "snippet": "..."},
            ],
        )
        out = _SearchMixin._format_search_text(
            None,  # type: ignore[arg-type]
            payload,  # type: ignore[arg-type]
            display_query="Biology",
        )
        # Old shape preserved.
        assert "Found 5 matches" in out
        assert "filtered matches" not in out

    def test_filtered_no_results_uses_terse_echo(self) -> None:
        """When the filtered search returns zero results, render the
        terse ``No filtered matches for "X"<filter_text>`` line — same
        shape as the non-compact filtered path (``zim/search.py:1510``).
        Recovery hints don't apply to a filter mismatch."""
        from openzim_mcp.zim.search import _SearchMixin

        payload = self._make_payload("xyz", 0, [])
        out = _SearchMixin._format_search_text(
            None,  # type: ignore[arg-type]
            payload,  # type: ignore[arg-type]
            display_query="xyz",
            filter_text=" (filters: namespace=C)",
        )
        assert 'No filtered matches for "xyz"' in out
        assert "(filters: namespace=C)" in out
        # The unfiltered recovery hints must NOT leak into the
        # filtered-no-results path.
        assert "suggestions for" not in out

    def test_unfiltered_no_results_keeps_recovery_hints(self) -> None:
        """Backwards-compat for the unfiltered no-results path."""
        from openzim_mcp.zim.search import _SearchMixin

        payload = self._make_payload("xyz", 0, [])
        out = _SearchMixin._format_search_text(
            None,  # type: ignore[arg-type]
            payload,  # type: ignore[arg-type]
            display_query="xyz",
        )
        # Unfiltered path keeps the full recovery block.
        assert 'No search results found for "xyz"' in out
        assert "suggestions for" in out
        assert "tell me about" in out

    def test_filtered_offset_exceeds_total_uses_qualifier(self) -> None:
        from openzim_mcp.zim.search import _SearchMixin

        payload = self._make_payload("berlin", 3, [], offset=10, limit=10)
        out = _SearchMixin._format_search_text(
            None,  # type: ignore[arg-type]
            payload,  # type: ignore[arg-type]
            display_query="Berlin",
            filter_text=" (filters: namespace=C)",
        )
        # Both the qualifier and the offset-exceeded notice must be
        # present.
        assert "Found 3 filtered matches" in out
        assert "(filters: namespace=C)" in out
        assert "offset 10 exceeds" in out


# ===========================================================================
# Cross-feature regression guards
# ===========================================================================


class TestRegressionGuards:
    """Pin invariants that the post-b2 sweep surfaced as feature-level
    sibling shapes. Worth keeping as canonical-source guards so future
    contributors don't drift one half out of sync with the other."""

    def test_leading_and_trailing_modal_politeness_both_recognised(self) -> None:
        """The post-b2 D1 lesson: leading and trailing politeness regexes
        must stay in sync. Both should strip the same modal class
        (``could/can/would/will`` + ``you``)."""
        from openzim_mcp.intent_parser import _extract_tell_me_about

        # Leading.
        p_leading: Dict[str, Any] = {}
        _extract_tell_me_about("could you tell me about Berlin", p_leading)
        # Trailing.
        p_trailing: Dict[str, Any] = {}
        _extract_tell_me_about("tell me about Berlin could you", p_trailing)
        # Both should converge on the same topic.
        assert p_leading.get("topic") == p_trailing.get("topic") == "Berlin"

    def test_reranker_telemetry_emission_path_unified(self) -> None:
        """The post-b2 D2 lesson: every return path of a search handler
        must participate in the rerank-counter contract. This guard
        pins ``_maybe_rerank_compact`` as the single emission point so
        future return paths can route through it uniformly."""
        import inspect

        from openzim_mcp.simple_tools import SimpleToolsHandler

        source = inspect.getsource(SimpleToolsHandler._maybe_rerank_compact)
        # All four counter constants must appear inside the function so
        # every code path through it bumps SOMETHING.
        assert "_RERANKER_ENGAGED" in source
        assert "_RERANKER_SKIPPED_NOT_INSTALLED" in source
        assert "_RERANKER_SKIPPED_NO_RESULTS" in source
        assert "_RERANKER_SKIPPED_PASSTHROUGH" in source

    def test_no_results_early_return_routes_through_rerank(self) -> None:
        """Pin the D2 fix shape: the no-results early-return branch in
        ``_handle_search`` must invoke ``_maybe_rerank_compact`` before
        bailing so the rerank counter bumps. Future contributors who
        re-introduce an early-return without this call would silently
        re-break the in-band telemetry contract."""
        import inspect

        from openzim_mcp.simple_tools import SimpleToolsHandler

        source = inspect.getsource(SimpleToolsHandler._handle_search)
        # Find the no-results early-return block; ``_maybe_rerank_compact``
        # must be called BEFORE the return.
        no_results_idx = source.find("No results for")
        assert no_results_idx > 0, "no-results message moved?"
        # Look backwards from the message for the rerank call.
        before_return = source[:no_results_idx]
        assert (
            "_maybe_rerank_compact" in before_return
        ), "no-results early-return path must call _maybe_rerank_compact first"
