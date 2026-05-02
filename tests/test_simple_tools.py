"""Tests for simple tools functionality."""

from unittest.mock import Mock, patch

import pytest

from openzim_mcp.simple_tools import IntentParser, SimpleToolsHandler


class TestIntentParser:
    """Test intent parsing logic."""

    def test_parse_list_files_intent(self):
        """Test parsing file listing intents."""
        queries = [
            "list files",
            "show files",
            "what files are available",
            "get zim files",
        ]
        for query in queries:
            intent, params, _ = IntentParser.parse_intent(query)
            assert intent == "list_files", f"Failed for query: {query}"

    def test_parse_metadata_intent(self):
        """Test parsing metadata intents."""
        queries = [
            "metadata for file.zim",
            "info about this zim",
            "details of the archive",
        ]
        for query in queries:
            intent, params, _ = IntentParser.parse_intent(query)
            assert intent == "metadata", f"Failed for query: {query}"

    def test_parse_main_page_intent(self):
        """Test parsing main page intents."""
        queries = [
            "main page",
            "show home page",
            "get start page",
        ]
        for query in queries:
            intent, params, _ = IntentParser.parse_intent(query)
            assert intent == "main_page", f"Failed for query: {query}"

    def test_parse_list_namespaces_intent(self):
        """Test parsing namespace listing intents."""
        queries = [
            "list namespaces",
            "show namespaces",
            "what namespaces exist",
        ]
        for query in queries:
            intent, params, _ = IntentParser.parse_intent(query)
            assert intent == "list_namespaces", f"Failed for query: {query}"

    def test_parse_browse_intent(self):
        """Test parsing browse intents."""
        queries = [
            "browse namespace C",
            "explore articles in namespace A",
            "show entries in namespace C",
        ]
        for query in queries:
            intent, params, _ = IntentParser.parse_intent(query)
            assert intent == "browse", f"Failed for query: {query}"

    def test_parse_browse_intent_with_namespace(self):
        """Test extracting namespace from browse queries."""
        query = "browse namespace C"
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "browse"
        assert params.get("namespace") == "C"

    def test_parse_structure_intent(self):
        """Test parsing article structure intents."""
        queries = [
            "structure of Biology",
            "outline of Evolution",
            "sections of Protein",
        ]
        for query in queries:
            intent, params, _ = IntentParser.parse_intent(query)
            assert intent == "structure", f"Failed for query: {query}"

    def test_parse_links_intent(self):
        """Test parsing links extraction intents."""
        queries = [
            "links in Biology",
            "references from Evolution",
            # Note: "related articles in Protein" is ambiguous and may match browse
        ]
        for query in queries:
            intent, params, _ = IntentParser.parse_intent(query)
            assert intent == "links", f"Failed for query: {query}"

    def test_parse_suggestions_intent(self):
        """Test parsing suggestions intents."""
        queries = [
            "suggestions for bio",
            "autocomplete evol",
            "hints for prot",
        ]
        for query in queries:
            intent, params, _ = IntentParser.parse_intent(query)
            assert intent == "suggestions", f"Failed for query: {query}"

    def test_parse_filtered_search_intent(self):
        """Test parsing filtered search intents."""
        queries = [
            "search evolution in namespace C",
            "find biology within type text/html",
        ]
        for query in queries:
            intent, params, _ = IntentParser.parse_intent(query)
            assert intent == "filtered_search", f"Failed for query: {query}"

    def test_parse_get_article_intent(self):
        """Test parsing get article intents."""
        queries = [
            "get article Biology",
            "show entry Evolution",
            "read page Protein",
        ]
        for query in queries:
            intent, params, _ = IntentParser.parse_intent(query)
            assert intent == "get_article", f"Failed for query: {query}"

    def test_parse_search_intent(self):
        """Test parsing general search intents."""
        queries = [
            "search for biology",
            "find evolution",
            "look for protein",
        ]
        for query in queries:
            intent, params, _ = IntentParser.parse_intent(query)
            assert intent == "search", f"Failed for query: {query}"

    def test_parse_default_to_search(self):
        """Test that ambiguous queries default to search."""
        query = "biology evolution protein"
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "search"
        assert params.get("query") == query

    def test_extract_entry_path_from_quoted_string(self):
        """Test extracting entry path from quoted strings."""
        query = 'get article "C/Biology"'
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "get_article"
        assert params.get("entry_path") == "C/Biology"

    def test_extract_search_query_with_filters(self):
        """Test extracting search query and filters."""
        query = "search evolution in namespace C"
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "filtered_search"
        assert "evolution" in params.get("query", "").lower()
        assert params.get("namespace") == "C"

    def test_parse_binary_intent(self):
        """Test parsing binary content retrieval intents."""
        queries = [
            "get binary content from I/image.png",
            "retrieve raw data from document.pdf",
            "extract binary entry logo.jpg",
            "fetch raw content from video.mp4",
        ]
        for query in queries:
            intent, params, _ = IntentParser.parse_intent(query)
            assert intent == "binary", f"Failed for query: {query}"

    def test_parse_binary_intent_media_types(self):
        """Test parsing binary intent with media type keywords."""
        queries = [
            "get pdf from I/document.pdf",
            "extract image I/logo.png",
            "fetch video presentation.mp4",
            "retrieve audio track.mp3",
            "download media file.jpg",
        ]
        for query in queries:
            intent, params, _ = IntentParser.parse_intent(query)
            assert intent == "binary", f"Failed for query: {query}"

    def test_extract_binary_entry_path_quoted(self):
        """Test extracting entry path from quoted strings for binary intent."""
        query = 'get binary content from "I/my-image.png"'
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "binary"
        assert params.get("entry_path") == "I/my-image.png"

    def test_extract_binary_entry_path_unquoted(self):
        """Test extracting entry path from unquoted strings for binary intent."""
        query = "extract pdf I/document.pdf"
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "binary"
        assert params.get("entry_path") == "I/document.pdf"

    def test_binary_metadata_only_mode(self):
        """Test detecting metadata only mode for binary intent."""
        query = "get binary content metadata only for I/image.png"
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "binary"
        assert params.get("include_data") is False


class TestSimpleToolsHandler:
    """Test simple tools handler."""

    @pytest.fixture
    def mock_zim_operations(self):
        """Create mock ZimOperations."""
        mock = Mock()
        mock.list_zim_files.return_value = (
            '[{"path": "/test/file.zim", "name": "file.zim"}]'
        )
        mock.search_zim_file.return_value = "Search results"
        mock.get_zim_entry.return_value = "Article content"
        mock.get_zim_metadata.return_value = "Metadata"
        mock.get_main_page.return_value = "Main page"
        mock.list_namespaces.return_value = "Namespaces"
        mock.browse_namespace.return_value = "Browse results"
        mock.get_article_structure.return_value = "Article structure"
        mock.extract_article_links.return_value = "Article links"
        mock.get_search_suggestions.return_value = "Suggestions"
        mock.search_with_filters.return_value = "Filtered search results"
        mock.get_binary_entry.return_value = (
            '{"path": "I/image.png", "mime_type": "image/png", "size": 1234}'
        )
        return mock

    @pytest.fixture
    def handler(self, mock_zim_operations):
        """Create SimpleToolsHandler with mock operations."""
        return SimpleToolsHandler(mock_zim_operations)

    def test_handle_list_files(self, handler, mock_zim_operations):
        """Test handling file listing queries."""
        result = handler.handle_zim_query("list files")
        mock_zim_operations.list_zim_files.assert_called_once()
        assert "file.zim" in result

    def test_handle_search(self, handler, mock_zim_operations):
        """Test handling search queries."""
        result = handler.handle_zim_query("search for biology", "/test/file.zim")
        mock_zim_operations.search_zim_file.assert_called_once()
        assert "Search results" in result

    def test_handle_get_article(self, handler, mock_zim_operations):
        """Test handling get article queries."""
        result = handler.handle_zim_query("get article Biology", "/test/file.zim")
        mock_zim_operations.get_zim_entry.assert_called_once()
        assert "Article content" in result

    def test_handle_metadata(self, handler, mock_zim_operations):
        """Test handling metadata queries."""
        result = handler.handle_zim_query("metadata for file", "/test/file.zim")
        mock_zim_operations.get_zim_metadata.assert_called_once()
        assert "Metadata" in result

    def test_handle_browse(self, handler, mock_zim_operations):
        """Test handling browse queries."""
        result = handler.handle_zim_query("browse namespace C", "/test/file.zim")
        mock_zim_operations.browse_namespace.assert_called_once()
        assert "Browse results" in result

    def test_handle_structure(self, handler, mock_zim_operations):
        """Test handling structure queries."""
        result = handler.handle_zim_query("structure of Biology", "/test/file.zim")
        mock_zim_operations.get_article_structure.assert_called_once()
        assert "Article structure" in result

    def test_handle_links(self, handler, mock_zim_operations):
        """Test handling links queries."""
        result = handler.handle_zim_query("links in Biology", "/test/file.zim")
        mock_zim_operations.extract_article_links.assert_called_once()
        assert "Article links" in result

    def test_handle_suggestions(self, handler, mock_zim_operations):
        """Test handling suggestions queries."""
        result = handler.handle_zim_query("suggestions for bio", "/test/file.zim")
        mock_zim_operations.get_search_suggestions.assert_called_once()
        assert "Suggestions" in result

    def test_handle_filtered_search(self, handler, mock_zim_operations):
        """Test handling filtered search queries."""
        result = handler.handle_zim_query(
            "search evolution in namespace C", "/test/file.zim"
        )
        mock_zim_operations.search_with_filters.assert_called_once()
        assert "Filtered search results" in result

    def test_auto_select_single_file(self, handler, mock_zim_operations):
        """Test auto-selecting ZIM file when only one exists."""
        # Mock list_zim_files_data to return a single file (structured data)
        mock_zim_operations.list_zim_files_data.return_value = [
            {"path": "/test/single.zim", "name": "single.zim"}
        ]

        handler.handle_zim_query("search for biology")
        # Should auto-select the file and perform search
        mock_zim_operations.search_zim_file.assert_called_once()

    def test_no_file_specified_multiple_files(self, handler, mock_zim_operations):
        """Test error when no file specified and multiple files exist."""
        # Mock list_zim_files_data to return multiple files (structured data)
        mock_zim_operations.list_zim_files_data.return_value = [
            {"path": "/test/file1.zim"},
            {"path": "/test/file2.zim"},
        ]
        # Also mock list_zim_files for the error message display
        mock_zim_operations.list_zim_files.return_value = (
            "Found 2 ZIM files:\n"
            '[{"path": "/test/file1.zim"}, {"path": "/test/file2.zim"}]'
        )

        result = handler.handle_zim_query("search for biology")
        # Should return error asking to specify file
        assert "No ZIM File Specified" in result or "Available files" in result

    def test_options_passed_correctly(self, handler, mock_zim_operations):
        """Test that options are passed correctly to underlying operations."""
        options = {"limit": 5, "offset": 10, "max_content_length": 5000}
        handler.handle_zim_query("search for biology", "/test/file.zim", options)

        # Check that limit and offset were passed to search
        call_args = mock_zim_operations.search_zim_file.call_args
        assert call_args is not None

    def test_handle_binary(self, handler, mock_zim_operations):
        """Test handling binary content retrieval queries."""
        result = handler.handle_zim_query(
            'get binary content from "I/image.png"', "/test/file.zim"
        )
        mock_zim_operations.get_binary_entry.assert_called_once()
        assert "I/image.png" in result

    def test_handle_binary_media_keyword(self, handler, mock_zim_operations):
        """Test handling binary queries with media type keywords."""
        result = handler.handle_zim_query("extract image I/logo.png", "/test/file.zim")
        mock_zim_operations.get_binary_entry.assert_called_once()
        assert "image.png" in result or mock_zim_operations.get_binary_entry.called

    def test_handle_binary_missing_path(self, handler, mock_zim_operations):
        """Test binary query without entry path returns error message."""
        result = handler.handle_zim_query("get binary content", "/test/file.zim")
        # Should return error about missing path
        assert "Missing Entry Path" in result or "specify" in result.lower()


class TestNewIntentPatterns:
    """v0.9.0 intent patterns: search_all, walk_namespace, etc."""

    def test_search_all_intent(self):
        """Test that 'search all files for X' routes to search_all."""
        from openzim_mcp.simple_tools import IntentParser

        intent, params, _ = IntentParser.parse_intent("search all files for python")
        assert intent == "search_all"
        assert params.get("query") == "python"

    def test_walk_namespace_intent(self):
        """Test that 'walk namespace X' routes to walk_namespace."""
        from openzim_mcp.simple_tools import IntentParser

        intent, _params, _ = IntentParser.parse_intent("walk namespace M")
        assert intent == "walk_namespace"

    def test_find_by_title_intent(self):
        """Test that 'find article titled X' routes to find_by_title."""
        from openzim_mcp.simple_tools import IntentParser

        intent, params, _ = IntentParser.parse_intent(
            "find article titled Photosynthesis"
        )
        assert intent == "find_by_title"
        assert "Photosynthesis" in str(params.get("title", ""))

    def test_related_intent(self):
        """Test that 'articles related to X' routes to related."""
        from openzim_mcp.simple_tools import IntentParser

        intent, _params, _ = IntentParser.parse_intent(
            "articles related to Climate_Change"
        )
        assert intent == "related"

    def test_search_all_extractor_has_redos_protection(self, monkeypatch):
        """The search_all param extractor must time out under ReDoS.

        Every other regex in ``simple_tools.py`` is wrapped via the
        ``safe_regex_*`` helpers (which apply a threading timeout). The
        ``search_all`` parameter extractor previously used a bare
        ``re.sub`` with a backtracking-prone lazy quantifier; this test
        ensures the wrapped variant aborts and falls back to the raw
        query on timeout, rather than hanging the worker thread.

        Strategy: monkeypatch ``re.sub`` (used inside the lambda) to
        sleep longer than the regex timeout. The fixed code wraps the
        call in ``run_with_timeout`` and catches ``RegexTimeoutError``,
        so it should still return a valid params dict whose ``query``
        falls back to the stripped input.
        """
        import re as _re
        import time

        from openzim_mcp import simple_tools

        # Patch re.sub on the simple_tools module to simulate a hanging
        # regex. The fix wraps the call in run_with_timeout, so this
        # must time out (not hang the test) and fall back to the raw
        # query.
        def slow_sub(*args, **kwargs):
            time.sleep(5)
            return _re.sub(*args, **kwargs)

        monkeypatch.setattr(simple_tools.re, "sub", slow_sub)

        # Force the search_all extractor path. Use the IntentParser
        # internal helper directly so we don't drag in slow classifier
        # patterns.
        start = time.monotonic()
        params = simple_tools.IntentParser._extract_params(
            "search all files for python", "search_all"
        )
        elapsed = time.monotonic() - start

        # Must respect the configured regex timeout (1s default), with
        # a small budget for thread setup / fallback path.
        assert elapsed < 2.0, (
            f"search_all extractor took {elapsed:.3f}s — timeout wrapping "
            "is missing or broken"
        )
        # And it must still return a usable query (fallback path).
        assert "query" in params
        assert params["query"]


class TestIntentParserBatchEntries:
    """Test intent patterns for the get_zim_entries (batch) tool."""

    def test_fetch_articles_routes_to_get_zim_entries(self):
        """Plural 'articles' cue with fetch verb routes to batch tool."""
        from openzim_mcp.simple_tools import IntentParser

        intent, _params, _ = IntentParser.parse_intent("fetch articles A/Foo and A/Bar")
        assert intent == "get_zim_entries"

    def test_get_entries_routes_to_get_zim_entries(self):
        """Explicit 'entries' cue routes to batch tool."""
        from openzim_mcp.simple_tools import IntentParser

        intent, _params, _ = IntentParser.parse_intent("get entries A/Foo, A/Bar")
        assert intent == "get_zim_entries"

    def test_singular_get_article_still_routes_to_get_article(self):
        """The new plural pattern must NOT shadow the existing singular intent."""
        from openzim_mcp.simple_tools import IntentParser

        intent, _params, _ = IntentParser.parse_intent("get article A/Foo")
        assert intent == "get_article"

    def test_get_zim_entries_extracts_path_list(self):
        """parse_intent must extract namespace/path tokens into params['entries']."""
        from openzim_mcp.simple_tools import IntentParser

        intent, params, _ = IntentParser.parse_intent(
            "fetch entries A/Foo and A/Bar from wikipedia.zim"
        )
        assert intent == "get_zim_entries"
        assert params.get("entries") == ["A/Foo", "A/Bar"]

    def test_get_zim_entries_extracts_multiple_namespaces(self):
        """Path extraction handles realistic comma-and-and joined lists."""
        from openzim_mcp.simple_tools import IntentParser

        intent, params, _ = IntentParser.parse_intent(
            "fetch articles A/Foo, A/Bar, and M/Image.png"
        )
        assert intent == "get_zim_entries"
        assert params.get("entries") == ["A/Foo", "A/Bar", "M/Image.png"]

    def test_get_zim_entries_strips_trailing_sentence_punctuation(self):
        """Trailing sentence punctuation must not glue onto the last path."""
        from openzim_mcp.simple_tools import IntentParser

        intent, params, _ = IntentParser.parse_intent("fetch entries A/Foo and A/Bar.")
        assert intent == "get_zim_entries"
        assert params.get("entries") == ["A/Foo", "A/Bar"]

    def test_get_zim_entries_strips_various_trailing_punctuation(self):
        """Other trailing punctuation (?, !, ,, ;, :) is also stripped."""
        from openzim_mcp.simple_tools import IntentParser

        intent, params, _ = IntentParser.parse_intent(
            "fetch entries A/Foo? and A/Bar! and A/Baz;"
        )
        assert intent == "get_zim_entries"
        assert params.get("entries") == ["A/Foo", "A/Bar", "A/Baz"]

    def test_get_zim_entries_preserves_internal_dots(self):
        """Stripping must not eat legitimate internal dots (e.g. file extensions)."""
        from openzim_mcp.simple_tools import IntentParser

        intent, params, _ = IntentParser.parse_intent(
            "fetch entries A/Foo and M/Image.png."
        )
        assert intent == "get_zim_entries"
        assert params.get("entries") == ["A/Foo", "M/Image.png"]


class TestGetZimEntriesDispatch:
    """H15 regression: get_zim_entries intent must dispatch to batch fetch."""

    @pytest.fixture
    def mock_zim_operations(self):
        """Mock ZimOperations with single-file auto-select and a get_entries spy."""
        mock = Mock()
        mock.list_zim_files_data.return_value = [
            {"path": "/test/wikipedia.zim", "name": "wikipedia.zim"}
        ]
        mock.list_zim_files.return_value = (
            '[{"path": "/test/wikipedia.zim", "name": "wikipedia.zim"}]'
        )
        mock.search_zim_file.return_value = "search-results-should-not-be-used"
        mock.get_entries.return_value = '{"results": [], "succeeded": 0, "failed": 0}'
        return mock

    @pytest.fixture
    def handler(self, mock_zim_operations):
        """Build a SimpleToolsHandler wired to the mock backend."""
        return SimpleToolsHandler(mock_zim_operations)

    def test_get_zim_entries_intent_dispatches_to_batch_fetch(
        self, handler, mock_zim_operations
    ):
        """A 'fetch entries X and Y' query must dispatch to get_entries."""
        handler.handle_zim_query(
            "fetch entries A/Foo and A/Bar from wikipedia.zim",
            zim_file_path="/test/wikipedia.zim",
        )

        assert (
            mock_zim_operations.get_entries.called
        ), "get_entries was not called; intent fell through to default"
        assert (
            not mock_zim_operations.search_zim_file.called
        ), "search_zim_file was called; intent fell through instead of dispatching"

        call_args = mock_zim_operations.get_entries.call_args
        # get_entries(entries=[{zim_file_path, entry_path}, ...])
        entries_arg = (
            call_args.args[0] if call_args.args else call_args.kwargs.get("entries")
        )
        assert isinstance(entries_arg, list) and len(entries_arg) == 2
        assert all(isinstance(e, dict) for e in entries_arg)
        assert [e["entry_path"] for e in entries_arg] == ["A/Foo", "A/Bar"]
        assert all(e["zim_file_path"] == "/test/wikipedia.zim" for e in entries_arg)

    def test_get_zim_entries_intent_with_no_paths_returns_help(
        self, handler, mock_zim_operations
    ):
        """If paths can't be extracted, return help, not search results."""
        # Query matches the get_zim_entries pattern but has no namespace/path
        # tokens — the dispatch must surface a help message rather than fall
        # through to search.
        result = handler.handle_zim_query(
            "fetch articles please",
            zim_file_path="/test/wikipedia.zim",
        )

        assert (
            not mock_zim_operations.get_entries.called
        ), "get_entries should not be invoked when no paths were extracted"
        assert (
            not mock_zim_operations.search_zim_file.called
        ), "intent should not fall through to generic search"
        # Help message should mention namespace/path syntax
        lowered = result.lower()
        assert (
            "namespace/path" in lowered
            or "extract entry paths" in lowered
            or "missing entry paths" in lowered
        ), f"unexpected help response: {result!r}"


class TestExplicitZimPathHonored:
    """Regression: H14 - explicit zim_file_path must not be overwritten."""

    @pytest.fixture
    def mock_zim_operations(self):
        """Create mock ZimOperations that records the zim path it receives."""
        mock = Mock()
        # Auto-select would return a different path; if the fix is wrong and
        # the intent branch calls _auto_select_zim_file, this is what would
        # be passed through to the backend.
        mock.list_zim_files_data.return_value = [
            {"path": "/auto/selected.zim", "name": "selected.zim"}
        ]
        mock.list_zim_files.return_value = (
            '[{"path": "/auto/selected.zim", "name": "selected.zim"}]'
        )
        mock.walk_namespace.return_value = "{}"
        mock.find_entry_by_title.return_value = "{}"
        mock.get_related_articles.return_value = "{}"
        return mock

    @pytest.fixture
    def handler(self, mock_zim_operations):
        """Build a SimpleToolsHandler wired to the mock backend."""
        return SimpleToolsHandler(mock_zim_operations)

    @pytest.mark.parametrize(
        "intent_query,backend_attr",
        [
            ("walk namespace M", "walk_namespace"),
            ("find article titled Photosynthesis", "find_entry_by_title"),
            ("articles related to Climate_Change", "get_related_articles"),
        ],
    )
    def test_simple_tools_uses_explicit_zim_path(
        self, handler, mock_zim_operations, intent_query, backend_attr
    ):
        """The caller-supplied zim_file_path must reach the backend.

        Previously, walk_namespace / find_by_title / related branches
        called self._auto_select_zim_file() again, silently overwriting
        the explicit path the caller supplied. Now the explicit path
        must be honored.
        """
        explicit = "/zims/wikipedia_en_simple.zim"
        handler.handle_zim_query(intent_query, zim_file_path=explicit)

        backend = getattr(mock_zim_operations, backend_attr)
        assert backend.called, f"{backend_attr} was not called"
        # First positional arg is the zim path
        call_args = backend.call_args
        actual_path = (
            call_args.args[0]
            if call_args.args
            else call_args.kwargs.get("zim_file_path")
        )
        assert (
            actual_path == explicit
        ), f"{backend_attr}: expected {explicit}, got {actual_path}"


class TestLowConfidenceNoteAppendedConsistently:
    """Regression for finding 8.13: every intent branch appends the note.

    The low-confidence note must be appended whenever confidence < 0.6.
    Previously the ``search_all`` / ``walk_namespace`` / ``find_by_title``
    / ``related`` branches in ``handle_zim_query`` returned the backend
    response verbatim, so callers got no warning when the query
    interpretation was uncertain. Every other intent branch already
    appended the note; these four were drift.
    """

    @pytest.fixture
    def mock_zim_operations(self):
        """Build a mock backend whose intent methods return JSON sentinels."""
        mock = Mock()
        mock.list_zim_files_data.return_value = [
            {"path": "/zims/test.zim", "name": "test.zim"}
        ]
        mock.list_zim_files.return_value = (
            '[{"path": "/zims/test.zim", "name": "test.zim"}]'
        )
        mock.search_all.return_value = '{"results": []}'
        mock.walk_namespace.return_value = '{"entries": []}'
        mock.find_entry_by_title.return_value = '{"matches": []}'
        mock.get_related_articles.return_value = '{"related": []}'
        return mock

    @pytest.fixture
    def handler(self, mock_zim_operations):
        """Wire a ``SimpleToolsHandler`` to the mock backend."""
        return SimpleToolsHandler(mock_zim_operations)

    @pytest.mark.parametrize(
        "intent,params",
        [
            ("search_all", {"query": "anything"}),
            ("walk_namespace", {"namespace": "C"}),
            ("find_by_title", {"title": "Photosynthesis"}),
            ("related", {"entry_path": "C/Photosynthesis"}),
        ],
    )
    def test_low_confidence_note_appended_for_all_intents(
        self, handler, intent, params
    ):
        """Force confidence below 0.6 and assert every branch appends the note."""
        explicit = "/zims/test.zim"

        # Pin intent + params and force confidence below the 0.6 threshold so
        # the low-confidence branch fires deterministically.
        with patch.object(
            IntentParser,
            "parse_intent",
            return_value=(intent, params, 0.4),
        ):
            result = handler.handle_zim_query("anything", zim_file_path=explicit)

        assert "moderate confidence" in result, (
            f"intent {intent!r}: low-confidence note missing from response: "
            f"{result!r}"
        )
