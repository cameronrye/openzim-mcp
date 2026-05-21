"""Regression tests for the post-a18 beta-test sweep (a19 fixes).

The post-a18 live-MCP sweep against the 118 GB Wikipedia ZIM after
the post-a17 fixes deployed surfaced three new defects (two
EXPOSED by a18's Unicode tail-tokenisation fix that couldn't have
been reproduced before; one DEFERRED from the post-a17 sweep):

- P3-D1: ``musicians from München`` resolved correctly via the
  new Unicode tail probe to Munich, then subject-attribute
  decomposition fired on the Notable people section. But the
  section content is two H3 sub-tables (``Born in Munich`` /
  ``Notable residents``) which compact mode renders as
  ``[Table N: M rows x P cols - pass compact=False to expand]``
  placeholders. The LLM gets zero substantive content from a
  query that should list musicians — the exact hallucination
  shape wave 4's empty-lead fallback was designed to prevent.
  Fix: detect placeholder dominance in
  ``_maybe_render_subject_section`` and substitute a
  ``compact=False`` recovery pointer instead of returning
  table placeholders as data.

- P3-D2: ``tell me about Berlin and München`` resolved correctly
  to Munich (right-promote), but the soft-connector footer was
  silently suppressed. The substring check ``"berlin" in
  "munich"`` is False, ``"münchen" in "munich"`` is also False
  (German ``München`` is the alias of English ``Munich``;
  substring matching can't see through that), so
  ``left_in == right_in == False`` hit the "neither in title —
  unclear which was picked" suppression. User doesn't learn
  Berlin was dropped. Fix: when both halves fail substring, fall
  back to title-alias probing — if a half's title-index hit
  resolves to ``top_path``, treat it as "in title".

- P1-D4 (deferred from post-a17 sweep): ``browse namespace M``
  silently accepts cursors emitted by ``walk_namespace`` — the
  simple-tools dispatcher decoded ``s.o`` and ``s.ns`` from any
  decoded cursor, ignoring ``s.t`` (issuing tool). The advanced
  tools already enforce tool-binding via
  ``Cursor.decode(expected_tool=...)``; this restores the check
  at the simple-tools handler edge by stashing ``_cursor_t`` and
  adding ``_cursor_tool_mismatch``, which both browse and walk
  handlers fire.

Each test pins one defect; failures here mean a regression on
the specific bug.
"""

from typing import Any
from unittest.mock import MagicMock

from openzim_mcp.pagination import Cursor
from openzim_mcp.simple_tools import SimpleToolsHandler

# ---------------------------------------------------------------------------
# P3-D1: subject-attribute section dominated by table placeholders falls
# back to a ``compact=False`` recovery pointer
# ---------------------------------------------------------------------------


class TestP3D1TableDominatedSubjectAttribute:
    """P3-D1: when subject-attribute decomposition would otherwise
    return a section body whose only substantive content is table
    placeholders, surface a ``compact=False`` recovery pointer
    instead. The placeholder strings carry no information for the
    LLM and otherwise trigger the same hallucination shape wave 4
    was built to prevent.
    """

    def _make_handler_for_subject_section(
        self,
        *,
        topic: str,
        top_title: str,
        section_text: str,
        section_id: str,
        section_body: str,
    ) -> SimpleToolsHandler:
        """Wire a SimpleToolsHandler to a mock that reaches the
        subject-attribute path and returns ``section_body`` as the
        section's ``content_markdown``.
        """
        path = top_title.replace(" ", "_")
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.search_zim_file_data.return_value = {
            "results": [{"path": path, "title": top_title}],
            "total": 1,
        }
        mock.get_zim_entry.return_value = "stub-body"
        mock.find_entry_by_title_data.return_value = {
            "results": [{"path": path, "title": top_title, "score": 1.0}],
            "total": 1,
        }
        # Article structure for the section-resolution probe — the
        # target H2 must be in the article and its id used downstream.
        mock.get_article_structure_data.return_value = {
            "headings": [
                {"level": 2, "text": section_text, "id": section_id},
            ],
        }
        # The section_data call returns the markdown that
        # _maybe_render_subject_section then inspects for table-
        # placeholder dominance.
        mock.get_section_data.return_value = {
            "content_markdown": section_body,
        }
        return SimpleToolsHandler(mock)

    def test_table_dominated_section_falls_back_to_compact_false_pointer(
        self,
    ) -> None:
        # Mimic Munich's Notable people section as it actually came
        # back live: two H3 sub-tables that compact mode stripped to
        # placeholders, with only the H3 headings as substantive
        # text. Without the fix the LLM would get zero useful
        # content. With the fix it gets a direct compact=False
        # recovery pointer.
        section_body = (
            "### Born in Munich\n\n"
            "[Table 8: 1 rows x 2 cols - pass compact=False to expand]\n\n"
            "### Notable residents\n\n"
            "[Table 9: 1 rows x 2 cols - pass compact=False to expand]\n"
        )
        handler = self._make_handler_for_subject_section(
            topic="musicians from München",
            top_title="Munich",
            section_text="Notable people",
            section_id="Notable_people",
            section_body=section_body,
        )
        out = handler.handle_zim_query(
            "tell me about musicians from München",
            zim_file_path="/x.zim",
            options={"compact": True},
        )
        # The fix surfaces a clear recovery message and DOES NOT
        # embed the table placeholders in the response body. The
        # subject_attribute_section telemetry marker should still
        # fire so callers can distinguish this branch from the
        # plain lead path.
        assert "[Table" not in out, (
            "table placeholders must be substituted by the "
            "compact=False recovery pointer, not surfaced as data"
        )
        assert "compact=False" in out
        assert "tell me about Munich" in out or "get section" in out
        assert "intent=subject_attribute_section" in out

    def test_section_with_real_prose_plus_one_table_still_returns_body(
        self,
    ) -> None:
        # Regression guard: a section with ONE table placeholder but
        # ALSO substantial prose (>= 100 chars of real content)
        # should NOT trigger the recovery pointer. The fix is for
        # sections where placeholders ARE the content.
        prose = (
            "Vienna's music tradition stretches from the Habsburg "
            "court through Mozart and Beethoven to the Second "
            "Viennese School. Today the city hosts the Vienna "
            "Philharmonic and the Wiener Staatsoper, two of the "
            "world's most prestigious music institutions, alongside "
            "an annual New Year's concert broadcast globally."
        )
        section_body = (
            f"{prose}\n\n" "[Table 3: 5 rows x 2 cols - pass compact=False to expand]\n"
        )
        handler = self._make_handler_for_subject_section(
            topic="musicians from Vienna",
            top_title="Vienna",
            section_text="Music",
            section_id="Music",
            section_body=section_body,
        )
        out = handler.handle_zim_query(
            "tell me about musicians from Vienna",
            zim_file_path="/x.zim",
            options={"compact": True},
        )
        # Body returned as-is (with placeholder pass-through). The
        # caller sees the prose AND a hint that one table was
        # stripped — that's the expected behaviour for a mixed
        # section.
        assert "Habsburg" in out
        assert "intent=subject_attribute_section" in out

    def test_section_with_zero_tables_unchanged(self) -> None:
        # Regression guard: no placeholders at all → no fallback.
        section_body = (
            "Tokyo has produced major contemporary musicians "
            "across genres including Ryuichi Sakamoto, Hikaru "
            "Utada, and many J-pop / city-pop figures."
        )
        handler = self._make_handler_for_subject_section(
            topic="musicians from Tokyo",
            top_title="Tokyo",
            section_text="Notable people",
            section_id="Notable_people",
            section_body=section_body,
        )
        out = handler.handle_zim_query(
            "tell me about musicians from Tokyo",
            zim_file_path="/x.zim",
            options={"compact": True},
        )
        assert "Ryuichi Sakamoto" in out
        assert "compact=False" not in out


# ---------------------------------------------------------------------------
# P3-D2: soft-connector recognises non-Latin halves via title-alias probe
# ---------------------------------------------------------------------------


class TestP3D2SoftConnectorAliasFallback:
    """P3-D2: when both halves of a soft-connector topic fail the
    substring-in-title check (typically because the resolved title
    is an English-aliased form of a non-Latin half — München ->
    Munich), fall back to title-alias probing. If a half's
    title-index hit resolves to ``top_path``, treat that half as
    "in title".
    """

    def _make_handler(
        self,
        *,
        top_title: str,
        alias_map: dict[str, str],
    ) -> SimpleToolsHandler:
        """Wire mocks so the search returns ``top_title`` for any
        query and the title index resolves each key in
        ``alias_map`` to the path value.
        """
        path = top_title.replace(" ", "_")
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        mock.search_zim_file_data.return_value = {
            "results": [{"path": path, "title": top_title}],
            "total": 1,
        }
        mock.get_zim_entry.return_value = "stub-body"

        def find_by_title(
            zim_file_path: str,
            title: str,
            *,
            cross_file: bool = False,
            limit: int = 3,
        ) -> dict[str, Any]:
            resolved_path = alias_map.get(title.lower())
            if resolved_path is None:
                return {"results": [], "total": 0}
            return {
                "results": [
                    {
                        "path": resolved_path,
                        "title": resolved_path.replace("_", " "),
                        "score": 1.0,
                    }
                ],
                "total": 1,
            }

        mock.find_entry_by_title_data.side_effect = find_by_title
        return SimpleToolsHandler(mock)

    def test_non_latin_half_resolves_via_alias_and_footer_fires(self) -> None:
        # ``Berlin and München`` resolved (via the Unicode tail probe
        # landed in a18) to Munich. Substring check fails for both:
        # ``berlin not in munich`` and ``münchen not in munich``.
        # Pre-fix: ``left_in == right_in == False`` → suppress.
        # User never learns Berlin was dropped. Post-fix: title
        # index probe sees ``München -> Munich``, so right_in becomes
        # True, footer fires correctly naming Berlin as the dropped
        # half.
        handler = self._make_handler(
            top_title="Munich",
            alias_map={"münchen": "Munich", "berlin": "Berlin"},
        )
        out = handler.handle_zim_query(
            "tell me about Berlin and München",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "query contained" in out, (
            "soft-connector footer must fire when one half resolves "
            "via title alias to the returned top_path"
        )
        # Sub-D-2 Rule 1 lowercases topics before the footer is built.
        assert "berlin" in out
        assert "tell me about berlin" in out

    def test_neither_half_resolves_via_alias_still_suppresses(self) -> None:
        # Defensive: when neither half's title-alias resolves to
        # ``top_path``, the fallback returns False for both and the
        # legacy "neither in title — unclear which was picked"
        # suppression still applies. No footer.
        handler = self._make_handler(
            top_title="Munich",
            # Neither half resolves to "Munich" via the title index.
            alias_map={
                "berlin": "Berlin",
                "lyon": "Lyon",
            },
        )
        out = handler.handle_zim_query(
            "tell me about Berlin and Lyon",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        assert "query contained" not in out

    def test_legacy_substring_path_still_works_without_zim_kwargs(
        self,
    ) -> None:
        # Defensive: when ``_soft_connector_footer`` is called via the
        # legacy positional-only signature (no zim_file_path /
        # top_path kwargs), the alias fallback can't run and the
        # substring-only behaviour remains in effect. Existing call
        # sites that didn't get migrated MUST not start crashing.
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        handler = SimpleToolsHandler(mock)
        # Title contains both halves → suppressed by the original
        # left_in == right_in == True branch.
        result = handler._soft_connector_footer("Romeo and Juliet", "Romeo and Juliet")
        assert result is None
        # Right half matches via substring → footer fires.
        result = handler._soft_connector_footer("Berlin and Paris", "Paris")
        assert result is not None
        assert "Berlin" in result


# ---------------------------------------------------------------------------
# P1-D4 (deferred from a17): cross-tool cursor reuse rejected at
# simple-tools handler edge
# ---------------------------------------------------------------------------


class TestP1D4CrossToolCursorRejection:
    """P1-D4 (deferred from post-a17 sweep): a cursor issued by
    ``walk_namespace`` previously walked browse silently because the
    simple-tools dispatcher decoded only ``s.o`` and ``s.ns`` from
    the cursor; ``s.t`` (issuing tool) was ignored. The advanced
    tools already enforce tool-binding via
    ``Cursor.decode(expected_tool=...)``; this restores the check
    at the simple-tools handler edge.
    """

    def _encode_walk_cursor(
        self, *, offset: int, limit: int, namespace: str, ai: str
    ) -> str:
        state: dict[str, Any] = {
            "o": offset,
            "l": limit,
            "ns": namespace,
            "ai": ai,
        }
        return Cursor.encode(tool="walk_namespace", state=state)  # type: ignore[arg-type]

    def _encode_browse_cursor(
        self, *, offset: int, limit: int, namespace: str, ai: str
    ) -> str:
        state: dict[str, Any] = {
            "o": offset,
            "l": limit,
            "ns": namespace,
            "ai": ai,
        }
        return Cursor.encode(tool="browse_namespace", state=state)  # type: ignore[arg-type]

    def test_walk_cursor_passed_to_browse_is_rejected(self) -> None:
        # Pre-fix: silently walked browse from walk's offset (=3 for
        # the canonical reproducer), returning entries 4-6 of the M
        # namespace and emitting a fresh ``browse_namespace`` cursor
        # as if nothing was wrong. Post-fix: the handler returns a
        # structured Cursor / Tool Mismatch error before any
        # backend call.
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        handler = SimpleToolsHandler(mock)
        cursor_token = self._encode_walk_cursor(
            offset=3, limit=3, namespace="M", ai="e048666a9e92"
        )
        out = handler.handle_zim_query(
            "browse namespace M",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        assert "Cursor / Tool Mismatch" in out
        assert "walk_namespace" in out
        assert "browse_namespace" in out
        # The backend call must NOT have happened.
        assert not mock.browse_namespace.called
        assert not mock.browse_namespace_data.called

    def test_browse_cursor_passed_to_walk_is_rejected(self) -> None:
        # Defence-in-depth: walk's own handler rejects browse cursors
        # too (same shape, opposite direction).
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        handler = SimpleToolsHandler(mock)
        cursor_token = self._encode_browse_cursor(
            offset=3, limit=3, namespace="M", ai="e048666a9e92"
        )
        out = handler.handle_zim_query(
            "walk namespace M",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        assert "Cursor / Tool Mismatch" in out
        assert "browse_namespace" in out
        assert "walk_namespace" in out
        assert not mock.walk_namespace.called
        assert not mock.walk_namespace_data.called

    def test_same_tool_cursor_round_trip_still_works(self) -> None:
        # Regression guard: a walk_namespace cursor passed back to
        # walk_namespace must STILL round-trip cleanly (the P1-D3
        # fix that landed in a18). The new tool-mismatch check
        # should fire ONLY on cross-tool reuse.
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        captured: dict[str, Any] = {}

        def fake_walk(
            zim_file_path: str,
            namespace: str,
            *,
            cursor_state: Any = None,
            limit: int = 200,
        ) -> dict[str, Any]:
            captured["cursor_state"] = cursor_state
            return {
                "namespace": namespace,
                "results": [],
                "next_cursor": None,
                "total": 12,
                "done": True,
                "page_info": {
                    "offset": 3,
                    "limit": limit,
                    "returned_count": 0,
                },
                "discovery_method": "full_iteration",
                "sampling_based": False,
                "results_may_be_incomplete": False,
            }

        mock.walk_namespace_data.side_effect = fake_walk
        handler = SimpleToolsHandler(mock)
        cursor_token = self._encode_walk_cursor(
            offset=3, limit=3, namespace="M", ai="e048666a9e92"
        )
        out = handler.handle_zim_query(
            "walk namespace M",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        # No tool-mismatch error; backend was called with the
        # rebuilt cursor_state carrying ai/ns.
        assert "Cursor / Tool Mismatch" not in out
        assert captured.get("cursor_state") is not None
        assert captured["cursor_state"]["ai"] == "e048666a9e92"
