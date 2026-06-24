"""Real-world-test regressions in namespace listing / browsing / walking."""

from __future__ import annotations

from typing import Any, Dict

from openzim_mcp.compact_renderers import render_namespaces


def test_namespace_header_reconciliation_is_arithmetically_clear():
    """The header must not call ``entry_count`` the grand total when the
    per-namespace rows sum to MORE than it. The +N extras must be tied,
    arithmetically, to the W/M entries that entry_count excludes.
    """
    data: Dict[str, Any] = {
        "total_entries": 2_416_931,
        "is_total_authoritative": True,
        "discovery_method": "full_iteration",
        "namespaces": {
            "C": {"total": 2_416_931, "description": "User content"},
            "M": {"total": 11, "description": "Metadata"},
            "W": {"total": 2, "description": "Well-known"},
        },
    }
    out = render_namespaces(data)
    header = out.splitlines()[0]
    # The per-namespace sum (the true inventory) is surfaced...
    assert "per-namespace sum: 2,416,944" in header
    # ...and the +13 is explicitly the W/M entries excluded from entry_count,
    # not a vague trailing "well-knowns/redirects" implying a shortfall.
    assert "+13" in header
    assert "entry_count" in header
    # entry_count must be labelled as a subset, not the grand "archive entries"
    # total (which read as larger-than-the-rows nonsense).
    assert "archive entries" not in header


# ---------------------------------------------------------------------------
# browse-namespace C scan-fill: offset is a content-row offset (not a raw
# entry-id), and unaddressable empty-path entries are skipped.
# ---------------------------------------------------------------------------

from openzim_mcp.zim.namespace import _scan_fill_c_namespace  # noqa: E402


def _asset(path: str, content_type: object = None) -> bool:
    return path.startswith(("_zim_static", "I/", "-/")) or path.endswith(
        (".js", ".png", ".css")
    )


def _tuple_get(paths):
    """Adapt a {id: path} map to the new ``(path, content_type)`` get_path
    contract used by ``_scan_fill_c_namespace`` (mimetype unused here)."""

    def _get(scan_id):
        return paths.get(scan_id), None

    return _get


def test_browse_offset_advances_by_content_rows_not_entry_id():
    # ids 0-3 are assets, id 4 is an unaddressable empty-path phantom,
    # ids 5-14 are real content entries.
    paths = {
        0: "_zim_static/a.js",
        1: "_zim_static/b.js",
        2: "I/x.png",
        3: "-/s.css",
        4: "",
    }
    paths.update({i: f"a/{i}" for i in range(5, 15)})
    get = _tuple_get(paths)

    page0, next0, exhausted0, _ = _scan_fill_c_namespace(15, get, _asset, 2, 0)
    page1, _next1, _ex1, _ = _scan_fill_c_namespace(15, get, _asset, 2, 1)

    assert page0 == ["a/5", "a/6"]
    # offset=1 must advance by exactly one CONTENT row, not collapse to the
    # same first content entry the way a raw entry-id offset did.
    assert page1 == ["a/6", "a/7"]
    assert page0 != page1
    # next-page offset is a row offset (offset + rows returned), so
    # ``offset += limit`` paging works.
    assert next0 == 2
    assert exhausted0 is False


def test_browse_skips_phantom_empty_path_entry():
    paths = {0: "", 1: "a/1", 2: "a/2"}
    page, _next, _ex, _ = _scan_fill_c_namespace(3, _tuple_get(paths), _asset, 10, 0)
    assert "" not in page
    assert page == ["a/1", "a/2"]


def test_browse_scan_exhaustion_flagged():
    paths = {i: f"a/{i}" for i in range(5)}
    page, _next, exhausted, _ = _scan_fill_c_namespace(
        5, _tuple_get(paths), _asset, 2, 4
    )
    assert page == ["a/4"]
    assert exhausted is True


# ---------------------------------------------------------------------------
# walk / browse must agree on whether a namespace letter is valid.
# ---------------------------------------------------------------------------

from pathlib import Path  # noqa: E402
from typing import Optional  # noqa: E402

import pytest  # noqa: E402

from openzim_mcp.cache import OpenZimMcpCache  # noqa: E402
from openzim_mcp.config import (  # noqa: E402
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor  # noqa: E402
from openzim_mcp.security import PathValidator  # noqa: E402
from openzim_mcp.zim_operations import ZimOperations  # noqa: E402


@pytest.fixture
def climate_ops_and_path(real_content_zim_files: Dict[str, Optional[Path]]):
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("climate-change ZIM fixture not available")
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(zim.parent.parent)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=1000, snippet_length=100),
        logging=LoggingConfig(level="ERROR"),
    )
    ops = ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=100),
    )
    return ops, str(zim)


def test_walk_and_browse_agree_on_unknown_namespace(climate_ops_and_path):
    ops, zim = climate_ops_and_path
    walk = ops.walk_namespace_data(zim, "Z")
    browse = ops.browse_namespace_data(zim, "Z")
    # Both surfaces must classify an unknown namespace the same way.
    assert walk["results"] == []
    assert browse["results"] == []
    assert walk["_meta"].get("reason") == "bad_namespace"
    assert browse["_meta"].get("reason") == "bad_namespace"
