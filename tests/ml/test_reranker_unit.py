"""Unit tests for BGEReranker (mocked FastEmbed)."""

from __future__ import annotations

from typing import List  # noqa: F401 — used by Task 5's TestScorePairs / TestRerank
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.config import (  # noqa: F401 — used by Task 5's TestScorePairs / TestRerank
    RerankerConfig,
)
from openzim_mcp.ml import detect
from openzim_mcp.ml.fallback import reset_kill_switches
from openzim_mcp.ml.reranker import BGEReranker


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    BGEReranker.reset_instance()
    reset_kill_switches()
    detect.cache_clear()


class TestBGEGet:
    def test_returns_none_when_extra_absent(self) -> None:
        with patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = None
            assert BGEReranker.get() is None

    def test_returns_none_when_disabled_via_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENZIM_RERANKER_DISABLE", "1")
        # Even if the extra is "installed", env disable wins.
        with patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec:
            mock_spec.return_value = object()
            assert BGEReranker.get() is None

    def test_returns_singleton_when_extra_present(self) -> None:
        with (
            patch("openzim_mcp.ml.importlib.util.find_spec") as mock_spec,
            patch("openzim_mcp.ml.reranker._load_model") as mock_load,
        ):
            mock_spec.return_value = object()
            mock_load.return_value = MagicMock(name="fastembed_reranker")
            a = BGEReranker.get()
            b = BGEReranker.get()
            assert a is not None
            assert a is b  # same singleton
            assert mock_load.call_count == 1
