"""Real-world-test regression: a single article reported two different body
sizes. The content layer computed ``total_length`` / sliced ``content_offset``
against link-laden markdown (e.g. 146,250 chars), while the caller received
link-stripped text (~83,424 chars) after the compact post-processing strip —
so ``content_offset`` addressed positions that didn't exist in the served
text. The fix strips markdown links IN the content layer (compact mode), so
the reported total, the offset, and the served text all agree.
"""

from __future__ import annotations

import re
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

_ENTRY = "A/Climate_change"
_MD_LINK = re.compile(r"\[[^\]]+\]\([^)]+\)")


@pytest.fixture
def ops_and_path(real_content_zim_files: Dict[str, Optional[Path]]):
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("climate-change ZIM fixture not available")
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(zim.parent.parent)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=1_000_000, snippet_length=100),
        logging=LoggingConfig(level="ERROR"),
    )
    ops = ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=100),
    )
    return ops, str(zim)


def test_compact_content_layer_strips_links(ops_and_path):
    ops, zim = ops_and_path
    out = ops.get_zim_entry(zim, _ENTRY, compact=True)
    # The content the caller receives — and that ``total_length`` /
    # ``content_offset`` are computed against — must already be stripped.
    assert _MD_LINK.search(out) is None, "compact content layer must strip links"


def test_non_compact_keeps_links(ops_and_path):
    ops, zim = ops_and_path
    out = ops.get_zim_entry(zim, _ENTRY, compact=False)
    # Legacy non-compact shape keeps the markdown links.
    assert _MD_LINK.search(out) is not None


def test_compact_structured_content_layer_strips_links(ops_and_path):
    ops, zim = ops_and_path
    payload = ops.get_zim_entry_data(zim, _ENTRY, compact=True)
    assert _MD_LINK.search(payload["content"]) is None
