"""Backtracking bounds on the content processor's line-shape regexes.

``_LIST_ITEM_RE`` and the leading-H1 matcher behind
``_strip_leading_title_heading`` each let two quantifiers compete for the
same whitespace run. The list pattern (``\\s+(.*\\S)\\s*$``) went quadratic
on a marker followed by spaces; the reluctant H1 pattern
(``#\\s+(.+?)\\s*\\n+``) re-scanned the gap for every candidate heading end
and took minutes on ``# `` followed by a few thousand spaces. These tests
pin the linear rewrites and their equivalence on the fixture shapes the
snippet code sees (MedlinePlus nav menus, suffixed titles, CRLF exports).
"""

from __future__ import annotations

import time
from typing import Callable, Tuple, TypeVar

import pytest

from openzim_mcp.content_processor import (
    _LEADING_H1_RE,
    _LIST_ITEM_RE,
    ContentProcessor,
    _is_nav_list_paragraph,
)

_T = TypeVar("_T")

# Well past the 4096-char front-door cap; the quadratic list pattern needs
# ~5s here and the old H1 pattern does not finish in any useful time.
_PATHOLOGICAL_LEN = 50_000
_BUDGET_S = 1.0


def _timed(fn: Callable[[], _T]) -> Tuple[_T, float]:
    start = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - start


# ---------------------------------------------------------------------------
# _LIST_ITEM_RE
# ---------------------------------------------------------------------------


class TestListItemRegex:
    @pytest.mark.parametrize(
        "line",
        [
            "* " + " " * _PATHOLOGICAL_LEN,
            "1. " + " " * _PATHOLOGICAL_LEN,
            "  - " + " \t" * (_PATHOLOGICAL_LEN // 2),
        ],
        ids=["star", "ordered", "dash-mixed-ws"],
    )
    def test_marker_followed_by_only_whitespace_is_linear(self, line: str) -> None:
        match, elapsed = _timed(lambda: _LIST_ITEM_RE.match(line))
        assert match is None
        assert elapsed < _BUDGET_S, f"list-item match took {elapsed:.3f}s"

    def test_nav_list_check_on_padded_items_is_linear(self) -> None:
        paragraph = "\n".join(["* " + " " * (_PATHOLOGICAL_LEN // 5)] * 5)
        result, elapsed = _timed(lambda: _is_nav_list_paragraph(paragraph))
        assert result is False
        assert elapsed < _BUDGET_S, f"nav-list check took {elapsed:.3f}s"

    @pytest.mark.parametrize(
        ("line", "text"),
        [
            ("  * Summary", "Summary"),
            ("  * Start Here", "Start Here"),
            ("* Diagnosis and Tests   ", "Diagnosis and Tests"),
            ("1. Statistics and Research", "Statistics and Research"),
            ("2) Clinical Trials\t", "Clinical Trials"),
            (
                "- [blood glucose](bloodglucose.html)",
                "[blood glucose](bloodglucose.html)",
            ),
            ("+ x", "x"),
            ("\t* a  b ", "a  b"),
            ("*   Deep, rapid breathing ", "Deep, rapid breathing"),
        ],
    )
    def test_item_text_excludes_outer_whitespace(self, line: str, text: str) -> None:
        match = _LIST_ITEM_RE.match(line)
        assert match is not None
        assert match.group(1) == text

    @pytest.mark.parametrize(
        "line",
        ["*", "* ", "1.", "1.   ", "Summary", "*Summary", "** bold **", "-\t"],
    )
    def test_marker_without_text_is_not_an_item(self, line: str) -> None:
        assert _LIST_ITEM_RE.match(line) is None

    def test_nav_list_fixture_shapes_still_classify(self) -> None:
        # Trimmed from medlineplus.gov/diabetes.html: the "On this page" menu.
        nav = (
            "  * Summary\n  * Start Here\n  * Diagnosis and Tests\n"
            "  * Prevention and Risk Factors\n"
        )
        assert _is_nav_list_paragraph(nav) is True
        # Symptom list from the encyclopedia page: sentence-case content.
        content = (
            "  * Being very thirsty\n  * Feeling hungry\n  * Having blurry eyesight\n"
        )
        assert _is_nav_list_paragraph(content) is False


# ---------------------------------------------------------------------------
# Leading-H1 strip
# ---------------------------------------------------------------------------


class TestLeadingH1Regex:
    @pytest.mark.parametrize(
        "content",
        [
            "# " + " " * _PATHOLOGICAL_LEN,
            "#" + " " * _PATHOLOGICAL_LEN,
            "# abc" + " " * _PATHOLOGICAL_LEN + "x",
            "  \n# Title" + " \t" * (_PATHOLOGICAL_LEN // 2),
        ],
        ids=["spaces", "no-gap", "gap-then-text", "mixed-ws"],
    )
    def test_heading_without_a_line_break_is_linear(self, content: str) -> None:
        match, elapsed = _timed(lambda: _LEADING_H1_RE.match(content))
        assert match is None
        assert elapsed < _BUDGET_S, f"H1 match took {elapsed:.3f}s"

    def test_strip_on_whitespace_only_heading_is_linear(self) -> None:
        content = "# " + " " * _PATHOLOGICAL_LEN + "\nBody."
        stripped, elapsed = _timed(
            lambda: ContentProcessor._strip_leading_title_heading(content, "Title")
        )
        # A heading with no text is not the title; nothing is stripped.
        assert stripped == content
        assert elapsed < _BUDGET_S, f"H1 strip took {elapsed:.3f}s"

    @pytest.mark.parametrize(
        ("content", "heading", "rest"),
        [
            ("#  Diabetes \n\nOn this page", "Diabetes", "On this page"),
            ("# Type 1 diabetes\n\nTo use", "Type 1 diabetes", "To use"),
            ("# Diabetes\r\n\r\nBody", "Diabetes", "Body"),
            ("# Diabetes\n  \n\nBody", "Diabetes", "Body"),
            ("# Diabetes\n## Summary\n\nBody", "Diabetes", "## Summary\n\nBody"),
            ("\n\n# Mercury (planet)\n", "Mercury (planet)", ""),
        ],
        ids=["padded", "plain", "crlf", "blank-run", "no-blank-line", "leading-blanks"],
    )
    def test_heading_text_and_match_end(
        self, content: str, heading: str, rest: str
    ) -> None:
        match = _LEADING_H1_RE.match(content)
        assert match is not None
        assert match.group(1) == heading
        assert content[match.end() :] == rest

    @pytest.mark.parametrize(
        "content",
        ["# Diabetes", "# Diabetes   ", "#\n\nDiabetes", "Diabetes\n\n# Diabetes\n"],
    )
    def test_not_a_leading_closed_heading(self, content: str) -> None:
        assert _LEADING_H1_RE.match(content) is None

    @pytest.mark.parametrize(
        ("content", "title", "expected"),
        [
            # Suffixed site titles: the bare H1 is a prefix up to a separator.
            (
                "#  Diabetes \n\nOn this page\n",
                "Diabetes | Type 1 Diabetes | Type 2 Diabetes | MedlinePlus",
                "On this page\n",
            ),
            (
                "# Type 1 diabetes\n\nTo use the sharing features\n",
                "Type 1 diabetes: MedlinePlus Medical Encyclopedia",
                "To use the sharing features\n",
            ),
            ("# Diabetes\r\n\r\nBody\r\n", "Diabetes - MedlinePlus", "Body\r\n"),
            # Exact title match goes through the escaped-title pattern.
            (
                "# Mercury (planet)\n\nMercury is.\n",
                "Mercury (planet)",
                "Mercury is.\n",
            ),
            # A real subheading under an unrelated title stays.
            ("# Geography\n\nBerlin is.\n", "Berlin", "# Geography\n\nBerlin is.\n"),
            # Prefix with no separator is a different word, not the title.
            ("# Diabet\n\nBody\n", "Diabetes", "# Diabet\n\nBody\n"),
        ],
        ids=["pipe-suffix", "colon-suffix", "crlf", "exact", "subheading", "prefix"],
    )
    def test_strip_leading_title_heading_on_fixture_shapes(
        self, content: str, title: str, expected: str
    ) -> None:
        assert ContentProcessor._strip_leading_title_heading(content, title) == expected
