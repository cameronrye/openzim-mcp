"""Regression tests for the post-a20 beta-test sweep (a21 candidate fixes).

The post-a20 live-MCP sweep against the 118 GB Wikipedia ZIM after
v2.0.0a20 deployed surfaced three user-facing defects across two
passes. Pass-1 caught P1-D1 + P1-D2 (the "fix unlocks new paths"
shape: a20's three landed fixes opened up the surfaces probed). Pass-2
caught PD2-1 by widening probe coverage to politeness wrappers across
all simple-mode intents — only ``tell_me_about`` was stripping
trailing politeness; every other extractor with a greedy
end-anchored capture was silently swallowing ``please`` / ``thanks``
/ ``thank you`` into the search term, title lookup, or entry path.

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

- PD2-1: trailing politeness markers (``please``, ``kindly``,
  ``thanks``, ``thank you``) leaked into every simple-mode intent
  EXCEPT ``tell_me_about`` and a few that capture by a tight tail
  token (filtered_search ends at the namespace letter; walk/browse
  capture only the letter). Only ``_extract_tell_me_about`` had a
  trailing-politeness strip (post-a11 B3); the sibling extractors
  (``_extract_search``, ``_extract_search_all``,
  ``_extract_find_by_title``, ``_extract_related``,
  ``_extract_suggestions``, ``_extract_entry_path_keyworded`` —
  feeding get_article / links / structure / toc / summary, plus
  ``_extract_get_zim_entries`` / ``_extract_get_section``) capture
  with greedy patterns terminated only by end-of-string and
  silently swallowed the politeness into the captured value:

    * ``search for biology please`` → query ``"biology please"``,
      ranks ``Thanks Maa`` etc. above the canonical ``Biology``.
    * ``find article titled Berlin please`` → ``"Berlin please"``,
      not found.
    * ``links in Photosynthesis please`` → tries to fetch
      ``"Photosynthesis please"``, not found.
    * Comma forms (``"biology, please"``) and other tail words
      (``thanks``, ``thank you``) showed the same shape.

  Fix: lift the trailing-politeness strip into
  ``IntentParser.parse_intent`` at the entry point — a single
  end-anchored strip on the query string, looped so combinations
  (``biology, thanks please``) peel cleanly, runs before pattern
  matching + extractor dispatch. Every extractor now sees the
  cleaned query. Legitimate content uses
  (``search for "Please Understand Me"`` — song title) are
  unaffected: the strip is end-anchored, so it only peels tokens
  appearing after the close-quote at end-of-string.

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
        assert not (
            isinstance(out, dict) and out.get("operation") == "cursor_decode"
        ), (
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


# ---------------------------------------------------------------------------
# PD2-1: trailing politeness leaks into intents other than tell_me_about
# ---------------------------------------------------------------------------


class TestPD21TrailingPolitenessStrip:
    """PD2-1: every extractor with a greedy end-anchored capture
    silently swallowed trailing politeness (``please`` / ``kindly`` /
    ``thanks`` / ``thank you``) into the captured value. Only
    ``_extract_tell_me_about`` had a strip. Fix lifts the strip into
    ``IntentParser.parse_intent`` so every extractor sees a cleaned
    query.

    These tests assert at the parsed-params level (the contract
    extractors expose), not at the end-to-end response level — that
    isolates the fix to the intent parser and keeps the tests fast
    regardless of which backend each intent then routes to.
    """

    def test_search_strips_trailing_please(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("search for biology please")
        assert intent == "search"
        assert params.get("query") == "biology"

    def test_search_strips_trailing_thanks(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("search for biology thanks")
        assert intent == "search"
        assert params.get("query") == "biology"

    def test_search_strips_trailing_thank_you(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "search for biology thank you"
        )
        assert intent == "search"
        assert params.get("query") == "biology"

    def test_search_strips_trailing_kindly(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("search for biology kindly")
        assert intent == "search"
        assert params.get("query") == "biology"

    def test_search_strips_comma_please(self) -> None:
        # ``biology, please`` — comma-then-politeness shape.
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("search for biology, please")
        assert intent == "search"
        assert params.get("query") == "biology"

    def test_search_strips_combined_thanks_please(self) -> None:
        # Loop pass: ``biology thanks please`` peels both tails.
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "search for biology thanks please"
        )
        assert intent == "search"
        assert params.get("query") == "biology"

    def test_find_by_title_strips_trailing_please(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "find article titled Berlin please"
        )
        assert intent == "find_by_title"
        assert params.get("title") == "berlin"  # Sub-D-2 Rule 1 lowercases

    def test_find_by_title_strips_trailing_thanks(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "find article titled Photosynthesis thanks"
        )
        assert intent == "find_by_title"
        assert params.get("title") == "photosynthesis"  # Sub-D-2 Rule 1 lowercases

    def test_links_strips_trailing_please(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "links in Photosynthesis please"
        )
        assert intent == "links"
        assert params.get("entry_path") == "photosynthesis"  # Sub-D-2 Rule 1 lowercases

    def test_structure_strips_trailing_please(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "show structure of Photosynthesis please"
        )
        assert intent == "structure"
        assert params.get("entry_path") == "photosynthesis"  # Sub-D-2 Rule 1 lowercases

    def test_get_article_strips_trailing_please(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("get article Berlin please")
        assert intent == "get_article"
        assert params.get("entry_path") == "berlin"  # Sub-D-2 Rule 1 lowercases

    def test_suggestions_strips_trailing_please(self) -> None:
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("suggestions for ber please")
        assert intent == "suggestions"
        assert params.get("partial_query") == "ber"

    def test_tell_me_about_already_stripped_still_works(self) -> None:
        # Regression guard: the original tell_me_about strip continues
        # to work (the lifted strip is upstream, so this should be
        # idempotent).
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("tell me about Berlin please")
        assert intent == "tell_me_about"
        assert params.get("topic") == "berlin"  # Sub-D-2 Rule 1 lowercases

    def test_walk_namespace_unaffected_by_trailing_please(self) -> None:
        # Walk's extractor captures only the namespace letter, so
        # trailing politeness never affected it pre-fix. The strip
        # must not change this behaviour.
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("walk namespace M please")
        assert intent == "walk_namespace"
        assert params.get("namespace") == "M"

    def test_filtered_search_unaffected_by_trailing_please(self) -> None:
        # Filtered search's regex ends at the namespace letter, so
        # the trailing politeness was already harmless. Defence-in-
        # depth: the strip must not break this case either.
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            "search Berlin in namespace C please"
        )
        assert intent == "filtered_search"
        assert params.get("query") == "berlin"  # Sub-D-2 Rule 1 lowercases
        assert (params.get("namespace") or "").upper() == "C"

    def test_quoted_inner_please_not_stripped(self) -> None:
        # Legitimate content uses with ``please`` as a query word
        # MUST not be touched. Quoted form encloses the content; the
        # strip is end-anchored after the close-quote.
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            'search for "Please Understand Me"'
        )
        assert intent == "search"
        # The quoted phrase remains intact (with or without enclosing
        # quotes is up to the extractor — what matters is "Please" is
        # still present as a content token).
        captured = (params.get("query") or "").lower()
        assert "please understand me" in captured

    def test_search_quoted_inner_please_with_outer_please_strip(self) -> None:
        # Hybrid: quoted content uses "please" AND trailing politeness
        # appears outside the quotes. Only the outside ``please`` peels.
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent(
            'search for "Please Understand Me" please'
        )
        assert intent == "search"
        captured = (params.get("query") or "").lower()
        assert "please understand me" in captured
        # The trailing ``please`` outside the quotes is gone.
        assert not captured.rstrip().endswith("please")

    def test_no_politeness_unchanged(self) -> None:
        # Regression guard: queries without any politeness tail must
        # parse exactly as before (the strip is a no-op).
        from openzim_mcp.intent_parser import IntentParser

        intent, params, _conf = IntentParser.parse_intent("search for biology")
        assert intent == "search"
        assert params.get("query") == "biology"

    def test_helper_idempotent(self) -> None:
        # _strip_trailing_politeness is exposed for unit testing the
        # loop behaviour directly.
        from openzim_mcp.intent_parser import IntentParser

        assert (
            IntentParser._strip_trailing_politeness("biology please thanks")
            == "biology"
        )
        assert (
            IntentParser._strip_trailing_politeness("biology, please, thanks")
            == "biology"
        )
        assert IntentParser._strip_trailing_politeness("biology") == "biology"
        assert IntentParser._strip_trailing_politeness("") == ""

    def test_helper_does_not_swallow_legitimate_content(self) -> None:
        # ``Photosynthesis`` ends in nothing that resembles politeness;
        # ``please`` inside a quoted phrase is content and must stay.
        from openzim_mcp.intent_parser import IntentParser

        assert (
            IntentParser._strip_trailing_politeness("Photosynthesis")
            == "Photosynthesis"
        )
        assert (
            IntentParser._strip_trailing_politeness('"Please Understand Me"')
            == '"Please Understand Me"'
        )

    def test_helper_handles_trailing_punctuation(self) -> None:
        # Trailing punctuation after the politeness (``please?`` /
        # ``please!`` / ``please.``) should still strip cleanly.
        from openzim_mcp.intent_parser import IntentParser

        assert IntentParser._strip_trailing_politeness("biology please.") == "biology"
        assert IntentParser._strip_trailing_politeness("biology please!") == "biology"
        assert IntentParser._strip_trailing_politeness("biology please?") == "biology"
        assert IntentParser._strip_trailing_politeness("biology, please.") == "biology"

    def test_helper_mid_query_politeness_word_unaffected(self) -> None:
        # ``thanks giving`` mid-phrase is content (Thanksgiving holiday).
        # ``kindly remind me`` mid-phrase is content. Strip is
        # end-anchored, so neither matches.
        from openzim_mcp.intent_parser import IntentParser

        assert (
            IntentParser._strip_trailing_politeness("biology thanks giving")
            == "biology thanks giving"
        )
        assert (
            IntentParser._strip_trailing_politeness("biology kindly remind me")
            == "biology kindly remind me"
        )


# ---------------------------------------------------------------------------
# PD2-2 / PD2-3 / PD2-4: small-model hallucinated zim_file_path recovery
# ---------------------------------------------------------------------------


class TestPD22DocstringExampleNoLongerBait:
    """PD2-2: the ``zim_query`` tool docstring used to contain a
    literal-looking example path (``/data/wikipedia_en_all_maxi.zim``).
    Small models with weak instruction-following parse "e.g." as
    illustrative inconsistently and frequently copy the example as
    the actual ``zim_file_path`` value. Real archives in production
    are date-suffixed (``wikipedia_en_all_maxi_2026-02.zim``) so the
    basename doesn't match either, and the previous "trust slashed
    paths" branch dropped the model into a ``File does not exist``
    retry loop with no recovery signal.

    The docstring no longer contains a literal-looking path example;
    the description leads with "Omit entirely (recommended)" so
    auto-select is the natural choice the model latches onto.
    """

    def test_zim_query_docstring_does_not_contain_literal_path_example(
        self,
    ) -> None:
        # The bait was the literal example ``/data/wikipedia_en_all_maxi.zim``
        # appearing in the docstring. Pin its removal — any reappearance
        # should fail this test and remind future maintainers that
        # docstring example paths get copied by small models.
        # The tool docstring lives on ``zim_query`` registered in
        # ``server.py``; we extract it from the source rather than
        # standing up a live server.
        import inspect

        import openzim_mcp.server as server_mod

        source = inspect.getsource(server_mod)
        assert "/data/wikipedia_en_all_maxi.zim" not in source, (
            "Docstring example reintroduced the literal-looking path "
            "small models copy verbatim. Use a generic placeholder or "
            "drop the example entirely."
        )

    def test_zim_query_docstring_emphasises_omit_to_auto_select(
        self,
    ) -> None:
        # Phase F D3 moved the zim_query docstring out of server.py
        # into a committed description file shipped with the wheel.
        import importlib.resources as resources

        source = (
            resources.files("openzim_mcp.tools")
            .joinpath("zim_query_description.md")
            .read_text(encoding="utf-8")
        )
        assert "Omit entirely" in source, (
            "Description file should lead with 'Omit entirely' for the "
            "zim_file_path parameter to nudge small models toward the "
            "canonical default."
        )


class TestPD23NormalizerSingleArchiveAutoSelect:
    """PD2-3: ``_normalize_zim_file_path`` auto-selects when exactly
    one archive is loaded — even when the candidate has a path
    separator. Pre-fix, slashed paths fell through "trust it" (H14)
    and reached the backend, which errored. In single-archive setups
    there is no ambiguity to surface; silent substitution is the
    right UX. Multi-archive setups still trust the candidate and let
    the backend error surface with PD2-4's recovery hint.
    """

    def _handler_single_archive(self) -> tuple[Any, MagicMock]:
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock = MagicMock()
        mock.list_zim_files_data.return_value = [
            {
                "path": "/var/lib/zim/wikipedia_en_all_maxi_2026-02.zim",
                "name": "wikipedia_en_all_maxi_2026-02.zim",
            },
        ]
        mock.list_zim_files.return_value = (
            '[{"path": "/var/lib/zim/wikipedia_en_all_maxi_2026-02.zim"}]'
        )
        mock.get_main_page.return_value = "main page text"
        return SimpleToolsHandler(mock), mock

    def _handler_multi_archive(self) -> tuple[Any, MagicMock]:
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock = MagicMock()
        mock.list_zim_files_data.return_value = [
            {"path": "/var/lib/zim/wikipedia_en_all_maxi_2026-02.zim"},
            {"path": "/var/lib/zim/wiktionary_en_all_maxi_2026-02.zim"},
        ]
        mock.list_zim_files.return_value = (
            '[{"path": "/var/lib/zim/wikipedia_en_all_maxi_2026-02.zim"}, '
            '{"path": "/var/lib/zim/wiktionary_en_all_maxi_2026-02.zim"}]'
        )
        return SimpleToolsHandler(mock), mock

    def test_docstring_example_path_auto_selects_single_archive(self) -> None:
        # The canonical small-model hallucination — the literal example
        # path from the (pre-PD2-2) tool docstring.
        handler, mock = self._handler_single_archive()
        result = handler._normalize_zim_file_path("/data/wikipedia_en_all_maxi.zim")
        assert result == "/var/lib/zim/wikipedia_en_all_maxi_2026-02.zim"

    def test_arbitrary_slashed_hallucination_auto_selects_single_archive(
        self,
    ) -> None:
        handler, mock = self._handler_single_archive()
        result = handler._normalize_zim_file_path("/totally/made/up.zim")
        assert result == "/var/lib/zim/wikipedia_en_all_maxi_2026-02.zim"

    def test_bare_filename_hallucination_still_auto_selects(self) -> None:
        # Regression guard for the original bare-filename auto-select.
        handler, mock = self._handler_single_archive()
        result = handler._normalize_zim_file_path("wikipedia.zim")
        assert result == "/var/lib/zim/wikipedia_en_all_maxi_2026-02.zim"

    def test_basename_match_still_resolves(self) -> None:
        # Regression guard: a bare filename matching the real basename
        # still resolves through the existing case-1 path.
        handler, mock = self._handler_single_archive()
        result = handler._normalize_zim_file_path("wikipedia_en_all_maxi_2026-02.zim")
        assert result == "/var/lib/zim/wikipedia_en_all_maxi_2026-02.zim"

    def test_real_full_path_passes_through(self) -> None:
        # Regression guard: the real full path matches case 1 and is
        # returned verbatim.
        handler, mock = self._handler_single_archive()
        real = "/var/lib/zim/wikipedia_en_all_maxi_2026-02.zim"
        assert handler._normalize_zim_file_path(real) == real

    def test_multi_archive_slashed_path_no_match_preserves_h14(self) -> None:
        # H14 narrowed: with multiple archives loaded, we can't
        # silently pick one — preserve the candidate so the backend
        # error surfaces and PD2-4 enriches it with the actual listing.
        handler, mock = self._handler_multi_archive()
        candidate = "/totally/made/up.zim"
        assert handler._normalize_zim_file_path(candidate) == candidate

    def test_multi_archive_bare_filename_no_match_preserves_h14(
        self,
    ) -> None:
        # Same shape for bare filenames in multi-archive setups: the
        # ambiguity blocks auto-select.
        handler, mock = self._handler_multi_archive()
        candidate = "totally-fake.zim"
        assert handler._normalize_zim_file_path(candidate) == candidate

    def test_zero_archives_loaded_returns_candidate_unchanged(self) -> None:
        # Edge case: no archives loaded → auto-select returns None →
        # we return the candidate, backend errors, error handler
        # surfaces "no archives loaded".
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock = MagicMock()
        mock.list_zim_files_data.return_value = []
        mock.list_zim_files.return_value = "[]"
        handler = SimpleToolsHandler(mock)
        candidate = "/whatever.zim"
        assert handler._normalize_zim_file_path(candidate) == candidate


class TestPD24FileNotFoundRecoveryHint:
    """PD2-4: when ``validate_zim_file`` raises a path-error, the
    catch-all in ``handle_zim_query`` now emits a targeted recovery
    hint listing real archive paths and the canonical "omit to
    auto-select" fix. Pre-fix, the generic 4-step "Troubleshooting"
    template gave no learning signal.
    """

    def test_recovery_hint_single_archive_says_omit(self) -> None:
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock = MagicMock()
        mock.list_zim_files_data.return_value = [
            {"path": "/var/lib/zim/wikipedia_en_all_maxi_2026-02.zim"},
        ]
        handler = SimpleToolsHandler(mock)
        hint = handler._zim_path_recovery_hint()
        assert hint is not None
        assert "Omit" in hint or "omit" in hint
        assert "/var/lib/zim/wikipedia_en_all_maxi_2026-02.zim" in hint

    def test_recovery_hint_multi_archive_lists_paths(self) -> None:
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock = MagicMock()
        mock.list_zim_files_data.return_value = [
            {"path": "/var/lib/zim/wikipedia.zim"},
            {"path": "/var/lib/zim/wiktionary.zim"},
        ]
        handler = SimpleToolsHandler(mock)
        hint = handler._zim_path_recovery_hint()
        assert hint is not None
        assert "/var/lib/zim/wikipedia.zim" in hint
        assert "/var/lib/zim/wiktionary.zim" in hint
        assert "verbatim" in hint or "Loaded archives" in hint

    def test_recovery_hint_zero_archives_returns_none(self) -> None:
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock = MagicMock()
        mock.list_zim_files_data.return_value = []
        handler = SimpleToolsHandler(mock)
        assert handler._zim_path_recovery_hint() is None

    def test_recovery_hint_backend_failure_returns_none(self) -> None:
        # Defensive: backend listing failure must not block the error
        # path. Returning None makes the caller fall back to the
        # generic troubleshooting block.
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock = MagicMock()
        mock.list_zim_files_data.side_effect = RuntimeError("listing failed")
        handler = SimpleToolsHandler(mock)
        assert handler._zim_path_recovery_hint() is None

    def test_recovery_hint_malformed_listing_returns_none(self) -> None:
        # Defensive: listing returns something other than a list of
        # dicts with path strings (e.g. None / wrong shape).
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock = MagicMock()
        mock.list_zim_files_data.return_value = "not-a-list"
        handler = SimpleToolsHandler(mock)
        assert handler._zim_path_recovery_hint() is None

    def test_multi_archive_path_error_surfaces_hint_end_to_end(self) -> None:
        # End-to-end: multi-archive setup, bogus slashed path passed,
        # backend raises ``File does not exist``, catch-all wraps it
        # in the PD2-4 recovery markdown with the actual paths listed.
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock = MagicMock()
        mock.list_zim_files_data.return_value = [
            {"path": "/var/lib/zim/wikipedia.zim"},
            {"path": "/var/lib/zim/wiktionary.zim"},
        ]
        # Make the backend raise to drive the catch-all.
        mock.get_main_page.side_effect = Exception(
            "File does not exist: /totally/fake.zim"
        )
        mock.config.meta.footer_enabled = False
        handler = SimpleToolsHandler(mock)
        out = handler.handle_zim_query(
            "show main page",
            zim_file_path="/totally/fake.zim",
        )
        assert isinstance(out, str)
        # New error shape.
        assert "**ZIM File Not Found**" in out
        # Real paths surfaced.
        assert "/var/lib/zim/wikipedia.zim" in out
        assert "/var/lib/zim/wiktionary.zim" in out
        # Generic troubleshooting block is replaced.
        assert "Check server logs" not in out

    def test_single_archive_path_error_falls_through_to_pd23_auto_select(
        self,
    ) -> None:
        # End-to-end: single-archive setup MUST never reach the
        # catch-all for a bogus zim_file_path — PD2-3 auto-selects
        # before the backend sees it. Pin this contract.
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock = MagicMock()
        mock.list_zim_files_data.return_value = [
            {"path": "/var/lib/zim/the-only-one.zim"},
        ]
        mock.list_zim_files.return_value = '[{"path": "/var/lib/zim/the-only-one.zim"}]'
        mock.get_main_page.return_value = "main page text"
        mock.config.meta.footer_enabled = False
        handler = SimpleToolsHandler(mock)
        handler.handle_zim_query(
            "show main page",
            zim_file_path="/some/other/fake.zim",
        )
        # Backend was invoked with the auto-selected path, not the
        # hallucinated one.
        mock.get_main_page.assert_called_once_with(
            "/var/lib/zim/the-only-one.zim", compact=False
        )
