"""Tests for search_tools module."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpRateLimitError
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.zim_operations import PaginationCursor


def _get_tool_fn(server: OpenZimMcpServer, name: str):
    """Resolve the registered FastMCP tool's callable across SDK versions."""
    tool = server.mcp._tool_manager._tools[name]
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None)
    assert fn is not None, f"could not find callable on tool object: {tool!r}"
    return fn


class TestRegisterSearchTools:
    """Test search tools registration."""

    def test_register_search_tools(self, test_config: OpenZimMcpConfig):
        """Test that search tools are registered correctly."""
        server = OpenZimMcpServer(test_config)
        assert server.mcp is not None


class TestSearchZimFileTool:
    """Test search_zim_file tool functionality."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_search_zim_file_success(self, server: OpenZimMcpServer):
        """Test successful ZIM file search."""
        server.async_zim_operations.search_zim_file = AsyncMock(
            return_value='{"results": [{"title": "Test Article"}]}'
        )
        server.rate_limiter.check_rate_limit = MagicMock()

        result = await server.async_zim_operations.search_zim_file(
            "/path/to/file.zim", "test query", 10, 0
        )

        assert "results" in result
        server.async_zim_operations.search_zim_file.assert_called_once_with(
            "/path/to/file.zim", "test query", 10, 0
        )

    @pytest.mark.asyncio
    async def test_search_zim_file_with_pagination(self, server: OpenZimMcpServer):
        """Test ZIM file search with pagination."""
        server.async_zim_operations.search_zim_file = AsyncMock(
            return_value='{"results": [], "offset": 10}'
        )

        result = await server.async_zim_operations.search_zim_file(
            "/path/to/file.zim", "test query", 10, 10
        )

        assert "results" in result
        server.async_zim_operations.search_zim_file.assert_called_once_with(
            "/path/to/file.zim", "test query", 10, 10
        )

    @pytest.mark.parametrize("bad_limit", [0, 200])
    @pytest.mark.asyncio
    async def test_search_limit_out_of_range_returns_error(
        self, server: OpenZimMcpServer, bad_limit: int
    ):
        """Out-of-range limits hit the registered tool's validator."""
        server.rate_limiter.check_rate_limit = MagicMock()
        search_zim_file = _get_tool_fn(server, "search_zim_file")
        result = await search_zim_file(
            zim_file_path="/path/to/file.zim", query="x", limit=bad_limit, offset=0
        )
        assert "must be between 1 and 100" in result

    def test_search_offset_validation_negative(self):
        """Test that negative offset returns validation error."""
        offset = -5
        # Negative offset should produce validation error message
        error = (
            "**Parameter Validation Error**\n\n"
            f"**Issue**: Offset must be non-negative (provided: {offset})\n\n"
        )
        assert "must be non-negative" in error

    @pytest.mark.asyncio
    async def test_search_zim_file_rate_limit_error(self, server: OpenZimMcpServer):
        """Test rate limit handling in search_zim_file."""
        error = OpenZimMcpRateLimitError("Rate limit exceeded")
        error_msg = server._create_enhanced_error_message(
            operation="search ZIM file",
            error=error,
            context="Query: 'test'",
        )
        assert "search ZIM file" in error_msg or "Operation" in error_msg

    @pytest.mark.asyncio
    async def test_search_zim_file_generic_exception(self, server: OpenZimMcpServer):
        """Test generic exception handling in search_zim_file."""
        server.async_zim_operations.search_zim_file = AsyncMock(
            side_effect=Exception("Search error")
        )

        with pytest.raises(Exception) as exc_info:
            await server.async_zim_operations.search_zim_file(
                "/path/to/file.zim", "query", None, 0
            )
        assert "Search error" in str(exc_info.value)


class TestSearchCursor:
    """The opaque cursor token round-trips through search_zim_file."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a server with search_zim_file stubbed to a passthrough."""
        srv = OpenZimMcpServer(test_config)
        srv.async_zim_operations.search_zim_file = AsyncMock(return_value="ok")
        srv.rate_limiter.check_rate_limit = MagicMock()
        return srv

    def test_pagination_cursor_round_trip(self):
        """Encode -> decode preserves offset, limit, and query."""
        token = PaginationCursor.create_next_cursor(
            current_offset=0, limit=5, total=100, query="diabetes"
        )
        assert token is not None
        decoded = PaginationCursor.decode(token)
        assert decoded == {"o": 5, "l": 5, "q": "diabetes"}

    def test_pagination_cursor_decode_rejects_garbage(self):
        """Malformed base64 surfaces as ValueError."""
        with pytest.raises(ValueError):
            PaginationCursor.decode("not-base64-!!!")

    def test_pagination_cursor_decode_rejects_missing_fields(self):
        """A token decoding to a dict without offset/limit is rejected."""
        import base64
        import json

        bad = base64.urlsafe_b64encode(json.dumps({"only": 1}).encode()).decode()
        with pytest.raises(ValueError, match="missing required fields"):
            PaginationCursor.decode(bad)

    @pytest.mark.asyncio
    async def test_cursor_overrides_offset_and_limit(self, server: OpenZimMcpServer):
        """`cursor` overrides explicit offset/limit when both are present."""
        token = PaginationCursor.create_next_cursor(
            current_offset=10, limit=7, total=100, query="diabetes"
        )

        fn = _get_tool_fn(server, "search_zim_file")
        await fn(
            zim_file_path="/path/to/file.zim",
            query="diabetes",
            limit=999,  # would fail validation if cursor didn't override
            offset=999,
            cursor=token,
        )

        call = server.async_zim_operations.search_zim_file.await_args
        # signature: (zim_file_path, query, limit, offset)
        assert call.args[2] == 7  # limit from cursor
        assert call.args[3] == 17  # next-page offset from cursor

    @pytest.mark.asyncio
    async def test_invalid_cursor_returns_validation_error(
        self, server: OpenZimMcpServer
    ):
        """Malformed cursor surfaces as a parameter-validation message."""
        fn = _get_tool_fn(server, "search_zim_file")
        result = await fn(
            zim_file_path="/path/to/file.zim",
            query="diabetes",
            cursor="!!!not-a-cursor!!!",
        )
        assert "Parameter Validation Error" in result
        assert "cursor" in result.lower()
        # The operations layer should not have been called.
        server.async_zim_operations.search_zim_file.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cursor_alone_supplies_query(self, server: OpenZimMcpServer):
        """A cursor alone is sufficient — the encoded query is reused."""
        token = PaginationCursor.create_next_cursor(
            current_offset=0, limit=2, total=100, query="diabetes"
        )

        fn = _get_tool_fn(server, "search_zim_file")
        await fn(zim_file_path="/path/to/file.zim", cursor=token)

        call = server.async_zim_operations.search_zim_file.await_args
        # signature: (zim_file_path, query, limit, offset)
        assert call.args[1] == "diabetes"
        assert call.args[2] == 2
        assert call.args[3] == 2

    @pytest.mark.asyncio
    async def test_missing_query_without_cursor_is_validation_error(
        self, server: OpenZimMcpServer
    ):
        """Without a cursor, an explicit query is still required."""
        fn = _get_tool_fn(server, "search_zim_file")
        result = await fn(zim_file_path="/path/to/file.zim")
        assert "Parameter Validation Error" in result
        assert "query" in result.lower()
        server.async_zim_operations.search_zim_file.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_matching_cursor_query_proceeds(self, server: OpenZimMcpServer):
        """When `query` matches the cursor's encoded query, the call proceeds.

        The mismatch rejection must not fire on equal queries — pagination
        with an explicit (matching) `query` is a normal pattern.
        """
        token = PaginationCursor.create_next_cursor(
            current_offset=0, limit=5, total=100, query="diabetes"
        )

        fn = _get_tool_fn(server, "search_zim_file")
        await fn(
            zim_file_path="/path/to/file.zim",
            query="diabetes",
            cursor=token,
        )

        call = server.async_zim_operations.search_zim_file.await_args
        # signature: (zim_file_path, query, limit, offset)
        assert call.args[1] == "diabetes"
        assert call.args[2] == 5
        assert call.args[3] == 5

    @pytest.mark.asyncio
    async def test_mismatched_cursor_query_returns_validation_error(
        self, server: OpenZimMcpServer
    ):
        """Reject when the cursor's embedded query differs from `query`.

        Cursors encode the query they were paired with; mixing them with a
        different ``query`` argument is almost always an LLM cycling cursors
        across turns, and would otherwise return the wrong page of the wrong
        query — silent data corruption. Reject loudly instead.
        """
        token = PaginationCursor.create_next_cursor(
            current_offset=0, limit=5, total=100, query="cursor-query"
        )

        fn = _get_tool_fn(server, "search_zim_file")
        result = await fn(
            zim_file_path="/path/to/file.zim",
            query="explicit-query",
            cursor=token,
        )

        assert "Parameter Validation Error" in result
        assert "cursor" in result.lower()
        assert "query" in result.lower()
        # The operations layer must not be called when the inputs conflict.
        server.async_zim_operations.search_zim_file.assert_not_awaited()


class TestSearchPaginationFooterFormat:
    """v1.2.0 search/filter renderers emit a compact one-line footer.

    Prior to v1.2.0 each search response ended with a 3-4 line block:
    a ``**Pagination**`` header, a ``**Next cursor**`` line spelling out a
    ~80-char base64 token, and a ``**Hint**`` line offering both cursor and
    offset. That payload was added to every prompt re-eval in an agentic
    loop. The cursor parameter is still accepted as an *input* — it's just
    no longer advertised in the rendered response, since an LLM keeping the
    conversation context can pass ``offset`` and re-supply the original
    query without losing any information.
    """

    def test_filtered_response_has_more_uses_compact_footer(self):
        from openzim_mcp.zim.search import _FilteredScanState, _format_filtered_response

        scan = _FilteredScanState(
            filtered_count=42,
            scanned=100,
            scan_cap_hit=False,
            total_filtered_is_lower_bound=False,
        )
        results = [
            {
                "title": f"R{i}",
                "path": f"C/R{i}",
                "namespace": "C",
                "content_type": "text/html",
                "snippet": "...",
            }
            for i in range(5)
        ]
        out = _format_filtered_response(
            query="x",
            filter_text="",
            results=results,
            scan=scan,
            total_results=42,
            offset=0,
            limit=5,
        )
        assert "Showing 1-5 of 42" in out
        assert "pass `offset=5` for the next page" in out
        # Old verbose markers must not appear.
        assert "**Pagination**" not in out
        assert "**Next cursor**" not in out
        assert "**Hint**" not in out

    def test_filtered_response_end_of_results_compact(self):
        from openzim_mcp.zim.search import _FilteredScanState, _format_filtered_response

        scan = _FilteredScanState(
            filtered_count=3,
            scanned=20,
            scan_cap_hit=False,
            total_filtered_is_lower_bound=False,
        )
        results = [
            {
                "title": f"R{i}",
                "path": f"C/R{i}",
                "namespace": "C",
                "content_type": "text/html",
                "snippet": "...",
            }
            for i in range(3)
        ]
        out = _format_filtered_response(
            query="x",
            filter_text="",
            results=results,
            scan=scan,
            total_results=3,
            offset=0,
            limit=10,
        )
        assert "Showing 1-3 of 3 (end of results)" in out
        assert "**Next cursor**" not in out
        assert "**End of results**" not in out


class TestSearchAllLimitAlias:
    """`limit` is accepted as an alias of `limit_per_file` on search_all."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a server with search_all_data stubbed to a passthrough."""
        srv = OpenZimMcpServer(test_config)
        # The MCP tool now hits the structured backend ``search_all_data``.
        srv.async_zim_operations.search_all_data = AsyncMock(return_value={})
        srv.rate_limiter.check_rate_limit = MagicMock()
        return srv

    @pytest.mark.asyncio
    async def test_limit_alias_used_when_limit_per_file_missing(
        self, server: OpenZimMcpServer
    ):
        """`limit` flows through when `limit_per_file` is unset."""
        fn = _get_tool_fn(server, "search_all")
        await fn(query="x", limit=8)
        call = server.async_zim_operations.search_all_data.await_args
        assert call.args[1] == 8

    @pytest.mark.asyncio
    async def test_limit_per_file_takes_precedence_over_limit(
        self, server: OpenZimMcpServer
    ):
        """`limit_per_file` wins when both names are provided."""
        fn = _get_tool_fn(server, "search_all")
        await fn(query="x", limit_per_file=3, limit=99)
        call = server.async_zim_operations.search_all_data.await_args
        assert call.args[1] == 3

    @pytest.mark.asyncio
    async def test_default_when_neither_provided(self, server: OpenZimMcpServer):
        """Default of 5 still applies when neither limit nor limit_per_file is set."""
        fn = _get_tool_fn(server, "search_all")
        await fn(query="x")
        call = server.async_zim_operations.search_all_data.await_args
        assert call.args[1] == 5


class TestSearchZimFileDataMeta:
    """search_zim_file_data must attach a _meta envelope on every return path."""

    @pytest.fixture
    def zim_ops(
        self,
        test_config: OpenZimMcpConfig,
        path_validator,
        openzim_mcp_cache,
        content_processor,
    ):
        from openzim_mcp.zim_operations import ZimOperations

        return ZimOperations(test_config, path_validator, openzim_mcp_cache, content_processor)

    def _zim_file(self, temp_dir):
        """Create a placeholder .zim file the path validator will accept."""
        from pathlib import Path

        p = Path(temp_dir) / "test.zim"
        p.write_bytes(b"")
        return p

    def test_search_zim_file_data_attaches_meta_fresh(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """Fresh computation path returns _meta envelope."""
        zim_file = self._zim_file(temp_dir)

        fresh_payload = {
            "query": "climate",
            "total_results": 3,
            "offset": 0,
            "limit": 10,
            "results": [
                {"path": "A/Foo", "title": "Foo", "snippet": "snippet text"}
            ],
            "pagination": {"has_more": False},
        }

        monkeypatch.setattr(zim_ops, "_perform_search", lambda *a, **kw: (fresh_payload, 3))

        from unittest.mock import MagicMock, patch

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.search_zim_file_data(str(zim_file), "climate", limit=10, offset=0)

        assert "_meta" in result, "fresh path must attach _meta"
        assert result["_meta"]["tokens_est"] > 0
        assert result["_meta"]["chars"] > 0
        assert result["_meta"]["truncated"] is False

    def test_search_zim_file_data_meta_on_zero_results(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """Zero-results path still carries _meta."""
        zim_file = self._zim_file(temp_dir)

        zero_payload = {
            "query": "xyzzy_no_match",
            "total_results": 0,
            "offset": 0,
            "limit": 10,
            "results": [],
            "pagination": {"has_more": False},
        }

        monkeypatch.setattr(zim_ops, "_perform_search", lambda *a, **kw: (zero_payload, 0))

        from unittest.mock import MagicMock, patch

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.search_zim_file_data(str(zim_file), "xyzzy_no_match", limit=10, offset=0)

        assert "_meta" in result, "zero-results path must attach _meta"

    def test_search_zim_file_data_meta_on_offset_exceeds_total(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """Offset-exceeds-total path carries _meta."""
        zim_file = self._zim_file(temp_dir)

        exceed_payload = {
            "query": "climate",
            "total_results": 5,
            "offset": 100,
            "limit": 10,
            "results": [],
            "pagination": {"has_more": False, "offset_exceeds_total": True},
        }

        monkeypatch.setattr(
            zim_ops, "_perform_search", lambda *a, **kw: (exceed_payload, 5)
        )

        from unittest.mock import MagicMock, patch

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.search_zim_file_data(
                str(zim_file), "climate", limit=10, offset=100
            )

        assert "_meta" in result, "offset-exceeds-total path must attach _meta"

    def test_search_zim_file_data_meta_on_cached_return(
        self, zim_ops, temp_dir
    ):
        """Cached return path backfills _meta if missing, and always returns _meta."""
        zim_file = self._zim_file(temp_dir)
        validated = zim_ops.path_validator.validate_path(str(zim_file))
        validated = zim_ops.path_validator.validate_zim_file(validated)
        cache_key = f"search_data:{validated}:climate:10:0"

        # Seed cache with an old-format entry (no _meta)
        old_payload = {
            "query": "climate",
            "total_results": 2,
            "offset": 0,
            "limit": 10,
            "results": [{"path": "A/Bar", "title": "Bar", "snippet": "bar"}],
            "pagination": {"has_more": False},
        }
        zim_ops.cache.set(cache_key, old_payload)

        result = zim_ops.search_zim_file_data(str(zim_file), "climate", limit=10, offset=0)

        assert "_meta" in result, "cached return must backfill _meta"
        assert result["_meta"]["tokens_est"] > 0


class TestInputSanitizationSearch:
    """Test input sanitization in search tools."""

    def test_sanitize_file_path(self, test_config: OpenZimMcpConfig):
        """Test that file paths are validated correctly."""
        from openzim_mcp.constants import INPUT_LIMIT_FILE_PATH
        from openzim_mcp.exceptions import OpenZimMcpValidationError
        from openzim_mcp.security import sanitize_input

        # Valid path should pass
        valid_path = "y" * 100
        sanitized = sanitize_input(valid_path, INPUT_LIMIT_FILE_PATH)
        assert sanitized == valid_path

        # Long path should raise error
        long_path = "y" * 2000
        with pytest.raises(OpenZimMcpValidationError):
            sanitize_input(long_path, INPUT_LIMIT_FILE_PATH)

    def test_sanitize_query(self, test_config: OpenZimMcpConfig):
        """Test that queries are validated correctly."""
        from openzim_mcp.constants import INPUT_LIMIT_QUERY
        from openzim_mcp.exceptions import OpenZimMcpValidationError
        from openzim_mcp.security import sanitize_input

        # Valid query should pass
        valid_query = "z" * 100
        sanitized = sanitize_input(valid_query, INPUT_LIMIT_QUERY)
        assert sanitized == valid_query

        # Long query should raise error
        long_query = "z" * 1000
        with pytest.raises(OpenZimMcpValidationError):
            sanitize_input(long_query, INPUT_LIMIT_QUERY)


# ---------------------------------------------------------------------------
# Phase-A _meta envelope smoke tests — search.py methods
# ---------------------------------------------------------------------------


class TestSearchMethodsMeta:
    """_meta is attached on every return path of the three search *_data
    methods: get_search_suggestions_data, find_entry_by_title_data,
    search_all_data.
    """

    @pytest.fixture
    def zim_ops(
        self,
        test_config: OpenZimMcpConfig,
        path_validator,
        openzim_mcp_cache,
        content_processor,
    ):
        from openzim_mcp.zim_operations import ZimOperations

        return ZimOperations(
            test_config, path_validator, openzim_mcp_cache, content_processor
        )

    def _zim_file(self, temp_dir):
        from pathlib import Path

        p = Path(temp_dir) / "test.zim"
        p.write_bytes(b"")
        return p

    # --- get_search_suggestions_data ---

    def test_suggestions_short_query_attaches_meta(self, zim_ops, temp_dir):
        """Short-query early-return path carries _meta."""
        zim_file = self._zim_file(temp_dir)
        result = zim_ops.get_search_suggestions_data(str(zim_file), "a")
        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1

    def test_suggestions_fresh_attaches_meta(self, zim_ops, temp_dir, monkeypatch):
        """Fresh computation path carries _meta."""
        zim_file = self._zim_file(temp_dir)
        monkeypatch.setattr(
            zim_ops,
            "_generate_search_suggestions",
            lambda *a, **kw: {
                "partial_query": "cli",
                "suggestions": [{"title": "Climate"}],
                "count": 1,
            },
        )
        from unittest.mock import MagicMock, patch

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.get_search_suggestions_data(str(zim_file), "cli")

        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1

    def test_suggestions_cached_backfills_meta(self, zim_ops, temp_dir):
        """Cached suggestions without _meta get backfilled on read."""
        zim_file = self._zim_file(temp_dir)
        validated = zim_ops.path_validator.validate_path(str(zim_file))
        validated = zim_ops.path_validator.validate_zim_file(validated)
        cache_key = f"suggestions_data:{validated}:climate:10"
        old = {"partial_query": "climate", "suggestions": [{"title": "Climate"}], "count": 1}
        zim_ops.cache.set(cache_key, old)

        result = zim_ops.get_search_suggestions_data(str(zim_file), "climate")
        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1

    # --- find_entry_by_title_data ---

    def test_find_entry_by_title_attaches_meta(self, zim_ops, temp_dir, monkeypatch):
        """find_entry_by_title_data result carries _meta."""
        zim_file = self._zim_file(temp_dir)
        from unittest.mock import MagicMock, patch

        mock_archive_obj = MagicMock()
        # Stub all fallback paths to avoid MagicMock objects leaking into
        # aggregate_results (which would break attach_meta's json.dumps).
        monkeypatch.setattr(zim_ops, "_find_entry_fast_path", lambda *a, **kw: None)
        monkeypatch.setattr(
            zim_ops, "_find_entry_typo_fallback", lambda *a, **kw: None
        )

        suggestion_search = MagicMock()
        suggestion_search.getEstimatedMatches.return_value = 0
        suggestion_searcher_instance = MagicMock()
        suggestion_searcher_instance.suggest.return_value = suggestion_search

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            with patch(
                "openzim_mcp.zim.search._zim_ops_mod.SuggestionSearcher",
                return_value=suggestion_searcher_instance,
            ):
                mock_archive.return_value.__enter__.return_value = mock_archive_obj
                result = zim_ops.find_entry_by_title_data(str(zim_file), "Climate")

        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1

    # --- search_all_data ---

    def test_search_all_data_attaches_meta(self, zim_ops, temp_dir, monkeypatch):
        """search_all_data carries _meta even with no ZIM files."""
        # list_zim_files_data returns empty list → per_file stays empty
        monkeypatch.setattr(zim_ops, "list_zim_files_data", lambda *a, **kw: [])
        result = zim_ops.search_all_data("climate")
        assert "_meta" in result
        assert result["_meta"]["tokens_est"] >= 1

    # --- search_zim_file_data _meta.reason ---

    def test_empty_search_meta_reason_is_0_hits(self, zim_ops, temp_dir, monkeypatch):
        """Search returning zero results should set _meta.reason='0_hits'."""
        from unittest.mock import MagicMock, patch

        zim_file = self._zim_file(temp_dir)

        query_obj = MagicMock()
        search_obj = MagicMock()
        search_obj.getEstimatedMatches.return_value = 0
        mock_searcher = MagicMock()
        mock_searcher.search.return_value = search_obj
        mock_query = MagicMock(return_value=query_obj)
        query_obj.set_query.return_value = query_obj

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            with patch(
                "openzim_mcp.zim.search._zim_ops_mod.Query", return_value=query_obj
            ):
                with patch(
                    "openzim_mcp.zim.search._zim_ops_mod.Searcher",
                    return_value=mock_searcher,
                ):
                    mock_archive.return_value.__enter__.return_value = MagicMock()
                    result = zim_ops.search_zim_file_data(
                        str(zim_file), "zzzimpossiblequery"
                    )

        assert result["total_results"] == 0
        assert result["_meta"].get("reason") == "0_hits"

    def test_non_empty_search_meta_no_reason(self, zim_ops, temp_dir, monkeypatch):
        """Search returning hits should omit _meta.reason."""
        from unittest.mock import MagicMock, patch

        zim_file = self._zim_file(temp_dir)

        query_obj = MagicMock()
        query_obj.set_query.return_value = query_obj

        mock_entry = MagicMock()
        mock_entry.title = "Climate"

        mock_archive_obj = MagicMock()
        mock_archive_obj.get_entry_by_path.return_value = mock_entry

        search_obj = MagicMock()
        search_obj.getEstimatedMatches.return_value = 1
        search_obj.getResults.return_value = ["C/Climate"]
        mock_searcher = MagicMock()
        mock_searcher.search.return_value = search_obj

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            with patch(
                "openzim_mcp.zim.search._zim_ops_mod.Query", return_value=query_obj
            ):
                with patch(
                    "openzim_mcp.zim.search._zim_ops_mod.Searcher",
                    return_value=mock_searcher,
                ):
                    mock_archive.return_value.__enter__.return_value = mock_archive_obj
                    result = zim_ops.search_zim_file_data(str(zim_file), "climate")

        assert result["total_results"] > 0
        assert "reason" not in result["_meta"]

    def test_empty_search_suggests_other_archives_with_query_match(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """When query yields zero results but matches another archive's name, suggest it."""
        from unittest.mock import MagicMock, patch

        zim_file = self._zim_file(temp_dir)

        # Mock _perform_search to return zero results
        zero_payload = {
            "query": "wikipedia",
            "total_results": 0,
            "offset": 0,
            "limit": 10,
            "results": [],
            "pagination": {"has_more": False},
        }
        monkeypatch.setattr(zim_ops, "_perform_search", lambda *a, **kw: (zero_payload, 0))

        # Mock list_zim_files_data to return two archives
        other_archive_path = str(temp_dir / "wikipedia_en_all.zim")
        monkeypatch.setattr(
            zim_ops,
            "list_zim_files_data",
            lambda *a, **kw: [
                {"path": str(zim_file), "name": "current"},
                {"path": other_archive_path, "name": "wikipedia"},
            ],
        )

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.search_zim_file_data(str(zim_file), "wikipedia", limit=10, offset=0)

        assert result["total_results"] == 0
        assert "_meta" in result
        assert "suggestions" in result["_meta"]
        assert len(result["_meta"]["suggestions"]) > 0
        # Check that we have an alt_archive suggestion
        alt_archive_suggestions = [
            s for s in result["_meta"]["suggestions"] if s.get("type") == "alt_archive"
        ]
        assert len(alt_archive_suggestions) > 0
        assert any(s["value"] == "wikipedia_en_all" for s in alt_archive_suggestions)

    def test_empty_search_suggests_archives_matching_tokens_in_query(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """Query tokens >= 4 chars should match archive basenames."""
        from unittest.mock import MagicMock, patch

        zim_file = self._zim_file(temp_dir)

        # Mock _perform_search to return zero results
        zero_payload = {
            "query": "photosynthesis process biology",
            "total_results": 0,
            "offset": 0,
            "limit": 10,
            "results": [],
            "pagination": {"has_more": False},
        }
        monkeypatch.setattr(zim_ops, "_perform_search", lambda *a, **kw: (zero_payload, 0))

        # Mock list_zim_files_data to return archives, one matching "biology"
        biology_archive_path = str(temp_dir / "biology_reference.zim")
        monkeypatch.setattr(
            zim_ops,
            "list_zim_files_data",
            lambda *a, **kw: [
                {"path": str(zim_file), "name": "current"},
                {"path": biology_archive_path, "name": "biology"},
            ],
        )

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.search_zim_file_data(
                str(zim_file), "photosynthesis process biology", limit=10, offset=0
            )

        assert result["total_results"] == 0
        assert "_meta" in result
        assert "suggestions" in result["_meta"]
        # Should match because "biology" token (>= 4 chars) is in "biology_reference"
        alt_archive_suggestions = [
            s for s in result["_meta"]["suggestions"] if s.get("type") == "alt_archive"
        ]
        assert len(alt_archive_suggestions) > 0
        assert any(s["value"] == "biology_reference" for s in alt_archive_suggestions)

    def test_empty_search_no_archive_suggestion_when_no_token_matches(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """Query tokens that don't match any other archive name should produce no alt_archive."""
        from unittest.mock import MagicMock, patch

        zim_file = self._zim_file(temp_dir)

        # Mock _perform_search to return zero results
        zero_payload = {
            "query": "zzzimpossiblequery",
            "total_results": 0,
            "offset": 0,
            "limit": 10,
            "results": [],
            "pagination": {"has_more": False},
        }
        monkeypatch.setattr(zim_ops, "_perform_search", lambda *a, **kw: (zero_payload, 0))

        # Mock list_zim_files_data with archives that don't match the query
        other_archive_path = str(temp_dir / "wikipedia_en.zim")
        monkeypatch.setattr(
            zim_ops,
            "list_zim_files_data",
            lambda *a, **kw: [
                {"path": str(zim_file), "name": "current"},
                {"path": other_archive_path, "name": "wikipedia"},
            ],
        )

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.search_zim_file_data(
                str(zim_file), "zzzimpossiblequery", limit=10, offset=0
            )

        assert result["total_results"] == 0
        assert "_meta" in result
        # Should have no alt_archive suggestions because query doesn't match any archive name
        suggestions = result["_meta"].get("suggestions", [])
        alt_archive_suggestions = [
            s for s in suggestions if s.get("type") == "alt_archive"
        ]
        assert len(alt_archive_suggestions) == 0

    def test_empty_search_ignores_short_query_tokens_for_archive_matching(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """Query tokens < 4 chars (like 'the', 'in') should not match archives."""
        from unittest.mock import MagicMock, patch

        zim_file = self._zim_file(temp_dir)

        # Mock _perform_search to return zero results
        zero_payload = {
            "query": "the in it",  # All tokens < 4 chars
            "total_results": 0,
            "offset": 0,
            "limit": 10,
            "results": [],
            "pagination": {"has_more": False},
        }
        monkeypatch.setattr(zim_ops, "_perform_search", lambda *a, **kw: (zero_payload, 0))

        # Mock list_zim_files_data with an archive named "init"
        init_archive_path = str(temp_dir / "init_guide.zim")
        monkeypatch.setattr(
            zim_ops,
            "list_zim_files_data",
            lambda *a, **kw: [
                {"path": str(zim_file), "name": "current"},
                {"path": init_archive_path, "name": "init"},
            ],
        )

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.search_zim_file_data(
                str(zim_file), "the in it", limit=10, offset=0
            )

        assert result["total_results"] == 0
        assert "_meta" in result
        # Should have no alt_archive suggestions because all tokens are < 4 chars
        suggestions = result["_meta"].get("suggestions", [])
        alt_archive_suggestions = [
            s for s in suggestions if s.get("type") == "alt_archive"
        ]
        assert len(alt_archive_suggestions) == 0

    def test_empty_search_respects_suggestions_limit(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """alt_archive suggestions must cap at structured_suggestions_limit."""
        from unittest.mock import MagicMock, patch

        zim_file = self._zim_file(temp_dir)

        # Mock _perform_search to return zero results
        zero_payload = {
            "query": "wiki",
            "total_results": 0,
            "offset": 0,
            "limit": 10,
            "results": [],
            "pagination": {"has_more": False},
        }
        monkeypatch.setattr(zim_ops, "_perform_search", lambda *a, **kw: (zero_payload, 0))

        # Create many archives matching the query
        archives = [{"path": str(zim_file), "name": "current"}]
        for i in range(10):
            archives.append({
                "path": str(temp_dir / f"wikipedia_en_{i}.zim"),
                "name": f"wikipedia_{i}",
            })

        monkeypatch.setattr(
            zim_ops,
            "list_zim_files_data",
            lambda *a, **kw: archives,
        )

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.search_zim_file_data(str(zim_file), "wiki", limit=10, offset=0)

        assert result["total_results"] == 0
        assert "_meta" in result
        # Check that suggestions are capped at the configured limit
        limit_n = zim_ops.config.search.structured_suggestions_limit
        alt_archive_suggestions = [
            s for s in result["_meta"]["suggestions"] if s.get("type") == "alt_archive"
        ]
        assert len(alt_archive_suggestions) <= limit_n

    def test_empty_search_skips_current_archive_in_suggestions(
        self, zim_ops, temp_dir, monkeypatch
    ):
        """Current archive should not suggest itself."""
        from unittest.mock import MagicMock, patch

        zim_file = self._zim_file(temp_dir)

        # Mock _perform_search to return zero results
        zero_payload = {
            "query": "wikipedia",
            "total_results": 0,
            "offset": 0,
            "limit": 10,
            "results": [],
            "pagination": {"has_more": False},
        }
        monkeypatch.setattr(zim_ops, "_perform_search", lambda *a, **kw: (zero_payload, 0))

        # Mock list_zim_files_data with the current archive having a matching name
        # Current archive stem: "test"
        # Other archive stem: "wikipedia_en" (matches query)
        current_path = str(zim_file)
        other_archive_path = str(temp_dir / "wikipedia_en.zim")
        monkeypatch.setattr(
            zim_ops,
            "list_zim_files_data",
            lambda *a, **kw: [
                {"path": current_path, "name": "test"},  # This should NOT be suggested
                {"path": other_archive_path, "name": "wikipedia"},
            ],
        )

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.search_zim_file_data(str(zim_file), "wikipedia", limit=10, offset=0)

        assert result["total_results"] == 0
        assert "_meta" in result
        alt_archive_suggestions = [
            s for s in result["_meta"]["suggestions"] if s.get("type") == "alt_archive"
        ]
        # Should suggest wikipedia_en but NOT test.zim
        assert len(alt_archive_suggestions) > 0
        assert all(s.get("value") != Path(current_path).stem for s in alt_archive_suggestions)
