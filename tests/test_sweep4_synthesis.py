"""Fourth-sweep regression tests for synthesize ranking and bundle headings.

Each class pins one defect; the docstrings name the failure the fix closes.
"""

from __future__ import annotations

import re
import time

from openzim_mcp.bundle import _compute_section_offsets, _loose_escaped_text
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.synthesize import _demote_list_articles, _is_list_article


def _hits(*paths: str) -> list[tuple[str, dict]]:
    return [("wiki", {"path": p}) for p in paths]


def _paths(hits: list[tuple[str, dict]]) -> list[str]:
    return [h["path"] for _archive, h in hits]


# --------------------------------------------------------------------------
# _LIST_ARTICLE_SUFFIX_RE: canonical award articles are narrative topics,
# not enumeration pages, and must not be partitioned to the bottom.
# --------------------------------------------------------------------------


class TestCanonicalAwardArticlesAreNotListArticles:
    def test_award_institution_articles_are_not_list_articles(self) -> None:
        """``Academy_Awards`` & friends are the canonical narrative article
        for the topic; the bare ``_awards``/``_honors`` suffix tokens swept
        them into the list partition."""
        for path in (
            "Academy_Awards",
            "Grammy_Awards",
            "Golden_Globe_Awards",
            "93rd_Academy_Awards",
            "Kennedy_Center_Honors",
            "Military_honors",
            "MTV_Video_Music_Awards",
        ):
            assert _is_list_article({"path": path}) is False, path

    def test_genuine_catalog_suffixes_still_demote(self) -> None:
        for path in (
            "Rephlex_Records_discography",
            "Taylor_Swift_videography",
            "Stanley_Kubrick_filmography",
            "Toni_Morrison_bibliography",
            "Beyoncé_awards_and_nominations",
            "Nelson_Mandela_honours_and_awards",
        ):
            assert _is_list_article({"path": path}) is True, path

    def test_canonical_award_hit_keeps_its_rank(self) -> None:
        """BM25 put ``Academy_Awards`` first for "academy awards ceremony";
        the demotion pushed it behind every unrelated hit."""
        ordered = _demote_list_articles(_hits("Academy_Awards", "Oscar_bait"))
        assert _paths(ordered) == ["Academy_Awards", "Oscar_bait"]

    def test_promoted_hit_is_never_demoted(self) -> None:
        """A title-index promotion is a deliberate ranking decision; the
        list-article heuristic must not undo it."""
        hits = [
            ("wiki", {"path": "List_of_cats", "promoted": True}),
            ("wiki", {"path": "Dog"}),
        ]
        assert _paths(_demote_list_articles(hits)) == ["List_of_cats", "Dog"]


# --------------------------------------------------------------------------
# _is_list_article: the anchored prefix/stem rules ran against the raw
# entry_id, so demotion was dead code on old-scheme (namespaced) archives.
# --------------------------------------------------------------------------


class TestListArticleDetectionOnOldSchemeArchives:
    def test_namespaced_list_articles_are_detected(self) -> None:
        for path in (
            "A/List_of_songs_about_Berlin",
            "A/Lists_of_musicians",
            "A/Outline_of_biology",
            "A/Listed_buildings_in_York",
            "C/Index_of_physics_articles",
        ):
            assert _is_list_article({"path": path}) is True, path

    def test_namespaced_ordinary_articles_are_not_detected(self) -> None:
        for path in ("A/Berlin", "A/Academy_Awards", "C/Cat"):
            assert _is_list_article({"path": path}) is False, path

    def test_namespaced_list_article_is_demoted(self) -> None:
        ordered = _demote_list_articles(
            _hits("A/List_of_songs_about_Berlin", "A/Berlin")
        )
        assert _paths(ordered) == ["A/Berlin", "A/List_of_songs_about_Berlin"]


# --------------------------------------------------------------------------
# bundle relaxed heading matcher: a run of backslashes in a heading made
# the per-character ``\\?`` units ambiguous with the inline-markup class,
# so a heading the relaxed pattern cannot match burned 2**n steps.
# --------------------------------------------------------------------------


class TestBackslashHeadingDoesNotBacktrack:
    @staticmethod
    def _sections(html: str):
        from bs4 import BeautifulSoup

        from openzim_mcp.content_processor import (
            _build_headings,
            select_main_content,
        )

        cp = ContentProcessor()
        soup = BeautifulSoup(html, "html.parser")
        root = select_main_content(soup)
        headings = _build_headings(root)
        rendered = cp._render_soup_to_text(root, compact=True)
        return rendered, _compute_section_offsets(rendered, headings)

    def test_backslash_run_heading_completes_promptly(self) -> None:
        """24 backslashes plus an inline link: the relaxed pattern cannot
        match (the link's brackets are outside its character classes) and
        used to explore 2**24 alternatives before giving up — 3.7s here,
        hours at n=34."""
        html = (
            "<html><body><h1>T</h1><p>intro</p>"
            "<h2>" + ("\\" * 24) + '<a href="/wiki/Y">y</a></h2>'
            "<p>body</p></body></html>"
        )
        start = time.perf_counter()
        _rendered, sections = self._sections(html)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"heading match took {elapsed:.2f}s"
        assert [s["title"] for s in sections][0] == "T"

    def test_backslash_run_heading_still_matches_relaxed(self) -> None:
        """The relaxed pattern exists to tolerate html2text's escaping, so a
        heading whose backslashes were doubled in the render must still be
        located."""
        html = (
            "<html><body><h1>T</h1><p>intro</p>"
            "<h2>a" + ("\\" * 3) + "b</h2><p>body</p></body></html>"
        )
        _rendered, sections = self._sections(html)
        assert [s["title"] for s in sections] == ["T", "a\\\\\\b"]

    def test_loose_escaped_text_tolerates_doubled_backslashes(self) -> None:
        pattern = re.compile(_loose_escaped_text("a\\\\b"))
        assert pattern.search("a\\\\\\\\b") is not None
        assert pattern.search("a\\\\b") is not None

    def test_loose_escaped_text_tolerates_escaped_punctuation(self) -> None:
        pattern = re.compile(_loose_escaped_text("1. Topic"))
        assert pattern.search("1\\. Topic") is not None
