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
