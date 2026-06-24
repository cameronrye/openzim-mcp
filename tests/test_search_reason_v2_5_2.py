"""BUG #4: zim_search empty-result reason classification.

A content_type filter that matches nothing must report
``no_content_type_match`` (not ``bad_namespace``); an unknown namespace
still reports ``bad_namespace``. Uses the generated v2 Phase A fixture
(real Xapian index) so ``unfiltered_total > 0`` for a known term.
"""

from __future__ import annotations

from pathlib import Path

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


def _ops(v2_phase_a_zim: Path) -> ZimOperations:
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(v2_phase_a_zim.parent)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=10000, snippet_length=200),
        logging=LoggingConfig(level="ERROR"),
    )
    return ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=200),
    )


def test_content_type_filter_miss_reports_no_content_type_match(v2_phase_a_zim):
    """A content_type that no fulltext-indexed entry matches reports
    ``no_content_type_match`` even though NO namespace filter was supplied."""
    ops = _ops(v2_phase_a_zim)
    zim = str(v2_phase_a_zim)
    data = ops.search_with_filters_data(
        zim, "Einstein", content_type="image/jpeg", limit=5
    )
    assert data["total"] == 0
    assert data["_meta"]["reason"] == "no_content_type_match"


def test_unknown_namespace_still_reports_bad_namespace(v2_phase_a_zim):
    """An invalid namespace letter still reports ``bad_namespace``."""
    ops = _ops(v2_phase_a_zim)
    zim = str(v2_phase_a_zim)
    data = ops.search_with_filters_data(zim, "Einstein", namespace="Z", limit=5)
    assert data["total"] == 0
    assert data["_meta"]["reason"] == "bad_namespace"
