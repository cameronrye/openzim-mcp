"""Tests for QueryRewriteConfig wiring on OpenZimMcpConfig."""

from __future__ import annotations

from pathlib import Path

from openzim_mcp.config import OpenZimMcpConfig, QueryRewriteConfig


class TestQueryRewriteConfig:
    def test_defaults(self) -> None:
        cfg = QueryRewriteConfig()
        assert cfg.enabled is True
        assert cfg.misspelling_map_path is None
        assert cfg.misspelling_exclusion_path is None
        assert cfg.stopword_phrase_probe is True

    def test_disable_master_switch(self) -> None:
        cfg = QueryRewriteConfig(enabled=False)
        assert cfg.enabled is False

    def test_override_misspelling_paths(self, tmp_path: Path) -> None:
        mp = tmp_path / "custom_misspellings.txt"
        mp.write_text("foo=bar\n")
        cfg = QueryRewriteConfig(misspelling_map_path=mp)
        assert cfg.misspelling_map_path == mp

    def test_attaches_to_openzim_config(self, tmp_path: Path) -> None:
        zim_dir = tmp_path / "zim"
        zim_dir.mkdir()
        cfg = OpenZimMcpConfig(allowed_directories=[str(zim_dir)])
        assert isinstance(cfg.query_rewrite, QueryRewriteConfig)
        assert cfg.query_rewrite.enabled is True
