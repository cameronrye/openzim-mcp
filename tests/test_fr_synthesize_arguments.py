"""``synthesize=True`` must not validate an argument and then drop it.

v3.3.1 field report, fid 130::

    zim_query(synthesize=True, limit=50)    citations 5, raw_chars 7469
    zim_query(synthesize=True, limit=1000)  citations 5, raw_chars 7469
                                            — byte-identical, sha256 match
    zim_query(synthesize=True, limit=1001)  invalid_limit: must not exceed 1000

So the argument is validated on a path that then ignores it, and the tool
description documents `limit` unconditionally without saying synthesize
does not honour it. `offset`, `content_offset` and `cursor` go the same
way: the tool checks their ranges and `_handle_synthesize_query`'s
signature never receives them.

The pipeline does have a passage count — ``SynthesizeConfig.top_n``,
bounded 1..50 — so `limit` maps onto something real for most values. Above
that bound there is nothing to honour, and clamping silently would be the
same defect in a smaller size, so it is refused in the vocabulary v3.3.0
introduced for combinations a mode cannot serve. The synthesize pipeline
fuses one ranked set and has no pagination at all, so the paging arguments
are refused rather than mapped.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

_MINI = "wikipedia_en_climate_change_mini_2024-06.zim"


@pytest.fixture
def query_tool(tmp_path, zim_test_data_dir: Optional[Path]) -> Any:
    if zim_test_data_dir is None:
        pytest.skip("ZIM_TEST_DATA_DIR not set")
    source = zim_test_data_dir / "withns" / _MINI
    if not source.exists():
        pytest.skip(f"{_MINI} not in the corpus")
    solo = tmp_path / "solo"
    solo.mkdir()
    shutil.copy(source, solo / _MINI)
    server = OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(solo)],
            tool_mode="simple",
            cache=CacheConfig(enabled=False),
        )
    )
    return server.mcp._tool_manager._tools["zim_query"].fn


def _articles(payload: Any) -> int:
    """How many source articles the answer was actually built from.

    ``top_n`` bounds the passages the pipeline keeps, and each surviving
    passage's article shows up here — so this is what a caller asking for
    "more results" is asking to move. ``citations`` is a derived count that
    runs one ahead of it, and ``passages`` is empty on this surface
    (``omit_passage_text``), so neither reads the knob directly.
    """
    assert isinstance(payload, dict), payload
    return len(payload.get("considered_articles") or [])


# ---------------------------------------------------------------------------
# `limit` is honoured where the pipeline has something to honour it with
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_limit_changes_the_number_of_source_articles(query_tool):
    one = await query_tool(query="climate change", synthesize=True, limit=1)
    two = await query_tool(query="climate change", synthesize=True, limit=2)

    assert one.get("error") is not True, one
    assert two.get("error") is not True, two
    assert _articles(one) == 1, one["considered_articles"]
    assert _articles(two) == 2, two["considered_articles"]
    assert one["total_chars"] < two["total_chars"], (one, two)


@pytest.mark.asyncio
async def test_two_limits_no_longer_produce_the_identical_payload(query_tool):
    """The finding's evidence was a sha256 match between two limits."""
    import json

    a = await query_tool(query="climate change", synthesize=True, limit=2)
    b = await query_tool(query="climate change", synthesize=True, limit=9)

    assert json.dumps(a, sort_keys=True) != json.dumps(b, sort_keys=True)


@pytest.mark.asyncio
async def test_omitting_limit_keeps_the_configured_default(query_tool):
    """Control: the default must not become "whatever was asked last"."""
    default = await query_tool(query="climate change", synthesize=True)
    narrowed = await query_tool(query="climate change", synthesize=True, limit=1)
    again = await query_tool(query="climate change", synthesize=True)

    assert default.get("error") is not True, default
    assert _articles(default) > _articles(narrowed)
    assert default["total_chars"] == again["total_chars"]


@pytest.mark.asyncio
async def test_a_limit_the_corpus_cannot_fill_saturates_quietly(query_tool):
    """Only three articles in this archive match, so asking for twenty is
    not an error — it is a ceiling the supply never reaches."""
    plenty = await query_tool(query="climate change", synthesize=True, limit=20)
    fewer = await query_tool(query="climate change", synthesize=True, limit=5)

    assert plenty.get("error") is not True, plenty
    assert _articles(plenty) == _articles(fewer)


# ---------------------------------------------------------------------------
# ...and refused where it has nothing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_limit_past_the_passage_ceiling_is_refused_not_clamped(query_tool):
    out = await query_tool(query="climate change", synthesize=True, limit=1000)

    assert out.get("error") is True, out
    assert out["operation"] == "invalid_limit", out
    assert "50" in out["message"], out["message"]
    assert "synthesize" in out["message"], out["message"]


@pytest.mark.asyncio
async def test_the_ceiling_itself_is_accepted(query_tool):
    """Control against an off-by-one that refuses the documented maximum."""
    out = await query_tool(query="climate change", synthesize=True, limit=50)

    assert out.get("operation") != "invalid_limit", out


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs,named",
    [
        ({"offset": 5}, "offset"),
        ({"content_offset": 100}, "content_offset"),
        ({"cursor": "abc"}, "cursor"),
    ],
)
async def test_paging_arguments_are_refused_rather_than_dropped(
    query_tool, kwargs, named
):
    """The pipeline fuses one ranked set; there is no page two to ask for."""
    out = await query_tool(query="climate change", synthesize=True, **kwargs)

    assert out.get("error") is True, out
    assert out["operation"] == "invalid_combination", out
    assert named in out["message"], out["message"]


@pytest.mark.asyncio
async def test_the_same_arguments_still_work_without_synthesize(query_tool):
    """Control: the refusals are scoped to the mode that cannot serve them.

    `offset` and a large `limit` are ordinary on the search path, and a
    guard written at the wrong level would break it.
    """
    out = await query_tool(query="search for climate", limit=60, offset=5)

    text = out if isinstance(out, str) else str(out)
    assert "invalid_combination" not in text, text
    assert "invalid_limit" not in text, text
