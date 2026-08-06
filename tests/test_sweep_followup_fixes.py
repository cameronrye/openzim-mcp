"""Follow-up regression tests for the 2026-08 correctness sweep.

Each test class pins one of the verified-but-deferred findings left after
the first sweep PR; the docstrings name the failure the fix closes.
"""

from __future__ import annotations

import pytest

from openzim_mcp.intent_parser import IntentParser, _extract_entry_path_keyworded


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
