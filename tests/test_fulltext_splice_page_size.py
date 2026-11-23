"""A fulltext page must never hold more rows than ``limit``.

``zim_search(mode='fulltext')`` promotes the canonical title-index hit onto
page one (fid 58) by prepending it as an extra row, so on the climate mini
archive ``query='glacier', limit=1`` returned ``A/Glacier`` plus
``A/Retreat_of_glaciers_since_1850`` (``returned_count: 2``) and
``limit=2`` returned three. Trimming the extra row away is not enough on its
own — the trimmed hit has to stay reachable from ``next_offset`` — so a page
the canonical would overflow is rebuilt from one ranked hit fewer.

Driven through the registered tool on the real archive.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

_CANONICAL = "A/Glacier"


@pytest.fixture
def climate_zim(real_content_zim_files: Dict[str, Optional[Path]]) -> Path:
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("climate-change ZIM fixture not available")
    return zim


def _server(zim: Path, *, cache: bool = False) -> OpenZimMcpServer:
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(zim.parent)],
            tool_mode="advanced",
            cache=(
                CacheConfig(enabled=True, max_size=100, ttl_seconds=600)
                if cache
                else CacheConfig(enabled=False)
            ),
        )
    )


async def _page(
    server: OpenZimMcpServer, zim: Path, *, limit: int, offset: int = 0
) -> Dict[str, Any]:
    tool = server.mcp._tool_manager._tools["zim_search"].fn
    return await tool(
        query="glacier", zim_file_path=str(zim), limit=limit, offset=offset
    )


def _ranked(server: OpenZimMcpServer, zim: Path, n: int) -> List[str]:
    """The archive's own BM25 order, before any splice."""
    raw = server.zim_operations.search_zim_file_data(str(zim), "glacier", limit=n)
    return [r["path"] for r in raw["results"]]


class TestTheSplicedPageFitsTheLimit:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("limit", [1, 2, 3, 5])
    async def test_a_page_never_exceeds_limit(
        self, climate_zim: Path, limit: int
    ) -> None:
        page = await _page(_server(climate_zim), climate_zim, limit=limit)

        assert 0 < len(page["results"]) <= limit, page["results"]
        assert page["page_info"]["returned_count"] == len(page["results"])
        assert page["page_info"]["limit"] == limit

    @pytest.mark.asyncio
    async def test_the_canonical_still_leads_a_small_page(
        self, climate_zim: Path
    ) -> None:
        """The canonical is ranked third, so at ``limit=2`` it is not on the
        BM25 page and the splice has to make room for it."""
        server = _server(climate_zim)
        ranked = _ranked(server, climate_zim, 3)
        assert ranked.index(_CANONICAL) == 2, ranked

        page = await _page(server, climate_zim, limit=2)

        assert [r["path"] for r in page["results"]] == [_CANONICAL, ranked[0]]
        # The ranked hit that made room is where the next page starts.
        assert page["page_info"]["next_offset"] == 1

    @pytest.mark.asyncio
    async def test_no_ranked_hit_falls_between_pages(self, climate_zim: Path) -> None:
        server = _server(climate_zim)
        ranked = _ranked(server, climate_zim, 6)

        for limit in (2, 3):
            offset, walked = 0, []
            while offset < 6:
                page = await _page(server, climate_zim, limit=limit, offset=offset)
                walked += [r["path"] for r in page["results"]]
                offset = page["page_info"]["next_offset"]
            missing = [p for p in ranked if p not in walked]
            assert not missing, (limit, missing, walked)
            assert walked[0] == _CANONICAL

    @pytest.mark.asyncio
    async def test_a_one_row_page_keeps_its_ranked_hit(self, climate_zim: Path) -> None:
        """One row cannot hold the canonical beside the ranked hit, and
        replacing that hit would leave it reachable from no ``offset`` of a
        one-row walk: the resume point after it is 1, and offset 0 is this
        page again. So the splice yields."""
        server = _server(climate_zim)
        ranked = _ranked(server, climate_zim, 1)

        page = await _page(server, climate_zim, limit=1)

        assert [r["path"] for r in page["results"]] == ranked
        assert page["page_info"]["next_offset"] == 1

    @pytest.mark.asyncio
    async def test_the_cached_page_is_the_same_page(self, climate_zim: Path) -> None:
        """Cache enabled: the rebuilt page reads cached search pages, and the
        warm call must serve the same bounded page."""
        server = _server(climate_zim, cache=True)

        cold = await _page(server, climate_zim, limit=2)
        warm = await _page(server, climate_zim, limit=2)

        for page in (cold, warm):
            assert len(page["results"]) == 2
            assert page["results"][0]["path"] == _CANONICAL
        assert warm["results"] == cold["results"]
        assert warm["page_info"] == cold["page_info"]
