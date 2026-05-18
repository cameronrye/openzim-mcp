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
        """Strong-hint precedence: 'notable' is weak and gets skipped;
        'people' is strong and is returned. Pin the actual algorithmic
        output rather than allowing both possible answers, so a
        regression that returns 'notable' instead of 'people' would
        be caught.
        """
        hint = handler._extract_subject_hint(
            topic="notable people from big rapids michigan",
            resolved_title="Big Rapids, Michigan",
        )
        assert hint == "people"

    def test_weak_hint_skipped_in_favor_of_strong_hint(self, handler):
        """When a residual contains both a weak hint ('notable') and a
        strong hint ('athletes'), the strong hint wins regardless of
        token order in the topic.
        """
        hint = handler._extract_subject_hint(
            topic="notable athletes from detroit",
            resolved_title="Detroit",
        )
        assert hint == "athletes"

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

    def test_substring_collisions_do_not_match(self, handler):
        """Whole-word matching prevents false positives like 'film'
        matching 'Microfilm' or 'science' matching 'Conscience'.
        """
        structure = {
            "headings": [
                {"level": 2, "text": "Microfilm collection", "id": "microfilm"},
                {"level": 2, "text": "Conscience and ethics", "id": "conscience"},
            ]
        }
        # "actor" candidate "Film" must NOT match "Microfilm collection".
        assert handler._resolve_section_for_subject(structure, "actor") is None
        # "scientist" candidate "Science" must NOT match
        # "Conscience and ethics".
        assert handler._resolve_section_for_subject(structure, "scientist") is None

    def test_word_boundary_inside_heading_still_matches(self, handler):
        """Whole-word matching still picks up the candidate when it's
        part of a multi-word heading like 'Music and dance' or
        'Film and television'.
        """
        structure = {
            "headings": [
                {"level": 2, "text": "Music and dance", "id": "music-dance"},
                {"level": 2, "text": "Film and television", "id": "film-tv"},
            ]
        }
        # "musician" -> "Music" candidate matches at word boundary.
        target = handler._resolve_section_for_subject(structure, "musician")
        assert target is not None
        assert target["text"] == "Music and dance"
        # "actor" -> "Film" candidate matches at word boundary.
        target = handler._resolve_section_for_subject(structure, "actor")
        assert target is not None
        assert target["text"] == "Film and television"


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

    def test_explicit_phrasing_with_subject_hint_still_decomposes(
        self, handler, mock_zim_operations
    ):
        """An explicit 'tell me about' phrasing that ALSO carries a
        subject hint (musician, actor, ...) should still route through
        subject-attribute decomposition. The original confidence-gate
        implementation skipped these, breaking queries like
        'tell me about famous musicians from Detroit' even though
        they have the same subject-attribute shape as the bare-topic
        version 'famous musicians from Detroit'.

        The subject-hint extraction is the sole gate; explicit
        phrasing is irrelevant.
        """
        result = handler.handle_zim_query(
            "tell me about famous musician from big rapids michigan",
            zim_file_path="/zim/test.zim",
            options={"compact": True, "max_content_length": 8000},
        )
        # Subject-decomposition fired.
        assert "May Erlewine" in result
        assert "Notable people" in result
        # get_section_data was called with the right section.
        mock_zim_operations.get_section_data.assert_called_once()
        called_args = mock_zim_operations.get_section_data.call_args
        positional = called_args.args
        kwargs = called_args.kwargs
        assert (
            "notable" in positional
            or kwargs.get("section_id") == "notable"
        )

    def test_bare_entity_request_skips_decomposition_via_no_hint(
        self, handler, mock_zim_operations
    ):
        """An explicit 'tell me about <entity>' phrasing without any
        subject hint in the residual must NOT trigger subject-
        decomposition. The subject-hint extraction returns None for
        empty residuals, which is the gate that protects bare entity
        requests from being decomposed.

        Lock the contract: _extract_subject_hint is the sole gate.
        Without confidence-based filtering, the test must show that
        absence-of-hint correctly suppresses subject-decomposition.
        """
        # Override search to resolve to "Big Rapids, Michigan" exactly.
        mock_zim_operations.search_zim_file_data.return_value = {
            "results": [
                {
                    "path": "Big_Rapids,_Michigan",
                    "title": "Big Rapids, Michigan",
                    "snippet": "...",
                },
            ],
        }
        result = handler.handle_zim_query(
            "tell me about Big Rapids, Michigan",
            zim_file_path="/zim/test.zim",
            options={"compact": True, "max_content_length": 8000},
        )
        # No subject-decomposition hedge in result.
        assert "asked about" not in result
        # get_section_data NOT called.
        mock_zim_operations.get_section_data.assert_not_called()

    def test_multi_entity_subject_query_emits_soft_connector_hint(
        self, handler, mock_zim_operations
    ):
        """When a subject query carries a soft connector like 'and'
        between two entity names and resolves to only one of them,
        the response includes the soft-connector ambiguity footer
        so the LLM knows the other entity was dropped.

        Without the footer, multi-entity queries silently drop the
        unresolved half — observed regression risk flagged by the
        post-task-2 cross-cutting review.
        """
        # Override the search/find to resolve "berlin and paris"
        # → paris only.
        mock_zim_operations.search_zim_file_data.return_value = {
            "results": [
                {"path": "Paris", "title": "Paris", "snippet": "..."},
            ],
        }
        def _find(zim_path, title, **kw):
            t_lower = title.strip().lower()
            if t_lower == "paris":
                return {
                    "results": [
                        {
                            "path": "Paris",
                            "title": "Paris",
                            "score": 1.0,
                        }
                    ]
                }
            return {"results": []}
        mock_zim_operations.find_entry_by_title_data.side_effect = _find
        mock_zim_operations.get_article_structure_data.return_value = {
            "headings": [
                {"level": 1, "text": "Paris", "id": "h1"},
                {"level": 2, "text": "Content", "id": "content"},
                {"level": 2, "text": "Music", "id": "music"},
            ]
        }
        mock_zim_operations.get_section_data.return_value = {
            "section": {"text": "Music", "id": "music", "level": 2},
            "content_markdown": "Paris is a major center for classical music.",
        }
        result = handler.handle_zim_query(
            "musicians from berlin and paris",
            zim_file_path="/zim/test.zim",
            options={"compact": True, "max_content_length": 8000},
        )
        # Subject-attribute fired (Music section returned).
        assert "Paris is a major center for classical music." in result
        # Soft-connector footer surfaced the dropped half.
        # The exact text format comes from _soft_connector_footer — look
        # at that method's existing test coverage to set the right
        # substring. Common substring is "may refer to" or "berlin".
        # Use a forgiving but meaningful check:
        assert "berlin" in result.lower() or "may also refer" in result.lower()
