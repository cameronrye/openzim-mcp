"""Regression tests for the code-scanning alert fixes.

Two alerts, two behaviour changes worth pinning:

* CodeQL ``py/catch-base-exception`` — the reranker's model-load worker
  caught ``BaseException`` purely to guarantee the caller always got a
  queue item. The guarantee is real; the handler was not the way to get
  it. It now lives in a ``finally``, so a ``BaseException`` exit still
  wakes the caller instead of stranding it on the full timeout, and is
  no longer laundered into the caller's thread as if the caller itself
  had been interrupted.

* Bandit ``B112`` (try/except/continue) — ``_heading_visible_text``
  swallowed every exception from ``Tag.select`` with a bare ``continue``,
  so a typo in ``UNWANTED_HTML_SELECTORS`` was indistinguishable from a
  selector that legitimately matched nothing.
"""

import logging
import threading
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup

from openzim_mcp import content_processor as cp


class _WorkerAbort(BaseException):
    """A BaseException that is not an Exception, like SystemExit."""


def _heading(html: str):
    tag = BeautifulSoup(html, "html.parser").find(["h1", "h2", "h3"])
    assert tag is not None
    return tag


class TestRerankerWorkerAlwaysReportsBack:
    """CodeQL py/catch-base-exception — reranker.py ``_worker``."""

    def test_base_exception_in_loader_wakes_caller_instead_of_timing_out(
        self,
    ) -> None:
        """A BaseException must not strand the caller for the whole timeout.

        Before the fix the ``except BaseException`` handler was what put
        the item on the queue. Removing it naively would mean the worker
        thread dies silently and the caller blocks until
        ``first_call_timeout_seconds`` elapses, then reports a misleading
        TimeoutError for a load that had already failed. The ``finally``
        keeps the wake-up; a TimeoutError here is the regression.
        """
        from openzim_mcp.ml.reranker import BGEReranker, RerankerConfig

        def abort(_model_id, _cache_dir, **_kwargs):
            raise _WorkerAbort("interpreter is going down")

        cfg = RerankerConfig(first_call_timeout_seconds=5.0)
        with patch("openzim_mcp.ml.reranker._load_model", side_effect=abort):
            # The worker re-raises after the finally; silence the thread
            # excepthook so the expected traceback is not printed.
            with patch.object(threading, "excepthook", lambda _args: None):
                with pytest.raises(RuntimeError) as excinfo:
                    BGEReranker._load_with_timeout(cfg)

        assert not isinstance(excinfo.value, TimeoutError), (
            "caller waited out the full timeout — the worker died without "
            "posting to the queue"
        )
        assert "terminated abnormally" in str(excinfo.value)

    def test_system_exit_is_not_re_raised_in_the_caller_thread(self) -> None:
        """SystemExit from the ML stack must not become the caller's exit.

        Relaying it verbatim made a worker-thread SystemExit look like the
        calling process had asked to terminate.
        """
        from openzim_mcp.ml.reranker import BGEReranker, RerankerConfig

        def abort(_model_id, _cache_dir, **_kwargs):
            raise SystemExit(3)

        cfg = RerankerConfig(first_call_timeout_seconds=5.0)
        with patch("openzim_mcp.ml.reranker._load_model", side_effect=abort):
            with pytest.raises(RuntimeError):
                BGEReranker._load_with_timeout(cfg)

    def test_ordinary_exception_is_still_relayed_verbatim(self) -> None:
        """The real cause must survive, not be replaced by the sentinel."""
        from openzim_mcp.ml.reranker import BGEReranker, RerankerConfig

        cause = OSError("model file is corrupt")
        cfg = RerankerConfig(first_call_timeout_seconds=5.0)
        with patch("openzim_mcp.ml.reranker._load_model", side_effect=cause):
            with pytest.raises(OSError) as excinfo:
                BGEReranker._load_with_timeout(cfg)

        assert excinfo.value is cause


class TestHeadingSelectorFailuresAreVisible:
    """Bandit B112 — content_processor.py ``_heading_visible_text``."""

    def test_malformed_selector_is_skipped_and_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        heading = _heading('<h2>History<span class="mw-editsection">[edit]</span></h2>')

        with patch.object(cp, "UNWANTED_HTML_SELECTORS", [".a{b", ".mw-editsection"]):
            with caplog.at_level(logging.DEBUG, logger="openzim_mcp.content_processor"):
                text = cp._heading_visible_text(heading)

        assert text == "History", "the surviving selector must still be applied"
        assert any(
            ".a{b" in record.getMessage() for record in caplog.records
        ), "the unusable selector was swallowed silently"

    def test_unsupported_pseudo_class_is_skipped_and_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """soupsieve raises NotImplementedError, not SelectorSyntaxError."""
        heading = _heading('<h2>Etymology<sup class="reference">[1]</sup></h2>')

        with patch.object(
            cp, "UNWANTED_HTML_SELECTORS", ["div::bogus", "sup.reference"]
        ):
            with caplog.at_level(logging.DEBUG, logger="openzim_mcp.content_processor"):
                text = cp._heading_visible_text(heading)

        assert text == "Etymology"
        assert any("div::bogus" in record.getMessage() for record in caplog.records)

    def test_valid_selectors_are_unaffected(self) -> None:
        """The happy path keeps its behaviour: no logging, full strip."""
        heading = _heading('<h2>History<span class="mw-editsection">[edit]</span></h2>')
        assert cp._heading_visible_text(heading) == "History"
