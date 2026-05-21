"""Tests for the `openzim-mcp download-models` CLI."""

from __future__ import annotations

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
