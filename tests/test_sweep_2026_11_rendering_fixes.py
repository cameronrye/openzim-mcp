"""Rendering regressions from the 2026-11 sweep: titles, links, footers, Unicode.

Each class pins one defect that reproduced against ``main`` at e945188 and
names the inputs that exposed it.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import pytest
from libzim.writer import Creator

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer
from tests.conftest_v2_fixtures import _HtmlItem


def _build_zim(path: Path, pages: Iterable[Tuple[str, str, str]]) -> Path:
    """Write ``(entry path, stored title, html)`` pages into an indexed ZIM."""
    pages = list(pages)
    with Creator(path).config_indexing(True, "eng") as creator:
        for entry_path, title, html in pages:
            creator.add_item(_HtmlItem(entry_path, title, html))
        creator.set_mainpath(pages[0][0])
    return path


def _server(
    directory: Path, tool_mode: str = "advanced", *, cache: bool = True
) -> OpenZimMcpServer:
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(directory)],
            tool_mode=tool_mode,
            cache=CacheConfig(enabled=cache),
        )
    )


async def _call(server: OpenZimMcpServer, tool: str, **arguments: Any) -> Any:
    """Invoke a registered tool the way the SDK dispatches it."""
    return await server.mcp._tool_manager._tools[tool].fn(**arguments)


class TestImageOnlyH1KeepsTheStoredTitle:
    """An image-only ``<h1>`` renamed the search row after the first sentence.

    The heading renders as ``# `` and a blank line, and ``leading_h1``'s
    ``#\\s+`` matched the newlines too, so the "heading" it read was the
    lead paragraph. ``completed_title`` then saw the stored title "Aspirin"
    as a prefix of "Aspirin is a medication used to…" and swapped it in.
    """

    @pytest.fixture
    def archive(self, tmp_path: Path) -> Path:
        return _build_zim(
            tmp_path / "titles.zim",
            [
                (
                    "A/Aspirin",
                    "Aspirin",
                    '<html><body><h1><img src="logo.png" alt=""></h1>'
                    "<p>Aspirin is a medication used to reduce pain, fever, "
                    "or inflammation.</p></body></html>",
                ),
                (
                    "A/Alzheimer",
                    "Alzheimer",
                    "<html><body><h1>Alzheimer&#x27;s Disease</h1>"
                    "<p>Alzheimer medication can slow the decline for a time."
                    "</p></body></html>",
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_search_row_title_is_not_the_lead_sentence(
        self, archive: Path
    ) -> None:
        server = _server(archive.parent)
        # The completion reads the snippet render out of the cache, so the
        # second call is the one a warm server answers from cached rows.
        for _ in range(2):
            result = await _call(
                server, "zim_search", query="medication", zim_file_path=str(archive)
            )
            titles: Dict[str, str] = {r["path"]: r["title"] for r in result["results"]}
            assert titles.get("A/Aspirin") == "Aspirin", titles
            # A real truncated title next to it is still completed.
            assert titles.get("A/Alzheimer") == "Alzheimer's Disease", titles


class TestCursorQueryContinuityReadsEveryScript:
    """A replayed search cursor was refused whenever its query left ASCII.

    The continuity check tokenised with ``[a-z0-9]+`` and folded nothing:
    "Москва 2020" kept only ``2020``, "Zürich" became ``rich``, and an
    all-Cyrillic query had no tokens at all and fell back to a substring
    test that reordered words fail, and that fallback compared unfolded
    text. Each replay below names the same topic as the cursor it carries.
    """

    @pytest.fixture
    def archive(self, tmp_path: Path) -> Path:
        topics = ("история", "культура", "транспорт")
        return _build_zim(
            tmp_path / "cyrillic.zim",
            [
                (
                    f"A/Moscow_{i}",
                    f"Moscow {i}",
                    f"<html><body><h1>Moscow {i}</h1><p>Москва 2020 Zürich ёж "
                    f"Москва культура {topic} города.</p></body></html>",
                )
                for i, topic in enumerate(topics)
            ]
            + [
                (
                    "A/Paris",
                    "Paris",
                    "<html><body><h1>Paris</h1><p>Париж 2020.</p></body></html>",
                )
            ],
        )

    @staticmethod
    def _cursor(server: OpenZimMcpServer, archive: Path, query: str) -> str:
        """The continuation cursor the search data layer mints for page 1."""
        page = server.zim_operations.search_zim_file_data(str(archive), query, limit=1)
        cursor = page["next_cursor"]
        assert cursor, page
        return str(cursor)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "issued_for, replayed_as",
        [
            ("Москва 2020", "search for Москва"),
            ("Zürich", "search for Zurich"),
            ("Москва культура", "search for культура Москва"),
            # Too short for a token: the substring fallback must fold too.
            ("ёж", "search for еж"),
        ],
    )
    async def test_a_same_topic_replay_reads_page_two(
        self, archive: Path, issued_for: str, replayed_as: str
    ) -> None:
        server = _server(archive.parent, "simple", cache=False)
        cursor = self._cursor(server, archive, issued_for)

        out = await _call(
            server,
            "zim_query",
            query=replayed_as,
            zim_file_path=str(archive),
            cursor=cursor,
        )

        assert not isinstance(out, dict), out
        assert "showing 2-2" in str(out), out

    @pytest.mark.asyncio
    async def test_a_different_topic_is_still_refused(self, archive: Path) -> None:
        server = _server(archive.parent, "simple", cache=False)
        cursor = self._cursor(server, archive, "Москва 2020")

        out = await _call(
            server,
            "zim_query",
            query="search for Париж",
            zim_file_path=str(archive),
            cursor=cursor,
        )

        assert isinstance(out, dict) and out.get("operation") == "cursor_decode", out
        assert "shares no terms" in out["message"], out


class TestSectionTitleMatchIgnoresUnicodeForm:
    """A composed section title missed the same heading stored decomposed.

    IEP stores "d. Al-Ghazālī and Descartes" in NFD while a caller types
    NFC. The two render identically and compared unequal, so both section
    surfaces answered "not found" — simple mode's with a "Did you mean"
    naming a heading that looked exactly like the request.
    """

    _COMPOSED = unicodedata.normalize("NFC", "d. Al-Ghazālī and Descartes")

    @pytest.fixture
    def archive(self, tmp_path: Path) -> Path:
        heading = unicodedata.normalize("NFD", self._COMPOSED)
        assert heading != self._COMPOSED
        html = (
            "<html><body><h1>Al-Ghazali</h1><p>Lead paragraph.</p>"
            "<h2>c. Resolution of Skepticism</h2>"
            "<p>A light from God resolves the doubt.</p>"
            f"<h2>{heading}</h2>"
            "<p>Both philosophers doubted the senses.</p></body></html>"
        )
        return _build_zim(tmp_path / "nfd.zim", [("A/Al-Ghazali", "Al-Ghazali", html)])

    @pytest.mark.asyncio
    async def test_zim_get_section_resolves_the_composed_title(
        self, archive: Path
    ) -> None:
        server = _server(archive.parent, cache=False)

        out = await _call(
            server,
            "zim_get_section",
            zim_file_path=str(archive),
            entry_path="A/Al-Ghazali",
            section_id=self._COMPOSED,
        )

        assert not out.get("error"), out
        assert "Both philosophers doubted the senses." in out["content_markdown"], out
        assert "A light from God" not in out["content_markdown"], out

    @pytest.mark.asyncio
    async def test_simple_section_query_resolves_the_composed_title(
        self, archive: Path
    ) -> None:
        server = _server(archive.parent, "simple", cache=False)

        out = str(
            await _call(
                server,
                "zim_query",
                query=f"section {self._COMPOSED} of A/Al-Ghazali",
                zim_file_path=str(archive),
            )
        )

        assert "Both philosophers doubted the senses." in out, out
        assert "not found" not in out, out
        assert "A light from God" not in out, out
