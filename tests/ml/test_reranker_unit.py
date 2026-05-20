"""Unit tests for BGEReranker (mocked FastEmbed)."""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.config import RerankerConfig
from openzim_mcp.ml import detect
from openzim_mcp.ml.fallback import reset_kill_switches
from openzim_mcp.ml.reranker import BGEReranker


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    BGEReranker.reset_instance()
    reset_kill_switches()
    detect.cache_clear()


class TestBGEGet:
    def test_returns_none_when_extra_absent(self) -> None:
        with patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = None
            assert BGEReranker.get() is None

    def test_returns_none_when_disabled_via_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENZIM_RERANKER_DISABLE", "1")
        # Even if the extra is "installed", env disable wins.
        with patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = object()
            assert BGEReranker.get() is None

    def test_returns_singleton_when_extra_present(self) -> None:
        with (
            patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec,
            patch("openzim_mcp.ml.reranker._load_model") as mock_load,
        ):
            mock_spec.return_value = object()
            mock_load.return_value = MagicMock(name="fastembed_reranker")
            a = BGEReranker.get()
            b = BGEReranker.get()
            assert a is not None
            assert a is b  # same singleton
            assert mock_load.call_count == 1

    def test_timeout_returns_none_within_bounded_time(self) -> None:
        """Regression: a slow _load_model must not block the caller past timeout."""
        import threading
        import time

        event = threading.Event()

        def slow_load(model_id: str, cache_dir: object) -> object:
            # Simulate a hung download that takes much longer than timeout.
            event.wait(timeout=30)
            return MagicMock()

        with (
            patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec,
            patch("openzim_mcp.ml.reranker._load_model", side_effect=slow_load),
        ):
            mock_spec.return_value = object()
            cfg = RerankerConfig(first_call_timeout_seconds=0.5)
            start = time.monotonic()
            result = BGEReranker.get(cfg)
            elapsed = time.monotonic() - start
        # Unblock the leaked background thread before exiting the test.
        event.set()

        assert result is None
        # 2.0s gives generous slack over the 0.5s timeout for CI jitter.
        assert elapsed < 2.0, f"get() blocked for {elapsed:.2f}s past timeout"

    def test_load_failure_trips_kill_switch(self) -> None:
        """Regression: after a load failure, subsequent get() calls must NOT retry."""
        call_count = 0

        def failing_load(model_id: str, cache_dir: object) -> object:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("simulated load failure")

        with (
            patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec,
            patch("openzim_mcp.ml.reranker._load_model", side_effect=failing_load),
        ):
            mock_spec.return_value = object()
            cfg = RerankerConfig(first_call_timeout_seconds=2.0)
            assert BGEReranker.get(cfg) is None
            assert BGEReranker.get(cfg) is None
            assert BGEReranker.get(cfg) is None
        assert (
            call_count == 1
        ), f"_load_model should be called once and never retried; got {call_count}"


class TestScorePairs:
    def _make_reranker_with_scores(self, scores: List[float]) -> BGEReranker:
        mock_model = MagicMock()
        mock_model.rerank = MagicMock(return_value=iter(scores))
        # Bypass BGEReranker.get() and inject a pre-built reranker
        return BGEReranker(model=mock_model, config=RerankerConfig())

    def test_empty_pairs_returns_empty(self) -> None:
        r = self._make_reranker_with_scores([])
        assert r.score_pairs([]) == []

    def test_returns_one_score_per_pair(self) -> None:
        r = self._make_reranker_with_scores([0.9, 0.5, 0.1])
        scores = r.score_pairs([("q", "d1"), ("q", "d2"), ("q", "d3")])
        assert scores == [0.9, 0.5, 0.1]

    def test_truncates_query_at_max_length(self) -> None:
        cfg = RerankerConfig(max_query_length=5)
        mock_model = MagicMock()
        mock_model.rerank = MagicMock(return_value=iter([0.5]))
        r = BGEReranker(model=mock_model, config=cfg)
        r.score_pairs([("abcdefghijklmnop", "doc")])
        # Verify the query passed to fastembed was truncated
        call_args = mock_model.rerank.call_args
        # FastEmbed's rerank signature: rerank(query: str, documents: List[str])
        passed_query = call_args[0][0]
        assert len(passed_query) <= 5


class TestRerank:
    def _make_reranker_with_scores(self, scores: List[float]) -> BGEReranker:
        mock_model = MagicMock()
        mock_model.rerank = MagicMock(return_value=iter(scores))
        return BGEReranker(model=mock_model, config=RerankerConfig())

    def test_short_query_skips_rerank(self) -> None:
        r = self._make_reranker_with_scores([0.5, 0.5, 0.5])
        # "Berlin" is 1 token, well below min_query_tokens=4
        candidates = [
            {"path": "A", "snippet": "...", "xapian_score": 1.0},
            {"path": "B", "snippet": "...", "xapian_score": 0.9},
        ]
        result = r.rerank("Berlin", candidates, top_k=2)
        # Returns input order unchanged (no rerank fired)
        assert [c["path"] for c in result] == ["A", "B"]
        # And no rerank_score field added
        assert all("rerank_score" not in c for c in result)

    def test_long_query_reranks(self) -> None:
        # Scores ordered to invert Xapian's ordering
        r = self._make_reranker_with_scores([0.1, 0.9])
        candidates = [
            {"path": "A", "snippet": "...", "xapian_score": 1.0},
            {"path": "B", "snippet": "...", "xapian_score": 0.5},
        ]
        result = r.rerank(
            "what year did Marie Curie discover radium",
            candidates,
            top_k=2,
        )
        # B now wins (rerank_score=0.9 > 0.1)
        assert [c["path"] for c in result] == ["B", "A"]
        assert result[0]["rerank_score"] == 0.9
        assert result[1]["rerank_score"] == 0.1

    def test_top_k_slices_result(self) -> None:
        r = self._make_reranker_with_scores([0.9, 0.5, 0.1])
        candidates = [
            {"path": "A", "snippet": "...", "xapian_score": 0.5},
            {"path": "B", "snippet": "...", "xapian_score": 0.5},
            {"path": "C", "snippet": "...", "xapian_score": 0.5},
        ]
        result = r.rerank(
            "what year did Marie Curie discover radium",
            candidates,
            top_k=2,
        )
        assert len(result) == 2
        assert [c["path"] for c in result] == ["A", "B"]

    def test_empty_candidates_returns_empty(self) -> None:
        r = self._make_reranker_with_scores([])
        assert r.rerank("any long enough query string", [], top_k=10) == []

    def test_inference_failure_falls_back_to_passthrough(self) -> None:
        """Regression: a mid-inference raise must return candidates[:top_k] via ml_fallback."""
        from openzim_mcp.ml.fallback import reset_kill_switches

        reset_kill_switches()
        mock_model = MagicMock()
        mock_model.rerank = MagicMock(side_effect=RuntimeError("OOM"))
        r = BGEReranker(model=mock_model, config=RerankerConfig())
        candidates = [
            {"path": "A", "snippet": "...", "xapian_score": 1.0},
            {"path": "B", "snippet": "...", "xapian_score": 0.9},
            {"path": "C", "snippet": "...", "xapian_score": 0.8},
        ]
        result = r.rerank(
            "what year did Marie Curie discover radium",
            candidates,
            top_k=2,
        )
        # Falls back to original order, sliced to top_k, no rerank_score
        assert [c["path"] for c in result] == ["A", "B"]
        assert all("rerank_score" not in c for c in result)
        reset_kill_switches()  # leave state clean for the next test


class TestRerankerWiredToHandleSearch:
    """Verify that _handle_search routes results through the reranker when
    available, and degrades gracefully when it is not."""

    def _make_handler(self):  # type: ignore[return]
        """Build a SimpleToolsHandler backed by a MagicMock ZimOperations.

        The mock is pre-wired with the compact-path data shape so
        _handle_search's compact branch (the only path where structured
        results are available for reranking) runs end-to-end.
        """
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock_ops = MagicMock()
        mock_ops.config.ml.reranker = RerankerConfig()
        # Compact path: search_zim_file_data returns a non-empty payload.
        mock_ops.search_zim_file_data.return_value = {
            "query": "what year was Marie Curie born",
            "results": [
                {"path": "A", "title": "Marie Curie", "snippet": "polonium"},
                {"path": "B", "title": "Curie (unit)", "snippet": "radioactivity"},
            ],
            "next_cursor": None,
            "total": 2,
            "done": True,
            "page_info": {"offset": 0, "limit": 10, "returned_count": 2},
        }
        mock_ops._format_search_text.return_value = "rendered results"
        # _splice_title_match_into_search calls find_title_match internally;
        # short-circuit it so the test doesn't need a real ZIM archive.
        mock_ops.get_search_suggestions.return_value = []
        return SimpleToolsHandler(mock_ops)

    def test_handle_search_uses_reranker_when_available(self) -> None:
        """When BGEReranker.get() returns a reranker, _handle_search routes
        results through rerank() and tracks 'reranker_engaged'."""
        mock_reranker = MagicMock()
        mock_reranker.rerank = MagicMock(
            side_effect=lambda query, candidates, top_k: [
                {**c, "rerank_score": 0.5} for c in candidates[:top_k]
            ]
        )
        handler = self._make_handler()
        with (
            patch(
                "openzim_mcp.ml.reranker.BGEReranker.get",
                return_value=mock_reranker,
            ),
            # _splice_title_match_into_search uses find_title_match which
            # calls into the archive; stub it to return None (no promotion).
            patch(
                "openzim_mcp.simple_tools.find_title_match",
                return_value=None,
            ),
        ):
            result = handler._handle_search(
                query="what year was Marie Curie born",
                zim_file_path="/fake/wiki.zim",
                params={},
                options={"compact": True},
            )
        mock_reranker.rerank.assert_called_once()
        call_kwargs = mock_reranker.rerank.call_args
        assert call_kwargs.kwargs["query"] == "what year was Marie Curie born"
        assert call_kwargs.kwargs["candidates"] == [
            {"path": "A", "title": "Marie Curie", "snippet": "polonium"},
            {"path": "B", "title": "Curie (unit)", "snippet": "radioactivity"},
        ]
        assert handler.get_telemetry().get("reranker_engaged", 0) == 1
        assert result == "rendered results"

    def test_handle_search_passthrough_when_reranker_absent(self) -> None:
        """When BGEReranker.get() returns None, _handle_search skips rerank
        and tracks 'reranker_skipped:not_installed'. Result shape is unchanged."""
        handler = self._make_handler()
        with (
            patch(
                "openzim_mcp.ml.reranker.BGEReranker.get",
                return_value=None,
            ),
            patch(
                "openzim_mcp.simple_tools.find_title_match",
                return_value=None,
            ),
        ):
            result = handler._handle_search(
                query="what year was Marie Curie born",
                zim_file_path="/fake/wiki.zim",
                params={},
                options={"compact": True},
            )
        assert handler.get_telemetry().get("reranker_skipped.not_installed", 0) == 1
        assert handler.get_telemetry().get("reranker_engaged", 0) == 0
        assert result == "rendered results"

    def test_handle_search_emits_passthrough_when_rerank_returns_unscored(
        self,
    ) -> None:
        """Regression: short-query bypass + ml_fallback inference failure both return
        unscored candidates. The handler must NOT count those as reranker_engaged."""
        handler = self._make_handler()
        mock_reranker = MagicMock()
        mock_reranker.rerank = MagicMock(
            side_effect=lambda query, candidates, top_k: candidates[:top_k]
        )
        with (
            patch(
                "openzim_mcp.ml.reranker.BGEReranker.get",
                return_value=mock_reranker,
            ),
            patch(
                "openzim_mcp.simple_tools.find_title_match",
                return_value=None,
            ),
        ):
            result = handler._handle_search(
                query="what year was Marie Curie born",
                zim_file_path="/fake/wiki.zim",
                params={},
                options={"compact": True},
            )
        telemetry = handler.get_telemetry()
        assert telemetry.get("reranker_skipped.passthrough", 0) == 1
        assert telemetry.get("reranker_engaged", 0) == 0
        assert result == "rendered results"


class TestRerankerWiredToHandleFilteredSearch:
    """Verify that _handle_filtered_search (compact mode) routes results
    through the reranker when available, and degrades gracefully when not."""

    def _make_handler(self):  # type: ignore[return]
        """Build a SimpleToolsHandler backed by a MagicMock ZimOperations.

        Pre-wired so the compact path (search_with_filters_data +
        _format_search_text) runs end-to-end.
        """
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock_ops = MagicMock()
        mock_ops.config.ml.reranker = RerankerConfig()
        mock_ops.search_with_filters_data.return_value = {
            "query": "what year was Marie Curie born",
            "results": [
                {"path": "A", "title": "Marie Curie", "snippet": "polonium"},
                {"path": "B", "title": "Curie (unit)", "snippet": "radioactivity"},
            ],
            "next_cursor": None,
            "total": 2,
            "done": True,
            "page_info": {"offset": 0, "limit": 10, "returned_count": 2},
            "namespace_filter": None,
            "content_type_filter": None,
        }
        mock_ops._format_search_text.return_value = "rendered filtered results"
        return SimpleToolsHandler(mock_ops)

    def test_handle_filtered_search_engages_reranker(self) -> None:
        """When BGEReranker.get() returns a reranker, _handle_filtered_search
        (compact mode) routes results through rerank() and tracks
        'reranker_engaged'."""
        mock_reranker = MagicMock()
        mock_reranker.rerank = MagicMock(
            side_effect=lambda query, candidates, top_k: [
                {**c, "rerank_score": 0.5} for c in candidates[:top_k]
            ]
        )
        handler = self._make_handler()
        with patch(
            "openzim_mcp.ml.reranker.BGEReranker.get",
            return_value=mock_reranker,
        ):
            result = handler._handle_filtered_search(
                query="what year was Marie Curie born",
                zim_file_path="/fake/wiki.zim",
                params={},
                options={"compact": True},
            )
        mock_reranker.rerank.assert_called_once()
        call_kwargs = mock_reranker.rerank.call_args
        assert call_kwargs.kwargs["query"] == "what year was Marie Curie born"
        assert handler.get_telemetry().get("reranker_engaged", 0) == 1
        assert result == "rendered filtered results"

    def test_handle_filtered_search_skips_reranker_when_absent(self) -> None:
        """When BGEReranker.get() returns None, compact filtered search skips
        rerank and tracks 'reranker_skipped.not_installed'."""
        handler = self._make_handler()
        with patch(
            "openzim_mcp.ml.reranker.BGEReranker.get",
            return_value=None,
        ):
            result = handler._handle_filtered_search(
                query="what year was Marie Curie born",
                zim_file_path="/fake/wiki.zim",
                params={},
                options={"compact": True},
            )
        assert handler.get_telemetry().get("reranker_skipped.not_installed", 0) == 1
        assert handler.get_telemetry().get("reranker_engaged", 0) == 0
        assert result == "rendered filtered results"

    def test_handle_filtered_search_legacy_path_bypasses_reranker(self) -> None:
        """Non-compact mode takes the legacy string path — reranker is not
        called and no telemetry is emitted."""
        handler = self._make_handler()
        mock_reranker = MagicMock()
        handler.zim_operations.search_with_filters_with_canonical_splice.return_value = (
            "legacy filtered results"
        )
        with patch(
            "openzim_mcp.ml.reranker.BGEReranker.get",
            return_value=mock_reranker,
        ):
            result = handler._handle_filtered_search(
                query="what year was Marie Curie born",
                zim_file_path="/fake/wiki.zim",
                params={},
                options={"compact": False},
            )
        mock_reranker.rerank.assert_not_called()
        assert handler.get_telemetry().get("reranker_engaged", 0) == 0
        assert result == "legacy filtered results"


class TestRerankerWiredToHandleSearchAll:
    """Verify that _handle_search_all (compact mode) routes results through
    the reranker globally across archives."""

    def _make_handler(self):  # type: ignore[return]
        """Build a SimpleToolsHandler with two-archive search_all_data shape."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock_ops = MagicMock()
        mock_ops.config.ml.reranker = RerankerConfig()
        mock_ops.search_all_data.return_value = {
            "query": "what year was Marie Curie born",
            "results": [
                {
                    "zim_file_path": "/a.zim",
                    "name": "archive_a",
                    "has_hits": True,
                    "error": False,
                    "result": {
                        "query": "what year was Marie Curie born",
                        "results": [
                            {
                                "path": "A1",
                                "title": "Marie Curie",
                                "snippet": "polonium",
                            },
                        ],
                        "total": 1,
                        "done": True,
                        "next_cursor": None,
                        "page_info": {"offset": 0, "limit": 5, "returned_count": 1},
                    },
                },
                {
                    "zim_file_path": "/b.zim",
                    "name": "archive_b",
                    "has_hits": True,
                    "error": False,
                    "result": {
                        "query": "what year was Marie Curie born",
                        "results": [
                            {
                                "path": "B1",
                                "title": "Curie (unit)",
                                "snippet": "radioactivity",
                            },
                        ],
                        "total": 1,
                        "done": True,
                        "next_cursor": None,
                        "page_info": {"offset": 0, "limit": 5, "returned_count": 1},
                    },
                },
            ],
            "_meta": {"reason": None, "suggestions": None},
            "files_searched": 2,
            "files_with_hits": 2,
            "files_failed": 0,
            "budget_exceeded": False,
            "done": True,
        }
        return SimpleToolsHandler(mock_ops)

    def test_handle_search_all_engages_reranker(self) -> None:
        """When BGEReranker.get() returns a reranker, _handle_search_all
        (compact mode) routes aggregated results through rerank() and tracks
        'reranker_engaged'."""
        mock_reranker = MagicMock()
        mock_reranker.rerank = MagicMock(
            side_effect=lambda query, candidates, top_k: [
                {**c, "rerank_score": 0.5} for c in candidates[:top_k]
            ]
        )
        handler = self._make_handler()
        with patch(
            "openzim_mcp.ml.reranker.BGEReranker.get",
            return_value=mock_reranker,
        ):
            handler._handle_search_all(
                query="what year was Marie Curie born",
                zim_file_path="/fake/wiki.zim",
                params={},
                options={"compact": True},
            )
        mock_reranker.rerank.assert_called_once()
        call_kwargs = mock_reranker.rerank.call_args
        # Both archive hits should be in the flattened candidates list.
        assert call_kwargs.kwargs["query"] == "what year was Marie Curie born"
        assert len(call_kwargs.kwargs["candidates"]) == 2
        assert handler.get_telemetry().get("reranker_engaged", 0) == 1

    def test_handle_search_all_skips_reranker_when_absent(self) -> None:
        """When BGEReranker.get() returns None, compact search_all skips
        rerank and tracks 'reranker_skipped.not_installed'."""
        handler = self._make_handler()
        with patch(
            "openzim_mcp.ml.reranker.BGEReranker.get",
            return_value=None,
        ):
            handler._handle_search_all(
                query="what year was Marie Curie born",
                zim_file_path="/fake/wiki.zim",
                params={},
                options={"compact": True},
            )
        assert handler.get_telemetry().get("reranker_skipped.not_installed", 0) == 1
        assert handler.get_telemetry().get("reranker_engaged", 0) == 0

    def test_handle_search_all_legacy_path_bypasses_reranker(self) -> None:
        """Non-compact mode takes the legacy string path — reranker is not called."""
        handler = self._make_handler()
        mock_reranker = MagicMock()
        handler.zim_operations.search_all.return_value = '{"results": []}'
        with patch(
            "openzim_mcp.ml.reranker.BGEReranker.get",
            return_value=mock_reranker,
        ):
            handler._handle_search_all(
                query="what year was Marie Curie born",
                zim_file_path="/fake/wiki.zim",
                params={},
                options={"compact": False},
            )
        mock_reranker.rerank.assert_not_called()
        assert handler.get_telemetry().get("reranker_engaged", 0) == 0
