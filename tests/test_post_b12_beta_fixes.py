r"""Regression tests for the post-b12 beta-test sweep.

Post-b12 live-MCP verification surfaced one new defect not caught by
the b11 ``_DISAMBIG_LEAD_PHRASES`` set — the Wikipedia ``Play``-style
disambig page uses the phrase ``may refer also to`` (word order:
may-refer-**also**-to) instead of ``may also refer to`` (word order:
may-**also**-refer-to).

## Live repro at v2.0.0b12

``tell me about Shakespeare England plays`` at v2.0.0b12 ships
``Play`` (disambig) at cert=0.85 — a Sub-pattern C leak that should
have been caught by the b12 disambig-render-time rejection. Path
through the gate:

  1. Z4 layer correctly rejects ``Shakespeare's_Kings`` at Pass 0.
  2. Pass 1 tail-iter probes ``"plays"`` → libzim returns ``Play``
     (the disambig page, direct match).
  3. Z4 check on ``Play``: canonical is single-token → not tangential
     → ``_passes_z4`` returns True.
  4. ``_handle_tell_me_about`` fetches the ``Play`` body.
  5. ``_is_disambig_lead(pre_h2_in_body)`` runs the trailing-tail
     ``endswith`` check against ``_DISAMBIG_LEAD_PHRASES``. The
     normalized pre-H2 tail is ``may refer also to`` — NOT in the
     phrase set ``("may refer to", "may also refer to")`` — so the
     check returns False and the b12 Sub-pattern C rejection does
     NOT fire.
  6. The Play disambig page is served as the tell_me_about answer.

The fix is a one-line tuple extension: add ``"may refer also to"`` to
``_DISAMBIG_LEAD_PHRASES``. The existing comment at
``simple_tools.py:2660`` explicitly anticipates this: "easier to
extend with new phrasings if ZIM exporters ever produce them".

## Counter-cases the fix preserves

- ``may refer to`` — original phrase (Martin-style) — still matches.
- ``may also refer to`` — b11 added (Lincoln-style) — still matches.
- ``may refer also to`` — b12 fix adds (Play-style) — NOW matches.
- Random body containing ``refer`` earlier but ending differently —
  still doesn't false-positive (trailing-tail endswith check is
  position-anchored).
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Direct unit tests on the extended _DISAMBIG_LEAD_PHRASES set.
# ---------------------------------------------------------------------------


class TestIsDisambigLeadPhrasingVariants:
    """The b12 disambig-render-time rejection depends on
    ``_is_disambig_lead`` detecting the Wikipedia disambig template's
    pre-H2 trailing phrase. The post-b12 sweep extends the phrase set
    to cover the ``may refer also to`` variant used by the ``Play``-
    style disambig pages."""

    def test_may_refer_to_detected(self) -> None:
        """Original Martin-style phrasing — preserved."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        assert SimpleToolsHandler._is_disambig_lead("**Martin** may refer to:")

    def test_may_also_refer_to_detected(self) -> None:
        """b11 Mercury-style phrasing (may-also-refer-to) — preserved."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        assert SimpleToolsHandler._is_disambig_lead("**Mercury** may also refer to:")

    def test_may_refer_also_to_detected(self) -> None:
        """b12 fix: Play-style phrasing (may-refer-also-to) — NEW."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        assert SimpleToolsHandler._is_disambig_lead("**Play** may refer also to:")

    def test_play_style_full_pre_h2_detected(self) -> None:
        """End-to-end: full Play-style pre-H2 body (Wiktionary look-up
        + most-commonly-refers preamble + may-refer-also-to tail) is
        correctly classified as disambig."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        play_pre_h2 = (
            "Look up _**play**_ or _**plays**_ in Wiktionary, the free "
            "dictionary.\n\n"
            "**Play** most commonly refers to: \n\n"
            "  * Play (activity), an activity done for enjoyment\n"
            "  * Play (theatre), a work of drama\n\n"
            "**Play** may refer also to:"
        )
        assert SimpleToolsHandler._is_disambig_lead(play_pre_h2)

    def test_non_disambig_with_refer_earlier_not_false_positive(self) -> None:
        """Defense: a body that mentions ``refer also to`` earlier but
        ends differently shouldn't trigger. The trailing-tail
        ``endswith`` check is position-anchored."""
        from openzim_mcp.simple_tools import SimpleToolsHandler

        body = (
            "Some article body that includes the phrase may refer also to "
            "somewhere in the middle of a sentence. " * 10
            + "But it ends with descriptive prose about its subject."
        )
        assert not SimpleToolsHandler._is_disambig_lead(body)


# ---------------------------------------------------------------------------
# Integration test: Shakespeare England plays → Play disambig leak.
# Mirrors the b11 TestSubPatternCDisambigRejection test pattern but
# uses the Play-style ``may refer also to`` phrasing.
# ---------------------------------------------------------------------------


_PLAY_DISAMBIG_PRE_H2 = (
    "Look up _**play**_ or _**plays**_ in Wiktionary, the free dictionary.\n\n"
    "**Play** most commonly refers to: \n\n"
    "  * Play (activity), an activity done for enjoyment\n"
    "  * Play (theatre), a work of drama\n\n"
    "**Play** may refer also to:"
)


class TestPlayDisambigRejection:
    """Integration test for the Play-style disambig rejection path.
    Without the b12 fix, ``Shakespeare England plays`` → ``Play``
    disambig leaks through because ``_is_disambig_lead`` misses the
    ``may refer also to`` phrasing. With the fix, the body is
    classified as disambig and the Sub-pattern C rejection fires."""

    @staticmethod
    def _make_handler(
        *,
        article_body: str,
        search_results: list,
        title_index: Optional[Dict[str, Any]] = None,
    ) -> Any:
        from openzim_mcp.simple_tools import SimpleToolsHandler

        mock = MagicMock()
        mock.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        mock.search_zim_file_data.return_value = {"results": search_results}
        mock.search_zim_file.return_value = "## BM25 fallback rendered\n\n..."
        mock.get_zim_entry.return_value = article_body
        mock.config.meta.footer_enabled = False
        mock.find_entry_by_title_data.return_value = (
            {"results": [title_index]} if title_index else {"results": []}
        )
        mock.get_article_structure_data.return_value = {"sections": []}
        return SimpleToolsHandler(mock), mock

    def test_play_style_disambig_multi_token_falls_to_search(self) -> None:
        """Topic with 3 content tokens + Play-style disambig body →
        b12 Sub-pattern C rejection must fire → BM25 fallback."""
        disambig_body = (
            f"# Play\n\n{_PLAY_DISAMBIG_PRE_H2}\n\n"
            "## Computers and technology\n  * Play (something)\n"
        )
        handler, mock = self._make_handler(
            article_body=disambig_body,
            search_results=[
                {"path": "Play", "title": "Play", "score": 100},
            ],
            title_index={"path": "Play", "title": "Play", "score": 1.0},
        )
        out = handler.handle_zim_query(
            "tell me about Shakespeare England plays",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        # b12 Sub-pattern C must reject the disambig auto-fetch.
        assert "## BM25 fallback rendered" in out
        mock.search_zim_file.assert_called()

    def test_play_style_disambig_bare_head_preserved(self) -> None:
        """``tell me about Play`` (1 content token) legitimately wants
        the disambig — don't override."""
        disambig_body = (
            f"# Play\n\n{_PLAY_DISAMBIG_PRE_H2}\n\n"
            "## Computers and technology\n  * Play (something)\n"
        )
        handler, mock = self._make_handler(
            article_body=disambig_body,
            search_results=[
                {"path": "Play", "title": "Play", "score": 100},
            ],
            title_index={"path": "Play", "title": "Play", "score": 1.0},
        )
        out = handler.handle_zim_query(
            "tell me about Play",
            zim_file_path="/x.zim",
            options={"compact": False},
        )
        # Bare-head 1-content-token topic: serve the disambig as
        # the answer.
        assert "_Source: `Play`_" in out
        mock.search_zim_file.assert_not_called()
