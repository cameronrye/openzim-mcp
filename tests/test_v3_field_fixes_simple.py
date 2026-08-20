"""v3.0.0 field-defect fixes — ``simple`` workstream.

Each class pins one defect from the 2026-08-19 real-world sweep of the
simple-mode ``zim_query`` surface (dispatcher, intent parser, cursor
handling, compact renderers). The defect ids (D42 …) refer to the
sweep's fix plan; the docstrings restate the observed behaviour so the
regression is recognisable without the report.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, Mock, patch

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import CacheConfig, ContentConfig, OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.exceptions import (
    OpenZimMcpArchivePathError,
    OpenZimMcpSecurityError,
    OpenZimMcpValidationError,
)
from openzim_mcp.mcp_envelope import is_tool_error_envelope
from openzim_mcp.pagination import Cursor, archive_identity
from openzim_mcp.security import PathValidator
from openzim_mcp.simple_tools import IntentParser, SimpleToolsHandler
from openzim_mcp.title_promotion import _candidate_forms, is_strong_title_match
from openzim_mcp.zim_operations import ZimOperations


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


class TestD49CandidateForms:
    """The suffix strip and the ``Last, First`` inversion behind
    ``is_strong_title_match`` were regexes whose adjacent quantifiers all
    accepted whitespace, so a long run of spaces made them backtrack
    polynomially (SonarCloud S8786). They are plain string splits now; this
    pins the exact spellings each candidate expands to, so the rewrite
    cannot drift from what the matcher was tuned against.
    """

    @pytest.mark.parametrize(
        ("candidate", "forms"),
        [
            # URL-shaped paths: no suffix, no comma — only themselves.
            ("medlineplus.gov/diabetes.html", ["medlineplus.gov/diabetes.html"]),
            ("iep.utm.edu/kant/", ["iep.utm.edu/kant/"]),
            # Site suffix alone.
            ("Measles | MedlinePlus", ["Measles | MedlinePlus", "Measles"]),
            # ``Last, First | Site`` expands to all three spellings.
            (
                "Kant, Immanuel" + IEP_SUFFIX,
                ["Kant, Immanuel" + IEP_SUFFIX, "Kant, Immanuel", "Immanuel Kant"],
            ),
            # The ``:`` / ``(`` tail is kept verbatim after the swapped name.
            (
                "Kant, Immanuel: Aesthetics" + IEP_SUFFIX,
                [
                    "Kant, Immanuel: Aesthetics" + IEP_SUFFIX,
                    "Kant, Immanuel: Aesthetics",
                    "Immanuel Kant: Aesthetics",
                ],
            ),
            (
                "Kant, Immanuel (1724-1804)",
                ["Kant, Immanuel (1724-1804)", "Immanuel Kant(1724-1804)"],
            ),
            # Whitespace around the comma is optional on both sides.
            ("Kant,Immanuel", ["Kant,Immanuel", "Immanuel Kant"]),
            (
                "Kant, Immanuel : Ethics",
                ["Kant, Immanuel : Ethics", "Immanuel Kant: Ethics"],
            ),
            # A multi-comma list, a ``:`` in the last-name half, and a plain
            # ``Title: Subtitle`` are not names — nothing is inverted.
            ("Smith, John, Jr., Sr.", ["Smith, John, Jr., Sr."]),
            ("Kant: Ethics, Immanuel", ["Kant: Ethics, Immanuel"]),
            (
                "Kant: Aesthetics" + IEP_SUFFIX,
                ["Kant: Aesthetics" + IEP_SUFFIX, "Kant: Aesthetics"],
            ),
            # Only the LAST pipe is a site suffix; one left inside the name
            # blocks the inversion.
            (
                "Kant, Immanuel | Foo | IEP",
                ["Kant, Immanuel | Foo | IEP", "Kant, Immanuel | Foo"],
            ),
            # An empty half never inverts.
            (", Immanuel", [", Immanuel"]),
            ("Kant,", ["Kant,"]),
            ("", [""]),
        ],
    )
    def test_forms(self, candidate: str, forms: List[str]) -> None:
        assert list(_candidate_forms(candidate)) == forms

    def test_whitespace_run_is_linear(self) -> None:
        # 20k spaces kept the old regexes backtracking for tens of seconds;
        # a string split finishes in microseconds.
        pathological = " " * 20_000 + "," + " " * 20_000
        start = time.perf_counter()
        forms = list(_candidate_forms(pathological))
        elapsed = time.perf_counter() - start
        assert forms == [pathological, ","]
        assert elapsed < 1.0, f"candidate expansion took {elapsed:.2f}s"


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


# ---------------------------------------------------------------------------
# D51: cursor mismatches were non-error markdown with two intent markers
# ---------------------------------------------------------------------------


def _archive_bound_handler() -> tuple[SimpleToolsHandler, MagicMock]:
    handler, mock = _handler_with()
    mock.path_validator.validate_path.return_value = Path("/zims/test.zim")
    mock.path_validator.validate_zim_file.return_value = Path("/zims/test.zim")
    return handler, mock


class TestD51CursorMismatchEnvelope:
    """A browse cursor handed to ``walk namespace C`` came back as
    ``isError:false`` markdown ending with BOTH ``intent=cursor_decode``
    and ``intent=walk_namespace`` markers, while an undecodable cursor
    came back as the structured ``cursor_decode`` envelope. Both are
    rejections of the same argument and must share one envelope.
    """

    @staticmethod
    def _assert_cursor_envelope(out: Any, title: str) -> None:
        assert is_tool_error_envelope(out), out
        assert out["operation"] == "cursor_decode"
        assert title in out["message"]
        assert "<!-- intent=" not in out["message"], "marker belongs to the envelope"

    def test_handler_tool_mismatch_is_the_cursor_decode_envelope(self) -> None:
        handler, mock = _handler_with()
        out = handler.handle_zim_query(
            "walk namespace C",
            zim_file_path="/zims/test.zim",
            options={"compact": True, "cursor": _browse_cursor()},
        )
        self._assert_cursor_envelope(out, "Cursor / Tool Mismatch")
        assert "browse_namespace" in out["message"]
        assert "walk_namespace" in out["message"]
        assert not mock.walk_namespace_data.called

    def test_dispatcher_foreign_cursor_guard_uses_the_same_envelope(self) -> None:
        handler, _ = _handler_with()
        out = handler.handle_zim_query(
            "find article titled Measles",
            zim_file_path="/zims/test.zim",
            options={"compact": True, "cursor": _browse_cursor()},
        )
        self._assert_cursor_envelope(out, "Cursor / Tool Mismatch")

    def test_namespace_mismatch_uses_the_same_envelope(self) -> None:
        handler, _ = _archive_bound_handler()
        cursor = Cursor.encode(
            tool="browse_namespace",
            state={  # type: ignore[typeddict-item]
                "o": 5,
                "l": 5,
                "ns": "M",
                "ai": archive_identity(Path("/zims/test.zim")),
            },
        )
        out = handler.handle_zim_query(
            "browse namespace C",
            zim_file_path="/zims/test.zim",
            options={"compact": True, "cursor": cursor},
        )
        self._assert_cursor_envelope(out, "Cursor / Namespace Mismatch")

    def test_archive_mismatch_uses_the_same_envelope(self) -> None:
        handler, _ = _archive_bound_handler()
        cursor = Cursor.encode(
            tool="browse_namespace",
            state={  # type: ignore[typeddict-item]
                "o": 5,
                "l": 5,
                "ns": "C",
                "ai": archive_identity(Path("/zims/other.zim")),
            },
        )
        out = handler.handle_zim_query(
            "browse namespace C",
            zim_file_path="/zims/test.zim",
            options={"compact": True, "cursor": cursor},
        )
        self._assert_cursor_envelope(out, "Cursor / Archive Mismatch")

    def test_article_mismatch_uses_the_same_envelope(self) -> None:
        handler, _ = _archive_bound_handler()
        cursor = Cursor.encode(
            tool="extract_article_links",
            state={  # type: ignore[typeddict-item]
                "o": 25,
                "l": 25,
                "ep": "A/Photosynthesis",
                "k": "internal",
                "ai": archive_identity(Path("/zims/test.zim")),
            },
        )
        out = handler.handle_zim_query(
            "links in Berlin",
            zim_file_path="/zims/test.zim",
            options={"compact": True, "cursor": cursor},
        )
        self._assert_cursor_envelope(out, "Cursor / Article Mismatch")

    def test_undecodable_cursor_keeps_its_envelope(self) -> None:
        handler, _ = _handler_with()
        out = handler.handle_zim_query(
            "walk namespace C",
            zim_file_path="/zims/test.zim",
            options={"compact": True, "cursor": "garbage!!"},
        )
        assert is_tool_error_envelope(out)
        assert out["operation"] == "cursor_decode"


# ---------------------------------------------------------------------------
# D52: binary intent's not-found error leaked internal API names
# ---------------------------------------------------------------------------


class TestD52BinaryNotFoundRecovery:
    """``get pdf easy-to-read-materials`` fell to the generic "Error
    Processing Query" envelope carrying the backend's hint "Try using
    search_zim_file() ... or browse_namespace()" — function names that
    are not tools in simple mode. Every sibling entry-taking handler
    routes not-found through ``_render_not_found_recovery``; binary was
    the only one without it, and its missing-path tip named
    ``extract_article_links`` verbatim.
    """

    BACKEND_HINT = (
        "Entry not found: easy-to-read-materials. Try using search_zim_file() "
        "to find available entries, or browse_namespace() to explore the "
        "file structure."
    )

    def test_not_found_uses_the_natural_language_recovery_block(self) -> None:
        handler, mock = _handler_with()
        mock.get_binary_entry.side_effect = Exception(self.BACKEND_HINT)
        out = handler.handle_zim_query(
            "get pdf easy-to-read-materials", zim_file_path="/zims/test.zim"
        )
        assert "Error Processing Query" not in out
        assert "search_zim_file()" not in out
        assert "browse_namespace()" not in out
        assert "Check server logs" not in out
        assert "search for easy-to-read-materials" in out
        assert "suggestions for easy-to-read-materials" in out
        assert "<!-- intent=binary" in out

    def test_invalid_request_uses_the_sibling_shape(self) -> None:
        handler, mock = _handler_with()
        mock.get_binary_entry.side_effect = OpenZimMcpValidationError(
            "max_size_bytes must be positive"
        )
        out = handler.handle_zim_query(
            "get pdf easy-to-read-materials", zim_file_path="/zims/test.zim"
        )
        assert "Error Processing Query" not in out
        assert "max_size_bytes must be positive" in out

    def test_archive_level_failure_still_reaches_the_path_envelope(self) -> None:
        handler, mock = _handler_with()
        mock.get_binary_entry.side_effect = OpenZimMcpArchivePathError(
            "File does not exist: /zims/missing.zim"
        )
        out = _text(
            handler.handle_zim_query(
                "get pdf easy-to-read-materials", zim_file_path="/zims/missing.zim"
            )
        )
        assert "ZIM File Not Found" in out or "Error Processing Query" in out
        assert "Article not found" not in out

    def test_missing_path_tip_names_a_simple_mode_operation(self) -> None:
        handler, _ = _handler_with()
        out = handler.handle_zim_query(
            "get binary content", zim_file_path="/zims/test.zim"
        )
        assert "Missing Entry Path" in out
        assert "extract_article_links" not in out
        assert "links in" in out


# ---------------------------------------------------------------------------
# D53: docstring says compact defaults True "in simple mode" only
# ---------------------------------------------------------------------------


class TestD53CompactDefaultWording:
    """One registration serves both modes and declares ``compact: bool =
    True``, so the schema default is ``true`` in advanced mode too; the
    description's "(default in simple mode)" implied a mode split that
    does not exist.
    """

    def test_description_does_not_claim_a_mode_specific_default(self) -> None:
        block = _description_arg_block("compact")
        assert "default in simple mode" not in block
        assert "default" in block.lower()

    def test_registered_default_is_true(self) -> None:
        import inspect

        from openzim_mcp.tools import zim_query as zim_query_module

        # The registration closes over ``server``; read the default off the
        # inner function's source rather than spinning up a server.
        source = inspect.getsource(zim_query_module.register)
        assert "compact: bool = True" in source


# ---------------------------------------------------------------------------
# D58: path-resolution / security failures delivered as isError=False
# ---------------------------------------------------------------------------


class TestD58PathFailuresAreErrorEnvelopes:
    """For the identical out-of-sandbox path, zim_metadata returned the
    structured envelope (isError=True) while zim_query returned a plain
    "ZIM File Not Found" string on the success path — and the same for
    ".." traversal, a missing file, and every other zim_file_path
    failure. In simple mode zim_query is the only tool, so a client had
    no isError signal for any security denial. The friendly markdown
    stays; it now rides in the envelope's ``message``.
    """

    def _two_archive_handler(self) -> tuple[SimpleToolsHandler, MagicMock]:
        handler, mock = _handler_with()
        mock.list_zim_files_data.return_value = [{"path": MEDLINE}, {"path": IEP}]
        return handler, mock

    def test_security_denial_is_an_error_envelope_with_the_guidance(self) -> None:
        handler, mock = self._two_archive_handler()
        mock.get_main_page.side_effect = OpenZimMcpSecurityError(
            "Access denied - Path is outside allowed directories"
        )
        out = handler.handle_zim_query("show main page", zim_file_path="/etc/hosts")
        assert is_tool_error_envelope(out), out
        assert out["operation"] == "zim_path_not_found"
        assert "ZIM File Not Found" in out["message"]
        assert "outside allowed directories" in out["message"]
        assert MEDLINE in out["message"], "recovery hint must still list archives"
        assert "<!-- intent=" not in out["message"]

    def test_missing_file_is_an_error_envelope(self) -> None:
        handler, mock = self._two_archive_handler()
        mock.get_main_page.side_effect = Exception(
            "File does not exist: /zims/totally-fake.zim"
        )
        out = handler.handle_zim_query(
            "show main page", zim_file_path="/zims/totally-fake.zim"
        )
        assert is_tool_error_envelope(out), out
        assert out["operation"] == "zim_path_not_found"
        assert "ZIM File Not Found" in out["message"]

    def test_traversal_rejection_is_an_error_envelope(self) -> None:
        handler, mock = self._two_archive_handler()
        mock.get_main_page.side_effect = OpenZimMcpSecurityError(
            "Path contains suspicious pattern: .."
        )
        out = handler.handle_zim_query(
            "show main page", zim_file_path="/zims/../zims/x.zim"
        )
        assert is_tool_error_envelope(out), out
        assert out["operation"] == "zim_query"
        assert "Error Processing Query" in out["message"]
        assert "suspicious pattern" in out["message"]

    def test_successful_calls_are_untouched(self) -> None:
        handler, mock = _handler_with()
        mock.get_main_page.return_value = "# Main\n\nbody"
        out = handler.handle_zim_query("show main page", zim_file_path="/zims/test.zim")
        assert isinstance(out, str)
        assert "body" in out


# ---------------------------------------------------------------------------
# R2-4 (D47 residual): suggestions signalled a continuation that did not exist
# ---------------------------------------------------------------------------


def _suggestion_ops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ZimOperations:
    """A real ``ZimOperations`` with path validation and the archive stat
    token stubbed out so the suggestion pipeline runs end to end against
    a mocked archive."""
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=1000, snippet_length=100),
    )
    ops = ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(snippet_length=100),
    )
    monkeypatch.setattr(ops, "_validate_zim_path", lambda p: Path("/zim/test.zim"))
    monkeypatch.setattr("openzim_mcp.bundle.archive_stat_token", lambda p: "tok")
    return ops


def _strategy1_pool(size: int) -> Any:
    """A Strategy 1 stub that honours ``limit`` over a pool of ``size`` titles."""

    def fake(archive: Any, partial_query: str, limit: int) -> List[Dict[str, str]]:
        return [
            {
                "text": f"Diabetes {i}",
                "path": f"C/Diabetes_{i}",
                "type": "search_start_match",
            }
            for i in range(min(size, limit))
        ]

    return fake


class TestR24SuggestionsContinuationIsReal:
    """``suggestions for diab`` with ``limit=3`` returned ``done: false``,
    ``next_cursor: null`` and ``_meta.reason =
    suggestion_total_is_lower_bound`` — a continuation signal with no
    continuation mechanism (the backend takes no offset or cursor, and
    ``offset=3`` replayed page one). A full page was *assumed* to mean
    more exist; the backend never looked. Now it over-fetches by one:
    when nothing lies beyond the page the payload is ``done: true`` with
    no lower-bound reason, and when more do exist ``done: false`` comes
    with ``page_info.total_is_lower_bound`` and an explicit
    ``_meta.hint`` naming the only continuation that works (raise
    ``limit``; at the cap, narrow the prefix).
    """

    def _data(self, ops: ZimOperations, limit: int) -> Dict[str, Any]:
        with patch("openzim_mcp.zim_operations.zim_archive") as zim_archive:
            zim_archive.return_value.__enter__.return_value = MagicMock()
            return dict(ops.get_search_suggestions_data("/zim/test.zim", "diab", limit))

    def test_more_beyond_the_page_yields_an_actionable_continuation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ops = _suggestion_ops(tmp_path, monkeypatch)
        monkeypatch.setattr(ops, "_get_suggestions_from_search", _strategy1_pool(10))
        out = self._data(ops, limit=3)
        assert out["page_info"]["returned_count"] == 3
        assert out["page_info"]["limit"] == 3
        assert out["done"] is False
        assert out["page_info"]["total_is_lower_bound"] is True
        assert out["_meta"]["reason"] == "suggestion_total_is_lower_bound"
        hint = out["_meta"]["hint"]
        assert "limit" in hint, hint
        assert "50" in hint, hint
        assert "offset" in hint, "must say why offset is not the continuation"

    def test_exactly_limit_matches_is_done(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ops = _suggestion_ops(tmp_path, monkeypatch)
        monkeypatch.setattr(ops, "_get_suggestions_from_search", _strategy1_pool(3))
        out = self._data(ops, limit=3)
        assert out["page_info"]["returned_count"] == 3
        assert out["done"] is True
        assert "reason" not in out["_meta"]
        assert "hint" not in out["_meta"]
        assert "total_is_lower_bound" not in out["page_info"]

    def test_short_page_is_done(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ops = _suggestion_ops(tmp_path, monkeypatch)
        monkeypatch.setattr(ops, "_get_suggestions_from_search", _strategy1_pool(2))
        out = self._data(ops, limit=3)
        assert out["page_info"]["returned_count"] == 2
        assert out["done"] is True
        assert "reason" not in out["_meta"]
        assert "hint" not in out["_meta"]

    def test_at_the_cap_the_hint_narrows_instead_of_raising(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ops = _suggestion_ops(tmp_path, monkeypatch)
        monkeypatch.setattr(ops, "_get_suggestions_from_search", _strategy1_pool(60))
        out = self._data(ops, limit=50)
        assert out["page_info"]["returned_count"] == 50
        assert out["done"] is False
        hint = out["_meta"]["hint"]
        assert "prefix" in hint, hint
        assert "larger" not in hint, "limit is already at the cap"

    def test_canonical_prepend_that_evicts_a_row_is_not_done(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The D6 canonical probe prepends a row and trims back to
        ``limit``; the evicted row is a real suggestion beyond the page."""
        ops = _suggestion_ops(tmp_path, monkeypatch)
        monkeypatch.setattr(ops, "_get_suggestions_from_search", _strategy1_pool(3))
        monkeypatch.setattr(
            ops,
            "_find_canonical_prefix_match",
            lambda *a, **kw: {"text": "Diab", "path": "C/Diab", "type": "canonical"},
        )
        out = self._data(ops, limit=3)
        assert [r["text"] for r in out["results"]] == [
            "Diab",
            "Diabetes 0",
            "Diabetes 1",
        ]
        assert out["done"] is False
        assert "hint" in out["_meta"]

    def test_title_index_fallback_detects_overflow_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Strategy 2 (SuggestionSearcher) gets the same over-fetch."""
        ops = _suggestion_ops(tmp_path, monkeypatch)
        monkeypatch.setattr(ops, "_get_suggestions_from_search", lambda *a, **kw: [])
        paths = [f"C/Diabetes_{i}" for i in range(8)]

        def entry_for(path: str) -> MagicMock:
            entry = MagicMock()
            entry.path = path
            entry.title = path[2:].replace("_", " ")
            return entry

        archive = MagicMock()
        archive.get_entry_by_path.side_effect = entry_for
        with (
            patch("openzim_mcp.zim_operations.zim_archive") as zim_archive,
            patch("openzim_mcp.zim_operations.SuggestionSearcher") as searcher_cls,
        ):
            zim_archive.return_value.__enter__.return_value = archive
            suggest = MagicMock()
            suggest.getEstimatedMatches.return_value = len(paths)
            suggest.getResults.return_value = paths
            searcher_cls.return_value.suggest.return_value = suggest
            full = dict(ops.get_search_suggestions_data("/zim/test.zim", "diab", 3))
            whole = dict(ops.get_search_suggestions_data("/zim/test.zim", "diab", 8))

        assert full["page_info"]["returned_count"] == 3
        assert full["done"] is False
        assert "hint" in full["_meta"]
        assert whole["page_info"]["returned_count"] == 8
        assert whole["done"] is True
        assert "hint" not in whole["_meta"]


class TestR24FindByTitleDoesNotClaimCompleteness:
    """Mirror image on ``find article titled``: the assembler trimmed the
    aggregate to ``limit`` and stamped ``done: true`` regardless, so a
    trimmed page claimed the set was exhausted. Trimming now yields
    ``done: false`` with the same lower-bound flag and ``limit`` hint;
    an untrimmed page keeps ``done: true``.
    """

    def _rows(self, n: int) -> List[Dict[str, Any]]:
        return [
            {
                "path": f"C/Diabetes_{i}",
                "title": f"Diabetes {i}",
                "score": 1.0 - i / 100,
                "zim_file": "/zim/test.zim",
                "match_type": "fuzzy_suggest",
            }
            for i in range(n)
        ]

    def _assemble(
        self, ops: ZimOperations, rows: List[Dict[str, Any]], limit: int
    ) -> Dict[str, Any]:
        return dict(
            ops._assemble_find_response(
                rows,
                title="diabetes",
                limit=limit,
                files=["/zim/test.zim"],
                fast_path_hit=False,
                fuzzy_path_hit=True,
                verified_variants=[],
            )
        )

    def test_trimmed_page_is_not_done(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ops = _suggestion_ops(tmp_path, monkeypatch)
        out = self._assemble(ops, self._rows(5), limit=3)
        assert out["page_info"]["returned_count"] == 3
        assert out["total"] == 3
        assert out["done"] is False
        assert out["page_info"]["total_is_lower_bound"] is True
        hint = out["_meta"]["hint"]
        assert "limit" in hint, hint
        assert "50" in hint, hint

    def test_untrimmed_page_is_done(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ops = _suggestion_ops(tmp_path, monkeypatch)
        for n in (2, 3):
            out = self._assemble(ops, self._rows(n), limit=3)
            assert out["page_info"]["returned_count"] == n
            assert out["done"] is True
            assert "hint" not in out["_meta"]
            assert "total_is_lower_bound" not in out["page_info"]

    def test_title_index_probe_looks_one_past_the_page(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The suggestion-index fallback pulled exactly ``limit`` rows, so
        the assembler never saw a trim: ``limit=3`` claimed ``done`` while
        ``limit=10`` returned ten. Pull one extra so a full page is only
        ``done`` when the index really had nothing more."""
        ops = _suggestion_ops(tmp_path, monkeypatch)
        monkeypatch.setattr(ops, "_fast_path_row", lambda *a, **kw: None)
        paths = [f"C/Diabetes_{i}" for i in range(10)]

        def entry_for(path: str) -> MagicMock:
            entry = MagicMock()
            entry.path = path
            entry.title = path[2:].replace("_", " ")
            entry.is_redirect = False
            return entry

        archive = MagicMock()
        archive.get_entry_by_path.side_effect = entry_for
        suggest = MagicMock()
        suggest.getEstimatedMatches.return_value = len(paths)
        suggest.getResults.side_effect = lambda start, count: paths[
            start : start + count
        ]
        with (
            patch("openzim_mcp.zim_operations.zim_archive") as zim_archive,
            patch("openzim_mcp.zim_operations.SuggestionSearcher") as searcher_cls,
        ):
            zim_archive.return_value.__enter__.return_value = archive
            searcher_cls.return_value.suggest.return_value = suggest
            page = dict(
                ops.find_entry_by_title_data("/zim/test.zim", "diabetes", limit=3)
            )
            whole = dict(
                ops.find_entry_by_title_data("/zim/test.zim", "diabetes", limit=10)
            )

        assert page["page_info"]["returned_count"] == 3
        assert page["done"] is False
        assert "hint" in page["_meta"]
        assert whole["page_info"]["returned_count"] == 10
        assert whole["done"] is True
        assert "hint" not in whole["_meta"]
