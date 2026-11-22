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


def _build_zim(directory: Path, pages: Dict[str, str]) -> Path:
    """One small archive of ``{path: html}`` pages, titled by the path."""
    from libzim.writer import Creator

    from tests.conftest_v2_fixtures import _HtmlItem

    out = directory / "fixture.zim"
    with Creator(out).config_indexing(True, "eng") as creator:
        for path, html in pages.items():
            creator.add_item(_HtmlItem(path, path.replace("_", " "), html))
        creator.set_mainpath(next(iter(pages)))
    return out


# Long enough that the summary's 200-word cap ends inside the lead, so a
# second infobox further down can only reach the summary by being hoisted.
_PAT_LEAD = " ".join(["Pat Example is a retired baseball player."] * 40)

_TWO_INFOBOX_HTML = f"""<html><head><title>Pat Example</title></head><body>
<h1>Pat Example</h1>
<table class="infobox">
<tr><th colspan="2">Pat Example</th></tr>
<tr><th>Born</th><td>1 May 1970</td></tr>
<tr><th>Position</th><td>Pitcher</td></tr>
</table>
<p>{_PAT_LEAD}</p>
<h2>Career</h2>
<table class="infobox">
<tr><th colspan="2">Career statistics</th></tr>
<tr><th>Team</th><td>Yankees</td></tr>
<tr><th>Years</th><td>1990-1999</td></tr>
</table>
<p>Pat pitched for a decade.</p>
<h2>Legacy</h2>
<p>Remembered fondly.</p>
</body></html>"""


class TestSummaryLeadsWithTheArticlesOwnInfobox:
    """The bundle lifted infobox #1, then its compact render lifted again.

    ``extract_entry_bundle`` extracted the first infobox into
    ``bundle["infobox"]`` — a field no tool reads — and decomposed it; the
    compact render then ran ``extract_infobox`` a second time, found the NEXT
    infobox and prepended it. So mini's Kyoto Protocol summary opened with the
    Doha Amendment's "Location: Doha, Qatar" while ``view="full",
    compact=True`` opened with "Location: Kyoto, Japan", and a second infobox
    left the section it belongs to for the top of the summary.
    """

    @pytest.mark.asyncio
    async def test_kyoto_summary_opens_with_the_full_views_infobox(
        self, climate_zim: Path
    ) -> None:
        zim_get = _tool(_server(climate_zim.parent), "zim_get")
        base = {"zim_file_path": str(climate_zim), "entry_path": "A/Kyoto_Protocol"}

        summary = (await zim_get(**base, view="summary"))["summary"]
        full = (await zim_get(**base, compact=True))["content"]
        infobox_block = full.split("\n\n", 1)[0]

        assert infobox_block.startswith(
            "**Signed:** 11 December 1997\n**Location:** Kyoto, Japan"
        ), infobox_block
        assert summary.startswith(infobox_block), summary[:400]
        assert "**Location:** Doha, Qatar" not in summary

    @pytest.mark.asyncio
    async def test_a_second_infobox_stays_in_its_own_section(
        self, tmp_path: Path
    ) -> None:
        zim = _build_zim(tmp_path, {"Pat_Example": _TWO_INFOBOX_HTML})
        server = _server(tmp_path)
        base = {"zim_file_path": str(zim), "entry_path": "Pat_Example"}

        summary = (await _tool(server, "zim_get")(**base, view="summary"))["summary"]
        full = (await _tool(server, "zim_get")(**base, compact=True))["content"]
        career = await _tool(server, "zim_get_section")(**base, section_id="career")

        assert summary.startswith("**Born:** 1 May 1970\n**Position:** Pitcher")
        assert "**Team:**" not in summary
        assert "Yankees" in career["content_markdown"], career
        # The section is the full view's own slice, table and all.
        assert career["content_markdown"].strip() in full

    @pytest.mark.asyncio
    async def test_a_cached_summary_is_the_corrected_one(
        self, climate_zim: Path
    ) -> None:
        zim_get = _tool(_server(climate_zim.parent, cache=True), "zim_get")
        args = {
            "zim_file_path": str(climate_zim),
            "entry_path": "A/Kyoto_Protocol",
            "view": "summary",
        }

        cold = await zim_get(**args)
        warm = await zim_get(**args)

        assert cold["summary"].startswith("**Signed:** 11 December 1997")
        assert warm["summary"] == cold["summary"]

    def test_the_bundle_field_holds_the_rows_it_rendered(self, tmp_path: Path) -> None:
        """No tool reads ``bundle["infobox"]``, so pin it here: it must be the
        infobox the render prepended, not empty and not a second lift."""
        from libzim.reader import Archive

        from openzim_mcp.bundle import extract_entry_bundle
        from openzim_mcp.content_processor import ContentProcessor

        zim = _build_zim(tmp_path, {"Pat_Example": _TWO_INFOBOX_HTML})
        bundle = extract_entry_bundle(
            Archive(str(zim)), "Pat_Example", content_processor=ContentProcessor()
        )

        assert bundle["infobox"] == {
            "fields": [
                {"label": "Born", "value": "1 May 1970"},
                {"label": "Position", "value": "Pitcher"},
            ]
        }
        assert bundle["rendered_markdown"].startswith("**Born:** 1 May 1970")

    @pytest.mark.asyncio
    async def test_an_infobox_that_fails_to_parse_does_not_fail_the_views(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The degrade-to-None guard the bundle documents never covered a
        compact bundle: the render's own extraction raised on the same node.
        One extraction, guarded where it runs, covers every compact view."""
        from openzim_mcp import content_processor

        def _explode(_cell: Any) -> str:
            raise RecursionError("maximum recursion depth exceeded")

        monkeypatch.setattr(content_processor, "_join_cell_text", _explode)
        zim = _build_zim(tmp_path, {"Pat_Example": _TWO_INFOBOX_HTML})
        zim_get = _tool(_server(tmp_path), "zim_get")
        base = {"zim_file_path": str(zim), "entry_path": "Pat_Example"}

        summary = await zim_get(**base, view="summary")
        toc = await zim_get(**base, view="toc")
        full = await zim_get(**base, compact=True)

        assert not summary.get("error"), summary
        assert "retired baseball player" in summary["summary"]
        assert [h["section_id"] for h in toc["toc"][0]["children"]] == [
            "career",
            "legacy",
        ], toc
        assert "retired baseball player" in full["content"]
        assert not full["content"].startswith("(Error"), full["content"][:200]


def _field_box_html(fields: int) -> str:
    rows = "".join(
        f"<tr><th>Field{i}</th><td>Value{i}</td></tr>" for i in range(fields)
    )
    return (
        "<html><body><h1>Field Box</h1>"
        f"<table class='infobox'>{rows}</table>"
        "<p>Field Box is an article whose infobox runs long.</p></body></html>"
    )


class TestCompactInfoboxSaysWhatTheCapLeftOut:
    """Compact mode cut an infobox at ``infobox_kv_limit`` (30) silently.

    ``extract_infobox`` stopped at the cap and the whole table was then
    decomposed, so mini's Hydrogen lost "CAS Number 12385-13-6", "Discovery:
    Henry Cavendish (1766)" and "Named by … Lavoisier" with ``_meta.truncated``
    false and nothing in the body — on ``zim_query``'s default ``compact=True``
    too. The table placeholder already says how to get a cut table back; the
    infobox now says the same.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fields, marker",
        [
            (31, "[Infobox: 1 more field - pass compact=False to expand]"),
            (40, "[Infobox: 10 more fields - pass compact=False to expand]"),
        ],
    )
    async def test_the_rows_past_the_cap_are_counted(
        self, tmp_path: Path, fields: int, marker: str
    ) -> None:
        zim = _build_zim(tmp_path, {"Field_Box": _field_box_html(fields)})
        zim_get = _tool(_server(tmp_path), "zim_get")
        base = {"zim_file_path": str(zim), "entry_path": "Field_Box"}

        compact = (await zim_get(**base, compact=True))["content"]
        raw = (await zim_get(**base, compact=False))["content"]

        assert "**Field29:** Value29" in compact
        assert "**Field30:**" not in compact
        assert f"**Field29:** Value29\n{marker}\n" in compact, compact[:2000]
        # The advice is true: the uncompacted view carries the fields it names.
        assert f"Value{fields - 1}" in raw

    @pytest.mark.asyncio
    async def test_an_infobox_at_the_cap_gets_no_marker(self, tmp_path: Path) -> None:
        zim = _build_zim(tmp_path, {"Field_Box": _field_box_html(30)})
        zim_get = _tool(_server(tmp_path), "zim_get")

        compact = (
            await zim_get(zim_file_path=str(zim), entry_path="Field_Box", compact=True)
        )["content"]

        assert "**Field29:** Value29" in compact
        assert "[Infobox:" not in compact

    @pytest.mark.asyncio
    async def test_zim_query_default_compact_carries_the_marker(
        self, tmp_path: Path
    ) -> None:
        zim = _build_zim(tmp_path, {"Field_Box": _field_box_html(40)})
        zim_query = _tool(_server(tmp_path), "zim_query")

        out = await zim_query(query="get article Field_Box", zim_file_path=str(zim))

        assert "**Field29:** Value29" in out
        assert "[Infobox: 10 more fields - pass compact=False to expand]" in out

    @pytest.mark.asyncio
    async def test_mini_hydrogen_names_its_three_dropped_fields(
        self, climate_zim: Path
    ) -> None:
        zim_get = _tool(_server(climate_zim.parent), "zim_get")
        base = {
            "zim_file_path": str(climate_zim),
            "entry_path": "A/Hydrogen",
            "max_content_length": 200_000,
        }

        compact = (await zim_get(**base, compact=True))["content"]
        raw = (await zim_get(**base, compact=False))["content"]

        assert "[Infobox: 3 more fields - pass compact=False to expand]" in compact
        assert "12385-13-6" not in compact
        assert "12385-13-6" in raw
        assert "Henry Cavendish (1766)" in raw
