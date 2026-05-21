"""Unit tests for openzim_mcp.ml.__init__'s feature-detection registry."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openzim_mcp.ml import MLFeatures, detect


class TestDetectRegistry:
    def setup_method(self) -> None:
        # Clear the lru_cache between tests so each test gets a fresh detect()
        detect.cache_clear()

    def test_returns_frozen_dataclass(self) -> None:
        features = detect()
        assert isinstance(features, MLFeatures)
        # frozen dataclass: mutation should raise
        with pytest.raises(Exception):
            features.reranker = not features.reranker  # type: ignore[misc]

    def test_reranker_true_when_fastembed_importable(self) -> None:
        with patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = object()  # truthy: package found
            features = detect()
            assert features.reranker is True
        # Verify find_spec was called with the expected argument
        mock_spec.assert_called_with("fastembed")

    def test_reranker_false_when_fastembed_missing(self) -> None:
        with patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = None  # falsy: package not found
            features = detect()
            assert features.reranker is False

    def test_detect_is_cached(self) -> None:
        # Two calls should hit find_spec only once
        with patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = object()
            detect()
            detect()
            assert mock_spec.call_count == 1
