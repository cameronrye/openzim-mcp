"""Guards that human-facing docs and tool-description prose match the code.

Tool descriptions are advisory prose a consuming model trusts to chain calls,
and ``docs/roadmap.md`` is the project's stated source of truth for "where are
we." Both have drifted from the code before — the roadmap claimed 19 weighted
intent patterns while ``IntentParser`` had grown to 25; the ``zim_search``
description named a result key (``entry_path``) the wire never emits; the
``zim_links`` description named a response type (``ArticleLinksResponse``) that
does not exist. These tests pin those load-bearing claims to the code so the
drift cannot silently recur.
"""

from __future__ import annotations

import pathlib
import re

import openzim_mcp.tool_schemas as schemas
from openzim_mcp.intent_parser import IntentParser
from openzim_mcp.tool_schemas import SearchHit
from openzim_mcp.tools._common import load_description

_ROADMAP = pathlib.Path(__file__).parent.parent / "docs" / "roadmap.md"


def test_roadmap_weighted_pattern_count_matches_code() -> None:
    """The sub-D-3 'N weighted patterns' figure equals the live table size."""
    roadmap = _ROADMAP.read_text(encoding="utf-8")
    match = re.search(r"(\d+)\s+weighted patterns", roadmap)
    assert match, "roadmap.md should state the weighted-pattern count in sub-D-3"
    assert int(match.group(1)) == len(IntentParser.INTENT_PATTERNS), (
        "docs/roadmap.md weighted-pattern count is stale relative to "
        f"IntentParser.INTENT_PATTERNS (={len(IntentParser.INTENT_PATTERNS)})"
    )


def test_zim_search_description_names_real_result_key() -> None:
    """zim_search RESPONSE prose names the real SearchHit key, not entry_path."""
    desc = load_description("zim_search")
    # Schema is the source of truth: the wire key is `path`, not `entry_path`.
    assert "path" in SearchHit.__annotations__
    assert "entry_path" not in SearchHit.__annotations__
    # The RESPONSE section must describe results as carrying `path`...
    assert "`path`" in desc
    # ...and must NOT claim each result carries `entry_path`.
    assert "`entry_path`, `title`" not in desc


def test_zim_links_description_names_real_response_type() -> None:
    """zim_links RESPONSE prose names LinksResponse, not ArticleLinksResponse."""
    desc = load_description("zim_links")
    assert hasattr(schemas, "LinksResponse")
    assert not hasattr(schemas, "ArticleLinksResponse")
    assert "ArticleLinksResponse" not in desc
