"""``compact_budget`` is a hard cap on the whole response, footer included.

Sweep finding (size cap and paging): the cap reserved room for the content
fence and the telemetry markers, then ``_finalize_compact_response`` appended
the ``> ~N tokens`` footer after it — so ``tiny`` came back at 2,036 chars
against its documented 2,000, and every budget overshot by the footer.

And at the smallest budgets the cap kept the page header after cutting every
row under it: a 500-char ``search for carbon`` said "showing 1-10" over no
rows at all.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Callable

import pytest
from libzim.writer import Creator

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig, RateLimitConfig
from openzim_mcp.server import OpenZimMcpServer
from tests.conftest_v2_fixtures import _HtmlItem
from tests.test_compact_cap_continuations import _build, _html, _note

# The documented ceiling of each named profile, plus the clamp floor.
_CAPS = {"tiny": 2_000, "small": 4_000, "medium": 6_000, 500: 500, 1000: 1000}


def _build_long_article(out: Path) -> Path:
    """A 200-paragraph article, numbered so a reader can see what it got, and
    an 80-section one whose outline alone overflows the small budgets."""
    paragraphs = "".join(
        f"<p>Paragraph {i:04d} of the long article: " + "zebra stripes " * 20 + "</p>"
        for i in range(200)
    )
    sections = "".join(
        f"<h2>Section {i:02d} on zebra herds</h2><p>Herd {i:02d} grazed.</p>"
        for i in range(80)
    )
    with Creator(str(out)).config_indexing(True, "eng") as creator:
        creator.add_item(_HtmlItem("Long", "Long", _html("Long", paragraphs)))
        creator.add_item(_HtmlItem("Outline", "Outline", _html("Outline", sections)))
        creator.set_mainpath("Long")
    return out


@pytest.fixture
def archives(tmp_path: Path) -> Path:
    _build(tmp_path / "plain.zim", hub=True)
    _build_long_article(tmp_path / "long.zim")
    return tmp_path


@pytest.fixture
def query(archives: Path) -> Callable[..., str]:
    server = OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(archives)],
            tool_mode="simple",
            cache=CacheConfig(enabled=False),
            rate_limit=RateLimitConfig(enabled=False),
        )
    )
    fn = server.mcp._tool_manager._tools["zim_query"].fn

    def _call(**kwargs: Any) -> str:
        out = asyncio.run(fn(**kwargs))
        assert isinstance(out, str), out
        return out

    return _call


_REQUESTS = [
    ("plain.zim", {"query": "browse namespace C"}),
    ("plain.zim", {"query": "walk namespace C", "limit": 50}),
    ("plain.zim", {"query": "search for zebra", "limit": 50}),
    ("plain.zim", {"query": "links in zebra_hub", "limit": 60}),
    ("plain.zim", {"query": "suggestions for zebra", "limit": 50}),
    ("long.zim", {"query": "get article Long"}),
    ("long.zim", {"query": "get article Long", "max_content_length": 9000}),
    ("long.zim", {"query": "show structure of Outline"}),
]


def test_the_whole_response_fits_its_budget(
    query: Callable[..., str], archives: Path
) -> None:
    over = []
    capped = 0
    for budget, cap in _CAPS.items():
        for archive, request_args in _REQUESTS:
            out = query(
                zim_file_path=str(archives / archive),
                compact_budget=budget,
                **request_args,
            )
            # Positive: a real response, footer and all.
            assert "\n> ~" in out, out[-300:]
            if len(out) > cap:
                over.append((budget, request_args, len(out)))
            if "Response truncated" in out:
                capped += 1
    assert over == []
    # Positive control: most of these requests overflow their budget, so the
    # cap and the footer after it really were exercised.
    assert capped >= 25, capped


def test_a_search_page_with_no_room_for_a_row_claims_none(
    query: Callable[..., str], archives: Path
) -> None:
    """Sweep the small budgets: the header names exactly the rows shipped,
    including when that is none of them."""
    empty_pages = 0
    for budget in range(500, 1100, 9):
        out = query(
            query="search for zebra",
            zim_file_path=str(archives / "plain.zim"),
            limit=10,
            compact_budget=budget,
        )
        ordinals = [int(n) for n in re.findall(r"^## (\d+)\. ", out, re.M)]
        claim = re.search(r"showing (\d+)-(\d+)", out)
        if ordinals:
            assert claim and claim.group(0) == f"showing 1-{ordinals[-1]}", budget
        else:
            assert claim is None, (budget, out[:400])
            if "showing none of 1-10:" in out:
                empty_pages += 1
    # Positive control: some budget fit the header and no row.
    assert empty_pages > 0


def test_a_walk_page_with_no_room_for_a_row_claims_none(
    query: Callable[..., str], archives: Path
) -> None:
    zim = archives / "long_titles.zim"
    with Creator(str(zim)).config_indexing(True, "eng") as creator:
        for i in range(5):
            title = f"Zebra field note {i:03d} " + "with an unusually long title " * 15
            creator.add_item(_HtmlItem(_note(i), title, _html(title, "<p>Zebra.</p>")))
        creator.set_mainpath(_note(0))
    out = query(
        query="walk namespace C", zim_file_path=str(zim), limit=3, compact_budget=500
    )
    header = out.splitlines()[0]
    # Negative: no row shipped, and the header no longer claims entries 1-3.
    assert "- **" not in out
    assert "— entries 1-3" not in header
    # Positive: it names the page it cut, and the footer says what happened.
    assert header.startswith("# Namespace `C` — none of entries 1-3 "), header
    assert "3 result rows were dropped" in out
