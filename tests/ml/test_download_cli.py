"""Tests for the `openzim-mcp download-models` CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.ml.cli.download import download_models_main


class TestDownloadModelsCli:
    def test_reports_when_no_extras_installed(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("openzim_mcp.ml.cli.download.detect") as mock_detect:
            mock_detect.return_value = MagicMock(reranker=False)
            rc = download_models_main(argv=[])
            captured = capsys.readouterr()
            assert rc == 0
            assert "no ml extras installed" in captured.out.lower()

    def test_downloads_reranker_when_extra_present(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch("openzim_mcp.ml.cli.download.detect") as mock_detect,
            patch("openzim_mcp.ml.cli.download._stage_reranker") as mock_stage,
        ):
            mock_detect.return_value = MagicMock(reranker=True)
            mock_stage.return_value = None  # success
            rc = download_models_main(argv=[])
            captured = capsys.readouterr()
            assert rc == 0
            assert "reranker" in captured.out.lower()
            mock_stage.assert_called_once()

    def test_returns_nonzero_on_stage_failure(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch("openzim_mcp.ml.cli.download.detect") as mock_detect,
            patch("openzim_mcp.ml.cli.download._stage_reranker") as mock_stage,
        ):
            mock_detect.return_value = MagicMock(reranker=True)
            mock_stage.side_effect = RuntimeError("network error")
            rc = download_models_main(argv=[])
            captured = capsys.readouterr()
            assert rc == 1
            assert "failed" in captured.out.lower()

    def test_honours_cache_dir_env_var(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Sweep-PR regression: the CLI must read
        ``OPENZIM_MCP_ML__RERANKER__CACHE_DIR`` so the air-gapped
        pre-stage workflow lands files where the runtime expects them.
        Direct ``RerankerConfig()`` instantiation silently ignored env
        vars because it inherits from ``BaseModel``, not ``BaseSettings``."""
        cache_dir = tmp_path / "fastembed-staging"
        cache_dir.mkdir()
        monkeypatch.setenv("OPENZIM_MCP_ML__RERANKER__CACHE_DIR", str(cache_dir))
        with (
            patch("openzim_mcp.ml.cli.download.detect") as mock_detect,
            patch("openzim_mcp.ml.cli.download._stage_reranker") as mock_stage,
        ):
            mock_detect.return_value = MagicMock(reranker=True)
            rc = download_models_main(argv=[])
            assert rc == 0
            (cfg,) = mock_stage.call_args.args
            assert cfg.cache_dir == cache_dir

    def test_honours_model_id_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Same root cause: ``OPENZIM_MCP_ML__RERANKER__MODEL_ID`` must
        flow through to the staging call. The CLI flag still overrides
        the env var (argparse default left None when --reranker-model-id
        absent)."""
        monkeypatch.setenv(
            "OPENZIM_MCP_ML__RERANKER__MODEL_ID", "BAAI/bge-reranker-large"
        )
        with (
            patch("openzim_mcp.ml.cli.download.detect") as mock_detect,
            patch("openzim_mcp.ml.cli.download._stage_reranker") as mock_stage,
        ):
            mock_detect.return_value = MagicMock(reranker=True)
            rc = download_models_main(argv=[])
            assert rc == 0
            (cfg,) = mock_stage.call_args.args
            assert cfg.model_id == "BAAI/bge-reranker-large"

    def test_cli_flag_overrides_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(
            "OPENZIM_MCP_ML__RERANKER__MODEL_ID", "BAAI/bge-reranker-base"
        )
        with (
            patch("openzim_mcp.ml.cli.download.detect") as mock_detect,
            patch("openzim_mcp.ml.cli.download._stage_reranker") as mock_stage,
        ):
            mock_detect.return_value = MagicMock(reranker=True)
            rc = download_models_main(
                argv=["--reranker-model-id", "jinaai/jina-reranker-v3"]
            )
            assert rc == 0
            (cfg,) = mock_stage.call_args.args
            assert cfg.model_id == "jinaai/jina-reranker-v3"
