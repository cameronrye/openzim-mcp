"""Tests for native libzim reader features surfaced by the MCP server.

Covers capabilities that python-libzim exposes but the server did not
previously use:

* ``M/Counter`` parsing into a ``{mimetype: count}`` breakdown.
* Archive identity (``uuid`` / ``is_multipart``) + index-capability
  flags (``has_fulltext_index`` / ``has_title_index``) on the metadata
  surface.
* Per-archive validation (``Archive.check()`` + ``checksum`` /
  ``has_checksum``) exposed through ``zim_health(zim_file_path=...)``.
* Robust missing-fulltext-index detection in search via the explicit
  ``has_fulltext_index`` precheck (replacing fragile exception-string
  parsing).
* Native exact-title lookup (``Archive.get_entry_by_title``) wired into
  the title fast path.
* Optional libzim cluster/dirent cache tuning driven from config.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from libzim.writer import Creator

from openzim_mcp.async_operations import AsyncZimOperations
from openzim_mcp.config import CacheConfig
from openzim_mcp.zim_operations import ZimOperations, zim_archive
from tests.conftest_v2_fixtures import _HtmlItem, make_zim_ops

# ---------------------------------------------------------------------------
# Local fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def noindex_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A ZIM built WITHOUT a full-text index (config_indexing(False))."""
    out = tmp_path_factory.mktemp("noidx") / "noindex.zim"
    with Creator(out).config_indexing(False, "eng") as creator:
        creator.add_item(
            _HtmlItem(
                "A/Alpha",
                "Alpha",
                "<html><body><h1>Alpha</h1><p>hello world content</p></body></html>",
            )
        )
        creator.set_mainpath("A/Alpha")
    return out


@pytest.fixture(scope="module")
def title_mismatch_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A ZIM where an entry's title does NOT map to its path by case/space.

    Path ``A/CC`` carries title ``Climate Change`` — the case-variant
    path probe can never reach it, but the native title index can.
    """
    out = tmp_path_factory.mktemp("titlemm") / "titles.zim"
    with Creator(out).config_indexing(True, "eng") as creator:
        creator.add_item(
            _HtmlItem(
                "A/CC",
                "Climate Change",
                "<html><body><h1>Climate Change</h1><p>about climate</p></body></html>",
            )
        )
        creator.add_item(
            _HtmlItem(
                "A/Other",
                "Other",
                "<html><body><p>other</p></body></html>",
            )
        )
        creator.set_mainpath("A/CC")
    return out


@pytest.fixture
def reset_libzim_caches():
    """Save/restore process-global libzim cache state around a test."""
    import libzim

    import openzim_mcp.zim.archive as arch_mod

    orig_cluster = libzim.get_cluster_cache_max_size()
    orig_dirent = arch_mod._LIBZIM_DIRENT_CACHE_MAX_COUNT
    try:
        yield
    finally:
        libzim.set_cluster_cache_max_size(orig_cluster)
        arch_mod._LIBZIM_DIRENT_CACHE_MAX_COUNT = orig_dirent


# ---------------------------------------------------------------------------
# 1. Counter parsing (pure function)
# ---------------------------------------------------------------------------


class TestCounterParsing:
    def test_parses_basic_counter_string(self) -> None:
        from openzim_mcp.zim.archive import _parse_counter_metadata

        result = _parse_counter_metadata("text/html=123;image/png=45")
        assert result == {"text/html": 123, "image/png": 45}

    def test_skips_malformed_pairs(self) -> None:
        from openzim_mcp.zim.archive import _parse_counter_metadata

        result = _parse_counter_metadata(
            "text/html=12;garbage;image/png=notanint;application/pdf=7"
        )
        assert result == {"text/html": 12, "application/pdf": 7}

    def test_empty_string_yields_empty_mapping(self) -> None:
        from openzim_mcp.zim.archive import _parse_counter_metadata

        assert _parse_counter_metadata("") == {}

    def test_strips_whitespace_around_pairs(self) -> None:
        from openzim_mcp.zim.archive import _parse_counter_metadata

        result = _parse_counter_metadata(" text/html = 5 ; image/svg+xml = 2 ")
        assert result == {"text/html": 5, "image/svg+xml": 2}


# ---------------------------------------------------------------------------
# 2. Metadata enrichment — identity, index capabilities, counter breakdown
# ---------------------------------------------------------------------------


class TestMetadataEnrichment:
    def test_zim_metadata_data_carries_identity_and_index_flags(
        self, v2_phase_a_zim: Path
    ) -> None:
        ops = make_zim_ops(str(v2_phase_a_zim.parent))
        data = ops.get_zim_metadata_data(str(v2_phase_a_zim))

        assert isinstance(data["uuid"], str) and len(data["uuid"]) > 0
        assert data["is_multipart"] is False
        assert data["has_fulltext_index"] is True
        assert data["has_title_index"] is True

    def test_zim_metadata_data_parses_counter(self, v2_phase_a_zim: Path) -> None:
        ops = make_zim_ops(str(v2_phase_a_zim.parent))
        data = ops.get_zim_metadata_data(str(v2_phase_a_zim))

        breakdown = data["counter_breakdown"]
        assert isinstance(breakdown, dict)
        # The fixture is built from text/html articles; the auto-generated
        # M/Counter therefore reports a positive text/html count.
        assert breakdown.get("text/html", 0) >= 1
        assert all(isinstance(v, int) for v in breakdown.values())

    @pytest.mark.asyncio
    async def test_archive_metadata_tool_shape_includes_new_sections(
        self, v2_phase_a_zim: Path
    ) -> None:
        ops = make_zim_ops(str(v2_phase_a_zim.parent))
        async_ops = AsyncZimOperations(ops)
        resp = await async_ops.get_archive_metadata_data(str(v2_phase_a_zim))

        assert "archive_identity" in resp
        assert isinstance(resp["archive_identity"]["uuid"], str)
        assert resp["archive_identity"]["is_multipart"] is False

        assert "index_capabilities" in resp
        assert resp["index_capabilities"]["has_fulltext_index"] is True
        assert resp["index_capabilities"]["has_title_index"] is True

        assert "counter_breakdown" in resp
        assert resp["counter_breakdown"].get("text/html", 0) >= 1

        # The pre-existing keys must remain intact.
        assert "metadata" in resp
        assert "namespaces" in resp


# ---------------------------------------------------------------------------
# 3. Per-archive validation
# ---------------------------------------------------------------------------


class TestArchiveValidation:
    def test_get_archive_validation_data_shape(self, v2_phase_a_zim: Path) -> None:
        ops = make_zim_ops(str(v2_phase_a_zim.parent))
        data = ops.get_archive_validation_data(str(v2_phase_a_zim))

        assert data["is_valid"] is True
        assert data["has_checksum"] is True
        assert isinstance(data["checksum"], str) and len(data["checksum"]) > 0
        assert data["has_fulltext_index"] is True
        assert data["has_title_index"] is True
        assert isinstance(data["uuid"], str) and len(data["uuid"]) > 0
        assert data["is_multipart"] is False
        assert data["name"].endswith(".zim")

    @pytest.mark.asyncio
    async def test_async_validation_wrapper(self, v2_phase_a_zim: Path) -> None:
        ops = make_zim_ops(str(v2_phase_a_zim.parent))
        async_ops = AsyncZimOperations(ops)
        data = await async_ops.get_archive_validation_data(str(v2_phase_a_zim))
        assert data["is_valid"] is True
        assert data["uuid"]

    def test_validation_cache_invalidates_on_file_replacement(
        self, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """The validation verdict must not be served stale after the ZIM at
        the same path is replaced — the cache key includes a stat token."""
        d = tmp_path_factory.mktemp("validate-invalidation")
        zp = d / "archive.zim"

        def _build(article_count: int) -> None:
            with Creator(zp).config_indexing(True, "eng") as creator:
                for i in range(article_count):
                    creator.add_item(
                        _HtmlItem(
                            f"A/Art{i}",
                            f"Art{i}",
                            f"<html><body><h1>Art{i}</h1><p>body {i}</p></body></html>",
                        )
                    )
                creator.set_mainpath("A/Art0")

        ops = make_zim_ops(str(d))
        _build(1)
        first = ops.get_archive_validation_data(str(zp))
        # Replace the file in place with materially different content (more
        # articles -> different size -> different uuid).
        _build(5)
        second = ops.get_archive_validation_data(str(zp))
        assert second["uuid"] != first["uuid"], (
            "validation result was served stale after the ZIM was replaced; "
            "the cache key must include a file-identity (stat) token"
        )

    @pytest.mark.asyncio
    async def test_zim_health_tool_routes_on_zim_file_path(
        self, v2_phase_a_zim: Path
    ) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from openzim_mcp.tools.zim_health import register as register_zim_health

        # Minimal fake server that captures the registered tool function.
        srv = MagicMock()
        store: dict = {}

        def _tool(*, description: str = ""):
            def decorate(fn):
                store[fn.__name__] = fn
                return fn

            return decorate

        srv.mcp.tool = _tool

        mock_ops = MagicMock()
        mock_ops.get_health_data = AsyncMock(return_value={"health": "ok"})
        mock_ops.get_archive_validation_data = AsyncMock(
            return_value={"is_valid": True}
        )

        import openzim_mcp.async_operations as ao

        orig = ao.AsyncZimOperations
        ao.AsyncZimOperations = lambda _zim_ops: mock_ops  # type: ignore[assignment]
        try:
            register_zim_health(srv)
            fn = store["zim_health"]

            # No path → combined server health.
            await fn()
            mock_ops.get_health_data.assert_awaited_once()
            mock_ops.get_archive_validation_data.assert_not_awaited()

            # With path → per-archive validation.
            result = await fn(zim_file_path="/some/archive.zim")
            mock_ops.get_archive_validation_data.assert_awaited_once_with(
                "/some/archive.zim"
            )
            assert result == {"is_valid": True}
        finally:
            ao.AsyncZimOperations = orig  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 4. Search missing-fulltext-index precheck
# ---------------------------------------------------------------------------


class TestSearchIndexPrecheck:
    def test_search_on_unindexed_archive_returns_no_xapian_reason(
        self, noindex_zim: Path
    ) -> None:
        ops = make_zim_ops(str(noindex_zim.parent))
        resp = ops.search_zim_file_data(str(noindex_zim), "hello")
        assert resp["_meta"].get("reason") == "no_xapian_index"
        assert resp["results"] == []
        assert resp["total"] == 0
        assert resp["done"] is True

    def test_filtered_search_on_unindexed_archive_degrades_gracefully(
        self, noindex_zim: Path
    ) -> None:
        ops = make_zim_ops(str(noindex_zim.parent))
        resp = ops.search_with_filters_data(str(noindex_zim), "hello", namespace="C")
        assert resp["_meta"].get("reason") == "no_xapian_index"
        assert resp["results"] == []

    def test_markdown_filtered_search_degrades_on_unindexed(
        self, noindex_zim: Path
    ) -> None:
        """The legacy markdown filtered-search surface must also degrade
        gracefully (not raise) on a no-fulltext-index archive, matching the
        structured _data variant."""
        ops = make_zim_ops(str(noindex_zim.parent))
        md = ops.search_with_filters(str(noindex_zim), "hello", namespace="C")
        assert isinstance(md, str)
        assert "index" in md.lower()

    def test_indexed_search_still_returns_hits(self, v2_phase_a_zim: Path) -> None:
        ops = make_zim_ops(str(v2_phase_a_zim.parent))
        resp = ops.search_zim_file_data(str(v2_phase_a_zim), "physicist")
        assert resp["_meta"].get("reason") != "no_xapian_index"
        assert resp["total"] >= 1


# ---------------------------------------------------------------------------
# 5. Native exact-title lookup
# ---------------------------------------------------------------------------


class TestNativeTitleLookup:
    def test_fast_path_resolves_via_native_title_index(
        self, title_mismatch_zim: Path
    ) -> None:
        ops = make_zim_ops(str(title_mismatch_zim.parent))
        with zim_archive(title_mismatch_zim) as archive:
            # The case-variant path probe cannot reach path "A/CC" from the
            # title "Climate Change"; the native title index can.
            entry = ops._find_entry_fast_path(archive, "Climate Change")
        assert entry is not None
        assert "CC" in entry.path

    def test_fast_path_missing_title_returns_none(
        self, title_mismatch_zim: Path
    ) -> None:
        ops = make_zim_ops(str(title_mismatch_zim.parent))
        with zim_archive(title_mismatch_zim) as archive:
            entry = ops._find_entry_fast_path(archive, "Totally Absent Title XYZ")
        assert entry is None

    def test_find_entry_by_title_data_resolves_title_only_match(
        self, title_mismatch_zim: Path
    ) -> None:
        ops = make_zim_ops(str(title_mismatch_zim.parent))
        data = ops.find_entry_by_title_data(str(title_mismatch_zim), "Climate Change")
        assert data["results"], "expected at least one result"
        top = data["results"][0]
        assert "CC" in top["path"]
        assert top["score"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 6. Cache tuning config
# ---------------------------------------------------------------------------


class TestCacheTuning:
    def test_cache_config_accepts_libzim_tuning_fields(self) -> None:
        cfg = CacheConfig(
            libzim_cluster_cache_max_size_bytes=8 * 1024 * 1024,
            libzim_dirent_cache_max_count=256,
        )
        assert cfg.libzim_cluster_cache_max_size_bytes == 8 * 1024 * 1024
        assert cfg.libzim_dirent_cache_max_count == 256

    def test_cache_config_defaults_are_none(self) -> None:
        cfg = CacheConfig()
        assert cfg.libzim_cluster_cache_max_size_bytes is None
        assert cfg.libzim_dirent_cache_max_count is None

    def test_cache_config_rejects_out_of_range(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CacheConfig(libzim_dirent_cache_max_count=-1)

    def test_configure_libzim_caches_sets_global_state(
        self, reset_libzim_caches
    ) -> None:
        import libzim

        import openzim_mcp.zim.archive as arch_mod

        arch_mod.configure_libzim_caches(
            cluster_cache_max_size_bytes=8 * 1024 * 1024,
            dirent_cache_max_count=256,
        )
        assert libzim.get_cluster_cache_max_size() == 8 * 1024 * 1024
        assert arch_mod._LIBZIM_DIRENT_CACHE_MAX_COUNT == 256

    def test_configure_does_not_reset_dirent_on_none(self, reset_libzim_caches) -> None:
        """A later call that sets only the cluster knob (dirent=None) must
        NOT clobber a dirent count another caller already set — None means
        'leave as-is', not 'reset to default'."""
        import openzim_mcp.zim.archive as arch_mod

        arch_mod.configure_libzim_caches(dirent_cache_max_count=256)
        assert arch_mod._LIBZIM_DIRENT_CACHE_MAX_COUNT == 256
        arch_mod.configure_libzim_caches(cluster_cache_max_size_bytes=8 * 1024 * 1024)
        assert arch_mod._LIBZIM_DIRENT_CACHE_MAX_COUNT == 256

    def test_zim_archive_applies_dirent_cache_when_configured(
        self, v2_phase_a_zim: Path, reset_libzim_caches
    ) -> None:
        import openzim_mcp.zim.archive as arch_mod

        arch_mod.configure_libzim_caches(
            cluster_cache_max_size_bytes=None,
            dirent_cache_max_count=321,
        )
        with zim_archive(v2_phase_a_zim) as archive:
            assert archive.dirent_cache_max_size == 321

    def test_zim_operations_init_applies_configured_tuning(
        self, v2_phase_a_zim: Path, reset_libzim_caches
    ) -> None:
        import openzim_mcp.zim.archive as arch_mod
        from openzim_mcp.cache import OpenZimMcpCache
        from openzim_mcp.config import (
            ContentConfig,
            LoggingConfig,
            OpenZimMcpConfig,
        )
        from openzim_mcp.content_processor import ContentProcessor
        from openzim_mcp.security import PathValidator

        config = OpenZimMcpConfig(
            allowed_directories=[str(v2_phase_a_zim.parent)],
            tool_mode="advanced",
            cache=CacheConfig(libzim_dirent_cache_max_count=200),
            content=ContentConfig(),
            logging=LoggingConfig(level="WARNING"),
        )
        pv = PathValidator(config.allowed_directories)
        cache = OpenZimMcpCache(config.cache)
        cp = ContentProcessor(snippet_length=config.content.snippet_length)
        ZimOperations(config, pv, cache, cp)
        assert arch_mod._LIBZIM_DIRENT_CACHE_MAX_COUNT == 200
