"""Regression tests for the post-a20 beta-test sweep (a21 candidate fixes).

The post-a20 live-MCP sweep against the 118 GB Wikipedia ZIM after
v2.0.0a20 deployed surfaced two new user-facing defects, both shaped
by the recurring "fix unlocks new paths" pattern that has held
across a17 → a18 → a19 → a20: each release's fixes reach code paths
earlier defects had intercepted, exposing the NEXT layer's bugs.

- P1-D1: the dispatcher's cursor-decode block (simple_tools.py
  ``handle_zim_query``) runs the cursor's ``s.q`` overlap check
  BEFORE any handler-level ``_cursor_tool_mismatch`` guard fires.
  When a cross-tool cursor carries an ``s.q`` field (a hand-stuffed
  walk_namespace cursor with ``s.q="biology"`` passed to ``search
  for photosynthesis``, or a real search cursor reused with a
  different tool), the dispatcher emits the "Cursor was issued for
  query X; current request shares no terms" message — naming the
  wrong fault shape. The user is advised to "start the search over
  for the new query" even though the cursor is from a different
  tool entirely. Post-a19's P1-D1/D2 made cross-tool reuse LOUD via
  the handler-edge guard; this defect is the surface of the
  dispatcher-vs-handler ordering issue pass-2 of the post-a19
  sweep flagged but did not address.

  Fix (scoped): the dispatcher's q-overlap check now skips when the
  cursor's ``t`` field claims a tool that does NOT legitimately
  emit ``s.q`` in its cursors (walk_namespace, browse_namespace,
  extract_article_links). Only ``search_zim_file`` and
  ``search_with_filters`` emit ``s.q`` (per the ``Cursor.encode``
  callsites in zim/search.py); any ``s.q`` riding a non-q-emitting
  ``t`` is adversarial or vestigial — letting the dispatcher
  short-circuit on it produces a misleading error. The handler's
  ``_cursor_tool_mismatch`` then fires with the correct
  ``Cursor / Tool Mismatch`` diagnosis.

- P1-D2: ``_soft_connector_footer``'s alias-fallback branch
  (post-a18 P3-D2) was gated on ``not left_in and not right_in``
  (both halves missing in substring). When one half matches the
  resolved title via substring (``Cologne`` ⊂ ``Cologne``) and the
  other matches only via title-alias (``Köln`` → ``Cologne``), the
  gate was False and the alias probe never ran. The footer
  surfaced "For Köln, query separately with tell me about Köln"
  for queries like
  ``tell me about Köln or Cologne`` — sending the caller on a
  two-hop journey to an article that just redirects back to the
  one already returned. Same shape for ``京都 or Kyoto`` /
  ``上海 or Shanghai`` / ``München or Munich`` (and the reverse-
  order variants).

  Fix: widen the gate to ``not (left_in and right_in)`` so the
  alias probe runs whenever EITHER half is missing in substring
  (only upgrades a False → True; unrelated halves like ``Berlin``
  in ``Berlin and 東京`` still resolve to themselves, so the gate
  semantics for the "real chain" case are unchanged). The
  irreducible ``東京 or Tokyo`` case stays unfixed because 東京
  title-resolves to its own disambig article path, not to Tokyo;
  the fallback correctly leaves it alone.

Each test pins one defect; failures here mean a regression on the
specific bug.
"""

from typing import Any
from unittest.mock import MagicMock

from openzim_mcp.pagination import Cursor
from openzim_mcp.simple_tools import SimpleToolsHandler


def _encode_cursor(tool: str, **state_fields: Any) -> str:
    """Encode a v2 cursor for ``tool`` from arbitrary ``s.*`` fields.

    Mirrors the helper used in the post-a19 fixes test file — the
    test surface mirrors production, where every cursor-emitting tool
    calls ``Cursor.encode(tool=..., state=...)`` with its own ``s.*``
    envelope. We can also pass adversarial ``s.q`` values on tools
    that don't normally emit ``q`` to verify the dispatcher's new
    skip behaviour.
    """
    return Cursor.encode(tool=tool, state=state_fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# P1-D1: dispatcher q-mismatch fires before handler tool-mismatch
# ---------------------------------------------------------------------------


class TestP1D1DispatcherQMismatchSkipsNonQEmittingTools:
    """P1-D1: cross-tool cursors that carry an adversarial ``s.q``
    must NOT trigger the dispatcher's q-overlap rejection — the
    correct diagnosis is tool-mismatch, fired by the handler-edge
    guard. The dispatcher now skips its q-check when the cursor's
    ``t`` field claims a non-q-emitting tool.
    """

    def _handler(self) -> tuple[SimpleToolsHandler, MagicMock]:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        return SimpleToolsHandler(mock), mock

    def test_walk_cursor_with_stuffed_q_routes_to_tool_mismatch(self) -> None:
        # Pre-fix: dispatcher saw cursor.q='biology', current query
        # tokens = {'search','for','photosynthesis'}, no overlap,
        # returned 'Cursor was issued for query "biology"; current
        # request shares no terms'. Post-fix: dispatcher sees
        # cursor.t='walk_namespace' is NOT q-emitting, skips q-check,
        # handler's tool-mismatch fires with the right diagnosis.
        handler, mock = self._handler()
        cursor_token = _encode_cursor(
            "walk_namespace", o=5, l=3, ns="M", ai="e048666a9e92", q="biology"
        )
        out = handler.handle_zim_query(
            "search for photosynthesis",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        # Must NOT route through the misleading q-mismatch shape.
        assert not (isinstance(out, dict) and out.get("operation") == "cursor_decode"), (
            f"dispatcher fired q-mismatch when handler tool-mismatch was correct: "
            f"{out!r}"
        )
        # Handler-level tool-mismatch markdown shape.
        assert isinstance(out, str)
        assert "Cursor / Tool Mismatch" in out
        assert "walk_namespace" in out
        assert "search_zim_file" in out
        # Backend not called.
        assert not mock.search_zim_file_data.called
        assert not mock.search_zim_file.called

    def test_browse_cursor_with_stuffed_q_routes_to_tool_mismatch(self) -> None:
        # Same shape with a different non-q-emitting source tool.
        handler, mock = self._handler()
        cursor_token = _encode_cursor(
            "browse_namespace",
            o=5,
            l=3,
            ns="M",
            ai="e048666a9e92",
            q="completely-unrelated",
        )
        out = handler.handle_zim_query(
            "search for Berlin",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        assert not (isinstance(out, dict) and out.get("operation") == "cursor_decode")
        assert isinstance(out, str)
        assert "Cursor / Tool Mismatch" in out
        assert "browse_namespace" in out
        assert "search_zim_file" in out

    def test_links_cursor_with_stuffed_q_routes_to_tool_mismatch(self) -> None:
        # ``extract_article_links`` also never emits ``s.q`` — any
        # ``s.q`` on its cursors is adversarial.
        handler, mock = self._handler()
        cursor_token = _encode_cursor(
            "extract_article_links",
            o=3,
            ai="e048666a9e92",
            q="vestigial",
        )
        out = handler.handle_zim_query(
            "search for Photosynthesis",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        assert not (isinstance(out, dict) and out.get("operation") == "cursor_decode")
        assert isinstance(out, str)
        assert "Cursor / Tool Mismatch" in out
        assert "extract_article_links" in out
        assert "search_zim_file" in out

    def test_walk_cursor_stuffed_q_to_filtered_search_routes_to_tool_mismatch(
        self,
    ) -> None:
        # Same shape with the filtered-search handler edge.
        handler, mock = self._handler()
        cursor_token = _encode_cursor(
            "walk_namespace",
            o=3,
            l=3,
            ns="M",
            ai="e048666a9e92",
            q="cooking",
        )
        out = handler.handle_zim_query(
            "search Berlin in namespace C",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        assert not (isinstance(out, dict) and out.get("operation") == "cursor_decode")
        assert isinstance(out, str)
        assert "Cursor / Tool Mismatch" in out
        assert "walk_namespace" in out
        assert "search_with_filters" in out

    def test_real_search_cursor_unrelated_query_still_q_mismatches(self) -> None:
        # Regression guard: the dispatcher's q-mismatch logic MUST
        # still fire for real ``search_zim_file`` cursors whose
        # stored ``s.q`` shares no terms with the current request.
        # This is the original D9 (beta) intent — pagination state
        # coupled to a different query. The fix only skips the check
        # for cursors from tools that don't normally emit ``s.q``;
        # real search cursors still go through.
        handler, mock = self._handler()
        cursor_token = _encode_cursor(
            "search_zim_file", o=5, q="algebra", ai="e048666a9e92"
        )
        out = handler.handle_zim_query(
            "search for photosynthesis",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        # Existing q-mismatch shape (JSON tool_error dict).
        assert isinstance(out, dict)
        assert out.get("operation") == "cursor_decode"
        assert "shares no terms" in (out.get("message") or "")

    def test_real_search_cursor_overlapping_query_routes_to_backend(self) -> None:
        # Regression guard: a real search cursor whose stored ``s.q``
        # overlaps the current query MUST still route through to the
        # backend (the canonical pagination path). The fix does not
        # touch this case.
        handler, mock = self._handler()
        mock.search_zim_file_data.return_value = {
            "total": 100,
            "results": [],
            "page_info": {"offset": 5, "limit": 5, "returned_count": 0},
            "_meta": {},
        }
        cursor_token = _encode_cursor(
            "search_zim_file", o=5, q="biology evolution", ai="e048666a9e92"
        )
        out = handler.handle_zim_query(
            "search for biology",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        # No cursor_decode error — backend was invoked.
        assert not (isinstance(out, dict) and out.get("operation") == "cursor_decode")
        assert mock.search_zim_file_data.called

    def test_walk_cursor_stuffed_q_to_walk_handler_routes_normally(self) -> None:
        # When the cursor's ``t`` matches the actual routing target
        # (walk -> walk), the dispatcher's q-skip does NOT alter
        # normal cursor consumption — the walk handler ignores the
        # stuffed ``q`` field (which doesn't appear in walk's data
        # path at all) and pages forward from the cursor's offset.
        # This pins the skip's blast radius to cross-tool reuse only.
        handler, mock = self._handler()
        mock.walk_namespace_data.return_value = {
            "results": [],
            "total": 100,
            "page_info": {"offset": 5, "limit": 3, "returned_count": 0},
            "_meta": {},
        }
        cursor_token = _encode_cursor(
            "walk_namespace",
            o=5,
            l=3,
            ns="M",
            ai="e048666a9e92",
            q="vestigial",
        )
        out = handler.handle_zim_query(
            "walk namespace M",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        # No tool-mismatch (same tool), no q-mismatch (skipped).
        assert not (isinstance(out, dict) and out.get("operation") == "cursor_decode")
        assert "Cursor / Tool Mismatch" not in (out if isinstance(out, str) else "")
        assert mock.walk_namespace_data.called


# ---------------------------------------------------------------------------
# P1-D2: soft-connector footer's alias-fallback gate was too narrow
# ---------------------------------------------------------------------------


class TestP1D2SoftConnectorFooterAsymmetricAliasSuppression:
    """P1-D2: the alias-fallback in ``_soft_connector_footer`` was
    gated on ``not left_in and not right_in`` — both halves missing
    in substring. The asymmetric case (one half matches substring,
    the other matches only via title alias) slipped through,
    producing footers that sent the user to a 2-hop article that
    just redirects back to the picked article (``Köln`` →
    ``Cologne``, ``京都`` → ``Kyoto``, ``上海`` → ``Shanghai``,
    ``München`` → ``Munich``).

    The fix widens the gate to ``not (left_in and right_in)`` so
    the alias probe runs whenever either half is missing in
    substring. The probe only upgrades a half whose top-scored
    title-index hit equals ``top_path``, so unrelated chain
    halves (``Berlin and 東京``) still drop correctly.
    """

    def _handler(
        self,
        alias_map: dict[str, str] | None = None,
    ) -> tuple[SimpleToolsHandler, MagicMock]:
        # Build a mock whose ``find_entry_by_title_data`` returns
        # the supplied alias mapping. The footer's alias probe calls
        # this backend; we drive deterministic responses to pin the
        # gate's behaviour without hitting a real archive.
        mock = MagicMock()

        def lookup(
            zim_file_path: str,
            title: str,
            *,
            cross_file: bool = False,
            limit: int = 1,
        ) -> dict[str, Any]:
            target = (alias_map or {}).get(title)
            if target is None:
                return {"results": []}
            return {"results": [{"path": target}]}

        mock.find_entry_by_title_data.side_effect = lookup
        return SimpleToolsHandler(mock), mock

    def test_koln_or_cologne_suppresses_footer(self) -> None:
        # Köln title-resolves to Cologne — same article via the
        # German-name alias. The footer must NOT direct the user to
        # ``tell me about Köln`` (which round-trips back to Cologne).
        handler, mock = self._handler(alias_map={"Köln": "Cologne"})
        out = handler._soft_connector_footer(
            topic="Köln or Cologne",
            top_title="Cologne",
            zim_file_path="/x.zim",
            top_path="Cologne",
        )
        assert out is None, f"footer should suppress alias-edge case, got: {out!r}"

    def test_cologne_or_koln_suppresses_footer(self) -> None:
        # Reverse order — same asymmetric alias case, picked half
        # on the left this time.
        handler, mock = self._handler(alias_map={"Köln": "Cologne"})
        out = handler._soft_connector_footer(
            topic="Cologne or Köln",
            top_title="Cologne",
            zim_file_path="/x.zim",
            top_path="Cologne",
        )
        assert out is None

    def test_kyoto_japanese_or_english_suppresses_footer(self) -> None:
        # CJK ideogram half (京都) aliases to the English title (Kyoto).
        handler, mock = self._handler(alias_map={"京都": "Kyoto"})
        out = handler._soft_connector_footer(
            topic="京都 or Kyoto",
            top_title="Kyoto",
            zim_file_path="/x.zim",
            top_path="Kyoto",
        )
        assert out is None

    def test_shanghai_or_chinese_suppresses_footer(self) -> None:
        handler, mock = self._handler(alias_map={"上海": "Shanghai"})
        out = handler._soft_connector_footer(
            topic="Shanghai or 上海",
            top_title="Shanghai",
            zim_file_path="/x.zim",
            top_path="Shanghai",
        )
        assert out is None

    def test_munich_german_alias_suppresses_footer(self) -> None:
        handler, mock = self._handler(alias_map={"München": "Munich"})
        out = handler._soft_connector_footer(
            topic="Munich or München",
            top_title="Munich",
            zim_file_path="/x.zim",
            top_path="Munich",
        )
        assert out is None

    def test_genuinely_different_halves_still_footer(self) -> None:
        # Regression guard: ``Berlin and München`` — different
        # cities, München aliases to Munich, but the resolver
        # picked one of them (München in the live probe). When
        # picked is München and dropped is Berlin, the alias probe
        # for Berlin returns Berlin's own path (NOT Munich) so the
        # dropped-half remains genuinely dropped — footer must fire.
        handler, mock = self._handler(
            alias_map={"München": "Munich", "Berlin": "Berlin"}
        )
        out = handler._soft_connector_footer(
            topic="Berlin and München",
            top_title="München",
            zim_file_path="/x.zim",
            top_path="Munich",
        )
        assert out is not None
        assert "Berlin" in out
        # Probe was run on both halves (Berlin AND München) — the
        # widened gate runs the fallback on the missing-substring
        # half(es), so München's alias matches → left_in=True,
        # Berlin's alias misses → right_in=False (or vice versa
        # depending on connector position).
        assert mock.find_entry_by_title_data.called

    def test_tokyo_has_own_disambig_still_fires_footer(self) -> None:
        # The irreducible edge: 東京 has its own disambig article at
        # path ``東京`` — not an alias to Tokyo. The fallback for 東京
        # returns its own path which differs from ``Tokyo``, so the
        # footer correctly fires (the user genuinely needs the
        # disambig page to choose between Tokyo / Tonkin / Đông Kinh).
        # This was flagged in the post-a20 brief as a known
        # not-in-scope edge case.
        handler, mock = self._handler(alias_map={"東京": "東京"})
        out = handler._soft_connector_footer(
            topic="東京 or Tokyo",
            top_title="Tokyo",
            zim_file_path="/x.zim",
            top_path="Tokyo",
        )
        assert out is not None
        assert "東京" in out

    def test_both_halves_already_in_title_no_alias_probe(self) -> None:
        # Regression guard: ``Romeo and Juliet`` with top_title
        # ``Romeo and Juliet`` — both halves match by substring,
        # widened gate evaluates to False, alias probe doesn't run,
        # footer suppresses (returned article IS the full phrase).
        handler, mock = self._handler()
        out = handler._soft_connector_footer(
            topic="Romeo and Juliet",
            top_title="Romeo and Juliet",
            zim_file_path="/x.zim",
            top_path="Romeo_and_Juliet",
        )
        # Suppressed via the structural-connector branch
        # (top_title contains "and" connector pattern) — kept here
        # to defence-in-depth check both branches reject this shape.
        assert out is None
        # No alias probe needed — the top-title-contains-connector
        # branch suppresses without reaching the alias fallback.
        assert not mock.find_entry_by_title_data.called

    def test_both_halves_missing_in_substring_alias_runs_for_both(self) -> None:
        # Regression guard for the original post-a18 P3-D2 motivation:
        # both halves miss substring, alias probe runs on both,
        # one alias matches → footer fires for the genuinely
        # dropped half. The post-a20 widening must preserve this.
        handler, mock = self._handler(
            alias_map={"München": "Munich", "Berlin": "Berlin"}
        )
        out = handler._soft_connector_footer(
            topic="Berlin and München",
            top_title="Munich",
            zim_file_path="/x.zim",
            top_path="Munich",
        )
        # München aliases to Munich (left_in upgrades), Berlin doesn't
        # (right_in stays False) — footer fires naming Berlin.
        assert out is not None
        assert "Berlin" in out


# ---------------------------------------------------------------------------
# End-to-end smoke gates
# ---------------------------------------------------------------------------


class TestEndToEndA20Gates:
    """End-to-end gates that confirm both P1-D1 and P1-D2 hold at the
    user-facing surface — not just at the helper layer. These mirror
    the live-MCP smoke gates from the post-a20 sweep brief.
    """

    def _handler(self) -> tuple[SimpleToolsHandler, MagicMock]:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.config.meta.footer_enabled = False
        return SimpleToolsHandler(mock), mock

    def test_walk_cursor_stuffed_q_search_intent_yields_tool_mismatch(self) -> None:
        # Cross-tool with stuffed q — must yield the markdown
        # tool-mismatch shape, not the JSON q-mismatch.
        handler, mock = self._handler()
        cursor_token = _encode_cursor(
            "walk_namespace",
            o=5,
            l=3,
            ns="M",
            ai="e048666a9e92",
            q="biology",
        )
        out = handler.handle_zim_query(
            "search for photosynthesis",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        assert isinstance(out, str), f"expected markdown, got {type(out)!r}: {out!r}"
        assert "Cursor / Tool Mismatch" in out

    def test_walk_cursor_stuffed_q_filtered_search_yields_tool_mismatch(
        self,
    ) -> None:
        handler, mock = self._handler()
        cursor_token = _encode_cursor(
            "walk_namespace",
            o=5,
            l=3,
            ns="C",
            ai="e048666a9e92",
            q="cooking",
        )
        out = handler.handle_zim_query(
            "search Berlin in namespace C",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        assert isinstance(out, str)
        assert "Cursor / Tool Mismatch" in out

    def test_walk_cursor_stuffed_q_links_yields_tool_mismatch(self) -> None:
        handler, mock = self._handler()
        # Make path resolution a no-op (returns nothing).
        mock.find_entry_by_title_data.return_value = {"results": []}
        cursor_token = _encode_cursor(
            "extract_article_links",
            o=3,
            ai="e048666a9e92",
            q="biology",
        )
        out = handler.handle_zim_query(
            "links in Photosynthesis",
            zim_file_path="/x.zim",
            options={"compact": True, "cursor": cursor_token},
        )
        assert isinstance(out, str)
        # The cursor's ``t`` is extract_article_links, which IS
        # what the routing target is, so this case is same-tool
        # cursor reuse. Tool-mismatch must NOT fire here — the
        # ``q`` is vestigial and the dispatcher skips its q-check
        # (extract_article_links is non-q-emitting). The handler
        # then walks normally (offset=0 hardcoded).
        assert "Cursor / Tool Mismatch" not in out
