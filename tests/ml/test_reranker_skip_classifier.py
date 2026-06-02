"""Unit tests for the transient-download-failure classifier.

The live reranker tests (`test_reranker_live.py`) download a model from
HuggingFace at test time. When HuggingFace's CDN is transiently
unavailable (see CI run #800), that download fails and the tests must
SKIP rather than fail — an external outage is not a code regression.

But a *genuine* regression (FastEmbed renamed a kwarg, the model id is
bad, the API shape drifted) must still FAIL loudly. The classifier under
test is what draws that line, so it gets exhaustive coverage here: every
"skip" verdict is a promise that we are not masking a real bug."""

from __future__ import annotations

import pytest

from tests.ml._reranker_test_support import is_transient_download_failure


class TestTransientDownloadFailureClassifier:
    @pytest.mark.parametrize(
        "exc",
        [
            # The exact message FastEmbed raises after exhausting its
            # download retries — the failure mode that broke CI #800.
            RuntimeError(
                "Could not load model Xenova/ms-marco-MiniLM-L-6-v2 " "from any source."
            ),
            ValueError("Could not download model from HuggingFace"),
            ConnectionError("Connection reset by peer"),
            TimeoutError("read operation timed out"),
            OSError(
                "HTTPSConnectionPool(host='huggingface.co', port=443): "
                "Max retries exceeded"
            ),
            RuntimeError("Server returned 503 Service Temporarily Unavailable"),
        ],
    )
    def test_transient_network_failures_are_skippable(self, exc: BaseException) -> None:
        assert is_transient_download_failure(exc) is True

    @pytest.mark.parametrize(
        "exc",
        [
            # A renamed kwarg — real API drift, must fail not skip.
            TypeError(
                "TextCrossEncoder.__init__() got an unexpected keyword "
                "argument 'model_name'"
            ),
            # Model genuinely not in the registry — real regression.
            ValueError("Model some/bad-model is not supported in TextCrossEncoder."),
            # Inference-shape bug — real regression.
            AssertionError("expected one score per pair"),
            KeyError("rerank_score"),
        ],
    )
    def test_genuine_regressions_are_not_skippable(self, exc: BaseException) -> None:
        assert is_transient_download_failure(exc) is False
