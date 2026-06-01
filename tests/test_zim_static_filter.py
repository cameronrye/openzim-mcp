"""Deferred defect: browse/walk must filter ZIMIT ``_zim_static`` infra assets.

New-scheme ZIMIT/warc2zim archives store ``_zim_static/`` assets (wombat.js +
the MathJax font set) under the C namespace at low entry-ids, so they
dominated page 1 of both ``browse_namespace`` and ``walk_namespace``. Both
surfaces now skip ``_zim_static/`` infra paths via ``_is_zimit_infra_path``
(a NARROW prefix match — legit C entries with asset extensions like
``favicon.png`` are kept). Walk already scan-filled with a scan-position
cursor, so it only needed the
predicate. Browse additionally had to switch from a fixed entry-id slice to a
scan-fill loop, so a filtered page still returns ``limit`` real rows and its
resume cursor encodes the next unscanned entry-id (a scan position) rather
than ``offset + returned_count`` — which used to drift once filtering made
matched-rows < ids-scanned.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.pagination import Cursor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations

# Interleave _zim_static assets with real C articles so scan-fill must skip
# past assets to fill a page. ids: 0 asset, 1 asset, 2 real, 3 asset, 4 real,
# 5 real, 6 asset, 7 real -> 4 real articles among 8 entries.
_ENTRIES = [
    "_zim_static/wombat.js",
    "_zim_static/mathjax/output/chtml/fonts/MathJax.woff2",
    "Apple",
    "_zim_static/mathjax/output/chtml/fonts/MathJax2.woff2",
    "Banana",
    "Cherry",
    "_zim_static/wombatSetup.js",
    "Date",
]
_REAL = ["Apple", "Banana", "Cherry", "Date"]


def _ctx(value):
    class _C:
        def __enter__(self):
            return value

        def __exit__(self, *a):
            return False

    return _C()


def _mock_archive(entries: list[str] = _ENTRIES) -> MagicMock:
    archive = MagicMock()
    archive.has_new_namespace_scheme = True
    archive.entry_count = len(entries)

    def _by_id(i: int) -> MagicMock:
        entry = MagicMock()
        entry.path = entries[i]
        entry.title = entries[i]
        return entry

    archive._get_entry_by_id.side_effect = _by_id
    return archive


def _ops(tmp_path, monkeypatch, entries: list[str] = _ENTRIES) -> ZimOperations:
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
    )
    ops = ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(),
    )
    archive = _mock_archive(entries)
    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive", lambda *a, **kw: _ctx(archive)
    )
    monkeypatch.setattr(
        "openzim_mcp.pagination.archive_identity", lambda *a, **kw: "test-id"
    )
    ops.path_validator = MagicMock()
    ops.path_validator.validate_path.return_value = str(tmp_path / "x.zim")
    ops.path_validator.validate_zim_file.return_value = str(tmp_path / "x.zim")
    # Isolate the pagination/filter logic from per-row materialisation.
    monkeypatch.setattr(
        ops,
        "_materialise_browse_entry",
        lambda archive, path, has_new_scheme: {"path": path, "title": path},
    )
    return ops


# --------------------------------------------------------------------------
# walk_namespace
# --------------------------------------------------------------------------


def test_walk_namespace_skips_zim_static_assets(tmp_path, monkeypatch) -> None:
    ops = _ops(tmp_path, monkeypatch)
    resp = ops.walk_namespace_data(str(tmp_path / "x.zim"), "C", limit=10)
    paths = [r["path"] for r in resp["results"]]
    assert paths == _REAL
    assert not any("_zim_static" in p for p in paths)


def test_walk_scan_fills_full_page_past_assets(tmp_path, monkeypatch) -> None:
    ops = _ops(tmp_path, monkeypatch)
    # limit=3 must yield 3 REAL articles even with assets interspersed.
    resp = ops.walk_namespace_data(str(tmp_path / "x.zim"), "C", limit=3)
    paths = [r["path"] for r in resp["results"]]
    assert paths == ["Apple", "Banana", "Cherry"]


# --------------------------------------------------------------------------
# browse_namespace
# --------------------------------------------------------------------------


def test_browse_namespace_skips_zim_static_assets(tmp_path, monkeypatch) -> None:
    ops = _ops(tmp_path, monkeypatch)
    resp = ops.browse_namespace_data(str(tmp_path / "x.zim"), "C", limit=10)
    paths = [r["path"] for r in resp["results"]]
    assert paths == _REAL
    assert resp["done"] is True
    # Narrow scope keeps the authoritative total (no lower-bound relabel).
    assert resp["page_info"].get("total_is_lower_bound") is None


def test_browse_keeps_legit_asset_extension_entries(tmp_path, monkeypatch) -> None:
    """Only ``_zim_static/`` infra is dropped — a legit C entry with an asset
    extension (favicon.png, a .pdf handout) stays browsable. This would FAIL
    under the broad extension-based ``_is_non_article_target`` predicate.
    """
    entries = [
        "_zim_static/wombat.js",
        "favicon.png",
        "Apple",
        "handouts/diabetes.pdf",
    ]
    ops = _ops(tmp_path, monkeypatch, entries=entries)
    resp = ops.browse_namespace_data(str(tmp_path / "x.zim"), "C", limit=10)
    paths = [r["path"] for r in resp["results"]]
    assert paths == ["favicon.png", "Apple", "handouts/diabetes.pdf"]
    assert not any("_zim_static" in p for p in paths)


def test_browse_scan_fills_full_page(tmp_path, monkeypatch) -> None:
    ops = _ops(tmp_path, monkeypatch)
    resp = ops.browse_namespace_data(str(tmp_path / "x.zim"), "C", limit=2)
    paths = [r["path"] for r in resp["results"]]
    assert paths == ["Apple", "Banana"]  # a full page of REAL rows, not assets
    assert resp["done"] is False
    assert resp["next_cursor"] is not None


def test_browse_resume_cursor_no_drift(tmp_path, monkeypatch) -> None:
    ops = _ops(tmp_path, monkeypatch)
    page1 = ops.browse_namespace_data(str(tmp_path / "x.zim"), "C", limit=2)
    # The resume cursor's offset is an ENTRY-ID scan position, not a row count:
    # page 1 scanned through Banana (id 4), so the next unscanned id is 5.
    state = Cursor.decode(page1["next_cursor"], expected_tool="browse_namespace")["s"]
    assert state["o"] == 5
    page2 = ops.browse_namespace_data(
        str(tmp_path / "x.zim"), "C", limit=2, offset=state["o"]
    )
    paths2 = [r["path"] for r in page2["results"]]
    # Continues exactly past the boundary — no duplicates, no skipped articles.
    assert paths2 == ["Cherry", "Date"]
    assert page2["done"] is True
