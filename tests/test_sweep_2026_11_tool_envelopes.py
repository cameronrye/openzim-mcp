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
