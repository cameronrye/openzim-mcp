"""Phase C golden-file regression tests for get_section and synthesize.

Anchors the response-contract shape for get_section_data and synthesize_query
so future changes that unintentionally alter the wire format show up as diffs.

Usage
-----
Capture (or refresh) goldens::

    OPENZIM_MCP_CAPTURE_GOLDENS=1 uv run pytest tests/test_golden_v2_phase_c.py -v

Compare against saved goldens (default)::

    uv run pytest tests/test_golden_v2_phase_c.py -v

Notes
-----
* Uses the same ``_capture_or_compare`` / ``_strip_volatile`` pattern as Phase B.
* ``v2_phase_c_zim`` is a purpose-built heading-rich fixture (A/Berlin, A/Munich)
  because Phase A's articles have no h2/h3 headings and therefore no section IDs
  for ``get_section`` to slice on.
* ``synthesize_query`` is called directly (bypassing ``handle_zim_query`` dispatch)
  to keep the golden independent of simple-tools wiring.
* ``score`` values in passages use rank-inverse (1/rank) — fully deterministic for
  a fixed ZIM, so they are kept in the snapshot.
* ``total_chars`` / ``total_words`` in SynthesizeResponse depend on rendered text
  length, which is deterministic for fixed content, and are also retained.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
    SynthesizeConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.synthesize import synthesize_query
from openzim_mcp.zim_operations import ZimOperations, zim_archive

GOLDENS_DIR = Path(__file__).parent / "data" / "goldens" / "v2_phase_c"

# Keys to strip from snapshots — volatile or environment-specific.
# Inherits Phase B's full set; no new volatile keys surfaced in Phase C output.
_VOLATILE_KEYS = frozenset(
    {
        # token/char counts depend on rendered snippet text
        "tokens_est",
        "chars",
        # file-system metadata — environment-specific
        "directory",
        "size_bytes",
        "modified",
        "size",
        # opaque cursor encodes archive identity (tmp path digest)
        "next_cursor",
        # find_entry_by_title_data embeds the absolute zim file path in results
        "zim_file",
    }
)


def _strip_volatile(d: Any) -> Any:
    """Recursively remove volatile keys from a nested dict/list structure."""
    if isinstance(d, dict):
        return {k: _strip_volatile(v) for k, v in d.items() if k not in _VOLATILE_KEYS}
    if isinstance(d, list):
        return [_strip_volatile(x) for x in d]
    return d


def _capture_or_compare(name: str, payload: dict, *, capture_mode: bool) -> None:
    """Write golden snapshot or assert equality against saved snapshot.

    When ``capture_mode=True`` or the file is absent, the payload is
    serialised to JSON and written.  Otherwise the saved golden is loaded and
    ``_strip_volatile(payload)`` must equal ``_strip_volatile(expected)``.

    Args:
        name: Basename (without extension) of the golden file.
        payload: The dict returned by the operation under test.
        capture_mode: When ``True``, always overwrite the file.

    Raises:
        AssertionError: When the stripped payloads differ in compare mode.
    """
    GOLDENS_DIR.mkdir(parents=True, exist_ok=True)
    path = GOLDENS_DIR / f"{name}.json"
    if capture_mode or not path.exists():
        path.write_text(
            json.dumps(
                _strip_volatile(payload), indent=2, ensure_ascii=False, sort_keys=True
            ),
            newline="\n",
        )
        return
    expected = json.loads(path.read_text())
    assert _strip_volatile(payload) == _strip_volatile(expected), (
        f"Golden mismatch for {name}. "
        "Set OPENZIM_MCP_CAPTURE_GOLDENS=1 to refresh after intentional changes."
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def zim_ops_c(v2_phase_c_zim: Path) -> ZimOperations:
    """Construct a ZimOperations instance pointing at the Phase C fixture archive."""
    zim_dir = str(v2_phase_c_zim.parent)
    config = OpenZimMcpConfig(
        allowed_directories=[zim_dir],
        tool_mode="advanced",
        cache=CacheConfig(enabled=True, max_size=20, ttl_seconds=300),
        content=ContentConfig(max_content_length=10000, snippet_length=200),
        logging=LoggingConfig(level="WARNING"),
    )
    path_validator = PathValidator(config.allowed_directories)
    cache = OpenZimMcpCache(config.cache)
    content_processor = ContentProcessor(snippet_length=config.content.snippet_length)
    return ZimOperations(config, path_validator, cache, content_processor)


@pytest.fixture(scope="module")
def zim_path_c(v2_phase_c_zim: Path) -> str:
    """Return the string path to the Phase C fixture ZIM file."""
    return str(v2_phase_c_zim)


@pytest.fixture(scope="session")
def capture_mode() -> bool:
    """Return True when the OPENZIM_MCP_CAPTURE_GOLDENS env var is set to '1'."""
    return os.environ.get("OPENZIM_MCP_CAPTURE_GOLDENS") == "1"


# ---------------------------------------------------------------------------
# get_section golden snapshots
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry_path,section_id,golden_name",
    [
        ("A/Berlin", "geography", "get_section_berlin_geography"),
        ("A/Berlin", "climate", "get_section_berlin_climate"),
        ("A/Munich", "history", "get_section_munich_history"),
    ],
)
def test_golden_get_section(
    zim_ops_c: ZimOperations,
    zim_path_c: str,
    entry_path: str,
    section_id: str,
    golden_name: str,
    capture_mode: bool,
) -> None:
    """get_section_data — snapshot of a named section from the heading-rich fixture."""
    payload = zim_ops_c.get_section_data(zim_path_c, entry_path, section_id=section_id)
    assert (
        "error" not in payload
    ), f"get_section_data returned an error for {entry_path}#{section_id}: {payload}"
    _capture_or_compare(golden_name, dict(payload), capture_mode=capture_mode)


# ---------------------------------------------------------------------------
# synthesize golden snapshots
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,golden_name",
    [
        ("berlin geography", "synthesize_berlin_geography"),
        ("munich history", "synthesize_munich_history"),
        ("capital city", "synthesize_capital_city"),
    ],
)
def test_golden_synthesize(
    zim_ops_c: ZimOperations,
    v2_phase_c_zim: Path,
    query: str,
    golden_name: str,
    capture_mode: bool,
) -> None:
    """synthesize_query — end-to-end snapshot for deterministic queries."""
    with zim_archive(v2_phase_c_zim) as archive:
        response = synthesize_query(
            query,
            archives=[(archive, v2_phase_c_zim)],
            search_handler=zim_ops_c,
            cache=zim_ops_c.cache,
            content_processor=zim_ops_c.content_processor,
            config=SynthesizeConfig(),
        )
    _capture_or_compare(golden_name, dict(response), capture_mode=capture_mode)
