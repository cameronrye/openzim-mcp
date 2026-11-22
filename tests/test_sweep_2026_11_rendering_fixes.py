"""Rendering regressions from the 2026-11 sweep: titles, links, footers, Unicode.

Each class pins one defect that reproduced against ``main`` at e945188 and
names the inputs that exposed it.
"""

from __future__ import annotations

import ast
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

import pytest
from libzim.writer import Creator

from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    OpenZimMcpConfig,
    SynthesizeConfig,
)
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


class TestRewindowedSnippetKeepsItsLeadIn:
    """A snippet slid to its first hit threw away the lead-in it made room for.

    The window opens ``lead`` characters before the hit and then snaps to a
    word boundary, but with ``rfind``, the space right before the hit, so
    "...word599 the recommended aspirin dose" came out as "...aspirin dose
    for adults". The ``...`` that marks the cut also kept synthesize from
    locating the passage in the article, so its citation lost the section it
    came from.
    """

    @pytest.fixture
    def archive(self, tmp_path: Path) -> Path:
        filler = " ".join(f"word{i}" for i in range(600))
        return _build_zim(
            tmp_path / "dosage.zim",
            [
                (
                    "A/Aspirin",
                    "Aspirin",
                    "<html><body><h1>Aspirin</h1>"
                    "<p>A common medicine kept in many homes.</p>"
                    f"<h2>Dosage</h2><p>{filler} the recommended aspirin dose "
                    "for adults is one tablet a day.</p></body></html>",
                ),
                (
                    "A/Other",
                    "Other",
                    "<html><body><h1>Other</h1><p>Nothing here.</p></body></html>",
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_search_snippet_reads_the_words_before_the_hit(
        self, archive: Path
    ) -> None:
        server = _server(archive.parent)
        for _ in range(2):  # the second page is served from the cache
            result = await _call(
                server, "zim_search", query="aspirin dose", zim_file_path=str(archive)
            )
            snippet = next(
                r["snippet"] for r in result["results"] if r["path"] == "A/Aspirin"
            )
            assert snippet.startswith("...word"), snippet
            assert "the recommended **aspirin** **dose** for adults" in snippet

    @pytest.mark.asyncio
    async def test_synthesize_cites_the_section_the_passage_came_from(
        self, archive: Path
    ) -> None:
        server = _server(archive.parent)
        for _ in range(2):
            result = await _call(
                server,
                "zim_query",
                query="what is the aspirin dose for adults",
                zim_file_path=str(archive),
                synthesize=True,
            )
            assert result["answer_markdown"].startswith("..."), result
            cited = {c["entry_path"]: c["section_id"] for c in result["citations"]}
            assert cited == {"A/Aspirin": "dosage"}, result["citations"]


class TestSynthesizeBudgetCutLeavesNoOpenBold:
    """The answer budget's cut could land inside a ``**bold**`` run.

    ``_enforce_budget`` sliced the last passage at the remaining budget and
    snapped to a space, which inside a bold run left its opening ``**``
    unclosed ("**Big Rapi"), so the rest of a rendered answer read as bold.
    """

    @pytest.fixture
    def archive(self, tmp_path: Path) -> Path:
        lead = " ".join(f"plain{i}" for i in range(30))
        bold = " ".join(f"bold{i}" for i in range(60))
        tail = " ".join(f"tail{i}" for i in range(40))
        return _build_zim(
            tmp_path / "rapids.zim",
            [
                (
                    "A/Big_Rapids",
                    "Big Rapids",
                    "<html><body><h1>Big Rapids</h1>"
                    f"<p>Big Rapids is a city in Michigan. {lead} <b>{bold}</b> "
                    f"{tail}</p></body></html>",
                ),
                (
                    "A/Other",
                    "Other",
                    "<html><body><h1>Other</h1><p>Nothing here.</p></body></html>",
                ),
            ],
        )

    @pytest.mark.asyncio
    async def test_the_cut_backs_off_to_before_the_bold_run(
        self, archive: Path
    ) -> None:
        server = OpenZimMcpServer(
            OpenZimMcpConfig(
                allowed_directories=[str(archive.parent)],
                tool_mode="advanced",
                cache=CacheConfig(enabled=False),
                content=ContentConfig(snippet_length=3000),
                synthesize=SynthesizeConfig(output_char_budget=500),
            )
        )

        result = await _call(
            server,
            "zim_query",
            query="big rapids city michigan",
            zim_file_path=str(archive),
            synthesize=True,
            limit=1,
        )

        passage = result["answer_markdown"].split("\n[cite: ")[0]
        assert passage.count("**") % 2 == 0, passage
        # The budget still bit, just before the run rather than inside it.
        assert passage.endswith("plain29"), passage
        assert passage.replace("**", "").startswith("Big Rapids is a city"), passage


@pytest.fixture
def climate_zim(real_content_zim_files: Dict[str, Optional[Path]]) -> Path:
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("wikipedia_climate ZIM fixture not available")
    return zim


class TestCompactLinkStripSurvivesASaturatedRegexPool:
    """A link-strip timeout cached a compact page with its links still in it.

    The strip ran in the shared 8-worker regex pool under a 1 s timeout and,
    on a timeout, returned the text unstripped while the payload still read
    as good. That page was then measured, paged and cached under the compact
    key: with the pool saturated, page 1 of ``A/Climate_change_in_the_Americas``
    (cap 1500) carried 14 links, ``total_chars`` 2062 and ``more_at_offset``
    1500, while page 2, once the pool was free, found a 941-char body with
    nothing past offset 1500.
    """

    @staticmethod
    async def _fetch_under_load(
        monkeypatch: pytest.MonkeyPatch, archive: Path, **arguments: Any
    ) -> Tuple[Any, Any, Any]:
        """``(unloaded, under_load, afterwards)`` compact pages of one entry.

        ``under_load`` is fetched while every strip call times out the way
        ``safe_regex_sub`` does when all regex workers are busy;
        ``afterwards`` repeats the request on the same caching server once
        the pool is free, so it is answered from the cache.
        """
        from openzim_mcp import compact_format
        from openzim_mcp.exceptions import RegexTimeoutError

        mixin = compact_format._CompactFormatMixin
        strip_patterns = (mixin._MARKDOWN_LINK_RE, mixin._MARKDOWN_IMAGE_RE)
        real = compact_format.safe_regex_sub

        def saturated(pattern: Any, *args: Any, **kwargs: Any) -> str:
            if pattern in strip_patterns:
                raise RegexTimeoutError("Regex operation timed out after 1.0 seconds")
            return real(pattern, *args, **kwargs)

        arguments = {"zim_file_path": str(archive), "compact": True, **arguments}
        unloaded = await _call(
            _server(archive.parent, cache=False), "zim_get", **arguments
        )
        server = _server(archive.parent)
        monkeypatch.setattr(compact_format, "safe_regex_sub", saturated)
        under_load = await _call(server, "zim_get", **arguments)
        monkeypatch.setattr(compact_format, "safe_regex_sub", real)
        afterwards = await _call(server, "zim_get", **arguments)
        return unloaded, under_load, afterwards

    @pytest.mark.asyncio
    async def test_a_pool_timeout_neither_ships_nor_caches_link_markup(
        self, climate_zim: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pages = await self._fetch_under_load(
            monkeypatch,
            climate_zim,
            entry_path="A/Climate_change_in_the_Americas",
            max_content_length=1500,
        )

        unloaded = pages[0]
        assert "Climate change in Canada" in unloaded["content"], unloaded
        for page in pages:
            assert "](" not in page["content"], page["content"][:400]
            assert page == unloaded

    @pytest.mark.asyncio
    async def test_image_markup_is_stripped_under_load_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """html2text drops ``<img>``, so only a text entry carries ``![]()``."""

        class _MarkdownItem(_HtmlItem):
            def get_mimetype(self) -> str:
                return "text/markdown"

        archive = tmp_path / "readme.zim"
        with Creator(archive).config_indexing(True, "eng") as creator:
            creator.add_item(
                _MarkdownItem(
                    "A/Readme",
                    "Readme",
                    "See ![the logo](logo.png) and [the docs](docs.html) first.",
                )
            )
            creator.set_mainpath("A/Readme")

        pages = await self._fetch_under_load(
            monkeypatch, archive, entry_path="A/Readme"
        )

        for page in pages:
            assert page["content"] == "See  and the docs first.", page


def _body(content: str) -> str:
    """``content`` without the truncation footer ``truncate_content`` appends."""
    return content.split("\n\n... [Content truncated, ")[0]


class TestMainPageStripsCompactLinks:
    """``zim_get(main_page=True, compact=True)`` skipped the compact link strip.

    The path fetch strips link markup before it measures; the main-page
    builder never did. On mini the main page shipped "[ ](Antarctica)
    [ ](Precipitation)…" and reported 1,945 total chars, while the same entry
    fetched by path is 199 characters of whitespace once its image links are
    gone.
    """

    @pytest.mark.asyncio
    async def test_an_all_link_main_page_says_it_has_no_content(
        self, climate_zim: Path
    ) -> None:
        server = _server(climate_zim.parent)
        for _ in range(2):  # the second page is served from the cache
            page = await _call(
                server,
                "zim_get",
                zim_file_path=str(climate_zim),
                main_page=True,
                compact=True,
                max_content_length=400,
            )
            assert "](" not in page["content"], page["content"][:200]
            assert page["content"] == "(No content)", page
            assert page["_meta"]["truncated"] is False, page

        by_path = await _call(
            server,
            "zim_get",
            zim_file_path=str(climate_zim),
            entry_path=page["path"],
            compact=True,
        )
        # The path fetch agrees there is no text left to show.
        assert by_path["content"].strip() == "", by_path["content"][:200]

    @pytest.mark.asyncio
    async def test_the_main_page_measures_what_the_path_fetch_measures(
        self, tmp_path: Path
    ) -> None:
        links = " ".join(
            f'<a href="Topic_{i}" title="Topic {i}">Topic {i}</a>' for i in range(20)
        )
        archive = _build_zim(
            tmp_path / "portal.zim",
            [
                (
                    "A/Portal",
                    "Portal",
                    "<html><body><h1>Portal</h1>"
                    f"<p>Welcome to the portal. Start with {links}.</p>"
                    "</body></html>",
                )
            ],
        )
        server = _server(archive.parent, cache=False)
        base = {"zim_file_path": str(archive), "compact": True}

        main = await _call(
            server, "zim_get", main_page=True, max_content_length=120, **base
        )
        by_path = await _call(
            server, "zim_get", entry_path="A/Portal", max_content_length=120, **base
        )

        assert main["path"] == "A/Portal", main
        assert "](" not in main["content"], main["content"]
        assert "Topic 0 Topic 1" in main["content"], main["content"]
        assert main["_meta"]["truncated"] is True, main
        assert main["_meta"]["total_chars"] == by_path["_meta"]["total_chars"]
        assert _body(main["content"]) == _body(by_path["content"])


_TRUNCATION_RE = re.compile(
    r"\n\n\.\.\. \[Content truncated, (?P<note>.*)\] \.\.\.$", re.S
)


def _split_page(content: str) -> Tuple[str, str]:
    """``(body, footer note)`` of one served page; the note is ``""`` if whole."""
    match = _TRUNCATION_RE.search(content)
    if match is None:
        return content, ""
    return content[: match.start()], match.group("note")


def _footer_arguments(note: str) -> Dict[str, Any]:
    """Every backticked ``name=value`` the footer tells the caller to pass."""
    return {
        name: ast.literal_eval(value)
        for name, value in re.findall(r"`(\w+)=([^`]+)`", note)
    }


def _footer_request(note: str) -> Optional[str]:
    """The ``zim_query`` request a simple-mode footer quotes, if any."""
    match = re.search(r"ask for `([^`]+)`", note)
    return match.group(1) if match else None


def _simple_body(text: str) -> str:
    """The article body of a simple-mode ``get article`` / ``main page`` reply."""
    assert "## Content\n\n" in text, text[:500]
    return text.split("## Content\n\n", 1)[1].rsplit("\n<!-- intent=", 1)[0]


def _simple_json(text: str) -> Any:
    """The JSON document a simple-mode batch reply carries."""
    return json.JSONDecoder().raw_decode(text[text.index("{") :])[0]


class TestContinuationFootersAreFollowable:
    """Every truncation footer must name a call that resumes where its page ended.

    The batch footer read "re-fetch this path with a single-entry
    `entry_path` call and `content_offset=800`" in either mode. In advanced
    mode it left out ``compact``, so following it with zim_get's default
    ``compact=False`` resumed in a different rendering (about 300 chars off
    on a compact Kyoto batch). In simple mode it named an ``entry_path``
    argument zim_query rejects as ``unknown_argument``. The main page told
    advanced callers to "switch to `get article`", which is simple-mode
    vocabulary, and gave no offset at all.

    Each test below does exactly what a footer says and nothing more, then
    checks that the two pages join into the start of the whole body.
    """

    _BATCH = ["A/Kyoto_Protocol", "A/Climate_change"]

    @pytest.fixture
    def portal(self, tmp_path: Path) -> Path:
        # Long enough that even the simple surface's 5,000-char main-page
        # cap truncates it once the links are stripped.
        links = " ".join(
            f'<a href="Topic_{i}" title="Topic {i}">Topic {i}</a>' for i in range(700)
        )
        return _build_zim(
            tmp_path / "portal.zim",
            [
                (
                    "A/Portal",
                    "Portal",
                    "<html><body><h1>Portal</h1>"
                    f"<p>Welcome to the portal. Start with {links}.</p>"
                    "</body></html>",
                )
            ],
        )

    @staticmethod
    def _whole_body(archive: Path, entry_path: str, compact: bool) -> str:
        server = _server(archive.parent, cache=False)
        return str(
            server.zim_operations.get_zim_entry_data(
                str(archive), entry_path, 10**7, 0, compact=compact
            )["content"]
        )

    @staticmethod
    async def _first_page(server: OpenZimMcpServer, tool: str, **arguments: Any) -> Any:
        """The truncated page, fetched twice: the footer is cached with it."""
        page = await _call(server, tool, **arguments)
        assert await _call(server, tool, **arguments) == page
        return page

    @pytest.mark.asyncio
    @pytest.mark.parametrize("compact", [True, False])
    async def test_advanced_batch_footer(
        self, climate_zim: Path, compact: bool
    ) -> None:
        server = _server(climate_zim.parent)
        batch = await self._first_page(
            server,
            "zim_get",
            zim_file_path=str(climate_zim),
            entry_paths=self._BATCH,
            compact=compact,
            max_content_length=800,
        )
        item = batch["results"][0]
        first, note = _split_page(item["content"])
        assert "single-entry `entry_path` call" in note, note

        second = await _call(
            server,
            "zim_get",
            zim_file_path=str(climate_zim),
            entry_path=item["entry_path"],
            max_content_length=800,
            **_footer_arguments(note),
        )

        rest, _ = _split_page(second["content"])
        assert rest, second
        whole = self._whole_body(climate_zim, item["entry_path"], compact)
        assert whole.startswith(first + rest), (note, rest[:120])

    @pytest.mark.asyncio
    @pytest.mark.parametrize("compact", [True, False])
    async def test_simple_batch_footer(self, climate_zim: Path, compact: bool) -> None:
        server = _server(climate_zim.parent, "simple")
        batch = _simple_json(
            str(
                await self._first_page(
                    server,
                    "zim_query",
                    query="get articles " + ", ".join(self._BATCH),
                    zim_file_path=str(climate_zim),
                    compact=compact,
                    max_content_length=800,
                )
            )
        )
        item = batch["results"][0]
        first, note = _split_page(item["content"])
        request = _footer_request(note)
        assert request == f"get article {item['entry_path']}", note

        second = await _call(
            server,
            "zim_query",
            query=request,
            zim_file_path=str(climate_zim),
            max_content_length=800,
            **_footer_arguments(note),
        )

        assert not isinstance(second, dict), second
        rest, _ = _split_page(_simple_body(str(second)))
        assert rest, second
        whole = self._whole_body(climate_zim, item["entry_path"], compact)
        assert whole.startswith(first + rest), (note, rest[:120])

    @pytest.mark.asyncio
    @pytest.mark.parametrize("compact", [True, False])
    async def test_advanced_main_page_footer(self, portal: Path, compact: bool) -> None:
        server = _server(portal.parent)
        page = await self._first_page(
            server,
            "zim_get",
            zim_file_path=str(portal),
            main_page=True,
            compact=compact,
            max_content_length=300,
        )
        first, note = _split_page(page["content"])
        arguments = _footer_arguments(note)
        assert arguments.get("entry_path") == page["path"], note

        second = await _call(
            server,
            "zim_get",
            zim_file_path=str(portal),
            max_content_length=300,
            **arguments,
        )

        rest, _ = _split_page(second["content"])
        assert rest, second
        whole = self._whole_body(portal, page["path"], compact)
        assert whole.startswith(first + rest), (note, rest[:120])

    @pytest.mark.asyncio
    @pytest.mark.parametrize("compact", [True, False])
    async def test_simple_main_page_footer(self, portal: Path, compact: bool) -> None:
        server = _server(portal.parent, "simple")
        page = str(
            await self._first_page(
                server,
                "zim_query",
                query="main page",
                zim_file_path=str(portal),
                compact=compact,
            )
        )
        first, note = _split_page(_simple_body(page))
        request = _footer_request(note)
        assert request == "get article A/Portal", note

        second = await _call(
            server,
            "zim_query",
            query=request,
            zim_file_path=str(portal),
            **_footer_arguments(note),
        )

        assert not isinstance(second, dict), second
        rest, _ = _split_page(_simple_body(str(second)))
        assert rest, second
        whole = self._whole_body(portal, "A/Portal", compact)
        assert whole.startswith(first + rest), (note, rest[:120])
