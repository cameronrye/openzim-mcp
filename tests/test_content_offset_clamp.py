"""Real-world-test regression: a ``content_offset`` past the end of the body
was echoed verbatim in a self-contradictory header
(``Content Offset: 999999999 of 146,250 characters``) with ``(No content)``,
instead of a clear "offset is past the end of the body" message.
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

_ENTRY = "A/Climate_change"


@pytest.fixture
def ops_and_path(
    real_content_zim_files: Dict[str, Optional[Path]],
):
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("climate-change ZIM fixture not available")
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(zim.parent.parent)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=100000, snippet_length=100),
        logging=LoggingConfig(level="ERROR"),
    )
    ops = ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=100),
    )
    return ops, str(zim)


def test_offset_past_end_is_not_echoed_as_contradiction(ops_and_path):
    ops, zim = ops_and_path
    out = ops.get_zim_entry(zim, _ENTRY, content_offset=999999999)
    # The self-contradictory "999999999 of <smaller N>" header must be gone.
    assert "999999999 of" not in out
    # And the response must clearly say the offset is past the body end.
    assert "past the end" in out.lower() or "beyond" in out.lower()


def test_in_range_offset_still_shows_normal_header(ops_and_path):
    ops, zim = ops_and_path
    out = ops.get_zim_entry(zim, _ENTRY, content_offset=10)
    assert "Content Offset: 10 of" in out
