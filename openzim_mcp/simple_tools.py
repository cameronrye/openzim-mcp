"""Simple tools implementation for OpenZIM MCP server.

This module provides intelligent, natural language-based tools that abstract
away the complexity of multiple specialized tools. Designed for LLMs with
limited tool-calling capabilities or context windows.

The regex-heavy intent-parsing layer lives in :mod:`openzim_mcp.intent_parser`.
``IntentParser``, ``safe_regex_search`` and ``safe_regex_findall`` are
re-exported here for backward-compatibility with existing imports.
"""

import logging
import re
import unicodedata
from typing import Any, Dict, Optional

from .intent_parser import IntentParser
from .security import sanitize_context_for_error
from .zim_operations import ZimOperations

logger = logging.getLogger(__name__)


class SimpleToolsHandler:
    """Handler for simple, intelligent MCP tools."""

    def __init__(self, zim_operations: ZimOperations):
        """Initialize simple tools handler.

        Args:
            zim_operations: ZimOperations instance for underlying operations
        """
        self.zim_operations = zim_operations
        self.intent_parser = IntentParser()

    def handle_zim_query(
        self,
        query: str,
        zim_file_path: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Handle a natural language query about ZIM file content.

        This is the main intelligent tool that routes queries to appropriate
        underlying operations based on intent parsing.

        Args:
            query: Natural language query
            zim_file_path: Optional path to ZIM file (auto-selects if not provided)
            options: Optional dict with advanced options (limit, offset, etc.)

        Returns:
            Response string with results
        """
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
                )
            options = options or {}
            intent, params, confidence = self.intent_parser.parse_intent(query)
            logger.info(
                f"Parsed intent: {intent}, params: {params}, "
                f"confidence: {confidence:.2f}"
            )

            low_confidence_note = self._confidence_note(intent, confidence, query)

            # ``list_files`` is the only intent that doesn't need a ZIM file.
            if intent == "list_files":
                return self.zim_operations.list_zim_files() + low_confidence_note

            if not zim_file_path:
                zim_file_path = self._auto_select_zim_file()
                if not zim_file_path:
                    return (
                        "**No ZIM File Specified**\n\n"
                        "Please specify a ZIM file path, or ensure there is "
                        "exactly one ZIM file available.\n\n"
                        "**Available files:**\n"
                        f"{self.zim_operations.list_zim_files()}"
                    )

            handler = self._INTENT_HANDLERS.get(
                intent, SimpleToolsHandler._handle_search
            )
            result = handler(self, query, zim_file_path, params, options)
            return result + low_confidence_note

        except Exception as e:
            logger.error(f"Error handling zim_query: {e}")
            # Sanitize both the query and error text to avoid leaking
            # absolute filesystem paths back to the MCP client.
            safe_query = sanitize_context_for_error(query)
            safe_error = sanitize_context_for_error(str(e))
            return (
                f"**Error Processing Query**\n\n"
                f"**Query**: {safe_query}\n"
                f"**Error**: {safe_error}\n\n"
                f"**Troubleshooting**:\n"
                f"1. Check that the ZIM file path is correct\n"
                f"2. Verify the query format\n"
                f"3. Try a simpler query\n"
                f"4. Check server logs for details"
            )

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
        return self.zim_operations.get_main_page(zim_file_path)

    def _handle_list_namespaces(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        return self.zim_operations.list_namespaces(zim_file_path)

    def _handle_browse(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        return self.zim_operations.browse_namespace(
            zim_file_path,
            params.get("namespace", "C"),
            options.get("limit", 50),
            options.get("offset", 0),
        )

    def _handle_structure(
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
                "Please specify which article you want the structure for.\n"
                "**Example**: 'structure of Biology' or "
                "'structure of \"C/Evolution\"'"
            )
        return self.zim_operations.get_article_structure(zim_file_path, entry_path)

    def _handle_toc(
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
                "Please specify which article you want the TOC for.\n"
                "**Example**: 'table of contents for Biology' or "
                "'toc of \"C/Evolution\"'"
            )
        return self.zim_operations.get_table_of_contents(zim_file_path, entry_path)

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
        return self.zim_operations.get_entry_summary(
            zim_file_path, entry_path, options.get("max_words", 200)
        )

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
        return self.zim_operations.extract_article_links(zim_file_path, entry_path)

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
        return self.zim_operations.search_with_filters(
            zim_file_path,
            params.get("query", query),
            params.get("namespace"),
            params.get("content_type"),
            options.get("limit"),
            options.get("offset", 0),
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
            # remainder as the entry path.
            cleaned_query = re.sub(
                r"\b(get|show|read|display|fetch|article|entry|page)\b",
                "",
                query,
                flags=re.IGNORECASE,
            ).strip()
            if not cleaned_query:
                return (
                    "**Missing Article Path**\n\n"
                    "Please specify which article you want to read.\n"
                    "**Example**: 'get article Biology' or "
                    "'show \"C/Evolution\"'"
                )
            entry_path = cleaned_query
        return self.zim_operations.get_zim_entry(
            zim_file_path,
            entry_path,
            options.get("max_content_length"),
            options.get("content_offset", 0),
        )

    def _handle_search(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        return self.zim_operations.search_zim_file(
            zim_file_path,
            params.get("query", query),
            options.get("limit"),
            options.get("offset", 0),
        )

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
            # Render the no-results message inline from the structured
            # payload — falling through to ``search_zim_file`` would
            # re-execute the same search, and zero-result responses are
            # not cached.
            return f'No search results found for "{topic}"'

        # Scan all returned results for strong title matches, not just
        # ``results[0]``. Wikipedia full-text search ranks word frequency
        # higher than title match, so for many bare-topic queries the
        # canonical article ranks below derivative pages (``Björk`` returns
        # ``List_of_songs_recorded_by_Björk`` first, the actual ``Björk``
        # article third). Auto-fetch only when there's *exactly one*
        # strong match — multiple matches mean genuine ambiguity (e.g.
        # ``Mercury`` -> planet, element, mythology) that the caller
        # should disambiguate.
        strong_matches = [
            r
            for r in results
            if self._is_strong_title_match(topic, r.get("path", ""), r.get("title", ""))
        ]
        if len(strong_matches) != 1:
            return self.zim_operations.search_zim_file(
                zim_file_path, topic, search_limit, 0
            )

        top = strong_matches[0]
        top_path = top.get("path", "")
        top_title = top.get("title", "")

        try:
            article_body = self.zim_operations.get_zim_entry(
                zim_file_path, top_path, max_content_length, 0
            )
        except Exception as e:
            # Article fetch failed — degrade gracefully to plain search.
            logger.warning(
                "tell_me_about: article fetch failed for %r, falling back to "
                "search: %s",
                top_path,
                e,
            )
            return self.zim_operations.search_zim_file(
                zim_file_path, topic, search_limit, 0
            )

        # Strong-match path: return just the article. We deliberately do
        # NOT append a "## Other matches" section here — the rendered
        # search would duplicate the top hit (we already inlined it
        # above), and the agentic-loop UX value of seeing related-but-not
        # asked-for articles is low. If the caller wants alternatives,
        # they can issue a separate ``search ...`` query.
        return (
            f"# {top_title or topic}\n\n"
            f"_Source: `{top_path}`_\n\n"
            f"{article_body}"
        )

    @staticmethod
    def _fold_diacritics(text: str) -> str:
        """Strip combining marks via NFKD so ``"Björk"`` -> ``"Bjork"``.

        Used by the strong-title-match heuristic so a topic with diacritics
        matches articles whose paths the ZIM stores ASCII-folded — and
        vice versa. NFKD also normalises composed vs decomposed forms of
        the same character (``"Å"`` U+00C5 vs ``"A"`` + U+030A), so the
        match is stable regardless of how either side encodes accents.
        """
        nfkd = unicodedata.normalize("NFKD", text)
        return "".join(c for c in nfkd if not unicodedata.combining(c))

    # Leading articles stripped from a topic on the second match attempt.
    # Covers the common "tell me about <leading article> <topic>" phrasing
    # that survives the ``tell me about`` prefix strip — e.g. ``"the
    # Apollo 11 mission"`` should still match ``Apollo_11``. We strip only
    # leading occurrences (``"The Beatles"`` ↔ ``"The_Beatles"`` matches
    # literally without stripping, and we never strip mid-string ``"the"``
    # from titles like ``"The Lord of the Rings"``).
    _LEADING_TOPIC_ARTICLES = ("the", "a", "an")

    @staticmethod
    def _is_strong_title_match(topic: str, path: str, title: str) -> bool:
        """Return True iff ``path`` or ``title`` looks like the article
        for ``topic``.

        Tokenizes both sides on alphanumerics after NFKD normalization
        with combining-mark stripping (so ``"Martin_Luther_King_Jr."``
        and ``"Martin Luther King Jr."`` both yield
        ``("martin", "luther", "king", "jr")``, and ``"Björk"`` matches
        both ``"Björk"`` and the ASCII-folded ``"Bjork"`` some ZIMs
        store), then accepts the match
        when the token lists are either equal or one is a prefix of the
        other:

        * Equal: ``"DNA"`` ↔ ``"DNA"``.
        * Topic is a prefix of the candidate, **and the extra material
          is a Wikipedia-style parenthesised disambiguation suffix**:
          ``"Mercury"`` → ``"Mercury_(planet)"``, ``"Apollo 11"`` →
          ``"Apollo_11_(mission)"``. Subtitle-style titles like
          ``"Marie Curie: The Courage of Knowledge"`` (a 2016 biopic)
          are *not* disambiguations of ``"Marie Curie"`` and must not
          auto-promote — they're separate works named after the topic.
        * Candidate is a prefix of the topic: ``"Apollo 11 (mission)"``
          → ``"Apollo_11"`` (the caller pre-disambiguated; the bare
          article matches).

        Pure substring containment was the v1.2.0-pre version of this
        check, but that false-matched short topics: ``"cat"`` "matched"
        ``"Catfish"`` and ``"py"`` "matched" ``"Pyramid"``. Token-list
        comparison fixes those without losing the disambiguation
        forgiveness above.

        A short-topic guard rejects topics whose tokens collectively have
        fewer than 3 characters, except for *exact* matches — so
        ``"Pi"`` ↔ ``"Pi"`` still works but ``"Pi"`` ↔ ``"Pizza"`` does
        not enter the prefix path at all.

        Leading-article fallback: if the literal topic doesn't match,
        try again with leading ``"the"`` / ``"a"`` / ``"an"`` stripped.
        Catches the common ``"tell me about the X"`` phrasing without
        breaking ``"The Beatles"``-style titles, which match literally
        before the fallback runs.
        """
        if SimpleToolsHandler._match_against_candidates(topic, path, title):
            return True
        # Fallback: strip a single leading article and retry. We only do
        # one pass — the goal is to forgive ``"the X"`` phrasings, not to
        # peel arbitrary stop-word prefixes.
        topic_tokens = tuple(re.findall(r"[A-Za-z0-9]+", topic))
        if (
            len(topic_tokens) >= 2
            and topic_tokens[0].lower() in SimpleToolsHandler._LEADING_TOPIC_ARTICLES
        ):
            stripped = topic[len(topic_tokens[0]) :].lstrip(" \t_-")
            return SimpleToolsHandler._match_against_candidates(stripped, path, title)
        return False

    @staticmethod
    def _match_against_candidates(topic: str, path: str, title: str) -> bool:
        """Token-list match check, factored out so the caller can retry
        with a transformed topic (e.g. leading articles stripped).
        """
        topic_normalized = SimpleToolsHandler._fold_diacritics(topic.lower())
        topic_tokens = tuple(re.findall(r"[a-z0-9]+", topic_normalized))
        if not topic_tokens:
            return False

        for candidate in (path, title):
            if not candidate:
                continue
            cand_normalized = SimpleToolsHandler._fold_diacritics(candidate.lower())
            cand_tokens = tuple(re.findall(r"[a-z0-9]+", cand_normalized))
            if not cand_tokens:
                continue
            # Exact match is always strong — works at any length.
            if topic_tokens == cand_tokens:
                return True
            # Prefix matches are only safe for topics with enough material
            # to be unambiguous; below 3 chars total, "Pi" / "Pizza" type
            # collisions outweigh the value.
            if sum(len(t) for t in topic_tokens) < 3:
                continue
            # Topic is a token-prefix of candidate. Only accept when the
            # raw "extra" portion is a parenthesised disambiguation — not
            # a colon/dash subtitle or an arbitrary continuation.
            if cand_tokens[: len(topic_tokens)] == topic_tokens:
                topic_span = r"[^a-z0-9]+".join(re.escape(t) for t in topic_tokens)
                m = re.match(topic_span, cand_normalized)
                if m:
                    rest = cand_normalized[m.end() :].lstrip(" \t_-")
                    if rest.startswith("("):
                        return True
                continue
            if topic_tokens[: len(cand_tokens)] == cand_tokens:
                return True
        return False

    def _handle_search_all(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        # Honour caller-supplied ``limit`` (mapped to ``limit_per_file`` for
        # symmetry with other tools) and fall back to 5 — matching
        # ``search_zim_file``'s explicit ``limit_per_file=5`` default.
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
        # ``offset`` semantically maps to ``cursor`` here — a resume token,
        # not pagination skip — but it's the only general-purpose passthrough
        # channel so we honour it.
        return self.zim_operations.walk_namespace(
            zim_file_path,
            params.get("namespace", "C"),
            cursor=options.get("offset", 0),
            limit=options.get("limit", 200),
        )

    def _handle_find_by_title(
        self,
        query: str,
        zim_file_path: str,
        params: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        return self.zim_operations.find_entry_by_title(
            zim_file_path,
            params.get("title", query),
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
        return self.zim_operations.get_related_articles(
            zim_file_path,
            params.get("entry_path", ""),
            limit=options.get("limit", 10),
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
            entries, options.get("max_content_length")
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
    }

    def _auto_select_zim_file(self) -> Optional[str]:
        """Auto-select a ZIM file if only one is available.

        Returns:
            Path to ZIM file if exactly one exists, None otherwise.
            Returns None with appropriate logging if multiple files exist
            or on error.
        """
        try:
            # Use structured data method directly (not parsing JSON from string)
            files = self.zim_operations.list_zim_files_data()

            if len(files) == 0:
                logger.info(
                    "Auto-select failed: no ZIM files found in allowed directories"
                )
                return None
            elif len(files) == 1:
                selected = str(files[0]["path"])
                logger.debug(f"Auto-selected ZIM file: {selected}")
                return selected
            else:
                logger.info(
                    f"Auto-select skipped: {len(files)} ZIM files found, "
                    "please specify which file to use"
                )
                return None

        except Exception as e:
            # Log at warning level with specific error for debugging
            logger.warning(
                f"Auto-select ZIM file failed with error: {type(e).__name__}: {e}"
            )
            return None
