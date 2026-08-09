"""Follow-up regression tests for the 2026-08 correctness sweep.

Each test class pins one of the verified-but-deferred findings left after
the first sweep PR; the docstrings name the failure the fix closes.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openzim_mcp.intent_parser import IntentParser, _extract_entry_path_keyworded
from openzim_mcp.simple_tools import SimpleToolsHandler
from openzim_mcp.synthesize import _promote_title_match


class TestEntryPathFirstPrepositionAnchor:
    """The keyworded extractor anchored on the LAST of/for/in/from/to, so
    title-internal prepositions truncated the entry: ``toc of Battle of
    Britain`` resolved entry ``Britain``, ``links in Lord of the Rings``
    resolved ``the Rings``. The anchor is now the FIRST preposition after
    the intent verb (with ``table of contents`` treated as one verb
    phrase so its internal ``of`` can't win).
    """

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            # The fix: title-internal prepositions survive.
            ("toc of Battle of Britain", "Battle of Britain"),
            ("links in Lord of the Rings", "Lord of the Rings"),
            ("ToC of Theory of relativity", "Theory of relativity"),
            ("structure of Theory of relativity", "Theory of relativity"),
            ("summary of History of France", "History of France"),
            ("links in the History of France article", "the History of France article"),
            # Pinned pre-fix behavior that must keep working.
            ("table of contents for Biology", "Biology"),
            ("table of contents of Paris", "Paris"),
            ("list the table of contents for Marie Curie", "Marie Curie"),
            (
                "table of contents for Shakespeare England plays",
                "Shakespeare England plays",
            ),
            ("get article History of France", "History of France"),
            ("get article Lord of the Rings", "Lord of the Rings"),
            ("links in Murphy's law and Sod's law", "Murphy's law and Sod's law"),
            ('structure of "Photosynthesis" in compact mode', "Photosynthesis"),
            (
                "what sections are in the Isaac Newton article",
                "the Isaac Newton article",
            ),
            (
                "show me the sections of the Albert Einstein article",
                "the Albert Einstein article",
            ),
            ("give a brief overview of Isaac Newton", "Isaac Newton"),
            ("outline the structure of Isaac Newton", "Isaac Newton"),
            ("links going out of Roman Empire", "Roman Empire"),
            ("what links out of Tokyo", "Tokyo"),
            ("outbound links from Quantum mechanics", "Quantum mechanics"),
            # ``references``/``related`` are links-intent verbs too. Omitting
            # them from the verb list left scan_from at 0, so a preposition
            # in a LEADING noun phrase won the anchor and the verb itself
            # leaked into the entry ("references in photosynthesis").
            ("list of references in Photosynthesis", "Photosynthesis"),
            (
                "the list of references in the Battle of Britain",
                "the Battle of Britain",
            ),
            ("see also references in Battle of Britain", "Battle of Britain"),
            ("the reference in Lord of the Rings", "Lord of the Rings"),
            ("related pages in Isle of Man", "Isle of Man"),
        ],
    )
    def test_extractor_preserves_title_internal_prepositions(
        self, query: str, expected: str
    ) -> None:
        params: dict = {}
        _extract_entry_path_keyworded(query, params)
        assert params.get("entry_path") == expected

    def test_prose_mention_of_toc_is_not_hijacked(self) -> None:
        """``tell me about the table of contents feature`` used to be
        parsed as toc-of-``feature`` (the phrase-internal ``of`` acted as
        the anchor). With the phrase treated as the verb and no
        preposition following it, no entry_path is extracted, so the
        handler's missing-argument guard fires instead of confidently
        serving the toc of the wrong article.
        """
        params: dict = {}
        _extract_entry_path_keyworded(
            "tell me about the table of contents feature", params
        )
        assert "entry_path" not in params

    def test_parse_intent_end_to_end(self) -> None:
        intent, params, _ = IntentParser.parse_intent("toc of Battle of Britain")
        assert intent == "toc"
        assert params["entry_path"].lower() == "battle of britain"

        intent, params, _ = IntentParser.parse_intent("links in Lord of the Rings")
        assert intent == "links"
        assert params["entry_path"].lower() == "lord of the rings"


class TestDisambigTwinDoesNotBlockPromotion:
    """``Berlin_(disambiguation)`` at rank 1 strong-matched ``berlin``
    (candidate-extends-topic), so the promotion short-circuits in
    synthesize and the search splice never probed for the canonical
    ``Berlin`` — the disambiguation page led the response. A twin is now
    never "already canonical" unless the query itself asks for the
    disambiguation page. The tell-me-about ambiguity machinery keeps
    counting the twin as a strong match (it auto-picks the canonical
    downstream), so ``is_strong_title_match`` itself is unchanged.
    """

    def test_synthesize_promotes_canonical_past_twin_at_rank_1(self) -> None:
        hits = [
            (
                "wiki",
                {"path": "Berlin_(disambiguation)", "snippet": "...", "score": 0.6},
            )
        ]
        search_handler = MagicMock()
        search_handler.title_match_hit.return_value = {
            "path": "Berlin",
            "snippet": "Berlin is the capital...",
            "score": 1.0,
        }
        promoted = _promote_title_match(
            hits,
            query="berlin",
            archives=[(MagicMock(), Path("/fake/wiki.zim"))],
            archives_searched=["wiki"],
            search_handler=search_handler,
        )
        paths = [h["path"] for _, h in promoted]
        assert paths[0] == "Berlin"
        # The twin is preserved at a lower rank, not dropped.
        assert "Berlin_(disambiguation)" in paths

    def test_explicit_disambiguation_query_keeps_twin_at_rank_1(self) -> None:
        hits = [
            (
                "wiki",
                {"path": "Berlin_(disambiguation)", "snippet": "...", "score": 0.6},
            )
        ]
        search_handler = MagicMock()
        promoted = _promote_title_match(
            hits,
            query="berlin disambiguation",
            archives=[(MagicMock(), Path("/fake/wiki.zim"))],
            archives_searched=["wiki"],
            search_handler=search_handler,
        )
        assert promoted == hits
        assert search_handler.title_match_hit.call_count == 0

    def test_search_splice_promotes_canonical_past_twin_at_rank_1(self) -> None:
        handler = SimpleToolsHandler.__new__(SimpleToolsHandler)
        handler.zim_operations = MagicMock()
        handler.zim_operations.find_entry_by_title_data.return_value = {
            "results": [
                {
                    "path": "Berlin",
                    "title": "Berlin",
                    "score": 1.0,
                    "zim_file": "/fake/wiki.zim",
                }
            ]
        }
        payload = {
            "query": "berlin",
            "results": [
                {
                    "path": "Berlin_(disambiguation)",
                    "title": "Berlin (disambiguation)",
                    "snippet": "...",
                }
            ],
            "total": 1,
            "page_info": {"offset": 0, "limit": 5, "returned_count": 1},
            "_meta": {},
        }
        spliced = handler._splice_title_match_into_search(
            payload, "/fake/wiki.zim", "berlin"
        )
        paths = [r["path"] for r in spliced["results"]]
        assert paths[0] == "Berlin"
        assert "Berlin_(disambiguation)" in paths


class TestNarrowSectionExcludesChildHeading:
    """``include_subsections=False`` narrowed the slice to the first
    following section's ``char_start`` — but in production bundles that
    offset is the child's BODY start (past its heading line), so the
    child's ``### Heading`` line leaked into the "no subsections" slice.
    ``SectionMeta`` now records ``heading_start`` and the narrowing
    boundaries use it (falling back to ``char_start`` for bundles built
    before the field existed).
    """

    #                          0         1         2
    #                          0123456789012345678901234...
    _MD = (
        "## Geography\n"  # heading_start 0, body 13
        "Berlin lies in northeastern Germany.\n"  # 13..50
        "### Topography\n"  # heading_start 50, body 65
        "Flat plain.\n"  # 65..77
    )

    def _bundle(self) -> dict:
        return {
            "entry_path": "Berlin",
            "title": "Berlin",
            "content_type": "text/html",
            "rendered_markdown": self._MD,
            "sections": [
                {
                    "id": "Geography",
                    "title": "Geography",
                    "level": 2,
                    "heading_start": 0,
                    "char_start": 13,
                    "char_end": len(self._MD),
                    "parent_id": None,
                },
                {
                    "id": "Topography",
                    "title": "Topography",
                    "level": 3,
                    "heading_start": 50,
                    "char_start": 65,
                    "char_end": len(self._MD),
                    "parent_id": "Geography",
                },
            ],
            "links": {"internal": [], "external": [], "media": []},
            "infobox": None,
        }

    def test_narrow_slice_stops_before_child_heading_line(self) -> None:
        import openzim_mcp.bundle as _bundle_mod
        from tests.test_get_section_d5_widen_v2a9 import _stub_structure_mixin

        mixin = _stub_structure_mixin()
        original = _bundle_mod.get_or_build_bundle
        _bundle_mod.get_or_build_bundle = (  # type: ignore[assignment]
            lambda *a, **kw: self._bundle()
        )
        try:
            out = mixin._get_section_data(
                archive=MagicMock(),
                validated_path=Path("/fake.zim"),
                entry_path="Berlin",
                section_id="Geography",
                max_chars=None,
                include_subsections=False,
            )
        finally:
            _bundle_mod.get_or_build_bundle = original  # type: ignore[assignment]

        assert out["content_markdown"] == "Berlin lies in northeastern Germany.\n"
        assert "Topography" not in out["content_markdown"]

    def test_bundle_builder_records_heading_start(self) -> None:
        from openzim_mcp.bundle import _compute_section_offsets

        sections = _compute_section_offsets(
            self._MD,
            [
                {"level": 2, "text": "Geography", "id": "Geography"},
                {"level": 3, "text": "Topography", "id": "Topography"},
            ],
        )
        by_id = {s["id"]: s for s in sections}
        assert by_id["Geography"]["heading_start"] == 0
        assert by_id["Geography"]["char_start"] == 13
        assert by_id["Topography"]["heading_start"] == 50
        assert by_id["Topography"]["char_start"] == 65


class _Session:  # weak-referenceable ServerSession stand-in
    pass


class TestPerSessionUriCapCoversKnownUris:
    """The per-session distinct-URI cap was checked only inside the
    ``not _is_known_uri(uri)`` branch, so a session at its cap could
    keep subscribing to any URI some other session had already
    registered — the cap only bound first-registrant subscriptions.
    The cap now applies to every subscription that would add a NEW
    distinct URI for the session; idempotent re-subscribes stay exempt.
    """

    @pytest.mark.asyncio
    async def test_known_uri_still_counts_against_session_cap(
        self, monkeypatch
    ) -> None:
        from openzim_mcp import subscriptions
        from openzim_mcp.exceptions import OpenZimMcpValidationError

        monkeypatch.setattr(subscriptions, "MAX_URIS_PER_SESSION", 2)
        registry = subscriptions.SubscriberRegistry()
        other = _Session()
        await registry.subscribe("zim://shared", other)

        greedy = _Session()
        await registry.subscribe("zim://a", greedy)
        await registry.subscribe("zim://b", greedy)
        # 'zim://shared' is already known (registered by ``other``), but
        # it is still a NEW distinct URI for ``greedy`` — the cap must
        # apply.
        with pytest.raises(OpenZimMcpValidationError):
            await registry.subscribe("zim://shared", greedy)

    @pytest.mark.asyncio
    async def test_resubscribe_at_cap_stays_idempotent(self, monkeypatch) -> None:
        from openzim_mcp import subscriptions

        monkeypatch.setattr(subscriptions, "MAX_URIS_PER_SESSION", 2)
        registry = subscriptions.SubscriberRegistry()
        session = _Session()
        await registry.subscribe("zim://a", session)
        await registry.subscribe("zim://b", session)
        # Re-subscribing to an already-held URI at the cap must not raise.
        await registry.subscribe("zim://a", session)


class TestReadyzWedgedProbeDoesNotAccumulateCallbacks:
    """Each ``/readyz`` request created a fresh ``asyncio.wrap_future``
    wrapper around the shared in-flight probe. ``wrap_future`` chains a
    done-callback onto the concurrent future and nothing unchains it when
    the waiter times out — so while a stat was wedged on a dead mount,
    every probe request (unauthenticated, unmetered) grew the future's
    callback list without bound. The wrapper is now created once per
    probe and shared by all waiters (``shield`` already cleans up its own
    per-waiter callback on timeout).
    """

    def test_timed_out_waiters_do_not_grow_probe_callbacks(
        self, monkeypatch, tmp_path
    ) -> None:
        import asyncio as _asyncio
        import threading as _threading
        from unittest.mock import patch as _patch

        from openzim_mcp import http_app as _http_app
        from openzim_mcp.http_app import _make_readyz

        monkeypatch.setattr(_http_app, "READYZ_PROBE_TIMEOUT_SECONDS", 0.05)

        released = _threading.Event()
        real_isdir = __import__("os").path.isdir

        def _wedged_isdir(p):
            released.wait(timeout=10)
            return real_isdir(p)

        class _Cfg:
            allowed_directories = [str(tmp_path)]

        class _Server:
            config = _Cfg()

        readyz = _make_readyz(_Server())

        captured: list = []
        real_get_executor = _http_app._get_executor

        def _capturing_get_executor(name):
            pool = real_get_executor(name)

            class _Capture:
                def submit(self, fn, *a, **kw):
                    fut = pool.submit(fn, *a, **kw)
                    captured.append(fut)
                    return fut

            return _Capture()

        async def _drive():
            with (
                _patch("openzim_mcp.http_app.os.path.isdir", _wedged_isdir),
                _patch("openzim_mcp.http_app._get_executor", _capturing_get_executor),
            ):
                responses = []
                for _ in range(5):
                    responses.append(await readyz(None))
                return responses

        try:
            responses = _asyncio.run(_drive())
        finally:
            released.set()

        # All five requests timed out against the single wedged probe.
        assert [r.status_code for r in responses] == [503] * 5
        assert len(captured) == 1, "single-flight broken: multiple submissions"
        # The shared probe must not have accumulated one chained callback
        # per request — one shared wrapper, not five.
        assert len(captured[0]._done_callbacks) <= 1, (
            f"callback accumulation: {len(captured[0]._done_callbacks)} "
            "callbacks chained onto the wedged probe"
        )


class TestSnippetCapSurvivesEmbeddedHeadings:
    """The snippet-cap regex terminated a ``Snippet:`` capture at ANY
    ``\\n\\n## `` — including a markdown H2 embedded in the snippet text
    itself — so everything after the embedded heading escaped the
    per-snippet cap. Result headings are always numbered (``## 3. ``)
    and html2text backslash-escapes numbered article headings
    (``## 1\\. Topic``), so anchoring on the numbered form is
    unambiguous. Same for an embedded ``\\n---\\n`` horizontal rule:
    the real footer always follows a blank line.
    """

    def test_embedded_h2_does_not_bypass_the_cap(self) -> None:
        from openzim_mcp.compact_format import _CompactFormatMixin

        tail = "tail-text " * 60
        text = (
            'Found 2 matches for "x", showing 1-2:\n\n'
            "## 1. Article One\n"
            "Path: A/One\n"
            "Snippet: lead sentence.\n\n## Embedded Section\n" + tail + "\n\n"
            "## 2. Article Two\n"
            "Path: A/Two\n"
            "Snippet: short.\n\n"
            "---\n"
        )
        out = _CompactFormatMixin._truncate_search_snippets(text, max_chars=250)
        assert tail.rstrip() not in out, "embedded H2 bypassed the snippet cap"
        assert "..." in out
        # The real numbered result boundary and footer survive.
        assert "## 2. Article Two" in out
        assert "Snippet: short." in out

    def test_embedded_hrule_does_not_bypass_the_cap(self) -> None:
        from openzim_mcp.compact_format import _CompactFormatMixin

        tail = "tail-text " * 60
        text = (
            'Found 1 matches for "x", showing 1-1:\n\n'
            "## 1. Article One\n"
            "Path: A/One\n"
            "Snippet: lead sentence.\n---\n" + tail + "\n\n"
            "---\n"
        )
        out = _CompactFormatMixin._truncate_search_snippets(text, max_chars=250)
        assert tail.rstrip() not in out, "embedded hrule bypassed the snippet cap"


class TestSuggestionScoreIndependentOfCallerLimit:
    """Suggestion rank-scores divided by ``len(paths)`` — the number of
    rows the CALLER asked for — so the same suggestion at the same rank
    scored 0.6333 at ``limit=10`` but 0.475 at ``limit=2``. Scores now
    decay against a fixed window, so a row's score depends only on its
    rank. Rank 0 keeps scoring 0.95, so the 0.95/0.8 promotion gates
    (which only read the top row) are unchanged.
    """

    def _run(self, test_config, monkeypatch, limit: int):
        from unittest.mock import MagicMock as _MM

        from tests.test_find_entry_by_title_characterization import (
            _entry,
            _make_server,
            _patch_archive,
        )

        server = _make_server(test_config)
        entries = {
            "Climate": _entry("Climate", "Climate"),
            "Climatology": _entry("Climatology", "Climatology"),
            "Climate_model": _entry("Climate_model", "Climate model"),
        }
        archive = _MM()
        archive.has_entry_by_title.return_value = False
        archive.has_entry_by_path.return_value = False
        archive.get_entry_by_path.side_effect = entries.__getitem__

        paths = ["Climate", "Climatology", "Climate_model"]
        sugg = _MM()
        sugg.getEstimatedMatches.return_value = len(paths)
        # Honor the caller's window, as libzim does.
        sugg.getResults.side_effect = lambda start, n: paths[start : start + n]
        searcher = _MM()
        searcher.suggest.return_value = sugg
        _patch_archive(monkeypatch, archive, searcher)

        return server.zim_operations.find_entry_by_title_data(
            "/zim/test.zim", "climat", cross_file=False, limit=limit
        )

    def test_rank_scores_stable_across_limits(self, test_config, monkeypatch):
        wide = self._run(test_config, monkeypatch, limit=10)
        narrow = self._run(test_config, monkeypatch, limit=2)

        wide_by_path = {r["path"]: r["score"] for r in wide["results"]}
        narrow_by_path = {r["path"]: r["score"] for r in narrow["results"]}
        assert narrow_by_path["Climatology"] == wide_by_path["Climatology"], (
            "rank-1 score varies with the caller's limit: "
            f"{narrow_by_path['Climatology']} vs {wide_by_path['Climatology']}"
        )
        # The top row keeps its promotion-gate score.
        assert wide_by_path["Climate"] == pytest.approx(0.95)
        # Scores stay rank-monotonic.
        scores = [r["score"] for r in wide["results"]]
        assert all(a >= b for a, b in zip(scores, scores[1:]))


class TestMainPageProbeFailureNotCachedAsAbsence:
    """A fallback probe path that RESOLVED to an entry but failed content
    extraction fell through the probe ladder into the ``no_main_page``
    arm — which is flagged ``content_ok=True`` ("structural property of
    the archive — safe to cache"). A transient read failure was thereby
    cached as a durable "this archive has no main page" claim. A
    found-but-unbuildable probe now yields ``content_error`` with
    ``content_ok=False``, so nothing is cached and the next request
    retries.
    """

    @staticmethod
    def _archive_with_broken_fallback_entry() -> MagicMock:
        from unittest.mock import PropertyMock

        inst = MagicMock()
        type(inst).main_entry = PropertyMock(
            side_effect=RuntimeError("Cannot find main entry")
        )
        broken = MagicMock()
        broken.is_redirect = False
        broken.title = "Welcome"
        broken.path = "W/mainPage"
        broken.get_item.side_effect = RuntimeError("transient read failure")

        def get_entry_by_path(path):
            if path == "W/mainPage":
                return broken
            raise KeyError(path)

        inst.get_entry_by_path.side_effect = get_entry_by_path
        return inst

    def test_found_but_unreadable_probe_is_content_error_not_absence(
        self,
    ) -> None:
        from openzim_mcp.zim_operations import ZimOperations

        ops = ZimOperations.__new__(ZimOperations)
        ops.content_processor = MagicMock()

        kind, payload, content_ok, found_at = ops._get_main_page_result(
            self._archive_with_broken_fallback_entry()
        )
        assert kind != "no_main_page", (
            "a resolvable-but-unreadable main-page entry must not be "
            "reported (and cached) as the archive having no main page"
        )
        assert content_ok is False, "error sentinel must not be cacheable"
