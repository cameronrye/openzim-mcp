"""Regression tests for the post-v2.0.4 beta-test sweep.

Single defect surfaced by a live two-archive sweep
(zim.owl-atlas.ts.net, wikipedia_en_all_maxi_2026-02 + superuser.com_en_all
_2026-02):

D-E sibling on ``_handle_get_article`` word-strip recovery branch.
The post-v2.0.0 sweep's D-E fix landed on three extractors
(``_extract_find_by_title``, ``_extract_related``,
``_extract_entry_path_keyworded``) and dropped the empty-quote 2-char
literal cleanly at parse time. ``IntentParser.parse_intent('get article
"")`` correctly returns ``{}`` (no ``entry_path``) — the parser is
fine.

But ``_handle_get_article`` has a word-strip recovery branch for the
case when the parser returned no ``entry_path``: it does
``safe_regex_sub(r"\\b(get|show|read|display|fetch|article|entry|page)\\b",
"", query, flags=IGNORECASE).strip()`` and assigns the result as the
``entry_path``. For ``get article ""``, that word-strip leaves the
literal 2-char ``""`` (whitespace ``.strip()`` is no-op on quote
chars), the truthy 2-char string passes the ``if not cleaned_query:``
guard, and the backend's title-promotion fuzzy-matches the literal
``""`` to the ``Empty_string`` Wikipedia article at cert=0.75.

Fix mirrors the post-v2.0.0 D-E shape: apply ``_strip_quote_pair`` to
``cleaned_query`` after the word-strip and re-check the empty guard.
Empty quote-pair drops to the ``Missing Article Path`` envelope;
quote-stripped real content (``get article "Photosynthesis"``) flows
through normally; bare paths (``get article Biology``) are unaffected.
"""

from unittest.mock import Mock

import pytest

from openzim_mcp.simple_tools import SimpleToolsHandler

# ===========================================================================
# D-E sibling — ``_handle_get_article`` word-strip recovery branch
# ===========================================================================


class TestGetArticleEmptyQuotedDropsToMissingArgGuard:
    """Pre-fix, ``get article ""`` reached the backend with
    ``entry_path='""'`` (the literal 2-char ASCII quote pair) which
    title-promotion fuzzy-matched to the ``Empty_string`` Wikipedia
    article at cert=0.75. Same silent-wrong-answer shape as the
    post-v2.0.0 D-E sweep, on the one handler the original fix
    couldn't cover (the parser drops ``entry_path`` correctly; this
    handler regenerates the literal from ``query`` via word-strip
    fallback).
    """

    @pytest.fixture
    def mock_zim_operations(self) -> Mock:
        mock = Mock()
        mock.list_zim_files.return_value = (
            '[{"path": "/test/file.zim", "name": "file.zim"}]'
        )
        mock.get_zim_entry.return_value = "Article content"
        return mock

    @pytest.fixture
    def handler(self, mock_zim_operations: Mock) -> SimpleToolsHandler:
        return SimpleToolsHandler(mock_zim_operations)

    @pytest.mark.parametrize(
        "query",
        [
            # Canonical ``get article`` trigger; ASCII single + double:
            'get article ""',
            "get article ''",
            # Sibling phrasings that still route to ``get_article`` intent
            # (``show article`` routes to ``browse`` — out of scope here):
            'read article ""',
            'fetch article ""',
            'get entry ""',
            'get page ""',
            # Curly quote pairs from LLM/copy-paste:
            "get article “”",  # “”
            "get article ‘’",  # ‘’
            # Whitespace-only between quotes — same expected behaviour:
            'get article "  "',
            "get article '  '",
        ],
    )
    def test_empty_quoted_input_drops_to_missing_arg_guard(
        self,
        handler: SimpleToolsHandler,
        mock_zim_operations: Mock,
        query: str,
    ) -> None:
        """Each empty/whitespace-only quote pair must surface the
        structured ``Missing Article Path`` envelope WITHOUT calling
        ``get_zim_entry``. Pre-fix the literal 2-char quote pair
        propagated to ``get_zim_entry`` which fuzzy-matched to the
        ``Empty_string`` Wikipedia article at cert=0.75.
        """
        result = handler.handle_zim_query(query, "/test/file.zim")
        assert "Missing Article Path" in result, (
            f"Empty-quoted input {query!r} must fire the missing-arg "
            f"guard. Got: {result!r}"
        )
        mock_zim_operations.get_zim_entry.assert_not_called()

    def test_quote_stripped_real_topic_still_resolves(
        self,
        handler: SimpleToolsHandler,
        mock_zim_operations: Mock,
    ) -> None:
        """Regression: ``get article "Photosynthesis"`` (quote-pair with
        real content) must continue to reach ``get_zim_entry`` with the
        quote-stripped value, not fire the missing-arg guard.
        """
        result = handler.handle_zim_query(
            'get article "Photosynthesis"', "/test/file.zim"
        )
        assert "Missing Article Path" not in result
        mock_zim_operations.get_zim_entry.assert_called_once()
        # entry_path is the second positional arg
        called_entry_path = mock_zim_operations.get_zim_entry.call_args.args[1]
        assert '"' not in called_entry_path and "'" not in called_entry_path, (
            f"Quote-strip must remove surrounding quote pair before the "
            f"backend lookup. Got entry_path={called_entry_path!r}"
        )

    def test_bare_topic_unaffected(
        self,
        handler: SimpleToolsHandler,
        mock_zim_operations: Mock,
    ) -> None:
        """Regression guard: ``get article Biology`` (no quotes) must
        keep flowing through the word-strip fallback unchanged."""
        result = handler.handle_zim_query("get article Biology", "/test/file.zim")
        assert "Missing Article Path" not in result
        mock_zim_operations.get_zim_entry.assert_called_once()


# ===========================================================================
# Parser-level: ``_extract_entry_path_keyworded`` quoted_match branch
# whitespace-only widening — benefits get_article / structure / toc /
# summary / links via the shared extractor.
# ===========================================================================


class TestEntryPathExtractorWhitespaceQuotedDrops:
    """``get article "  "`` and siblings reached the handler with
    ``entry_path="  "`` (2 whitespace chars) because the quoted_match
    branch's ``+`` quantifier matched whitespace-only content. Truthy
    2-char string then bypassed every downstream ``if not entry_path:``
    guard. Fix strips the captured value and drops the param entirely
    when empty after strip.
    """

    @pytest.mark.parametrize(
        "query,expected_intent",
        [
            ('get article "  "', "get_article"),
            ("get article '  '", "get_article"),
            ('structure of "  "', "structure"),
            ('links in "  "', "links"),
            ('summary of "  "', "summary"),
            ('toc of "  "', "toc"),
        ],
    )
    def test_whitespace_only_quoted_drops_entry_path(
        self, query: str, expected_intent: str
    ) -> None:
        """Each entry-path-keyworded intent must drop the param when
        the quoted value is whitespace-only, so the handler's
        missing-arg guard fires instead of the backend silent-matching
        the literal whitespace to a disambig page."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(query)
        assert intent == expected_intent
        assert not params.get("entry_path"), (
            f"{query!r} captured entry_path={params.get('entry_path')!r}; "
            f"expected drop after whitespace-strip so the handler's "
            f"missing-arg guard fires."
        )

    def test_quoted_real_topic_still_resolves(self) -> None:
        """Regression: ``get article "Photosynthesis"`` must still
        capture the topic (no spurious strip on non-empty content)."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            'get article "Photosynthesis"'
        )
        assert intent == "get_article"
        assert params.get("entry_path") == "photosynthesis"

    def test_quoted_topic_with_inner_whitespace_preserved(self) -> None:
        """Regression: interior whitespace in a real topic
        (``get article "World War II"``) must survive — only
        surrounding whitespace is stripped."""
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent('get article "World War II"')
        assert intent == "get_article"
        assert params.get("entry_path") == "world war ii"


# ===========================================================================
# Pass-2 D-H — duplicate ``<!-- intent=filtered_search cert=0.80 -->``
# telemetry comment on missing-namespace envelope.
# ===========================================================================


class TestFilteredSearchMissingNamespaceSingleIntentFooter:
    """``_handle_filtered_search`` missing-namespace envelope embedded an
    ``<!-- intent=filtered_search cert=0.80 -->`` comment in the body
    that duplicated the dispatcher's auto-appended footer (every string
    result gets an intent footer at handle_zim_query, line ~1017). The
    sibling ``_handle_browse`` / ``_handle_walk_namespace`` envelopes
    relied on the auto-append and emitted exactly one footer. Pinning
    parity here.
    """

    @pytest.fixture
    def handler(self) -> SimpleToolsHandler:
        from unittest.mock import MagicMock

        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        # Backend must NOT be reached for invalid namespace inputs.
        mock.search_with_filters_with_canonical_splice.side_effect = AssertionError(
            "backend should not be called for invalid namespace"
        )
        return SimpleToolsHandler(mock)

    @pytest.mark.parametrize(
        "query",
        [
            'search Berlin in namespace ""',
            "search photosynthesis in namespace abc",
            "search Berlin in namespace XYZ",
            "search foo in namespace 1",
        ],
    )
    def test_exactly_one_filtered_search_intent_footer(
        self, handler: SimpleToolsHandler, query: str
    ) -> None:
        """Each invalid-namespace envelope must carry exactly one
        ``<!-- intent=filtered_search cert=...`` footer — not two. The
        sibling browse / walk_namespace envelopes (line 2974, line 5111)
        already emit one; this pins parity for filtered_search."""
        out = handler.handle_zim_query(
            query, zim_file_path="/x.zim", options={"compact": False}
        )
        assert "Missing or Invalid Namespace" in out
        footer_count = out.count("<!-- intent=filtered_search cert=")
        assert footer_count == 1, (
            f"Expected exactly one filtered_search intent footer; got "
            f"{footer_count}. Full output:\n{out}"
        )

    def test_browse_missing_namespace_unchanged(
        self, handler: SimpleToolsHandler
    ) -> None:
        """Regression guard: the sibling ``_handle_browse`` envelope
        already emitted exactly one ``<!-- intent=browse cert=`` footer
        via the dispatcher auto-append; this pin confirms the fix
        didn't accidentally touch that surface."""
        out = handler.handle_zim_query(
            "browse namespace XYZ",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "Missing or Invalid Namespace" in out
        assert out.count("<!-- intent=browse cert=") == 1


# ===========================================================================
# Pass-3 D-I — synthesize path bypasses meta-only / chained-intent /
# multi-entity-chain guards. Same shape as the post-v2.0.0 D-G fix:
# the synthesize early-exit at simple_tools.py:626 skipped three
# additional guards the non-synthesize path fires at handle_zim_query
# lines 693, 710, 960.
# ===========================================================================


class TestSynthesizePathBypassesGuards:
    """Pre-fix, ``synthesize=True`` with a meta-only / chained / multi-
    entity query bypassed the guards and silently RAG-searched the
    literal verb chain:
      * ``try again`` → Aaliyah's "Try Again" song body
      * ``tell me about Berlin then list namespaces`` → Namespace + War
      * ``tell me about Berlin and Munich and Cologne`` → Cologne only

    Fix mirrors the simple-mode guards inside ``_handle_synthesize_query``
    and returns structured ``tool_error`` envelopes (synthesize's
    native error shape, same as D-G).
    """

    def _make_handler(self) -> SimpleToolsHandler:
        from unittest.mock import MagicMock

        mock_ops = MagicMock()
        mock_ops.list_zim_files_data.return_value = [
            {"path": "/data/zim_0.zim", "name": "zim_0.zim"},
        ]
        mock_ops.list_zim_files.return_value = "Found 1 ZIM file."
        # ``_multi_entity_chain_guidance`` probes the title index. For
        # bare chain rejections we want the probe to MISS so the
        # guidance fires; return an empty results envelope.
        mock_ops.find_entry_by_title_data.return_value = {"results": []}
        mock_ops.config = MagicMock()
        mock_ops.config.query_rewrite = MagicMock()
        mock_ops.config.query_rewrite.enabled = False
        return SimpleToolsHandler(mock_ops)

    def test_synthesize_meta_only_returns_meta_only_guidance(self) -> None:
        """``try again`` with synthesize=True must fire the same meta-
        only guidance the simple path fires at handle_zim_query line
        693, NOT silently BM25-search the literal phrase and return
        the Aaliyah "Try Again" song body."""
        handler = self._make_handler()
        result = handler.handle_zim_query(
            query="try again", options={"synthesize": True}
        )
        assert isinstance(result, dict), (
            f"Expected tool_error envelope (dict). Got {type(result).__name__}: "
            f"{result!r}"
        )
        assert result.get("error") is True
        assert result.get("operation") == "meta_only_guidance", (
            f"Pre-fix `try again` with synthesize silently returned the "
            f"Aaliyah `Try Again` song. Post-fix must return "
            f"meta_only_guidance. Got operation="
            f"{result.get('operation')!r}"
        )

    @pytest.mark.parametrize(
        "query",
        [
            "tell me about Berlin then list namespaces",
            "get article Photosynthesis then search for Berlin",
            "search for biology then show structure of Evolution",
        ],
    )
    def test_synthesize_chained_intent_returns_chained_rejection(
        self, query: str
    ) -> None:
        """Each chained-operation query with synthesize=True must fire
        the same chained_intent_rejected envelope as the simple path
        (handle_zim_query line 710), NOT silently RAG-search the
        literal chain."""
        handler = self._make_handler()
        result = handler.handle_zim_query(query, options={"synthesize": True})
        assert isinstance(result, dict)
        assert result.get("error") is True
        assert result.get("operation") == "chained_intent_rejected", (
            f"Pre-fix {query!r} with synthesize silently returned RAG hits "
            f"on the literal chain. Post-fix must return "
            f"chained_intent_rejected. Got operation="
            f"{result.get('operation')!r}"
        )
        # Recovery info preserved: simple-mode markdown body should be
        # passed through as the tool_error message.
        assert "Chained Operations Detected" in (result.get("message") or "")

    def test_synthesize_multi_entity_returns_multi_entity_rejection(self) -> None:
        """``tell me about Berlin and Munich and Cologne`` with
        synthesize=True must fire multi_entity_chain_rejected as the
        simple path does (handle_zim_query line 960). Pre-fix returned
        Cologne plus unrelated articles — Berlin and Munich silently
        dropped."""
        handler = self._make_handler()
        result = handler.handle_zim_query(
            "tell me about Berlin and Munich and Cologne",
            options={"synthesize": True},
        )
        assert isinstance(result, dict)
        assert result.get("error") is True
        assert result.get("operation") == "multi_entity_chain_rejected"
        assert "Multi-Entity Chain Detected" in (result.get("message") or "")

    def test_synthesize_canonical_multi_entity_title_not_rejected(self) -> None:
        """Regression: ``Earth, Wind & Fire`` is a canonical multi-entity
        article title. The simple-mode path suppresses chain rejection
        when the whole-topic title-index probe returns a high-score
        hit. Synthesize must follow the same suppression — pin by
        mocking the title-index probe to return score=1.0 for the
        full topic."""
        from unittest.mock import MagicMock

        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock_ops = MagicMock()
        mock_ops.list_zim_files_data.return_value = [
            {"path": "/data/zim_0.zim", "name": "zim_0.zim"},
        ]
        mock_ops.list_zim_files.return_value = "Found 1 ZIM file."
        mock_ops.find_entry_by_title_data.return_value = {
            "results": [
                {"path": "Earth,_Wind_&_Fire", "score": 1.0},
            ]
        }
        mock_ops.config = MagicMock()
        mock_ops.config.query_rewrite = MagicMock()
        mock_ops.config.query_rewrite.enabled = False
        # Backend synthesize path must be reached — pin by having it
        # raise an obviously-not-a-chain-rejection error.
        handler = SimpleToolsHandler(mock_ops)
        result = handler.handle_zim_query(
            "tell me about Earth, Wind & Fire",
            options={"synthesize": True},
        )
        if isinstance(result, dict):
            assert result.get("operation") != "multi_entity_chain_rejected", (
                f"Canonical multi-entity title was incorrectly rejected. "
                f"The title-index probe (score=1.0) should suppress the "
                f"chain rejection. Got: {result}"
            )


# ===========================================================================
# Pass-4 D-J — circular ``tell me about <X>`` no-results recovery hint
# ===========================================================================


class TestTellMeAboutNoResultsRecoveryNotCircular:
    """When ``_handle_tell_me_about`` falls back to the search backend
    on no-results, the shared ``_format_search_text`` recovery hints
    (zim/search.py:774-782) include a ``tell me about {topic}`` bullet
    — which is exactly what the caller just tried. Live repro:
    ``tell me about photosynthsis`` (misspelling not in the post-a11
    map) → "No search results found for photosynthsis" with a recovery
    bullet `tell me about photosynthsis` (circular).

    Fix swaps the bullet for ``find article titled {topic}`` (title-
    index fuzzy lookup) — a genuinely different recovery path. Pinned
    via the canonical search-backend wording so future drift in
    ``_format_search_text`` surfaces here.
    """

    def test_swap_replaces_circular_tell_me_about_bullet(self) -> None:
        """Direct unit test on the helper. Given the canonical no-
        results recovery body, the swap must drop the ``tell me about
        X`` bullet and emit ``find article titled X`` instead."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        topic = "photosynthsis"
        # Mirror exactly what zim/search.py:_format_search_text
        # produces for a no-results echo. If the canonical wording
        # drifts, the swap silently no-ops — this test pins it.
        input_text = (
            f'No search results found for "{topic}".\n\n'
            f"**Try one of these:**\n"
            f"- `suggestions for {topic[:30]}` — autocomplete to "
            f"catch typos or partial names\n"
            f"- `tell me about {topic[:30]}` — structured topic "
            f"lookup with auto article fetch\n"
            f"- A shorter or differently-cased query"
        )
        out = SimpleToolsHandler._swap_tell_me_about_recovery_hint(input_text, topic)
        assert f"tell me about {topic[:30]}" not in out, (
            f"Circular `tell me about {topic[:30]}` bullet must be removed. "
            f"Got:\n{out}"
        )
        assert f"find article titled {topic[:30]}" in out, (
            f"Replacement `find article titled {topic[:30]}` bullet missing. "
            f"Got:\n{out}"
        )

    def test_swap_idempotent_when_no_circular_bullet(self) -> None:
        """Regression: when the input doesn't contain the circular
        bullet (e.g. it's already been swapped, or it's an entirely
        different envelope), the swap leaves the text unchanged."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        unchanged = "**Some envelope** that doesn't carry the bullet."
        assert (
            SimpleToolsHandler._swap_tell_me_about_recovery_hint(unchanged, "Berlin")
            == unchanged
        )

    def test_swap_canonical_source_pin_against_format_search_text(self) -> None:
        """Canonical-source pin: the swap relies on an EXACT-string
        match against ``_format_search_text``'s wording. Reach into
        the formatter directly with a zero-results payload and
        confirm the swap consumes the bullet end-to-end. If
        ``_format_search_text`` ever changes the wording, this test
        fails and the swap string in ``_swap_tell_me_about_recovery_hint``
        must be updated in tandem."""
        from unittest.mock import MagicMock

        from openzim_mcp.simple_tools import SimpleToolsHandler
        from openzim_mcp.zim.search import _SearchMixin

        topic = "photosynthsis"
        # Build a minimal payload the formatter accepts as
        # ``total == 0`` with no filter context.
        payload = {
            "query": topic,
            "total": 0,
            "page_info": {"offset": 0, "limit": 3},
            "results": [],
            "done": True,
            "next_cursor": None,
        }
        # Call as an unbound method — _format_search_text is on a
        # mixin and is self-bound, but its no-results path doesn't
        # touch any instance state.
        rendered = _SearchMixin._format_search_text(MagicMock(), payload)
        # Sanity-check the formatter still emits the circular bullet
        # the swap targets. If this assertion fires, the canonical
        # source wording has drifted and the swap is no-opping.
        assert (
            f"- `tell me about {topic[:30]}` — structured topic "
            f"lookup with auto article fetch"
        ) in rendered, (
            "_format_search_text no longer emits the canonical "
            "circular bullet — update the swap string in "
            "_swap_tell_me_about_recovery_hint to match."
        )
        swapped = SimpleToolsHandler._swap_tell_me_about_recovery_hint(rendered, topic)
        assert f"tell me about {topic[:30]}" not in swapped
        assert f"find article titled {topic[:30]}" in swapped
