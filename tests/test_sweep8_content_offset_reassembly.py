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


class TestMachineReadableOffsetAgrees:
    """``_meta.more_at_offset`` must advance exactly as the body hint does.

    The two were computed independently — the body hint inside
    ``truncate_content`` and ``_content_chars`` in ``zim/content.py`` — so
    fixing one left the other gluing words together at every boundary, and a
    client following the structured field got different text from one
    following the prose. Both now derive from ``paged_slice_length``.
    """

    def test_slice_length_matches_the_body_hint(
        self, processor: ContentProcessor
    ) -> None:
        from openzim_mcp.content_processor import paged_slice_length

        body = " ".join(f"word{i:05d}" for i in range(40))
        page = 20
        offset = 0
        while True:
            rendered = processor.truncate_content(
                body[offset:],
                page,
                current_offset=offset,
                paginatable=True,
                original_total=len(body),
            )
            hint = _NEXT_OFFSET.search(rendered)
            if not hint:
                break
            expected = offset + paged_slice_length(body[offset:], page, offset)
            assert int(hint.group(1)) == expected
            offset = expected

    def test_untruncated_body_consumes_everything(
        self, processor: ContentProcessor
    ) -> None:
        from openzim_mcp.content_processor import paged_slice_length

        body = "short body"
        assert paged_slice_length(body, 1000, 0) == len(body)
        assert paged_slice_length("", 1000, 0) == 0

    def test_trailing_whitespace_is_deferred_not_consumed(self) -> None:
        from openzim_mcp.content_processor import paged_slice_length

        # The page ends mid-gap; the gap belongs to the next page.
        assert paged_slice_length("aa   bb", 4, 10) == 2
        # At the top of the article, leading whitespace is consumed.
        assert paged_slice_length("  aabb", 4, 0) == 4


class TestMetadataEntryPaginationOffset:
    """The payload builders must publish the same advance the body hint uses.

    ``_content_chars`` becomes ``_meta.more_at_offset``, which is what a
    programmatic client pages by. It was computed as the raw page size while
    the body hint had been corrected to the stripped one, so the structured
    field still skipped the boundary whitespace and glued words together —
    and the two fields disagreed with each other.
    """

    def test_content_chars_matches_the_shared_slice_length(self) -> None:
        from unittest.mock import MagicMock

        from openzim_mcp.content_processor import ContentProcessor, paged_slice_length
        from openzim_mcp.zim.content import _ContentMixin

        body = " ".join(f"word{i:05d}" for i in range(40))
        page = 20

        class _Stub(_ContentMixin):
            def __init__(self) -> None:
                self.content_processor = ContentProcessor(
                    OpenZimMcpConfig(allowed_directories=["/tmp"])
                )

        stub = _Stub()
        archive = MagicMock()
        item = MagicMock()
        item.content = body.encode()
        item.mimetype = "text/plain"
        archive.get_metadata_item.return_value = item

        payload, ok = stub._get_metadata_entry_data(archive, "M/Description", page, 0)

        assert ok
        assert payload["_content_chars"] == paged_slice_length(body, page, 0)
        # The boundary lands on a space, so the raw page size is the wrong
        # answer and must not be what ships.
        assert payload["_content_chars"] != page
