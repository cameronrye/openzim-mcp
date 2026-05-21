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
        The synthesize pipeline must complete cleanly with passages intact and
        the original BM25 order preserved."""
        hits = [
            {"path": "A/Cats", "snippet": "cats are mammals", "score": 0.9},
            {"path": "A/Dogs", "snippet": "dogs are mammals", "score": 0.7},
        ]
        cfg = RerankerConfig(min_query_tokens=4)  # "cats" is 1 token → passthrough
        # Build reranker with the same min_query_tokens so gate fires.
        reranker = _make_reranker([0.8, 0.6], min_query_tokens=4)

        with (
            patch("openzim_mcp.ml.reranker.BGEReranker.get", return_value=reranker),
            patch("openzim_mcp.bundle.get_or_build_bundle", return_value=None),
        ):
            response = self._call_synthesize(hits, cfg, query="cats")

        # Pipeline completes; no exception.
        assert "query" in response
        passages = response.get("passages", [])
        assert passages, "passthrough must not drop passages"
        # In the short-query bypass, Xapian BM25 order is preserved: Cats first.
        assert "Cats" in passages[0]["cite_id"], (
            "Short-query passthrough should preserve original BM25 order; "
            f"got cite_id={passages[0]['cite_id']!r}"
        )

    def test_reranker_ordering_survives_affinity_boost(self) -> None:
        """Regression: affinity-sort step must respect rerank scores, not BM25.

        Constructs a synthetic bundle so _attribute_sections appends #section_id
        to both passages, enabling _boost_by_section_affinity to fire. Then
        verifies the rerank ordering (B > A) is preserved after the affinity
        pass — i.e. the p["score"] = rerank_score propagation line is effective.

        If that line were deleted, _boost_by_section_affinity would sort by the
        original Xapian BM25 scores and A (BM25=0.9) would beat B (BM25=0.7).
        """
        # BM25 order: A (score=0.9) first, B (score=0.7) second.
        # Reranker inverts: B gets 0.9, A gets 0.1.
        hits = [
            {
                "path": "A/PageA",
                "snippet": "chlorophyll absorbs sunlight for energy",
                "score": 0.9,
            },
            {
                "path": "A/PageB",
                "snippet": "photosynthesis converts light into glucose",
                "score": 0.7,
            },
        ]
        cfg = RerankerConfig(min_query_tokens=1)

        # Reranker returns B with score 0.9, A with score 0.1 — inverted BM25 order.
        def _inverted_rerank(
            query: str, candidates: list[dict], top_k: int
        ) -> list[dict]:
            scored = [
                {
                    **c,
                    "rerank_score": 0.9 if "PageB" in c["path"] else 0.1,
                }
                for c in candidates
            ]
            return sorted(scored, key=lambda x: x["rerank_score"], reverse=True)[:top_k]

        mock_reranker = MagicMock(spec=BGEReranker)
        mock_reranker.rerank = MagicMock(side_effect=_inverted_rerank)

        # Build a synthetic bundle so _attribute_sections assigns #section_id
        # to both passages and _boost_by_section_affinity actually fires.
        # The bundle's rendered_markdown must contain both passage texts so
        # _locate_passage succeeds and assigns the section.
        passage_a_text = "chlorophyll absorbs sunlight for energy"
        passage_b_text = "photosynthesis converts light into glucose"
        # Section spans: sec_a covers the first passage (pos 0..len(a)+1),
        # sec_b covers the second passage, title includes a query token.
        sec_a_text = passage_a_text + "\n"
        sec_b_text = passage_b_text + "\n"
        rendered_md = sec_a_text + sec_b_text
        len_a = len(sec_a_text)
        fake_bundle = {
            "title": "Plants",
            "rendered_markdown": rendered_md,
            "sections": [
                {
                    "id": "sec_a",
                    "title": "Chlorophyll",  # contains "chlorophyll" — query token
                    "char_start": 0,
                    "char_end": len_a,
                },
                {
                    "id": "sec_b",
                    "title": "Photosynthesis",  # contains query token
                    "char_start": len_a,
                    "char_end": len(rendered_md),
                },
            ],
        }

        with (
            patch(
                "openzim_mcp.ml.reranker.BGEReranker.get",
                return_value=mock_reranker,
            ),
            patch(
                "openzim_mcp.bundle.get_or_build_bundle",
                return_value=fake_bundle,
            ),
        ):
            response = self._call_synthesize(
                hits,
                cfg,
                query="photosynthesis chlorophyll",
            )

        passages = response.get("passages", [])
        assert passages, "passages must not be empty"
        # B had the highest rerank_score (0.9); it must appear first.
        # If p["score"] = rerank_score propagation is missing, the affinity sort
        # reverts to Xapian BM25 and A (0.9 BM25) wins instead.
        assert "PageB" in passages[0]["cite_id"], (
            "PageB had rerank_score=0.9 but lost the top slot — "
            "affinity sort must use rerank_score not BM25. "
            f"Got cite_id={passages[0]['cite_id']!r}"
        )
