"""A forged cursor must not be able to ask for a page the tool would refuse.

Cursors are unsigned base64 JSON, so `s.l` is entirely client-controlled.
Every tool validates an explicit `limit` against its cap, but that check only
runs when the caller passes one — a request carrying only a cursor skipped it
and the cursor's page size went straight to the data layer.
`search_zim_file_data` has no range check of its own, so
`result_count = min(limit, total_results - offset)` became the whole match
set: millions of libzim lookups and snippet renders on a real archive, from
one unauthenticated request.

The rule already documented for `s.l` — anything that isn't a positive int
falls back to the handler default rather than erroring — now covers "larger
than any page the server would ever mint" too.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict

import pytest

from openzim_mcp.constants import MAX_SEARCH_RESULT_LIMIT
from openzim_mcp.cursor_decode import decode_offset_cursor
from openzim_mcp.tools._common import effective_limit


def _cursor(state: Dict[str, Any], tool: str = "search_zim_file") -> str:
    payload = {"v": 2, "t": tool, "s": state}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


class TestEffectiveLimit:
    """The advanced arm's resolver."""

    def test_oversized_cursor_limit_falls_back_to_the_default(self) -> None:
        assert effective_limit(None, {"l": 10**9}, 50) == 50

    def test_limit_at_the_cap_is_honoured(self) -> None:
        assert (
            effective_limit(None, {"l": MAX_SEARCH_RESULT_LIMIT}, 50)
            == MAX_SEARCH_RESULT_LIMIT
        )

    def test_ordinary_cursor_limit_is_still_honoured(self) -> None:
        assert effective_limit(None, {"l": 3}, 50) == 3

    def test_explicit_limit_still_wins(self) -> None:
        assert effective_limit(7, {"l": 3}, 50) == 7


class TestDecodeCursorState:
    """The simple arm's resolver."""

    @pytest.mark.parametrize("oversized", [MAX_SEARCH_RESULT_LIMIT + 1, 10**9])
    def test_oversized_cursor_limit_is_not_projected(self, oversized: int) -> None:
        result = decode_offset_cursor(
            _cursor({"o": 0, "l": oversized, "q": "berlin"}),
            query="berlin",
            q_emitting_tools={"search_zim_file"},
        )
        assert not isinstance(result, dict), result
        assert result.limit is None, (
            "an oversized page size must fall back to the handler default, "
            f"got {result.limit}"
        )

    def test_limit_at_the_cap_is_honoured(self) -> None:
        result = decode_offset_cursor(
            _cursor({"o": 0, "l": MAX_SEARCH_RESULT_LIMIT, "q": "berlin"}),
            query="berlin",
            q_emitting_tools={"search_zim_file"},
        )
        assert not isinstance(result, dict), result
        assert result.limit == MAX_SEARCH_RESULT_LIMIT

    def test_ordinary_cursor_limit_is_still_honoured(self) -> None:
        result = decode_offset_cursor(
            _cursor({"o": 0, "l": 3, "q": "berlin"}),
            query="berlin",
            q_emitting_tools={"search_zim_file"},
        )
        assert not isinstance(result, dict), result
        assert result.limit == 3
