"""Unit tests for ml_fallback decorator."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from openzim_mcp.ml.fallback import ml_fallback, reset_kill_switches


@pytest.fixture(autouse=True)
def _reset() -> None:
    """Each test starts with empty kill-switch state."""
    reset_kill_switches()


def _fallback(*args: Any, **kwargs: Any) -> str:
    return "fallback"


class TestMlFallback:
    def test_success_path_returns_inner_result(self) -> None:
        @ml_fallback(feature="reranker", on_failure=_fallback)
        def inner() -> str:
            return "inner"

        assert inner() == "inner"

    def test_first_exception_logs_warning_and_returns_fallback(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)

        @ml_fallback(feature="reranker", on_failure=_fallback)
        def inner() -> str:
            raise RuntimeError("boom")

        result = inner()
        assert result == "fallback"
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "reranker" in warnings[0].message.lower()

    def test_subsequent_calls_after_failure_skip_inner(self) -> None:
        call_count = 0

        @ml_fallback(feature="reranker", on_failure=_fallback)
        def inner() -> str:
            nonlocal call_count
            call_count += 1
            raise RuntimeError("boom")

        inner()  # triggers kill switch
        inner()  # should NOT call inner again
        inner()
        assert call_count == 1  # only the first call entered the wrapped function

    def test_subsequent_failures_log_debug_only(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)

        @ml_fallback(feature="reranker", on_failure=_fallback)
        def inner() -> str:
            raise RuntimeError("boom")

        inner()  # WARNING
        inner()  # DEBUG (kill-switch path)

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        debugs = [r for r in caplog.records if r.levelname == "DEBUG"]
        assert len(warnings) == 1
        assert any("reranker" in d.message.lower() for d in debugs)

    def test_kill_switch_is_per_feature(self) -> None:
        """A failure on reranker doesn't disable a hypothetical other feature."""

        @ml_fallback(feature="reranker", on_failure=_fallback)
        def reranker_inner() -> str:
            raise RuntimeError("boom")

        @ml_fallback(feature="other", on_failure=_fallback)
        def other_inner() -> str:
            return "other_ok"

        reranker_inner()
        assert other_inner() == "other_ok"
