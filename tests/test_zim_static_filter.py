"""Deferred defect: browse/walk must filter non-article assets out of C.

New-scheme ZIMIT/warc2zim archives store ``_zim_static/`` assets (wombat.js +
the MathJax font set) — and, more generally, images / css / fonts / media —
under the C namespace at low entry-ids, so they dominated page 1 of both
``browse_namespace`` and ``walk_namespace``. Both surfaces now skip non-article
assets via ``_is_non_article_target`` (``.html`` / ``.htm`` are kept as
articles). Walk already scan-filled with a scan-position cursor, so it only
needed the predicate. Browse additionally had to switch from a fixed entry-id
slice to a scan-fill loop, so a filtered page still returns ``limit`` real rows
and its resume cursor encodes the next unscanned entry-id (a scan position)
rather than ``offset + returned_count`` — which used to drift once filtering
made matched-rows < ids-scanned.
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


def _mock_archive(
    entries: list[str] = _ENTRIES, mimetypes: dict[int, str] | None = None
) -> MagicMock:
    archive = MagicMock()
    archive.has_new_namespace_scheme = True
    archive.entry_count = len(entries)
    mt = mimetypes or {}

    def _by_id(i: int) -> MagicMock:
        entry = MagicMock()
        entry.path = entries[i]
        entry.title = entries[i]
        entry.is_redirect = False
        item = MagicMock()
        # Default text/html so the existing path/extension-driven asset tests
        # are unaffected; per-row overrides drive the content-type-aware path.
        item.mimetype = mt.get(i, "text/html")
        entry.get_item.return_value = item
        return entry

    archive._get_entry_by_id.side_effect = _by_id
    return archive


def _ops(
    tmp_path,
    monkeypatch,
    entries: list[str] = _ENTRIES,
    mimetypes: dict[int, str] | None = None,
) -> ZimOperations:
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
    archive = _mock_archive(entries, mimetypes)
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


def test_browse_hides_all_non_article_assets(tmp_path, monkeypatch) -> None:
    """Broad scope: EVERY non-article asset (js/png/pdf/font/css/media) is
    dropped from C browse, not only ``_zim_static/``. Article-like entries —
    including ``.html`` / ``.htm``, which the predicate treats as articles —
    survive.
    """
    entries = [
        "_zim_static/wombat.js",
        "favicon.png",
        "Apple",
        "handouts/diabetes.pdf",
        "About.html",
    ]
    ops = _ops(tmp_path, monkeypatch, entries=entries)
    resp = ops.browse_namespace_data(str(tmp_path / "x.zim"), "C", limit=10)
    paths = [r["path"] for r in resp["results"]]
    assert paths == ["Apple", "About.html"]
    assert not any(p.endswith((".js", ".png", ".pdf")) for p in paths)


def test_browse_signals_assets_filtered(tmp_path, monkeypatch) -> None:
    """page_info.assets_filtered flags pages where non-article assets were
    skipped, so a consumer understands returned_count < limit/total (it's
    filtering, not truncation). An all-article archive omits the flag."""
    ops = _ops(tmp_path, monkeypatch)  # _ENTRIES interleaves assets
    resp = ops.browse_namespace_data(str(tmp_path / "x.zim"), "C", limit=2)
    assert resp["page_info"].get("assets_filtered") is True

    ops2 = _ops(tmp_path, monkeypatch, entries=["Apple", "Banana", "Cherry"])
    resp2 = ops2.browse_namespace_data(str(tmp_path / "x.zim"), "C", limit=2)
    assert resp2["page_info"].get("assets_filtered") is None


def test_browse_scan_fills_past_long_asset_run(tmp_path, monkeypatch) -> None:
    """A long run of leading assets is scanned through to fill the page with
    real articles — no short page, no premature done."""
    entries = [f"_zim_static/font{i}.woff2" for i in range(50)] + ["Apple", "Banana"]
    ops = _ops(tmp_path, monkeypatch, entries=entries)
    resp = ops.browse_namespace_data(str(tmp_path / "x.zim"), "C", limit=2)
    paths = [r["path"] for r in resp["results"]]
    assert paths == ["Apple", "Banana"]
    assert resp["done"] is True
    assert resp["page_info"].get("assets_filtered") is True


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
    # The resume cursor's offset is a CONTENT-ROW offset: page 1 returned 2
    # real rows (Apple, Banana), so the next row offset is 2.
    state = Cursor.decode(page1["next_cursor"], expected_tool="browse_namespace")["s"]
    assert state["o"] == 2
    page2 = ops.browse_namespace_data(
        str(tmp_path / "x.zim"), "C", limit=2, offset=state["o"]
    )
    paths2 = [r["path"] for r in page2["results"]]
    # Continues exactly past the boundary — no duplicates, no skipped articles.
    assert paths2 == ["Cherry", "Date"]
    assert page2["done"] is True


# --------------------------------------------------------------------------
# BUG #5 — content-type-aware asset filtering
# --------------------------------------------------------------------------


def test_is_non_article_target_content_type_aware() -> None:
    """The predicate flags asset mimetypes regardless of path extension, keeps
    HTML, and stays backward-compatible when content_type is omitted."""
    pred = ZimOperations._is_non_article_target
    assert pred("fonts.googleapis.com/css2?family=Roboto", "text/css") is True
    assert pred("x", "image/png") is True
    assert pred("x", "font/woff2") is True
    assert pred("lib?v=1", "application/javascript") is True
    assert pred("article/?x=1", "text/html") is False
    assert pred("page", "application/xhtml+xml") is False
    # Back-compat: no mimetype -> extension-only behaviour unchanged.
    assert pred("x.png") is True
    assert pred("foo.html#sec") is False


def test_browse_hides_query_string_css_assets(tmp_path, monkeypatch) -> None:
    """BUG #5: rows whose libzim mimetype is an asset family (text/css, …) are
    filtered even when the path lacks an asset extension — catching the
    query-string / extensionless asset URLs the path heuristic missed."""
    entries = [
        "fonts.googleapis.com/css2?family=Roboto",
        "magazine.example.org/?css=custom",
        "Apple",
        "About.html",
    ]
    mimetypes = {0: "text/css", 1: "text/css", 2: "text/html", 3: "text/html"}
    ops = _ops(tmp_path, monkeypatch, entries=entries, mimetypes=mimetypes)
    resp = ops.browse_namespace_data(str(tmp_path / "x.zim"), "C", limit=10)
    paths = [r["path"] for r in resp["results"]]
    assert paths == ["Apple", "About.html"]
    assert resp["page_info"].get("assets_filtered") is True


def test_walk_hides_query_string_css_assets(tmp_path, monkeypatch) -> None:
    """BUG #5: walk applies the same content-type-aware asset filter."""
    entries = [
        "fonts.googleapis.com/css2?family=Roboto",
        "Apple",
        "lib/app?v=1",
        "Banana",
    ]
    mimetypes = {
        0: "text/css",
        1: "text/html",
        2: "application/javascript",
        3: "text/html",
    }
    ops = _ops(tmp_path, monkeypatch, entries=entries, mimetypes=mimetypes)
    resp = ops.walk_namespace_data(str(tmp_path / "x.zim"), "C", limit=10)
    paths = [r["path"] for r in resp["results"]]
    assert paths == ["Apple", "Banana"]


def test_browse_include_assets_surfaces_assets(tmp_path, monkeypatch) -> None:
    """BUG #8: include_assets=True surfaces asset rows so binary entries are
    discoverable (then fetchable via zim_get(binary=True))."""
    entries = ["_zim_static/wombat.js", "img/plato.jpg", "Apple"]
    mimetypes = {0: "application/javascript", 1: "image/jpeg", 2: "text/html"}
    ops = _ops(tmp_path, monkeypatch, entries=entries, mimetypes=mimetypes)
    resp = ops.browse_namespace_data(
        str(tmp_path / "x.zim"), "C", limit=10, include_assets=True
    )
    paths = [r["path"] for r in resp["results"]]
    assert paths == ["_zim_static/wombat.js", "img/plato.jpg", "Apple"]
    # Nothing was skipped, so the assets_filtered flag is absent.
    assert resp["page_info"].get("assets_filtered") is None
