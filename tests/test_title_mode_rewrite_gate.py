"""Title mode must look the query up as typed before it rewrites it.

``zim_search(mode='title')`` ran the misspelling map and the leading-article
strip on every query before the lookup, so a title that starts with "A",
"An", "The" or "Of" was answered with a different article: on the climate
mini archive ``A Green New Deal`` returned ``A/Green_New_Deal`` at 1.0
"direct", while ``A/A_Green_New_Deal`` — the article actually named that,
whose hatnote says "For the American policy proposal, see Green New Deal" —
exists. It also ignored ``query_rewrite.enabled=false``: the operator's kill
switch still had ``photosythesis`` looked up and echoed as
``photosynthesis``.

Driven through the registered tool on the real archive.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig, QueryRewriteConfig
from openzim_mcp.server import OpenZimMcpServer


@pytest.fixture
def climate_zim(real_content_zim_files: Dict[str, Optional[Path]]) -> Path:
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("climate-change ZIM fixture not available")
    return zim


def _tool(allowed: Path, *, rewrite: bool = True, cache: bool = False) -> Any:
    config = OpenZimMcpConfig(
        allowed_directories=[str(allowed)],
        tool_mode="advanced",
        cache=(
            CacheConfig(enabled=True, max_size=100, ttl_seconds=600)
            if cache
            else CacheConfig(enabled=False)
        ),
        query_rewrite=QueryRewriteConfig(enabled=rewrite),
    )
    server = OpenZimMcpServer(config)
    return server.mcp._tool_manager._tools["zim_search"].fn


async def _title(tool: Any, zim: Path, query: str) -> Dict[str, Any]:
    return await tool(query=query, mode="title", zim_file_path=str(zim), limit=5)


class TestTypedTitleIsLookedUpFirst:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("A Green New Deal", "A/A_Green_New_Deal"),
            ("The Day After Tomorrow", "A/The_Day_After_Tomorrow"),
            ("An Inconvenient Truth", "A/An_Inconvenient_Truth"),
        ],
    )
    async def test_a_title_starting_with_an_article_is_kept(
        self, climate_zim: Path, query: str, expected: str
    ) -> None:
        page = await _title(_tool(climate_zim.parent), climate_zim, query)

        top = page["results"][0]
        # Positive: the article the typed string names, as an exact match,
        # looked up under the string the caller typed.
        assert top["path"] == expected, page["results"]
        assert top["score"] == 1.0
        assert top["match_type"] == "direct"
        assert page["query"] == query
        # Negative: the article-stripped title is not what answered.
        stripped = query.split(" ", 1)[1]
        assert page["query"] != stripped

    @pytest.mark.asyncio
    async def test_the_lower_cased_spelling_is_kept_too(
        self, climate_zim: Path
    ) -> None:
        """Simple mode lower-cases every query; the typed-first lookup is
        case-insensitive, so the article survives that as well."""
        page = await _title(_tool(climate_zim.parent), climate_zim, "a green new deal")

        assert page["results"][0]["path"] == "A/A_Green_New_Deal", page["results"]
        assert page["results"][0]["path"] != "A/Green_New_Deal"

    @pytest.mark.asyncio
    async def test_the_cached_page_is_the_typed_title(self, climate_zim: Path) -> None:
        """Cache enabled: both lookups are cached per title string, so the
        second call must still be keyed on what was typed."""
        tool = _tool(climate_zim.parent, cache=True)

        cold = await _title(tool, climate_zim, "A Green New Deal")
        warm = await _title(tool, climate_zim, "A Green New Deal")

        for page in (cold, warm):
            assert page["results"][0]["path"] == "A/A_Green_New_Deal"
            assert page["query"] == "A Green New Deal"
        assert warm["results"] == cold["results"]


class TestRewriteStillRunsWhenTheTypedStringIsNotATitle:
    @pytest.mark.asyncio
    async def test_an_article_prefix_with_no_title_is_still_stripped(
        self, climate_zim: Path
    ) -> None:
        # Control: "The Greenhouse Effect" names no entry, so the strip runs.
        # ("The Green New Deal" would not do: it is a redirect title.)
        page = await _title(
            _tool(climate_zim.parent), climate_zim, "The Greenhouse Effect"
        )

        assert page["query"] == "Greenhouse Effect"
        assert page["results"][0]["path"] == "A/Greenhouse_effect", page["results"]

    @pytest.mark.asyncio
    async def test_a_misspelling_with_no_title_is_still_corrected(
        self, climate_zim: Path
    ) -> None:
        page = await _title(_tool(climate_zim.parent), climate_zim, "photosythesis")

        assert page["query"] == "photosynthesis"
        assert page["query"] != "photosythesis"


class TestKillSwitch:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", ["photosythesis", "The Greenhouse Effect"])
    async def test_disabled_rewrite_looks_up_the_query_unchanged(
        self, climate_zim: Path, query: str
    ) -> None:
        page = await _title(
            _tool(climate_zim.parent, rewrite=False), climate_zim, query
        )

        # Positive: the lookup ran under the string the caller sent.
        assert page["query"] == query
        # Negative: no rewritten form answered in its place.
        assert page["query"] not in ("photosynthesis", "Greenhouse Effect")

    @pytest.mark.asyncio
    async def test_cross_file_honours_both_rules(
        self, climate_zim: Path, tmp_path: Path
    ) -> None:
        """The fan-out branch rewrites too, so it needs the same gate."""
        shutil.copy(climate_zim, tmp_path / climate_zim.name)

        typed = await _tool(tmp_path)(
            query="A Green New Deal", mode="title", cross_file=True, limit=5
        )
        disabled = await _tool(tmp_path, rewrite=False)(
            query="photosythesis", mode="title", cross_file=True, limit=5
        )
        enabled = await _tool(tmp_path)(
            query="photosythesis", mode="title", cross_file=True, limit=5
        )

        assert typed["results"][0]["path"] == "A/A_Green_New_Deal", typed["results"]
        assert typed["query"] == "A Green New Deal"
        assert disabled["query"] == "photosythesis"
        # Control: with the switch on, the same fan-out is still corrected.
        assert enabled["query"] == "photosynthesis"
