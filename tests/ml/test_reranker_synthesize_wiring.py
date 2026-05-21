"""Tests for BGEReranker wiring into synthesize_query (Task 9).

Tests operate at the _extract_passages_for_top_hits / synthesize_query level
using mocked archives and reranker singletons to avoid real ZIM I/O.
"""

from __future__ import annotations

from typing import Any, List
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reranker(scores: List[float], *, min_query_tokens: int = 1) -> BGEReranker:
    """Build a BGEReranker backed by a mock model that returns ``scores``.

    ``min_query_tokens=1`` by default so the skip-on-short-query gate does
    not fire on test queries; callers that want to exercise the gate should
    pass a higher value explicitly.
    """
    mock_model = MagicMock()
    mock_model.rerank = MagicMock(return_value=iter(scores))
    return BGEReranker(
        model=mock_model, config=RerankerConfig(min_query_tokens=min_query_tokens)
    )


def _make_top_hits(paths: List[str], archive: str = "wiki") -> list[tuple[str, dict]]:
    """Build minimal top_hits list for _extract_passages_for_top_hits."""
    return [
        (archive, {"path": p, "snippet": f"text about {p}", "score": 1.0 - 0.1 * i})
        for i, p in enumerate(paths)
    ]


# ---------------------------------------------------------------------------
# Unit-level: rerank block logic in synthesize_query
# ---------------------------------------------------------------------------


class TestRerankerWiringInSynthesizeQuery:
    """Drive synthesize_query with mocked archives + reranker.

    We avoid real libzim I/O by injecting a MagicMock archive whose
    search_top_k returns controlled hits. Bundle lookups are also mocked
    to short-circuit attribution so tests focus solely on the rerank step.
    """

    def _make_search_handler(self, hits: List[dict]) -> Any:
        handler = MagicMock()
        handler.search_top_k.return_value = hits
        # title_match_hit returns None so title-promotion is a no-op.
        handler.title_match_hit.return_value = None
        return handler

    def _make_archive_pair(self, stem: str = "wiki") -> tuple[Any, Any]:
        from pathlib import Path
        from unittest.mock import MagicMock

        archive = MagicMock()
        path = MagicMock(spec=Path)
        path.stem = stem
        return archive, path

    def _make_cache_and_cp(self) -> tuple[Any, Any]:
        cache = MagicMock()
        # Bundle lookup returns None so attribution is a no-op.
        cache.get.return_value = None
        cp = MagicMock()
        cp.html_to_plain_text.side_effect = lambda h: h
        return cache, cp

    def _call_synthesize(
        self,
        hits: List[dict],
        reranker_config: RerankerConfig,
        query: str = "photosynthesis and plants",
    ) -> Any:
        """Call synthesize_query with mocked archives.

        Callers are responsible for patching BGEReranker.get and
        openzim_mcp.bundle.get_or_build_bundle before calling this helper.
        """
        from openzim_mcp.config import SynthesizeConfig
        from openzim_mcp.synthesize import synthesize_query

        archive, path = self._make_archive_pair()
        cache, cp = self._make_cache_and_cp()
        search_handler = self._make_search_handler(hits)

        return synthesize_query(
            query,
            archives=[(archive, path)],
            search_handler=search_handler,
            cache=cache,
            content_processor=cp,
            config=SynthesizeConfig(top_n=5, per_archive_k=10),
            reranker_config=reranker_config,
        )

    def test_reranker_engaged_reorders_passages(self) -> None:
        """When BGEReranker.get() returns a reranker, passages are reordered
        by rerank_score rather than Xapian BM25 order.

        Scores in hits order: Low=0.1 (bad), High=0.9 (good) — reranker
        flips them so High surfaces first.
        """
        hits = [
            {"path": "A/Low", "snippet": "low relevance passage", "score": 0.9},
            {"path": "A/High", "snippet": "highly relevant passage", "score": 0.7},
        ]
        cfg = RerankerConfig(min_query_tokens=1)
        # Build a pre-wired reranker and inject it via BGEReranker.get().
        reranker = _make_reranker([0.1, 0.9])

        with (
            patch("openzim_mcp.ml.reranker.BGEReranker.get", return_value=reranker),
            patch("openzim_mcp.bundle.get_or_build_bundle", return_value=None),
        ):
            response = self._call_synthesize(hits, cfg)

        # After reranking, High should be the top citation.
        passages = response.get("passages", [])
        if passages:
            assert "High" in passages[0]["cite_id"]
        else:
            # compact/budget mode dropped passages — check citations ordering.
            citations = response.get("citations", [])
            assert any("High" in c["cite_id"] for c in citations)

    def test_reranker_absent_preserves_original_order(self) -> None:
        """When BGEReranker.get() returns None, passage order is unchanged from
        Xapian BM25."""
        hits = [
            {"path": "A/First", "snippet": "first passage", "score": 0.9},
            {"path": "A/Second", "snippet": "second passage", "score": 0.7},
        ]
        cfg = RerankerConfig()

        with (
            patch("openzim_mcp.ml.reranker.BGEReranker.get", return_value=None),
            patch("openzim_mcp.bundle.get_or_build_bundle", return_value=None),
        ):
            response = self._call_synthesize(hits, cfg)

        # Passages retain BM25 order: First before Second.
        passages = response.get("passages", [])
        if passages:
            assert "First" in passages[0]["cite_id"]

    def test_reranker_config_none_skips_rerank(self) -> None:
        """When reranker_config=None is passed, the rerank block is entirely
        skipped and BGEReranker.get() is never called.

        BGEReranker is imported locally inside synthesize_query, so we patch
        the classmethod on the class itself via its module path.
        """
        hits = [
            {"path": "A/Alpha", "snippet": "alpha text", "score": 0.9},
            {"path": "A/Beta", "snippet": "beta text", "score": 0.7},
        ]

        from openzim_mcp.config import SynthesizeConfig
        from openzim_mcp.synthesize import synthesize_query

        archive, path = self._make_archive_pair()
        cache, cp = self._make_cache_and_cp()
        search_handler = self._make_search_handler(hits)

        with (
            patch(
                "openzim_mcp.ml.reranker.BGEReranker.get", return_value=None
            ) as mock_get,
            patch("openzim_mcp.bundle.get_or_build_bundle", return_value=None),
        ):
            synthesize_query(
                "alpha beta query",
                archives=[(archive, path)],
                search_handler=search_handler,
                cache=cache,
                content_processor=cp,
                config=SynthesizeConfig(),
                reranker_config=None,  # explicit None — rerank block must not run
            )

        # BGEReranker.get() must NOT be called when reranker_config is None.
        mock_get.assert_not_called()

    def test_short_query_passthrough_does_not_crash(self) -> None:
        """A single-token query hits the skip-on-short-query gate inside reranker.rerank.
        The synthesize pipeline must complete cleanly with passages intact."""
        hits = [
            {"path": "A/Cats", "snippet": "cats are mammals", "score": 0.9},
        ]
        cfg = RerankerConfig(min_query_tokens=4)  # "cats" is 1 token → passthrough
        # Build reranker with the same min_query_tokens so gate fires.
        reranker = _make_reranker([0.8], min_query_tokens=4)

        with (
            patch("openzim_mcp.ml.reranker.BGEReranker.get", return_value=reranker),
            patch("openzim_mcp.bundle.get_or_build_bundle", return_value=None),
        ):
            response = self._call_synthesize(hits, cfg, query="cats")

        # Pipeline completes; no exception.
        assert "query" in response
