"""v3.0.0 field-defect fixes — ``simple`` workstream.

Each class pins one defect from the 2026-08-19 real-world sweep of the
simple-mode ``zim_query`` surface (dispatcher, intent parser, cursor
handling, compact renderers). The defect ids (D42 …) refer to the
sweep's fix plan; the docstrings restate the observed behaviour so the
regression is recognisable without the report.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, Mock

import pytest

from openzim_mcp.pagination import Cursor
from openzim_mcp.simple_tools import IntentParser, SimpleToolsHandler
from openzim_mcp.title_promotion import is_strong_title_match


def _weak_results() -> List[Dict[str, Any]]:
    """Three hits that do NOT strong-match the topic ``immanuel kant``
    under the order-sensitive matcher (the IEP ``Last, First | Site``
    shape), so ``tell me about`` falls through to the rendered search.
    """
    return [
        {
            "path": "iep.utm.edu/kantaest/",
            "title": "Kant: Aesthetics | Internet Encyclopedia",
            "snippet": "...",
        },
        {
            "path": "iep.utm.edu/kant-rel/",
            "title": "Kant: Religion | Internet Encyclopedia",
            "snippet": "...",
        },
        {
            "path": "iep.utm.edu/kantmeta/",
            "title": "Kant: Metaphysics | Internet Encyclopedia",
            "snippet": "...",
        },
    ]


# ---------------------------------------------------------------------------
# D42: tell_me_about advertises ``pass offset=N`` but hardcoded offset 0
# ---------------------------------------------------------------------------


class TestD42TellMeAboutHonoursOffset:
    """The weak-match ``tell me about`` render ends with ``Showing 1-3 of
    ~151 — pass offset=3 for the next page``, but every search call in
    ``_search_or_recover_tell_me_about`` passed a literal ``0``: replaying
    with ``offset=3`` returned the byte-identical first page forever.
    """

    @pytest.fixture
    def mock_ops(self) -> Mock:
        mock = Mock()
        mock.search_zim_file_data.return_value = {"results": _weak_results()}
        mock.search_zim_file.return_value = "rendered page"
        return mock

    def test_offset_reaches_structured_search_and_rendered_fallback(
        self, mock_ops: Mock
    ) -> None:
        handler = SimpleToolsHandler(mock_ops)
        handler.handle_zim_query(
            "tell me about immanuel kant",
            zim_file_path="/zims/iep.zim",
            options={"offset": 3},
        )
        data_call = mock_ops.search_zim_file_data.call_args
        assert data_call is not None
        assert data_call.args[3] == 3, "structured search ignored the offset"
        render_call = mock_ops.search_zim_file.call_args
        assert render_call is not None
        assert render_call.args[3] == 3, "rendered fallback ignored the offset"

    def test_offset_reaches_empty_result_render(self, mock_ops: Mock) -> None:
        mock_ops.search_zim_file_data.return_value = {"results": []}
        handler = SimpleToolsHandler(mock_ops)
        handler.handle_zim_query(
            "tell me about immanuel kant",
            zim_file_path="/zims/iep.zim",
            options={"offset": 6},
        )
        assert mock_ops.search_zim_file.call_args.args[3] == 6

    def test_paged_call_never_auto_fetches_from_page_n(self, mock_ops: Mock) -> None:
        """A continuation request is walking the weak-match list the
        footer advertised; page N's top hit strong-matching the topic
        must not flip the response into an article body.
        """
        mock_ops.search_zim_file_data.return_value = {
            "results": [
                {"path": "Immanuel_Kant", "title": "Immanuel Kant", "snippet": ""}
            ]
        }
        handler = SimpleToolsHandler(mock_ops)
        out = handler.handle_zim_query(
            "tell me about immanuel kant",
            zim_file_path="/zims/iep.zim",
            options={"offset": 3},
        )
        mock_ops.get_zim_entry.assert_not_called()
        assert "rendered page" in out
        assert mock_ops.search_zim_file.call_args.args[3] == 3

    def test_first_page_behaviour_unchanged(self, mock_ops: Mock) -> None:
        handler = SimpleToolsHandler(mock_ops)
        handler.handle_zim_query(
            "tell me about immanuel kant", zim_file_path="/zims/iep.zim"
        )
        assert mock_ops.search_zim_file_data.call_args.args[3] == 0
        assert mock_ops.search_zim_file.call_args.args[3] == 0


# Shared helper for handler-level tests that need a realistic backend mock.
def _handler_with(**overrides: Any) -> tuple[SimpleToolsHandler, MagicMock]:
    mock = MagicMock()
    mock.list_zim_files_data.return_value = [{"path": "/zims/test.zim"}]
    mock.config.meta.footer_enabled = False
    for name, value in overrides.items():
        setattr(mock, name, value)
    return SimpleToolsHandler(mock), mock


def _text(out: Any) -> str:
    """Human-readable body of a handler result, whatever its envelope."""
    if isinstance(out, str):
        return out
    if isinstance(out, dict):
        return str(out.get("message", ""))
    return str(out)


def _browse_cursor(*, offset: int = 5, limit: int = 5) -> str:
    state: Dict[str, Any] = {"o": offset, "l": limit, "ns": "C", "ai": "6d0b22d20314"}
    return Cursor.encode(tool="browse_namespace", state=state)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# D44: foreign cursors silently accepted by the intents without a guard
# ---------------------------------------------------------------------------


class TestD44ForeignCursorRejectedUniformly:
    """The dispatcher projects a decoded cursor's offset / limit into
    ``options`` for EVERY intent, but only five handlers rejected a
    cursor minted by another tool. A ``browse_namespace`` cursor handed
    to ``find article titled Measles`` was silently applied and resized
    the page from 10 to 5; ``tell me about`` swallowed it too.
    """

    @pytest.mark.parametrize(
        ("query", "backend_method"),
        [
            ("find article titled Measles", "find_entry_by_title_data"),
            ("find article titled Measles", "find_entry_by_title"),
            ("tell me about Measles", "search_zim_file_data"),
            ("suggestions for meas", "get_search_suggestions"),
            ("articles related to Measles", "get_related_entries"),
            ("get article Measles", "get_zim_entry"),
        ],
    )
    def test_unguarded_intents_reject_foreign_cursor(
        self, query: str, backend_method: str
    ) -> None:
        handler, mock = _handler_with()
        out = handler.handle_zim_query(
            query,
            zim_file_path="/zims/test.zim",
            options={"compact": True, "cursor": _browse_cursor()},
        )
        body = _text(out)
        assert "Cursor / Tool Mismatch" in body
        assert "browse_namespace" in body
        assert not getattr(mock, backend_method).called

    def test_find_by_title_page_size_not_resized_by_foreign_cursor(self) -> None:
        """Without a cursor the default page (10) reaches the backend; the
        foreign cursor's ``l=5`` must never get there.
        """
        handler, mock = _handler_with()
        handler.handle_zim_query(
            "find article titled Measles",
            zim_file_path="/zims/test.zim",
            options={"compact": True},
        )
        assert mock.find_entry_by_title_data.call_args.kwargs["limit"] == 10
        mock.find_entry_by_title_data.reset_mock()
        handler.handle_zim_query(
            "find article titled Measles",
            zim_file_path="/zims/test.zim",
            options={"compact": True, "cursor": _browse_cursor(limit=5)},
        )
        assert not mock.find_entry_by_title_data.called

    def test_guarded_handlers_keep_their_own_diagnosis(self) -> None:
        """The existing handler-edge guards stay authoritative for the
        cursor-consuming intents (no double rejection, same diagnosis).
        """
        handler, mock = _handler_with()
        out = handler.handle_zim_query(
            "walk namespace C",
            zim_file_path="/zims/test.zim",
            options={"compact": True, "cursor": _browse_cursor()},
        )
        body = _text(out)
        assert "Cursor / Tool Mismatch" in body
        assert "walk_namespace" in body
        assert not mock.walk_namespace_data.called


# ---------------------------------------------------------------------------
# D45: ``search <archive> for <terms>`` neither selects nor strips the archive
# ---------------------------------------------------------------------------

MEDLINE = "/zims/medlineplus.gov_en_all_2025-01.zim"
IEP = "/zims/internet-encyclopedia-philosophy_en_all_2025-06.zim"


class TestD45ArchiveNameInSearchQuery:
    """With two archives loaded and no path, ``search medlineplus for
    diabetes`` tripped the "No ZIM File Specified" gate although the
    query named the target; with an explicit path the archive name
    leaked into the terms (``Found ~2239 matches for "medlineplus for
    diabetes"``).
    """

    def _handler(self) -> tuple[SimpleToolsHandler, MagicMock]:
        handler, mock = _handler_with()
        mock.list_zim_files_data.return_value = [{"path": MEDLINE}, {"path": IEP}]
        mock.search_zim_file.return_value = "rendered"
        return handler, mock

    def test_named_archive_selected_before_the_no_zim_file_gate(self) -> None:
        handler, mock = self._handler()
        out = handler.handle_zim_query("search medlineplus for diabetes")
        assert "No ZIM File Specified" not in _text(out)
        call = mock.search_zim_file.call_args
        assert call is not None
        assert call.args[0] == MEDLINE
        assert call.args[1] == "diabetes"

    def test_full_basename_with_zim_suffix_selects_too(self) -> None:
        handler, mock = self._handler()
        handler.handle_zim_query(
            "search medlineplus.gov_en_all_2025-01.zim for diabetes"
        )
        call = mock.search_zim_file.call_args
        assert call.args[0] == MEDLINE
        assert call.args[1] == "diabetes"

    def test_explicit_path_wins_but_archive_name_is_stripped(self) -> None:
        handler, mock = self._handler()
        handler.handle_zim_query(
            "search medlineplus for diabetes", zim_file_path=MEDLINE
        )
        call = mock.search_zim_file.call_args
        assert call.args[0] == MEDLINE
        assert call.args[1] == "diabetes"

    def test_unknown_leading_word_is_left_in_the_terms(self) -> None:
        """``treatments`` names no loaded archive, so it is a search term."""
        handler, mock = self._handler()
        handler.handle_zim_query(
            "search treatments for diabetes", zim_file_path=MEDLINE
        )
        assert mock.search_zim_file.call_args.args[1] == "treatments for diabetes"

    def test_ambiguous_prefix_does_not_guess(self) -> None:
        handler, mock = self._handler()
        mock.list_zim_files_data.return_value = [
            {"path": "/zims/wikipedia_en_all_2026-02.zim"},
            {"path": "/zims/wikipedia_de_all_2026-02.zim"},
        ]
        out = handler.handle_zim_query("search wikipedia for cats")
        assert "No ZIM File Specified" in _text(out)
        assert not mock.search_zim_file.called


# ---------------------------------------------------------------------------
# D46: "next page" / "more results" ran junk full-text searches
# ---------------------------------------------------------------------------


class TestD46PaginationFollowUpsAreMetaOnly:
    """``next page`` ran a full-text search over ~1699 stop-word hits and
    ``more results`` searched for the literal words; ``try again`` was
    already caught by the meta-only filter. ``page`` / ``results`` were
    missing from the filler-token set, so the two-word forms failed the
    all-tokens-filler check.
    """

    @pytest.mark.parametrize(
        "query",
        ["next page", "more results", "next", "more"],
    )
    def test_pagination_follow_up_returns_guidance(self, query: str) -> None:
        handler = SimpleToolsHandler(Mock())
        assert SimpleToolsHandler._is_meta_only_query(query)
        out = handler.handle_zim_query(query, zim_file_path="/zims/test.zim")
        assert "Try one of these starting points" in out
        # The guidance must point at the real continuation mechanism.
        assert "offset" in out
        handler.zim_operations.search_zim_file.assert_not_called()
        handler.zim_operations.search_zim_file_data.assert_not_called()

    @pytest.mark.parametrize(
        "query",
        ["search results", "main page", "Page", "results of the 1992 election"],
    )
    def test_content_bearing_queries_still_reach_the_parser(self, query: str) -> None:
        assert not SimpleToolsHandler._is_meta_only_query(query)

    def test_guidance_stays_short(self) -> None:
        assert len(SimpleToolsHandler._meta_query_guidance()) < 1000


# ---------------------------------------------------------------------------
# D47: documented ``offset`` silently ignored by suggestions / find_by_title
# ---------------------------------------------------------------------------


def _description_arg_block(name: str) -> str:
    """Return the indented ``Args:`` paragraph for ``name`` from the
    zim_query description (up to the next ``<arg>:`` line at the same
    indentation).
    """
    from openzim_mcp.tools.zim_query import _DESCRIPTION

    lines = _DESCRIPTION.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"    {name}:"))
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if line.startswith("    ") and not line.startswith("     "):
            break
        block.append(line)
    return "\n".join(block)


class TestD47OffsetExclusionsDocumented:
    """``offset`` was documented as generic pagination with no per-intent
    exclusion, yet ``suggestions for`` and ``find article titled`` never
    read it: ``offset=3`` returned the identical first page. The
    backends take no offset (suggestions is declared non-paginated), so
    the contract is documented at the tool surface instead.
    """

    def test_offset_doc_names_the_intents_that_ignore_it(self) -> None:
        block = _description_arg_block("offset")
        assert "suggestions for" in block
        assert "find article titled" in block
        assert "limit" in block, "must tell the caller what to do instead"


# ---------------------------------------------------------------------------
# D48: "get the article about X" leaked command scaffolding into search terms
# ---------------------------------------------------------------------------


class TestD48GetArticleDeterminerAndAbout:
    """``get the article about Immanuel Kant`` fell to the generic search
    fallback with the WHOLE sentence as terms (``**the**`` highlighted in
    the snippets) because the get_article pattern required verb/noun
    adjacency and nothing peeled the ``about`` bridge.
    """

    @pytest.mark.parametrize(
        ("query", "expected_path"),
        [
            ("get the article about Immanuel Kant", "immanuel kant"),
            ("get the article Immanuel Kant", "immanuel kant"),
            ("show an entry about Photosynthesis", "photosynthesis"),
            ("get article about Photosynthesis", "photosynthesis"),
            ("fetch the page on Photosynthesis", "on photosynthesis"),
            # Title-internal prepositions are still preserved (H6).
            ("get the article Lord of the Rings", "lord of the rings"),
        ],
    )
    def test_routes_to_get_article_with_clean_path(
        self, query: str, expected_path: str
    ) -> None:
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "get_article", query
        assert params.get("entry_path", "").lower() == expected_path

    def test_handler_fetches_the_article_instead_of_searching(self) -> None:
        handler, mock = _handler_with()
        mock.get_zim_entry.return_value = "# Immanuel Kant\n\nbody"
        out = handler.handle_zim_query(
            "get the article about Immanuel Kant", zim_file_path="/zims/test.zim"
        )
        assert mock.get_zim_entry.called
        assert mock.get_zim_entry.call_args.args[1].lower() == "immanuel kant"
        assert not mock.search_zim_file.called
        assert not mock.search_zim_file_data.called
        assert "body" in out


# ---------------------------------------------------------------------------
# D49: natural-order names never strong-match "Last, First | Site" titles
# ---------------------------------------------------------------------------

IEP_SUFFIX = " | Internet Encyclopedia of Philosophy"


class TestD49InvertedTitleStrongMatch:
    """IEP titles all read ``Kant, Immanuel | Internet Encyclopedia of
    Philosophy``; the order-sensitive token comparison never matched the
    natural word order every real user types, so ``tell me about
    Immanuel Kant`` rendered a plain 3-hit list while ``tell me about
    Kant, Immanuel`` reached the strong-match disambiguation.
    """

    @pytest.mark.parametrize(
        ("topic", "title"),
        [
            ("immanuel kant", "Kant, Immanuel" + IEP_SUFFIX),
            ("immanuel kant", "Kant, Immanuel"),
            ("Immanuel Kant", "Kant, Immanuel: Aesthetics" + IEP_SUFFIX),
            ("kant, immanuel", "Kant, Immanuel" + IEP_SUFFIX),
            # Site suffix alone must not dilute an otherwise exact title.
            ("measles", "Measles" + " | MedlinePlus"),
        ],
    )
    def test_inverted_and_suffixed_titles_match(self, topic: str, title: str) -> None:
        assert is_strong_title_match(topic, "iep.utm.edu/x/", title)

    @pytest.mark.parametrize(
        ("topic", "title"),
        [
            ("immanuel kant", "Hegel, Georg Wilhelm Friedrich" + IEP_SUFFIX),
            ("immanuel kant", "Kant: Aesthetics" + IEP_SUFFIX),
            ("immanuel kant", "Immanuel, Hegel" + IEP_SUFFIX),
            ("martin luther king", "Martin" + IEP_SUFFIX),
            # Inversion must not rescue a multi-comma list.
            ("john smith", "Smith, John, Jr., Sr."),
        ],
    )
    def test_unrelated_or_overreaching_titles_still_miss(
        self, topic: str, title: str
    ) -> None:
        assert not is_strong_title_match(topic, "iep.utm.edu/x/", title)

    def test_natural_order_query_reaches_disambiguation(self) -> None:
        handler, mock = _handler_with()
        mock.search_zim_file_data.return_value = {
            "results": [
                {
                    "path": "iep.utm.edu/kantaest/",
                    "title": "Kant, Immanuel: Aesthetics" + IEP_SUFFIX,
                    "snippet": "",
                },
                {
                    "path": "iep.utm.edu/kantview/",
                    "title": "Kant, Immanuel" + IEP_SUFFIX,
                    "snippet": "",
                },
                {
                    "path": "iep.utm.edu/kant-rel/",
                    "title": "Kant, Immanuel: Philosophy of Religion" + IEP_SUFFIX,
                    "snippet": "",
                },
            ]
        }
        mock.search_zim_file.return_value = "plain rendered list"
        out = handler.handle_zim_query(
            "tell me about Immanuel Kant", zim_file_path="/zims/test.zim"
        )
        assert "plain rendered list" not in out
        assert "Multiple articles match" in out
        assert "iep.utm.edu/kantview/" in out


# ---------------------------------------------------------------------------
# D50: get_zim_entries rejects the archive's own domain-shaped paths
# ---------------------------------------------------------------------------


class TestD50GetEntriesAcceptsDomainPaths:
    """Every other response prints ``Path: medlineplus.gov/measles.html``,
    but the batch extractor only accepted single-letter-namespace tokens,
    so pasting those paths back produced "Missing Entry Paths" with an
    example (``C/Photosynthesis``) that teaches a shape this archive
    does not print.
    """

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            (
                "get articles medlineplus.gov/measles.html, medlineplus.gov/rubella.html",
                ["medlineplus.gov/measles.html", "medlineplus.gov/rubella.html"],
            ),
            (
                "fetch entries iep.utm.edu/kantview/ and iep.utm.edu/kantaest/",
                ["iep.utm.edu/kantview/", "iep.utm.edu/kantaest/"],
            ),
            # Namespace-prefixed and domain-shaped paths may be mixed.
            (
                "get entries C/Photosynthesis and medlineplus.gov/measles.html",
                ["C/Photosynthesis", "medlineplus.gov/measles.html"],
            ),
            # A ZIM filename is still not an entry path.
            (
                "fetch entries A/Foo and A/Bar from wikipedia.zim",
                ["A/Foo", "A/Bar"],
            ),
            # libzim paths are case-sensitive: a mixed-case zimit path must
            # survive Rule 1's lowercasing the way ``A/...`` paths already do.
            (
                "get articles en.wikipedia.org/wiki/Immanuel_Kant and "
                "en.wikipedia.org/wiki/Georg_Hegel",
                [
                    "en.wikipedia.org/wiki/Immanuel_Kant",
                    "en.wikipedia.org/wiki/Georg_Hegel",
                ],
            ),
        ],
    )
    def test_extracts_domain_shaped_paths(
        self, query: str, expected: List[str]
    ) -> None:
        intent, params, _ = IntentParser.parse_intent(query)
        assert intent == "get_zim_entries"
        assert params.get("entries") == expected

    def test_batch_fetch_reaches_the_backend(self) -> None:
        handler, mock = _handler_with()
        mock.get_entries.return_value = "two entries"
        out = handler.handle_zim_query(
            "get articles medlineplus.gov/measles.html, medlineplus.gov/rubella.html",
            zim_file_path="/zims/test.zim",
        )
        assert "Missing Entry Paths" not in out
        entries = mock.get_entries.call_args.args[0]
        assert [e["entry_path"] for e in entries] == [
            "medlineplus.gov/measles.html",
            "medlineplus.gov/rubella.html",
        ]

    def test_missing_paths_example_teaches_both_shapes(self) -> None:
        handler, _ = _handler_with()
        out = handler.handle_zim_query("get articles", zim_file_path="/zims/test.zim")
        assert "Missing Entry Paths" in out
        assert "C/Photosynthesis" in out
        assert "medlineplus.gov/measles.html" in out
        assert "Path:" in out, "should point at the Path: lines other responses print"
