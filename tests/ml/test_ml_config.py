"""Tests for MLConfig + RerankerConfig wiring on OpenZimMcpConfig."""

from __future__ import annotations

from pathlib import Path

import pytest

from openzim_mcp.config import MLConfig, OpenZimMcpConfig, RerankerConfig


class TestRerankerConfig:
    def test_defaults(self) -> None:
        cfg = RerankerConfig()
        assert cfg.enabled is True
        assert cfg.model_id == "BAAI/bge-reranker-base"
        assert cfg.final_top_k == 10
        assert cfg.max_query_length == 256
        assert cfg.max_passage_length == 512
        assert cfg.min_query_tokens == 4
        assert cfg.first_call_timeout_seconds == pytest.approx(15.0)
        assert cfg.cache_dir is None

    def test_stale_candidate_pool_size_env_var_tolerated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # ``candidate_pool_size`` was removed (it was never read; the
        # reranker only ever sees the caller's page of results, so the
        # documented recall benefit did not exist). Deployments that
        # still export the old nested env var must not error at
        # startup: RerankerConfig is a plain BaseModel with pydantic's
        # default ``extra='ignore'``, so the stale value is dropped.
        zim_dir = tmp_path / "zim"
        zim_dir.mkdir()
        monkeypatch.setenv("OPENZIM_MCP_ML__RERANKER__CANDIDATE_POOL_SIZE", "100")
        cfg = OpenZimMcpConfig(allowed_directories=[str(zim_dir)])
        assert not hasattr(cfg.ml.reranker, "candidate_pool_size")

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
