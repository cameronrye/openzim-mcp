"""Phase B golden-file regression tests anchoring the v2 response-contract shape.

Captures the structured output of the major ``_data`` methods so future changes
that unintentionally alter the wire format show up as golden diffs.

Usage
-----
Capture (or refresh) goldens::

    OPENZIM_MCP_CAPTURE_GOLDENS=1 uv run pytest tests/test_golden_v2_phase_b.py -v

Compare against saved goldens (default)::

    uv run pytest tests/test_golden_v2_phase_b.py -v

Notes
-----
* ``_strip_volatile`` removes keys whose values change across runs or environments:
  ``tokens_est``, ``chars`` (depend on rendered content length),
  ``path``, ``directory``, ``size_bytes``, ``modified``, ``size``
  (environment-specific file-system metadata), and ``next_cursor``
  (encodes archive identity which can vary between tmp paths).
  Stripping these keeps the diff focused on structural contract shape.
* ``list_zim_files_summary_data`` is intentionally excluded — its output
  contains absolute paths and file-system timestamps that are
  environment-specific; five solid stable snapshots beat eight flaky ones.
"""

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
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations

GOLDENS_DIR = Path(__file__).parent / "data" / "goldens" / "v2_phase_b"

# Keys to strip from snapshots — volatile or environment-specific.
_VOLATILE_KEYS = frozenset(
    {
        # token/char counts depend on rendered snippet text
        "tokens_est",
        "chars",
        # file-system metadata — environment-specific
        "path",
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
    """Recursively remove volatile keys from a nested dict/list structure.

    Keys removed: ``tokens_est``, ``chars`` (content-length-dependent),
    ``path``, ``directory``, ``size_bytes``, ``modified``, ``size``
    (environment-specific fs metadata), and ``next_cursor`` (encodes archive
    identity derived from tmp paths).
    """
    if isinstance(d, dict):
        return {
            k: _strip_volatile(v) for k, v in d.items() if k not in _VOLATILE_KEYS
        }
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
        payload: The dict returned by the ``_data`` method under test.
        capture_mode: When ``True``, always overwrite the file.

    Raises:
        AssertionError: When the stripped payloads differ in compare mode.
    """
    GOLDENS_DIR.mkdir(parents=True, exist_ok=True)
    path = GOLDENS_DIR / f"{name}.json"
    if capture_mode or not path.exists():
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
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
def zim_ops(v2_phase_a_zim: Path) -> ZimOperations:
    """Construct a ZimOperations instance pointing at the fixture archive."""
    zim_dir = str(v2_phase_a_zim.parent)
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


@pytest.fixture
def zim_path(v2_phase_a_zim: Path) -> str:
    """Return the string path to the fixture ZIM file."""
    return str(v2_phase_a_zim)


@pytest.fixture
def capture_mode() -> bool:
    """Return True when the OPENZIM_MCP_CAPTURE_GOLDENS env var is set to '1'."""
    return os.environ.get("OPENZIM_MCP_CAPTURE_GOLDENS") == "1"


# ---------------------------------------------------------------------------
# Snapshot tests
# ---------------------------------------------------------------------------


def test_golden_search_einstein(
    zim_ops: ZimOperations, zim_path: str, capture_mode: bool
) -> None:
    """search_zim_file_data — top-2 results for 'Einstein'."""
    payload = zim_ops.search_zim_file_data(zim_path, query="Einstein", limit=2)
    _capture_or_compare("search_einstein_2", dict(payload), capture_mode=capture_mode)


def test_golden_find_einstein(
    zim_ops: ZimOperations, zim_path: str, capture_mode: bool
) -> None:
    """find_entry_by_title_data — exact title lookup for 'Einstein'."""
    payload = zim_ops.find_entry_by_title_data(zim_path, title="Einstein")
    _capture_or_compare("find_einstein", dict(payload), capture_mode=capture_mode)


def test_golden_browse_a_namespace(
    zim_ops: ZimOperations, zim_path: str, capture_mode: bool
) -> None:
    """browse_namespace_data — first 10 entries in namespace A."""
    payload = zim_ops.browse_namespace_data(
        zim_path, namespace="A", limit=10, offset=0
    )
    _capture_or_compare("browse_A_10", dict(payload), capture_mode=capture_mode)


def test_golden_walk_a_namespace(
    zim_ops: ZimOperations, zim_path: str, capture_mode: bool
) -> None:
    """walk_namespace_data — initial page walk through namespace A."""
    payload = zim_ops.walk_namespace_data(
        zim_path, namespace="A", cursor_state=None, limit=10
    )
    _capture_or_compare("walk_A_10", dict(payload), capture_mode=capture_mode)


def test_golden_links_einstein_internal(
    zim_ops: ZimOperations, zim_path: str, capture_mode: bool
) -> None:
    """extract_article_links_data — internal links from A/Einstein."""
    payload = zim_ops.extract_article_links_data(
        zim_path, entry_path="A/Einstein", kind="internal"
    )
    _capture_or_compare(
        "links_einstein_internal", dict(payload), capture_mode=capture_mode
    )


def test_golden_list_namespaces(
    zim_ops: ZimOperations, zim_path: str, capture_mode: bool
) -> None:
    """list_namespaces_data — namespace summary for the fixture archive."""
    payload = zim_ops.list_namespaces_data(zim_path)
    _capture_or_compare("list_namespaces", dict(payload), capture_mode=capture_mode)


def test_golden_suggest_ein(
    zim_ops: ZimOperations, zim_path: str, capture_mode: bool
) -> None:
    """get_search_suggestions_data — title suggestions for partial query 'Ein'."""
    payload = zim_ops.get_search_suggestions_data(
        zim_path, partial_query="Ein", limit=5
    )
    _capture_or_compare("suggest_ein", dict(payload), capture_mode=capture_mode)
