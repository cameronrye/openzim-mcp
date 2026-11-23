"""Paging an article through compact ``zim_query`` must not skip text.

Sweep finding (size cap and paging): ``_handle_get_article`` sizes the page by
``max_content_length`` (4,000 chars by default) and the data layer ends it
with ``Pass `content_offset=N``` — N being the first character the page did
not serve. ``_cap_response_size`` then cut the rendered page to the compact
budget, hint and all, so on the 200-paragraph ``A/Long`` fixture:

* ``compact_budget="tiny"`` returned paragraphs 0000-0004 and no hint, under a
  footer pointing at "the cursor in the body above (if present)";
* ``content_offset=4000``, the next page by the page size, started at
  paragraph 0011 — 0005-0010 were never served (``small`` lost 0010);
* the default budget with ``max_content_length=9000`` shipped 5.7k of 9.2k.

The test follows the hint each page actually carries and checks the text it
reaches, so a hint that skips (or repeats) anything fails on the text.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest
from libzim.writer import Creator

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig, RateLimitConfig
from openzim_mcp.server import OpenZimMcpServer
from tests.conftest_v2_fixtures import _HtmlItem
from tests.test_compact_cap_continuations import _html

_CAPS = {"tiny": 2_000, "small": 4_000, "medium": 6_000, 1000: 1000}
_BODY_START = "\n## Content\n\n"
_HINT_RE = re.compile(r"Pass `content_offset=(\d+)` to read the next page")
_NOTE_RE = re.compile(r"\n\n\.\.\. \[Content truncated, [^\n]*\] \.\.\.")


@pytest.fixture
def server(tmp_path: Path) -> OpenZimMcpServer:
    paragraphs = "".join(
        f"<p>Paragraph {i:04d} of the long article: " + "zebra stripes " * 20 + "</p>"
        for i in range(60)
    )
    with Creator(str(tmp_path / "long.zim")).config_indexing(True, "eng") as creator:
        creator.add_item(_HtmlItem("Long", "Long", _html("Long", paragraphs)))
        creator.set_mainpath("Long")
    # Cache ON: every page is asked for twice, so a re-fit page that a warm
    # cache serves differently from a cold render shows up as a mismatch.
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(tmp_path)],
            tool_mode="simple",
            cache=CacheConfig(
                enabled=True,
                persistence_enabled=False,
                persistence_path=str(tmp_path / "cache"),
            ),
            rate_limit=RateLimitConfig(enabled=False),
        )
    )


def _query(server: OpenZimMcpServer) -> Callable[..., str]:
    fn = server.mcp._tool_manager._tools["zim_query"].fn

    def _call(**kwargs: Any) -> str:
        out = asyncio.run(fn(**kwargs))
        assert isinstance(out, str), out
        return out

    return _call


def _page_body(text: str) -> str:
    """The article text one page served: between its header and its note."""
    start = text.index(_BODY_START) + len(_BODY_START)
    note = _NOTE_RE.search(text, start)
    end = note.start() if note else text.index("\n<!-- intent=", start)
    return text[start:end]


def _full_body(server: OpenZimMcpServer) -> str:
    """The whole compact body, from the data layer in one unbounded page."""
    zim = server.config.allowed_directories[0] + "/long.zim"
    page = server.zim_operations.get_zim_entry(zim, "Long", 10**7, 0, compact=True)
    start = page.index(_BODY_START) + len(_BODY_START)
    assert not _NOTE_RE.search(page)
    return page[start:]


def _read_all(
    query: Callable[..., str], zim: str, budget: Any, max_content_length: Optional[int]
) -> List[str]:
    pages: List[str] = []
    offset = 0
    for _ in range(500):
        kwargs: Dict[str, Any] = {
            "query": "get article Long",
            "zim_file_path": zim,
            "compact_budget": budget,
        }
        if offset:
            kwargs["content_offset"] = offset
        if max_content_length is not None:
            kwargs["max_content_length"] = max_content_length
        out = query(**kwargs)
        pages.append(out)
        hint = _HINT_RE.search(out)
        if hint is None:
            return pages
        assert int(hint.group(1)) > offset, "the hint must move forward"
        offset = int(hint.group(1))
    raise AssertionError("paging did not terminate")


@pytest.mark.parametrize(
    "budget,max_content_length",
    [("tiny", None), ("small", None), (1000, None), ("medium", 9000)],
    ids=["tiny", "small", "1000", "medium-mcl9000"],
)
def test_following_the_hint_reproduces_the_whole_body(
    server: OpenZimMcpServer, budget: Any, max_content_length: Optional[int]
) -> None:
    query = _query(server)
    zim = server.config.allowed_directories[0] + "/long.zim"
    full = _full_body(server)
    assert len(full) > 15_000

    first = _read_all(query, zim, budget, max_content_length)
    assert "".join(_page_body(p) for p in first) == full
    # Positive controls: the budget really did bind, page after page, and
    # every page still fits it — the page was re-cut by the data layer
    # rather than sliced by the cap, so no page carries the cap's footer.
    assert len(first) >= 3
    for page in first:
        assert len(page) <= _CAPS[budget], (len(page), page[-300:])
        assert "Response truncated" not in page
    assert all(_HINT_RE.search(p) for p in first[:-1])

    # Second pass on a warm cache: byte-identical pages.
    second = _read_all(query, zim, budget, max_content_length)
    assert second == first
