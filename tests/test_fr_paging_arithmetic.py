"""Every number in a search footer must live in one coordinate system.

v3.3.1 field report, fid 50 — and the simple-mode bullet "search paging
numbers items and recommends an `offset` that disagree, so the naive next
page repeats results".

The canonical dedup collapses query-string twins, so a page can consume
more of the ranked stream than it renders. `offset` is a position in that
stream; the "Showing 1-10" line counts rendered rows. On the shipped
MedlinePlus archive, `search for asthma` renders 10 rows out of 12
consumed::

    Showing 1-10 of ~704 — pass `offset=12` for the next page

A caller who reads "1-10" and pages by `offset=10` — the obvious
arithmetic, and the only one the sentence supports — gets two rows back
that it has already seen. The recommendation itself is right; nothing in
the sentence says where 12 comes from, so the model has no reason to
prefer it over its own subtraction.

Page 2 then numbers its items 13-22 while the reader has seen exactly ten,
because that numbering is already in stream coordinates. It is the first
page's range line that is in the other system, alone.

fid 67 fixed the *recommendation*; this is the sentence around it.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

pytestmark = pytest.mark.live

_MEDLINEPLUS = "/Users/cameron/Developer/zim/medlineplus.gov_en_all_2025-01.zim"


def _footer(text: str) -> str:
    lines = [ln for ln in text.splitlines() if "Showing" in ln]
    assert lines, text[-400:]
    return lines[-1]


@pytest.fixture
def query_tool() -> Any:
    import os

    from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
    from openzim_mcp.server import OpenZimMcpServer

    if not os.path.exists(_MEDLINEPLUS):
        pytest.skip("MedlinePlus archive not present")
    server = OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[os.path.dirname(_MEDLINEPLUS)],
            tool_mode="simple",
            cache=CacheConfig(enabled=False),
        )
    )
    return server.mcp._tool_manager._tools["zim_query"].fn


@pytest.mark.asyncio
async def test_a_collapsed_page_says_how_far_it_scanned(query_tool):
    """The reported page: 10 rows rendered, 12 consumed, offset=12."""
    text = await query_tool(
        query="search for asthma", zim_file_path=_MEDLINEPLUS, limit=10, offset=0
    )
    footer = _footer(text)

    recommended = re.search(r"`offset=(\d+)`", footer)
    assert recommended, footer
    scanned = int(recommended.group(1))

    # The number the caller is told to use must be derivable from the
    # sentence it appears in, not just asserted at the end of it.
    assert str(scanned) in footer.split("pass")[0], (
        "the footer recommends an offset that nothing before it explains: " + footer
    )


@pytest.mark.asyncio
async def test_the_collapse_itself_is_named(query_tool):
    """A gap between rendered and consumed is a fact about the results, not
    a rounding artefact — a caller reconciling counts across pages needs it
    said rather than inferred."""
    text = await query_tool(
        query="search for asthma", zim_file_path=_MEDLINEPLUS, limit=10, offset=0
    )
    footer = _footer(text)

    assert "duplicate" in footer.lower(), footer


@pytest.mark.asyncio
async def test_an_uncollapsed_page_stays_exactly_as_it_was(query_tool):
    """Control, and the common case: when nothing collapsed there is no
    second coordinate to reconcile, so the sentence must not grow a clause
    explaining a discrepancy that does not exist."""
    text = await query_tool(
        query="search for diabetes", zim_file_path=_MEDLINEPLUS, limit=10, offset=0
    )
    footer = _footer(text)

    assert "duplicate" not in footer.lower(), footer
    assert re.search(r"Showing 1-10 of [~\d]", footer), footer
    assert "`offset=10`" in footer, footer


@pytest.mark.asyncio
async def test_the_recommended_offset_still_returns_no_duplicates(query_tool):
    """The property fid 67 established, re-checked here so this change is
    provably about the wording and not about the arithmetic."""
    first = await query_tool(
        query="search for asthma", zim_file_path=_MEDLINEPLUS, limit=10, offset=0
    )
    recommended = int(re.search(r"`offset=(\d+)`", _footer(first)).group(1))
    second = await query_tool(
        query="search for asthma",
        zim_file_path=_MEDLINEPLUS,
        limit=10,
        offset=recommended,
    )

    paths = lambda t: set(re.findall(r"^Path: (.+)$", t, re.M))  # noqa: E731
    assert not (paths(first) & paths(second)), paths(first) & paths(second)
