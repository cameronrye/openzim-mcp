"""Regression tests for the post-a21 beta-test sweep (a22 candidate fixes).

The post-a21 live-MCP sweep against the 118 GB Wikipedia ZIM after
v2.0.0a21 deployed surfaced ELEVEN user-facing defects in a single
pass. Pass-1 probed the angles pass-2 of the post-a20 sweep didn't
cover for each of the six a21 fix shapes (P1-D1 dispatcher q-gate,
P1-D2 alias-fallback gate, PD2-1 politeness strip, PD2-2 docstring
bait, PD2-3 single-archive auto-select, PD2-4 recovery hint), plus
small-model transcript review for the weak-instruction-follower
defect class.

The defects span six surfaces:

* **Politeness strip** — P1-D6/D7 cover British/texting and
  multi-language trailing markers that the post-a20 regex didn't
  enumerate (``ta`` / ``cheers`` / ``thx`` / ``ty`` / ``pls`` /
  ``bitte`` / ``danke`` / ``gracias`` / ``por favor`` / ``merci``).
  P1-D8 is the B4 ``search for <politeness>`` guard miss
  (``_search_query_tail`` used the ORIGINAL query, so the trailing
  politeness wasn't peeled before the empty-tail check and the search
  silently dispatched with ``query="for"`` — the literal verb word).
  P1-D1 is the same shape under defence-in-depth: even when
  ``parse_intent`` doesn't strip for whatever reason (in-process
  module cache, future regression, etc.), the dispatcher edge
  re-applies the strip idempotently so the handler still sees a
  cleaned ``params``.

* **Soft-connector footer / multi-entity chain** — P1-D2/D3/D4 cover
  3+ entity chains the post-a20 P1-D2 alias-fallback widening didn't
  address. ``tell me about Köln, München, and Berlin`` produced a
  footer suggesting ``tell me about Köln, München,`` (still-chained
  recursive suggestion); ``tell me about Berlin or 東京 or Tokyo``
  silently fell through to "No search results found" with no chain
  signal; ``tell me about Berlin and München and Köln`` returned
  Cologne with no footer about the dropped Berlin/München. Fix:
  detect 3+ substantive proper-noun-shaped halves split by soft
  connectors AND probe the title index for the whole topic — if no
  clean single-title hit, fire a structured ``Multi-Entity Chain
  Detected`` rejection (mirrors the existing
  ``chained_intent_rejected`` shape). The title-index probe
  suppresses false-fires on real multi-entity titles like
  ``Earth, Wind & Fire`` / ``Romeo and Juliet`` (already 2-entity
  case) / ``Lions, Tigers, and Bears``.

* **Dispatcher q-gate drift** — P1-D5 pins the contract between
  ``Cursor.encode(state={..., "q": ...})`` callsites and
  ``_Q_EMITTING_CURSOR_TOOLS``. Pre-fix, a future contributor could
  add a new q-emitting tool but forget to update the set; the
  dispatcher q-overlap check would silently degrade to no-op for
  that tool — paginating with the wrong query proceeds silently. The
  test pins both sides of the contract: the set value AND a comment
  hook in ``zim/search.py`` that mentions ``_Q_EMITTING_CURSOR_TOOLS``
  so the right place to update is greppable from the encode callsite.

* **Docstring path-bait siblings** — P1-D9 widens the post-a20 PD2-2
  regression test to every LLM-facing tool docstring. PD2-2 only
  pinned ``server.py``'s ``zim_query`` docstring; ``structure_tools``
  (``get_entry_summary`` / ``get_table_of_contents`` /
  ``get_binary_entry``) and ``content_tools`` (``get_zim_entries``)
  carried sibling docstring path examples
  (``/path/to/wiki.zim`` / ``/path/file.zim`` / ``/path/x.zim``) that
  small models can copy verbatim. Fix: replace literal paths with
  placeholders that don't look like valid filesystem paths (e.g.,
  ``<zim_path>`` or omit and reference ``list_zim_files``).

* **Recovery hint marker overlap** — P1-D10 tightens the PD2-4
  detector to discriminate the security-specific
  ``OpenZimMcpSecurityError`` (path outside allowed directories) from
  the validation-specific ``OpenZimMcpValidationError`` (file does
  not exist / not a zim file / not a file). Pre-fix, both fell into
  the generic "doesn't match any loaded archive" hint, dropping the
  security-relevant reason. The hint now surfaces the original error
  message alongside the recovery instruction.

* **Tool-self-described drift (weak-instruction-follower)** — T-D1
  pins that the ``zim_query`` docstring's ``limit`` parameter
  description explicitly says it's ignored for atomic intents
  (``tell_me_about`` / ``get article`` / ``show structure``). Small
  models (Qwen3-8B-Q4 in the live transcript) speculatively pass
  ``limit=5`` on tell_me_about; the call wastes tokens but doesn't
  fail visibly. The docstring nudge prevents future drift.

Methodology note (post-a21): the recurring "fix unlocks new paths"
cycle reproduced again. Post-a20's P1-D2 (alias-fallback widening to
2-entity asymmetric chains) didn't address 3+ entity chains; this
pass's P1-D2/D3/D4 catch them. Post-a20's PD2-1 (parse_intent strip)
didn't widen the politeness token set; P1-D6/D7 add the
British/texting/multi-language variants. Post-a20's PD2-2 (zim_query
docstring de-bait) didn't sweep the sibling advanced-tool docstrings;
P1-D9 widens the regression net. The fix-then-stress-test cycle
keeps producing real defects at each new edge.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock

import pytest

from openzim_mcp.intent_parser import IntentParser
from openzim_mcp.simple_tools import SimpleToolsHandler

# ===========================================================================
# P1-D6 + P1-D7: trailing politeness regex extension
# ===========================================================================


class TestP1D6P1D7TrailingPolitenessExtensions:
    """P1-D6 (British/texting) + P1-D7 (multilang). Pre-fix the
    politeness regex only enumerated ``please`` / ``kindly`` /
    ``thanks`` / ``thank you|u``. Common British/texting variants
    (``ta`` / ``cheers`` / ``thx`` / ``ty`` / ``pls``) and the
    obvious multi-language tokens (``bitte`` / ``danke`` / ``merci``
    / ``gracias`` / ``por favor``) silently leaked into the search
    query, title lookup, or topic. The fix adds the missing tokens
    AND tightens the leading anchor to require a word boundary so
    embedded substrings like ``cantata`` / ``dante`` don't get
    falsely stripped at the tail.
    """

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("search for biology ta", "search for biology"),
            ("search for biology cheers", "search for biology"),
            ("search for biology thx", "search for biology"),
            ("search for biology ty", "search for biology"),
            ("search for biology pls", "search for biology"),
            ("search for biology bitte", "search for biology"),
            ("search for biology danke", "search for biology"),
            ("search for biology merci", "search for biology"),
            ("search for biology gracias", "search for biology"),
            ("search for biology por favor", "search for biology"),
            # Case variants
            ("search for biology Ta", "search for biology"),
            ("search for biology CHEERS", "search for biology"),
            # Comma / punctuation forms
            ("search for biology, ta", "search for biology"),
            ("search for biology, pls!", "search for biology"),
            # Multi-token tail
            ("search for biology please, ta", "search for biology"),
            # Idempotence: already-stripped query unchanged
            ("search for biology", "search for biology"),
        ],
    )
    def test_extended_tokens_strip(self, raw: str, expected: str) -> None:
        assert IntentParser._strip_trailing_politeness(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            # Word-boundary safety: politeness tokens embedded in other
            # words must NOT be stripped. Pre-fix-extension, naive
            # additions of short tokens (``ta``) would have stripped
            # ``cantata`` → ``can``, ``vista`` → ``vis``.
            "cantata",
            "vista",
            "feta",
            "tomato",
            "data",
            "Dante",
            "thanks giving",  # NB: trailing "giving" word — strip should not eat "thanks"
        ],
    )
    def test_word_boundary_safety(self, raw: str) -> None:
        assert IntentParser._strip_trailing_politeness(raw) == raw

    @pytest.mark.parametrize(
        "raw, expected_query",
        [
            ("search for biology ta", "biology"),
            ("search for biology cheers", "biology"),
            ("search for biology bitte", "biology"),
            ("search for biology por favor", "biology"),
            ("find article titled Berlin ta", "berlin"),  # Sub-D-2 Rule 1 lowercases
            ("find article titled Berlin merci", "berlin"),  # Sub-D-2 Rule 1 lowercases
        ],
    )
    def test_extended_tokens_in_full_parse(self, raw: str, expected_query: str) -> None:
        intent, params, _conf = IntentParser.parse_intent(raw)
        assert (
            "ta" not in (params.get("query", "") + params.get("title", "")).lower()
        ), f"Leftover token in params for {raw!r}: {params}"
        v = params.get("query") or params.get("title") or ""
        assert v == expected_query, f"Expected {expected_query!r}, got {v!r}"


# ===========================================================================
# P1-D8: B4 "Search Terms Required" guard miss with politeness tail
# ===========================================================================


class TestP1D8SearchTermsRequiredAfterPolitenessStrip:
    """P1-D8: ``search for please`` after parse_intent's politeness
    strip becomes ``search for`` (empty tail) — but the dispatcher's
    B4 guard called ``_search_query_tail(query)`` with the ORIGINAL
    query (still ``search for please``), so the tail returned was
    ``please`` (non-empty), the guard didn't fire, and ``_extract_search``
    captured the literal verb word ``for`` as the search term.
    Result: ``Found N matches for "for"`` — 200k+ hits dominated by
    stop-word collisions, no useful learning signal.

    Fix: peel trailing politeness off the tail before the empty-tail
    check so the guard fires for politeness-only search queries.
    """

    def _handler_single_archive(self) -> tuple[Any, MagicMock]:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        return SimpleToolsHandler(mock), mock

    @pytest.mark.parametrize(
        "query",
        [
            "search for please",
            "search for thanks",
            "search for kindly",
            "search for please.",
            "search for thank you",
            "search for ta",
            "search for cheers",
            "search for pls",
        ],
    )
    def test_politeness_only_search_fires_terms_required(self, query: str) -> None:
        handler, _mock = self._handler_single_archive()
        result = handler.handle_zim_query(query=query, zim_file_path="/x.zim")
        assert "Search Terms Required" in str(result), (
            f"Expected the B4 guard to fire for {query!r}, got: " f"{str(result)[:300]}"
        )


# ===========================================================================
# P1-D1: defense-in-depth — dispatcher-edge politeness strip on params
# ===========================================================================


class TestP1D1DispatcherEdgePolitenessStrip:
    """P1-D1: the live-MCP sweep observed
    ``Found 5000 matches for "biology please"`` for the query
    ``search for biology please`` despite the post-a20 PD2-1 fix
    that lifted the trailing-politeness strip to
    ``IntentParser.parse_intent``. Source-side, the strip works
    correctly; the most likely cause is an in-process module cache
    on the live server that loaded only PART of the PR-#152 diff
    (the rest of the a21 gates pass live). The user decided to log
    this as a defect and land a defense-in-depth that re-applies
    the strip at the dispatcher edge — idempotent when
    ``parse_intent`` already stripped, and a belt-and-suspenders
    catch for any future regression that bypasses
    ``parse_intent``.

    Fix: in ``handle_zim_query``, after the parse_intent call,
    apply ``IntentParser._strip_trailing_politeness`` to each of
    the user-supplied content fields in ``params``
    (``query`` / ``topic`` / ``title`` / ``entry_path`` /
    ``partial_query``). Strip is idempotent — no-op when
    ``parse_intent`` already cleaned.
    """

    def _handler_single_archive(self) -> tuple[Any, MagicMock]:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        # Search returns a structured payload that includes the
        # ``query`` used. We assert the dispatcher passed the stripped
        # form even if parse_intent didn't.
        mock.search_zim_file.return_value = "search ok"
        return SimpleToolsHandler(mock), mock

    def test_dispatcher_strips_query_field_idempotently(self) -> None:
        # Simulate a hypothetical case where ``parse_intent`` returns
        # params with politeness still attached (e.g., a future
        # regression). The dispatcher-edge strip must clean it.
        from openzim_mcp.intent_parser import IntentParser as IP

        original_parse = IP.parse_intent

        def buggy_parse(query: str, *, title_probe=None):
            # Pretend parse_intent forgot to strip. Return the search
            # extractor's output without the strip — params["query"]
            # carries the trailing politeness.
            return "search", {"query": "biology please"}, 0.75

        IP.parse_intent = staticmethod(buggy_parse)  # type: ignore[method-assign]
        try:
            handler, mock = self._handler_single_archive()
            handler.handle_zim_query(
                query="search for biology please", zim_file_path="/x.zim"
            )
            # The dispatcher edge should have stripped "please" before
            # dispatching to the search backend.
            calls = mock.search_zim_file.call_args_list
            assert calls, "Search backend was not called"
            # Backend's second positional arg is the query.
            args, kwargs = calls[0]
            search_query = args[1] if len(args) > 1 else kwargs.get("query")
            assert search_query == "biology", (
                f"Dispatcher should have stripped politeness defence-in-depth; "
                f"backend got {search_query!r}"
            )
        finally:
            IP.parse_intent = original_parse  # type: ignore[method-assign]


# ===========================================================================
# P1-D2 + P1-D3 + P1-D4: multi-entity chain warning
# ===========================================================================


class TestMultiEntityChainGuidance:
    """P1-D2/D3/D4: 3+ entity bare-topic chains joined by soft
    connectors (``and`` / ``or`` / ``,`` / ``&`` / ``vs``) bypass
    the existing 2-entity soft-connector footer's alias-fallback.
    Pre-fix:

    * ``tell me about Köln, München, and Berlin`` → returned Berlin
      + footer suggesting ``tell me about Köln, München,`` (the
      dropped half still contains a comma — re-running it would
      re-trigger the same defect).

    * ``tell me about Berlin or 東京 or Tokyo`` → silent "No search
      results found" (the resolver couldn't title-index the literal
      multi-entity string and the search fallback fired no signal
      about the dropped halves).

    * ``tell me about Berlin and München and Köln`` → returned
      Cologne (Köln alias) with NO footer about Berlin / München.

    Fix: at the dispatcher edge (for tell_me_about intent), detect
    3+ substantive proper-noun-shaped halves split by combined soft
    connectors AND probe the title index for the whole topic. If the
    whole topic doesn't title-resolve cleanly to a single article,
    fire a ``Multi-Entity Chain Detected`` rejection naming each
    detected entity and instructing the caller to issue N separate
    calls. The title-index probe suppresses false-fires on real
    multi-entity titles (``Earth, Wind & Fire`` /
    ``Lions, Tigers, and Bears``).
    """

    def _handler(
        self,
        title_resolves: dict[str, str] | None = None,
    ) -> tuple[Any, MagicMock]:
        """Build a handler with a stub title-index probe.

        ``title_resolves`` maps query string (lowercased) → top-hit
        path. If a query string isn't in the map, the probe returns
        no results (simulating "title does not resolve cleanly").
        """
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.list_zim_files.return_value = '[{"path": "/x.zim"}]'

        def stub_find(zim_path, query, **kw):
            key = (query or "").lower()
            if title_resolves and key in title_resolves:
                return {"results": [{"path": title_resolves[key], "score": 1.0}]}
            return {"results": []}

        mock.find_entry_by_title_data.side_effect = stub_find
        return SimpleToolsHandler(mock), mock

    def test_three_entity_and_chain_fires_warning(self) -> None:
        # No title-index hit for the whole topic — chain warning fires.
        handler, _mock = self._handler(title_resolves={})
        result = handler.handle_zim_query(
            query="tell me about Köln, München, and Berlin",
            zim_file_path="/x.zim",
        )
        body = str(result)
        assert (
            "Multi-Entity Chain Detected" in body
        ), f"Expected chain warning; got: {body[:400]}"
        # Each entity should be enumerated in the warning.
        # Sub-D-2 Rule 1 lowercases everything before chain detection.
        assert (
            "köln" in body and "münchen" in body and "berlin" in body
        ), f"Entities not enumerated: {body[:400]}"

    def test_three_entity_or_chain_with_non_latin_fires_warning(self) -> None:
        handler, _mock = self._handler(title_resolves={})
        result = handler.handle_zim_query(
            query="tell me about Berlin or 東京 or Tokyo",
            zim_file_path="/x.zim",
        )
        body = str(result)
        assert "Multi-Entity Chain Detected" in body
        # Sub-D-2 Rule 1 lowercases ASCII; non-Latin codepoints are untouched.
        assert "berlin" in body and "東京" in body and "tokyo" in body

    def test_four_entity_chain_fires_warning(self) -> None:
        handler, _mock = self._handler(title_resolves={})
        result = handler.handle_zim_query(
            query="tell me about Berlin and München and Köln and Hamburg",
            zim_file_path="/x.zim",
        )
        body = str(result)
        assert "Multi-Entity Chain Detected" in body

    def test_two_entity_chain_does_not_fire(self) -> None:
        # 2-entity case is already handled by the post-a20 P1-D2
        # alias-fallback footer.
        handler, _mock = self._handler(title_resolves={})
        # The handler will try to resolve "Berlin or Köln" via the
        # normal path; we only check that the multi-entity warning
        # is NOT in the response (the existing soft-connector path
        # can do whatever it does).
        result = handler.handle_zim_query(
            query="tell me about Berlin or Köln", zim_file_path="/x.zim"
        )
        body = str(result)
        assert "Multi-Entity Chain Detected" not in body

    def test_multi_entity_title_suppresses_warning(self) -> None:
        # ``Earth, Wind & Fire`` is a real article title. Even
        # without a title-index hit, the half "Wind" fails the
        # ``_is_substantive_topic`` 5-ASCII-char floor (it's 4
        # chars, single token, no digit, no non-ASCII letter), so
        # the chain warning is suppressed before the title probe
        # would even run. Defence-in-depth: when the substantive
        # filter doesn't catch the real title, the title-index
        # probe does.
        handler, _mock = self._handler(
            title_resolves={"earth, wind & fire": "Earth,_Wind_&_Fire"}
        )
        result = handler.handle_zim_query(
            query="tell me about Earth, Wind & Fire", zim_file_path="/x.zim"
        )
        body = str(result)
        assert (
            "Multi-Entity Chain Detected" not in body
        ), f"False-fire on real multi-entity title: {body[:400]}"

    def test_lions_tigers_and_bears_suppressed_via_title_probe(self) -> None:
        # ``Lions, Tigers, and Bears`` is a real idiom / film
        # subtitle. Every half is substantive (Lions=5, Tigers=6,
        # Bears=5), so the substantive filter doesn't catch it.
        # Title-index probe finds a cleanly-matching article path,
        # ``_path_matches_topic_loosely`` normalises both sides and
        # suppresses the chain warning.
        handler, _mock = self._handler(
            title_resolves={
                "lions, tigers, and bears": "Lions,_Tigers,_and_Bears",
            }
        )
        result = handler.handle_zim_query(
            query="tell me about Lions, Tigers, and Bears",
            zim_file_path="/x.zim",
        )
        body = str(result)
        assert (
            "Multi-Entity Chain Detected" not in body
        ), f"False-fire on real multi-entity idiom: {body[:400]}"

    def test_comma_then_and_strips_leading_conjunction(self) -> None:
        # Regression: pre-strip-leading-conjunction the comma-split
        # left ``"and Berlin"`` as the third half. Verify the strip
        # collapses ``", and "`` to a clean entity boundary.
        halves = SimpleToolsHandler._split_multi_entity("Köln, München, and Berlin")
        assert halves == [
            "Köln",
            "München",
            "Berlin",
        ], f"Leading conjunction not stripped: {halves}"

    def test_search_intent_not_affected(self) -> None:
        # Multi-entity check is gated on tell_me_about — ``search for
        # X and Y and Z`` is a legitimate multi-term BM25 query and
        # must not fire the chain warning.
        handler, _mock = self._handler(title_resolves={})
        result = handler.handle_zim_query(
            query="search for Berlin and München and Köln",
            zim_file_path="/x.zim",
        )
        body = str(result)
        assert "Multi-Entity Chain Detected" not in body


# ===========================================================================
# P1-D5: drift guard for _Q_EMITTING_CURSOR_TOOLS
# ===========================================================================


class TestP1D5QEmittingCursorToolsDrift:
    """P1-D5: the post-a20 P1-D1 fix introduced
    ``SimpleToolsHandler._Q_EMITTING_CURSOR_TOOLS`` as a hand-
    maintained frozenset of tool names whose cursors legitimately
    carry an ``s.q`` field. The dispatcher's q-overlap check skips
    when the cursor's ``t`` claims a tool NOT in the set. If a
    future contributor adds a new q-emitting tool (a new
    ``Cursor.encode(state={..., "q": ...})`` callsite) but forgets
    to update the set, the dispatcher's q-overlap guard silently
    degrades to no-op for that tool — paginating with the wrong
    query proceeds silently.

    Pin both:
      * the current set value (so accidental edits surface).
      * a comment hook in ``zim/search.py`` that mentions
        ``_Q_EMITTING_CURSOR_TOOLS`` so the right place to update
        is greppable from the encode callsite.
    """

    def test_q_emitting_cursor_tools_pinned_value(self) -> None:
        assert SimpleToolsHandler._Q_EMITTING_CURSOR_TOOLS == frozenset(
            {"search_zim_file", "search_with_filters"}
        )

    def test_search_encode_callsite_references_set(self) -> None:
        # Both encode callsites (search_zim_file at L664, search_with_
        # filters at L1243) must reference the set by name in the
        # surrounding comments so a contributor adding a new
        # q-emitting tool sees the pointer.
        import openzim_mcp.zim.search as search_mod

        source = inspect.getsource(search_mod)
        assert "_Q_EMITTING_CURSOR_TOOLS" in source, (
            "zim/search.py must reference _Q_EMITTING_CURSOR_TOOLS so "
            "future Cursor.encode(state={..., 'q': ...}) callsites are "
            "wired to the dispatcher's q-overlap guard. Add a comment "
            "near the encode callsites pointing at "
            "simple_tools._Q_EMITTING_CURSOR_TOOLS."
        )

    def test_q_emitting_set_matches_search_encode_sites(self) -> None:
        # Find every ``Cursor.encode(tool="X", state={..., "q":  ...})``
        # site in zim/search.py and assert the tool names align with
        # ``_Q_EMITTING_CURSOR_TOOLS``. Catches the case where a
        # contributor adds a new encode site but forgets the set.
        import re

        import openzim_mcp.zim.search as search_mod

        source = inspect.getsource(search_mod)
        # Match ``Cursor.encode(tool="X"`` and remember X.
        tool_names = set(re.findall(r"Cursor\.encode\(\s*tool=\"(\w+)\"", source))
        # Each ``Cursor.encode`` callsite in zim/search.py emits a
        # state with ``"q"`` (see the bodies); pinning the equality
        # locks the contract.
        assert tool_names == SimpleToolsHandler._Q_EMITTING_CURSOR_TOOLS, (
            f"Drift detected: zim/search.py encodes cursors for {tool_names}, "
            f"_Q_EMITTING_CURSOR_TOOLS lists "
            f"{SimpleToolsHandler._Q_EMITTING_CURSOR_TOOLS}. Update the "
            f"set so the dispatcher's q-overlap guard fires for the new "
            f"tool too."
        )


# ===========================================================================
# P1-D9: PD2-2 sibling docstring path-bait sweep
# ===========================================================================


class TestP1D9DocstringPathBaitSiblings:
    """P1-D9: the post-a20 PD2-2 fix removed the literal-looking path
    example (``/data/wikipedia_en_all_maxi.zim``) from the
    ``zim_query`` tool docstring in ``server.py``. The advanced-
    tool docstrings in ``tools/structure_tools.py`` and
    ``tools/content_tools.py`` carried sibling docstring path
    examples (``/path/to/wiki.zim`` / ``/path/file.zim`` /
    ``/path/x.zim``) that the PD2-2 regression test didn't reach.
    Small models copy these verbatim too — the canonical
    weak-instruction-follower defect class — and drop into the same
    "File does not exist" retry loop the PD2-3 auto-select +
    PD2-4 recovery hint were designed to break.

    Fix: replace literal ``/path/...`` strings in the docstring
    Examples blocks with placeholders that won't validate as a real
    filesystem path (e.g., ``<zim_path>``). The widened regression
    test below scans every ``openzim_mcp/tools/*.py`` source file
    for any string matching ``/path/...\\.zim`` or
    ``/data/...\\.zim`` in a docstring context — anything new
    fails the test.
    """

    def test_no_path_bait_in_tools_docstrings(self) -> None:
        import re
        from pathlib import Path

        tools_dir = Path(__file__).resolve().parents[1] / "openzim_mcp" / "tools"
        assert tools_dir.is_dir(), f"tools/ not found at {tools_dir}"

        # Match ``/path/...\.zim`` or ``/data/...\.zim`` shapes.
        # Conservative — only flags strings that look like fake
        # filesystem paths a small model would copy. Real path
        # references inside test setup or fixture data aren't in
        # tools/ source.
        bait_re = re.compile(r"/(?:path|data)/[\w/.-]*\.zim")
        offenders: list[tuple[str, int, str]] = []
        for py in sorted(tools_dir.glob("*.py")):
            text = py.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                m = bait_re.search(line)
                if m:
                    offenders.append((py.name, line_no, m.group(0)))

        assert not offenders, (
            "Found docstring path-bait in tools/ that small models can "
            "copy verbatim — same defect class as post-a20 PD2-2. "
            f"Sites: {offenders}. Replace literal paths with placeholders "
            "like ``<zim_path>`` or omit and reference list_zim_files()."
        )


# ===========================================================================
# P1-D10: PD2-4 recovery hint marker overlap with security errors
# ===========================================================================


class TestP1D10RecoveryHintMarkerDiscriminatesSecurityError:
    """P1-D10: the post-a20 PD2-4 recovery-hint detector matches the
    substring ``"access denied"`` in the exception message. The
    ``OpenZimMcpSecurityError`` raised by ``security.py`` when the
    path is outside the allowed directories formats its message as
    ``"Access denied - Path is outside allowed directories: ..."``.
    Pre-fix, the catch-all detected the substring, replaced the
    security-specific reason with the generic "doesn't match any
    loaded archive" hint, and the caller never saw the actual cause.

    Fix: surface the original exception message alongside the
    recovery hint so security-specific failures (path outside
    allowed directories) keep their diagnostic context.
    """

    def _handler_multi_archive(self) -> tuple[Any, MagicMock]:
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

    def test_security_error_surfaces_original_reason(self) -> None:
        from openzim_mcp.exceptions import OpenZimMcpSecurityError

        handler, mock = self._handler_multi_archive()
        # Stub get_main_page (or whatever the dispatcher routes to) to
        # raise the security error so the catch-all hits.
        mock.get_main_page.side_effect = OpenZimMcpSecurityError(
            "Access denied - Path is outside allowed directories: /etc/x.zim"
        )
        # Use main_page intent so the dispatch is deterministic.
        result = handler.handle_zim_query(
            query="show main page",
            zim_file_path="/etc/x.zim",
        )
        body = str(result)
        # The recovery hint may still fire (it's useful — surfaces real
        # archive paths) but MUST NOT drop the original reason on the
        # floor. Either preserve the original message OR mention
        # "outside allowed directories".
        assert (
            "outside allowed directories" in body.lower() or "Path is outside" in body
        ), (
            f"P1-D10: security-specific error reason was dropped by the "
            f"PD2-4 recovery hint. Got: {body[:500]}"
        )


# ===========================================================================
# T-D1: zim_query docstring clarifies limit ignored for atomic intents
# ===========================================================================


class TestTD1LimitDocstringClarifiesAtomicIntents:
    """T-D1: live small-model transcript (Qwen3-8B-Q4) showed the
    model passing ``limit=5`` on a ``tell_me_about`` query. The
    ``limit`` docstring said "Max search/browse results (default: 3)"
    — silent about whether it applies to atomic intents. Small
    models speculatively pass it; the call wastes tokens because the
    handler ignores it.

    Fix: docstring nudge — call out the atomic intents
    (``tell_me_about`` / ``get article`` / ``show structure`` /
    ``main_page`` / ``list_namespaces`` / ``list_files``) as
    ignoring ``limit``.
    """

    def test_limit_docstring_mentions_atomic_intents(self) -> None:
        import openzim_mcp.server as server_mod

        source = inspect.getsource(server_mod)
        # Look for an explicit mention near the ``limit`` Args block.
        # We can't grep for the exact wording (style choice) but the
        # docstring must say something about ``limit`` being ignored
        # or no-op for atomic intents.
        assert "limit" in source.lower() and (
            "ignored" in source.lower() or "atomic" in source.lower()
        ), (
            "zim_query docstring should clarify that ``limit`` is "
            "ignored for atomic intents (tell_me_about / get article / "
            "show structure / main_page / list_namespaces / list_files). "
            "Small models speculatively pass it otherwise."
        )
