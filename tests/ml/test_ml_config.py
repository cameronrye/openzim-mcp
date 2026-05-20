"""Tests for MLConfig + RerankerConfig wiring on OpenZimMcpConfig."""

from __future__ import annotations

from pathlib import Path

import pytest

from openzim_mcp.config import MLConfig, OpenZimMcpConfig, RerankerConfig


class TestRerankerConfig:
    def test_defaults(self) -> None:
        cfg = RerankerConfig()
        assert cfg.enabled is True
        assert cfg.model_id == "Xenova/bge-reranker-base-onnx"
        assert cfg.candidate_pool_size == 50
        assert cfg.final_top_k == 10
        assert cfg.max_query_length == 256
        assert cfg.max_passage_length == 512
        assert cfg.min_query_tokens == 4
        assert cfg.first_call_timeout_seconds == 5.0
        assert cfg.cache_dir is None

    def test_pool_size_bounds(self) -> None:
        # Pydantic v2 validation: pool size must be positive
        with pytest.raises(Exception):
            RerankerConfig(candidate_pool_size=0)
        # Reasonable upper bound prevents runaway memory
        with pytest.raises(Exception):
            RerankerConfig(candidate_pool_size=10000)

    def test_min_query_tokens_bounds(self) -> None:
        # 0 disables the skip gate; that's allowed.
        RerankerConfig(min_query_tokens=0)
        # Negative is not.
        with pytest.raises(Exception):
            RerankerConfig(min_query_tokens=-1)


class TestMLConfig:
    def test_defaults(self) -> None:
        cfg = MLConfig()
        assert isinstance(cfg.reranker, RerankerConfig)
        assert cfg.reranker.enabled is True

    def test_attaches_to_openzim_config(self, tmp_path: Path) -> None:
        zim_dir = tmp_path / "zim"
        zim_dir.mkdir()
        cfg = OpenZimMcpConfig(allowed_directories=[str(zim_dir)])
        assert isinstance(cfg.ml, MLConfig)
        assert isinstance(cfg.ml.reranker, RerankerConfig)
