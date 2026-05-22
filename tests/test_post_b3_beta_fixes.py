r"""Regression tests for the post-b3 beta-test sweep.

The post-b3 live-MCP probe pass against v2.0.0b3 confirmed all six
post-b2 fix families land cleanly on live (D1-D4 + the pass-2/pass-3
siblings). Deeper probing of the ``tell me about X's Y`` shape — the
attack surface b2 D3 partially closed — surfaced a pre-existing
silent-wrong-answer in the auto-fetch flow that b3 didn't reach.

## Defect — ``X's Y`` auto-fetch silent-wrong-answer

``_promote_topic_via_title_index`` (simple_tools.py:3868) iterates
trailing tails via ``iter_query_tails`` (title_promotion.py:191).
``iter_query_tails`` tokenizes on alphanumeric runs, so the
apostrophe in ``X's Y`` is treated as a separator: the topic
``"einstein's theory"`` becomes the tokens
``["einstein", "s", "theory"]``. Tails yielded longest-first:

- ``"einstein s theory"`` — no canonical match (the canonical
  is stored WITH the apostrophe — ``Einstein's_theory`` is a
  redirect to ``Theory_of_relativity``)
- ``"s theory"`` — no canonical match
- ``"theory"`` — matches the generic ``Theory`` article at score
  1.0 → wins → wrong article fetched

Live impact (post-b3):
- ``tell me about Einstein's theory`` → ``Theory`` (expected
  ``Theory_of_relativity`` — confirmed canonical at 1.00 via
  ``find article titled einstein's theory``)
- ``tell me about Plato's cave`` → ``Cave`` (expected
  ``Allegory_of_the_cave`` — confirmed at 1.00)
- ``tell me about Plato's Republic`` → ``Republic`` (expected
  ``Republic_(Plato)`` — confirmed at 0.95)
- ``tell me about Darwin's evolution`` → ``Evolution``

The bug is pre-existing — it would have affected any user typing
``tell me about X's Y`` for years — but surfaced via the post-b3
sweep's deeper probing of possessive shapes. The b2 D3 retry
correctly suppresses decomposition for these cases (the title-probe
gate fires True because the redirect chain is canonical), but the
downstream auto-fetch flow's tail iteration then picks the wrong
tail.

## Fix

In ``_promote_topic_via_title_index``, probe the FULL topic (with
original punctuation preserved) BEFORE entering the tail iteration.
``find_title_match`` uses libzim's title index directly — it
correctly handles apostrophes and redirects. ``min_score=0.95``
mirrors the canonical-or-fuzzy gate that Rule 2/3/4's probe uses
(intent_parser.py:317), accepting both direct hits (1.0) and
high-confidence redirects (0.95).

Non-possessive queries hit this new probe with the same behavior
they would get from pass-1's longest tail — the new call returns
redundantly on those, never less correct.

"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import patch


class TestPossessiveAutofetchProbe:
    """Pin the post-b3 fix: ``_promote_topic_via_title_index`` probes
    the full topic with original punctuation BEFORE iter_query_tails
    decomposes it.

    The fix lives in ``simple_tools._promote_topic_via_title_index``;
    the test patches ``find_title_match`` at the import site to
    isolate behavior."""

    def _make_handler_with_mock_promote(self) -> Any:
        """Build a minimal stub carrying the method we test under.
        The method is called unbound so we can pass any duck-typed
        object as ``self``."""

        class _StubOps:
            pass

        class _Handler:
            zim_operations = _StubOps()

        return _Handler()

    def test_full_topic_probe_runs_before_tail_iteration(self) -> None:
        """Live repro shape: ``einstein's theory`` should resolve
        through the new full-topic probe to ``Theory_of_relativity``
        (the canonical redirect target), NOT through tail iteration
        which would pick ``Theory`` (the shortest tail)."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        handler = self._make_handler_with_mock_promote()

        # The mock returns the canonical redirect target for the
        # full topic (apostrophe preserved); returns ``Theory`` for
        # any bare ``"theory"`` tail. If the fix is correct, the
        # full-topic probe wins and ``Theory`` (the wrong tail)
        # never gets called.
        def fake_find_title_match(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            if topic == "einstein's theory":
                return {
                    "path": "Theory_of_relativity",
                    "title": "Theory of relativity",
                    "zim_file": "test.zim",
                }
            return None

        with patch(
            "openzim_mcp.simple_tools.find_title_match",
            side_effect=fake_find_title_match,
        ):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                handler,  # type: ignore[arg-type]
                "test.zim",
                "einstein's theory",
            )
        assert result is not None
        assert result["path"] == "Theory_of_relativity"

    def test_full_topic_probe_uses_min_score_095(self) -> None:
        """The full-topic probe must use ``min_score=0.95`` so it
        catches both direct hits (1.0) and high-confidence redirects
        (0.95). Live repro: ``Plato's Republic`` resolves to
        ``Republic_(Plato)`` at score 0.95 via the title index.

        Verify by inspection: ``min_score=0.95`` appears in the new
        call inside ``_promote_topic_via_title_index``."""
        import inspect

        from openzim_mcp.simple_tools import SimpleToolsHandler

        source = inspect.getsource(SimpleToolsHandler._promote_topic_via_title_index)
        # The new call must explicitly pass min_score=0.95.
        assert "min_score=0.95" in source, (
            "post-b3 full-topic probe must use min_score=0.95 to match "
            "the canonical-or-fuzzy gate (Rule 2/3/4 convention)"
        )

    def test_full_topic_probe_runs_before_pass_1(self) -> None:
        """Structural guard: the full-topic ``find_title_match`` call
        must appear BEFORE the ``for tail in iter_query_tails`` loop
        in the source. Future contributors who reorder this would
        silently re-break the apostrophe-tokenization fix."""
        import inspect

        from openzim_mcp.simple_tools import SimpleToolsHandler

        source = inspect.getsource(SimpleToolsHandler._promote_topic_via_title_index)
        # Look for actual code constructs, not mentions in comments.
        # ``min_score=0.95`` is unique to the post-b3 full-topic
        # probe call site. ``for tail in iter_query_tails(`` is the
        # pass-1 loop opener.
        probe_idx = source.find("min_score=0.95")
        loop_idx = source.find("for tail in iter_query_tails(")
        assert probe_idx > 0, "full-topic probe call missing"
        assert loop_idx > 0, "iter_query_tails loop missing"
        assert probe_idx < loop_idx, (
            "full-topic probe must run BEFORE iter_query_tails loop "
            "to preserve apostrophe-bearing canonical matches"
        )

    def test_full_topic_probe_returns_none_falls_through(self) -> None:
        """When the full-topic probe finds no canonical (e.g., prose
        queries like ``famous people from big rapids michigan``), it
        must fall through to the existing tail iteration cleanly."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        handler = self._make_handler_with_mock_promote()
        call_log: List[str] = []

        def fake_find_title_match(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            call_log.append(topic)
            # Only match the tail "big rapids michigan", not the
            # full prose query — simulates the existing tail-iteration
            # behavior.
            if topic == "big rapids michigan":
                return {
                    "path": "Big_Rapids,_Michigan",
                    "title": "Big Rapids, Michigan",
                    "zim_file": "test.zim",
                }
            return None

        with patch(
            "openzim_mcp.simple_tools.find_title_match",
            side_effect=fake_find_title_match,
        ):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                handler,  # type: ignore[arg-type]
                "test.zim",
                "famous people from big rapids michigan",
            )
        assert result is not None
        assert result["path"] == "Big_Rapids,_Michigan"
        # The full topic was probed first (as the new pass-0), but
        # didn't match — tail iteration then ran and found the
        # canonical entity tail.
        assert call_log[0] == "famous people from big rapids michigan"
        assert "big rapids michigan" in call_log

    def test_full_topic_probe_preserves_apostrophe(self) -> None:
        """The fix's whole point: the topic string passed to
        ``find_title_match`` must include the apostrophe so the title
        index can match the canonical entry. iter_query_tails would
        have stripped the apostrophe; the new pass-0 doesn't."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        handler = self._make_handler_with_mock_promote()
        topic_seen: List[str] = []

        def fake_find_title_match(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            topic_seen.append(topic)
            return None  # force fall-through

        with patch(
            "openzim_mcp.simple_tools.find_title_match",
            side_effect=fake_find_title_match,
        ):
            SimpleToolsHandler._promote_topic_via_title_index(
                handler,  # type: ignore[arg-type]
                "test.zim",
                "plato's cave",
            )
        # First call (the new pass-0) sees the apostrophe-preserving
        # form. The subsequent tail-iteration calls don't.
        assert topic_seen[0] == "plato's cave", (
            "full-topic probe must receive the original topic with " "apostrophe intact"
        )
        # Tail iteration calls strip the apostrophe (yielding
        # "plato s cave", "s cave", "cave").
        tail_calls = topic_seen[1:]
        assert any("'" not in t for t in tail_calls), (
            "tail iteration is expected to yield apostrophe-less "
            "tails (sanity check that we're hitting the legacy path)"
        )


class TestPossessivePromoteIntegration:
    """End-to-end-shaped test exercising the failure mode the
    post-b3 sweep observed. Uses a more complete mock of the
    handler chain so we cover the call path from
    ``_promote_topic_via_title_index`` back through the live shape."""

    def test_einsteins_theory_resolves_to_relativity(self) -> None:
        """Live repro: ``einstein's theory`` should resolve through
        the redirect chain to ``Theory_of_relativity``, NOT to the
        generic ``Theory`` article that the tail-iteration would
        pick."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        class _StubOps:
            pass

        class _Handler:
            zim_operations = _StubOps()

        def fake_find_title_match(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            # The title index for "einstein's theory" resolves to
            # Theory_of_relativity at score 1.0 (verified live).
            # The pre-fix tail iteration would have yielded
            # "einstein s theory" / "s theory" / "theory" — only
            # the last matches anything ("Theory" canonical).
            if topic == "einstein's theory":
                return {
                    "path": "Theory_of_relativity",
                    "title": "Theory of relativity",
                    "zim_file": "test.zim",
                }
            if topic == "theory":
                return {
                    "path": "Theory",
                    "title": "Theory",
                    "zim_file": "test.zim",
                }
            return None

        with patch(
            "openzim_mcp.simple_tools.find_title_match",
            side_effect=fake_find_title_match,
        ):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                _Handler(),  # type: ignore[arg-type]
                "test.zim",
                "einstein's theory",
            )
        assert result is not None
        # Critical assertion: ``Theory_of_relativity``, NOT ``Theory``.
        assert result["path"] == "Theory_of_relativity"
        assert result["path"] != "Theory"

    def test_platos_cave_resolves_to_allegory(self) -> None:
        """Live repro: ``plato's cave`` should resolve to
        ``Allegory_of_the_cave`` (1.00), NOT to the generic ``Cave``
        article."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        class _StubOps:
            pass

        class _Handler:
            zim_operations = _StubOps()

        def fake_find_title_match(
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
                }
            if topic == "cave":
                return {
                    "path": "Cave",
                    "title": "Cave",
                    "zim_file": "test.zim",
                }
            return None

        with patch(
            "openzim_mcp.simple_tools.find_title_match",
            side_effect=fake_find_title_match,
        ):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                _Handler(),  # type: ignore[arg-type]
                "test.zim",
                "plato's cave",
            )
        assert result is not None
        assert result["path"] == "Allegory_of_the_cave"
        assert result["path"] != "Cave"

    def test_platos_republic_at_0_95_score_caught(self) -> None:
        """Live repro: ``plato's republic`` resolves to
        ``Republic_(Plato)`` at score 0.95 via the title index. The
        new probe's ``min_score=0.95`` accepts this (Rule 2/3/4
        canonical-or-fuzzy convention).

        Mock the find_title_match to accept only when the requested
        min_score <= 0.95 — exercising the score threshold."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        class _StubOps:
            pass

        class _Handler:
            zim_operations = _StubOps()

        def fake_find_title_match(
            zim_ops: Any,
            zim_file_path: str,
            topic: str,
            *,
            cross_file: bool = False,
            min_score: float = 1.0,
        ) -> Optional[Dict[str, Any]]:
            # Score 0.95 is below the strict 1.0 gate the existing
            # tail iteration uses — only the new pass-0 (which uses
            # min_score=0.95) catches this.
            if topic == "plato's republic" and min_score <= 0.95:
                return {
                    "path": "Republic_(Plato)",
                    "title": "Republic (Plato)",
                    "zim_file": "test.zim",
                }
            # Generic Republic at 1.0 would be caught by tail
            # iteration if the new pass-0 misses.
            if topic == "republic":
                return {
                    "path": "Republic",
                    "title": "Republic",
                    "zim_file": "test.zim",
                }
            return None

        with patch(
            "openzim_mcp.simple_tools.find_title_match",
            side_effect=fake_find_title_match,
        ):
            result = SimpleToolsHandler._promote_topic_via_title_index(
                _Handler(),  # type: ignore[arg-type]
                "test.zim",
                "plato's republic",
            )
        assert result is not None
        # Must catch the 0.95 score on the full topic, not fall
        # through to the strict-1.0 tail-iteration which would pick
        # the generic ``Republic``.
        assert result["path"] == "Republic_(Plato)"


class TestRegressionGuards:
    """Pin the post-b3 invariant: the apostrophe-tokenization bug
    drove this sweep. Future contributors who change
    ``_promote_topic_via_title_index`` should preserve the
    full-topic-with-punctuation probe at the start."""

    def test_promote_function_starts_with_full_topic_probe(self) -> None:
        """The first ``find_title_match`` call inside
        ``_promote_topic_via_title_index`` must pass the bare
        ``topic`` argument (not a tail-iterated form). If a
        future refactor moves tail iteration up, this guard fires."""
        import inspect

        from openzim_mcp.simple_tools import SimpleToolsHandler

        source = inspect.getsource(SimpleToolsHandler._promote_topic_via_title_index)
        # The first occurrence of find_title_match must be passing
        # the bare ``topic`` (not ``tail`` or ``window``).
        first_call_idx = source.find("find_title_match(")
        assert first_call_idx > 0, "find_title_match call missing"
        # Look at the args of the first call.
        # Take the next 200 chars to capture the multi-line call.
        first_call_snippet = source[first_call_idx : first_call_idx + 200]
        # The bare ``topic`` argument should appear before ``tail`` or
        # ``window`` — i.e., the first call uses the full topic.
        assert ", topic," in first_call_snippet or ", topic\n" in first_call_snippet, (
            "first find_title_match call must use the bare ``topic`` "
            "argument (full topic with punctuation), not a tail or "
            "window form"
        )
