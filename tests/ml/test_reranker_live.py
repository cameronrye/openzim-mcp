"""End-to-end tests against the real FastEmbed reranker.

These tests SKIP when the [reranker] extra is not installed. CI runs
them in a dedicated job (see .github/workflows/test.yml). They confirm
the FastEmbed API surface matches our wrapper and that the reranker
actually reorders results in a predictable way.

Model note: tests use Xenova/ms-marco-MiniLM-L-6-v2 (~80 MB) instead
of the production default (BAAI/bge-reranker-base, ~1 GB) to keep
CI download times bounded. Both use the same TextCrossEncoder API."""

from __future__ import annotations

import pytest

from openzim_mcp.config import RerankerConfig
from openzim_mcp.ml.fallback import reset_kill_switches
from openzim_mcp.ml.reranker import BGEReranker

# Lightweight cross-encoder available in fastembed 0.8+; verified to
# produce correct semantic ordering for the test fixtures below.
_TEST_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"


@pytest.fixture(autouse=True)
def _reset() -> None:
    BGEReranker.reset_instance()
    reset_kill_switches()


@pytest.mark.requires_reranker
class TestRerankerIntegration:
    def test_get_loads_model_on_first_call(self) -> None:
        # Generous timeout for cold-cache CI runs.
        cfg = RerankerConfig(model_id=_TEST_MODEL, first_call_timeout_seconds=120.0)
        reranker = BGEReranker.get(cfg)
        assert reranker is not None

    def test_reranks_known_corpus_correctly(self) -> None:
        cfg = RerankerConfig(model_id=_TEST_MODEL, first_call_timeout_seconds=120.0)
        reranker = BGEReranker.get(cfg)
        assert reranker is not None

        # Query is content-fragment shaped — semantic relevance should
        # win over surface keyword overlap.
        query = "what biological pigment makes plants appear green"
        candidates = [
            {
                "path": "Chlorophyll",
                "snippet": (
                    "Chlorophyll is the green pigment in plants that absorbs "
                    "light for photosynthesis."
                ),
                "xapian_score": 0.3,  # intentionally low — Xapian misses it
            },
            {
                "path": "Green",
                "snippet": (
                    "Green is the color between blue and yellow on the visible "
                    "spectrum."
                ),
                "xapian_score": 0.9,  # Xapian's top hit (keyword overlap)
            },
            {
                "path": "Plant",
                "snippet": (
                    "Plants are mainly multicellular eukaryotes in the kingdom "
                    "Plantae."
                ),
                "xapian_score": 0.5,
            },
        ]
        result = reranker.rerank(query, candidates, top_k=3)
        # Chlorophyll should win on semantic match despite low Xapian score.
        assert result[0]["path"] == "Chlorophyll"
        assert all("rerank_score" in c for c in result)

    def test_score_pairs_returns_one_per_pair(self) -> None:
        cfg = RerankerConfig(model_id=_TEST_MODEL, first_call_timeout_seconds=120.0)
        reranker = BGEReranker.get(cfg)
        assert reranker is not None
        pairs = [
            ("query about cats", "Cats are small carnivorous mammals."),
            ("query about cats", "The sun is the star at the center of the solar system."),
        ]
        scores = reranker.score_pairs(pairs)
        assert len(scores) == 2
        # First pair (relevant) should score higher than second (irrelevant).
        assert scores[0] > scores[1]
