"""Regressions from the 2026-11 sweep of error envelopes, argument handling,
advice, prompts and resources.

Each class pins one defect that reproduced against ``main`` at e945188 and
names the inputs that exposed it. Every test drives a real client session,
or the simple-mode handler end to end, in the mode the defect lives in.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer
from tests.test_mcp_session import _connected_client, _text

_MINI = "wikipedia_en_climate_change_mini_2024-06.zim"


@pytest.fixture
def withns(zim_test_data_dir: Optional[Path]) -> Path:
    """The testing-suite directory holding the mini archive and small.zim."""
    if zim_test_data_dir is None:
        pytest.skip("ZIM_TEST_DATA_DIR not set")
    directory = zim_test_data_dir / "withns"
    for name in (_MINI, "small.zim"):
        if not (directory / name).exists():
            pytest.skip(f"{name} not in the corpus")
    return directory


@asynccontextmanager
async def _session(
    directory: Path, tool_mode: str, *, cache: bool = False
) -> AsyncIterator[Any]:
    config = OpenZimMcpConfig(
        allowed_directories=[str(directory)],
        tool_mode=tool_mode,
        cache=CacheConfig(enabled=cache),
    )
    async with _connected_client(OpenZimMcpServer(config)) as session:
        yield session


async def _call(session: Any, tool: str, arguments: Dict[str, Any]) -> Any:
    """``(is_error, text, parsed JSON or None)`` for one tool call."""
    result = await session.call_tool(tool, arguments)
    text = _text(result)
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    return result.is_error, text, parsed


class TestBrowseCursorFromAnotherArchive:
    """``zim_browse`` answered another archive's cursor with the generic
    "Input Validation Error" envelope.

    The archive-identity check can only run in the data layer, which raised
    the base validation error, and ``zim_browse`` had no branch for it — so
    the one cursor fault a client's ``cursor_*`` recovery handles by code
    arrived under ``operation="zim_browse"``. ``zim_links`` already reports
    the same fault as ``cursor_context_mismatch``.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["page", "walk"])
    async def test_foreign_cursor_is_a_cursor_context_mismatch(
        self, withns: Path, mode: str
    ) -> None:
        mini, small = str(withns / _MINI), str(withns / "small.zim")
        base = {"namespace": "A", "mode": mode, "limit": 3}
        async with _session(withns, "advanced") as session:
            _, _, first = await _call(
                session, "zim_browse", {**base, "zim_file_path": mini}
            )
            cursor = first["next_cursor"]
            assert cursor, first
            is_error, text, foreign = await _call(
                session,
                "zim_browse",
                {**base, "zim_file_path": small, "cursor": cursor},
            )
            _, _, resumed = await _call(
                session,
                "zim_browse",
                {**base, "zim_file_path": mini, "cursor": cursor},
            )

        assert is_error is True, text
        assert foreign["operation"] == "cursor_context_mismatch", foreign
        assert "different archive" in foreign["message"], foreign
        assert "Input Validation Error" not in foreign["message"], foreign
        # Positive pair: the cursor still resumes the archive that issued it.
        assert resumed.get("error") is not True, resumed
        assert resumed["results"], resumed
        assert resumed["results"] != first["results"]


def _leading_json(text: str) -> Dict[str, Any]:
    """The JSON body of a non-compact ``zim_query`` response.

    The intent / reranker telemetry comments follow the closing brace.
    """
    return json.loads(text[: text.rfind("}") + 1])


class TestSimpleModeRejectionsAreErrors:
    """Simple mode answered a backend-rejected argument as a success.

    ``_render_invalid_request`` returned its "Invalid Request" prose on the
    success path, so a client branching on ``isError`` recorded
    ``browse namespace A`` with ``limit=300`` as a retrieval — and the
    filtered-search variant was even wrapped in the untrusted-content fence.
    The same mistake on the cursor-checking ``browse`` already came back as
    a ``cursor_decode`` error; ``walk`` did not.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "query, limit, cap",
        [
            ("browse namespace A", 300, "1 and 200"),
            ("walk namespace A", 900, "1 and 500"),
            ("search climate in namespace A", 200, "1 and 100"),
        ],
    )
    async def test_out_of_range_limit_is_flagged(
        self, withns: Path, query: str, limit: int, cap: str
    ) -> None:
        mini = str(withns / _MINI)
        async with _session(withns, "simple") as session:
            is_error, text, body = await _call(
                session,
                "zim_query",
                {"query": query, "zim_file_path": mini, "limit": limit},
            )
            ok_error, ok_text, _ = await _call(
                session,
                "zim_query",
                {"query": query, "zim_file_path": mini, "limit": 5},
            )

        assert is_error is True, text
        assert body["operation"] == "invalid_request", body
        # The prose is unchanged; it rides in ``message``.
        assert body["message"].startswith("**Invalid Request**"), body
        assert cap in body["message"], body
        assert "retrieved_archive_content" not in text, text
        # Positive pair: the same query at an accepted limit still succeeds.
        assert ok_error is not True, ok_text
        assert "Invalid Request" not in ok_text

    @pytest.mark.asyncio
    async def test_walk_rejects_another_archives_cursor_like_browse(
        self, withns: Path
    ) -> None:
        mini, small = str(withns / _MINI), str(withns / "small.zim")
        async with _session(withns, "simple") as session:
            cursors = {}
            for verb in ("walk", "browse"):
                _, text, _ = await _call(
                    session,
                    "zim_query",
                    {
                        "query": f"{verb} namespace A",
                        "zim_file_path": mini,
                        "limit": 3,
                        "compact": False,
                    },
                )
                cursors[verb] = _leading_json(text)["next_cursor"]
            replies = {}
            for verb, cursor in cursors.items():
                replies[verb] = await _call(
                    session,
                    "zim_query",
                    {
                        "query": f"{verb} namespace A",
                        "zim_file_path": small,
                        "cursor": cursor,
                    },
                )
            resumed = await _call(
                session,
                "zim_query",
                {
                    "query": "walk namespace A",
                    "zim_file_path": mini,
                    "cursor": cursors["walk"],
                },
            )

        walk_error, walk_text, walk_body = replies["walk"]
        browse_error, _, browse_body = replies["browse"]
        assert browse_error is True and browse_body["operation"] == "cursor_decode"
        assert walk_error is True, walk_text
        assert walk_body["operation"] == "cursor_decode", walk_body
        assert "Drop the `cursor`" in walk_body["message"], walk_body
        # Positive pair: the walk cursor still resumes its own archive.
        assert resumed[0] is not True, resumed[1]
        assert "A/" in resumed[1], resumed[1]
