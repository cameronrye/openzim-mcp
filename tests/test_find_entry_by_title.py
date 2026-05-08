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
        server.async_zim_operations.find_entry_by_title_data = AsyncMock(
            return_value={}
        )
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

        call = server.async_zim_operations.find_entry_by_title_data.await_args
        sent_path = call.args[0]
        assert (
            "\x00" not in sent_path
        ), f"NUL byte leaked through with cross_file=True: {sent_path!r}"
        assert sent_path == "anyname.zim"


class TestTypoTolerantFallback:
    """v1.2.0 follow-up: when the case-variant fast path AND the libzim
    suggestion search both come up empty, try a small set of single-edit
    variants of the input (transposition / single deletion) before
    returning ``"no results"``. Catches the common LLM typo case
    (``"Einstien"`` → ``"Einstein"``, ``"Phyton"`` → ``"Python"``) that
    the suggestion index can't recover from.
    """

    def test_typo_variants_produces_transposition(self):
        from openzim_mcp.zim.search import _SearchMixin

        variants = _SearchMixin._typo_variants("Einstien")
        # The Einstien -> Einstein swap is at position 5-6 (i↔e).
        assert "Einstein" in variants

    def test_typo_variants_produces_deletions_for_long_titles(self):
        from openzim_mcp.zim.search import _SearchMixin

        variants = _SearchMixin._typo_variants("Phython")
        assert "Python" in variants

    def test_typo_variants_skips_deletion_for_short_titles(self):
        """Deletions on short titles produce too many spurious matches
        (e.g. "test" -> "tes" matching unrelated 3-char articles).
        """
        from openzim_mcp.zim.search import _SearchMixin

        variants = _SearchMixin._typo_variants("test")
        # Adjacent transpositions only — no deletions for len < 6.
        assert "tes" not in variants
        assert "tst" not in variants
        assert "est" not in variants  # would be a deletion

    def test_typo_variants_skips_no_op_swaps(self):
        """Swap of identical adjacent chars is a no-op; don't yield it
        as a variant (it would just probe the original twice).
        """
        from openzim_mcp.zim.search import _SearchMixin

        variants = _SearchMixin._typo_variants("Coffee")
        # The "ff" pair would yield "Coffee" again — skipped.
        assert variants.count("Coffee") == 0

    @pytest.fixture
    def server(self, test_config):
        return OpenZimMcpServer(test_config)

    def test_typo_fallback_resolves_einstien(self, server, monkeypatch):
        """End-to-end: ``Einstien`` (typo) → fast-path probes find
        ``Einstein`` via the i↔e transposition variant.
        """
        mock_archive = MagicMock()
        # Fast path: only "Einstein" / "C/Einstein" hits.
        valid_paths = {"C/Einstein"}

        def has(path):
            return path in valid_paths

        mock_archive.has_entry_by_path.side_effect = has
        mock_entry = MagicMock()
        mock_entry.path = "C/Einstein"
        mock_entry.title = "Einstein"
        mock_archive.get_entry_by_path.return_value = mock_entry
        # Suggestions return nothing (libzim can't recover from this typo).
        mock_suggest = MagicMock()
        mock_suggest.getEstimatedMatches.return_value = 0
        mock_suggest.getResults.return_value = []
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

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Einstien", cross_file=False, limit=10
        )
        assert result["fuzzy_path_hit"] is True
        assert len(result["results"]) == 1
        hit = result["results"][0]
        assert hit["path"] == "C/Einstein"
        assert hit["title"] == "Einstein"
        # Below 0.95 so a real suggestion-top in another file would
        # outrank a fuzzy hit. ``pytest.approx`` rather than ``==`` so
        # SonarCloud S1244 (float-equality bug rule) doesn't flag the
        # comparison; the value here is one we set, not one derived
        # from arithmetic, so equality is semantically fine.
        # Uses config.search.fuzzy_title_score_penalty (default 0.85).
        assert hit["score"] == pytest.approx(
            server.zim_operations.config.search.fuzzy_title_score_penalty
        )
        assert hit.get("match_type") == "typo_corrected"

    def test_typo_fallback_skipped_when_suggestion_hits(self, server, monkeypatch):
        """When the suggestion search returns ANY hit, fuzzy fallback
        does not run — suggestion results have stronger provenance and
        should always win.
        """
        mock_archive = MagicMock()
        mock_archive.has_entry_by_path.return_value = False
        mock_entry = MagicMock()
        mock_entry.path = "C/Some_article"
        mock_entry.title = "Some article"
        mock_archive.get_entry_by_path.return_value = mock_entry
        # Suggestion returns one weak result.
        mock_suggest = MagicMock()
        mock_suggest.getEstimatedMatches.return_value = 1
        mock_suggest.getResults.return_value = ["C/Some_article"]
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

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Einstien", cross_file=False, limit=10
        )
        assert result["fuzzy_path_hit"] is False

    def test_typo_fallback_skipped_for_short_queries(self, server, monkeypatch):
        """Queries < 4 chars don't run the fuzzy fallback — too many
        spurious matches.
        """
        mock_archive = MagicMock()
        mock_archive.has_entry_by_path.return_value = False
        mock_suggest = MagicMock()
        mock_suggest.getEstimatedMatches.return_value = 0
        mock_suggest.getResults.return_value = []
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

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Pi", cross_file=False, limit=10
        )
        # Empty result and no fuzzy fired.
        assert result["results"] == []
        assert result["fuzzy_path_hit"] is False

    def test_fuzzy_match_score_uses_default_penalty(self, server, monkeypatch):
        """A typo-corrected hit should score equal to
        fuzzy_title_score_penalty (default 0.85).
        """
        mock_archive = MagicMock()
        valid_paths = {"C/Einstein"}

        def has(path):
            return path in valid_paths

        mock_archive.has_entry_by_path.side_effect = has
        mock_entry = MagicMock()
        mock_entry.path = "C/Einstein"
        mock_entry.title = "Einstein"
        mock_archive.get_entry_by_path.return_value = mock_entry
        mock_suggest = MagicMock()
        mock_suggest.getEstimatedMatches.return_value = 0
        mock_suggest.getResults.return_value = []
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

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Einstien", cross_file=False, limit=10
        )
        fuzzy_results = [
            r for r in result["results"] if r.get("match_type") == "typo_corrected"
        ]
        assert len(fuzzy_results) > 0
        expected_score = server.zim_operations.config.search.fuzzy_title_score_penalty
        assert fuzzy_results[0]["score"] == pytest.approx(expected_score)

    def test_fuzzy_match_score_overridable_via_config(self, test_config, monkeypatch):
        """Setting fuzzy_title_score_penalty=0.5 produces score=0.5."""
        # Create a config with custom fuzzy_title_score_penalty
        test_config.search.fuzzy_title_score_penalty = 0.5
        server = OpenZimMcpServer(test_config)

        mock_archive = MagicMock()
        valid_paths = {"C/Einstein"}

        def has(path):
            return path in valid_paths

        mock_archive.has_entry_by_path.side_effect = has
        mock_entry = MagicMock()
        mock_entry.path = "C/Einstein"
        mock_entry.title = "Einstein"
        mock_archive.get_entry_by_path.return_value = mock_entry
        mock_suggest = MagicMock()
        mock_suggest.getEstimatedMatches.return_value = 0
        mock_suggest.getResults.return_value = []
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

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Einstien", cross_file=False, limit=10
        )
        fuzzy_results = [
            r for r in result["results"] if r.get("match_type") == "typo_corrected"
        ]
        assert len(fuzzy_results) > 0
        assert fuzzy_results[0]["score"] == pytest.approx(0.5)

    def test_fuzzy_min_length_gates_short_queries(self, test_config, monkeypatch):
        """With fuzzy_title_min_query_len=6, a 5-char query should not
        trigger fuzzy fallback.
        """
        # Create a config with custom fuzzy_title_min_query_len
        test_config.search.fuzzy_title_min_query_len = 6
        server = OpenZimMcpServer(test_config)

        mock_archive = MagicMock()
        mock_archive.has_entry_by_path.return_value = False
        mock_suggest = MagicMock()
        mock_suggest.getEstimatedMatches.return_value = 0
        mock_suggest.getResults.return_value = []
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

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Einst", cross_file=False, limit=10
        )
        # No fuzzy results because query length (5) < fuzzy_title_min_query_len (6)
        assert all(r.get("match_type") != "typo_corrected" for r in result["results"])


class TestMetaSuggestionsAndReason:
    """Phase A items #4 + #14: _meta.suggestions[] and _meta.reason codes."""

    @pytest.fixture
    def server(self, test_config):
        return OpenZimMcpServer(test_config)

    def _mock_empty_archive(self, server, monkeypatch):
        """Set up mocks so fast path + suggestions both miss, typo fallback runs."""
        mock_archive = MagicMock()
        mock_archive.has_entry_by_path.return_value = False
        mock_suggest = MagicMock()
        mock_suggest.getEstimatedMatches.return_value = 0
        mock_suggest.getResults.return_value = []
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

    def test_fuzzy_candidates_appear_in_meta_suggestions(self, server, monkeypatch):
        """When fuzzy fallback eligibility is met (no fast path, query long
        enough), _meta.suggestions[] contains alt_spelling entries derived
        from the typo variant generator.
        """
        self._mock_empty_archive(server, monkeypatch)

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Einstien", cross_file=False, limit=10
        )
        # "Einstien" is 8 chars — above the default fuzzy_title_min_query_len (4)
        suggestions = result.get("_meta", {}).get("suggestions", [])
        spelling_alts = [s for s in suggestions if s.get("type") == "alt_spelling"]
        assert spelling_alts, "expected typo variants as alt_spelling suggestions"
        # Each suggestion must have both required keys
        for s in spelling_alts:
            assert "type" in s
            assert "value" in s

    def test_suggestions_capped_at_structured_suggestions_limit(
        self, server, monkeypatch
    ):
        """_meta.suggestions[] must not exceed structured_suggestions_limit."""
        self._mock_empty_archive(server, monkeypatch)

        # Use a long title that generates many transposition variants
        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Photosynthesis", cross_file=False, limit=10
        )
        suggestions = result.get("_meta", {}).get("suggestions", [])
        limit_n = server.zim_operations.config.search.structured_suggestions_limit
        assert len(suggestions) <= limit_n

    def test_no_suggestions_when_fast_path_hits(self, server, monkeypatch):
        """When the fast path succeeds, suggestions should be absent (None /
        not set) — no fuzzy lookup was needed.
        """
        mock_archive = MagicMock()
        mock_archive.has_entry_by_path.return_value = True
        mock_entry = MagicMock()
        mock_entry.path = "C/Einstein"
        mock_entry.title = "Einstein"
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

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Einstein", cross_file=False, limit=10
        )
        assert result["results"], "expected a hit on the fast path"
        # fast_path_hit means no fuzzy → no suggestions
        assert result.get("_meta", {}).get("suggestions") is None

    def test_find_entry_meta_reason_on_zero_results(self, server, monkeypatch):
        """When no results found, _meta.reason should be '0_hits'."""
        self._mock_empty_archive(server, monkeypatch)

        # Use a query short enough to skip typo fallback but still long enough
        # for suggestion search — still returns empty.
        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "zzzimpossiblequery", cross_file=False, limit=10
        )
        assert result["results"] == []
        assert result["_meta"].get("reason") == "0_hits"

    def test_find_entry_meta_reason_absent_on_hits(self, server, monkeypatch):
        """When results found, _meta.reason should be absent (None → omitted)."""
        mock_archive = MagicMock()
        mock_archive.has_entry_by_path.return_value = True
        mock_entry = MagicMock()
        mock_entry.path = "C/Einstein"
        mock_entry.title = "Einstein"
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

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Einstein", cross_file=False, limit=10
        )
        assert result["results"], "expected a hit"
        assert "reason" not in result["_meta"]

    def test_no_suggestions_when_query_too_short(self, server, monkeypatch):
        """Queries below fuzzy_title_min_query_len produce no alt_spelling
        suggestions even when all paths miss.
        """
        self._mock_empty_archive(server, monkeypatch)

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Pi", cross_file=False, limit=10
        )
        suggestions = result.get("_meta", {}).get("suggestions", [])
        spelling_alts = [s for s in suggestions if s.get("type") == "alt_spelling"]
        assert (
            spelling_alts == []
        ), "short query should not produce alt_spelling suggestions"
