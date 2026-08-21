"""``zim_browse``'s documented soft reject matches both of its modes.

D05 described the unknown-namespace reject as ``total: 0`` +
``discovery_method: "rejected_unknown_namespace"`` + ``_meta.reason:
"bad_namespace"``. Only the page branch emits the first two: walk's early
reject goes through ``_build_walk_result``, which hard-codes ``total:
None`` and never sets ``discovery_method``. A walk-mode caller branching
on either marker read a rejected namespace as a successful empty page.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

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
from openzim_mcp.tools._common import load_description
from openzim_mcp.zim_operations import ZimOperations


def _errors_section() -> str:
    text = load_description("zim_browse")
    return text[text.index("ERRORS:") :]


def test_description_scopes_total_zero_to_page_mode() -> None:
    errors = _errors_section()
    page_only = errors[errors.index("page-only") :]
    assert "total: 0" in page_only, errors


def test_description_scopes_discovery_method_to_page_mode() -> None:
    errors = _errors_section()
    page_only = errors[errors.index("page-only") :]
    assert "rejected_unknown_namespace" in page_only, errors


def test_description_leaves_the_cross_mode_marker_unqualified() -> None:
    """``_meta.reason`` is the one marker both branches set, so it stays the
    documented way to detect the reject."""
    errors = _errors_section()
    assert "bad_namespace" in errors[: errors.index("page-only")], errors


@pytest.fixture
def browse_ops_and_path(basic_test_zim_files: Dict[str, Optional[Path]]):
    zim = basic_test_zim_files.get("withns")
    if zim is None:
        pytest.skip("withns small.zim fixture not available")
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


def test_walk_reject_really_omits_discovery_method(browse_ops_and_path) -> None:
    """Pins the asymmetry the description now admits, so a later change to
    either side has to move both."""
    ops, zim = browse_ops_and_path
    assert "discovery_method" not in ops.walk_namespace_data(zim, "Z", limit=5)


def test_walk_reject_really_reports_a_null_total(browse_ops_and_path) -> None:
    ops, zim = browse_ops_and_path
    assert ops.walk_namespace_data(zim, "Z", limit=5)["total"] is None


def test_page_reject_really_reports_the_page_only_markers(browse_ops_and_path) -> None:
    ops, zim = browse_ops_and_path
    page = ops.browse_namespace_data(zim, "Z", limit=5, offset=0)
    assert page["total"] == 0
    assert page["discovery_method"] == "rejected_unknown_namespace"
