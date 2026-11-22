"""Regressions from the 2026-11 sweep of error envelopes, argument handling,
advice, prompts and resources.

Each class pins one defect that reproduced against ``main`` at e945188 and
names the inputs that exposed it. Every test drives a real client session,
or the simple-mode handler end to end, in the mode the defect lives in.
"""

from __future__ import annotations

import json
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Optional

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer
from tests.test_mcp_session import _connected_client, _text

_MINI = "wikipedia_en_climate_change_mini_2024-06.zim"
# 40 bytes: carries the extension, fails to open ("too small to contain a
# header").
_BAD = "invalid.smaller_than_header.zim"


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


class TestEmptySynthesizeQuery:
    """``{"query": "", "synthesize": true}`` came back as a 0-hit success.

    The synthesize branch ran before the empty-query guard, so the empty
    string was searched and the response was an ``isError=false`` briefing
    with ``reason="0_hits"`` — while the same query without ``synthesize``
    was already the ``query_required`` error.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("query", ["", "   "])
    async def test_empty_query_is_query_required_in_both_branches(
        self, withns: Path, query: str
    ) -> None:
        async with _session(withns, "simple") as session:
            synth = await _call(
                session, "zim_query", {"query": query, "synthesize": True}
            )
            plain = await _call(session, "zim_query", {"query": query})

        for is_error, text, body in (synth, plain):
            assert is_error is True, text
            assert body["operation"] == "query_required", body
            assert body["invalid_arguments"] == ["query"], body

    @pytest.mark.asyncio
    async def test_a_real_query_still_synthesizes(self, withns: Path) -> None:
        """Positive pair: the guard must not swallow the synthesize branch."""
        async with _session(withns, "simple") as session:
            is_error, text, body = await _call(
                session,
                "zim_query",
                {
                    "query": "carbon tax",
                    "synthesize": True,
                    "zim_file_path": str(withns / _MINI),
                },
            )

        assert is_error is not True, text
        assert body["answer_markdown"], body
        assert body["citations"], body


class TestSynthesizeRefusesSizeArguments:
    """``synthesize=True`` accepted ``compact_budget`` / ``max_content_length``
    and ignored them.

    ``compact_budget="tiny"`` is documented as a hard 2,000-char cap; with
    ``synthesize=True`` it came back as a 7,816-char payload, byte-identical
    to the call without it. The pipeline has no knob either argument maps
    onto, so it is refused the way ``offset`` and ``cursor`` already are.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "extra, named",
        [
            ({"compact_budget": "tiny"}, ["compact_budget"]),
            ({"compact_budget": 500}, ["compact_budget"]),
            ({"max_content_length": 200}, ["max_content_length"]),
            (
                {"compact_budget": "tiny", "max_content_length": 200},
                ["compact_budget", "max_content_length"],
            ),
        ],
    )
    async def test_size_arguments_are_refused(
        self, withns: Path, extra: Dict[str, Any], named: list
    ) -> None:
        base = {
            "query": "tell me about carbon tax",
            "zim_file_path": str(withns / _MINI),
        }
        async with _session(withns, "simple") as session:
            is_error, text, body = await _call(
                session, "zim_query", {**base, "synthesize": True, **extra}
            )
            # Positive pairs: synthesize alone still answers, and the same
            # arguments are honoured on the path that has a budget to apply.
            synth_error, synth_text, _ = await _call(
                session, "zim_query", {**base, "synthesize": True}
            )
            plain_error, plain_text, _ = await _call(
                session, "zim_query", {**base, **extra}
            )

        assert is_error is True, text[:300]
        assert body["operation"] == "invalid_combination", body
        for name in named:
            assert f"`{name}`" in body["message"], body
        assert "synthesize=True" in body["message"], body
        assert synth_error is not True, synth_text[:300]
        assert plain_error is not True, plain_text[:300]
        if "compact_budget" in extra and extra["compact_budget"] == "tiny":
            assert len(plain_text) < 2_500, len(plain_text)


def _embedded_json(text: str) -> Dict[str, Any]:
    """The JSON object inside a (possibly fenced, footered) response."""
    return json.loads(text[text.index("{") : text.rfind("}") + 1])


_CLAMP_NOTE = "exceeds this operation's maximum of 50"


class TestLimitPastTheFiftyCapIsClamped:
    """``limit`` 51..1000 sank ``suggestions for`` and ``search all files``.

    ``zim_query`` documents 1..1000, both backends stop at 50, and neither
    handler reconciled the two: the call came back as the generic "Error
    Processing Query" telling the client to "check server logs", with a
    traceback logged at ERROR. ``links in`` and ``articles related to``
    already clamp and say so.
    """

    @pytest.mark.asyncio
    async def test_suggestions_clamp_and_say_so_inside_the_json(
        self, withns: Path
    ) -> None:
        base = {"query": "suggestions for clim", "zim_file_path": str(withns / _MINI)}
        async with _session(withns, "simple") as session:
            is_error, text, _ = await _call(
                session, "zim_query", {**base, "limit": 100}
            )
            _, wide, _ = await _call(
                session, "zim_query", {**base, "limit": 100, "compact": False}
            )
            ok_error, ok_text, _ = await _call(
                session, "zim_query", {**base, "limit": 50}
            )

        assert is_error is not True, text[:300]
        assert "Error Processing Query" not in text
        # The body is still JSON — the compact cap shrinks it structurally —
        # and the clamp is stated inside it rather than after the brace.
        payload = _embedded_json(text)
        assert payload["results"], payload
        assert len(payload["results"]) <= 50
        assert "`limit=100`" in payload["note"], payload
        assert _CLAMP_NOTE in payload["note"], payload
        # The added key is counted in the size the payload reports.
        uncapped = _embedded_json(wide)
        body = {k: v for k, v in uncapped.items() if k != "_meta"}
        assert uncapped["_meta"]["chars"] == len(json.dumps(body, ensure_ascii=False))
        # Positive pair: an in-range limit carries no note.
        assert ok_error is not True, ok_text[:300]
        assert "note" not in _embedded_json(ok_text)

    @pytest.mark.asyncio
    async def test_suggestions_note_never_reaches_the_cached_page(
        self, withns: Path
    ) -> None:
        """The data layer caches the page under the clamped limit, which an
        in-range ``limit=50`` call then reads back; the note must ride on a
        copy, or it leaks into every later answer for that prefix."""
        base = {"query": "suggestions for clim", "zim_file_path": str(withns / _MINI)}
        # ``compact=False`` keeps the size cap out of the comparison, so the
        # in-range page is compared whole, ``_meta`` included.
        exact = {**base, "limit": 50, "compact": False}
        async with _session(withns, "simple", cache=True) as session:
            _, before, _ = await _call(session, "zim_query", exact)
            _, clamped, _ = await _call(session, "zim_query", {**base, "limit": 100})
            _, after, _ = await _call(session, "zim_query", exact)

        assert _CLAMP_NOTE in _embedded_json(clamped)["note"]
        assert "note" not in _embedded_json(after), after[-400:]
        assert _embedded_json(after) == _embedded_json(before)

    @pytest.mark.asyncio
    async def test_search_all_clamps_and_says_so(self, withns: Path) -> None:
        base = {"query": "search all files for carbon tax"}
        async with _session(withns, "simple") as session:
            is_error, text, _ = await _call(
                session, "zim_query", {**base, "limit": 100}
            )
            ok_error, ok_text, _ = await _call(
                session, "zim_query", {**base, "limit": 5}
            )

        assert is_error is not True, text[:300]
        assert "Error Processing Query" not in text
        assert "`A/Carbon_tax`" in text, text[:500]
        assert f"`limit=100` {_CLAMP_NOTE}" in text, text[-600:]
        assert ok_error is not True, ok_text[:300]
        assert "`A/Carbon_tax`" in ok_text
        assert _CLAMP_NOTE not in ok_text


class TestSearchAllRefusesOffset:
    """``search all files for X`` answered ``offset=3`` and ``offset=300``
    with page one, byte for byte.

    The fan-out returns each archive's top hits and has no next page, so the
    offset was accepted and dropped; advanced ``zim_search(cross_file=True,
    offset=3)`` already refuses the same request.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("offset", [3, 300])
    async def test_offset_is_refused_with_a_route_that_pages(
        self, withns: Path, offset: int
    ) -> None:
        mini = str(withns / _MINI)
        async with _session(withns, "simple") as session:
            is_error, text, body = await _call(
                session,
                "zim_query",
                {
                    "query": "search all files for carbon tax",
                    "limit": 3,
                    "offset": offset,
                },
            )
            ok_error, ok_text, _ = await _call(
                session,
                "zim_query",
                {"query": "search all files for carbon tax", "limit": 3},
            )
            # The advice names the per-archive route; it must really page.
            first = await _call(
                session,
                "zim_query",
                {"query": "search for carbon tax", "zim_file_path": mini, "limit": 3},
            )
            second = await _call(
                session,
                "zim_query",
                {
                    "query": "search for carbon tax",
                    "zim_file_path": mini,
                    "limit": 3,
                    "offset": 3,
                },
            )

        assert is_error is True, text[:300]
        assert body["operation"] == "invalid_combination", body
        assert f"`offset` (provided: {offset})" in body["message"], body
        assert "`search for <terms>`" in body["message"], body
        assert "`zim_file_path`" in body["message"], body
        # Positive pairs: the fan-out itself still answers, and the route the
        # message names returns a different page at the same offset.
        assert ok_error is not True, ok_text[:300]
        assert "`A/Carbon_tax`" in ok_text
        assert first[0] is not True and second[0] is not True
        assert "A/Carbon_tax" in first[1]
        assert "A/Carbon_tax" not in second[1], second[1][:600]


class TestSynthesizeMetaWithAFailedArchive:
    """A failed archive changed what ``_meta`` measured, and leaked its path.

    ``_meta.chars`` is the answer's length on every synthesize response —
    until ``archives_failed`` was added and the payload re-measured, when it
    became the JSON envelope's (5,267 → 8,265 for the same answer). The
    failure's ``error`` also echoed the archive's absolute path, which every
    other diagnostic redacts to the filename.
    """

    @staticmethod
    def _corpus(root: Path, withns: Path, *, broken: bool) -> Path:
        corpus = root / ("broken" if broken else "healthy")
        corpus.mkdir()
        shutil.copy(withns / _MINI, corpus / _MINI)
        if broken:
            shutil.copy(withns / _BAD, corpus / _BAD)
        return corpus

    @pytest.mark.asyncio
    async def test_meta_measures_the_answer_and_the_path_is_redacted(
        self, tmp_path: Path, withns: Path
    ) -> None:
        if not (withns / _BAD).exists():
            pytest.skip(f"{_BAD} not in the corpus")
        args = {"query": "tell me about greenhouse effect", "synthesize": True}
        results = {}
        for broken in (False, True):
            corpus = self._corpus(tmp_path, withns, broken=broken)
            async with _session(corpus, "simple") as session:
                results[broken] = await _call(session, "zim_query", args)

        healthy, failed = results[False][2], results[True][2]
        assert results[True][0] is not True, results[True][1][:300]
        assert "archives_failed" not in healthy
        (failure,) = failed["archives_failed"]
        # The same answer reports the same size, failure or not.
        assert failed["answer_markdown"] == healthy["answer_markdown"]
        assert failed["_meta"]["chars"] == len(failed["answer_markdown"])
        assert failed["_meta"] == healthy["_meta"]
        # Redacted to the filename, with the diagnosis kept.
        assert str(tmp_path) not in failure["error"], failure
        assert f"...{_BAD}" in failure["error"], failure
        assert "too small" in failure["error"], failure


class TestBinaryTipNamesARouteToMediaPaths:
    """The binary intent's missing-path tip promised a listing that does not
    exist.

    "`links in <article>` lists the media paths an article embeds" — but the
    compact ``links in`` view drops the media bucket and the full view lists
    internal links only, so following the tip never produced a media path.
    """

    @pytest.mark.asyncio
    async def test_simple_mode_tip_leads_to_a_fetchable_media_path(
        self, withns: Path
    ) -> None:
        mini = str(withns / _MINI)
        async with _session(withns, "simple") as session:
            _, tip, _ = await _call(
                session, "zim_query", {"query": "get image", "zim_file_path": mini}
            )
            # Follow the tip on an archive that files its media under ``I``.
            _, listing, _ = await _call(
                session,
                "zim_query",
                {
                    "query": "browse namespace I",
                    "zim_file_path": mini,
                    "limit": 3,
                    "compact": False,
                },
            )
            media_path = _leading_json(listing)["results"][0]["path"]
            fetch_error, fetched, _ = await _call(
                session,
                "zim_query",
                {
                    "query": f'get binary content from "{media_path}"',
                    "zim_file_path": mini,
                },
            )

        assert "Missing Entry Path" in tip, tip
        assert "`links in <article>`" not in tip, tip
        assert "`browse namespace I`" in tip, tip
        assert media_path.startswith("I/"), media_path
        assert fetch_error is not True, fetched[:300]
        assert '"encoding": "base64"' in fetched, fetched[:300]

    @pytest.mark.asyncio
    async def test_advanced_mode_tip_names_the_media_bucket(self, withns: Path) -> None:
        mini = str(withns / _MINI)
        async with _session(withns, "advanced") as session:
            _, tip, _ = await _call(
                session, "zim_query", {"query": "get image", "zim_file_path": mini}
            )
            # The call the tip spells out is accepted as written.
            links_error, links, body = await _call(
                session,
                "zim_links",
                {"zim_file_path": mini, "entry_path": "A/Carbon_tax", "kind": "media"},
            )

        assert "`links in <article>`" not in tip, tip
        assert '`zim_links(entry_path=<article>, kind="media")`' in tip, tip
        assert links_error is not True, links[:300]
        assert "media" in body["category_totals"], body


# The lead of this article is a 69-row table, which compact rendering
# replaces with a placeholder telling the caller to pass ``compact=False``.
_TABLE_ARTICLE = "A/List_of_coal-fired_power_stations_in_Vietnam"
_PLACEHOLDER = "[Table 1: 69 rows x 9 cols - pass compact=False to expand]"


class TestGetSectionHonoursCompact:
    """``get section X of Y`` with ``compact=False`` still returned the
    compact table placeholder — "pass compact=False to expand" — so the
    advice looped: the handler never passed ``compact`` to the section
    fetch, which defaults to the compact bundle.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cache", [False, True])
    async def test_compact_false_expands_the_table(
        self, withns: Path, cache: bool
    ) -> None:
        base = {
            "query": f"get section 1 of {_TABLE_ARTICLE}",
            "zim_file_path": str(withns / _MINI),
            "max_content_length": 50_000,
        }
        async with _session(withns, "simple", cache=cache) as session:
            # Compact first, so with the cache on the raw call follows a
            # cached compact bundle (and the compact call after it a raw one).
            _, compact, _ = await _call(session, "zim_query", base)
            raw_error, raw, _ = await _call(
                session, "zim_query", {**base, "compact": False}
            )
            _, compact_again, _ = await _call(session, "zim_query", base)

        assert raw_error is not True, raw[:300]
        assert "List of coal-fired power stations in Vietnam" in raw
        assert _PLACEHOLDER not in raw, raw[:1500]
        # The table itself, rendered: its 69 rows, not a placeholder for them.
        rows = [line for line in raw.splitlines() if line.count(" | ") >= 5]
        assert len(rows) > 50, raw[:1500]
        assert "Duyen Hai 1 |" in raw, raw[:1500]
        # Positive pair: compact mode keeps the placeholder it advertises.
        assert _PLACEHOLDER in compact, compact[:1500]
        assert compact_again == compact


class TestTableDominatedSectionAdviceResolves:
    """The subject-section fallback's own advice was a dead end.

    For a section that compact mode reduces to table placeholders it says to
    re-issue ``get section <ref> of <path>`` with ``compact=False``. The
    reference was the heading's *id* (``Notable_people``), which
    ``get section`` matches against heading TEXT — "Section not found" — and
    even a reference that matched came back compact (see above). Munich's
    ``Notable people`` (two placeholder-only sub-tables) is the live shape.
    """

    @staticmethod
    def _handler() -> Any:
        from unittest.mock import MagicMock

        from openzim_mcp.simple_tools import SimpleToolsHandler

        placeholders = (
            "### Born in Munich\n\n"
            "[Table 8: 1 rows x 2 cols - pass compact=False to expand]\n"
        )
        expanded = (
            "### Born in Munich\n\nName | Born\n---|---\nRichard Strauss | 1864\n"
        )
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.search_zim_file_data.return_value = {
            "results": [{"path": "Munich", "title": "Munich"}],
            "total": 1,
        }
        mock.get_zim_entry.return_value = "stub-body"
        mock.find_entry_by_title_data.return_value = {
            "results": [{"path": "Munich", "title": "Munich", "score": 1.0}],
            "total": 1,
        }
        mock.get_article_structure_data.return_value = {
            "headings": [{"level": 2, "text": "Notable people", "id": "Notable_people"}]
        }
        # The section body as each bundle renders it.
        mock.get_section_data.side_effect = lambda *_a, compact=True, **_k: {
            "content_markdown": placeholders if compact else expanded
        }
        return SimpleToolsHandler(mock)

    def test_following_the_advice_returns_the_expanded_section(self) -> None:
        handler = self._handler()
        out = handler.handle_zim_query(
            "tell me about musicians from München",
            zim_file_path="/x.zim",
            options={"compact": True},
        )
        advice = re.findall(r"`(get section [^`]+)`", out)
        assert advice == ["get section Notable people of Munich"], out

        follow_up = handler.handle_zim_query(
            advice[0], zim_file_path="/x.zim", options={"compact": False}
        )

        assert "not found" not in follow_up, follow_up
        assert "Richard Strauss | 1864" in follow_up, follow_up
        assert "[Table 8" not in follow_up, follow_up


_URL_HINT_RE = re.compile(r"never URLs: [^(]*\(e\.g\. '([^']+)'")


class TestWikiUrlHintResolves:
    """The URL-shaped-path hint corrected a Wikipedia URL to another miss.

    For ``https://en.wikipedia.org/wiki/Carbon_tax`` it suggested
    ``en.wikipedia.org/wiki/Carbon_tax`` — keeping the host is right for a
    zimit crawl, but mwoffliner archives (every Wikimedia project) file the
    article under its title — and that second miss carried no hint at all,
    because the scheme it keys on was gone. On the mini fixture the article
    is ``A/Carbon_tax``.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "https://en.wikipedia.org/wiki/Carbon_tax",
            "https://en.m.wikipedia.org/wiki/Carbon_tax#History",
            "http://en.wikipedia.org/wiki/Carbon%5Ftax?oldid=1",
        ],
    )
    async def test_following_the_hint_reaches_the_article(
        self, withns: Path, url: str
    ) -> None:
        mini = str(withns / _MINI)
        async with _session(withns, "advanced") as session:
            is_error, text, body = await _call(
                session, "zim_get", {"zim_file_path": mini, "entry_path": url}
            )
            match = _URL_HINT_RE.search(body["message"])
            assert match, body["message"]
            ok_error, ok_text, followed = await _call(
                session,
                "zim_get",
                {
                    "zim_file_path": mini,
                    "entry_path": match.group(1),
                    "max_content_length": 200,
                },
            )

        assert is_error is True, text[:300]
        assert ok_error is not True, ok_text[:300]
        assert followed["path"] == "A/Carbon_tax", followed
        assert match.group(1) == "Carbon_tax", body["message"]
        # The host-kept spelling a zimit crawl of a wiki would use is still
        # offered, second.
        assert "'en." in body["message"] and "if that misses" in body["message"]

    @pytest.mark.asyncio
    async def test_a_crawled_site_url_still_keeps_its_host(self, withns: Path) -> None:
        """Positive pair: zimit archives file entries under the host."""
        mini = str(withns / _MINI)
        async with _session(withns, "advanced") as session:
            _, _, body = await _call(
                session,
                "zim_get",
                {"zim_file_path": mini, "entry_path": "https://iep.utm.edu/stoicism/"},
            )

        match = _URL_HINT_RE.search(body["message"])
        assert match and match.group(1) == "iep.utm.edu/stoicism/", body["message"]

    def test_a_wiki_url_without_a_title_offers_no_empty_path(self) -> None:
        from openzim_mcp.error_messages import url_shaped_path_hint

        hint = url_shaped_path_hint("https://en.wikipedia.org/wiki/")

        assert "(e.g. ''" not in hint, hint
        assert "(e.g. 'en.wikipedia.org/wiki/')" in hint, hint


def _prompt_step(prompt: Any, number: int) -> str:
    """One numbered workflow line of a rendered prompt."""
    text = prompt.messages[0].content.text
    return next(line for line in text.splitlines() if line.startswith(f"{number}."))


class TestExplorePromptWalksTheContentNamespace:
    """``/explore`` step 3 walked namespace ``C`` on every archive.

    Old-scheme archives — the climate mini fixture among them — keep their
    articles in ``A``, so the walk scanned all 20,565 entries and returned
    nothing, with no word on why.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "subdir, name, namespace",
        [("withns", _MINI, "A"), ("nons", "small.zim", "C")],
    )
    async def test_step_three_samples_real_articles(
        self, zim_test_data_dir: Optional[Path], subdir: str, name: str, namespace: str
    ) -> None:
        if zim_test_data_dir is None:
            pytest.skip("ZIM_TEST_DATA_DIR not set")
        archive = zim_test_data_dir / subdir / name
        if not archive.exists():
            pytest.skip(f"{name} not in the corpus")
        async with _session(archive.parent, "advanced") as session:
            prompt = await session.get_prompt(
                "explore", {"zim_file_path": str(archive)}
            )
            step = _prompt_step(prompt, 3)
            named = re.search(r"namespace=`([A-Z])`", step)
            assert named, step
            # Run step 3 exactly as the prompt spells it.
            is_error, text, walked = await _call(
                session,
                "zim_browse",
                {
                    "zim_file_path": str(archive),
                    "namespace": named.group(1),
                    "mode": "walk",
                    "limit": 5,
                },
            )

        assert named.group(1) == namespace, step
        assert is_error is not True, text[:300]
        assert walked["results"], walked

    @pytest.mark.asyncio
    async def test_an_unreadable_archive_defers_to_the_metadata_step(
        self, withns: Path
    ) -> None:
        """Nothing to probe: say how to choose instead of guessing ``C``."""
        async with _session(withns, "advanced") as session:
            prompt = await session.get_prompt(
                "explore", {"zim_file_path": str(withns / "missing.zim")}
            )

        step = _prompt_step(prompt, 3)
        assert "step 1" in step, step
        assert "`C`" in step and "`A`" in step, step
        assert "namespace=`C`" not in step, step

    @pytest.mark.asyncio
    async def test_an_archive_outside_the_allowed_directories_is_not_opened(
        self, tmp_path: Path, withns: Path
    ) -> None:
        """The probe takes a client-supplied path, so it goes through the
        path validator like every tool: a real archive outside the allowed
        directories gets the generic wording, not its scheme read out."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        shutil.copy(withns / "small.zim", allowed / "small.zim")
        async with _session(allowed, "advanced") as session:
            outside = await session.get_prompt(
                "explore", {"zim_file_path": str(withns / _MINI)}
            )
            inside = await session.get_prompt(
                "explore", {"zim_file_path": str(allowed / "small.zim")}
            )

        assert "namespace=`A`" not in _prompt_step(outside, 3)
        assert "step 1" in _prompt_step(outside, 3)
        # Positive pair: the allowed copy of an old-scheme archive is probed.
        assert "namespace=`A`" in _prompt_step(inside, 3)


class TestSummarizePromptRanksByMention:
    """``/summarize`` took "the most-mentioned related entries" from
    ``direction="outbound"``.

    Outbound links come back occurrence by occurrence, in document order with
    duplicates kept (58 rows, 54 targets, for ``A/Climate_change``), so
    nothing in them is ranked by mentions. ``direction="related"`` is exactly
    that: distinct targets with a ``mention_count``, most-mentioned first.
    """

    @pytest.mark.asyncio
    async def test_step_three_returns_distinct_articles_by_mention_count(
        self, withns: Path
    ) -> None:
        mini = str(withns / _MINI)
        article = "A/Climate_change"
        async with _session(withns, "advanced") as session:
            prompt = await session.get_prompt(
                "summarize", {"zim_file_path": mini, "entry_path": article}
            )
            step = _prompt_step(prompt, 3)
            direction = re.search(r"direction=`([a-z]+)`", step)
            assert direction, step
            # Run step 3 exactly as the prompt spells it.
            is_error, text, body = await _call(
                session,
                "zim_links",
                {
                    "zim_file_path": mini,
                    "entry_path": article,
                    "direction": direction.group(1),
                    "limit": 10,
                },
            )

        assert direction.group(1) == "related", step
        assert "outbound" not in prompt.messages[0].content.text
        assert is_error is not True, text[:300]
        paths = [row["path"] for row in body["results"]]
        counts = [row["mention_count"] for row in body["results"]]
        assert paths and len(set(paths)) == len(paths), paths
        assert counts == sorted(counts, reverse=True) and counts[0] > 1, counts
