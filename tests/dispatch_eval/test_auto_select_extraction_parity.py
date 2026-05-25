"""Gate 0a — auto-select-extraction parity diff-test.

For each archive-count scenario (0 / 1 / N files / ``list_zim_files_data``
raises), assert that the old instance method
(``SimpleToolsHandler._auto_select_zim_file``) and the extracted module-level
function (``topic_preprocessing.auto_select_zim_file``) produce byte-identical
return values AND identical log records.

## Fixture choice

The plan template referenced a ``configured_server`` fixture that doesn't exist
in this repo. A3a's scenarios STUB ``list_zim_files_data`` per case, so a full
configured-server surface is unnecessary — a ``MagicMock``-backed
``SimpleToolsHandler`` (the same pattern ``tests/_promote_fixtures.make_disambig_handler``
uses for the post-b11/b12 sweep tests) gives us full coverage of the four
arms without any real ZIM, libzim, or filesystem dependency.

## Signatures verified against the codebase

- ``SimpleToolsHandler.__init__(zim_operations)`` (simple_tools.py:160)
- ``SimpleToolsHandler._auto_select_zim_file(self)`` (simple_tools.py:5784)
  consumes ``self.zim_operations.list_zim_files_data() -> list[dict]`` where
  each dict carries at least a ``"path"`` key (archive.py:299-334 returns
  ``{"name", "path", "directory", "size", "size_bytes", "modified"}`` — the
  selector only reads ``["path"]``).
- Log levels emitted: INFO on 0 files, DEBUG on 1 file, INFO on N files,
  WARNING on exception (simple_tools.py:5797-5817).
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from openzim_mcp.simple_tools import SimpleToolsHandler

# Will be filled in once Task A4 lands the extraction. Until then,
# the parity assertion fails at the import-presence check (RED).
try:
    from openzim_mcp.topic_preprocessing import (  # type: ignore[import-not-found]
        auto_select_zim_file,
    )
except ImportError:
    auto_select_zim_file = None  # type: ignore[assignment]


_LOG_NAME = "openzim_mcp.simple_tools"


@pytest.fixture
def mock_handler() -> SimpleToolsHandler:
    """Build a ``SimpleToolsHandler`` against a ``MagicMock`` ``zim_operations``.

    The mock surface mirrors ``make_disambig_handler`` from
    ``tests/_promote_fixtures.py``: a single MagicMock standing in for a full
    ``ZimOperations`` instance. Each parametrized scenario stubs
    ``list_zim_files_data`` differently.
    """
    return SimpleToolsHandler(MagicMock())


@pytest.mark.parametrize(
    "scenario", ["zero_files", "one_file", "n_files", "raises"]
)
def test_auto_select_parity(
    scenario: str,
    mock_handler: SimpleToolsHandler,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Old method and new module-level function return identical values AND
    emit identical log records across every archive-count scenario."""
    assert auto_select_zim_file is not None, (
        "topic_preprocessing.auto_select_zim_file missing — "
        "Task A4 (extraction) has not landed yet. RED phase expected."
    )

    # Stub ``zim_operations.list_zim_files_data`` per scenario. ``path`` is
    # the only key ``_auto_select_zim_file`` reads (simple_tools.py:5802).
    if scenario == "zero_files":
        monkeypatch.setattr(
            mock_handler.zim_operations, "list_zim_files_data", lambda: []
        )
    elif scenario == "one_file":
        monkeypatch.setattr(
            mock_handler.zim_operations,
            "list_zim_files_data",
            lambda: [{"path": "/a/b.zim"}],
        )
    elif scenario == "n_files":
        monkeypatch.setattr(
            mock_handler.zim_operations,
            "list_zim_files_data",
            lambda: [{"path": "/a/b.zim"}, {"path": "/c/d.zim"}],
        )
    else:  # raises
        def boom() -> Any:
            raise RuntimeError("simulated")

        monkeypatch.setattr(
            mock_handler.zim_operations, "list_zim_files_data", boom
        )

    # Capture old-method return + logs.
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=_LOG_NAME):
        old_result = mock_handler._auto_select_zim_file()
    old_records = [(r.levelname, r.message) for r in caplog.records]

    # Capture new-function return + logs. Pass ``zim_operations`` positionally
    # — the extracted module-level signature is expected to take it as its
    # first/only argument per the Task A4 plan.
    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger=_LOG_NAME):
        new_result = auto_select_zim_file(mock_handler.zim_operations)
    new_records = [(r.levelname, r.message) for r in caplog.records]

    assert old_result == new_result, (
        f"divergence on {scenario}: old={old_result!r} new={new_result!r}"
    )
    assert old_records == new_records, (
        f"log divergence on {scenario}: "
        f"old={old_records!r} new={new_records!r}"
    )
