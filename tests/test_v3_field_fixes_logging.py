"""Log-record contract for the advanced tool seam.

Sibling of ``test_v3_field_fixes_errors.py``. That module pinned the SHAPE of
a log record (one physical line, R2-3); this one pins its LEVEL and its SIZE.

A follow-up from PR #374, proved against ``a59eb03``:

* every caller mistake on the whole tool surface — a mistyped ``entry_path``,
  a path outside ``allowed_directories``, a rejected argument, a rate-limit
  denial — was logged at ERROR, because ``tools/_common.tool_error_response``
  called ``.error(...)`` unconditionally. An ERROR channel that fires on user
  typos trains an operator to ignore it, which is how a real archive
  corruption gets missed.
"""

import contextlib
import logging
from pathlib import Path
from typing import Dict, Optional

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import (
    OpenZimMcpArchiveError,
    OpenZimMcpEntryNotFoundError,
)
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.tools._common import tool_error_response


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
