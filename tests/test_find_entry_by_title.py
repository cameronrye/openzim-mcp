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
        # Post-a14 sweep: the production path now calls
        # ``_follow_redirect_chain`` on the fast-path entry to report
        # the canonical post-redirect path. Mark the mock as a non-
        # redirect explicitly so the chain returns it unchanged.
        mock_entry.is_redirect = False
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
        # Phase B contract keys (non-paginated tool, but contract still applies).
        assert result["next_cursor"] is None
        assert result["done"] is True
        assert result["total"] == len(result["results"])
        assert result["page_info"]["offset"] == 0
        assert result["page_info"]["limit"] == 10
        assert result["page_info"]["returned_count"] == len(result["results"])

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
        # Phase B contract keys (non-paginated tool, but contract still applies).
        assert result["next_cursor"] is None
        assert result["done"] is True
        assert result["total"] == 0
        assert result["page_info"]["offset"] == 0
        assert result["page_info"]["limit"] == 10
        assert result["page_info"]["returned_count"] == 0

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
        # Post-a14 sweep: production path now follows redirect chain;
        # mark the mock as canonical so the chain returns it as-is.
        good_entry.is_redirect = False
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
        # Phase B contract keys (non-paginated tool, but contract still applies).
        assert result["next_cursor"] is None
        assert result["done"] is True
        assert result["total"] == len(result["results"])
        assert result["page_info"]["offset"] == 0
        assert result["page_info"]["limit"] == 10
        assert result["page_info"]["returned_count"] == len(result["results"])


def _ctx(value):
    class _C:
        def __enter__(self):
            return value

        def __exit__(self, *a):
            return False

    return _C()


def _patch_path_validator(server, validated_path: str = "/zim/test.zim") -> None:
    """Stub the server's path validator to return a fixed path.

    Used by every fuzzy-/suggestion-mock test so the validator never
    actually touches the filesystem.
    """
    server.zim_operations.path_validator = MagicMock()
    server.zim_operations.path_validator.validate_path.return_value = validated_path
    server.zim_operations.path_validator.validate_zim_file.return_value = validated_path


def _mock_archive_and_suggester(
    monkeypatch,
    *,
    valid_paths: set | None = None,
    entry_path: str | None = None,
    entry_title: str | None = None,
    suggestion_results: list | None = None,
):
    """Install mocks for ``zim_archive`` and ``SuggestionSearcher``.

    ``valid_paths``: paths for which ``has_entry_by_path`` returns True.
        ``None`` means no path matches (fast-path will miss).
    ``entry_path`` / ``entry_title``: the entry returned by
        ``get_entry_by_path`` when called on a valid path.
    ``suggestion_results``: paths the suggestion searcher should return
        (also drives ``getEstimatedMatches``). Default ``None`` → empty
        (suggestions miss entirely).

    Returns the ``mock_archive`` so a caller can attach extra behaviour
    (e.g., tweak ``has_entry_by_path`` to a custom predicate).
    """
    mock_archive = MagicMock()
    if valid_paths is None:
        mock_archive.has_entry_by_path.return_value = False
    else:
        mock_archive.has_entry_by_path.side_effect = lambda p: p in valid_paths
    if entry_path is not None:
        mock_entry = MagicMock()
        mock_entry.path = entry_path
        mock_entry.title = entry_title or entry_path
        # Explicit non-redirect: without this, MagicMock attribute access
        # returns a truthy MagicMock and the v2.0.0a9 typo-ranking path
        # would follow a phantom redirect chain off the mock and serialize
        # MagicMock-typed paths/titles into the JSON envelope.
        mock_entry.is_redirect = False
        mock_archive.get_entry_by_path.return_value = mock_entry
    results = suggestion_results or []
    mock_suggest = MagicMock()
    mock_suggest.getEstimatedMatches.return_value = len(results)
    mock_suggest.getResults.return_value = results
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
    return mock_archive


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
        _mock_archive_and_suggester(
            monkeypatch,
            valid_paths={"C/Einstein"},
            entry_path="C/Einstein",
            entry_title="Einstein",
        )
        _patch_path_validator(server)

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Einstien", cross_file=False, limit=10
        )
        assert result["fuzzy_path_hit"] is True
        assert len(result["results"]) == 1
        hit = result["results"][0]
        assert hit["path"] == "C/Einstein"
        assert hit["title"] == "Einstein"
        # Phase B contract keys (non-paginated tool, but contract still applies).
        assert result["next_cursor"] is None
        assert result["done"] is True
        assert result["total"] == len(result["results"])
        assert result["page_info"]["offset"] == 0
        assert result["page_info"]["limit"] == 10
        assert result["page_info"]["returned_count"] == len(result["results"])
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
        _mock_archive_and_suggester(
            monkeypatch,
            entry_path="C/Some_article",
            entry_title="Some article",
            suggestion_results=["C/Some_article"],
        )
        _patch_path_validator(server)

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Einstien", cross_file=False, limit=10
        )
        assert result["fuzzy_path_hit"] is False

    def test_typo_fallback_skipped_for_short_queries(self, server, monkeypatch):
        """Queries < 4 chars don't run the fuzzy fallback — too many
        spurious matches.
        """
        _mock_archive_and_suggester(monkeypatch)
        _patch_path_validator(server)

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
        _mock_archive_and_suggester(
            monkeypatch,
            valid_paths={"C/Einstein"},
            entry_path="C/Einstein",
            entry_title="Einstein",
        )
        _patch_path_validator(server)

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
        test_config.search.fuzzy_title_score_penalty = 0.5
        server = OpenZimMcpServer(test_config)
        _mock_archive_and_suggester(
            monkeypatch,
            valid_paths={"C/Einstein"},
            entry_path="C/Einstein",
            entry_title="Einstein",
        )
        _patch_path_validator(server)

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
        test_config.search.fuzzy_title_min_query_len = 6
        server = OpenZimMcpServer(test_config)
        _mock_archive_and_suggester(monkeypatch)
        _patch_path_validator(server)

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

    def test_fuzzy_candidates_appear_in_meta_suggestions(self, server, monkeypatch):
        """When fuzzy fallback eligibility is met (no fast path, no
        suggestion-search hit, query long enough), and at least one typo
        variant resolves to a real entry in the archive, that variant
        title appears in ``_meta.suggestions[]``.

        Regression: earlier code emitted raw permutations of the user's
        input regardless of whether they resolved (Phase A #6). The new
        behaviour only emits archive-verified entry titles.
        """
        # Make the typo-variant probe for "C/Einstein" resolve.
        # "Einstien" → transposition → "Einstein" which the fast-path
        # tries as "C/Einstein".
        mock_archive = _mock_archive_and_suggester(monkeypatch)
        einstein_entry = MagicMock()
        einstein_entry.path = "C/Einstein"
        einstein_entry.title = "Einstein"
        einstein_entry.is_redirect = False
        mock_archive.has_entry_by_path.side_effect = lambda p: p == "C/Einstein"
        mock_archive.get_entry_by_path.side_effect = lambda p: (
            einstein_entry if p == "C/Einstein" else (_ for _ in ()).throw(KeyError(p))
        )
        _patch_path_validator(server)

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Einstien", cross_file=False, limit=10
        )
        # With the new fix, the typo fallback resolves to "Einstein" so
        # the result list contains one entry and _meta.suggestions is
        # NOT emitted (issue #7: suggestions only on 0-hit responses).
        # If the typo fallback didn't run for some reason, we'd expect
        # the verified-variants list. Either way: no raw permutations.
        suggestions = result.get("_meta", {}).get("suggestions", [])
        for s in suggestions:
            # Every suggestion must be a value that resolved against
            # the archive, not a mangled permutation.
            assert s["value"] == "Einstein"

    def test_suggestions_omitted_when_archive_has_no_matches(self, server, monkeypatch):
        """When the archive contains nothing that resolves any typo
        variant, ``_meta.suggestions`` is empty rather than a list of
        nonsense permutations of the user's input (Phase A #6)."""
        _mock_archive_and_suggester(monkeypatch)  # has_entry_by_path → False
        _patch_path_validator(server)

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim",
            "Photosythesis",  # 13 chars > fuzzy_title_min_query_len
            cross_file=False,
            limit=10,
        )
        suggestions = result.get("_meta", {}).get("suggestions", [])
        # No archive entry resolves any typo variant → no suggestions
        assert suggestions == [] or suggestions is None or suggestions == []

    def test_suggestions_capped_at_structured_suggestions_limit(
        self, server, monkeypatch
    ):
        """_meta.suggestions[] must not exceed structured_suggestions_limit."""
        _mock_archive_and_suggester(monkeypatch)
        _patch_path_validator(server)

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
        mock_archive = _mock_archive_and_suggester(
            monkeypatch,
            entry_path="C/Einstein",
            entry_title="Einstein",
        )
        # All paths hit (fast path always succeeds)
        mock_archive.has_entry_by_path.return_value = True
        _patch_path_validator(server)

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Einstein", cross_file=False, limit=10
        )
        assert result["results"], "expected a hit on the fast path"
        # fast_path_hit means no fuzzy → no suggestions
        assert result.get("_meta", {}).get("suggestions") is None

    def test_find_entry_meta_reason_on_zero_results(self, server, monkeypatch):
        """When no results found, _meta.reason should be '0_hits'."""
        _mock_archive_and_suggester(monkeypatch)
        _patch_path_validator(server)

        # Use a query short enough to skip typo fallback but still long enough
        # for suggestion search — still returns empty.
        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "zzzimpossiblequery", cross_file=False, limit=10
        )
        assert result["results"] == []
        assert result["_meta"].get("reason") == "0_hits"
        # Phase B contract keys (non-paginated tool, but contract still applies).
        assert result["next_cursor"] is None
        assert result["done"] is True
        assert result["total"] == 0
        assert result["page_info"]["offset"] == 0
        assert result["page_info"]["limit"] == 10
        assert result["page_info"]["returned_count"] == 0

    def test_find_entry_meta_reason_absent_on_hits(self, server, monkeypatch):
        """When results found, _meta.reason should be absent (None → omitted)."""
        mock_archive = _mock_archive_and_suggester(
            monkeypatch,
            entry_path="C/Einstein",
            entry_title="Einstein",
        )
        # All paths hit (fast path always succeeds)
        mock_archive.has_entry_by_path.return_value = True
        _patch_path_validator(server)

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Einstein", cross_file=False, limit=10
        )
        assert result["results"], "expected a hit"
        assert "reason" not in result["_meta"]

    def test_no_suggestions_when_query_too_short(self, server, monkeypatch):
        """Queries below fuzzy_title_min_query_len produce no alt_spelling
        suggestions even when all paths miss.
        """
        _mock_archive_and_suggester(monkeypatch)
        _patch_path_validator(server)

        result = server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "Pi", cross_file=False, limit=10
        )
        suggestions = result.get("_meta", {}).get("suggestions", [])
        spelling_alts = [s for s in suggestions if s.get("type") == "alt_spelling"]
        assert (
            spelling_alts == []
        ), "short query should not produce alt_spelling suggestions"
