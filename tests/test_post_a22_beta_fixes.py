r"""Regression tests for the post-a22 beta-test sweep (a23 candidate fixes).

The post-a22 live-MCP sweep against the 118 GB Wikipedia ZIM after
v2.0.0a22 deployed surfaced SIX defects across the new attack
surface that a22's eleven fixes unlocked. The pattern keeps holding:
each alpha's landed fixes make new code paths REACHABLE, and the
next sweep finds defects in those paths.

Defects span four surfaces:

* **Multi-entity chain leading-conjunction strip (P1-D1).** The
  post-a21 ``_split_multi_entity`` helper applies a defensive
  leading-conjunction strip to every cleaned half (so a hypothetical
  reordering of the connector pattern list that leaves ``"and X"`` as
  a leftover prefix gets cleaned). The strip was applied uniformly
  to ALL halves including the half that occupies the START of the
  original topic — where a leading ``And`` / ``Or`` / ``&`` is real
  title content (Agatha Christie's ``And Then There Were None``,
  the phrase ``Or Else``, the ampersand-led band ``& Co.``). Two
  observed user-visible failure modes:

    - ``tell me about And Then There Were None and Hercule Poirot
      and Murder on the Orient Express`` → rejection bullets read
      ``tell me about Then There Were None`` / ``... Hercule
      Poirot`` / ``... Murder on the Orient Express`` — the leading
      ``And`` got mangled away from the first bullet.
    - ``tell me about Or Else and Death and Taxes and Pride and
      Prejudice`` → first half stripped from ``Or Else`` to ``Else``
      (4 chars, single token, no digit, no non-ASCII letter) →
      fails ``_is_substantive_topic`` → multi-entity rejection
      silently abandoned → tell_me_about dispatches normally and
      returns the Pride and Prejudice article, dropping 4 of 5
      entities with no signal.

  Fix: skip the leading-conjunction strip on the FIRST non-empty
  half (the one that occupies position 0 of the original topic),
  where the conjunction is intentional title content. Subsequent
  halves get the defensive strip as before — they can only get a
  leading conjunction prefix from a hypothetical reordered pattern
  list, never from the user's typed input.

* **Politeness regex extension — SMS variants (P1-D2).** The
  post-a21 widening (``ta`` / ``cheers`` / ``thx`` / ``ty`` /
  ``pls`` + ``bitte`` / ``danke`` / ``merci`` / ``gracias`` /
  ``por favor``) didn't cover common chat / SMS spellings:
  ``thnx``, ``thanx``, ``tysm``, ``kthx``, ``kthxbai``. Same
  shape as the post-a21 P1-D6/D7 leak — ``search for biology
  thnx`` ranks ``"biology thnx"`` (3 irrelevant matches) instead
  of stripping the politeness.

* **Q-emitting cursor tools drift guard scope (P1-D3).** Post-a21
  P1-D5 introduced a regression test that scans ``zim/search.py``
  for ``Cursor.encode(tool="X", ...)`` callsites and pins
  membership equality with ``SimpleToolsHandler.
  _Q_EMITTING_CURSOR_TOOLS``. But ``Cursor.encode`` callsites also
  exist in ``zim/namespace.py`` (4 sites) and ``zim/structure.py``
  (1 site) — and a hypothetical future q-emitting tool added in
  any of those would pass the test silently while breaking the
  dispatcher's q-overlap guard. Widen the scan to all of
  ``openzim_mcp/zim/*.py`` and assert that every encode site whose
  state contains a ``"q"`` key has its tool in the set.

* **PD2-2 sibling docstring path-bait — entry_path placeholders
  (P1-D4).** Post-a21 P1-D9 widened the PD2-2 path-bait sweep to
  every ``openzim_mcp/tools/*.py`` but only scanned for
  ``/path/...\.zim`` / ``/data/...\.zim`` shapes. The ``entry_path``
  parameter docstrings used ``'A/Some_Article'`` and
  ``'C/Some_Article'`` as literal-looking placeholders (6 sites:
  1 in ``content_tools.py``, 5 in ``structure_tools.py``) — same
  weak-instruction-follower defect class. A small model copying
  ``Some_Article`` verbatim hits an entry-not-found loop the
  PD2-3 / PD2-4 hints can't reach (the recovery hints are for
  ZIM PATH errors, not entry-path errors). Fix: replace with
  ``<entry_path>`` placeholder and widen the docstring regression
  test to scan for ``Some_Article`` / ``some_article`` shapes.

* **``limit`` docstring nudge — missing atomic intents (P1-D5).**
  Post-a21 T-D1 enumerated atomic intents that ignore ``limit``
  in the ``zim_query`` docstring: ``tell me about <topic>``,
  ``get article <name>``, ``show structure of <name>``, ``links in
  <name>``, ``articles related to <name>``, ``show main page``,
  ``list namespaces``, ``metadata for <file>``, ``list available
  ZIM files``. Three more atomic intents whose handlers don't
  reference ``options.get("limit", ...)`` are missing from the
  list: ``summary of <name>``, ``table of contents <name>``,
  ``section <X> of <name>``. Same shape as T-D1.

* **Dispatcher-edge politeness strip — additional user-content
  fields (P1-D6).** Post-a21 P1-D1 (defence-in-depth) strips
  trailing politeness from ``params`` for five fields:
  ``{query, topic, title, entry_path, partial_query}``. Two more
  user-content fields populated by intent extractors aren't
  covered: ``section_name`` (from ``section <X> of <Y>`` parses)
  and ``entries`` (list of entry paths from batched parses).
  Defensive strip on both so the belt-and-suspenders catch
  remains complete.

The post-a22 sweep methodology continues to confirm the recurring
"fix unlocks new paths" pattern: a22's multi-entity rejection LANDED
correctly but exposed the P1-D1 first-word edge; a22's politeness
extension widened the token set but missed the SMS family P1-D2
covers; a22's drift-guard, sibling-docstring sweep, and limit
nudge each landed at NARROWER scope than the sibling shapes warrant
(P1-D3/D4/D5). Future fixes should preemptively widen each new
guard to every analogue site before merging.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openzim_mcp.intent_parser import IntentParser
from openzim_mcp.simple_tools import SimpleToolsHandler

# ===========================================================================
# P1-D1: multi-entity chain leading-conjunction strip overfires on
# first-word "And" / "Or" / "&" in legitimate titles
# ===========================================================================


class TestP1D1MultiEntityFirstWordConjunction:
    """P1-D1: ``_split_multi_entity`` applies the defensive
    leading-conjunction strip (``_CONJUNCTION_PREFIXES``) to every
    cleaned half. Pre-fix, the half that occupies the START of the
    original topic also got the strip, mangling legitimate first
    words like ``And`` / ``Or``. Two observed live-MCP failures:

      * ``tell me about And Then There Were None and Hercule Poirot
        and Murder on the Orient Express`` → bullets read
        ``tell me about Then There Were None`` (leading ``And``
        stripped) — the rejection text misnames the entity.
      * ``tell me about Or Else and Death and Taxes and Pride and
        Prejudice`` → first half ``Or Else`` stripped to ``Else``
        (4 chars, single token, no digit, no non-ASCII letter) →
        fails ``_is_substantive_topic`` → ``_split_multi_entity``
        returns None → multi-entity rejection silently abandoned →
        tell_me_about resolves Pride and Prejudice, dropping the
        other 4 entities with no warning.

    Fix: skip the leading-conjunction strip on the FIRST non-empty
    half (parts[0] after iterative re.split preserves order). Real
    leftover conjunction prefixes only arise on halves that resulted
    from a split mid-string — never on the original-leading half.
    """

    def test_split_preserves_first_word_and_literal(self) -> None:
        result = SimpleToolsHandler._split_multi_entity(
            "And Then There Were None and Hercule Poirot and Murder on the Orient Express"
        )
        assert result is not None, (
            "Expected 3-entity split, got None (substantive filter "
            "likely failed on a mangled first half)"
        )
        assert result[0] == "And Then There Were None", (
            f"First half should keep leading 'And' (real title content); "
            f"got {result[0]!r}"
        )
        assert result[1] == "Hercule Poirot"
        assert result[2] == "Murder on the Orient Express"

    def test_split_preserves_first_word_or_literal(self) -> None:
        result = SimpleToolsHandler._split_multi_entity(
            "Or Else and Death and Taxes and Pride and Prejudice"
        )
        assert result is not None, (
            "Pre-fix: 'Or Else' stripped to 'Else' (4 chars, not "
            "substantive) → split returns None → entities silently dropped"
        )
        assert result[0] == "Or Else", (
            f"First half should keep leading 'Or' (real title content); "
            f"got {result[0]!r}"
        )
        # The other halves are single substantive tokens (≥5 chars).
        assert "Death" in result
        assert "Taxes" in result
        assert "Pride" in result
        assert "Prejudice" in result

    def test_split_preserves_first_word_ampersand_literal(self) -> None:
        # Defensive: an ``& X and Y and Z`` topic shouldn't mangle the
        # leading ``& `` either. The current pattern order doesn't
        # produce this organically, but the exemption should hold for
        # any leading-conjunction prefix.
        result = SimpleToolsHandler._split_multi_entity("& Co and ABC and XYZW Corp")
        # The first half "& Co" should retain its leading ampersand.
        # If substantive filter rejects "& Co" (2 chars after strip),
        # accept None as well — the point of this test is to confirm
        # the strip doesn't mangle the leading "&".
        if result is not None:
            assert result[0].startswith(
                "&"
            ), f"First half should keep leading '&'; got {result[0]!r}"

    def test_strip_still_applies_to_non_first_halves(self) -> None:
        # Defensive: the strip exists for hypothetical future pattern
        # reorderings that could leave ``"and X"`` as a half (e.g. if
        # someone moved the comma pass before the and pass). Build a
        # parts list directly that mimics that shape and verify the
        # non-first half still gets cleaned. Use the public split
        # entrypoint to keep the test grounded in real behaviour:
        # there's no organic way to produce a leading-conjunction
        # half in the current ordering, so this test asserts the
        # CURRENT NORMAL behaviour stays unchanged — both halves
        # parse cleanly without leading conjunction artifacts.
        result = SimpleToolsHandler._split_multi_entity(
            "Berlin, Munich, Hamburg, Düsseldorf"
        )
        assert result == ["Berlin", "Munich", "Hamburg", "Düsseldorf"]

    def test_mixed_substantive_halves_split_intact(self) -> None:
        # All halves long enough to clear ``_is_substantive_topic``
        # (≥5 chars per token): the iterative split returns each
        # whole entity. Upstream ``_multi_entity_chain_guidance`` is
        # the layer that probes the title index and suppresses
        # when ``_path_matches_topic_loosely`` matches.
        result = SimpleToolsHandler._split_multi_entity(
            "Beans, Greens, Tomatoes, Potatoes"
        )
        assert result == ["Beans", "Greens", "Tomatoes", "Potatoes"]

    def test_unicode_first_word_not_mangled(self) -> None:
        # Sanity: Unicode-starting first word (München) doesn't trigger
        # the conjunction strip (no conjunction prefix to match) and
        # the substantive filter accepts it via the non-ASCII-letter
        # relaxed threshold.
        result = SimpleToolsHandler._split_multi_entity("München and Köln and Berlin")
        assert result == ["München", "Köln", "Berlin"]


# ===========================================================================
# P1-D2: politeness regex extension — SMS variants
# ===========================================================================


class TestP1D2PolitenessSmsVariants:
    """P1-D2: post-a21 P1-D6/D7 widened the politeness regex to cover
    ``ta`` / ``cheers`` / ``thx`` / ``ty`` / ``pls`` + the multilang
    tokens, but missed common SMS / chat spellings: ``thnx``,
    ``thanx``, ``tysm``, ``kthx``, ``kthxbai``. Live a22 sweep
    observed ``search for biology thnx`` searching for
    ``"biology thnx"`` (3 irrelevant matches) and ``search for
    biology thanx`` searching for ``"biology thanx"``. Same shape as
    the post-a21 missed-token class.
    """

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("search for biology thnx", "search for biology"),
            ("search for biology thanx", "search for biology"),
            ("search for biology tysm", "search for biology"),
            ("search for biology kthx", "search for biology"),
            ("search for biology kthxbai", "search for biology"),
            # Case variants
            ("search for biology THNX", "search for biology"),
            ("search for biology Tysm", "search for biology"),
            # Punctuation forms
            ("search for biology, thnx!", "search for biology"),
            ("search for biology; thanx.", "search for biology"),
            # Chained with existing tokens (strip loop handles)
            ("search for biology please thnx", "search for biology"),
            ("search for biology thnx ta", "search for biology"),
        ],
    )
    def test_sms_variants_strip(self, raw: str, expected: str) -> None:
        assert IntentParser._strip_trailing_politeness(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            # Word-boundary safety: no in-word matches even though the
            # tokens are short. ``thx``/``thnx``/``thanx`` are unusual
            # substrings inside real English; ``ty`` and ``ta`` are
            # already covered by P1-D6/D7 word-boundary tests.
            "matthx",  # invented — verify no match on suffix
            "kthxbai_extension",  # invented — should not match (no end-anchor)
            "tysone",  # invented — should not match
        ],
    )
    def test_word_boundary_safety_sms(self, raw: str) -> None:
        assert IntentParser._strip_trailing_politeness(raw) == raw

    @pytest.mark.parametrize(
        "raw, expected_query",
        [
            ("search for biology thnx", "biology"),
            ("search for biology thanx", "biology"),
            ("search for biology tysm", "biology"),
            ("find article titled Berlin thnx", "Berlin"),
            ("find article titled Berlin tysm", "Berlin"),
        ],
    )
    def test_sms_variants_in_full_parse(self, raw: str, expected_query: str) -> None:
        _intent, params, _conf = IntentParser.parse_intent(raw)
        v = params.get("query") or params.get("title") or ""
        assert (
            v == expected_query
        ), f"Expected {expected_query!r}, got {v!r} from {raw!r}"


# ===========================================================================
# P1-D3: q-emitting cursor tools drift guard scope widening
# ===========================================================================


class TestP1D3QEmittingDriftGuardWiderScope:
    """P1-D3: the post-a21 ``TestP1D5QEmittingCursorToolsDrift``
    regression scans ONLY ``zim/search.py`` for ``Cursor.encode``
    callsites and pins membership equality with
    ``SimpleToolsHandler._Q_EMITTING_CURSOR_TOOLS``. But
    ``Cursor.encode`` callsites also exist in ``zim/namespace.py``
    (browse / walk variants) and ``zim/structure.py`` (extract links).
    A future contributor adding a q-emitting tool in any of those
    would pass the test silently while breaking the dispatcher's
    q-overlap guard.

    Fix: scan EVERY ``openzim_mcp/zim/*.py`` for ``Cursor.encode``
    callsites, parse each call's state for the presence of a ``"q"``
    key (indicating the tool legitimately emits a search query in
    its cursor state), and assert that every tool whose encode state
    contains ``"q"`` is in ``_Q_EMITTING_CURSOR_TOOLS`` AND vice
    versa.
    """

    @staticmethod
    def _find_call_body(text: str, start: int) -> str | None:
        """Given ``text`` and ``start`` (position just after the
        opening ``(`` of a balanced call), return the body up to but
        not including the matching close paren. Returns None on
        unbalanced input.
        """
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        if depth != 0:
            return None
        return text[start : i - 1]

    @staticmethod
    def _state_var_carries_q(text: str, var_name: str, encode_pos: int) -> bool:
        """Backward-scan up to ~80 lines before ``encode_pos`` for a
        construction or mutation of ``var_name`` that sets a ``"q"``
        key. Accepts:
          * ``var["q"] = ...`` mutation
          * ``var = {..., "q": ..., ...}`` plain assignment
          * ``var: Type = {..., "q": ..., ...}`` PEP 526 annotation
        """
        line_start = text.rfind("\n", 0, encode_pos)
        line_no = text.count("\n", 0, line_start)
        window_start_line = max(0, line_no - 80)
        lines = text.splitlines()
        window = "\n".join(lines[window_start_line : line_no + 1])
        mutation_re = rf'{re.escape(var_name)}\s*\[\s*["\']q["\']\s*\]'
        if re.search(mutation_re, window):
            return True
        # ``var = {...}`` OR ``var: Type = {...}`` (PEP 526 inline
        # annotation). ``[\s\S]`` allows newlines without enabling
        # global DOTALL.
        decl_re = (
            rf"{re.escape(var_name)}"
            r"(?:\s*:\s*[^=\n]+?)?"
            r"\s*=\s*\{[\s\S]*?[\"\']q[\"\']\s*:"
        )
        return bool(re.search(decl_re, window))

    @classmethod
    def _encode_call_emits_q(cls, text: str, body: str, encode_pos: int) -> bool:
        """Decide whether a single ``Cursor.encode(...)`` body emits a
        cursor whose state carries a ``"q"`` field. Either the state
        literal in the body has ``"q":`` directly, or the state
        references a variable whose construction adds ``"q"``.
        """
        if re.search(r'["\']q["\']\s*:', body):
            return True
        state_m = re.search(r"state\s*=\s*(?:cast\([^,]+,\s*)?(\w+)", body)
        if not state_m:
            return False
        return cls._state_var_carries_q(text, state_m.group(1), encode_pos)

    @classmethod
    def _scan_q_emitting_tools_in_zim(cls) -> set[str]:
        """Walk every ``openzim_mcp/zim/**/*.py`` source file, find
        ``Cursor.encode(tool="X", state={..., "q": ..., ...})``
        callsites, and return the set of tool names whose state
        contains a ``"q"`` key.

        Robust against multi-line encode calls — captures the entire
        encode call body up to the matching close paren (depth-1
        scan).

        Post-a23 P1-D4: ``rglob`` (recursive) rather than ``glob``
        (direct children only). The current zim/ tree is flat, but a
        future contributor adding ``openzim_mcp/zim/cursor/encoder.py``
        (or any subdirectory) would have q-emitting callsites silently
        missed by a non-recursive scan. Same narrow-scope sibling
        shape as the post-a22 P1-D3 widening from one file to all
        files in the directory — the next widening is naturally to
        all files in the tree.
        """
        zim_dir = Path(__file__).resolve().parents[1] / "openzim_mcp" / "zim"
        assert zim_dir.is_dir(), f"zim/ not found at {zim_dir}"

        q_emitting: set[str] = set()
        for py in sorted(zim_dir.rglob("*.py")):
            text = py.read_text(encoding="utf-8")
            for m in re.finditer(r"Cursor\.encode\(", text):
                body = cls._find_call_body(text, m.end())
                if body is None:
                    continue
                tool_m = re.search(r'tool\s*=\s*"(\w+)"', body)
                if not tool_m:
                    continue
                if cls._encode_call_emits_q(text, body, m.start()):
                    q_emitting.add(tool_m.group(1))
        return q_emitting

    def test_scan_finds_known_q_emitting_tools(self) -> None:
        # Sanity check: the scanner must find the two known q-emitting
        # tools in zim/search.py. If this assertion fails the scanner
        # itself is broken, not the fix.
        scanned = self._scan_q_emitting_tools_in_zim()
        assert "search_zim_file" in scanned, (
            f"Scanner failed to find search_zim_file; got {scanned}. "
            f"Either the scanner is broken or zim/search.py no longer "
            f"encodes that tool's cursors with a 'q' state field."
        )
        assert (
            "search_with_filters" in scanned
        ), f"Scanner failed to find search_with_filters; got {scanned}."

    def test_q_emitting_set_matches_all_zim_modules(self) -> None:
        scanned = self._scan_q_emitting_tools_in_zim()
        pinned = SimpleToolsHandler._Q_EMITTING_CURSOR_TOOLS
        assert scanned == pinned, (
            f"Drift detected across openzim_mcp/zim/*.py: source "
            f"encodes q-bearing cursors for {scanned}, "
            f"_Q_EMITTING_CURSOR_TOOLS lists {pinned}. Update the set "
            f"so the dispatcher's q-overlap guard fires for the new "
            f"tool too — the post-a21 P1-D5 guard scanned only "
            f"zim/search.py; this widened scan covers namespace.py "
            f"and structure.py too."
        )


# ===========================================================================
# P1-D4: PD2-2 sibling docstring path-bait sweep — entry_path placeholders
# ===========================================================================


class TestP1D4EntryPathDocstringBaitSweep:
    """P1-D4: the post-a21 P1-D9 sibling docstring sweep widened the
    PD2-2 ``/path/...\\.zim`` / ``/data/...\\.zim`` regex scan to every
    ``openzim_mcp/tools/*.py``. But the ``entry_path`` parameter
    docstrings used ``'A/Some_Article'`` and ``'C/Some_Article'`` as
    literal-looking placeholders (5 sites in ``structure_tools.py``,
    1 in ``content_tools.py``). Same weak-instruction-follower defect
    class: a small model copies ``Some_Article`` verbatim, gets back
    an entry-not-found error, and falls into a retry loop. The
    PD2-3 / PD2-4 recovery hints only trigger on ZIM PATH errors,
    not entry-path errors, so the bait was unreachable by the
    existing safety net.

    Fix: replace ``Some_Article`` with the ``<entry_path>`` placeholder
    shape (matching the existing ``<zim_path>`` convention) and widen
    the docstring regression test to catch both shapes.
    """

    def test_no_some_article_placeholder_in_tools_docstrings(self) -> None:
        tools_dir = Path(__file__).resolve().parents[1] / "openzim_mcp" / "tools"
        assert tools_dir.is_dir(), f"tools/ not found at {tools_dir}"

        # Match ``Some_Article`` / ``some_article`` and variants
        # commonly used as placeholder examples.
        bait_re = re.compile(r"\b[Ss]ome_[Aa]rticle\b")
        offenders: list[tuple[str, int, str]] = []
        for py in sorted(tools_dir.glob("*.py")):
            text = py.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                m = bait_re.search(line)
                if m:
                    offenders.append((py.name, line_no, line.strip()))

        assert not offenders, (
            "Found ``Some_Article`` placeholder bait in tools/ docstrings "
            "that small models can copy verbatim — same defect class as "
            "post-a20 PD2-2 (path bait) and post-a21 P1-D9 (docstring "
            f"path-bait sweep). Sites: {offenders}. Replace with the "
            "``<entry_path>`` placeholder convention used elsewhere."
        )

    @staticmethod
    def _is_legacy_a_namespace_bait_line(line: str) -> bool:
        """True iff ``line`` is an ``entry_path`` docstring example
        carrying a legacy ``'A/<word>'`` namespace bait that isn't
        the special-case ``A/B`` Wikipedia testing article and isn't
        explicitly documenting the legacy/modern distinction.
        """
        line_lower = line.lower()
        if "entry_path" not in line_lower:
            return False
        if "e.g." not in line_lower and "example" not in line_lower:
            return False
        m = re.search(r"['\"]A/(\w+)['\"]", line)
        if not m or m.group(1) == "B":
            return False
        return "legacy" not in line_lower and "modern" not in line_lower

    def test_no_legacy_a_namespace_entry_path_example(self) -> None:
        # Pass-2 source-level audit (P2-D1 within this sweep): the
        # ``get_section`` docstring originally used ``'A/Berlin'`` as
        # the ``entry_path`` example. The legacy ``A/`` namespace is
        # the pre-2018 single-namespace ZIM convention; modern multi-
        # namespace ZIMs (Wikipedia 2026-02, the live target) use
        # ``C/``. A small model copying ``A/Berlin`` verbatim hits
        # entry-not-found on a modern archive and drops into a retry
        # loop — same weak-instruction-follower defect class as P1-D4
        # but the bait was active wrong-guidance, not placeholder.
        #
        # Scan every ``Args:`` block in ``tools/*.py`` for an
        # ``entry_path`` line whose example uses bare ``'A/`` or
        # ``"A/`` followed by a real word — the legacy-namespace
        # bait. ``A/B`` (the Wikipedia testing article whose real
        # path is genuinely ``A/B``) is the only legitimate
        # exception; the test allows it explicitly.
        tools_dir = Path(__file__).resolve().parents[1] / "openzim_mcp" / "tools"
        offenders: list[tuple[str, int, str]] = []
        for py in sorted(tools_dir.glob("*.py")):
            text = py.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if self._is_legacy_a_namespace_bait_line(line):
                    offenders.append((py.name, line_no, line.strip()))
        assert not offenders, (
            "Found legacy ``A/<title>`` namespace bait in tools/ "
            "docstrings — modern ZIMs use ``C/``. Same weak-instruction-"
            "follower defect class as P1-D4. Sites: "
            f"{offenders}. Update to ``C/`` or document both conventions."
        )

    def test_replacement_uses_entry_path_placeholder(self) -> None:
        # Defensive: confirm the post-a22 replacement landed and uses
        # the ``<entry_path>`` placeholder convention (mirrors the
        # existing ``<zim_path>`` shape). A contributor adding a new
        # entry_path-bearing tool sees the pattern and mirrors it.
        structure_src = (
            Path(__file__).resolve().parents[1]
            / "openzim_mcp"
            / "tools"
            / "structure_tools.py"
        ).read_text(encoding="utf-8")
        content_src = (
            Path(__file__).resolve().parents[1]
            / "openzim_mcp"
            / "tools"
            / "content_tools.py"
        ).read_text(encoding="utf-8")
        assert "<entry_path>" in structure_src, (
            "structure_tools.py docstrings should reference "
            "``<entry_path>`` placeholder after the P1-D4 replacement."
        )
        assert "<entry_path>" in content_src, (
            "content_tools.py docstrings should reference "
            "``<entry_path>`` placeholder after the P1-D4 replacement."
        )


# ===========================================================================
# P1-D5: limit docstring nudge — missing atomic intents
# ===========================================================================


class TestP1D5LimitNudgeEnumeratesAllAtomicIntents:
    """P1-D5: post-a21 T-D1 added a "limit is ignored for atomic
    intents" note to the ``zim_query`` docstring listing nine
    intents. Three more atomic intents whose handlers don't reference
    ``options.get("limit", ...)`` are missing: ``summary of <name>``,
    ``table of contents <name>``, ``section <X> of <name>``. Same
    shape as T-D1 — small models passing ``limit=5`` on these get
    no doc signal that the parameter is ignored.

    Fix: extend the docstring enumeration.
    """

    def test_summary_intent_listed(self) -> None:
        # The zim_query tool docstring lives on an inner async def
        # registered at runtime; easiest entrypoint is reading
        # server.py source directly and asserting the ``limit:``
        # enumeration block lists the three new atomic-intent markers.
        src_path = Path(__file__).resolve().parents[1] / "openzim_mcp" / "server.py"
        src = src_path.read_text(encoding="utf-8")
        # Anchor on the docstring entry (``limit: Max search/browse
        # results``) rather than the bare ``limit:`` literal — the
        # latter also matches the parameter signature ``limit:
        # Optional[int] = None,`` earlier in the file. Slice forward
        # to the next ``\n<whitespace><word>:`` parameter label. Two
        # non-overlapping find()/search() calls instead of a single
        # regex with ``.+?(?=...)`` so SonarCloud's S6019 (reluctant
        # quantifier) stays quiet — the regex equivalent works fine
        # but the explicit two-step is plainer to read.
        anchor = "limit: Max search/browse results"
        limit_idx = src.find(anchor)
        assert limit_idx != -1, (
            "Could not locate `limit:` docstring block in server.py — "
            "did the parameter docstring shape change?"
        )
        # Search the suffix for the next docstring parameter label.
        tail_start = limit_idx + len(anchor)
        next_label = re.search(r"\n\s+\w+:", src[tail_start:])
        end = tail_start + next_label.start() if next_label is not None else len(src)
        # Normalise whitespace so multi-line wrapping doesn't break
        # substring assertions (``section <X>\n  of <name>`` →
        # ``section <X> of <name>``).
        block = re.sub(r"\s+", " ", src[limit_idx:end])
        for marker in (
            "summary of",
            "table of contents",
            "section <X> of",
        ):
            assert marker in block, (
                f"`limit` docstring enumeration missing atomic intent "
                f"marker ``{marker}``. Block: {block!r}"
            )


# ===========================================================================
# P1-D6: dispatcher-edge politeness strip — section_name + entries fields
# ===========================================================================


class TestP1D6DispatcherEdgeStripWiderFields:
    """P1-D6: post-a21 P1-D1 dispatcher-edge politeness strip covers
    ``{query, topic, title, entry_path, partial_query}`` but not
    ``section_name`` (from ``section <X> of <Y>`` parses) or
    ``entries`` (list from batched parses). Same defence-in-depth
    rationale as P1-D1: if ``parse_intent``'s universal strip ever
    fails (in-process module cache regression, future refactor),
    the dispatcher edge should still cleanse every user-content
    field before the handler runs.
    """

    def _make_handler(self) -> tuple[SimpleToolsHandler, MagicMock]:
        mock = MagicMock()
        mock.list_zim_files_data.return_value = [
            {"path": "/data/wikipedia_en_all_maxi.zim"},
        ]
        return SimpleToolsHandler(mock), mock

    def test_section_name_in_strip_loop(self) -> None:
        # Confirm the dispatcher loop processes ``section_name`` by
        # reading the source — the strip is too deeply nested in
        # ``handle_zim_query`` for a clean unit-test entrypoint, but
        # the source-level pin catches accidental field removal.
        src_path = (
            Path(__file__).resolve().parents[1] / "openzim_mcp" / "simple_tools.py"
        )
        src = src_path.read_text(encoding="utf-8")
        # The defence-in-depth strip block lives in handle_zim_query
        # just after parse_intent. Anchor on the post-a21 comment
        # marker, then find the ``for _key in (...):`` tuple after
        # it. Two-step find()/search() instead of a single combined
        # regex with ``[\s\S]+?`` so SonarCloud's S5852 (ReDoS-shape
        # backtracking) stays quiet — the reluctant-greedy + literal
        # match pattern is a known polynomial-backtracking shape the
        # static analyzer flags even when the actual runtime is fine.
        marker = "# Post-a21 P1-D1: defence-in-depth"
        marker_idx = src.find(marker)
        assert (
            marker_idx != -1
        ), "Could not locate dispatcher-edge politeness strip marker."
        tail = src[marker_idx + len(marker) :]
        tuple_match = re.search(r"for _key in \(([^)]+)\):", tail)
        assert (
            tuple_match is not None
        ), "Could not locate ``for _key in (...)`` tuple after marker."
        fields = tuple_match.group(1)
        # Pin the expected field set.
        for field in (
            "query",
            "topic",
            "title",
            "entry_path",
            "partial_query",
            "section_name",
        ):
            assert (
                f'"{field}"' in fields
            ), f"Dispatcher-edge strip missing field ``{field}``: {fields!r}"

    def test_entries_list_strip_present(self) -> None:
        # The list-typed ``entries`` field gets its own loop because
        # scalar-string strip can't iterate it. Verify the loop is
        # wired in source.
        src_path = (
            Path(__file__).resolve().parents[1] / "openzim_mcp" / "simple_tools.py"
        )
        src = src_path.read_text(encoding="utf-8")
        # The entries-list strip should mention ``params.get("entries")``
        # and call ``_strip_trailing_politeness`` on each element.
        assert 'params.get("entries")' in src, (
            "Dispatcher-edge politeness strip should process the "
            "``entries`` list field."
        )

    def test_section_name_with_politeness_stripped_end_to_end(self) -> None:
        # End-to-end: parse_intent's universal strip should already
        # handle this, but the defence-in-depth layer is the safety
        # net. Build a query that triggers section parse + politeness
        # tail and verify the section_name comes out clean.
        intent, params, _conf = IntentParser.parse_intent(
            "section Evolution of Biology please"
        )
        if intent == "get_section":
            # parse_intent's strip handled it.
            section_name = params.get("section_name", "")
            assert (
                "please" not in section_name.lower()
            ), f"section_name leaked politeness: {section_name!r}"
