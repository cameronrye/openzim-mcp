r"""Regression tests for the post-b4 beta-test sweep.

The post-b4 live-MCP sweep against v2.0.0b4 verified the b3 fix (the
full-topic ``find_title_match(min_score=0.95)`` probe at pass-0 of
``_promote_topic_via_title_index``) on three of the four user-listed
verification cases. ``tell me about Darwin's evolution`` still
returned ``Evolution`` — exposing two siblings of the same
apostrophe-tokenization defect class, plus a gate-semantics defect in
the new pass-0 itself.

## D1 — b4 pass-0 gate cannot distinguish redirect-0.95 from fuzzy-0.95

``find_entry_by_title_data`` scores libzim's suggestion-search results
on a linearly-decaying rank formula capped at 0.95 (zim/search.py
:2814-2822). The same 0.95 score is produced by:

  * a **redirect walk** — suggestion returned the redirect entry
    (``Plato's_cave``) → ``_follow_redirect_chain`` walked to the
    canonical (``Allegory_of_the_cave``); meaningful relationship
    between topic and result
  * a **pure fuzzy title-prefix match** — suggestion returned a title
    that fuzzy-matches the input (``Evolution`` for the query
    ``Darwin's evolution``); no meaningful relationship beyond
    superficial token overlap

The b4 gate at ``min_score=0.95`` accepts both. ``tell me about
Darwin's evolution`` → ``Evolution`` at cert=0.85 (silent-wrong-
answer); same shape for ``tell me about Darwin's evolution history`` →
``Darwin's_Ghosts:_The_Secret_History_of_Evolution`` (judgment-call
over-promotion at the 0.95 fuzzy reach).

## D2 — pass-1 ``iter_query_tails`` still strips apostrophes

The b4 fix only patched pass-0. Pass-1 (``iter_query_tails`` at
``simple_tools.py:3925``) still consumes ``_TAIL_TOKEN_RE`` at
``title_promotion.py:188`` which treats apostrophes as token boundaries.
For prose-with-possessive queries where the full topic is NOT
canonical at the 0.95 gate, pass-1 strips the apostrophe and picks
the shortest tail. Live silent-wrong-answers (cert=0.85):

  * ``tell me about Plato's republic philosophy`` → ``Philosophy``
  * ``tell me about Einstein's theory history`` → ``History``
  * ``tell me about Einstein's theory tourism`` → ``Tourism``

The defect shape is: any prose-with-possessive whose trailing token
is a Wikipedia-canonical generic word wins pass-1 at strict 1.0.

## D3 — synthesize ``_promote_title_match`` never got the b4 treatment

PR #169 only touched ``_promote_topic_via_title_index`` (the tell-me-
about path). ``_promote_title_match`` in ``synthesize.py:869-950``
iterates ``iter_query_tails(query)`` at line 915 without the b4
pass-0 full-query probe. Live (``synthesize=true``):

  * ``Einstein's theory`` → top citation ``Theory`` (expected
    ``Theory_of_relativity``)
  * ``Plato's cave`` → top citation ``Cave`` (correct answer
    demoted to rank 2)

## D5 (latent) — pass-2 windows + pass-3 typo-tolerant tails

``iter_query_windows`` and the pass-3 0.8-fuzzy tail probe share the
same tokenizer and would strip apostrophes too, but are masked in
practice because pass-1 finds a strict-1.0 single-token tail before
they fire. Fixed for free by the tokenizer change.

## Fixes

1. **match_type annotation** — ``find_entry_by_title_data`` now
   tags each result row with a ``match_type`` ∈ ``{"direct",
   "redirect", "fuzzy_suggest", "typo_corrected"}``. ``find_title_match``
   propagates it through to its returned dict.

2. **Pass-0 gate filter** — ``_promote_topic_via_title_index`` pass-0
   and the new synthesize-side pass-0 reject results with
   ``match_type == "fuzzy_suggest"``. The 0.95 score is only safe to
   auto-fetch when it represents a canonical redirect; pure fuzzy-
   prefix matches at the same score are silent-wrong-answer risks.
   Pass-3 (typo-tolerant 0.8 tail) also applies the filter so the
   same fuzzy-suggest leak can't sneak through the lower gate.

3. **Tokenizer fix** — ``_TAIL_TOKEN_RE`` keeps apostrophes (both
   straight ``'`` and curly ``’``) inside alphanumeric runs, so
   ``einstein's`` stays one token.

4. **Possessive min_len floor** — when the topic contains an
   apostrophe-possessive, pass-1 / pass-3 / synthesize-pass-1 use
   ``min_len=2`` so a generic 1-token tail can't silently win. The
   pass-0 full-topic probe handles the legitimate "X's Y is
   canonical" case; tail iteration past 1 token would otherwise just
   risk picking a generic Wikipedia title.

5. **Synthesize pass-0** — ``_promote_title_match`` now mirrors the
   ``_promote_topic_via_title_index`` pass-0 probe at the start, with
   the same match_type filter.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch


class TestMatchTypePropagation:
    """``find_title_match`` must propagate the ``match_type`` field
    from the underlying ``find_entry_by_title_data`` result row so
    callers can distinguish redirect-walks from incidental fuzzy
    title-prefix matches."""

    def test_propagates_match_type_direct(self) -> None:
        from openzim_mcp.title_promotion import find_title_match

        mock = MagicMock()
        mock.find_entry_by_title_data.return_value = {
            "results": [
                {
                    "path": "Berlin",
                    "title": "Berlin",
                    "score": 1.0,
                    "match_type": "direct",
                }
            ]
        }
        result = find_title_match(mock, "/x.zim", "Berlin")
        assert result is not None
        assert result["match_type"] == "direct"

    def test_propagates_match_type_redirect(self) -> None:
        from openzim_mcp.title_promotion import find_title_match

        mock = MagicMock()
        mock.find_entry_by_title_data.return_value = {
            "results": [
                {
                    "path": "Allegory_of_the_cave",
                    "title": "Allegory of the cave",
                    "score": 0.95,
                    "match_type": "redirect",
                }
            ]
        }
        result = find_title_match(mock, "/x.zim", "Plato's cave", min_score=0.95)
        assert result is not None
        assert result["match_type"] == "redirect"

    def test_propagates_match_type_fuzzy_suggest(self) -> None:
        from openzim_mcp.title_promotion import find_title_match

        mock = MagicMock()
        mock.find_entry_by_title_data.return_value = {
            "results": [
                {
                    "path": "Evolution",
                    "title": "Evolution",
                    "score": 0.95,
                    "match_type": "fuzzy_suggest",
                }
            ]
        }
        result = find_title_match(mock, "/x.zim", "Darwin's evolution", min_score=0.95)
        assert result is not None
        # Score gate still passes — match_type is informational here.
        # The caller filters on match_type.
        assert result["match_type"] == "fuzzy_suggest"


class TestFuzzySuggestGateReject:
    """``_promote_topic_via_title_index`` pass-0 must REJECT results
    whose ``match_type == "fuzzy_suggest"``. The 0.95 suggestion-rank
    score covers both safe (canonical redirect) and unsafe (incidental
    fuzzy title-prefix) cases; only the former is suitable for
    auto-fetch."""

    def _make_handler(self) -> Any:
        class _StubOps:
            pass

        class _Handler:
            zim_operations = _StubOps()

        return _Handler()

    def test_pass_0_rejects_fuzzy_suggest(self) -> None:
        """Live repro: ``darwin's evolution`` → ``Evolution`` at score
        0.95 via fuzzy_suggest. Pass-0 must reject; tail iteration
        then takes over and finds nothing → returns None → caller
        falls back to BM25 → user sees the search response instead of
        the wrong article."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        def fake(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            # Full topic: hits Evolution via fuzzy_suggest at 0.95.
            # In production the suggestion-rank cap is 0.95, so this
            # row is only visible when ``min_score <= 0.95``.
            if topic == "darwin's evolution" and min_score <= 0.95:
                return {
                    "path": "Evolution",
                    "title": "Evolution",
                    "zim_file": "test.zim",
                    "match_type": "fuzzy_suggest",
                }
            # Tail "evolution": hits Evolution as a direct title match
            # at strict 1.0. With the possessive min_len=2 floor, this
            # 1-token tail is never probed, so no spurious match.
            if topic == "evolution":
                return {
                    "path": "Evolution",
                    "title": "Evolution",
                    "zim_file": "test.zim",
                    "match_type": "direct",
                }
            return None

        with patch("openzim_mcp.simple_tools.find_title_match", side_effect=fake):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                self._make_handler(),
                "test.zim",
                "darwin's evolution",
            )
        # The fuzzy_suggest rejection + possessive min_len=2 floor
        # together mean no promoted result.
        assert result is None, (
            f"expected None (fuzzy_suggest rejected + min_len=2 floor), "
            f"got {result!r}"
        )

    def test_pass_0_accepts_redirect(self) -> None:
        """Live repro: ``plato's cave`` → ``Allegory_of_the_cave`` at
        score 0.95 via a redirect walk (Plato's_cave redirect entry →
        canonical target). match_type="redirect" is accepted."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        def fake(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            if topic == "plato's cave":
                return {
                    "path": "Allegory_of_the_cave",
                    "title": "Allegory of the cave",
                    "zim_file": "test.zim",
                    "match_type": "redirect",
                }
            return None

        with patch("openzim_mcp.simple_tools.find_title_match", side_effect=fake):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                self._make_handler(),
                "test.zim",
                "plato's cave",
            )
        assert result is not None
        assert result["path"] == "Allegory_of_the_cave"

    def test_pass_0_accepts_fuzzy_suggest_on_non_possessive_topic(self) -> None:
        """Pass-3 audit refinement: the ``fuzzy_suggest`` filter ONLY
        applies when the topic carries an apostrophe-possessive. For
        non-possessive prose queries (``Berlin Germany`` → ``Berlin``
        at 0.95 via libzim's tokenized-prefix match), the fuzzy_suggest
        IS the intended answer — libzim correctly resolved the first
        token to the canonical, with the second as disambiguator. The
        b4 pass-0 specifically improved this class over the pre-b4
        pass-1 behavior (which would have picked the trailing tail
        ``germany`` at strict 1.0 → returned the Germany article
        instead of the Berlin one the user asked about). An
        unconditional filter would silently revert that improvement;
        the refined gate preserves it."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        def fake(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            # Non-possessive 2-token prose: libzim returns ``Berlin``
            # as fuzzy_suggest at 0.95. No possessive marker in the
            # topic, so the filter does NOT reject.
            if topic.lower() == "berlin germany" and min_score <= 0.95:
                return {
                    "path": "Berlin",
                    "title": "Berlin",
                    "zim_file": "test.zim",
                    "match_type": "fuzzy_suggest",
                }
            # Tail ``germany`` would resolve at strict 1.0 if pass-0
            # missed — pre-b4 behavior was to return Germany. The
            # refined fix must keep Berlin (pass-0 wins) for this
            # non-possessive shape.
            if topic == "germany":
                return {
                    "path": "Germany",
                    "title": "Germany",
                    "zim_file": "test.zim",
                    "match_type": "direct",
                }
            return None

        with patch("openzim_mcp.simple_tools.find_title_match", side_effect=fake):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                self._make_handler(),
                "test.zim",
                "Berlin Germany",
            )
        # Non-possessive: pass-0 accepts fuzzy_suggest Berlin → user
        # gets the article they asked about.
        assert result is not None
        assert result["path"] == "Berlin", (
            f"non-possessive fuzzy_suggest must be accepted (b4 "
            f"behavior preserved); got {result!r}"
        )

    def test_pass_0_accepts_missing_match_type_backwards_compat(self) -> None:
        """Pre-D1 callers / older mock fixtures don't set match_type.
        Pass-0 must still accept them so the b3 tests keep passing."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        def fake(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            if topic == "einstein's theory":
                # No match_type field — older mock shape.
                return {
                    "path": "Theory_of_relativity",
                    "title": "Theory of relativity",
                    "zim_file": "test.zim",
                }
            return None

        with patch("openzim_mcp.simple_tools.find_title_match", side_effect=fake):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                self._make_handler(),
                "test.zim",
                "einstein's theory",
            )
        assert result is not None
        assert result["path"] == "Theory_of_relativity"


class TestPossessiveTokenizer:
    """``_TAIL_TOKEN_RE`` must preserve apostrophes inside otherwise-
    alphanumeric runs so ``einstein's`` stays a single token. Both
    straight (``'``) and curly (``’``) apostrophes are recognised
    (Wikipedia uses both)."""

    def test_iter_query_tails_keeps_straight_apostrophe(self) -> None:
        from openzim_mcp.title_promotion import iter_query_tails

        tails = list(iter_query_tails("einstein's theory"))
        # Must NOT contain an "s" stub token.
        assert "s theory" not in tails
        assert "einstein s theory" not in tails
        # Must contain the apostrophe-preserved tails.
        assert "einstein's theory" in tails
        # 1-token tails: only "theory", NOT "s".
        assert "theory" in tails
        assert "s" not in tails

    def test_iter_query_tails_keeps_curly_apostrophe(self) -> None:
        from openzim_mcp.title_promotion import iter_query_tails

        tails = list(iter_query_tails("einstein’s theory"))
        # Curly apostrophe also preserved inside the token.
        assert "einstein’s theory" in tails or "einstein's theory" in tails
        # No stub "s" token.
        assert "s" not in tails

    def test_iter_query_windows_keeps_apostrophe(self) -> None:
        from openzim_mcp.title_promotion import iter_query_windows

        windows = list(iter_query_windows("einstein's theory of gravity"))
        # No stub "s" token in any window.
        assert "s" not in windows
        # The apostrophe-preserved possessor token appears as a
        # standalone window.
        assert "einstein's" in windows or "einstein’s" in windows

    def test_non_possessive_query_unchanged(self) -> None:
        """The original 'famous people from big rapids michigan' tail
        iteration motivating ``_promote_topic_via_title_index`` must
        still work — no apostrophes, no behavior change."""
        from openzim_mcp.title_promotion import iter_query_tails

        tails = list(iter_query_tails("famous people from big rapids michigan"))
        # Greedy length-down: longest tail (capped at max_len=4) first.
        assert (
            tails[0] == "people from big rapids"
            or tails[0] == "from big rapids michigan"
        )
        # The motivating "big rapids michigan" tail must appear.
        assert "big rapids michigan" in tails
        # The 1-token "michigan" tail is also yielded by default.
        assert "michigan" in tails


class TestPossessiveMinLenFloor:
    """When the topic carries an apostrophe-possessive, pass-1 of
    ``_promote_topic_via_title_index`` must iterate tails at
    ``min_len=2`` so a generic 1-token tail (philosophy, history,
    tourism) can't silently win after pass-0 missed."""

    def _make_handler(self) -> Any:
        class _StubOps:
            pass

        class _Handler:
            zim_operations = _StubOps()

        return _Handler()

    def test_possessive_prose_no_1_token_pass_1_match(self) -> None:
        """Live repro: ``plato's republic philosophy`` (prose with
        possessive, full topic NOT canonical). With the min_len=2
        floor, pass-1 doesn't probe the 1-token tail ``philosophy``,
        so the wrong promotion can't happen."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        def fake(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            # Full topic: no canonical match.
            if topic == "plato's republic philosophy":
                return None
            # 2-tail "republic philosophy": no canonical match.
            if topic == "republic philosophy":
                return None
            # 1-tail "philosophy": IF probed, would return Philosophy
            # at strict 1.0. The test asserts this is NEVER called.
            if topic == "philosophy":
                return {
                    "path": "Philosophy",
                    "title": "Philosophy",
                    "zim_file": "test.zim",
                    "match_type": "direct",
                }
            return None

        with patch("openzim_mcp.simple_tools.find_title_match", side_effect=fake):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                self._make_handler(),
                "test.zim",
                "plato's republic philosophy",
            )
        # With the min_len=2 floor, the 1-token "philosophy" tail is
        # not probed, so no spurious Philosophy promotion. Pass-0
        # missed too, so we get None and the caller falls back to
        # BM25 (where the user can see "no canonical, multiple
        # weak matches" instead of a confident wrong answer).
        assert result is None, (
            f"expected None (min_len=2 floor blocks 1-token tail), " f"got {result!r}"
        )

    def test_possessive_prose_2_token_tail_still_probed(self) -> None:
        """The floor is min_len=2, not min_len=3. A 2-token tail that
        IS canonical should still resolve (legitimate entity
        resolution)."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        def fake(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            # Full topic: no canonical match.
            if topic == "newton's theory of motion":
                return None
            # Possessive-preserved tail iteration:
            # 4-tail: "newton's theory of motion" (= full topic above)
            # 3-tail: "theory of motion"
            # 2-tail: "of motion"
            # (1-tail "motion" not probed under min_len=2 floor)
            if topic == "theory of motion":
                return {
                    "path": "Motion_(physics)",
                    "title": "Motion (physics)",
                    "zim_file": "test.zim",
                    "match_type": "direct",
                }
            return None

        with patch("openzim_mcp.simple_tools.find_title_match", side_effect=fake):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                self._make_handler(),
                "test.zim",
                "newton's theory of motion",
            )
        # 3-token tail "theory of motion" hits strict 1.0 → returned.
        assert result is not None
        assert result["path"] == "Motion_(physics)"

    def test_non_possessive_prose_still_uses_1_token_floor(self) -> None:
        """The min_len=2 floor is conditional on the topic carrying an
        apostrophe-possessive. For pure prose without a possessive,
        the original min_len=1 behavior is preserved so the motivating
        "famous people from big rapids michigan" → "michigan" 1-token
        tail still works as a last resort."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        def fake(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            # No canonical match anywhere except the trailing 1-token
            # tail.
            if topic == "michigan":
                return {
                    "path": "Michigan",
                    "title": "Michigan",
                    "zim_file": "test.zim",
                    "match_type": "direct",
                }
            return None

        with patch("openzim_mcp.simple_tools.find_title_match", side_effect=fake):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                self._make_handler(),
                "test.zim",
                # No apostrophe — original min_len=1 applies.
                "people who live in michigan",
            )
        # No possessive → min_len=1 → 1-token "michigan" tail probed
        # → strict 1.0 hit → returned.
        assert result is not None
        assert result["path"] == "Michigan"


class TestSynthesizePromoteFullTopicProbe:
    """``_promote_title_match`` in ``synthesize.py`` was not patched by
    PR #169. The same b4 pass-0 full-query probe must run at the start
    here too, so possessive queries through the synthesize path
    resolve to the canonical redirect target instead of the buggy
    pass-1 tail-iteration winner."""

    def test_synthesize_pass_0_full_query_probe(self) -> None:
        """Live repro: ``Einstein's theory`` with ``synthesize=true``
        currently returns rank-1 ``Theory``. The new pass-0 should
        intercept and promote ``Theory_of_relativity`` to rank 1.

        Also pins the API-contract invariant: ``find_title_match``
        receives ``search_handler`` (a ZimOperations-shaped object —
        wired in production at ``simple_tools._handle_synthesize_query``
        via ``search_handler=self.zim_operations``) and the validated
        path string. Pre-pass-2 audit, this site passed the libzim
        ``Archive`` handle instead, which silently no-ops because
        ``Archive`` has no ``find_entry_by_title_data`` method."""
        from openzim_mcp.synthesize import _promote_title_match

        # Search handler stub with a title_match_hit that uses the
        # full query when probed for the canonical, but would also
        # return ``Theory`` for the bare 1-token tail (which the new
        # pass-0 probe should make irrelevant).
        class _Archive:
            pass

        archive_obj = _Archive()
        archives_searched = ["wiki"]

        def fake_title_match_hit(archive: Any, query: str) -> Optional[Dict[str, Any]]:
            # Old pass-1 path: returns "Theory" for the "theory" tail.
            if query == "theory":
                return {
                    "path": "Theory",
                    "title": "Theory",
                    "match_type": "direct",
                }
            return None

        # Mock find_title_match (the new pass-0 probe) so the full
        # query "einstein's theory" resolves to the canonical redirect
        # target at 0.95. ``find_entry_by_title_data`` is
        # case-insensitive internally (``title_lower = title.lower()``
        # at zim/search.py:2738) so the mock lowercases the input
        # before comparing. Records calls so the test can assert the
        # API-contract: arg-0 is the search_handler, arg-1 is the
        # validated path.
        call_log: List[tuple[Any, str, str]] = []

        def fake_find_title_match(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            call_log.append((zim_ops, zim_file_path, topic))
            if topic.lower() == "einstein's theory":
                return {
                    "path": "Theory_of_relativity",
                    "title": "Theory of relativity",
                    "zim_file": "wiki",
                    "match_type": "redirect",
                    # Post-b6 Z1: the synthesize filter rejects
                    # redirects whose pre-resolution path doesn't
                    # share a possessor token with the query. The
                    # live ``Einstein's_theory`` redirect entry
                    # carries the possessor ``einstein`` → ACCEPT.
                    "pre_redirect_path": "Einstein's_theory",
                }
            return None

        handler = MagicMock()
        handler.title_match_hit = fake_title_match_hit

        with patch(
            "openzim_mcp.synthesize.find_title_match",
            side_effect=fake_find_title_match,
        ):
            promoted_hits = _promote_title_match(
                # Top hit is the wrong "Theory" article (pre-fix
                # behavior); we want the pass-0 probe to override.
                [("wiki", {"path": "Theory", "title": "Theory"})],
                query="Einstein's theory",
                archives=[(archive_obj, "/wiki.zim")],
                archives_searched=archives_searched,
                search_handler=handler,
            )
        # Pass-0 promoted Theory_of_relativity to rank 1.
        assert len(promoted_hits) >= 1
        top_path = promoted_hits[0][1]["path"]
        assert (
            top_path == "Theory_of_relativity"
        ), f"expected Theory_of_relativity at rank 1, got {top_path!r}"
        # API contract: pass-0 must call find_title_match with the
        # search_handler (zim_operations) and the validated PATH from
        # the archives tuple, NOT the libzim ``Archive`` object and
        # NOT the archive_name label.
        assert call_log, "pass-0 probe never called find_title_match"
        first_zim_ops, first_path, first_topic = call_log[0]
        assert first_zim_ops is handler, (
            f"arg-0 must be the search_handler (zim_operations); "
            f"got {first_zim_ops!r}"
        )
        assert first_path == "/wiki.zim", (
            f"arg-1 must be the validated path from archives[..][1]; "
            f"got {first_path!r}"
        )
        assert first_topic == "Einstein's theory"

    def test_synthesize_pass_0_accepts_fuzzy_suggest_on_non_possessive(
        self,
    ) -> None:
        """Synthesize mirror of the simple-mode non-possessive carve-
        out: ``Berlin Germany`` through ``synthesize=true`` must still
        let pass-0 accept the ``Berlin`` fuzzy_suggest hit so it's
        promoted to rank 1, matching the b4 improvement that the
        unconditional filter would have reverted."""
        from openzim_mcp.synthesize import _promote_title_match

        class _Archive:
            pass

        archive_obj = _Archive()

        def fake_find_title_match(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            if topic.lower() == "berlin germany" and min_score <= 0.95:
                return {
                    "path": "Berlin",
                    "title": "Berlin",
                    "zim_file": "wiki",
                    "match_type": "fuzzy_suggest",
                }
            return None

        handler = MagicMock()
        handler.title_match_hit = lambda _a, _q: None

        with patch(
            "openzim_mcp.synthesize.find_title_match",
            side_effect=fake_find_title_match,
        ):
            result_hits = _promote_title_match(
                # Empty top_hits: pass-0 is the only path that can
                # contribute. Without the carve-out the result would
                # be the same empty list (silent regression vs b4).
                [],
                query="Berlin Germany",
                archives=[(archive_obj, "/wiki.zim")],
                archives_searched=["wiki"],
                search_handler=handler,
            )
        # Non-possessive: pass-0 promotes Berlin to rank 1.
        assert len(result_hits) == 1
        top_archive, top_hit = result_hits[0]
        assert top_archive == "wiki"
        assert top_hit["path"] == "Berlin"

    def test_synthesize_pass_0_rejects_fuzzy_suggest(self) -> None:
        """The synthesize-side pass-0 must also apply the D1 match_type
        filter so ``Einstein's xyz`` (fuzzy false-positive at 0.95)
        doesn't get auto-promoted."""
        from openzim_mcp.synthesize import _promote_title_match

        class _Archive:
            pass

        archive_obj = _Archive()

        def fake_find_title_match(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            if topic.lower() == "einstein's xyz":
                return {
                    "path": "Xyz",
                    "title": "Xyz",
                    "zim_file": "wiki",
                    "match_type": "fuzzy_suggest",
                }
            return None

        handler = MagicMock()
        handler.title_match_hit = lambda _a, _q: None

        existing_hits: List[tuple[str, Dict[str, Any]]] = [
            ("wiki", {"path": "Albert_Einstein", "title": "Albert Einstein"})
        ]
        with patch(
            "openzim_mcp.synthesize.find_title_match",
            side_effect=fake_find_title_match,
        ):
            result_hits = _promote_title_match(
                existing_hits,
                query="Einstein's xyz",
                archives=[(archive_obj, "/wiki.zim")],
                archives_searched=["wiki"],
                search_handler=handler,
            )
        # Pass-0 rejected fuzzy_suggest; existing hits preserved
        # untouched (no spurious Xyz promotion).
        assert result_hits == existing_hits


class TestRegressionGuards:
    """Pin the post-b4 invariants so future contributors don't
    regress them."""

    def test_tail_token_re_accepts_apostrophe_in_token(self) -> None:
        """Direct check on the tokenizer regex — the load-bearing
        invariant for D2/D3/D5."""
        from openzim_mcp.title_promotion import _TAIL_TOKEN_RE

        tokens = _TAIL_TOKEN_RE.findall("einstein's theory")
        assert tokens == ["einstein's", "theory"], (
            f"_TAIL_TOKEN_RE must keep apostrophes inside tokens; " f"got {tokens!r}"
        )
        # Curly apostrophe variant.
        tokens_curly = _TAIL_TOKEN_RE.findall("einstein’s theory")
        assert tokens_curly == ["einstein’s", "theory"], (
            f"_TAIL_TOKEN_RE must keep curly apostrophes inside tokens; "
            f"got {tokens_curly!r}"
        )

    def test_promote_function_has_pass_0_match_type_filter(self) -> None:
        """Structural pin: ``_promote_topic_via_title_index`` must
        check ``match_type`` against ``"fuzzy_suggest"`` before
        accepting the pass-0 result. Post-b6 Z1: the check moved into
        the shared ``title_promotion.accept_possessive_promotion``
        helper (single source of truth for both simple_tools and
        synthesize); this guard now greps the shared helper's source
        instead of the method body. If a refactor removes this check,
        the b4 D1 regression returns."""
        import inspect

        from openzim_mcp import title_promotion

        source = inspect.getsource(title_promotion.accept_possessive_promotion)
        assert '"fuzzy_suggest"' in source or "'fuzzy_suggest'" in source, (
            "_promote_topic_via_title_index must filter fuzzy_suggest " "at pass-0"
        )

    def test_synthesize_promote_starts_with_full_query_probe(self) -> None:
        """Structural pin: ``_promote_title_match`` must call
        ``find_title_match`` with the bare query BEFORE iterating
        tails."""
        import inspect

        from openzim_mcp.synthesize import _promote_title_match

        source = inspect.getsource(_promote_title_match)
        first_find_call = source.find("find_title_match(")
        first_iter_call = source.find("iter_query_tails(")
        assert first_find_call > 0, "find_title_match call missing"
        assert first_iter_call > 0, "iter_query_tails call missing"
        assert first_find_call < first_iter_call, (
            "_promote_title_match must probe full query via "
            "find_title_match BEFORE iter_query_tails decomposes it"
        )

    def test_synthesize_promote_passes_search_handler_to_find_title_match(
        self,
    ) -> None:
        """Pass-2 audit pin: ``_promote_title_match``'s call to
        ``find_title_match`` must pass ``search_handler`` (a
        ZimOperations-shaped object) as arg-0, NOT the libzim
        ``Archive`` handle. ``find_title_match`` calls
        ``zim_operations.find_entry_by_title_data(...)`` on arg-0 —
        if arg-0 is an ``Archive`` (which has no such method) the
        probe silently no-ops via the ``except Exception``. This
        guard regex-locates the first ``find_title_match(`` invocation
        inside ``_promote_title_match`` and verifies its first
        positional argument names ``search_handler``."""
        import inspect
        import re as _re

        from openzim_mcp.synthesize import _promote_title_match

        source = inspect.getsource(_promote_title_match)
        # Match the first multi-line call: ``find_title_match(`` then
        # the next non-whitespace token is the first positional arg.
        match = _re.search(
            r"find_title_match\(\s*([A-Za-z_][A-Za-z_0-9]*)",
            source,
        )
        assert match is not None, "find_title_match call missing"
        first_arg_name = match.group(1)
        assert first_arg_name == "search_handler", (
            f"first arg to find_title_match must be ``search_handler`` "
            f"(the ZimOperations-shaped object); got {first_arg_name!r}. "
            f"Passing the libzim ``Archive`` here silently no-ops the "
            f"probe — see post-b4 pass-2 audit finding A1."
        )
