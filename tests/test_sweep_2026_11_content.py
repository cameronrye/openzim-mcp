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


def _without_meta(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if k != "_meta"}


class TestPercentEncodedPathsResolveOnEverySurface:
    """Only ``view="full"`` served the percent-encoded spelling of a path.

    ``A/K%C3%B6ppen_climate_classification`` is how mini's own main page links
    the article, and ``view="full"`` serves it through the ladder's exact probe
    on the decoded spelling. Three other lookups skipped that probe — the
    bundle's (toc, structure, section, outbound links), the summary's and the
    binary fetch's — and answered Resource Not Found. For an image the text
    view's own advice, "fetch it with zim_get(…, binary=True)", then failed.
    """

    _ENCODED = "A/K%C3%B6ppen_climate_classification"
    _RAW = "A/Köppen_climate_classification"
    _IMAGE_ENCODED = "I/Koppen-Geiger_Map_v2_World_1991%E2%80%932020.svg.png.webp"
    _IMAGE_RAW = "I/Koppen-Geiger_Map_v2_World_1991–2020.svg.png.webp"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("view", ["summary", "toc", "structure"])
    async def test_structure_views_serve_the_encoded_spelling(
        self, climate_zim: Path, view: str
    ) -> None:
        zim_get = _tool(_server(climate_zim.parent), "zim_get")
        base = {"zim_file_path": str(climate_zim), "view": view}

        encoded = await zim_get(**base, entry_path=self._ENCODED)
        raw = await zim_get(**base, entry_path=self._RAW)

        assert not encoded.get("error"), encoded
        assert encoded["path"] == self._RAW
        assert _without_meta(encoded) == _without_meta(raw)

    @pytest.mark.asyncio
    async def test_get_section_serves_the_encoded_spelling(
        self, climate_zim: Path
    ) -> None:
        server = _server(climate_zim.parent)
        toc = await _tool(server, "zim_get")(
            zim_file_path=str(climate_zim), entry_path=self._RAW, view="toc"
        )
        section_id = toc["toc"][0]["section_id"]
        get_section = _tool(server, "zim_get_section")
        base = {"zim_file_path": str(climate_zim), "section_id": section_id}

        encoded = await get_section(**base, entry_path=self._ENCODED)
        raw = await get_section(**base, entry_path=self._RAW)

        assert not encoded.get("error"), encoded
        assert encoded["entry_path"] == self._RAW
        assert "Köppen climate classification" in encoded["content_markdown"]
        assert _without_meta(encoded) == _without_meta(raw)

    @pytest.mark.asyncio
    async def test_outbound_links_serve_the_encoded_spelling(
        self, climate_zim: Path
    ) -> None:
        zim_links = _tool(_server(climate_zim.parent), "zim_links")
        base = {"zim_file_path": str(climate_zim), "direction": "outbound"}

        encoded = await zim_links(**base, entry_path=self._ENCODED)
        raw = await zim_links(**base, entry_path=self._RAW)

        assert not encoded.get("error"), encoded
        assert encoded["results"], encoded
        assert encoded["results"] == raw["results"]

    @pytest.mark.asyncio
    async def test_binary_fetch_the_text_view_recommends_now_works(
        self, climate_zim: Path
    ) -> None:
        zim_get = _tool(_server(climate_zim.parent), "zim_get")
        base = {"zim_file_path": str(climate_zim)}

        advice = await zim_get(**base, entry_path=self._IMAGE_ENCODED)
        binary = await zim_get(**base, entry_path=self._IMAGE_ENCODED, binary=True)
        raw = await zim_get(**base, entry_path=self._IMAGE_RAW, binary=True)

        assert "binary=True" in advice["content"], advice
        assert not binary.get("error"), binary
        assert binary["path"] == self._IMAGE_RAW
        assert binary["mime_type"] == "image/webp"
        assert binary["data"] and binary["data"] == raw["data"]
