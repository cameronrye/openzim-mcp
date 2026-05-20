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
