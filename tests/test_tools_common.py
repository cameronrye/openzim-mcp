"""Unit tests for :mod:`openzim_mcp.tools._common`.

Covers ``tool_error_response`` (including the per-tool logger-name guard from
commit 0530bd7) and ``load_description``.
"""

from __future__ import annotations

import logging
import pathlib

import pytest

from openzim_mcp.tools._common import load_description, tool_error_response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeServer:
    """Minimal stand-in for OpenZimMcpServer sufficient to exercise _common."""

    def __init__(self, sentinel: str = "SENTINEL") -> None:
        self._sentinel = sentinel
        self.calls: list[dict] = []

    def _create_enhanced_error_message(
        self, *, operation: str, error: Exception, context: str
    ) -> str:
        self.calls.append(
            {"operation": operation, "error": error, "context": context}
        )
        return self._sentinel


# ---------------------------------------------------------------------------
# tool_error_response tests
# ---------------------------------------------------------------------------


def test_tool_error_response_returns_sentinel() -> None:
    server = _FakeServer(sentinel="MY_SENTINEL")
    err = ValueError("boom")
    result = tool_error_response(
        server, operation="zim_links", error=err, context="ctx"
    )
    assert result == "MY_SENTINEL"


def test_tool_error_response_passes_kwargs() -> None:
    server = _FakeServer()
    err = ValueError("boom")
    tool_error_response(server, operation="zim_links", error=err, context="ctx")

    assert len(server.calls) == 1
    call = server.calls[0]
    assert call["operation"] == "zim_links"
    assert call["error"] is err
    assert call["context"] == "ctx"


def test_tool_error_response_context_defaults_to_empty_string() -> None:
    """context=None should coerce to '' before forwarding."""
    server = _FakeServer()
    tool_error_response(server, operation="zim_query", error=RuntimeError("x"))

    assert server.calls[0]["context"] == ""


def test_tool_error_response_logs_under_per_tool_logger(caplog: pytest.LogCaptureFixture) -> None:
    """KEY REGRESSION GUARD (commit 0530bd7): the log record must be emitted under
    ``openzim_mcp.tools.<operation>`` — NOT the flattened ``openzim_mcp.tools``
    parent — so each tool's log records keep their module-level identity."""
    server = _FakeServer()
    err = ValueError("boom")

    with caplog.at_level(logging.ERROR, logger="openzim_mcp.tools.zim_links"):
        tool_error_response(server, operation="zim_links", error=err, context="ctx")

    # At least one record must have the exact per-tool logger name.
    tool_records = [r for r in caplog.records if r.name == "openzim_mcp.tools.zim_links"]
    assert tool_records, (
        "Expected a log record under 'openzim_mcp.tools.zim_links'; "
        f"got names: {[r.name for r in caplog.records]}"
    )

    record = tool_records[0]
    assert record.levelno == logging.ERROR
    # The rendered message must identify the operation and the error.
    assert record.getMessage() == "Error in zim_links: boom"


def test_tool_error_response_log_message_format(caplog: pytest.LogCaptureFixture) -> None:
    """Message format ``'Error in <op>: <err>'`` must hold for other operations too."""
    server = _FakeServer()

    with caplog.at_level(logging.ERROR, logger="openzim_mcp.tools.zim_query"):
        tool_error_response(
            server, operation="zim_query", error=RuntimeError("oops"), context=""
        )

    tool_records = [r for r in caplog.records if r.name == "openzim_mcp.tools.zim_query"]
    assert tool_records
    assert tool_records[0].getMessage() == "Error in zim_query: oops"


# ---------------------------------------------------------------------------
# load_description tests
# ---------------------------------------------------------------------------


def test_load_description_returns_file_contents() -> None:
    """load_description('zim_links') must return the same bytes as reading the
    .md file directly — no truncation, no transformation."""
    direct = (
        pathlib.Path(__file__).parent.parent
        / "openzim_mcp"
        / "tools"
        / "zim_links_description.md"
    ).read_text(encoding="utf-8")

    via_helper = load_description("zim_links")

    assert via_helper == direct


def test_load_description_missing_name_raises() -> None:
    """A nonexistent description name must raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_description("nonexistent_tool_xyz")
