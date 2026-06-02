"""End-to-end tests against the real FastEmbed reranker.

These tests SKIP when the [reranker] extra is not installed, and the
download-dependent ones also SKIP when the model can't be fetched from
HuggingFace (transient CDN/network outage — not a regression; see the
`_require_live_model` fixture). CI runs them in a dedicated job (see
.github/workflows/test.yml), which pre-stages the model with retries
first. They confirm the FastEmbed API surface matches our wrapper and
that the reranker actually reorders results in a predictable way.

Model note: tests use Xenova/ms-marco-MiniLM-L-6-v2 (~80 MB) instead
of the production default (BAAI/bge-reranker-base, ~1 GB) to keep
CI download times bounded. Both use the same TextCrossEncoder API."""

from __future__ import annotations

import pytest

from openzim_mcp.config import RerankerConfig
from openzim_mcp.ml.fallback import reset_kill_switches
from openzim_mcp.ml.reranker import BGEReranker, _load_model
from tests.ml._reranker_test_support import is_transient_download_failure

# Lightweight cross-encoder available in fastembed 0.8+; verified to
# produce correct semantic ordering for the test fixtures below.
_TEST_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"


@pytest.fixture(autouse=True)
def _reset() -> None:
    BGEReranker.reset_instance()
    reset_kill_switches()


@pytest.fixture(scope="module")
def _require_live_model() -> None:
    """Probe the test model once before the download-dependent tests run.

    If FastEmbed can't fetch it because HuggingFace is unreachable (a
    transient CDN/network outage — exactly what broke CI run #800, where
    one runner downloaded fine and another got a CloudFront error on the
    same commit), SKIP rather than fail: an external outage is not a code
    regression. Genuine load errors (renamed kwarg, dropped model, API
    drift) are re-raised and still fail the suite — see
    `is_transient_download_failure` for where that line is drawn.

    On success the model lands in FastEmbed's cache, so each test's
    `BGEReranker.get()` call is a warm-cache hit."""
    try:
        _load_model(_TEST_MODEL, None)
    except Exception as exc:  # noqa: BLE001 — re-raised unless transient
        if is_transient_download_failure(exc):
            pytest.skip(
                f"reranker test model unavailable — transient download/"
                f"network failure, not a regression: {exc}"
            )
        raise


@pytest.mark.requires_reranker
class TestRerankerIntegration:
    def test_get_loads_model_on_first_call(self, _require_live_model: None) -> None:
        # Generous timeout for cold-cache CI runs.
        cfg = RerankerConfig(model_id=_TEST_MODEL, first_call_timeout_seconds=120.0)
        reranker = BGEReranker.get(cfg)
        assert reranker is not None

    def test_reranks_known_corpus_correctly(self, _require_live_model: None) -> None:
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

    def test_score_pairs_returns_one_per_pair(self, _require_live_model: None) -> None:
        cfg = RerankerConfig(model_id=_TEST_MODEL, first_call_timeout_seconds=120.0)
        reranker = BGEReranker.get(cfg)
        assert reranker is not None
        pairs = [
            ("query about cats", "Cats are small carnivorous mammals."),
            (
                "query about cats",
                "The sun is the star at the center of the solar system.",
            ),
        ]
        scores = reranker.score_pairs(pairs)
        assert len(scores) == 2
        # First pair (relevant) should score higher than second (irrelevant).
        assert scores[0] > scores[1]

    def test_production_default_model_is_supported_by_fastembed(self) -> None:
        """Guard: the model ID baked into RerankerConfig must remain in
        FastEmbed's supported-models registry. If FastEmbed renames or
        drops `BAAI/bge-reranker-base`, users hit a hard load failure
        on first MCP query — catch the regression here instead."""
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        supported = TextCrossEncoder.list_supported_models()
        # list_supported_models() returns a list of dicts; extract the model names
        supported_names = {entry["model"] for entry in supported}
        prod_default = RerankerConfig().model_id
        assert prod_default in supported_names, (
            f"RerankerConfig.model_id default ({prod_default!r}) is not in "
            f"FastEmbed's supported models list. Either FastEmbed dropped it "
            f"or the default needs updating in openzim_mcp/config.py."
        )
