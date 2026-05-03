"""Tests for find_entry_by_title tool."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpValidationError
from openzim_mcp.server import OpenZimMcpServer


class TestFindEntryByTitle:
    """Test find_entry_by_title operation."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_empty_title_raises(self, server: OpenZimMcpServer):
        """Empty/whitespace title raises OpenZimMcpValidationError."""
        with pytest.raises(OpenZimMcpValidationError):
            server.zim_operations.find_entry_by_title(
                "/zim/test.zim", "", cross_file=False, limit=10
            )

    def test_limit_bounds(self, server: OpenZimMcpServer):
        """Limit < 1 or > 50 raises OpenZimMcpValidationError."""
        with pytest.raises(OpenZimMcpValidationError, match="limit must be"):
            server.zim_operations.find_entry_by_title(
                "/zim/test.zim", "Python", cross_file=False, limit=0
            )
        with pytest.raises(OpenZimMcpValidationError, match="limit must be"):
            server.zim_operations.find_entry_by_title(
                "/zim/test.zim", "Python", cross_file=False, limit=51
            )

    def test_fast_path_exact_match(self, server: OpenZimMcpServer, monkeypatch):
        """Direct C/<title> path match short-circuits the suggestion search."""
        mock_archive = MagicMock()
        mock_archive.has_entry_by_path.return_value = True
        mock_entry = MagicMock()
        mock_entry.path = "C/Python_(programming_language)"
        mock_entry.title = "Python (programming language)"
        mock_archive.get_entry_by_path.return_value = mock_entry

        monkeypatch.setattr(
            "openzim_mcp.zim_operations.zim_archive",
            lambda *a, **kw: _ctx(mock_archive),
        )
        server.zim_operations.path_validator = MagicMock()
        server.zim_operations.path_validator.validate_path.return_value = (
            "/zim/test.zim"
        )
        server.zim_operations.path_validator.validate_zim_file.return_value = (
            "/zim/test.zim"
        )

        result_json = server.zim_operations.find_entry_by_title(
            "/zim/test.zim",
            "Python (programming language)",
            cross_file=False,
            limit=10,
        )
        result = json.loads(result_json)
        assert result["fast_path_hit"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["path"] == "C/Python_(programming_language)"

    def test_no_matches_returns_empty(self, server: OpenZimMcpServer, monkeypatch):
        """No matches returns empty results, not an error."""
        mock_archive = MagicMock()
        mock_archive.has_entry_by_path.return_value = False
        mock_suggest = MagicMock()
        mock_suggest.getEstimatedMatches.return_value = 0
        mock_suggest.getResults.return_value = []

        # SuggestionSearcher(archive).suggest(title) is the real call path;
        # patch the constructor so the test stays at the API-shape level.
        mock_searcher = MagicMock()
        mock_searcher.suggest.return_value = mock_suggest
        monkeypatch.setattr(
            "openzim_mcp.zim_operations.SuggestionSearcher",
            lambda archive: mock_searcher,
        )

        monkeypatch.setattr(
            "openzim_mcp.zim_operations.zim_archive",
            lambda *a, **kw: _ctx(mock_archive),
        )
        server.zim_operations.path_validator = MagicMock()
        server.zim_operations.path_validator.validate_path.return_value = (
            "/zim/test.zim"
        )
        server.zim_operations.path_validator.validate_zim_file.return_value = (
            "/zim/test.zim"
        )

        result_json = server.zim_operations.find_entry_by_title(
            "/zim/test.zim", "NonexistentArticle12345", cross_file=False, limit=10
        )
        result = json.loads(result_json)
        assert result["results"] == []
        assert result["fast_path_hit"] is False
        assert result["files_searched"] == 1

    def test_cross_file_aggregates_and_skips_failures(
        self, server: OpenZimMcpServer, monkeypatch
    ):
        """Cross-file mode aggregates results and skips files that can't open."""
        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[
                {"path": "/zim/good.zim", "name": "good.zim"},
                {"path": "/zim/bad.zim", "name": "bad.zim"},
            ]
        )

        good_archive = MagicMock()
        good_archive.has_entry_by_path.return_value = True
        good_entry = MagicMock()
        good_entry.path = "C/Python"
        good_entry.title = "Python"
        good_archive.get_entry_by_path.return_value = good_entry

        def archive_factory(path, *a, **kw):
            if "bad" in str(path):
                raise RuntimeError("corrupt archive")
            return _ctx(good_archive)

        monkeypatch.setattr("openzim_mcp.zim_operations.zim_archive", archive_factory)

        result_json = server.zim_operations.find_entry_by_title(
            "/unused.zim", "Python", cross_file=True, limit=10
        )
        result = json.loads(result_json)
        assert result["files_searched"] == 2
        assert len(result["results"]) == 1
        assert result["results"][0]["zim_file"] == "/zim/good.zim"


def _ctx(value):
    class _C:
        def __enter__(self):
            return value

        def __exit__(self, *a):
            return False

    return _C()


class TestFindEntryByTitleToolSanitization:
    """Sanitization tests for the registered MCP tool wrapper."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    @pytest.mark.asyncio
    async def test_zim_file_path_sanitized_when_cross_file_true(
        self, server: OpenZimMcpServer
    ):
        """zim_file_path is sanitized even when cross_file=True.

        Previously the sanitize call was gated on ``not cross_file``, so a
        NUL byte in the path would flow through to the backend untouched.
        Pin the fix by asserting the registered tool strips control chars
        in this branch.
        """
        server.async_zim_operations.find_entry_by_title = AsyncMock(return_value="{}")
        server.rate_limiter.check_rate_limit = MagicMock()

        tool = server.mcp._tool_manager._tools["find_entry_by_title"]
        fn = getattr(tool, "fn", None) or getattr(tool, "func", None)
        assert fn is not None

        bad_path = "any\x00name.zim"
        await fn(
            zim_file_path=bad_path,
            title="Foo",
            cross_file=True,
            limit=5,
        )

        call = server.async_zim_operations.find_entry_by_title.await_args
        sent_path = call.args[0]
        assert (
            "\x00" not in sent_path
        ), f"NUL byte leaked through with cross_file=True: {sent_path!r}"
        assert sent_path == "anyname.zim"
