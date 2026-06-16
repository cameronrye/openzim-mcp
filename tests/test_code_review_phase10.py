"""Regression tests for code-review 2026-06-10 Phase 10 (performance).

H15 (find_entry_by_title_data uncached + per-probe typo sweeps), M32 (preset
re-derived per uncached search). M30/L4 duplicate probes collapse into the
H15 cache. Verifies the caches actually ENGAGE on a real fixture archive.
"""

from pathlib import Path

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
from openzim_mcp.zim.archive import zim_archive
from openzim_mcp.zim_operations import ZimOperations


@pytest.fixture
def ops(v2_phase_a_zim: Path) -> ZimOperations:
    config = OpenZimMcpConfig(
        allowed_directories=[str(v2_phase_a_zim.parent)],
        tool_mode="advanced",
        cache=CacheConfig(enabled=True, max_size=50, ttl_seconds=300),
        content=ContentConfig(max_content_length=10000, snippet_length=200),
        logging=LoggingConfig(level="WARNING"),
    )
    return ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(snippet_length=config.content.snippet_length),
    )


def _cache_keys(ops: ZimOperations, prefix: str) -> list:
    # OpenZimMcpCache stores entries in an internal dict; inspect keys.
    store = getattr(ops.cache, "_cache", None) or getattr(ops.cache, "cache", {})
    return [k for k in store if str(k).startswith(prefix)]


# H15 — find_entry_by_title_data is cached per (path, stat-token, title, limit)
def test_h15_find_entry_by_title_is_cached(ops, v2_phase_a_zim):
    path = str(v2_phase_a_zim)
    first = ops.find_entry_by_title_data(path, "Einstein", cross_file=False, limit=5)
    assert _cache_keys(ops, "find_title:v1:"), "expected a find_title cache entry"
    second = ops.find_entry_by_title_data(path, "Einstein", cross_file=False, limit=5)
    # The cache hit returns an equivalent payload.
    assert second == first


# M32 — preset resolution caches the metadata-entries extraction per archive
def test_m32_preset_entries_cached_on_search(ops, v2_phase_a_zim):
    path = str(v2_phase_a_zim)
    ops.search_zim_file_data(path, "Einstein", limit=2)
    assert _cache_keys(
        ops, "preset_entries:v1:"
    ), "expected a preset_entries cache entry"


# M31 — the query-independent snippet render is cached per (path, entry, token)
def test_m31_snippet_render_cached_on_search(ops, v2_phase_a_zim):
    path = str(v2_phase_a_zim)
    ops.search_zim_file_data(path, "Einstein", limit=2)
    assert _cache_keys(
        ops, "snippet_render:v1:"
    ), "expected a snippet_render cache entry"


# M31 residue — the synthesize hot path (search_top_k / title_match_hit) must
# also engage the snippet_render cache. These hold an OPEN archive, so they
# need ``validated_path`` threaded through to ``_get_entry_snippet`` for the
# cache key to be built. Without the thread-through the cache never engages on
# the synthesize path and the snippet-vs-bundle double render M31 targeted
# persists.
def test_m31_snippet_render_cached_on_search_top_k(ops, v2_phase_a_zim):
    path = str(v2_phase_a_zim)
    with zim_archive(v2_phase_a_zim) as archive:
        hits = ops.search_top_k(archive, "Einstein", k=2, validated_path=path)
    assert hits, "expected search_top_k to return hits for the fixture"
    assert _cache_keys(ops, "snippet_render:v1:"), (
        "expected search_top_k to engage the snippet_render cache when "
        "validated_path is supplied"
    )


def test_m31_snippet_render_cached_on_title_match_hit(ops, v2_phase_a_zim):
    path = str(v2_phase_a_zim)
    with zim_archive(v2_phase_a_zim) as archive:
        hit = ops.title_match_hit(archive, "Einstein", validated_path=path)
    assert hit is not None, "expected title_match_hit to resolve the fixture title"
    assert _cache_keys(ops, "snippet_render:v1:"), (
        "expected title_match_hit to engage the snippet_render cache when "
        "validated_path is supplied"
    )
