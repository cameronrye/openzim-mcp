"""Simple tools implementation for OpenZIM MCP server.

This module provides intelligent, natural language-based tools that abstract
away the complexity of multiple specialized tools. Designed for LLMs with
limited tool-calling capabilities or context windows.

The regex-heavy intent-parsing layer lives in :mod:`openzim_mcp.intent_parser`.
``IntentParser`` and ``safe_regex_sub`` are imported from there; refer to that
module directly for the timeout-guarded ``safe_regex_*`` helpers.
"""

import logging
import re
from collections import Counter
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union, cast

import openzim_mcp.zim_operations as _zim_ops_mod

from . import compact_renderers
from .article_body import _ArticleBodyMixin
from .chain_detection import _ChainMixin
from .compact_format import _CompactFormatMixin
from .cursor_decode import decode_offset_cursor
from .disambiguation import _DisambiguationMixin
from .exceptions import RegexTimeoutError
from .intent_parser import IntentParser, _strip_quote_pair, safe_regex_sub
from .meta import build_meta, format_footer
from .rerank import (
    _INFO_LEVEL_TELEMETRY_EVENTS,
    _RERANKER_ENGAGED,
    _RERANKER_SKIPPED_NO_RESULTS,
    _RERANKER_SKIPPED_NOT_INSTALLED,
    _RERANKER_SKIPPED_PASSTHROUGH,
    _RerankMixin,
)
from .responses import ToolErrorPayload, tool_error
from .security import sanitize_context_for_error
from .subject_section import _SubjectSectionMixin
from .title_promotion import (
    _DISCRIMINATOR_STOP_WORDS,
    _TAIL_TOKEN_RE,
    _TOKEN_RE,
    find_title_match,
    has_apostrophe_possessive,
    is_strong_title_match,
)
from .tool_schemas import (
    SearchAllResponse,
    SearchResponse,
    SynthesizeResponse,
)
from .zim_operations import ZimOperations

logger = logging.getLogger(__name__)


# Phase D sub-D-2 query-rewrite telemetry events.
_QUERY_REWRITE_MISSPELLING = "query_rewrite.misspelling"
_QUERY_REWRITE_STOPWORD_PHRASE = "query_rewrite.stopword_phrase"
_QUERY_REWRITE_X_OF_Y = "query_rewrite.x_of_y"


# Post-b6 Z1: the shared D1+Z1 filter lives in ``title_promotion`` as
# ``accept_possessive_promotion`` (imported above). simple_tools and
# synthesize both use it so the two-mode tell-me-about/synthesize
# paths apply identical safety logic. The legacy thin wrapper kept
# here would have duplicated the helper across modules — replaced
# with the direct import.


@dataclass
class _HandlerResult:
    """Structured return value from an intent handler.

    Most handlers return a plain ``str``; handlers that need to pass
    structured ``_meta`` fields (e.g. ``reason``, ``suggestions``) up to
    ``handle_zim_query``'s footer-building logic return this instead.

    ``handle_zim_query`` detects the type at runtime and unpacks the fields
    before the footer step — existing handlers that return strings are
    completely unaffected.
    """

    body: str
    reason: Optional[str] = None
    suggestions: Optional[List[Dict[str, str]]] = field(default=None)


class SimpleToolsHandler(
    _ArticleBodyMixin,
    _ChainMixin,
    _CompactFormatMixin,
    _DisambiguationMixin,
    _RerankMixin,
    _SubjectSectionMixin,
):
    """Handler for simple, intelligent MCP tools."""

    def __init__(self, zim_operations: ZimOperations):
        """Initialize simple tools handler.

        Args:
            zim_operations: ZimOperations instance for underlying operations
        """
        self.zim_operations = zim_operations
        self.intent_parser = IntentParser()
        # In-memory telemetry counters surface via ``get_server_health``.
        # Each branch in ``handle_zim_query`` that is interesting for
        # tuning the heuristics (meta-guidance, hallucinated paths, regex
        # timeouts, response truncation, non-Latin routing, …) bumps a
        # named counter here. No PII; the dict is small enough to ship in
        # a health-check response. Process-local — restarts reset.
        self._telemetry: Counter[str] = Counter()

    def _track(self, event: str) -> None:
        """Increment the named telemetry counter.

        Events in ``_INFO_LEVEL_TELEMETRY_EVENTS`` also emit a single
        INFO log line per call so simple-mode operators (who don't have
        ``get_server_health``) can observe them in the server log.
        """
        self._telemetry[event] += 1
        if event in _INFO_LEVEL_TELEMETRY_EVENTS:
            logger.info("telemetry: %s", event)

    def get_telemetry(self) -> Dict[str, int]:
        """Return a snapshot of the in-memory telemetry counters.

        Used by ``get_server_health`` to surface heuristic-branch
        frequencies for tuning. Returns a copy so callers can't mutate
        the internal counter.
        """
        return dict(self._telemetry)

    @staticmethod
    def _recase_from_original(token: str, original_query: str) -> str:
        """Post-b1 P1-D2: return ``token`` in the casing it appears
        with in ``original_query`` (case-insensitive substring search).

        Falls back to ``token`` unchanged when the lookup misses (e.g.,
        when the topic was reshaped by a rewrite step that doesn't
        preserve a clean substring — Rule 2 misspelling substitution,
        Rule 4 entity-attribute reorder). The original-case form is
        used in user-facing guidance text (chain rejection bullets,
        soft-connector footer) so the caller's recovery copy-paste
        path keeps the diacritics and casing they originally typed."""
        if not original_query or not token:
            return token
        idx = original_query.lower().find(token.lower())
        if idx < 0:
            return token
        return original_query[idx : idx + len(token)]

    def _probe_archive_path(self, zim_file_path: Optional[str]) -> Optional[str]:
        """Post-b1 P1-D1: resolve the archive the query-rewrite title
        probe should consult.

        ``handle_zim_query`` auto-selects the single loaded archive
        downstream (line ~776) when ``zim_file_path`` is omitted — the
        recommended calling pattern per the tool's own docstring. The
        probe was previously built BEFORE that resolution, so a
        ``None`` caller-supplied path produced a ``None`` probe and
        rules 2/3/4 ran in degraded mode for the overwhelming majority
        of real calls. Mirror the same auto-select policy so the probe
        sees the same archive the search will actually run against
        (single-archive case). In multi-archive mode without an
        explicit path, ``_auto_select_zim_file()`` returns ``None`` and
        the probe stays degraded — that's the only genuinely ambiguous
        case where falling back to "no probe" is the right answer."""
        if zim_file_path:
            return zim_file_path
        return self._auto_select_zim_file()

    def _build_title_probe(
        self, zim_file_path: Optional[str]
    ) -> Optional[Callable[[str], bool]]:
        """Sub-D-2: build a callable that probes the title index for a
        canonical (score >= 0.95) hit, returning True/False.

        Returns None when no archive path is in scope (rules 2 and 3
        will run in degraded mode). Returns a closure over the
        zim_operations + path otherwise."""
        if not zim_file_path:
            return None

        def probe(token: str) -> bool:
            try:
                # min_score=0.95 catches both exact (1.0) and fuzzy
                # (0.95+) title hits — broad enough to suppress rule 2
                # substitutions where the original is plausibly a real
                # entity name.
                match = find_title_match(
                    self.zim_operations,
                    zim_file_path,
                    token,
                    min_score=0.95,
                )
                return match is not None
            except Exception:
                # Probe failures degrade the gate, not the search.
                return False

        return probe

    def handle_zim_query(
        self,
        query: str,
        zim_file_path: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> Union[str, SynthesizeResponse, ToolErrorPayload]:
        """Handle a natural language query about ZIM file content.

        This is the main intelligent tool that routes queries to appropriate
        underlying operations based on intent parsing.

        Args:
            query: Natural language query
            zim_file_path: Optional path to ZIM file (auto-selects if not provided)
            options: Optional dict with advanced options (limit, offset, etc.)

        Returns:
            Markdown string (synthesize=False) or SynthesizeResponse
            (synthesize=True) or ToolErrorPayload on error.
        """
        options = options or {}
        # D10: decode the optional ``cursor`` and project its ``o``
        # (offset) into ``options["offset"]`` so downstream handlers —
        # all of which still take integer offsets — keep working
        # unchanged. The cursor's tool name is ignored at this layer:
        # the simple-mode router dispatches based on the parsed
        # intent, not on which tool emitted the cursor. Mismatches
        # surface as a no-op (the offset is still valid, just maybe
        # smaller than the new query's hit count). Malformed cursors
        # are surfaced as a structured error.
        cursor_raw = options.get("cursor")
        if cursor_raw is not None:
            # Simple-mode dispatch routes by parsed intent, not by the
            # tool that emitted the cursor — and ``Cursor.decode`` requires
            # an ``expected_tool`` match. ``decode_offset_cursor`` decodes
            # the payload directly (bypassing that check) so any tool's
            # cursor can be replayed for offset extraction. It returns a
            # ``CursorDecodeResult`` (offset + optional ns/ai/tool to
            # project into ``options``) or one of the structured
            # ``cursor_decode`` ``ToolErrorPayload`` errors. See
            # ``openzim_mcp.cursor_decode`` for the full rationale.
            cursor_result = decode_offset_cursor(
                str(cursor_raw),
                query=query,
                q_emitting_tools=self._Q_EMITTING_CURSOR_TOOLS,
            )
            if isinstance(cursor_result, dict):
                # ToolErrorPayload — surface it unchanged.
                return cursor_result
            options["offset"] = cursor_result.offset
            # Only project ns/ai/tool when truthy (same condition as the
            # former inline block); downstream handlers read these to
            # reject namespace / archive-identity / cross-tool mismatches.
            if cursor_result.ns:
                options["_cursor_ns"] = cursor_result.ns
            if cursor_result.ai:
                options["_cursor_ai"] = cursor_result.ai
            if cursor_result.tool:
                options["_cursor_t"] = cursor_result.tool
        # Normalize hallucinated ``zim_file_path`` BEFORE branching to the
        # synthesize pipeline. Small models pass bare filenames
        # (``"wikipedia.zim"``) or article titles (``"Big Rapids,
        # Michigan.zim"``) when the parameter is documented as optional;
        # the path validator anchors them to the process CWD and produces
        # a confusing ``Access denied`` error. Pre-A14 fix, only the
        # intent-classification branch (below) ran this resolver — the
        # synthesize branch bypassed it, so the same hallucinated path
        # succeeded with ``synthesize=False`` and failed with
        # ``synthesize=True``. Lifting the resolver here makes both
        # branches share one policy. The ``zim_file_path is None`` case
        # is intentionally NOT normalized here: synthesize opens all
        # archives for multi-archive RRF fusion when no path is given,
        # while the intent branch auto-selects when exactly one archive
        # is available.
        if zim_file_path:
            zim_file_path = self._normalize_zim_file_path(zim_file_path)

        if options.get("synthesize"):
            try:
                return self._handle_synthesize_query(
                    query,
                    zim_file_path,
                    compact=bool(options.get("compact", False)),
                )
            except Exception as e:
                logger.error(
                    "Unexpected error in synthesize path: %s", e, exc_info=True
                )
                return tool_error(
                    operation="synthesize_pipeline_error",
                    message=f"Synthesize pipeline failed: {e}",
                )
        # Post-b1: snapshot reranker telemetry counters so the response
        # envelope can surface whether rerank engaged for this specific
        # request. The four counters (engaged / skipped.not_installed /
        # skipped.no_results / skipped.passthrough) live in
        # ``self._telemetry`` and are advanced-mode-only via
        # ``get_server_health``; HTTP-MCP hosts that filter that tool
        # out leave simple-tool callers with no in-band visibility.
        # The delta-based check is best-effort and matches the existing
        # telemetry-Counter concurrency model (Counter mutations are not
        # atomic across threads, so a parallel request could leak its
        # event in — same tradeoff the post-b1 INFO log already accepts).
        _RERANK_EVENTS_BEFORE = {
            _RERANKER_ENGAGED: self._telemetry.get(_RERANKER_ENGAGED, 0),
            _RERANKER_SKIPPED_NOT_INSTALLED: self._telemetry.get(
                _RERANKER_SKIPPED_NOT_INSTALLED, 0
            ),
            _RERANKER_SKIPPED_NO_RESULTS: self._telemetry.get(
                _RERANKER_SKIPPED_NO_RESULTS, 0
            ),
            _RERANKER_SKIPPED_PASSTHROUGH: self._telemetry.get(
                _RERANKER_SKIPPED_PASSTHROUGH, 0
            ),
        }
        try:
            # Reject empty / whitespace-only queries upfront. The router
            # would otherwise classify the input as a low-confidence search
            # and fall through to ``search_zim_file("")``, which the search
            # tool itself rejects — so the only thing we'd return is a
            # confusing "No search results found for ''" string. Validate
            # at the front door so the caller gets an actionable message.
            if not query or not query.strip():
                return (
                    "**Query Required**\n\n"
                    "**Issue**: query must be a non-empty natural-language "
                    "string.\n\n"
                    "**Examples**:\n"
                    "- `list available ZIM files`\n"
                    '- `search for "evolution"`\n'
                    "- `get article Tiger`\n"
                    "- `show structure of Biology`\n"
                    "<!-- intent=query_required cert=1.00 -->"
                )
            # Conversational filler / meta-instructions ("do both",
            # "try again", "test this", "ok") have no information content
            # for the intent classifier and would otherwise produce one of:
            #   * a no-results search ("No search results found for...")
            #   * a 200k-hit search dominated by stop-word collisions
            #   * an article-body dump for a coincidental title match
            #     ("try again" -> Aaliyah's "Try Again" song body)
            # None of those teach the caller what to do next. Return
            # explicit guidance instead so the LLM (or user) sees the
            # tool's playbook on the very next turn.
            if self._is_meta_only_query(query):
                self._track("meta_only_guidance")
                # A11 post-a11 L1 (second pass): meta-only guidance is
                # the third structured early-return path the first L1
                # fix missed. Same telemetry contract as the chained
                # / topic-required / search-terms-required paths so
                # callers branching on the comment see this rejection
                # class too.
                return self._meta_query_guidance() + (
                    "\n<!-- intent=meta_only_guidance cert=1.00 -->"
                )
            # A11 B1: a query that chains two operation phrases
            # ("tell me about berlin then list namespaces") would
            # otherwise silently dispatch to whichever intent ranked
            # highest, dropping the other half on the floor. Detect
            # the chain and ask the caller to split the work into
            # separate calls before the parser can swallow it.
            chained_warning = self._chained_intent_guidance(query)
            if chained_warning is not None:
                self._track("chained_intent_rejected")
                # A11 post-a11 L1: structured guidance responses participate
                # in the same intent-telemetry contract as article-body
                # responses (Opp6). Append a deterministic comment so a
                # calling LLM can branch on the rejection class without
                # body-parsing.
                return chained_warning + (
                    "\n<!-- intent=chained_intent_rejected cert=1.00 -->"
                )
            # Sub-D-2: build the title probe (returns None when no archive
            # is in scope; rules 2 and 3 degrade gracefully). Snapshot
            # intermediate stages by running the rules individually to emit
            # per-rule telemetry. This keeps parse_intent's responsibilities
            # clean (it doesn't know about _track); the cost is two extra
            # rule passes worth of CPU per query.
            if self.zim_operations.config.query_rewrite.enabled:
                # Post-b1 P1-D1: resolve the probe archive BEFORE
                # building the probe so it sees the same archive
                # ``handle_zim_query`` will auto-select downstream
                # (single-archive case). Pre-fix, ``zim_file_path``
                # was passed straight through and produced a None
                # probe whenever the caller omitted the path — the
                # documented-as-recommended pattern.
                probe_path = self._probe_archive_path(zim_file_path)
                title_probe = self._build_title_probe(probe_path)
                after_lower = IntentParser._normalize_topic_case(query)
                after_misspell = IntentParser._apply_misspelling_map(
                    after_lower, title_probe=title_probe
                )
                if after_misspell != after_lower:
                    self._track(_QUERY_REWRITE_MISSPELLING)
                after_stopword = IntentParser._detect_stopword_phrase(
                    after_misspell, title_probe=title_probe
                )
                if after_stopword != after_misspell:
                    self._track(_QUERY_REWRITE_STOPWORD_PHRASE)
                # Post-b1 P1-D3: pass the same probe so Rule 4 can
                # suppress decomposition when the full query is itself
                # a canonical title (``lord of the rings``,
                # ``the art of war``, ``history of rome``).
                _, hint_probe = IntentParser._decompose_x_of_y(
                    after_stopword, title_probe=title_probe
                )
                if hint_probe is not None:
                    self._track(_QUERY_REWRITE_X_OF_Y)
            else:
                title_probe = None

            intent, params, confidence = self.intent_parser.parse_intent(
                query,
                title_probe=title_probe,
                query_rewrite_enabled=self.zim_operations.config.query_rewrite.enabled,
            )
            # Post-b1 P1-D2: stash the pre-rewrite, original-case query
            # in params so user-facing guidance (multi-entity chain
            # rejection, soft-connector footer) can echo entities back
            # in the caller's casing instead of Rule 1's lowercased
            # form. The leading underscore marks this as a wiring-layer
            # hint — consumers should treat its absence as the legacy
            # behaviour (use the lowercase value as-is).
            if isinstance(params, dict):
                params.setdefault("_pre_rewrite_query", query)
            # Post-a21 P1-D1: defence-in-depth strip of trailing
            # politeness on user-supplied content fields in ``params``.
            # Idempotent when ``parse_intent`` already cleaned them
            # (the post-a20 PD2-1 strip lives there), and a belt-and-
            # suspenders catch for any future regression that returns
            # ``params`` with politeness still attached (the live a21
            # sweep observed ``Found N matches for "biology please"``
            # despite the source-side ``parse_intent`` strip working
            # correctly under direct unit test — the most likely cause
            # was an in-process module cache on the live server that
            # loaded only part of PR #152, but the user-visible defect
            # is the same shape regardless of root cause). Idempotent
            # by construction — the strip's regex is end-anchored and
            # leaves clean content untouched.
            if isinstance(params, dict):
                # Post-a22 P1-D6: widen the defence-in-depth strip
                # to ``section_name`` (carries user-content for
                # ``section <X> of <Y>`` queries) — every other field
                # set by an extractor that captures with a greedy tail
                # is at risk if ``parse_intent``'s universal strip ever
                # fails (in-process module cache, future regression).
                # ``entries`` is a list of strings handled separately
                # below because the universal scalar-string strip can't
                # iterate it.
                for _key in (
                    "query",
                    "topic",
                    "title",
                    "entry_path",
                    "partial_query",
                    "section_name",
                ):
                    _v = params.get(_key)
                    if isinstance(_v, str) and _v:
                        _v_clean = IntentParser._strip_trailing_politeness(_v).strip()
                        if _v_clean != _v:
                            params[_key] = _v_clean
                # ``entries`` is a list of entry-path strings (from
                # batched ``get N entries`` parses). Strip per-element
                # so a trailing politeness on the last entry doesn't
                # become part of the path.
                _entries = params.get("entries")
                if isinstance(_entries, list) and _entries:
                    _cleaned_entries: List[Any] = []
                    _changed = False
                    for _entry in _entries:
                        if isinstance(_entry, str) and _entry:
                            _entry_clean = IntentParser._strip_trailing_politeness(
                                _entry
                            ).strip()
                            if _entry_clean != _entry:
                                _changed = True
                            _cleaned_entries.append(_entry_clean)
                        else:
                            _cleaned_entries.append(_entry)
                    if _changed:
                        params["entries"] = _cleaned_entries
            # A11 B2: ``tell me about <empty>`` (trailing-space input,
            # punctuation-only topic) used to fall through to a topic
            # of ``"tell me about"`` and disambiguate to article titles
            # literally named "Tell Me About Tomorrow". Validate the
            # extracted topic before the handler can search for it.
            if intent == "tell_me_about" and isinstance(params, dict):
                topic = (params.get("topic") or "").strip()
                if not topic:
                    return (
                        "**Topic Required**\n\n"
                        "**Issue**: `tell me about` needs a non-empty "
                        "topic to look up.\n\n"
                        "**Examples**:\n"
                        "- `tell me about Photosynthesis`\n"
                        "- `who is Albert Einstein`\n"
                        "- `describe DNA`\n"
                        "<!-- intent=topic_required cert=1.00 -->"
                    )
            # A11 B4: ``search for `` (trailing space, no terms) used
            # to fall through to searching for the literal word "for".
            # Validate the extracted query before dispatch.
            if intent == "search" and isinstance(params, dict):
                search_q = (params.get("query") or "").strip()
                # If the extractor copied the full query verbatim because
                # nothing followed "search for", the result equals the
                # original query — accept that case only when there are
                # ≥1 non-stopword content tokens. Otherwise reject.
                #
                # Post-a21 P1-D8: peel trailing politeness from the
                # tail before the empty-check. Pre-fix, ``search for
                # please`` (and ``search for ta`` after the P1-D6
                # extension) returned tail=``"please"`` (non-empty),
                # the guard didn't fire, ``_extract_search`` captured
                # ``"for"`` as the search term and the user got a
                # 200k-hit response dominated by the literal verb
                # word. The strip is idempotent — when the tail
                # carries real content the politeness substring is
                # never trailing.
                tail = self._search_query_tail(query)
                if tail is not None:
                    tail = IntentParser._strip_trailing_politeness(tail).strip()
                if tail is not None and not tail:
                    return (
                        "**Search Terms Required**\n\n"
                        "**Issue**: `search for` needs at least one "
                        "search term.\n\n"
                        "**Examples**:\n"
                        '- `search for "quantum mechanics"`\n'
                        "- `search for Berlin in namespace C`\n"
                        "<!-- intent=search_terms_required cert=1.00 -->"
                    )
                # Replace the params copy with the cleaned tail so the
                # handler doesn't run on the verb-prefixed raw query.
                if tail:
                    params["query"] = tail
                else:
                    params["query"] = search_q
            logger.info(
                f"Parsed intent: {intent}, params: {params}, "
                f"confidence: {confidence:.2f}"
            )
            self._track(f"intent.{intent}")

            low_confidence_note = self._confidence_note(intent, confidence, query)
            if low_confidence_note:
                self._track("low_confidence_note")

            # ``list_files`` is the only intent that doesn't need a ZIM file.
            if intent == "list_files":
                return self.zim_operations.list_zim_files() + low_confidence_note

            # Post-v2.0.0 D-A: ``search_all`` is semantically cross-archive
            # — ``_handle_search_all`` ignores ``zim_file_path`` and
            # iterates every loaded archive via ``search_all_data`` /
            # ``search_all``. Pre-fix this intent tripped the
            # no-zim-file gate when 2+ archives were loaded and the
            # caller followed the docstring's recommendation to OMIT
            # the path; the gate blocked the intended cross-archive
            # query. Mirror the ``list_files`` bypass: route past the
            # gate and let the handler iterate. Pass any caller-supplied
            # path through unchanged (the handler ignores it but
            # downstream low-confidence rendering / telemetry expect a
            # non-empty string).
            if intent == "search_all":
                zim_file_path = zim_file_path or ""
            elif not zim_file_path:
                # Post-v2.0.0 D-B: ``metadata for X.zim`` carries a
                # filename hint that the dispatcher can resolve against
                # the loaded archives BEFORE the no-zim-file gate fires.
                # Without this, the multi-archive case (2+ loaded ZIMs)
                # fails the gate even though the query named the target
                # in plain text. Only resolves to a real archive path;
                # unknown filenames still fall through to the gate so
                # the operator sees a clear error.
                if intent == "metadata" and isinstance(params, dict):
                    hint = params.get("metadata_target")
                    if hint:
                        resolved = self._resolve_zim_path(hint)
                        if resolved:
                            zim_file_path = resolved
                if not zim_file_path:
                    zim_file_path = self._auto_select_zim_file()
                if not zim_file_path:
                    # Post-v2.0.5 D-M: callers hitting the
                    # ambiguous-archive gate (2+ archives loaded, no
                    # ``zim_file_path`` arg, intent doesn't
                    # auto-select) saw only "specify a ZIM file
                    # path" with a raw file listing — no hint that
                    # ``search all files for X`` or
                    # ``synthesize=True`` would route across all
                    # archives without an explicit path. Add a
                    # "Try one of these to recover:" block
                    # mirroring the shape used elsewhere.
                    return (
                        "**No ZIM File Specified**\n\n"
                        "Please specify a ZIM file path, or ensure there is "
                        "exactly one ZIM file available.\n\n"
                        "**Try one of these to recover:**\n"
                        "- Pass the `zim_file_path` argument to target a "
                        "specific archive\n"
                        "- `search all files for <terms>` — fan out across "
                        "every loaded archive\n"
                        "- `tell me about <topic>` with `synthesize=True` — "
                        "auto-open every loaded archive and pick the best "
                        "hit\n\n"
                        "**Available files:**\n"
                        f"{self.zim_operations.list_zim_files()}"
                        "\n<!-- intent=no_zim_file_specified cert=1.00 -->"
                    )
            # Hallucinated paths were already normalized at the top of
            # ``handle_zim_query`` (see comment above the synthesize branch).
            # By this point, ``zim_file_path`` is either a known real path,
            # an auto-selected fallback, or an unmatched slashed path that
            # the caller deliberately wrote (H14: explicit paths must reach
            # the backend and surface a clear error there, not a silent
            # auto-replacement).

            # Post-a21 P1-D2 / P1-D3 / P1-D4: detect bare-topic chains
            # of 3+ substantive proper-noun-shaped halves joined by soft
            # connectors (``and`` / ``or`` / ``,`` / ``&`` / ``vs`` /
            # ``/``). The post-a20 P1-D2 alias-fallback widening only
            # addresses the 2-entity asymmetric case (``Köln or Cologne``).
            # 3+ entity queries either silently dropped halves
            # (``Berlin and München and Köln`` → Cologne, no footer
            # about Berlin or München) or produced a footer suggesting
            # a still-chained re-query (``Köln, München, and Berlin``
            # → footer ``tell me about Köln, München,``).
            multi_entity_warning = self._multi_entity_chain_guidance(
                intent, params, zim_file_path
            )
            if multi_entity_warning is not None:
                self._track("multi_entity_chain_rejected")
                return multi_entity_warning

            handler = self._INTENT_HANDLERS.get(
                intent, SimpleToolsHandler._handle_search
            )
            raw = handler(self, query, zim_file_path, params, options)
            # Unpack structured handler results; plain string handlers are
            # unaffected — they return a ``str`` as before.
            if isinstance(raw, _HandlerResult):
                result = raw.body
                handler_reason: Optional[str] = raw.reason
                handler_suggestions: Optional[List[Dict[str, str]]] = raw.suggestions
            else:
                result = raw
                handler_reason = None
                handler_suggestions = None
            if options.get("compact", False) and intent in self._TEXT_HEAVY_INTENTS:
                # Strip markdown link-soup ([text](href "tooltip") -> text)
                # from article-body and search-snippet responses. Wikipedia
                # markdown is ~50% link syntax in the head of a typical
                # article, ~86% in main-page nav lists. Stripping ~halves
                # the context cost for the same prose payload, without
                # losing any content that a small LLM was going to use
                # anyway (small LLMs don't follow inline links from inside
                # tool responses; they issue follow-up tool calls). The
                # JSON-returning intents (structure / links / find_by_title
                # / related / etc.) handle their own compact rendering and
                # are deliberately not in _TEXT_HEAVY_INTENTS.
                result = self._strip_markdown_links(result)
            if options.get("compact", False) and intent in self._SEARCH_RENDER_INTENTS:
                # Search snippets default to 3000 chars per result. For
                # 5 results that's 15k chars of preview alone — a small
                # LLM only needs ~250 chars to rank relevance. Truncate
                # each snippet AFTER the link-soup strip so the cap
                # applies to the post-stripped char count.
                result = self._truncate_search_snippets(result)
            result = result + low_confidence_note
            # A11 Opp6: intent telemetry footer. Invisible to humans
            # (HTML comment, not rendered) but visible in the raw token
            # stream so a calling LLM can branch on the parsed intent
            # and the parser's classification certainty. Cheaper than
            # parsing the body to infer what the tool did. Skipped when
            # the result is already a ToolErrorPayload (dict) — those
            # carry ``operation`` themselves.
            #
            # The certainty is emitted as ``cert=`` (not the obvious
            # ``confidence=``) so existing tests asserting
            # ``"confidence" not in result`` for the visible-note path
            # still hold — the visible note uses the prose word
            # "confidence", the invisible telemetry uses the marker
            # ``cert``.
            if isinstance(result, str):
                result = result + (f"\n<!-- intent={intent} cert={confidence:.2f} -->")
                # Post-b1: surface reranker engagement state in-band so
                # simple-tool callers (the default mode) can confirm
                # whether D-1's cross-encoder rerank actually engaged
                # for this request. Mirrors the intent telemetry shape
                # (HTML comment, invisible to humans, addressable by a
                # calling LLM). Emitted only when the request actually
                # touched a search path — non-search intents leave the
                # counter untouched and the comment is suppressed.
                _rerank_state = self._compute_rerank_state(_RERANK_EVENTS_BEFORE)
                if _rerank_state is not None:
                    result = result + f"\n<!-- reranker={_rerank_state} -->"
            if options.get("compact", False):
                # Belt-and-suspenders cap: even after every per-intent
                # trim, a backend can return more than the simple-mode
                # budget can absorb (e.g. a future intent that doesn't
                # know about compact, a backend error message that
                # echoes a large payload, etc.). Hard-cap the response
                # so the LLM's per-turn context cost is predictable.
                # Budget is sizable to the calling model — 4k for an
                # 8B-class model on an agentic prompt, 12k for a 70B
                # assistant. The footer names the original size so the
                # LLM knows it's seeing a tail.
                budget = self._resolve_compact_budget(options.get("compact_budget"))
                # Reserve room for the prompt-injection fence so its
                # closing tag is never cut by the cap.
                will_wrap = intent in self._PROMPT_INJECTION_FENCE_INTENTS
                effective_budget = (
                    budget - self._CONTENT_FENCE_OVERHEAD if will_wrap else budget
                )
                # Capture pre-cap size to report truncation in footer
                pre_cap_chars = len(result)
                if len(result) > effective_budget:
                    self._track("response_truncated")
                result = self._cap_response_size(
                    result, effective_budget, intent=intent
                )
                # Determine if truncation occurred
                was_truncated = len(result) < pre_cap_chars
                if will_wrap:
                    result = self._wrap_retrieved_content(result)

                # Op5 (v2.0.0a9): simple-mode truncation comes from
                # ``_cap_response_size`` capping the *rendered output*
                # — the operation underneath doesn't support content-
                # byte re-pagination from this layer. Passing
                # ``content_chars=None`` suppresses the misleading
                # ``pass offset=N for more`` footer hint (which
                # interprets ``offset`` as a result-set index for
                # search/browse, not a byte offset). The
                # ``_cap_response_size`` body already carries the
                # actionable recovery advice (``tighter query`` /
                # ``compact=False``) so the user isn't blind.
                # ``total_chars`` stays so callers can still see how
                # much was elided. ``handler_reason`` /
                # ``handler_suggestions`` (compact-mode zero-result
                # search) drive the empty-result footer variant.
                meta = build_meta(
                    rendered=result,
                    truncated=was_truncated,
                    content_chars=None,
                    total_chars=pre_cap_chars if was_truncated else None,
                    reason=handler_reason,
                    suggestions=handler_suggestions,
                )
                footer = format_footer(
                    meta,
                    footer_enabled=self.zim_operations.config.meta.footer_enabled,
                )
                if footer:
                    result = result + "\n\n" + footer
            return result

        except Exception as e:
            logger.error(f"Error handling zim_query: {e}")
            # Sanitize both the query and error text to avoid leaking
            # absolute filesystem paths back to the MCP client.
            safe_query = sanitize_context_for_error(query)
            safe_error = sanitize_context_for_error(str(e))
            # M31: when the inner synthesize branch raises past its own
            # try-except (rare but reachable on unexpected internal
            # failures), the outer except previously swallowed the
            # ``ToolErrorPayload`` shape and emitted a markdown string.
            # Detect the synthesize path and return a structured error
            # so callers can programmatically branch on
            # ``result.error``.
            if options.get("synthesize"):
                return tool_error(
                    operation="synthesize_pipeline_error",
                    message=f"Synthesize pipeline failed: {safe_error}",
                    context=f"Query: {safe_query}",
                )
            # Post-a20 PD2-4: when ``validate_zim_file`` raises (file
            # does not exist / not a file / wrong extension), the
            # generic four-step "Troubleshooting" block gives small
            # models no learning signal — they just retry the same
            # call. Replace with a targeted recovery hint that lists
            # the actual loaded archive paths and points at the
            # canonical fix ("omit `zim_file_path` to auto-select" or
            # "use one of these paths verbatim"). PD2-3's auto-select
            # already handles single-archive setups silently; this
            # branch is the multi-archive recovery surface (and
            # defence-in-depth if PD2-3's backend listing ever fails).
            error_lower = str(e).lower()
            looks_like_zim_path_error = any(
                marker in error_lower
                for marker in (
                    "file does not exist",
                    "path is not a file",
                    "is not a zim file",
                    "access denied",
                )
            )
            if looks_like_zim_path_error:
                hint = self._zim_path_recovery_hint()
                if hint is not None:
                    # Post-a21 P1-D10: surface the original exception
                    # message alongside the recovery hint. Pre-fix the
                    # detector matched ``"access denied"`` substring,
                    # which the security validator's
                    # ``OpenZimMcpSecurityError`` ("Access denied -
                    # Path is outside allowed directories") triggered
                    # in addition to the intended file-not-found
                    # ``OpenZimMcpValidationError``. The replacement
                    # body dropped the security-specific reason on
                    # the floor and emitted only the generic "doesn't
                    # match any loaded archive" message — confusing
                    # the caller about why their path actually failed
                    # (path outside allowed tree vs typoed filename).
                    # Including ``**Reason**`` keeps the diagnostic
                    # context while still surfacing the recovery hint.
                    return (
                        f"**ZIM File Not Found**\n\n"
                        f"**Query**: {safe_query}\n"
                        f"**Issue**: the `zim_file_path` value passed "
                        f"doesn't match any loaded archive.\n"
                        f"**Reason**: {safe_error}\n\n"
                        f"{hint}\n\n"
                        f"<!-- intent=zim_path_not_found cert=1.00 -->"
                    )
            return (
                f"**Error Processing Query**\n\n"
                f"**Query**: {safe_query}\n"
                f"**Error**: {safe_error}\n\n"
                f"**Troubleshooting**:\n"
                f"1. Omit `zim_file_path` to auto-select the loaded "
                f"archive (single-archive setups), or call "
                f"`list available ZIM files` to see real paths\n"
                f"2. Verify the query format\n"
                f"3. Try a simpler query\n"
                f"4. Check server logs for details"
            )

    def _zim_path_recovery_hint(self) -> Optional[str]:
        """Post-a20 PD2-4: render the recovery hint surfaced by the
        catch-all when ``validate_zim_file`` raises. Returns a
        Markdown fragment listing real archive paths plus the
        canonical "omit to auto-select" fix, or ``None`` if the
        backend listing can't be fetched (caller falls back to the
        generic troubleshooting block).

        Defensive against backend failures: ``list_zim_files_data``
        going sideways should never block the error path itself.
        """
        try:
            files = self.zim_operations.list_zim_files_data()
        except Exception:
            return None
        if not isinstance(files, list) or not files:
            return None
        paths: List[str] = []
        for entry in files:
            if isinstance(entry, dict):
                p = entry.get("path")
                if isinstance(p, str) and p:
                    paths.append(p)
        if not paths:
            return None
        if len(paths) == 1:
            return (
                "**Recovery**: this archive is the only one loaded — "
                "omit the `zim_file_path` parameter entirely and the "
                "tool will auto-select it.\n\n"
                f"**Loaded archive**: `{paths[0]}`"
            )
        bullets = "\n".join(f"  - `{p}`" for p in paths)
        return (
            "**Recovery**: pass one of the paths below verbatim, or "
            "use `list available ZIM files` for the same listing.\n\n"
            f"**Loaded archives**:\n{bullets}"
        )

    @staticmethod
    def _search_query_tail(query: str) -> Optional[str]:
        """Return the search-tail string after ``search for`` /
        ``find`` / ``look up`` etc. if the query is search-shaped.

        Returns ``None`` if the query doesn't look like a search verb
        prefix (so the legacy bare-query fallback applies). Returns an
        empty string if the verb prefix is present but no terms
        follow (``search for `` or ``search for`` with no trailing
        whitespace) — the caller surfaces an error.

        Split into three single-token regexes (verb, optional ``up``
        for ``look up``, optional ``for`` connector) rather than one
        combined pattern so static analyzers can't flag adjacent
        ``\\s*`` / ``\\s+`` quantifiers as polynomial-backtracking
        hotspots.
        """
        verb_m = re.match(r"^\s*(search|find|look)\b", query, re.IGNORECASE)
        if not verb_m:
            return None
        tail = query[verb_m.end() :]
        if verb_m.group(1).lower() == "look":
            up_m = re.match(r"\s+up\b", tail, re.IGNORECASE)
            if up_m:
                tail = tail[up_m.end() :]
        for_m = re.match(r"\s+for\b", tail, re.IGNORECASE)
        if for_m:
            tail = tail[for_m.end() :]
        return tail.strip().rstrip("?.,;:!").strip()

    @staticmethod
    def _confidence_note(intent: str, confidence: float, query: str = "") -> str:
        """Render a confidence note tier-appropriate for the parsed intent.

        Tiers:
          * < 0.55 — "low confidence". Names the interpreted intent so the
            caller can spot fallbacks (e.g. ``"tell me a joke"`` lands on
            the search-fallback at confidence 0.5; saying the result is
            "moderate confidence" understates that nothing matched).
          * 0.55–0.7 — "moderate confidence" (legacy wording).
          * >= 0.7 — no note (well-calibrated, don't pester).

        Suppression: when the intent is ``search`` and the query looks like
        a bare topic name (proper noun phrase with no command verbs),
        defaulting to search is the *correct* interpretation — the
        confidence number is low because the intent classifier had nothing
        verb-shaped to latch onto, not because the answer is uncertain.
        Emitting a "low confidence" warning in that case has misled both
        humans (who think the search results are bad) and LLMs (who choose
        not to trust them). Skip the note for that pattern.
        """
        if (
            intent == "search"
            and confidence < 0.7
            and IntentParser._looks_like_bare_topic(query)
        ):
            return ""
        if confidence < 0.55:
            return (
                "\n\n*Note: Low confidence in query interpretation "
                f"(interpreted as `{intent}`). "
                "Try rephrasing your query if the results aren't what "
                "you expected.*\n"
            )
        if confidence < 0.7:
            return (
                "\n\n*Note: This query interpretation has moderate confidence. "
                "If the results aren't what you expected, "
                "try rephrasing your query.*\n"
            )
        return ""

    @staticmethod
    def _is_meta_only_query(query: str) -> bool:
        """Return True iff ``query`` is conversational filler / meta-instruction.

        Heuristic — every alphanumeric token (lowercased) is in
        ``IntentParser._COMMON_FILLER_TOKENS`` AND no token is
        capitalized in the original query AND the query has at most a
        handful of tokens. Capitalization is treated as a user-typed
        proper-noun signal: ``"Hello"`` alone is borderline filler but
        ``"Hello"`` capitalized may genuinely be the song title — defer
        to the intent parser in that case.

        Intentionally conservative: the false-positive cost (treating
        a real query as filler) is much higher than the
        false-negative cost (letting a filler query through to the
        intent parser, where the bare-topic gate is the second line of
        defense — see :meth:`IntentParser._looks_like_bare_topic`).
        """
        if not query:
            return False
        raw_tokens = re.findall(r"[A-Za-z0-9]+", query)
        # Cap at 8 tokens — anything longer is a real sentence, not
        # conversational filler.
        if not raw_tokens or len(raw_tokens) > 8:
            return False
        if any(t[0].isupper() for t in raw_tokens):
            return False
        return all(t.lower() in IntentParser._COMMON_FILLER_TOKENS for t in raw_tokens)

    @staticmethod
    def _meta_query_guidance() -> str:
        """Render a structured-guidance response for meta-only queries.

        The response names a small starter playbook that maps directly
        onto specific intents the parser handles with high confidence.
        An LLM that copied the user's literal "test this tool" message
        verbatim sees this guidance on its next turn and can pick a
        concrete starter query — turning a useless 200k-hit search into
        an actionable hint.
        """
        return (
            "**Your query looks like exploratory or conversational "
            "filler — I couldn't extract a topic or operation.**\n\n"
            "**Try one of these starting points:**\n"
            "- `list available ZIM files` — see what archives are loaded\n"
            "- `show main page` — read the main page of the active "
            "archive\n"
            "- `list namespaces` — see what entry types exist\n"
            "- `tell me about <topic>` — fetch an article "
            "(e.g. `tell me about Photosynthesis`)\n"
            "- `search for <terms>` — full-text search\n"
        )

    # Intents whose responses are dense markdown-rendered prose (article
    # body or search snippets). In compact mode the outer dispatcher
    # strips ``[text](url "tooltip")`` markdown link syntax from these,
    # which roughly doubles the useful prose density per token. Other
    # intents return JSON or short structured text; they do their own
    # compact rendering when needed.
    _TEXT_HEAVY_INTENTS = frozenset(
        {
            "main_page",
            "get_article",
            "tell_me_about",
            "search",
            "search_all",
            "filtered_search",
            "summary",
            "get_section",
        }
    )

    # Subset of ``_TEXT_HEAVY_INTENTS`` whose responses contain raw
    # third-party prose (article body, lead-section, named section).
    # These get wrapped in a content-fence + "treat as data" annotation
    # so an LLM consuming the tool output is signaled that the prose
    # came from an external archive and any instruction-shaped text
    # inside is data, not directives. Search-shaped intents are
    # excluded — their snippets are short and pre-trimmed, and the
    # outer ``## N. <title>`` scaffolding already telegraphs "list of
    # results" rather than "free-form text from somewhere".
    _PROMPT_INJECTION_FENCE_INTENTS = frozenset(
        {"main_page", "get_article", "tell_me_about", "summary", "get_section"}
    )

    # Search-shaped intents: their rendered output has the canonical
    # ``Snippet: ...`` blocks that ``_truncate_search_snippets`` knows
    # how to compress. tell_me_about is included for its
    # search-fallback path (when no strong title match).
    _SEARCH_RENDER_INTENTS = frozenset(
        {"search", "filtered_search", "search_all", "tell_me_about"}
    )

    # Post-a20 P1-D1: the set of cursor-emitting tools that legitimately
    # carry an ``s.q`` field in their cursor payload (``search_zim_file``
    # / ``search_with_filters`` — see ``Cursor.encode`` callsites in
    # ``zim/search.py``). Other cursor-emitting tools (``walk_namespace``
    # / ``browse_namespace`` / ``extract_article_links``) never emit
    # ``s.q``; if a cursor claims one of those tools but still carries
    # ``s.q``, the field is adversarial or vestigial. The dispatcher's
    # q-overlap check skips that case so the handler-level
    # ``_cursor_tool_mismatch`` can fire with the correct diagnosis.
    _Q_EMITTING_CURSOR_TOOLS = frozenset({"search_zim_file", "search_with_filters"})

    @staticmethod
    def _cursor_tool_mismatch(
        options: Dict[str, Any], request_tool: str
    ) -> Optional[str]:
        """Post-a18 P1-D4: return a structured error when the decoded
        cursor's ``s.t`` (issuing tool) differs from the handler's
        own tool name. The simple-tools dispatcher decodes cursors
        in-place earlier, bypassing the advanced tools'
        ``Cursor.decode(expected_tool=...)`` enforcement; this helper
        restores cross-tool rejection at the handler edge.

        Returns ``None`` when no cursor was passed, when the cursor
        had no ``t`` field, or when both match. The error shape
        mirrors the existing ``s.ns`` / ``s.q`` / ``s.ai`` mismatch
        errors so callers programmatically branching on
        ``cursor_decode`` keep working unchanged.
        """
        cursor_t = options.get("_cursor_t")
        if not isinstance(cursor_t, str) or not cursor_t:
            return None
        if cursor_t == request_tool:
            return None
        return (
            "**Cursor / Tool Mismatch**\n\n"
            "**Issue**: the cursor was issued by "
            f"`{cursor_t}` but this call routes to "
            f"`{request_tool}`. Drop the cursor and call again "
            "without it (or restart the paginated call with the "
            "tool that issued the cursor).\n\n"
            "<!-- intent=cursor_decode cert=1.00 -->"
        )

    @staticmethod
    def _cursor_ns_mismatch(
        options: Dict[str, Any], request_namespace: str
    ) -> Optional[str]:
        """P3-D7 helper: return a structured error string when the
        decoded cursor's ``s.ns`` differs from the request's namespace.

        Returns ``None`` when no cursor was passed, when the cursor had
        no ``ns`` field, or when both match (case-insensitive). The
        error shape mirrors the existing ``s.q`` / ``s.ai`` mismatch
        errors so callers programmatically branching on ``cursor_decode``
        keep working unchanged.
        """
        cursor_ns = options.get("_cursor_ns")
        if not isinstance(cursor_ns, str) or not cursor_ns:
            return None
        # Canonicalise both sides — namespace inputs are accepted
        # case-insensitive across the dispatcher surface.
        if cursor_ns.strip().upper() == request_namespace.strip().upper():
            return None
        return (
            "**Cursor / Namespace Mismatch**\n\n"
            "**Issue**: the cursor was issued for namespace "
            f"`{cursor_ns}` but this call asked for namespace "
            f"`{request_namespace}`. Drop the cursor and call again "
            "without it (or start a fresh page-1 request for the new "
            "namespace).\n\n"
            "<!-- intent=cursor_decode cert=1.00 -->"
        )

    # ---------------------------------------------------------------- handlers

    def _handle_metadata(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        return self.zim_operations.get_zim_metadata(zim_file_path)

    def _handle_main_page(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        return self.zim_operations.get_main_page(
            zim_file_path, compact=options.get("compact", False)
        )

    def _handle_list_namespaces(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        if options.get("compact", False):
            data = self.zim_operations.list_namespaces_data(zim_file_path)
            return compact_renderers.render_namespaces(data)
        return self.zim_operations.list_namespaces(zim_file_path)

    def _handle_browse(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        # A15 post-a15 P6-D1: missing / malformed namespace argument
        # used to fall through to ``params.get("namespace", "C")`` and
        # silently browse C — exact analogue of the walk_namespace
        # P4-D3 defect, same shape error, same fix. Mirror the
        # walk_namespace missing-arg shape so the error surface is
        # consistent across the simple-mode tools.
        namespace = params.get("namespace")
        if not namespace:
            return (
                "**Missing or Invalid Namespace**\n\n"
                "**Issue**: `browse namespace` needs a single namespace "
                "letter (A, C, M, W, etc.; case-insensitive).\n"
                "**Examples**:\n"
                "- `browse namespace C` — main content entries\n"
                "- `browse namespace M` — archive metadata\n"
                "- `browse namespace W` — well-known entries"
            )
        # Post-a18 P1-D4: cursor's tool must match this handler.
        # Walk-namespace's cursor previously walked browse silently
        # because the simple-tools dispatcher only read ``s.o`` and
        # ``s.ns`` from the decoded cursor — neither encoded the
        # issuing tool. The advanced tools already enforce this via
        # ``Cursor.decode(expected_tool=...)``; this restores the
        # check at the simple-tools handler edge.
        tool_mismatch = self._cursor_tool_mismatch(options, "browse_namespace")
        if tool_mismatch is not None:
            return tool_mismatch
        # P3-D7: cursor's namespace must match the request's namespace.
        mismatch = self._cursor_ns_mismatch(options, namespace)
        if mismatch is not None:
            return mismatch
        return self.zim_operations.browse_namespace(
            zim_file_path,
            namespace,
            options.get("limit", 50),
            options.get("offset", 0),
        )

    # a13 D8: backend "entry not found" messages occasionally leak
    # Python helper names (``search_zim_file()`` / ``browse_namespace()``)
    # that don't exist on the MCP surface. Strip them so the recovery
    # message lists only commands the caller can actually issue.
    _BACKEND_API_LEAK_RE = re.compile(
        r"\s*Try using \w+\(\)[^.]*\.?",
    )

    def _render_not_found_recovery(
        self,
        entry_path: str,
        exc: Exception,
        op_label: str,
    ) -> str:
        """Render a structured "entry not found" response for handlers
        whose underlying backend call raised on an unknown entry path.

        Pre-a13, the four handlers ``show structure of`` / ``summary of`` /
        ``get article`` / ``links in`` propagated the exception up to the
        top-level ``handle_zim_query`` ``except`` block, which emitted a
        generic ``**Error Processing Query**`` template with no intent
        telemetry, leaked Python function names from the backend error
        text (``Try using search_zim_file()``), and pointed callers at
        ``Check server logs`` (which the MCP surface can't see). a13 D8
        modernises the four sites to match the shape ``_handle_related``
        already used: a clear article path in the title, a sanitized
        error body, and three concrete recovery commands the caller can
        paste back. The outer ``handle_zim_query`` then layers the
        ``<!-- intent=... cert=... -->`` telemetry comment on success
        — which now fires because the handler returned a string instead
        of raising.
        """
        err = sanitize_context_for_error(str(exc))
        err = self._BACKEND_API_LEAK_RE.sub("", err).strip()
        recovery_path = entry_path[:60]
        # Post-v2.0.5 D-P: add `tell me about X` as a fourth
        # recovery option. Same sibling-widening as D-N (which added
        # it to ``render_find_by_title`` no-results). `tell me about`
        # combines fuzzy title-index lookup with a RAG fallback when
        # no exact title hits, so it's a distinct signal from the
        # pure ``find article titled X`` title-only path — worth
        # both, since the caller may have a typo (title-index
        # recovers) or a paraphrase (RAG recovers).
        return (
            f"**Article not found: `{entry_path}`**\n\n"
            f"`{op_label} {entry_path}` failed: {err}\n\n"
            "**Try one of these to recover:**\n"
            f"- `suggestions for {recovery_path}` — autocomplete to "
            "catch typos / partial names\n"
            f"- `find article titled {entry_path}` — title-index "
            "lookup with fuzzy fallback\n"
            f"- `search for {entry_path}` — full-text search\n"
            f"- `tell me about {entry_path}` — fuzzy title-index "
            "lookup with RAG fallback when no exact title matches\n"
        )

    def _resolve_natural_language_path(
        self, zim_file_path: str, entry_path: str
    ) -> str:
        """A11 E1 (post-a10): probe the title index for ``entry_path``
        and return the canonical title-resolved path when one exists.

        ``show structure of List of common misconceptions`` used to
        error with ``Cannot find entry`` because the backend takes an
        exact path (with underscores), not a free-form title. D2 in
        a10 added this title-resolution step to ``_handle_related``;
        E1 extends the same pattern to every handler that resolves an
        entry path from natural language: structure, table of
        contents, links in, summary of, get section, get article.

        Falls through to the literal ``entry_path`` when no canonical
        title-index hit exists, so callers passing the exact stored
        path (``List_of_common_misconceptions``) still get a direct
        lookup. ``min_score=0.8`` matches the typo-tolerant gate used
        elsewhere so the same single-edit typos that route through
        ``tell me about`` also route through these handlers.
        """
        if not entry_path:
            return entry_path
        try:
            promoted = find_title_match(
                self.zim_operations,
                zim_file_path,
                entry_path,
                min_score=0.8,
            )
        except Exception as e:
            logger.debug(
                "_resolve_natural_language_path: find_title_match failed for " "%r: %s",
                entry_path,
                e,
            )
            return entry_path
        if promoted is not None and promoted.get("path"):
            return str(promoted["path"])
        return entry_path

    def _handle_structure(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        """O6 (beta): the ``show structure`` operation returns a FLAT list
        of headings (with per-heading summaries in non-compact mode), while
        the sibling ``table of contents`` operation
        (:meth:`_handle_toc`) returns the same headings as a NESTED tree
        with parent/child links. Both are valid; small models tend to
        prefer ``show structure`` for "which sections exist" and
        ``table of contents`` for "give me the section hierarchy I can
        recurse into".
        """
        entry_path = params.get("entry_path")
        if not entry_path:
            return (
                "**Missing Article Path**\n\n"
                "Please specify which article you want the structure for.\n"
                "**Example**: 'structure of Biology' or "
                "'structure of \"C/Evolution\"'"
            )
        entry_path = self._resolve_natural_language_path(zim_file_path, entry_path)
        try:
            if options.get("compact", False):
                # Skip the per-heading ``preview`` field (~3000 chars each;
                # 10 sections × 3000 = 30k+ char response). Structure is for
                # navigation — knowing which sections exist is enough for an
                # LLM to choose where to drill in next via ``summary of <path>``
                # or ``get article <path>``. Drops the response from ~17k to
                # ~1-2k chars on a typical Wikipedia article.
                payload = self.zim_operations.get_article_structure_data(
                    zim_file_path, entry_path
                )
                return compact_renderers.compact_structure_payload(payload)
            return self.zim_operations.get_article_structure(zim_file_path, entry_path)
        except Exception as e:
            return self._render_not_found_recovery(entry_path, e, "show structure of")

    def _handle_toc(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        """O6 (beta): returns the article's heading set as a NESTED tree
        with ``children`` links per node, distinct from the FLAT
        :meth:`_handle_structure` listing. Use ``show structure`` for a
        single-pass scan; use ``table of contents`` when the caller
        wants to recurse into specific sub-trees.
        """
        entry_path = params.get("entry_path")
        if not entry_path:
            return (
                "**Missing Article Path**\n\n"
                "Please specify which article you want the TOC for.\n"
                "**Example**: 'table of contents for Biology' or "
                "'toc of \"C/Evolution\"'"
            )
        entry_path = self._resolve_natural_language_path(zim_file_path, entry_path)
        try:
            return self.zim_operations.get_table_of_contents(zim_file_path, entry_path)
        except Exception as e:
            # Post-v2.0.5 D-Q: ``_handle_toc`` was the one structure/content
            # handler that never routed through ``_render_not_found_recovery``
            # — an unknown TOC path raised ``OpenZimMcpArchiveError`` straight
            # up to ``handle_zim_query``'s generic ``**Error Processing
            # Query**`` block, the exact pre-a13 behavior the recovery
            # envelope was built to replace. Sibling of D-P (which widened
            # the shared envelope's recovery bullets); this brings the last
            # holdout handler onto that shared envelope.
            return self._render_not_found_recovery(
                entry_path, e, "table of contents for"
            )

    def _handle_summary(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        entry_path = params.get("entry_path")
        if not entry_path:
            return (
                "**Missing Article Path**\n\n"
                "Please specify which article you want a summary for.\n"
                "**Example**: 'summary of Biology' or "
                "'summarize \"C/Evolution\"'"
            )
        entry_path = self._resolve_natural_language_path(zim_file_path, entry_path)
        try:
            return self.zim_operations.get_entry_summary(
                zim_file_path,
                entry_path,
                options.get("max_words", 200),
                compact=options.get("compact", False),
            )
        except Exception as e:
            return self._render_not_found_recovery(entry_path, e, "summary of")

    def _handle_get_section(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        """Fetch a single named section out of an article.

        Closes the loop on the lead-section + TOC pattern in
        :meth:`_lead_with_toc`: an LLM that read ``"# Biology"`` plus a
        list of section titles can now request ``"section Evolution of
        Biology"`` and get just that section back instead of refetching
        the whole article. Resolves the section by case-insensitive
        match against ``get_article_structure_data`` headings, accepts a
        bare integer as a 1-indexed position into the heading list, and
        returns a "did you mean?" list if the requested name doesn't
        match any heading.
        """
        section_name = params.get("section_name", "").strip()
        entry_path = params.get("entry_path", "").strip()
        if not section_name or not entry_path:
            return (
                "**Missing Section Reference**\n\n"
                "Please specify both a section name and an article.\n"
                "**Examples**:\n"
                "- `section Evolution of Biology`\n"
                "- `the Cellular respiration section of Biology`\n"
                "- `section 3 of Biology` (numeric position)"
            )
        entry_path = self._resolve_natural_language_path(zim_file_path, entry_path)
        try:
            structure = self.zim_operations.get_article_structure_data(
                zim_file_path, entry_path
            )
        except Exception as e:
            return (
                f"**Could not load article `{entry_path}` for section lookup**\n\n"
                f"{sanitize_context_for_error(str(e))}"
            )
        headings = []
        if isinstance(structure, dict):
            for h in structure.get("headings") or []:
                if isinstance(h, dict) and h.get("text"):
                    headings.append(h)
        if not headings:
            return (
                f"**No sections found in `{entry_path}`**\n\n"
                f"Article has no parsable section headings — try "
                f"`tell me about {entry_path}` for the full body."
            )

        # Numeric reference: 1-indexed position into the heading list.
        # Accepts a bare digit string from the parser (we don't pre-cast
        # because the regex captures everything as text).
        target = None
        if section_name.isdigit():
            idx = int(section_name) - 1
            if 0 <= idx < len(headings):
                target = headings[idx]
        else:
            wanted = section_name.lower()
            for h in headings:
                if h.get("text", "").strip().lower() == wanted:
                    target = h
                    break
            if target is None:
                # Substring fallback — useful when the LLM truncates the
                # heading title from the TOC.
                for h in headings:
                    if wanted in h.get("text", "").strip().lower():
                        target = h
                        break

        if target is None:
            self._track("section_not_found")
            avail = "\n".join(
                f"- {h.get('text')}" for h in headings[:20] if h.get("text")
            )
            # D4 (beta): surface a "did you mean?" pointer. The structured
            # ``get_section`` operation already computes this via difflib
            # at ``zim/structure.py:644`` (Op5) but the natural-language
            # path was reimplementing section lookup against the
            # ``headings`` list and never queried that operation, so the
            # closest_match never reached the markdown surface. Compute
            # it locally against the same heading text list so the model
            # gets a direct retry path ("Did you mean 'Geography'?")
            # instead of being forced to scan the 20-line list.
            import difflib

            heading_texts = [
                h.get("text", "").strip() for h in headings if h.get("text")
            ]
            closest_matches = difflib.get_close_matches(
                section_name, heading_texts, n=1, cutoff=0.6
            )
            hint = f"Did you mean **{closest_matches[0]}**? " if closest_matches else ""
            return (
                f'**Section "{section_name}" not found in `{entry_path}`**\n\n'
                f"{hint}Available sections:\n{avail}"
            )

        # Delegate to ``get_section_data`` to slice the full section out
        # of the bundle's rendered markdown — ~500-1500 tokens, the
        # small-model sweet spot per Phase C #7. The heading's ``id``
        # matches the bundle section ``id`` 1:1 (both are derived from
        # the same ``bundle["sections"]`` list).
        #
        # Op3: when the query was phrased as ``narrow section X of Y``
        # (parser sets ``params["narrow"] = True``), scope the slice to
        # the heading itself — no nested H3/H4 children. Lets a small
        # model fetch just the H2 lead paragraphs without the whole
        # sub-tree spilling into the response.
        section_id = target.get("id") or ""
        include_subsections = not bool(params.get("narrow"))
        try:
            section = self.zim_operations.get_section_data(
                zim_file_path,
                entry_path,
                section_id,
                include_subsections=include_subsections,
            )
        except Exception as e:
            return (
                f"**Could not load section `{target.get('text')}` "
                f"from `{entry_path}`**\n\n"
                f"{sanitize_context_for_error(str(e))}"
            )
        if isinstance(section, dict) and section.get("error"):
            return (
                f'**Section "{target.get("text")}" in `{entry_path}` is empty**\n\n'
                f"This heading exists in the article structure but has "
                f"no content rendered. The article may have been "
                f"truncated by the backend; try `get article "
                f"{entry_path}` for the full body."
            )
        text: str = ""
        if isinstance(section, dict):
            raw = section.get("content_markdown")
            if isinstance(raw, str):
                text = raw.strip()
        if not text:
            return (
                f'**Section "{target.get("text")}" in `{entry_path}` is empty**\n\n'
                f"This heading exists in the article structure but has "
                f"no content rendered. The article may have been "
                f"truncated by the backend; try `get article "
                f"{entry_path}` for the full body."
            )
        # A11 E2 (post-a10): honor ``max_content_length`` when set.
        # Previously the section text was returned in full regardless
        # of the cap, so ``get section History of Berlin`` with
        # ``max_content_length=1500`` returned ~5800 chars. Trim to
        # the cap and append a one-line truncation footer so callers
        # know more content exists.
        max_len = options.get("max_content_length")
        full_len = len(text)
        truncated = False
        if isinstance(max_len, int) and max_len > 0 and full_len > max_len:
            truncated = True
            text = text[:max_len]
        self._track("section_returned")
        header = (
            f"# {target.get('text')}\n_From `{entry_path}` "
            f"(level {target.get('level', '?')} heading)_\n\n"
        )
        body = header + text
        if truncated:
            body = body + (
                f"\n\n_Section truncated at {len(text):,} chars "
                f"(was {full_len:,}). Re-run with a larger "
                f"`max_content_length` to see more._"
            )
        return body

    def _handle_links(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        entry_path = params.get("entry_path")
        if not entry_path:
            return (
                "**Missing Article Path**\n\n"
                "Please specify which article to extract links from.\n"
                "**Example**: 'links in Biology' or "
                "'links from \"C/Evolution\"'"
            )
        # Post-a19 P1-D2 (widened cross-tool guard): reject cursors
        # issued by a different cursor-emitting tool. The current
        # handler hardcodes offset=0 internally, but defending the
        # boundary keeps the guard consistent with the sibling
        # cursor-consuming handlers (``_handle_browse`` /
        # ``_handle_walk_namespace`` / ``_handle_search`` /
        # ``_handle_filtered_search``) so a future offset-reading
        # change can't silently regress into a cross-tool walk.
        tool_mismatch = self._cursor_tool_mismatch(options, "extract_article_links")
        if tool_mismatch is not None:
            return tool_mismatch
        entry_path = self._resolve_natural_language_path(zim_file_path, entry_path)
        try:
            if options.get("compact", False):
                # Wikipedia-scale articles like "Photosynthesis" produce
                # ~2,000 internal links and ~400 external in the legacy
                # response — at ~150 chars per link object that's ~36k char
                # JSON, ~9k tokens. In compact mode use a much tighter
                # default limit and render a flat markdown list of just
                # ``- text -> path`` per link, dropping the per-link object
                # shape entirely. Drops the response from ~36k to ~2k chars.
                #
                # P3-D6: bumped from 20 to 25 so hub articles return enough
                # context for a single agent turn without forcing the
                # immediate paging treadmill the live MCP sweep observed
                # (``links in Berlin`` returned 3 of 2,749 internal —
                # well below the limit set here, suggesting a downstream
                # narrowing path; the bump documents the simple-mode
                # default and keeps it well clear of the previous 20-link
                # convention).
                limit = options.get("limit") or 25
                # v2 Phase B: extract_article_links_data returns one category
                # per call. The compact view shows internal + external; fetch
                # both and pass merged data to the renderer.
                internal = self.zim_operations.extract_article_links_data(
                    zim_file_path, entry_path, limit=limit, offset=0, kind="internal"
                )
                external = self.zim_operations.extract_article_links_data(
                    zim_file_path, entry_path, limit=limit, offset=0, kind="external"
                )
                return compact_renderers.render_links(internal, external)
            return self.zim_operations.extract_article_links(zim_file_path, entry_path)
        except Exception as e:
            return self._render_not_found_recovery(entry_path, e, "links in")

    def _handle_binary(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        entry_path = params.get("entry_path")
        if not entry_path:
            return (
                "**Missing Entry Path**\n\n"
                "Please specify the path of the binary content.\n"
                "**Examples**:\n"
                "- 'get binary content from \"I/image.png\"'\n"
                "- 'extract pdf \"I/document.pdf\"'\n"
                "- 'retrieve image I/logo.png'\n\n"
                "**Tip**: Use `extract_article_links` to discover "
                "embedded media paths."
            )
        return self.zim_operations.get_binary_entry(
            zim_file_path,
            entry_path,
            options.get("max_size_bytes"),
            params.get("include_data", True),
        )

    def _handle_suggestions(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        partial_query = params.get("partial_query", "")
        if not partial_query:
            return (
                "**Missing Search Term**\n\n"
                "Please specify what you want suggestions for.\n"
                "**Example**: 'suggestions for bio' or "
                "'autocomplete \"evol\"'"
            )
        return self.zim_operations.get_search_suggestions(
            zim_file_path, partial_query, options.get("limit", 10)
        )

    def _handle_filtered_search(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        # A16 post-a16 D6: if the user wrote ``in namespace X`` but the
        # extractor (now strict) couldn't parse a valid single-letter
        # namespace, surface the same "Missing or Invalid Namespace"
        # guidance the sibling ``browse_namespace`` / ``walk_namespace``
        # tools produce. Pre-fix, ``search foo in namespace AB`` /
        # ``... 1`` / ``... _`` silently dropped the namespace filter
        # at the regex level and the backend returned ``No filtered
        # matches`` with no signal that the namespace itself was
        # invalid. Validate at the handler so the user gets the
        # specific input-error class.
        if params.get("namespace") is None and re.search(
            r"\bin\s+namespace\b", query, re.IGNORECASE
        ):
            # Post-v2.0.4 sweep pass-2: the embedded
            # ``<!-- intent=filtered_search cert=0.80 -->`` here
            # duplicated the dispatcher's auto-appended intent footer
            # at line 1017 (every string result gets ``intent={intent}
            # cert={confidence:.2f}`` from the parser's classification).
            # Sibling ``_handle_browse`` / ``_handle_walk_namespace``
            # missing-namespace envelopes never embedded it and rely on
            # the auto-append. Drop the embedded comment so the
            # response carries exactly one intent footer.
            return (
                "**Missing or Invalid Namespace**\n\n"
                "**Issue**: `search ... in namespace` needs a single "
                "namespace letter (A, C, M, W, etc.; case-insensitive).\n"
                "**Examples**:\n"
                "- `search Berlin in namespace C` — main content\n"
                "- `search Counter in namespace M` — archive metadata"
            )
        # Post-a19 P1-D2: reject cursors issued by a different
        # cursor-emitting tool. Pre-fix, a ``walk_namespace`` cursor
        # passed to ``search foo in namespace C`` was silently
        # decoded; ``options["offset"]`` got the walk cursor's
        # ``s.o`` and filtered search returned page-2-of-walk-offset
        # results instead of the search's page 1. The advanced
        # ``search_with_filters`` tool enforces tool-binding via
        # ``Cursor.decode(expected_tool=...)``; this restores it at
        # the simple-tools handler edge.
        tool_mismatch = self._cursor_tool_mismatch(options, "search_with_filters")
        if tool_mismatch is not None:
            return tool_mismatch
        search_query = params.get("query", query)
        limit = options.get("limit")
        offset = options.get("offset", 0)
        # Post-b1 P3-D1: build the original-case display form so the
        # backend's ``Found N filtered matches for "X"`` /
        # ``No filtered matches for "X"`` echoes show the caller's
        # casing. Same shape as the _handle_search hoisting above.
        pre_rewrite = (
            params.get("_pre_rewrite_query") if isinstance(params, dict) else None
        )
        display_query = (
            self._recase_from_original(search_query, pre_rewrite)
            if isinstance(pre_rewrite, str) and pre_rewrite
            else search_query
        )
        if options.get("compact", False):
            # Phase D sub-D-1: compact path gives us a structured payload
            # to rerank before rendering. The canonical-title-match splice
            # lives in ``search_with_filters_with_canonical_splice`` (legacy
            # path); compact mode skips it and lets the reranker handle
            # ordering — consistent with how _handle_search treats its
            # compact vs. legacy paths.
            payload: Dict[str, Any] = cast(
                Dict[str, Any],
                self.zim_operations.search_with_filters_data(
                    zim_file_path,
                    search_query,
                    params.get("namespace"),
                    params.get("content_type"),
                    limit,
                    offset,
                ),
            )
            payload = self._maybe_rerank_compact(
                payload=payload, query=search_query, limit=limit
            )
            # SearchWithFiltersResponse has the same core keys as SearchResponse
            # (query, total, page_info, results, done, next_cursor) so the
            # text formatter accepts it structurally.
            #
            # Post-b2 D4: pass ``filter_text`` so the compact filtered
            # echo reads ``Found N filtered matches for "X" (filters:
            # namespace=C)`` — matching the non-compact filtered
            # path's wording. Pre-fix, both paths shared the
            # unfiltered ``Found N matches for "X"`` line because
            # ``_format_search_text`` had no filter awareness.
            from .zim.search import _format_filter_text

            compact_filter_text = _format_filter_text(
                params.get("namespace"),
                params.get("content_type"),
            )
            return self.zim_operations._format_search_text(
                cast(SearchResponse, payload),
                display_query=display_query,
                filter_text=compact_filter_text or "",
            )
        # A11 post-a11 H2: route to the canonical-title-match-aware
        # variant so ``search for berlin in namespace C`` surfaces
        # the canonical ``Berlin`` article instead of dropping it
        # behind ``List of songs about Berlin``. Only fires at
        # offset=0 — see the wrapper for paging-stability rationale.
        return self.zim_operations.search_with_filters_with_canonical_splice(
            zim_file_path,
            search_query,
            params.get("namespace"),
            params.get("content_type"),
            limit,
            offset,
            display_query=display_query,
        )

    def _handle_get_article(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        entry_path = params.get("entry_path")
        if not entry_path:
            # If no specific path, strip common request words and use the
            # remainder as the entry path. Use the timeout-protected wrapper
            # so this stays consistent with the rest of the user-input regex
            # surface — the pattern itself is safe but the precedent isn't.
            try:
                cleaned_query = safe_regex_sub(
                    r"\b(get|show|read|display|fetch|article|entry|page)\b",
                    "",
                    query,
                    flags=re.IGNORECASE,
                ).strip()
            except RegexTimeoutError:
                cleaned_query = query.strip()
            # Post-v2.0.4 D-E sibling: peel a surrounding quote-pair so
            # ``get article ""`` / ``get article ''`` drop to the missing-
            # arg guard. Pre-fix the word-strip left the literal 2-char
            # quote pair, which the backend fuzzy-matched to the
            # ``Empty_string`` article at cert=0.75 (same silent-wrong-
            # answer shape as the post-v2.0.0 D-E sweep — that fix landed
            # on the extractor and the keyword-branch tail, but the
            # ``_handle_get_article`` word-strip recovery branch
            # regenerates the literal from ``query`` and bypasses it).
            cleaned_query = _strip_quote_pair(cleaned_query)
            if not cleaned_query:
                return (
                    "**Missing Article Path**\n\n"
                    "Please specify which article you want to read.\n"
                    "**Example**: 'get article Biology' or "
                    "'show \"C/Evolution\"'"
                )
            entry_path = cleaned_query
        # A11 E1: probe the title index so natural-language paths
        # like ``get article List of common misconceptions`` resolve
        # to the underscored canonical path. Post-v2.0.5 D-K: dropped
        # the original ``" " in entry_path`` gate so single-token
        # tails (``get article Biology``) also route through the
        # probe — the parser lowercases all entry_paths (Rule 1) and
        # most articles in ``wikipedia_en_all_maxi_2026-02`` don't
        # ship a lowercase redirect, so the direct path lookup
        # silently failed for ``biology`` even though the title
        # index resolves it to ``Biology`` at score 1.00. Sibling
        # handlers (structure / summary / get_section / links)
        # already probe unconditionally; this restores parity. The
        # probe is a single Xapian title-index lookup with
        # ``min_score=0.8``; on a miss it returns ``entry_path``
        # unchanged, so namespace-prefixed paths (``A/Biology``)
        # still fall through to the direct lookup at zero behaviour
        # cost.
        entry_path = self._resolve_natural_language_path(zim_file_path, entry_path)
        try:
            return self.zim_operations.get_zim_entry(
                zim_file_path,
                entry_path,
                options.get("max_content_length"),
                options.get("content_offset", 0),
                compact=options.get("compact", False),
            )
        except Exception as e:
            return self._render_not_found_recovery(entry_path, e, "get article")

    def _handle_search(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> Union[str, "_HandlerResult"]:
        """Route a search-intent query to the appropriate backend call.

        In ``compact=True`` mode, uses the structured ``search_zim_file_data``
        variant so we can inspect the payload before rendering.  When the
        payload has zero results, returns a ``_HandlerResult`` whose
        ``reason`` / ``suggestions`` fields are plumbed into the
        ``handle_zim_query`` footer step — the footer then renders the
        empty-result suggestion variant (``> No results. Try: …``) instead
        of the legacy prose block ("**Try one of these:**").

        In ``compact=False`` mode, delegates straight to the legacy
        ``search_zim_file`` string surface so existing callers see no change.

        D6 (v2.0.0a9): on first-page searches, splice in a title-index
        score-1.0 hit when the top BM25 result isn't a strong match
        for the query (``search for Einstein`` → ``List of things
        named after Albert Einstein`` instead of ``Albert_Einstein``).
        Only applied at ``offset=0`` so paged results stay stable.
        """
        # Post-a19 P1-D1: reject cursors issued by a different
        # cursor-emitting tool. Pre-fix, a ``walk_namespace`` /
        # ``browse_namespace`` cursor passed to ``search for X`` was
        # silently decoded; ``options["offset"]`` got the cursor's
        # ``s.o`` and search returned page-2-of-cursor-offset results
        # instead of page 1 of the search. The advanced
        # ``search_zim_file`` tool enforces tool-binding via
        # ``Cursor.decode(expected_tool=...)``; this restores it at
        # the simple-tools handler edge. Same shape as the post-a18
        # P1-D4 fix that landed for browse / walk_namespace.
        tool_mismatch = self._cursor_tool_mismatch(options, "search_zim_file")
        if tool_mismatch is not None:
            return tool_mismatch
        search_query = params.get("query", query)
        limit = options.get("limit")
        offset = options.get("offset", 0)
        # Post-b1 P3-D1: build the original-case display form once.
        # Passed to backend renderers so user-facing echoes
        # (``Found N matches for "X"`` / ``No search results found
        # for "X"``) reflect the caller's casing instead of Rule 1's
        # lowercased extraction. Search matching uses ``search_query``
        # unchanged — Xapian is case-insensitive.
        pre_rewrite = (
            params.get("_pre_rewrite_query") if isinstance(params, dict) else None
        )
        display_query = (
            self._recase_from_original(search_query, pre_rewrite)
            if isinstance(pre_rewrite, str) and pre_rewrite
            else search_query
        )

        if options.get("compact", False):
            # Use the dict variant so we can inspect _meta.suggestions on
            # empty results and surface them via the footer instead of the
            # legacy prose block.
            payload = self.zim_operations.search_zim_file_data(
                zim_file_path, search_query, limit, offset
            )
            # Phase B: ``total`` replaces ``total_results``.
            if payload.get("total", 0) == 0:
                # Let handle_zim_query's footer step render the structured
                # suggestion footer (format_footer empty-result variant).
                # Post-b1 P2-D2: ``display_query`` was hoisted above
                # for use by the backend renderers (P3-D1); reuse it
                # here so the no-results echo also reflects the
                # caller's original casing.
                # Post-b2 D2: invoke the rerank apply so its no-results
                # / not-installed counter bumps even on this early-
                # return path. Without this, the in-band
                # ``<!-- reranker=... -->`` comment is silently
                # suppressed for every no-results search — the b1
                # D-1 telemetry contract promised the comment on
                # every multi-token search. ``_maybe_rerank_compact``
                # is a no-op on empty ``results`` aside from the
                # counter bump (the rerank singleton is also cached,
                # so the call is cheap).
                self._maybe_rerank_compact(
                    payload=cast(Dict[str, Any], payload),
                    query=search_query,
                    limit=limit,
                )
                meta = payload.get("_meta", {})
                # Post-v2.0.5 D-L: inject a cross-intent
                # ``tell me about {display_query}`` suggestion into
                # the meta footer so the compact-mode caller sees
                # the same structured-topic-lookup escape hatch the
                # non-compact ``_format_search_text`` body offers
                # (``zim/search.py:779``). Pre-fix, the compact
                # footer only carried backend-derived suggestions
                # (alt_spelling / alt_archive) when present, and
                # fell through to the terse one-liner
                # ``> No results. Try a shorter or differently-
                # spelled query.`` when they were absent — leaving
                # callers without a pointer to the more powerful
                # ``tell me about X`` path. Appended (not
                # prepended) so the typo-catching ``suggestions for
                # X`` hint stays first when the backend supplied
                # it.
                truncated = display_query[:30]
                backend_suggestions = list(meta.get("suggestions") or [])
                backend_suggestions.append(
                    {"type": "cross_intent_tell_me_about", "value": truncated}
                )
                return _HandlerResult(
                    body=f'No results for "{display_query}".',
                    reason=meta.get("reason", "0_hits"),
                    suggestions=backend_suggestions,
                )
            # D6: promote canonical title-index hit if the top BM25 hit
            # isn't a strong title match. Only on first page. The splice
            # helper accepts/returns ``Dict[str, Any]`` so it can mutate
            # arbitrary keys; ``SearchResponse`` is its precise wire shape
            # and the cast bridges the TypedDict / dict narrowing gap mypy
            # can't infer through assignment.
            if offset == 0:
                payload = cast(
                    SearchResponse,
                    self._splice_title_match_into_search(
                        cast(Dict[str, Any], payload),
                        zim_file_path,
                        search_query,
                    ),
                )
            # Phase D sub-D-1: cross-encoder rerank if available.
            payload = cast(
                SearchResponse,
                self._maybe_rerank_compact(
                    payload=cast(Dict[str, Any], payload),
                    query=search_query,
                    limit=limit,
                ),
            )
            # Non-empty results: render via the legacy text formatter so the
            # markdown shape is identical to the non-compact path.
            # Post-b1 P3-D1: pass display_query so ``Found N matches
            # for "X"`` echoes in the caller's original case.
            return self.zim_operations._format_search_text(
                payload, display_query=display_query
            )

        # compact=False: unchanged legacy path. Title promotion is
        # applied in compact mode only (the default surface for
        # ``zim_query``). Legacy callers of the non-compact rendered
        # string keep byte-identical output, including the original
        # BM25 ranking.
        # Post-b1 P3-D1: pass display_query so non-compact callers
        # also get the original-case echo.
        return self.zim_operations.search_zim_file(
            zim_file_path,
            search_query,
            limit,
            offset,
            display_query=display_query,
        )

    @staticmethod
    def _stable_demote_list_articles(
        results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """A11 post-a11 H3: stable-partition list / discography / catalog
        articles to the bottom of a search results list.

        Reuses the same predicate the synthesize ranker uses
        (:func:`openzim_mcp.synthesize._is_list_article`) so plain
        ``search`` and ``synthesize`` agree on which hits are catalog-
        shaped. Pre-fix, ``search for cats`` returned
        ``Rephlex_Records_discography`` at rank 2 — the synthesize-
        layer Opp2 demote was applied only inside ``synthesize_query``;
        plain search left the discography in place. The basic-search
        splice now applies the same demote so the two surfaces line up.

        Stable: preserves order within both partitions so the splice's
        canonical promotion + Xapian's underlying ranking are
        unchanged for non-list hits.
        """
        if not results:
            return results
        from openzim_mcp.synthesize import _is_list_article

        non_list = [r for r in results if not _is_list_article(r)]
        list_hits = [r for r in results if _is_list_article(r)]
        if not list_hits:
            return results
        return non_list + list_hits

    def _splice_title_match_into_search(
        self,
        payload: Dict[str, Any],
        zim_file_path: str,
        search_query: str,
    ) -> Dict[str, Any]:
        """Prepend the title-index score-1.0 hit to ``payload['results']``
        when the BM25 top hit isn't a strong title match. Then stable-
        demote any list / discography / catalog articles to the
        bottom of the page (A11 post-a11 H3) so the splice and the
        synthesize ranker agree on which hits are catalog-shaped
        noise.

        Mutates and returns ``payload`` — callers treat the response as
        new-shape regardless of caching upstream because the splice is
        applied per-request after the cache read.
        """
        results = payload.get("results") or []
        if not results:
            return payload
        # Pre-splice demote: regardless of whether the canonical
        # title-match probe fires, push catalog-shape hits below the
        # narrative articles so ``search for cats`` stops surfacing
        # Rephlex Records discography at rank 2 even when no title
        # promotion happens.
        results = self._stable_demote_list_articles(cast(List[Dict[str, Any]], results))
        payload["results"] = results
        top = results[0]
        if not isinstance(top, dict):
            return payload
        top_path = str(top.get("path", ""))
        top_title = str(top.get("title", top_path.replace("_", " ")))
        if is_strong_title_match(search_query, top_path, top_title):
            return payload
        promoted = find_title_match(self.zim_operations, zim_file_path, search_query)
        if promoted is None:
            return payload
        promoted_path = promoted["path"]
        existing_paths = {
            str(r.get("path", "")) for r in results if isinstance(r, dict)
        }
        if promoted_path in existing_paths:
            # Reorder: move the canonical to position 0 without dup.
            reordered = [
                r
                for r in results
                if not (isinstance(r, dict) and str(r.get("path", "")) == promoted_path)
            ]
            promoted_existing = next(
                r
                for r in results
                if isinstance(r, dict) and str(r.get("path", "")) == promoted_path
            )
            payload["results"] = [promoted_existing, *reordered]
            return payload
        # Build a synthetic result row matching the existing shape — no
        # snippet text since the title-index path doesn't compute one;
        # downstream renderers tolerate missing snippets and show a
        # clear "title match" indicator.
        synthetic = {
            "path": promoted_path,
            "title": promoted["title"],
            "snippet": "(canonical title match)",
        }
        # DD4 (beta, second pass): trim back to the requested limit so
        # the splice doesn't push the result count off by one. The
        # previous prepend produced 4 results for ``limit=3``; the
        # rendered header then read "showing 1-4" with limit=3, a
        # contract inconsistency. Drop the last BM25 result to make
        # room for the canonical splice; the dropped result is the
        # lowest-ranked of the BM25 set, so the displacement carries
        # the least information loss.
        page_info = payload.get("page_info") or {}
        requested_limit = page_info.get("limit") or len(results)
        spliced = [synthetic, *results][:requested_limit]
        payload["results"] = spliced
        # Keep ``page_info.returned_count`` consistent with the spliced
        # length so renderers don't claim to show more rows than they
        # actually do.
        if isinstance(page_info, dict):
            page_info["returned_count"] = len(spliced)
            payload["page_info"] = page_info
        return payload

    def _promote_topic_via_title_index(
        self, zim_file_path: str, topic: str
    ) -> Optional[Dict[str, Any]]:
        """Phase F: thin wrapper delegating to ``topic_preprocessing``.

        See :func:`openzim_mcp.topic_preprocessing.promote_topic_via_title_index`
        for the Z3/Z4/OPP-1 pass-order documentation. Behavior is byte-identical
        to the pre-extraction implementation (proven by the Gate 0a parity
        diff-test in ``tests/dispatch_eval/test_promotion_extraction_parity.py``
        replaying the b1→b13 probe set against a live Wikipedia ZIM).
        """
        from openzim_mcp.topic_preprocessing import promote_topic_via_title_index

        return promote_topic_via_title_index(
            zim_operations=self.zim_operations,
            zim_file_path=zim_file_path,
            topic=topic,
        )

    @staticmethod
    def _swap_tell_me_about_recovery_hint(text: str, topic: str) -> str:
        """Post-v2.0.4 D-J: when ``_handle_tell_me_about`` falls back
        to the search backend's rendered no-results output, the shared
        ``_format_search_text`` recovery hints (zim/search.py:774-782)
        suggest ``tell me about {topic}`` — which is exactly what the
        caller just tried. Swap that bullet for a ``find article
        titled {topic}`` hint (title-index fuzzy lookup) that's
        genuinely a different recovery path.

        Implemented as a narrow string-replace at the handler edge
        rather than parameterizing the shared formatter so the
        search-backend recovery wording stays canonical for direct
        ``search for X`` callers (where the ``tell me about`` cross-
        intent nudge is still useful). The replace is canonical-source
        pinned by ``TestTellMeAboutNoResultsRecoveryNotCircular`` —
        future search.py wording changes need to update the swap in
        tandem.
        """
        truncated = topic[:30]
        circular = (
            f"- `tell me about {truncated}` — structured topic "
            f"lookup with auto article fetch"
        )
        replacement = (
            f"- `find article titled {truncated}` — title-index "
            f"lookup with fuzzy fallback"
        )
        return text.replace(circular, replacement)

    def _handle_tell_me_about(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        """Search for a topic and inline the top article body when it's a
        strong title match.

        Triggered by explicit "tell me about X" / "who is X" / "what is X" /
        "describe X" phrasings, and by the bare-topic fallback in
        ``IntentParser.parse_intent`` (e.g. ``"Martin Luther King Jr."``).

        Strategy:
          1. Run a small (limit=3) structured search for the topic.
          2. If there are no results → render the empty-search response
             so the caller still gets a clear "nothing found" message.
          3. If the top hit's title or path is a strong match for the topic
             (token-list equality or prefix in either direction) →
             fetch the article body and return it as the response.
          4. Otherwise → fall through to the rendered search response so
             the caller sees the multiple weak matches and can disambiguate.

        Saves the model an entire agentic round trip on the common
        topic-lookup case ("who is X" today is two tool calls: search,
        then get_article).
        """
        topic = (params.get("topic") or query).strip()
        if not topic:
            topic = query
        # Sub-D-2 rule 4 may have stashed a structured (entity,
        # attribute) pair in params during parse_intent. When present,
        # prefer it over re-extracting from the topic — rule 4 already
        # did the work and the structured fields are more reliable.
        decomposition_hint = params.get("decomposition_hint")
        if isinstance(decomposition_hint, dict):
            entity_hint = decomposition_hint.get("entity")
            if entity_hint:
                # Use the hinted entity as the topic to look up. The
                # attribute hint (decomposition_hint["attribute"]) is
                # preserved in `params` for downstream consumers that
                # may want to focus extraction on a specific attribute.
                # No active consumer today — that's a future-work hook.
                topic = entity_hint
        # Post-b2 D3: when parse_intent didn't attach a decomposition
        # hint, retry Rule 4's POSSESSIVE shape on the EXTRACTED
        # topic. Rule 4's ``_POSSESSIVE_RE`` / ``_X_OF_Y_RE`` are
        # ``^...$``-anchored and run against the FULL query at
        # parse_intent time. For ``tell me about <entity>'s
        # <attr>`` shapes the verb prefix prevented the match; the
        # corrected possessive form arrived here intact and the
        # downstream auto-resolve silently picked the trailing
        # token. Sibling shape: ``Photosythesis's reproduction``
        # (after Rule 2 → ``photosynthesis's reproduction``) used
        # to return the ``Reproduction`` article instead of
        # ``Photosynthesis``.
        #
        # Scope narrowed to the possessive shape (``X's Y``) only.
        # The ``X of Y`` shape is intentionally NOT retried at the
        # handler edge because the existing title-promotion path
        # already resolves canonical multi-word titles (``lord of
        # the rings`` → ``The_Lord_of_the_Rings``); a handler-side
        # retry would re-introduce the pre-b1-P1-D3 family of
        # decomposition mishaps for non-canonical ``X of Y``
        # queries. Possessive shapes are unambiguous: ``<entity>'s
        # <attribute>`` is grammatically a noun-phrase about the
        # entity.
        elif topic and "'s " in topic.lower():
            _title_probe = self._build_title_probe(
                self._probe_archive_path(zim_file_path)
            )
            _, _retry_hint = IntentParser._decompose_x_of_y(
                topic.lower(), title_probe=_title_probe
            )
            if isinstance(_retry_hint, dict):
                _retry_entity = _retry_hint.get("entity")
                if _retry_entity:
                    topic = _retry_entity
                    # Surface the hint so downstream consumers see
                    # the same shape Rule 4 would have produced.
                    params["decomposition_hint"] = _retry_hint
        # A16 post-a16 D3: a topic like ``M/Title`` or ``c/Berlin`` is a
        # ZIM namespace path the caller pasted into ``tell me about``.
        # The downstream search either silently strips the prefix (libzim
        # lookup-by-title is namespace-tolerant) and returns the canonical
        # ``Title`` / ``Berlin`` article, or fuzzy-resolves to a wrong
        # article entirely. Mirror the same guard
        # ``_handle_find_by_title`` uses so the caller gets the right
        # tool (``get article M/Title``) instead of a silent wrong
        # answer. Accept both uppercase and lowercase first letter —
        # libzim namespace lookups are case-insensitive (see
        # ``openzim_mcp/zim/namespace.py``).
        # Pass-2 self-audit: require the suffix to be ≥3 chars so real
        # short article titles like ``A/B`` (testing methodology) or
        # ``a/b`` aren't redirected as namespace paths. Wikipedia
        # ZIM namespace keys are always ≥3 chars (Title, Counter,
        # Creator, mainPage, favicon, ...).
        if (
            len(topic) >= 4
            and topic[0].isascii()
            and topic[0].isalpha()
            and topic[1] == "/"
            and len(topic[2:].strip()) >= 3
        ):
            normalized = topic[0].upper() + topic[1:]
            return (
                "**Namespace Path, Not a Topic**\n\n"
                f"`{topic}` looks like a ZIM namespace path. "
                "``tell me about`` runs a title-search and would "
                "either drop the namespace prefix or fuzzy-resolve "
                "to an unrelated article.\n"
                "**Try one of**:\n"
                f"- `get article {normalized}` — direct path lookup\n"
                f"- `tell me about {topic[2:].strip()}` — "
                "title search on the bare name\n"
                "<!-- intent=namespace_path_redirect cert=0.95 -->"
            )
        # A16 post-a16 D9: callers often paste a ZIM path form
        # (``Sun_(disambiguation)``, ``Apollo_11``) into ``tell me about``,
        # but the title index is whitespace-tokenised and the search
        # ranker scores ``Sun_(disambiguation)`` as a single literal
        # token (zero hits) rather than ``Sun (disambiguation)``
        # (matches via title-index). Normalise underscores to spaces
        # so pasted paths resolve the same way the equivalent title
        # form does. Real article titles do not contain underscores
        # on Wikipedia, so the normalisation is lossless.
        if "_" in topic:
            topic = topic.replace("_", " ").strip()
        # A16 post-a16 D8: when the topic explicitly names a disambig
        # page (``Berlin (disambiguation)``, ``Apollo 11
        # (disambiguation)``), the fuzzy title-search ranks unrelated
        # articles containing the bare word ``disambiguation`` (e.g.
        # ``Word-sense_disambiguation``) above the requested
        # ``<X>_(disambiguation)`` path. Probe the title index for an
        # exact ``<X>_(disambiguation)`` path and fetch it directly
        # when it exists. Same path-existence helper as D4.
        if topic.lower().endswith(" (disambiguation)"):
            base = topic[: -len(" (disambiguation)")].strip()
            if base:
                resolved = self._probe_disambig_twin(
                    zim_file_path, base.replace(" ", "_")
                )
                if resolved is not None:
                    body = self._fetch_topic_article_body(
                        zim_file_path,
                        resolved,
                        options.get("max_content_length") or 8000,
                        options,
                    )
                    if body is not None:
                        return (
                            f"# {topic}\n\n"
                            f"_Source: `{resolved}`_\n\n"
                            f"{body}\n"
                            "<!-- intent=tell_me_about cert=0.95 -->"
                        )
                # Fall through to fuzzy search if the title-index probe
                # missed — the disambig auto-pick downstream will still
                # try its best.
        # Cap the search at 3 results: the auto-fetch path either inlines
        # the top article (in which case we don't render the others — see
        # below) or falls through to a plain rendered search, where 3 hits
        # is enough to disambiguate without flooding the response. A
        # caller-supplied ``limit`` only takes effect when it asks for
        # *fewer* than 3 hits.
        search_limit = min(options.get("limit") or 3, 3)
        max_content_length = options.get("max_content_length") or 8000

        try:
            payload = self.zim_operations.search_zim_file_data(
                zim_file_path, topic, search_limit, 0
            )
        except Exception:
            # If the structured search fails, fall through to the legacy
            # rendered search so the caller still gets useful output.
            return self.zim_operations.search_zim_file(
                zim_file_path, topic, search_limit, 0
            )

        results = payload.get("results", []) if isinstance(payload, dict) else []
        if not results:
            return self._swap_tell_me_about_recovery_hint(
                self.zim_operations.search_zim_file(
                    zim_file_path, topic, search_limit, 0
                ),
                topic,
            )

        top = results[0]
        top_path = top.get("path", "")
        top_title = top.get("title", "")
        if not is_strong_title_match(topic, top_path, top_title):
            promoted = self._promote_topic_via_title_index(zim_file_path, topic)
            if promoted is None:
                return self._swap_tell_me_about_recovery_hint(
                    self.zim_operations.search_zim_file(
                        zim_file_path, topic, search_limit, 0
                    ),
                    topic,
                )
            top_path = promoted["path"]
            top_title = promoted["title"]

        # Disambiguation: if MULTIPLE search hits strong-match the topic,
        # there's a real ambiguity (Mercury → planet/element/mythology;
        # Java → island/programming; Apollo → spacecraft/program/god).
        # Auto-fetching the top one in that case is silently picking
        # *one* meaning — the caller never learns the alternatives
        # existed. Surface them instead so the LLM can pick. Tested
        # against the disambiguation-page case AND the natural multiple
        # similarly-named-articles case.
        strong_matches = [
            r
            for r in results
            if isinstance(r, dict)
            and is_strong_title_match(topic, r.get("path", ""), r.get("title", ""))
        ]
        # A11 C2 (post-a10 review, second pass + third pass): ``tell
        # me about Apollo 11`` used to disambiguate between
        # ``Apollo_11_anniversaries``,
        # ``Apollo_11_lunar_sample_display`` and
        # ``Apollo_11_goodwill_messages`` — three weak matches that
        # extend the topic, with the canonical ``Apollo_11`` article
        # itself hidden because Xapian's top-3 didn't include it.
        # Probe the title index for the exact-topic canonical BEFORE
        # the disambig check fires so the canonical is always
        # considered.
        #
        # Gate the probe so it only runs when it can actually help:
        #
        #   (a) ``len(strong_matches) >= 2`` — the disambig page
        #       would otherwise render; the probe lets the canonical
        #       in alongside the others.
        #   (b) ``len(strong_matches) == 1`` AND the lone match is a
        #       disambig twin — third-pass fix: search returned
        #       ``Berlin_(disambiguation)`` as the only strong match,
        #       the canonical ``Berlin`` wasn't in Xapian's top-3,
        #       and the early ``is_strong_title_match`` check
        #       accepts the twin via candidate-extends-topic so the
        #       promotion-above branch never fired. Without this
        #       clause the handler fetches the disambig page instead
        #       of the canonical city article.
        #
        # When there are 0 strong matches the handler has already
        # fallen through to plain search.
        #
        # A11 post-a11 C1: extended the gate to also fire when the
        # lone strong match is an "extends-topic" hit (not a token-
        # equality match). The pre-fix assumption — "1 non-twin
        # strong match → auto-fetch is correct" — silently broke for
        # ``tell me about France``: Xapian's top hit was
        # ``France_national_football_team_results_(2000–2019)``,
        # which strong-matched ``France`` via the candidate-extends-
        # topic rule (``cand_tokens[:1] == ("france",)``). The
        # canonical ``France`` article exists in the title index but
        # was never probed, so the football article was returned
        # silently. The probe now fires for this case too; a sibling
        # auto-pick (below) prefers the canonical when its tokens
        # equal the topic exactly. Mercury / Apollo / Java / DNA
        # forks are unaffected — those already have a token-equality
        # canonical in their strong-match set.
        topic_tokens = tuple(_TOKEN_RE.findall(topic.lower()))
        gate_for_disambig_render = len(strong_matches) >= 2
        gate_for_lone_twin = (
            len(strong_matches) == 1
            and isinstance(strong_matches[0], dict)
            and self._is_disambig_twin_path(str(strong_matches[0].get("path") or ""))
        )
        gate_for_lone_extends_topic = (
            len(strong_matches) == 1
            and isinstance(strong_matches[0], dict)
            and topic_tokens
            and tuple(
                _TOKEN_RE.findall(
                    str(
                        strong_matches[0].get("title")
                        or strong_matches[0].get("path")
                        or ""
                    ).lower()
                )
            )
            != topic_tokens
        )
        if (
            gate_for_disambig_render
            or gate_for_lone_twin
            or gate_for_lone_extends_topic
        ):
            canonical = self._promote_topic_via_title_index(zim_file_path, topic)
            if canonical is not None:
                canonical_path = canonical.get("path", "")
                present_paths = {
                    str(r.get("path", ""))
                    for r in strong_matches
                    if isinstance(r, dict)
                }
                if canonical_path and canonical_path not in present_paths:
                    canonical_row: Dict[str, Any] = {
                        "path": canonical_path,
                        "title": canonical.get("title") or top_title,
                        "snippet": "(canonical title match)",
                    }
                    # ``SearchHit`` is a TypedDict; cast satisfies
                    # the type-checker since the synthetic row carries
                    # only the keys downstream consumers actually read.
                    strong_matches = cast(Any, [canonical_row, *strong_matches])
        # A11 C1 + Opp1: when the disambig set contains exactly the
        # ``Foo`` article AND its ``Foo (disambiguation)`` twin, the
        # caller almost always wants the canonical ``Foo``. Drop the
        # disambig-suffixed twin from the strong-match list (it
        # remains discoverable via the "may also refer to" hint we
        # append in the canonical's footer below).
        canonical_match = self._auto_pick_canonical_over_disambig_twin(
            topic, cast(List[Dict[str, Any]], strong_matches)
        )
        # A11 post-a11 C1 (sibling rule): if the strong-match set is
        # ``[canonical-with-topic-tokens, ..._extends-topic-only]`` —
        # i.e. one entry whose title equals the topic exactly AND zero
        # disambig twins AND zero other token-equality matches — pick
        # the canonical and surface the others as a "may also refer
        # to" hint. Without this, ``tell me about France`` (after the
        # gate change above prepends the canonical) would render a
        # 2-way fork between ``France`` and the football team article.
        # Apollo / Mercury / Java / DNA are unaffected — those have
        # multiple token-equality matches (e.g. ``Apollo`` AND
        # ``Apollo (disambiguation)``), so this rule sees more than
        # one canonical and returns None to let the disambig render.
        if canonical_match is None:
            canonical_match = self._auto_pick_canonical_over_extends_topic(
                topic, cast(List[Dict[str, Any]], strong_matches)
            )
        disambig_twin_path: Optional[str] = None
        related_extends_paths: List[str] = []
        if canonical_match is not None:
            canonical_path = str(canonical_match.get("path") or "")
            top_path = canonical_match["path"]
            top_title = canonical_match.get("title") or top_title
            # A11 F8 / Opp5: record the disambig twin path so we can
            # surface it as a footer hint on the returned article body.
            # The caller still learns the disambiguation exists even
            # though we auto-picked the canonical.
            for m in strong_matches:
                if isinstance(m, dict) and self._is_disambig_twin_path(
                    str(m.get("path") or "")
                ):
                    disambig_twin_path = str(m["path"])
                    break
            # A16 post-a16 D4: when the strong-match scan didn't see a
            # disambig twin, explicitly probe ``<canonical>_(disambiguation)``
            # via the title index. The pre-a16 code relied entirely on
            # the search engine surfacing the twin in its top hits, but
            # for canonicals with many prefix-sibling sub-articles (Sun
            # / Sun_Ra_..., Apollo_11 / Apollo_11_anniversaries, Java /
            # Java_Community_Process) the search engine ranks the
            # sub-articles higher than the disambig page (the disambig
            # title carries the extra ``(disambiguation)`` token which
            # hurts its fuzzy score against the bare topic). The miss
            # then routed the footer to ``May also refer to: <sub-
            # article>`` wording that mis-frames sub-articles as
            # alternative meanings. A direct title-index probe is one
            # in-memory hit per resolve and short-circuits the
            # mis-framing.
            if disambig_twin_path is None:
                disambig_twin_path = self._probe_disambig_twin(
                    zim_file_path, canonical_path
                )
            # A11 post-a11 C1: when the auto-pick is the
            # canonical-over-extends-topic case (Apollo 11 over
            # anniversaries / lunar / goodwill, France over the
            # football article), surface the other strong matches as a
            # short "may also refer to" hint so the caller can still
            # reach the variants without paying a follow-up search call.
            for m in strong_matches:
                if not isinstance(m, dict):
                    continue
                m_path = str(m.get("path") or "")
                if m_path and m_path != canonical_path:
                    if not self._is_disambig_twin_path(m_path):
                        related_extends_paths.append(m_path)
        elif len(strong_matches) >= 2:
            self._track("disambiguation_returned")
            # Post-b1 P2-D1: pass the pre-rewrite original-case query
            # so the disambig heading echoes the caller's casing
            # instead of Rule 1's lowercased topic.
            disambig_original = (
                params.get("_pre_rewrite_query") if isinstance(params, dict) else None
            )
            return self._render_disambiguation(
                topic,
                strong_matches,
                original_query=(
                    disambig_original if isinstance(disambig_original, str) else None
                ),
            )

        # Subject-attribute decomposition (2026-05-18): when the
        # original topic carried a subject category hint
        # (``musician``, ``actor``, ``notable people``, ...) and the
        # resolved entity's article has a section that maps to that
        # hint, return the section body instead of the (often empty)
        # lead. Motivating case: ``famous musician from big rapids
        # michigan`` from the 2026-05-18 live transcript.
        # Post-b1 P1-D2: thread the original-case query through so the
        # nested soft-connector footer can recase its entity references.
        original_query_for_subject = (
            params.get("_pre_rewrite_query") if isinstance(params, dict) else None
        )
        subject_section_result = self._maybe_render_subject_section(
            zim_file_path=zim_file_path,
            topic=topic,
            top_path=top_path,
            top_title=top_title,
            options=options,
            original_query=(
                original_query_for_subject
                if isinstance(original_query_for_subject, str)
                else None
            ),
        )
        if subject_section_result is not None:
            return subject_section_result

        article_body = self._fetch_topic_article_body(
            zim_file_path, top_path, max_content_length, options
        )
        if article_body is None:
            # Article fetch failed — degrade gracefully to plain search.
            return self.zim_operations.search_zim_file(
                zim_file_path, topic, search_limit, 0
            )
        result = (
            f"# {top_title or topic}\n\n"
            f"_Source: `{top_path}`_\n\n"
            f"{article_body}"
        )
        # A15 post-a15: when the resolved article body IS itself a
        # disambiguation page (Mercury, Java, etc. — bare titles that
        # never had a dedicated article and live as disambig at the
        # canonical path), both trailing footers are misleading:
        # ``Note: this topic also has a disambiguation page`` points
        # back at the same content, and ``May also refer to: <one
        # extends-topic sibling>`` names a single random match while
        # the body itself already enumerates dozens of alternates. The
        # canonical-vs-disambig auto-pick that produced these hints
        # was designed for cases like Berlin (canonical city article,
        # separate Berlin_(disambiguation) twin) — when the auto-pick
        # is the disambig page itself, drop them. Detection re-uses
        # the same pre-H2 ``may refer to`` test the lead-with-TOC cut
        # uses, on the fetched body.
        h2_in_body = self._first_article_h2(article_body)
        pre_h2_in_body = (
            article_body[: h2_in_body.start()].rstrip()
            if h2_in_body
            else article_body.rstrip()
        )
        body_is_disambig_page = self._is_disambig_lead(pre_h2_in_body)
        # Post-b11 Sub-pattern C: when the auto-picked canonical's body
        # IS a disambig page AND the topic has 2+ meaningful (non-stop-
        # word) tokens, the user clearly wanted a specific article (the
        # `Lincoln slavery emancipation` → `Lincoln` disambig case at
        # v2.0.0b11). Fall back to plain BM25 search so the LLM sees
        # the ranked specific articles instead of the disambig list.
        # Single-content-token topics (``tell me about Lincoln``) are
        # the bare-head case and legitimately want the disambig — the
        # ``len >= 2`` floor preserves that. ``has_apostrophe_possessive``
        # bypass: possessive queries (``Lincoln's emancipation``) carry
        # their own intent signal that's already handled by OPP-1 at
        # the promotion layer.
        if body_is_disambig_page and not has_apostrophe_possessive(topic):
            disambig_content_tokens = [
                t
                for t in _TAIL_TOKEN_RE.findall(topic.lower())
                if t not in _DISCRIMINATOR_STOP_WORDS
            ]
            if len(disambig_content_tokens) >= 2:
                return self.zim_operations.search_zim_file(
                    zim_file_path, topic, search_limit, 0
                )
        if disambig_twin_path and not body_is_disambig_page:
            result = result + (
                f"\n\n_Note: this topic also has a disambiguation page — "
                f"see `get article {disambig_twin_path}` for alternate "
                f"meanings._"
            )
        if related_extends_paths and not body_is_disambig_page:
            # A11 post-a11 C1: cap the hint at the first 4 alternates
            # so the footer stays small even on hub topics that
            # generated a long extends-list.
            preview = ", ".join(f"`{p}`" for p in related_extends_paths[:4])
            extra = (
                f" (+{len(related_extends_paths) - 4} more)"
                if len(related_extends_paths) > 4
                else ""
            )
            result = result + (
                f"\n\n_May also refer to: {preview}{extra} — "
                f"use `tell me about <full title>` to fetch any of these._"
            )
        # A16 post-a16 D1 (pass-2): soft-connector ambiguity footer.
        # When the user's topic carried an ambiguous connector
        # (``Berlin and Paris`` / ``Tokyo, Osaka`` / ``Brad & Angelina``
        # / ``TCP/IP``) and the returned article only includes one of
        # the halves, surface a footer so the caller knows what was
        # picked vs. dropped. Suppressed when the returned title
        # already contains both halves (``Romeo and Juliet`` is one
        # article whose title spans the connector — no footer needed).
        # Post-b1 P1-D2: thread the original-case query through so the
        # footer echoes entity names in the caller's casing.
        original_query = (
            params.get("_pre_rewrite_query") if isinstance(params, dict) else None
        )
        soft_footer = self._soft_connector_footer(
            topic,
            top_title,
            zim_file_path=zim_file_path,
            top_path=top_path,
            original_query=original_query if isinstance(original_query, str) else None,
        )
        if soft_footer:
            result = result + soft_footer
        return result

    def _fetch_topic_article_body(
        self,
        zim_file_path: str,
        top_path: str,
        max_content_length: int,
        options: Dict[str, Any],
    ) -> Optional[str]:
        """Fetch the article body for the resolved tell_me_about top hit.

        Returns the body string on success, or ``None`` when the backend
        raises and the caller should degrade to plain search.

        DD2 (beta, second pass): threads ``options["content_offset"]``
        through so long-article pagination works under ``tell me
        about``. When ``content_offset == 0`` AND ``compact=True``,
        apply the lead-with-TOC cut so the response stays scoped to
        the lead + section list (the small-model sweet spot). Skip
        the cut when paging mid-article — the "lead section" concept
        doesn't apply, and the H2-boundary cut would truncate the
        requested page at the next heading.
        """
        content_offset = self._coerce_content_offset(options.get("content_offset"))
        try:
            body = self.zim_operations.get_zim_entry(
                zim_file_path,
                top_path,
                max_content_length,
                content_offset,
                compact=options.get("compact", False),
            )
        except Exception as e:
            logger.warning(
                "tell_me_about: article fetch failed for %r, falling back to "
                "search: %s",
                top_path,
                e,
            )
            return None
        if options.get("compact", False) and content_offset == 0:
            body = self._lead_with_toc(zim_file_path, top_path, body)
        return body

    @staticmethod
    def _coerce_content_offset(raw: Any) -> int:
        """Cast a caller-supplied ``content_offset`` to a non-negative int.

        Defaults to 0 on any TypeError/ValueError (None, strings, etc.).
        Negative ints are clamped to 0 so a malformed cursor can't
        produce an out-of-range slice downstream.
        """
        try:
            return max(int(raw or 0), 0)
        except (TypeError, ValueError):
            return 0

    def _handle_search_all(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> "Union[str, _HandlerResult]":
        # Honour caller-supplied ``limit`` (mapped to ``limit_per_file`` for
        # symmetry with other tools) and fall back to 5 — matching
        # ``search_zim_file``'s explicit ``limit_per_file=5`` default.
        if options.get("compact", False):
            actual_query = params.get("query", query)
            data = self.zim_operations.search_all_data(
                actual_query,
                limit_per_file=options.get("limit", 5),
            )
            # Phase D sub-D-1: cross-encoder rerank across all archives.
            # Hits are flattened into a single candidate list (tagged with
            # their source archive index so they can be redistributed after
            # reranking), reranked globally so the best hits win regardless
            # of which archive they come from, then grouped back into the
            # per-archive structure that ``render_search_all`` expects.
            per_file: List[Dict[str, Any]] = [
                cast(Dict[str, Any], e) for e in (data.get("results") or [])
            ]
            per_file = self._maybe_rerank_search_all(
                per_file=per_file, query=actual_query
            )

            data = cast(
                SearchAllResponse,
                {**cast(Dict[str, Any], data), "results": per_file},
            )
            body = compact_renderers.render_search_all(data, actual_query)
            # H10: surface the aggregate ``reason`` / ``suggestions`` from
            # _meta so the footer renders structured recovery hints in
            # the no-hit aggregate case. Without this, the legacy
            # markdown path swallowed both signals.
            meta_obj = data.get("_meta") if isinstance(data, dict) else None
            reason = meta_obj.get("reason") if isinstance(meta_obj, dict) else None
            suggestions = (
                meta_obj.get("suggestions") if isinstance(meta_obj, dict) else None
            )
            # All-archives-failed signal (Op4): if every per-file entry
            # carries an error, flag with ``archive_unavailable`` so the
            # caller knows the issue is structural, not query-shape.
            if per_file and all(
                isinstance(e, dict) and e.get("error") for e in per_file
            ):
                reason = "archive_unavailable"
            return _HandlerResult(body=body, reason=reason, suggestions=suggestions)
        return self.zim_operations.search_all(
            params.get("query", query),
            limit_per_file=options.get("limit", 5),
        )

    def _handle_walk_namespace(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        # A15 post-a15 P4-D3: ``walk namespace`` with a malformed
        # argument (multi-char ``AB``, digit ``1``, special ``_``, or
        # missing entirely) previously fell through to
        # ``params.get("namespace", "C")`` and silently walked C —
        # giving the caller no signal that their input was rejected.
        # Mirror the missing-arg shape ``_handle_find_by_title`` /
        # ``_handle_links`` / ``_handle_suggestions`` use so the error
        # surface is consistent across the simple-mode tools.
        namespace = params.get("namespace")
        if not namespace:
            return (
                "**Missing or Invalid Namespace**\n\n"
                "**Issue**: `walk namespace` needs a single "
                "namespace letter (A, C, M, W, etc.; case-insensitive).\n"
                "**Examples**:\n"
                "- `walk namespace C` — main content entries\n"
                "- `walk namespace M` — archive metadata\n"
                "- `walk namespace W` — well-known entries"
            )
        # Post-a18 P1-D4 (defence-in-depth): walk's own handler
        # rejects cursors issued by other tools (browse / search /
        # links) for the same reason ``_handle_browse`` does — see
        # the comment there.
        tool_mismatch = self._cursor_tool_mismatch(options, "walk_namespace")
        if tool_mismatch is not None:
            return tool_mismatch
        # P3-D7: cursor's namespace must match the request's namespace.
        # See _decode_cursor for the stash; the legacy ``ai`` / ``q``
        # mismatch checks already follow this shape.
        mismatch = self._cursor_ns_mismatch(options, namespace)
        if mismatch is not None:
            return mismatch
        # ``offset`` semantically maps to ``scan_at`` here — a resume
        # entry id, not pagination skip — but it's the only
        # general-purpose passthrough channel so we honour it. v2 walk
        # takes the decoded cursor-state dict directly so callers don't
        # have to round-trip through base64.
        offset = int(options.get("offset", 0) or 0)
        limit = options.get("limit", 200)
        # Post-a17 P1-D3: include the cursor's original ``ai`` field
        # when it was stashed by the dispatcher (see _decode_cursor at
        # ~line 295). Without it, ``walk_namespace_data``'s
        # unconditional ``verify_archive_identity`` rejects the
        # synthetic cursor with a misleading "missing archive-identity
        # field" error — even though the user was just round-tripping
        # the cursor the tool itself emitted. ``ns`` is also threaded
        # through so the cursor->namespace check stays meaningful when
        # the handler-level guard (``_cursor_ns_mismatch`` above) is
        # paired with the data-layer guard inside
        # ``walk_namespace_data``.
        cursor_state: Optional[Dict[str, Any]]
        if offset > 0:
            cursor_state = {"scan_at": offset, "l": limit}
            cursor_ai = options.get("_cursor_ai")
            if isinstance(cursor_ai, str) and cursor_ai:
                cursor_state["ai"] = cursor_ai
            cursor_ns = options.get("_cursor_ns")
            if isinstance(cursor_ns, str) and cursor_ns:
                cursor_state["ns"] = cursor_ns
        else:
            cursor_state = None
        if options.get("compact", False):
            data = self.zim_operations.walk_namespace_data(
                zim_file_path,
                namespace,
                cursor_state=cursor_state,
                limit=limit,
            )
            return compact_renderers.render_walk_namespace(data)
        return self.zim_operations.walk_namespace(
            zim_file_path,
            namespace,
            cursor=cursor_state,
            limit=limit,
        )

    def _handle_find_by_title(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        title = params.get("title")
        if not title:
            # Bare ``find article titled`` (no name) previously fell back
            # to passing the entire query as the title, which the backend
            # then searched for verbatim — producing an empty result with
            # no signal that the parameter was missing. Return an
            # actionable missing-title error instead, matching the style
            # of the other entry-path-required handlers above.
            return (
                "**Missing Article Title**\n\n"
                "Please specify the title of the article to find.\n"
                "**Examples**:\n"
                "- 'find article titled Photosynthesis'\n"
                "- 'find entry named \"World War II\"'\n"
                "- 'what's the path for Cellular_respiration'\n"
            )
        # A15 post-a15: namespace-prefixed input like ``M/Title`` is a
        # ZIM path, not a title. The title index only stores titles
        # (e.g. M/Title's title is just "Title"), so passing the path
        # to ``find_entry_by_title_data`` returns silently 0 hits with
        # no signal that the user used the wrong tool. Redirect upfront
        # so the caller knows to use ``get article`` for path lookup.
        # Pattern: single alpha letter + ``/`` + ≥3-char suffix. Both
        # uppercase and lowercase namespace letters are accepted because
        # Sub-D-2 Rule 1 lowercases the query before intent parsing, so
        # an originally uppercase ``M/Title`` arrives as ``m/title``.
        # libzim namespace lookups are case-insensitive, so normalising
        # to uppercase in the suggestion is still correct.
        # The ≥3-char floor avoids false-positiving real short titles
        # that legitimately contain ``/`` (the Wikipedia ``A/B`` testing
        # article has a 1-char suffix).
        if (
            len(title) >= 4
            and title[0].isascii()
            and title[0].isalpha()
            and title[1] == "/"
            and len(title[2:].strip()) >= 3
        ):
            normalized_title = title[0].upper() + title[1:]
            return (
                "**Namespace Path, Not a Title**\n\n"
                f"`{title}` looks like a ZIM namespace path. The title "
                "index only stores entry titles, so a path lookup "
                "returns no hits.\n"
                "**Try one of**:\n"
                f"- `get article {normalized_title}` — direct path lookup\n"
                f"- `find article titled {title[2:].strip()}` — "
                "title-only lookup (drops the namespace prefix)\n"
            )
        if options.get("compact", False):
            data = self.zim_operations.find_entry_by_title_data(
                zim_file_path,
                title,
                cross_file=False,
                limit=options.get("limit", 10),
            )
            # A16 post-a16 D7: lowercase-first-char namespace-path shape
            # (``m/Title``, ``c/Berlin``, ``w/mainPage``) couldn't fire
            # the upfront uppercase-only redirect because some real
            # article titles ARE lowercase-first-char + ``/`` (e.g.
            # the Wikipedia ``A/B`` testing article via ``a/b``). Now
            # that we've actually consulted the title index and got
            # zero hits, the shape unambiguously means "namespace
            # path the caller misrouted to find_by_title". Emit the
            # same redirect the uppercase upfront path uses, with the
            # suggestion paths normalised to uppercase (the
            # conventional ZIM form). libzim namespace lookups are
            # case-insensitive (see ``openzim_mcp/zim/namespace.py``).
            results = data.get("results") if isinstance(data, dict) else None
            if (
                not results
                and len(title) >= 4
                and title[0].isascii()
                and title[0].isalpha()
                and title[1] == "/"
                and len(title[2:].strip()) >= 3
            ):
                normalized = title[0].upper() + title[1:]
                return (
                    "**Namespace Path, Not a Title**\n\n"
                    f"`{title}` looks like a ZIM namespace path. The "
                    "title index only stores entry titles, so a path "
                    "lookup returns no hits.\n"
                    "**Try one of**:\n"
                    f"- `get article {normalized}` — direct path lookup "
                    "(namespace letters are case-insensitive)\n"
                    f"- `find article titled {title[2:].strip()}` — "
                    "title-only lookup (drops the namespace prefix)\n"
                )
            return compact_renderers.render_find_by_title(data, title)
        return self.zim_operations.find_entry_by_title(
            zim_file_path,
            title,
            cross_file=False,
            limit=options.get("limit", 10),
        )

    def _handle_related(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        entry_path = params.get("entry_path")
        if not entry_path:
            # An empty entry_path used to be passed straight to the
            # backend, which returned ``"Entry not found: ''"`` inside a
            # JSON envelope — useless for a small LLM trying to recover.
            # Return an actionable missing-article error instead.
            return (
                "**Missing Article**\n\n"
                "Please specify which article to find related entries "
                "for.\n"
                "**Examples**:\n"
                "- 'articles related to Photosynthesis'\n"
                "- 'what links to \"Climate change\"'\n"
                "- 'links from Cellular_respiration'\n"
            )
        # D2 (beta): the intent parser hands us the topic verbatim from
        # the user's phrasing (``articles related to United States`` →
        # ``United States``), but the underlying entry path stores
        # spaces as underscores (``United_States``). Without a title
        # resolution step the backend hits ``Cannot find entry`` and
        # returns a useless error, even though ``tell me about United
        # States`` would have resolved correctly via the same title
        # promotion that ``_handle_tell_me_about`` already uses. Probe
        # the title index for the topic-as-title FIRST; fall through to
        # the literal path only when no canonical match exists so a
        # caller passing the exact path (``Cellular_respiration``)
        # still gets a direct lookup. ``min_score=0.8`` so common
        # typos route here too (``articles related to Photosythesis``
        # → ``Photosynthesis``).
        promoted = find_title_match(
            self.zim_operations, zim_file_path, entry_path, min_score=0.8
        )
        if promoted is not None and promoted.get("path"):
            entry_path = promoted["path"]
        try:
            if options.get("compact", False):
                data = self.zim_operations.get_related_articles_data(
                    zim_file_path,
                    entry_path,
                    limit=options.get("limit", 10),
                )
                return compact_renderers.render_related(data, entry_path)
            return self.zim_operations.get_related_articles(
                zim_file_path,
                entry_path,
                limit=options.get("limit", 10),
            )
        except Exception as e:
            # A11 F3 (post-a10): when the entry path doesn't exist
            # (``articles related to NotARealArticle123``), the
            # backend raised ``"Cannot find entry"`` and the surface
            # returned a one-line raw error with no recovery hint.
            # Wrap with a structured guidance message pointing to
            # ``suggestions for`` / ``find article titled`` so a
            # small LLM has a concrete next step.
            err = sanitize_context_for_error(str(e))
            # Post-v2.0.5 D-P sibling: mirror the recovery shape from
            # ``_render_not_found_recovery``; ``tell me about`` is a
            # distinct recovery (title-index + RAG fallback) from the
            # pure ``find article titled X`` path.
            return (
                f"**Article not found: `{entry_path}`**\n\n"
                f"{err}\n\n"
                "**Try one of these to recover:**\n"
                f"- `suggestions for {entry_path[:40]}` — autocomplete "
                "to catch typos / partial names\n"
                f"- `find article titled {entry_path}` — title-index "
                "lookup with fuzzy fallback\n"
                f"- `search for {entry_path}` — full-text search\n"
                f"- `tell me about {entry_path}` — fuzzy title-index "
                "lookup with RAG fallback when no exact title matches\n"
            )

    def _handle_get_zim_entries(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        entry_paths = params.get("entries") or []
        if not entry_paths:
            return (
                "**Missing Entry Paths**\n\n"
                "I couldn't extract entry paths from your query. "
                "Use namespace/path syntax, e.g., "
                "'fetch entries C/Photosynthesis C/Cell_biology'."
            )
        entries = [
            {"zim_file_path": zim_file_path, "entry_path": p} for p in entry_paths
        ]
        return self.zim_operations.get_entries(
            entries,
            options.get("max_content_length"),
            compact=options.get("compact", False),
        )

    _INTENT_HANDLERS = {
        "metadata": _handle_metadata,
        "main_page": _handle_main_page,
        "list_namespaces": _handle_list_namespaces,
        "browse": _handle_browse,
        "structure": _handle_structure,
        "toc": _handle_toc,
        "summary": _handle_summary,
        "links": _handle_links,
        "binary": _handle_binary,
        "suggestions": _handle_suggestions,
        "filtered_search": _handle_filtered_search,
        "get_article": _handle_get_article,
        "search": _handle_search,
        "search_all": _handle_search_all,
        "tell_me_about": _handle_tell_me_about,
        "walk_namespace": _handle_walk_namespace,
        "find_by_title": _handle_find_by_title,
        "related": _handle_related,
        "get_zim_entries": _handle_get_zim_entries,
        "get_section": _handle_get_section,
    }

    def _handle_synthesize_query(
        self,
        query: str,
        zim_file_path: Optional[str],
        *,
        compact: bool = False,
    ) -> Union[SynthesizeResponse, ToolErrorPayload]:
        """Phase C: dispatch query to the synthesize pipeline.

        Opens archives using ExitStack (clean lifecycle, no leaks), calls
        synthesize_query, and returns a SynthesizeResponse or ToolErrorPayload.

        Archive resolution:
          - If zim_file_path is provided, validate and open that single archive.
          - Otherwise, discover all ZIM files via list_zim_files_data() and
            open all of them (multi-archive RRF fusion path).

        search_handler is self.zim_operations — ZimOperations has search_top_k
        directly, satisfying the synthesize pipeline's duck-typed interface.

        D5 fix: strip natural-language interrogative prefixes ("tell me
        about", "who is", "what are", …) before handing the query to
        the search stage. Without the strip, ``synthesize=True`` with
        query ``"tell me about Berlin"`` BM25-matched on the words
        "tell" + "me" + "about" + "Berlin" and returned songs by Irving
        Berlin / Nat King Cole albums / Hans Abrahamsen pieces.
        Re-using ``IntentParser`` keeps prefix detection in one place
        and benefits from the existing test coverage.
        """
        from openzim_mcp.synthesize import synthesize_query

        # Post-v2.0.4 D-I: mirror the meta-only / chained-intent guards
        # the non-synthesize path fires at handle_zim_query lines 693
        # and 710. Pre-fix the synthesize early-exit at line 626 skipped
        # both: ``try again`` BM25-searched and returned Aaliyah's "Try
        # Again" song; ``tell me about Berlin then list namespaces``
        # silently RAG-searched the literal verb chain and returned
        # Namespace + War articles instead of rejecting the chain.
        # Same shape as the post-v2.0.0 D-G fix — return a structured
        # tool_error envelope (synthesize's native error shape) with
        # the full markdown guidance from the simple-mode helpers so
        # callers get the same actionable recovery info.
        if self._is_meta_only_query(query):
            self._track("meta_only_guidance")
            return tool_error(
                operation="meta_only_guidance",
                message=self._meta_query_guidance(),
            )
        chained_warning = self._chained_intent_guidance(query)
        if chained_warning is not None:
            self._track("chained_intent_rejected")
            return tool_error(
                operation="chained_intent_rejected",
                message=chained_warning,
            )

        # D5: distill the user's natural-language query down to the
        # topic (or actual search terms) BEFORE handing it to BM25.
        # The intent parser already knows how to pull "Berlin" out of
        # "tell me about Berlin" / "who is Berlin" / "describe Berlin".
        # Fall back to the raw query when the parser doesn't classify
        # it as a topic ask — for plain ``search`` intents (the user
        # typed "berlin wall" directly), the raw query IS the search
        # query.
        # Sub-D-2: build the title probe (returns None when no archive
        # is in scope; rules 2 and 3 degrade gracefully). Snapshot
        # intermediate stages by running the rules individually to emit
        # per-rule telemetry. This keeps parse_intent's responsibilities
        # clean (it doesn't know about _track); the cost is two extra
        # rule passes worth of CPU per query.
        if self.zim_operations.config.query_rewrite.enabled:
            # Post-b1 P1-D1: mirror of the simple-branch fix at line
            # ~624 — pre-resolve zim_file_path so the probe sees the
            # single auto-selected archive when the caller omits it.
            probe_path = self._probe_archive_path(zim_file_path)
            title_probe = self._build_title_probe(probe_path)
            after_lower = IntentParser._normalize_topic_case(query)
            after_misspell = IntentParser._apply_misspelling_map(
                after_lower, title_probe=title_probe
            )
            if after_misspell != after_lower:
                self._track(_QUERY_REWRITE_MISSPELLING)
            after_stopword = IntentParser._detect_stopword_phrase(
                after_misspell, title_probe=title_probe
            )
            if after_stopword != after_misspell:
                self._track(_QUERY_REWRITE_STOPWORD_PHRASE)
            # Post-b1 P1-D3: pass probe to Rule 4 (mirror of the
            # simple-branch wiring).
            _, hint_probe = IntentParser._decompose_x_of_y(
                after_stopword, title_probe=title_probe
            )
            if hint_probe is not None:
                self._track(_QUERY_REWRITE_X_OF_Y)
        else:
            title_probe = None

        try:
            intent, params, _confidence = self.intent_parser.parse_intent(
                query,
                title_probe=title_probe,
                query_rewrite_enabled=self.zim_operations.config.query_rewrite.enabled,
            )
        except Exception as e:  # pragma: no cover — defensive
            logger.debug("intent_parser failed in synthesize prelude: %s", e)
            intent, params = "search", {}
        # Post-v2.0.0 D-G: mirror the empty-topic / empty-search guards
        # the non-synthesize path fires at simple_tools.py:836-887.
        # Pre-fix, ``tell me about `` (trailing whitespace, empty topic)
        # with synthesize=True silently searched the literal verb prefix
        # "tell me about" via BM25 and returned title-prefix matches
        # (``Tell_Me_About_Tomorrow``, ``Tell_Me_About_Your_Day_Today``).
        # Same shape for ``tell me about ?`` (punctuation-only) and
        # ``tell me about ""`` (D-E quoted-empty on the synthesize path).
        # Return a structured tool_error envelope — synthesize's native
        # error shape — rather than the markdown the non-synthesize path
        # emits, since the synthesize return type is already
        # ``Union[SynthesizeResponse, ToolErrorPayload]``.
        if intent == "tell_me_about" and isinstance(params, dict):
            _topic_check = (params.get("topic") or "").strip()
            if not _topic_check:
                return tool_error(
                    operation="topic_required",
                    message=(
                        "`tell me about` needs a non-empty topic to look up. "
                        "Examples: `tell me about Photosynthesis`, "
                        "`who is Albert Einstein`, `describe DNA`."
                    ),
                )
        elif intent == "search" and isinstance(params, dict):
            # Mirror the non-synthesize empty-search check at line ~869:
            # ``_extract_search`` falls back to the whole query when no
            # tail follows ``search for``, so ``params["query"]`` for
            # ``search for `` is the full literal "search for " — which
            # ``.strip()`` reduces to "search for", non-empty. Use
            # ``_search_query_tail`` which peels the verb prefix and
            # returns "" when no terms follow.
            _search_tail = self._search_query_tail(query)
            if _search_tail is not None:
                _search_tail = IntentParser._strip_trailing_politeness(
                    _search_tail
                ).strip()
            if _search_tail is not None and not _search_tail:
                return tool_error(
                    operation="search_terms_required",
                    message=(
                        "`search for` needs at least one search term. "
                        'Examples: `search for "quantum mechanics"`, '
                        "`search for Berlin in namespace C`."
                    ),
                )
        # Post-v2.0.4 D-I: mirror the multi-entity chain rejection the
        # non-synthesize path fires at handle_zim_query line 960.
        # Pre-fix, ``tell me about Berlin and Munich and Cologne`` with
        # synthesize=True silently RAG-searched the literal three-entity
        # chain and returned Cologne plus unrelated articles — Berlin
        # and Munich data dropped on the floor. ``_multi_entity_chain_
        # guidance`` requires a real archive path to probe the title
        # index (so canonical multi-entity titles like ``Earth, Wind &
        # Fire`` aren't false-rejected). Resolve best-effort: use the
        # explicit zim_file_path if given, else pick the first
        # available archive. When no archive is available skip the
        # probe — the synthesize pipeline will surface a
        # no_archives_available error below anyway.
        multi_probe_path: Optional[str] = zim_file_path
        if not multi_probe_path:
            try:
                _file_entries = self.zim_operations.list_zim_files_data()
                for _entry in _file_entries:
                    _ep = _entry.get("path")
                    if _ep:
                        multi_probe_path = str(_ep)
                        break
            except Exception:
                multi_probe_path = None
        if multi_probe_path:
            multi_entity_warning = self._multi_entity_chain_guidance(
                intent, params, multi_probe_path
            )
            if multi_entity_warning is not None:
                self._track("multi_entity_chain_rejected")
                return tool_error(
                    operation="multi_entity_chain_rejected",
                    message=multi_entity_warning,
                )
        search_query = query
        if intent == "tell_me_about" and isinstance(params, dict):
            topic = params.get("topic")
            if isinstance(topic, str) and topic.strip():
                search_query = topic.strip()
        elif intent == "search" and isinstance(params, dict):
            extracted = params.get("query")
            if isinstance(extracted, str) and extracted.strip():
                search_query = extracted.strip()

        # Resolve the set of archive paths to open.
        archives_to_open: list[Path] = []
        if zim_file_path:
            try:
                validated = self.zim_operations.path_validator.validate_path(
                    zim_file_path
                )
                validated = self.zim_operations.path_validator.validate_zim_file(
                    validated
                )
                archives_to_open = [validated]
            except Exception as e:
                return tool_error(
                    operation="invalid_path",
                    message=f"Invalid ZIM file path: {e}",
                )
        else:
            try:
                file_entries = self.zim_operations.list_zim_files_data()
                archives_to_open = [
                    Path(str(entry["path"]))
                    for entry in file_entries
                    if entry.get("path")
                ]
            except Exception as e:
                logger.warning("list_zim_files_data failed in synthesize: %s", e)
                archives_to_open = []

        if not archives_to_open:
            return tool_error(
                operation="no_archives_available",
                message=(
                    "No ZIM archives are available. "
                    "Specify a zim_file_path or configure allowed_directories."
                ),
            )

        with ExitStack() as stack:
            archives: list = []
            for vp in archives_to_open:
                try:
                    archive = stack.enter_context(_zim_ops_mod.zim_archive(vp))
                    archives.append((archive, vp))
                except Exception as e:
                    logger.warning(
                        "Could not open archive %s for synthesize: %s", vp, e
                    )
                    continue

            if not archives:
                return tool_error(
                    operation="no_archives_available",
                    message="No ZIM archives could be opened for synthesize.",
                )

            return synthesize_query(
                search_query,
                archives=archives,
                search_handler=self.zim_operations,
                cache=self.zim_operations.cache,
                content_processor=self.zim_operations.content_processor,
                config=self.zim_operations.config.synthesize,
                # Phase D sub-D-1: pass the reranker config so the
                # synthesize pipeline can rerank passage candidates
                # before section attribution. Passage ordering pays
                # off most here — this is the deepest content-
                # fragment-query surface.
                reranker_config=self.zim_operations.config.ml.reranker,
                # The original natural-language query goes in the
                # response so callers can correlate the synthesized
                # answer with what they actually asked. Without this,
                # ``query`` echoes back the BM25-stripped form which
                # is harder to recognize.
                original_query=query,
                # In compact mode, suppress the answer/passage text
                # duplication (D8) and strip Wikipedia's markdown
                # link soup (Op4). Verbose mode keeps both for callers
                # that want full passage shape for downstream
                # processing.
                omit_passage_text=compact,
                strip_links=compact,
            )

    def _normalize_zim_file_path(self, candidate: str) -> str:
        """Resolve hallucinated ZIM file paths or fall back to auto-select.

        Returns the (possibly rewritten) path. Resolution policy:

          1. ``candidate`` matches a real ZIM file's full path or basename:
             return the real path. Basename-only matches normalize bare-
             filename hallucinations like ``"wikipedia.zim"`` to whatever
             directory the file actually lives in.

          2. ``candidate`` doesn't match anything AND exactly one ZIM
             file is loaded: auto-select that one. Catches bare-filename
             hallucinations (``"wikipedia.zim"``) and — post-a20 PD2-3
             — also fully-qualified path hallucinations like
             ``/data/wikipedia_en_all_maxi.zim`` (small models routinely
             copy this literally from the tool's own docstring example;
             the real archive is date-suffixed and won't match by
             basename either). In single-archive setups the explicit
             path is functionally redundant — there is no second
             archive to disambiguate against — so silent substitution
             is the right UX and unlocks small-model recovery instead
             of dropping them into a "File does not exist" loop.

          3. ``candidate`` doesn't match anything AND multiple archives
             are loaded: trust the candidate. The backend surfaces a
             clean ``File does not exist`` error which
             ``handle_zim_query``'s catch-all then enriches with the
             list of real archive paths (post-a20 PD2-4). H14's rule
             that "explicit paths must reach the backend" only matters
             when there's genuine ambiguity about which archive the
             caller wanted — single-archive setups have none.
        """
        resolved = self._resolve_zim_path(candidate)
        if resolved is not None:
            if resolved != candidate:
                self._track("zim_path_resolved_by_basename")
                logger.info(
                    f"Resolved hallucinated zim_file_path "
                    f"'{candidate}' to '{resolved}' via basename match."
                )
            return resolved
        auto_selected = self._auto_select_zim_file()
        if auto_selected:
            has_separator = "/" in candidate or "\\" in candidate
            self._track(
                "zim_path_replaced_with_auto_select_separator"
                if has_separator
                else "zim_path_replaced_with_auto_select"
            )
            logger.info(
                f"Discarded hallucinated zim_file_path "
                f"'{candidate}' (no match, single archive loaded); "
                f"auto-selected '{auto_selected}'."
            )
            return auto_selected
        return candidate

    def _resolve_zim_path(self, candidate: str) -> Optional[str]:
        """Try to resolve ``candidate`` to a real ZIM file's full path.

        Returns:
            * ``candidate`` (verbatim) if it matches a real file's path.
            * The matched file's full path if ``candidate``'s basename
              matches a real file's basename in a different directory
              (handles bare-filename hallucinations like
              ``"wikipedia.zim"`` by normalizing to the actual path).
            * ``None`` if no match is found, or if the backend fails.

        Defensive against backend failures: any exception while
        fetching or iterating the ZIM-files listing means we cannot
        verify the path; return ``None`` and let the caller decide how
        to proceed.
        """
        cand = candidate.strip()
        if not cand:
            return None
        cand_basename = Path(cand).name
        try:
            files = self.zim_operations.list_zim_files_data()
            basename_match: Optional[str] = None
            for entry in files:
                real_path = str(entry.get("path", ""))
                if not real_path:
                    continue
                if cand == real_path:
                    return real_path
                if (
                    basename_match is None
                    and cand_basename
                    and Path(real_path).name == cand_basename
                ):
                    # Defer returning until we've checked the rest of
                    # the list for an exact-path match. Otherwise an
                    # earlier basename-match would mask a later
                    # exact-path match in the same listing.
                    basename_match = real_path
            return basename_match
        except Exception:
            return None

    def _auto_select_zim_file(self) -> Optional[str]:
        """Phase F: thin wrapper delegating to ``topic_preprocessing``.

        See :func:`openzim_mcp.topic_preprocessing.auto_select_zim_file` for
        the 4-arm log envelope (0-files info / 1-file debug / N-files info /
        exception warning). Byte-identical to the pre-extraction implementation
        (proven by the Gate 0a parity diff-test in
        ``tests/dispatch_eval/test_auto_select_extraction_parity.py``).
        """
        from openzim_mcp.topic_preprocessing import auto_select_zim_file

        return auto_select_zim_file(self.zim_operations)
