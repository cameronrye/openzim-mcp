"""Regressions from the 2026-11 sweep's content cluster.

Each class pins one defect that reproduced against ``main`` at e945188 —
infoboxes, entry-path resolution, TOC ids and silent article substitution —
and drives the registered tools end to end on real archives: the climate
``mini`` fixture where it shows the defect, and small archives built here
where the shape has to be exact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.rate_limiter import RateLimitConfig
from openzim_mcp.server import OpenZimMcpServer


@pytest.fixture
def climate_zim(real_content_zim_files: Dict[str, Optional[Path]]) -> Path:
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("wikipedia_climate ZIM fixture not available")
    return zim


def _server(directory: Path, *, cache: bool = False) -> OpenZimMcpServer:
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(directory)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=cache, persistence_enabled=False),
            rate_limit=RateLimitConfig(enabled=False),
        )
    )


def _tool(server: OpenZimMcpServer, name: str) -> Callable[..., Any]:
    return server.mcp._tool_manager._tools[name].fn


class TestZimGetRejectsTraversalLikeItsSiblings:
    """``zim_get(view="full")`` skipped the path-traversal guard.

    ``get_zim_entry_data`` never called ``reject_path_traversal``, so
    ``../Hydrogen`` reached the search fallback, whose matcher drops the first
    segment and served ``A/Hydrogen`` — while ``view="toc"``, the summary, the
    binary fetch and the legacy text ``get_zim_entry`` all answered "Rejected
    suspicious entry path" for the same argument.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "entry_path",
        # The first two were served as A/Hydrogen; the rest answered
        # not-found, which is the wrong verdict for a traversal shape.
        [
            "../Hydrogen",
            "%2e%2e/Hydrogen",
            "A/../Hydrogen",
            "..%2FHydrogen",
            "..\\Hydrogen",
        ],
    )
    async def test_full_view_rejects_what_the_other_views_reject(
        self, climate_zim: Path, entry_path: str
    ) -> None:
        zim_get = _tool(_server(climate_zim.parent), "zim_get")
        args = {"zim_file_path": str(climate_zim), "entry_path": entry_path}

        full = await zim_get(**args)
        toc = await zim_get(**args, view="toc")

        assert "content" not in full, full
        assert "Rejected suspicious entry path" in full["message"], full
        # The sibling verdict this surface now agrees with.
        assert "Rejected suspicious entry path" in toc["message"], toc

    @pytest.mark.asyncio
    async def test_real_and_slashed_paths_are_still_served(
        self, climate_zim: Path
    ) -> None:
        """The guard runs on the un-rooted spelling, as every sibling's does,
        so a client's leading slash is still a slip to recover from — and the
        payload still marks that rewrite with ``requested_path`` (D17)."""
        zim_get = _tool(_server(climate_zim.parent), "zim_get")

        plain = await zim_get(zim_file_path=str(climate_zim), entry_path="A/Hydrogen")
        slashed = await zim_get(
            zim_file_path=str(climate_zim), entry_path="/A/Hydrogen"
        )

        assert plain["path"] == "A/Hydrogen", plain
        assert "chemical element" in plain["content"]
        assert slashed["path"] == "A/Hydrogen", slashed
        assert slashed["requested_path"] == "/A/Hydrogen"
        assert slashed["content"] == plain["content"]
