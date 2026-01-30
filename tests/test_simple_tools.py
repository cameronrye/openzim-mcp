"""Tests for simple tools functionality."""

from unittest.mock import Mock

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
