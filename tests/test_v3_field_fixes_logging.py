"""Log-record contract for the advanced tool seam.

Sibling of ``test_v3_field_fixes_errors.py``. That module pinned the SHAPE of
a log record (one physical line, R2-3); this one pins its LEVEL and its SIZE.

Two follow-ups from PR #374, both proved against ``a59eb03``:

* every caller mistake on the whole tool surface — a mistyped ``entry_path``,
  a path outside ``allowed_directories``, a rejected argument, a rate-limit
  denial — was logged at ERROR, because ``tools/_common.tool_error_response``
  called ``.error(...)`` unconditionally. An ERROR channel that fires on user
  typos trains an operator to ignore it, which is how a real archive
  corruption gets missed.
* PR #374 bounded the CLIENT-facing echo (``error_messages._bound_details``)
  but not the log: a 1,000,000-char ``entry_path`` produced a 2,474-char
  client message and a 1,000,067-char log record.
"""

import contextlib
import logging
from pathlib import Path
from typing import Dict, Optional

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import (
    ArchiveOpenTimeoutError,
    OpenZimMcpArchiveError,
    OpenZimMcpArchiveNameError,
    OpenZimMcpCursorMismatchError,
    OpenZimMcpEntryNotFoundError,
    OpenZimMcpFileNotFoundError,
    OpenZimMcpRateLimitError,
    OpenZimMcpSecurityError,
    OpenZimMcpValidationError,
)
from openzim_mcp.security import _CONTEXT_MAX_LENGTH, sanitize_for_log
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.tools._common import tool_error_response

# A control-character-bearing path, mirroring ``_INJECTED_PATH`` in
# ``test_v3_field_fixes_errors``: the new length bound must not be added in a
# way that bypasses the R2-3 single-line guarantee.
_INJECTED_PATH = "/tmp/foo\n\tbar\r.zim"


@contextlib.contextmanager
def _captured(caplog: pytest.LogCaptureFixture, logger_name: str, level: int):
    """Attach caplog's handler to one named logger for the duration.

    ``OpenZimMcpServer`` construction runs ``logging.basicConfig(force=True)``,
    which drops caplog's root handler, so ``caplog.at_level`` alone captures
    nothing once a real server exists in the process. ``level`` is explicit
    here because this module asserts on records BELOW error level, which an
    ``at_level(ERROR)`` capture silently discards.

    Propagation is suspended for the duration: when the server is built in a
    FIXTURE, ``basicConfig(force=True)`` runs before pytest installs its
    call-phase root handler, so that handler survives and the same record is
    appended to ``caplog.records`` twice — once here and once at the root.
    These tests count records, so one record must mean one record.
    """
    target = logging.getLogger(logger_name)
    propagate = target.propagate
    target.addHandler(caplog.handler)
    target.propagate = False
    try:
        with caplog.at_level(level, logger=logger_name):
            yield
    finally:
        target.propagate = propagate
        target.removeHandler(caplog.handler)


def _records(caplog: pytest.LogCaptureFixture, logger_name: str):
    return [r for r in caplog.records if r.name == logger_name]


@pytest.fixture
def advanced_server(temp_dir: Path) -> OpenZimMcpServer:
    config = OpenZimMcpConfig(allowed_directories=[str(temp_dir)], tool_mode="advanced")
    return OpenZimMcpServer(config)


# --------------------------------------------------------------------------
# Level: a caller mistake is not a server fault
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error",
    [
        OpenZimMcpValidationError("limit must be between 1 and 100"),
        OpenZimMcpCursorMismatchError("cursor was issued for another archive"),
        OpenZimMcpArchiveNameError("did not match any loaded archive"),
        OpenZimMcpSecurityError("Access denied - Path is outside allowed directories"),
        OpenZimMcpFileNotFoundError("File does not exist: /nowhere/x.zim"),
        OpenZimMcpRateLimitError("Rate limit exceeded"),
        OpenZimMcpEntryNotFoundError("Entry not found: 'A/Nope'."),
    ],
    ids=lambda e: type(e).__name__,
)
def test_caller_fault_logs_at_warning_not_error(
    advanced_server: OpenZimMcpServer,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    """The request was wrong and the same request will always be wrong; the
    process is healthy and no operator action exists."""
    with _captured(caplog, "openzim_mcp.tools.zim_get", logging.WARNING):
        tool_error_response(advanced_server, operation="zim_get", error=error)

    (record,) = _records(caplog, "openzim_mcp.tools.zim_get")
    assert record.levelno == logging.WARNING


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("boom"),
        OpenZimMcpArchiveError("libzim could not decode the cluster"),
        ArchiveOpenTimeoutError("timed out opening archive"),
    ],
    ids=lambda e: type(e).__name__,
)
def test_server_fault_still_logs_at_error(
    advanced_server: OpenZimMcpServer,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    """The guard that the demotion did not swallow real faults: without it a
    later widening of the caller-fault tuple silences archive corruption."""
    with _captured(caplog, "openzim_mcp.tools.zim_links", logging.WARNING):
        tool_error_response(advanced_server, operation="zim_links", error=error)

    (record,) = _records(caplog, "openzim_mcp.tools.zim_links")
    assert record.levelno == logging.ERROR


def test_entry_not_found_is_a_subclass_of_archive_error() -> None:
    """The backward-compatibility contract: every existing
    ``except OpenZimMcpArchiveError`` keeps catching a not-found unchanged, so
    introducing the type is a pure classification change."""
    assert issubclass(OpenZimMcpEntryNotFoundError, OpenZimMcpArchiveError)


def test_entry_not_found_still_renders_the_resource_not_found_template(
    advanced_server: OpenZimMcpServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Splitting the type must not change what the CLIENT reads.

    ``get_error_config``'s type mapping is by EXACT type, so a new subclass
    reaches the not-found template only via the prose check — which is the
    same string-matching this change exists to stop relying on. The probe
    message therefore deliberately omits the "entry not found" wording: the
    TYPE alone must select the template, or a rephrase at any raise site
    would start rendering "verify the ZIM file is not corrupted" for a
    missing page.
    """
    with _captured(caplog, "openzim_mcp.tools.zim_get", logging.WARNING):
        payload = tool_error_response(
            advanced_server,
            operation="zim_get",
            error=OpenZimMcpEntryNotFoundError("No such article: 'A/Nope'."),
        )

    assert "Resource Not Found" in payload["message"], payload["message"]


def test_structure_not_found_helper_raises_the_typed_error() -> None:
    """``structure._entry_not_found_error`` is the shared constructor for the
    section/structure miss; it must mint the typed error, not the parent."""
    from openzim_mcp.zim.structure import _entry_not_found_error

    assert isinstance(_entry_not_found_error("A/Nope"), OpenZimMcpEntryNotFoundError)


def test_missing_entry_path_raises_the_typed_error(
    basic_test_zim_files: Dict[str, Optional[Path]], temp_dir: Path
) -> None:
    """End to end through the data layer: the single most common user mistake
    on this server — a wrong entry path — must arrive typed."""
    zim_path = basic_test_zim_files["withns"]
    if zim_path is None:
        pytest.skip("ZIM test corpus not available")

    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.content_processor import ContentProcessor
    from openzim_mcp.security import PathValidator
    from openzim_mcp.zim_operations import ZimOperations

    config = OpenZimMcpConfig(allowed_directories=[str(zim_path.parent)])
    ops = ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(snippet_length=100),
    )

    with pytest.raises(OpenZimMcpEntryNotFoundError):
        ops.get_zim_entry(str(zim_path), "A/NoSuchEntryXyz")


# --------------------------------------------------------------------------
# Size: the log was the last unbounded amplifier
# --------------------------------------------------------------------------


def test_sanitize_for_log_bounds_oversized_text() -> None:
    out = sanitize_for_log("z" * 1_000_000)

    assert len(out) < 1200, len(out)
    assert out.endswith("chars elided]"), out[-40:]


def test_sanitize_for_log_leaves_a_legal_max_length_path_intact() -> None:
    """The cap sits above ``INPUT_LIMITS.FILE_PATH`` (1000), the largest
    documented argument, so a LEGAL value is never trimmed. This is the pin
    that stops someone "tidying" the cap below it."""
    legal = "/" + "p" * 999

    assert sanitize_for_log(legal) == legal
    assert len(legal) <= _CONTEXT_MAX_LENGTH


def test_sanitize_for_log_still_collapses_control_chars() -> None:
    """The bound must not be added in a way that bypasses R2-3."""
    out = sanitize_for_log(f"Path contains suspicious pattern: {_INJECTED_PATH}")

    assert "\n" not in out
    assert "\t" not in out
    assert "\r" not in out


def test_tool_error_log_record_is_bounded_for_a_1mb_entry_path(
    advanced_server: OpenZimMcpServer, caplog: pytest.LogCaptureFixture
) -> None:
    """THE regression test: at ``a59eb03`` this record measured 1,000,067
    characters while the client envelope was already capped at ~2,500."""
    huge = "A/" + "z" * 1_000_000
    error = OpenZimMcpEntryNotFoundError(
        f"Entry not found: '{huge}'. Double-check the spelling."
    )

    with _captured(caplog, "openzim_mcp.tools.zim_get", logging.WARNING):
        tool_error_response(
            advanced_server, operation="zim_get", error=error, context=f"Path: {huge}"
        )

    (record,) = _records(caplog, "openzim_mcp.tools.zim_get")
    assert len(record.getMessage()) < 2000, len(record.getMessage())


def test_short_log_message_round_trips_byte_for_byte(
    advanced_server: OpenZimMcpServer, caplog: pytest.LogCaptureFixture
) -> None:
    """The bound is a no-op below the cap — ``test_tools_common`` pins the
    exact ``'Error in <op>: <err>'`` rendering."""
    with _captured(caplog, "openzim_mcp.tools.zim_links", logging.WARNING):
        tool_error_response(
            advanced_server, operation="zim_links", error=RuntimeError("boom")
        )

    (record,) = _records(caplog, "openzim_mcp.tools.zim_links")
    assert record.getMessage() == "Error in zim_links: boom"
