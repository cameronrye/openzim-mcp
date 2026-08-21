"""Simple mode must honour the page size its own cursor was issued under.

Every cursor this server mints encodes the page size in ``s.l``. The ADVANCED
arm reads it — ``tools/_common.effective_limit`` returns ``state['l']`` when
the caller omits ``limit``, and ``zim_browse``/``zim_links`` route every branch
through it — so an opaque-cursor client that replays ``next_cursor`` without
repeating ``limit`` keeps its page size.

The SIMPLE arm never did. ``decode_offset_cursor`` projected ``o``/``ns``/
``ai``/``t``/``ep``/``k`` onto ``CursorDecodeResult`` but not ``l``, so
``handle_zim_query`` stashed nothing and each handler fell back to its own
hard-coded default. Replaying the cursor the footer *tells the caller to pass*
therefore silently changed the page size — for ``walk namespace``, from the
requested 3 rows to the handler default of 200.

That is the same defect ``effective_limit`` was added to fix, on the arm that
was missed: one of the two sibling paths got the fix and the other did not.
"""

from __future__ import annotations

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.cursor_decode import decode_offset_cursor
from openzim_mcp.pagination import Cursor
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.simple_tools import SimpleToolsHandler


def _token(tool: str, state: dict) -> str:
    return Cursor.encode(tool=tool, state=state)


def test_decode_projects_the_cursor_page_size() -> None:
    result = decode_offset_cursor(
        _token("walk_namespace", {"o": 57, "l": 3, "ns": "A", "ai": "abc123"}),
        query="walk namespace A",
        q_emitting_tools=set(),
    )
    assert not isinstance(result, dict), result
    assert result.offset == 57
    assert result.limit == 3


def test_absent_page_size_stays_none() -> None:
    """A cursor without ``l`` must not invent one — the handler default wins."""
    result = decode_offset_cursor(
        _token("walk_namespace", {"o": 10, "ns": "A"}),
        query="walk namespace A",
        q_emitting_tools=set(),
    )
    assert not isinstance(result, dict), result
    assert result.limit is None


def test_invalid_page_size_is_ignored_not_fatal() -> None:
    """A hand-built cursor can carry anything; fall back, don't crash.

    Mirrors ``effective_limit``'s rule on the advanced arm: anything other
    than a positive int is discarded in favour of the caller's default.
    """
    for bad in (0, -5, "3", 3.5, True, None):
        result = decode_offset_cursor(
            _token("walk_namespace", {"o": 10, "l": bad, "ns": "A"}),
            query="walk namespace A",
            q_emitting_tools=set(),
        )
        assert not isinstance(result, dict), (bad, result)
        assert result.limit is None, f"{bad!r} should not be accepted as a limit"


@pytest.fixture
def corpus_handler(real_content_zim_files):
    """A SimpleToolsHandler over the shipped Wikipedia corpus archive."""
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("wikipedia climate corpus archive not available")
    config = OpenZimMcpConfig(allowed_directories=[str(zim.parent)])
    return SimpleToolsHandler(OpenZimMcpServer(config).zim_operations), zim


class TestEndToEndReplay:
    """The footer says "pass cursor=X"; doing so must not resize the page."""

    def test_walk_namespace_cursor_replay_keeps_page_size(self, corpus_handler) -> None:
        import re

        simple_tools_handler, real_zim_file = corpus_handler
        page1 = str(
            simple_tools_handler.handle_zim_query(
                "walk namespace A",
                zim_file_path=str(real_zim_file),
                options={"compact": True, "limit": 3},
            )
        )
        match = re.search(r"cursor=([A-Za-z0-9_=-]+)", page1)
        assert match, f"no cursor in page 1 footer: {page1[:400]}"

        page2 = str(
            simple_tools_handler.handle_zim_query(
                "walk namespace A",
                zim_file_path=str(real_zim_file),
                options={"compact": True, "cursor": match.group(1)},
            )
        )
        # Page 1 reported "scan positions 1-57" for 3 entries. Page 2 must
        # carry the same page size, not balloon to the 200-row default.
        span = re.search(r"entries (\d+)-(\d+)", page2)
        assert span, f"no entry span in page 2 header: {page2[:400]}"
        width = int(span.group(2)) - int(span.group(1)) + 1
        assert width <= 60, (
            f"page 2 spans {width} entries; the cursor was issued for a "
            "3-row page, so replaying it must not resize to the handler default"
        )

    def test_explicit_limit_still_overrides_the_cursor(self, corpus_handler) -> None:
        """Precedence matches the advanced arm: explicit limit wins."""
        import re

        simple_tools_handler, real_zim_file = corpus_handler
        page1 = str(
            simple_tools_handler.handle_zim_query(
                "walk namespace A",
                zim_file_path=str(real_zim_file),
                options={"compact": True, "limit": 3},
            )
        )
        cursor = re.search(r"cursor=([A-Za-z0-9_=-]+)", page1).group(1)
        page2 = str(
            simple_tools_handler.handle_zim_query(
                "walk namespace A",
                zim_file_path=str(real_zim_file),
                options={"compact": True, "cursor": cursor, "limit": 5},
            )
        )
        span = re.search(r"entries (\d+)-(\d+)", page2)
        assert span, page2[:400]
        assert int(span.group(2)) - int(span.group(1)) + 1 <= 10
