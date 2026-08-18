"""Paging an article with ``content_offset`` must reassemble to the original.

``truncate_content`` stripped the slice it emitted but advanced the
``content_offset`` it advertises by the *unstripped* page size, so every
character of whitespace sitting on a page boundary was dropped from the
document rather than deferred to the next page. A client following the
footer's own instruction and concatenating the pages got words fused
together — "word00001word00002" — with no indication anything was lost.
"""

from __future__ import annotations

import re

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor

_FOOTER = re.compile(r"\n*\.\.\. \[Content truncated.*", re.DOTALL)
_NEXT_OFFSET = re.compile(r"content_offset=(\d+)")


@pytest.fixture
def processor() -> ContentProcessor:
    return ContentProcessor(OpenZimMcpConfig(allowed_directories=["/tmp"]))


def _page_through(processor: ContentProcessor, body: str, page: int) -> str:
    """Follow the footer's own ``content_offset`` hint to the end."""
    parts: list[str] = []
    offset = 0
    for _ in range(500):  # generous bound; the loop must terminate on its own
        rendered = processor.truncate_content(
            body[offset:],
            page,
            current_offset=offset,
            paginatable=True,
            original_total=len(body),
        )
        parts.append(_FOOTER.sub("", rendered))
        hint = _NEXT_OFFSET.search(rendered)
        if not hint:
            break
        nxt = int(hint.group(1))
        assert nxt > offset, f"offset did not advance past {offset}"
        offset = nxt
    else:  # pragma: no cover
        pytest.fail("paging did not terminate")
    return "".join(parts)


@pytest.mark.parametrize("page", [20, 21, 37])
def test_pages_reassemble_to_the_original_body(
    processor: ContentProcessor, page: int
) -> None:
    """Word boundaries land on the page edge for at least one page size here."""
    body = " ".join(f"word{i:05d}" for i in range(40))
    assert _page_through(processor, body, page) == body


def test_newline_boundaries_survive_paging(processor: ContentProcessor) -> None:
    """Paragraph breaks are whitespace too, and they carry meaning."""
    body = "\n\n".join(f"Paragraph {i} body text here." for i in range(12))
    assert _page_through(processor, body, 29) == body


def test_leading_whitespace_is_trimmed_once_at_the_top(
    processor: ContentProcessor,
) -> None:
    """The article's own leading whitespace is still cosmetic, and dropping it
    at offset 0 costs no interior character."""
    body = "   " + " ".join(f"word{i:05d}" for i in range(30))
    assert _page_through(processor, body, 25) == body.lstrip()
