"""Real-world-test regressions for ``get_search_suggestions_data``.

Covers two findings:

* Single-character prefixes silently returned zero suggestions because of a
  ``len(prefix) < 2`` floor, even though thousands of titles match.
* ``total``/``done`` always claimed the result set was complete
  (``done=True``) even when the page was filled to ``limit`` and more
  matches almost certainly existed — falsely signalling completeness.
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
from openzim_mcp.zim_operations import ZimOperations


@pytest.fixture
def ops_for_climate(
    real_content_zim_files: Dict[str, Optional[Path]],
) -> ZimOperations:
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("climate-change ZIM fixture not available")
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(zim.parent.parent)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=1000, snippet_length=100),
        logging=LoggingConfig(level="ERROR"),
    )
    return ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=100),
    )


@pytest.fixture
def climate_zim_path(real_content_zim_files: Dict[str, Optional[Path]]) -> Path:
    p = real_content_zim_files.get("wikipedia_climate")
    if p is None:
        pytest.skip("climate-change ZIM fixture not available")
    return p


def test_single_char_prefix_returns_suggestions(
    ops_for_climate: ZimOperations, climate_zim_path: Path
):
    """A single-character prefix must not be silently floored to zero."""
    out = ops_for_climate.get_search_suggestions_data(
        str(climate_zim_path), "c", limit=10
    )
    assert out["results"], (
        "single-char prefix 'c' returned no suggestions; "
        "the <2-char floor should be lifted"
    )
    assert out["total"] >= 1


def test_empty_prefix_still_returns_empty(
    ops_for_climate: ZimOperations, climate_zim_path: Path
):
    """Empty / whitespace prefixes remain an empty (but valid) result."""
    out = ops_for_climate.get_search_suggestions_data(
        str(climate_zim_path), "   ", limit=10
    )
    assert out["results"] == []
    assert out["total"] == 0
    assert out["done"] is True


def test_full_page_does_not_claim_completeness(
    ops_for_climate: ZimOperations, climate_zim_path: Path
):
    """When suggestions fill the page to ``limit`` the result must not claim
    the set is exhausted (``done=True``)."""
    out = ops_for_climate.get_search_suggestions_data(
        str(climate_zim_path), "climate", limit=1
    )
    if out["page_info"]["returned_count"] < 1:
        pytest.skip("fixture produced no 'climate' suggestions")
    assert out["page_info"]["returned_count"] == 1
    assert (
        out["done"] is False
    ), "a full page (returned_count == limit) must not report done=True"
