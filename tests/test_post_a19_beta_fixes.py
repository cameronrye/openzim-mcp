"""Regression tests for the post-a19 beta-test sweep (a20 fixes).

The post-a19 live-MCP sweep against the 118 GB Wikipedia ZIM after
v2.0.0a19 deployed surfaced three new user-facing defects across one
pass. Two were unlocked by a19's own fix shapes opening up code
paths the pass-2 source-level audit didn't cover; one was the
deferred-widening follow-up flagged in the post-a18 sweep.

- P1-D1: ``search for X`` silently consumes the offset from a
  cross-tool cursor. Pre-fix, a ``walk_namespace`` or
  ``browse_namespace`` cursor passed to ``search for Photosynthesis``
  decoded ``s.o=3`` into ``options["offset"]`` and search returned
  ``showing 4-6 of 4237`` instead of ``showing 1-3``. The advanced
  ``search_zim_file`` tool enforces tool-binding via
  ``Cursor.decode(expected_tool=...)``; this defect is the
  simple-tools-layer mirror of the post-a18 P1-D4 fix that landed
  for ``_handle_browse`` / ``_handle_walk_namespace``. Fix: call
  ``_cursor_tool_mismatch(options, "search_zim_file")`` at the top
  of ``_handle_search``.

- P1-D2: ``search X in namespace C`` silently consumes a cross-tool
  cursor's offset (same shape, sibling handler). Fix: call
  ``_cursor_tool_mismatch(options, "search_with_filters")`` at the
  top of ``_handle_filtered_search``. Defence-in-depth: also guard
  ``_handle_links`` (it hardcodes ``offset=0`` today so no live
  defect, but it IS a cursor-emitting handler — defending the
  boundary prevents a future offset-reading change from regressing
  silently).

- P1-D3: soft-connector footer silently suppressed when a half is a
  short (<5 ASCII char) non-Latin proper noun. ``tell me about
  Berlin and 東京`` resolved correctly to 東京 (right-promote), but
  ``_is_substantive_topic("東京")`` returned False because the
  ASCII-length-5 heuristic doesn't account for CJK ideograms
  carrying syllable-level lexical weight per character. Same shape
  for ``Köln`` (4 chars, has ö) and ``京都`` / ``北京`` / ``上海``.
  The post-a17 → a18 Unicode tail-tokenisation fix made these
  topics REACHABLE; this fix lets the chain detector + soft-
  connector footer recognise them as substantive when they're 2+
  chars and carry at least one non-ASCII letter.

Each test pins one defect; failures here mean a regression on the
specific bug.
"""

from typing import Any
from unittest.mock import MagicMock

from openzim_mcp.pagination import Cursor
from openzim_mcp.simple_tools import SimpleToolsHandler


def _encode_cursor(tool: str, **state_fields: Any) -> str:
    """Encode a v2 cursor for ``tool`` from arbitrary ``s.*`` fields.

    A single parameterised helper keeps cursor-shape knowledge in one
    place — the test surface mirrors the production encoder, where
    every cursor-emitting tool calls ``Cursor.encode(tool=..., state=...)``
    with its own ``s.*`` envelope.
    """
    return Cursor.encode(tool=tool, state=state_fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# P1-D1: search silently consumes cross-tool cursor's offset
# ---------------------------------------------------------------------------


class TestP1D1SearchCrossToolCursorRejection:
    """P1-D1: a ``walk_namespace`` / ``browse_namespace`` cursor
    passed to ``search for X`` previously decoded ``s.o`` silently
    into ``options["offset"]`` and the search returned page-2-of-
    cursor-offset results instead of its own page 1.
    """

    def test_walk_cursor_passed_to_search_is_rejected(self) -> None:
        # Pre-fix: silently applied walk's offset to the search;
        # search backend returned results 4-6 instead of 1-3.
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        handler = SimpleToolsHandler(mock)
        cursor_token = _encode_cursor(
            "walk_namespace", o=3, l=3, ns="M", ai="e048666a9e92"
        )
        out = handler.handle_zim_query(
            "search for Photosynthesis",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        assert "Cursor / Tool Mismatch" in out
        assert "walk_namespace" in out
        assert "search_zim_file" in out
        # The backend call MUST NOT have happened — the guard fires
        # before any search routing.
        assert not mock.search_zim_file_data.called
        assert not mock.search_zim_file.called

    def test_browse_cursor_passed_to_search_is_rejected(self) -> None:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        handler = SimpleToolsHandler(mock)
        cursor_token = _encode_cursor(
            "browse_namespace", o=3, l=3, ns="M", ai="e048666a9e92"
        )
        out = handler.handle_zim_query(
            "search for Berlin",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        assert "Cursor / Tool Mismatch" in out
        assert "browse_namespace" in out
        assert "search_zim_file" in out
        assert not mock.search_zim_file_data.called

    def test_same_tool_search_cursor_round_trips(self) -> None:
        # Regression guard: a ``search_zim_file`` cursor passed back
        # to ``search`` MUST still apply offset normally — the new
        # guard fires only on cross-tool reuse.
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False

        def fake_search(
            zim_file_path: str,
            query: str,
            limit: Any,
            offset: int,
        ) -> dict[str, Any]:
            return {
                "total": 100,
                "results": [],
                "page_info": {
                    "offset": offset,
                    "limit": limit or 5,
                    "returned_count": 0,
                },
                "_meta": {},
            }

        mock.search_zim_file_data.side_effect = fake_search
        handler = SimpleToolsHandler(mock)
        cursor_token = _encode_cursor(
            "search_zim_file", o=3, q="photosynthesis", ai="e048666a9e92"
        )
        out = handler.handle_zim_query(
            "search for photosynthesis",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        assert "Cursor / Tool Mismatch" not in out
        # Backend WAS called.
        assert mock.search_zim_file_data.called

    def test_search_without_cursor_unaffected(self) -> None:
        # Defence-in-depth: the guard MUST be a no-op when no cursor
        # is passed (the canonical entry path for nearly all callers).
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.search_zim_file_data.return_value = {
            "total": 0,
            "results": [],
            "_meta": {},
        }
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "search for Photosynthesis",
            zim_file_path="/x.zim",
            options={"compact": True},
        )
        assert "Cursor / Tool Mismatch" not in out
        assert mock.search_zim_file_data.called


# ---------------------------------------------------------------------------
# P1-D2: filtered_search + links silently consume cross-tool cursor
# ---------------------------------------------------------------------------


class TestP1D2FilteredSearchAndLinksCrossToolCursorRejection:
    """P1-D2: the cross-tool cursor guard widens to the other two
    cursor-emitting simple-tools handlers.

    ``_handle_filtered_search`` had the same live defect as
    ``_handle_search``: a walk cursor's offset bled into the
    filtered-search call silently.

    ``_handle_links`` hardcodes offset=0 today, so the live shape
    didn't reproduce — but the guard is added for defence-in-depth
    (consistency with the sibling handlers + future-proofing if
    offset-reading is ever added).
    """

    def test_walk_cursor_passed_to_filtered_search_is_rejected(self) -> None:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        handler = SimpleToolsHandler(mock)
        cursor_token = _encode_cursor(
            "walk_namespace", o=3, l=3, ns="M", ai="e048666a9e92"
        )
        out = handler.handle_zim_query(
            "search Berlin in namespace C",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        assert "Cursor / Tool Mismatch" in out
        assert "walk_namespace" in out
        assert "search_with_filters" in out
        # No backend call.
        assert not mock.search_with_filters_with_canonical_splice.called

    def test_walk_cursor_passed_to_links_is_rejected(self) -> None:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        # Make natural-language path resolution a no-op.
        mock.find_entry_by_title_data.return_value = {"hits": []}
        handler = SimpleToolsHandler(mock)
        cursor_token = _encode_cursor(
            "walk_namespace", o=3, l=3, ns="M", ai="e048666a9e92"
        )
        out = handler.handle_zim_query(
            "links in Photosynthesis",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        assert "Cursor / Tool Mismatch" in out
        assert "walk_namespace" in out
        assert "extract_article_links" in out
        # No backend call.
        assert not mock.extract_article_links_data.called
        assert not mock.extract_article_links.called

    def test_filtered_search_without_cursor_unaffected(self) -> None:
        # Regression guard: the canonical entry path (no cursor)
        # still routes to the backend.
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.search_with_filters_with_canonical_splice.return_value = "ok"
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "search Berlin in namespace C",
            zim_file_path="/x.zim",
            options={"compact": True},
        )
        assert "Cursor / Tool Mismatch" not in out
        assert mock.search_with_filters_with_canonical_splice.called


# ---------------------------------------------------------------------------
# P1-D3: _is_substantive_topic now recognises short non-Latin proper nouns
# ---------------------------------------------------------------------------


class TestP1D3UnicodeSubstantiveTopic:
    """P1-D3: pre-fix, ``_is_substantive_topic`` rejected ``東京``
    (2 chars), ``Köln`` (4 chars), ``京都`` etc. because the ASCII-
    length-5 heuristic ignored that non-Latin proper nouns pack
    syllable-level lexical weight into each character. This
    suppressed the soft-connector footer for ``Berlin and 東京`` /
    ``Köln and Berlin`` even when the resolver picked the right
    article.
    """

    def test_cjk_two_char_topic_is_substantive(self) -> None:
        assert SimpleToolsHandler._is_substantive_topic("東京") is True
        assert SimpleToolsHandler._is_substantive_topic("北京") is True
        assert SimpleToolsHandler._is_substantive_topic("京都") is True
        assert SimpleToolsHandler._is_substantive_topic("上海") is True

    def test_umlaut_short_topic_is_substantive(self) -> None:
        # 4-char German city names with umlauts: ``Köln``, ``Bonn`` is
        # ASCII-only so passes the existing path; this targets the
        # post-a19 non-ASCII branch.
        assert SimpleToolsHandler._is_substantive_topic("Köln") is True
        assert SimpleToolsHandler._is_substantive_topic("Ürüm") is True

    def test_short_ascii_particles_still_rejected(self) -> None:
        # Regression guard: the original a16 post-a16 D1 motivation
        # was rejecting English particles like ``Then`` / ``Both`` /
        # ``Here`` / ``Now``. Those must still be rejected.
        assert SimpleToolsHandler._is_substantive_topic("Then") is False
        assert SimpleToolsHandler._is_substantive_topic("Both") is False
        assert SimpleToolsHandler._is_substantive_topic("Here") is False
        assert SimpleToolsHandler._is_substantive_topic("Now") is False
        assert SimpleToolsHandler._is_substantive_topic("This") is False

    def test_abbreviations_still_rejected(self) -> None:
        # The pass-2 self-audit motivation for the substantive check
        # was protecting against abbreviation-then-capital false-
        # positives in chain detection: ``Dr. Strange`` should NOT
        # be treated as a chain. The ``Dr.`` half is ASCII-only and
        # under 5 chars, so the relaxed non-ASCII branch must not
        # activate.
        assert SimpleToolsHandler._is_substantive_topic("Dr.") is False
        assert SimpleToolsHandler._is_substantive_topic("St.") is False
        assert SimpleToolsHandler._is_substantive_topic("Mt.") is False
        assert SimpleToolsHandler._is_substantive_topic("Jr.") is False

    def test_single_cjk_char_still_rejected(self) -> None:
        # A single CJK character is too ambiguous (could be a particle,
        # a one-character toponym is rare in actual usage). The
        # length-≥2 minimum keeps the false-positive surface tight.
        assert SimpleToolsHandler._is_substantive_topic("京") is False
        assert SimpleToolsHandler._is_substantive_topic("北") is False

    def test_existing_long_ascii_topics_unaffected(self) -> None:
        # Regression guard: the original 5-char ASCII path still
        # works for ASCII proper nouns.
        assert SimpleToolsHandler._is_substantive_topic("Berlin") is True
        assert SimpleToolsHandler._is_substantive_topic("Tokyo") is True
        assert SimpleToolsHandler._is_substantive_topic("Apollo") is True

    def test_multi_token_topics_unaffected(self) -> None:
        # Regression guard: the ≥2-token path still wins.
        assert SimpleToolsHandler._is_substantive_topic("Big Rapids") is True
        assert SimpleToolsHandler._is_substantive_topic("Romeo and Juliet") is True

    def test_digit_topics_unaffected(self) -> None:
        # Regression guard: digit-containing short topics still pass.
        assert SimpleToolsHandler._is_substantive_topic("Apollo 11") is True
        assert SimpleToolsHandler._is_substantive_topic("1969") is True

    def test_empty_and_whitespace_rejected(self) -> None:
        assert SimpleToolsHandler._is_substantive_topic("") is False
        assert SimpleToolsHandler._is_substantive_topic("   ") is False

    def test_cyrillic_short_topic_via_existing_threshold(self) -> None:
        # ``Москва`` is 6 chars — passes the existing 5-char ASCII
        # threshold. Test included to document that Cyrillic 4-char
        # names ALSO pass the new non-ASCII branch.
        assert SimpleToolsHandler._is_substantive_topic("Москва") is True
        # 3-char Cyrillic — uncommon as a real article title, but
        # passes the relaxed non-ASCII branch (len≥2).
        assert SimpleToolsHandler._is_substantive_topic("СПб") is True

    def test_soft_connector_footer_fires_with_cjk_dropped_half(self) -> None:
        # End-to-end via the soft-connector footer: pre-fix, "Berlin
        # and 東京" returned 東京 silently; the footer was suppressed
        # because 東京 failed the substantive check, dropping the
        # chain through to the no-footer path. Post-fix, the footer
        # fires naming Berlin as the dropped half.
        handler = SimpleToolsHandler(MagicMock())
        footer = handler._soft_connector_footer(
            "Berlin and 東京",
            "東京",
            zim_file_path="/x.zim",
            top_path="東京",
        )
        assert footer is not None
        assert "Berlin" in footer
        assert "東京" in footer

    def test_soft_connector_footer_fires_with_umlaut_dropped_half(self) -> None:
        # ``Köln and Berlin``: pre-fix, Köln failed substantive
        # (4 chars), so the chain detector + footer were suppressed.
        # Post-fix, the footer fires.
        handler = SimpleToolsHandler(MagicMock())
        footer = handler._soft_connector_footer(
            "Köln and Berlin",
            "Berlin",
            zim_file_path="/x.zim",
            top_path="Berlin",
        )
        assert footer is not None
        assert "Köln" in footer
        assert "Berlin" in footer
