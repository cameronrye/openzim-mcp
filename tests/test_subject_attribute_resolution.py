"""Subject-attribute decomposition for ``tell me about`` queries.

When the resolved entity's title doesn't cover all of the topic's
tokens, the residual tokens often name a subject category (the
``musician`` in ``famous musician from big rapids michigan``).
This module tests the helper that detects that pattern and the
end-to-end routing that fetches the matching section instead of
the (often empty) lead.
"""

from unittest.mock import MagicMock

import pytest

from openzim_mcp.simple_tools import SimpleToolsHandler


class TestExtractSubjectHint:
    """Unit-level coverage of ``_extract_subject_hint`` — the helper
    that pulls a subject token (``musician``, ``actor``, ...) out of
    the residual after entity resolution.
    """

    @pytest.fixture
    def handler(self):
        return SimpleToolsHandler(MagicMock())

    def test_musician_residual_extracts_musician_hint(self, handler):
        hint = handler._extract_subject_hint(
            topic="famous musician from big rapids michigan",
            resolved_title="Big Rapids, Michigan",
        )
        assert hint == "musician"

    def test_notable_people_residual_extracts_people_hint(self, handler):
        hint = handler._extract_subject_hint(
            topic="notable people from big rapids michigan",
            resolved_title="Big Rapids, Michigan",
        )
        assert hint in {"people", "notable"}

    def test_weak_hint_alone_returns_none(self, handler):
        hint = handler._extract_subject_hint(
            topic="famous big rapids michigan",
            resolved_title="Big Rapids, Michigan",
        )
        assert hint is None

    def test_no_residual_returns_none(self, handler):
        hint = handler._extract_subject_hint(
            topic="big rapids michigan",
            resolved_title="Big Rapids, Michigan",
        )
        assert hint is None

    def test_residual_without_subject_word_returns_none(self, handler):
        hint = handler._extract_subject_hint(
            topic="tourism in big rapids michigan",
            resolved_title="Big Rapids, Michigan",
        )
        assert hint is None

    def test_stopwords_in_residual_ignored(self, handler):
        hint = handler._extract_subject_hint(
            topic="actors from big rapids michigan",
            resolved_title="Big Rapids, Michigan",
        )
        assert hint == "actors"
