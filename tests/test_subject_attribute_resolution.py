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


class TestResolveSectionForSubject:
    """Unit-level coverage of ``_resolve_section_for_subject`` — the
    helper that picks the best matching H2 from an article's section
    list given a subject hint token.
    """

    @pytest.fixture
    def handler(self):
        return SimpleToolsHandler(MagicMock())

    def test_musician_matches_music_section(self, handler):
        structure = {
            "headings": [
                {"level": 1, "text": "Big Rapids, Michigan", "id": "h1"},
                {"level": 2, "text": "Content", "id": "content"},
                {"level": 2, "text": "History", "id": "history"},
                {"level": 2, "text": "Notable people", "id": "notable"},
            ]
        }
        target = handler._resolve_section_for_subject(structure, "musician")
        assert target is not None
        assert target.get("text") == "Notable people"

    def test_musician_prefers_music_over_notable_people(self, handler):
        structure = {
            "headings": [
                {"level": 1, "text": "Detroit", "id": "h1"},
                {"level": 2, "text": "Content", "id": "content"},
                {"level": 2, "text": "Music", "id": "music"},
                {"level": 2, "text": "Notable people", "id": "notable"},
            ]
        }
        target = handler._resolve_section_for_subject(structure, "musician")
        assert target is not None
        assert target.get("text") == "Music"

    def test_no_matching_section_returns_none(self, handler):
        structure = {
            "headings": [
                {"level": 1, "text": "Big Rapids, Michigan", "id": "h1"},
                {"level": 2, "text": "Content", "id": "content"},
                {"level": 2, "text": "Geography", "id": "geo"},
                {"level": 2, "text": "Climate", "id": "climate"},
            ]
        }
        target = handler._resolve_section_for_subject(structure, "musician")
        assert target is None

    def test_unknown_subject_returns_none(self, handler):
        structure = {
            "headings": [
                {"level": 2, "text": "Notable people", "id": "notable"},
            ]
        }
        target = handler._resolve_section_for_subject(structure, "philosopher")
        assert target is None


class TestEndToEndSubjectAttributeRouting:
    """Integration coverage: a query like ``famous musician from big
    rapids michigan`` should fetch the ``Notable people`` (or
    ``Music``) section of the resolved place article instead of the
    empty lead.
    """

    @pytest.fixture
    def mock_zim_operations(self):
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/zim/test.zim"}]
        mock.search_zim_file_data.return_value = {
            "results": [
                {
                    "path": "Big_Rapids,_Michigan",
                    "title": "Big Rapids, Michigan",
                    "snippet": "...",
                },
            ],
        }
        def _find(zim_path, title, **kw):
            t_lower = title.strip().lower()
            if t_lower in {
                "big rapids michigan",
                "big rapids, michigan",
                "michigan",
                "rapids michigan",
            }:
                return {
                    "results": [
                        {
                            "path": "Big_Rapids,_Michigan",
                            "title": "Big Rapids, Michigan",
                            "score": 1.0,
                        }
                    ]
                }
            return {"results": []}
        mock.find_entry_by_title_data.side_effect = _find
        mock.get_article_structure_data.return_value = {
            "headings": [
                {"level": 1, "text": "Big Rapids, Michigan", "id": "h1"},
                {"level": 2, "text": "Content", "id": "content"},
                {"level": 2, "text": "History", "id": "history"},
                {"level": 2, "text": "Notable people", "id": "notable"},
                {"level": 2, "text": "Education", "id": "education"},
            ]
        }
        mock.get_section_data.return_value = {
            "section": {"text": "Notable people", "id": "notable", "level": 2},
            "content_markdown": (
                "May Erlewine (born 1983) is an American singer-songwriter "
                "from Big Rapids."
            ),
        }
        mock.search_zim_file.return_value = "fallback search response"
        mock.get_zim_entry.return_value = (
            "# Big Rapids, Michigan\nPath: Big_Rapids,_Michigan\n"
            "Type: text/html\n## Content\n\n"
            "# Big Rapids, Michigan\n\n"
            "## History\n\nHistory body.\n\n"
            "## Notable people\n\nNotable people body."
        )
        return mock

    @pytest.fixture
    def handler(self, mock_zim_operations):
        return SimpleToolsHandler(mock_zim_operations)

    def test_subject_query_fetches_notable_people_section(
        self, handler, mock_zim_operations
    ):
        result = handler.handle_zim_query(
            "famous musician from big rapids michigan",
            zim_file_path="/zim/test.zim",
            options={"compact": True, "max_content_length": 8000},
        )
        assert "May Erlewine" in result
        assert "Notable people" in result
        mock_zim_operations.get_section_data.assert_called_once()
        called_args = mock_zim_operations.get_section_data.call_args
        positional = called_args.args
        kwargs = called_args.kwargs
        # Section id "notable" must appear somewhere in args/kwargs.
        found_section_id = (
            "notable" in positional
            or kwargs.get("section_id") == "notable"
        )
        assert found_section_id
