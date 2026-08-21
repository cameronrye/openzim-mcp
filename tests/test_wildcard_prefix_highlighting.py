"""Regression tests for trailing-``*`` prefix terms in snippet highlighting.

A wildcard query (``climat*``) retrieves fine — libzim hands the query to
Xapian, whose stemmer matches ``climate`` — but the snippet came back with
nothing bolded: ``_snippet_query`` peeled the ``*`` off and
``_highlight_terms`` then hunted for a literal whole word ``climat`` that
never occurs in prose. The very hit the stemmer found went unmarked, and the
paragraph ANCHOR could land on a different paragraph than the one the
highlighter would have bolded (the 2/3-stem fallback in ``create_snippet``
is looser than the whole-word pass).

Surfaces covered: ``zim_search`` (mode="fulltext", including the
namespace/content-type-filtered projection) and ``zim_query`` — both funnel
through ``_get_entry_snippet`` -> ``ContentProcessor.create_snippet`` ->
``_highlight_terms``.
"""

import re

from openzim_mcp.content_processor import (
    ContentProcessor,
    _highlight_terms,
    _split_query_terms,
    _split_query_terms_typed,
)
from openzim_mcp.zim.search import _snippet_query


class TestSnippetQueryKeepsTheWildcardMarker:
    """``_snippet_query`` must hand the ``*`` on, not eat it."""

    def test_trailing_star_survives(self) -> None:
        assert _snippet_query("climat*") == "climat*"

    def test_grouping_punctuation_is_still_peeled(self) -> None:
        assert _snippet_query("(climat*)") == "climat*"

    def test_operator_words_are_still_dropped_when_starred(self) -> None:
        # Without rstrip("*") on the operator test, ``and*`` slips past the
        # operator filter and gets bolded as content again.
        assert _snippet_query("insulin and* glucose") == "insulin glucose"

    def test_bare_star_yields_no_terms(self) -> None:
        assert _snippet_query("*") is None

    def test_existing_operator_stripping_is_unchanged(self) -> None:
        # Byte-identical to the D30 assertions; restated so a rewrite of
        # ``_snippet_query`` cannot quietly regress them.
        assert _snippet_query("(insulin) AND (NOT glucose)") == "insulin glucose"
        assert _snippet_query("salt and pepper") == "salt pepper"
        assert _snippet_query("AND OR NOT") is None


class TestPrefixTermTokenizing:
    """``_split_query_terms_typed`` marks only END-of-term ``*`` as a prefix."""

    def test_trailing_star_marks_a_prefix_term(self) -> None:
        assert _split_query_terms_typed("diabet*") == [("diabet", True)]

    def test_plain_term_is_not_a_prefix(self) -> None:
        assert _split_query_terms_typed("diabetes") == [("diabetes", False)]

    def test_mid_word_star_is_two_ordinary_terms(self) -> None:
        # Xapian honours ``*`` only at the end of a term, so ``clima*te``
        # is two literals — not a prefix probe.
        assert _split_query_terms_typed("clima*te") == [("clima", True), ("te", False)]

    def test_bare_star_yields_nothing(self) -> None:
        assert _split_query_terms_typed("*") == []
        assert _split_query_terms_typed("**") == []

    def test_untyped_splitter_still_returns_bare_terms(self) -> None:
        assert _split_query_terms("Climat* change") == ["climat", "change"]


class TestPrefixTermHighlighting:
    """``_highlight_terms`` bolds the whole word a prefix term opens."""

    def test_prefix_term_bolds_the_stemmed_word(self) -> None:
        out = _highlight_terms(
            "Diabetes mellitus, also called diabetes, affects patients.",
            "diabet*",
            max_hits=10,
        )
        assert "**Diabetes**" in out
        assert "**diabetes**" in out

    def test_prefix_term_anchors_at_the_word_start(self) -> None:
        # The leading ``\b`` is Xapian's prefix semantics: ``diabet*`` does
        # not match the middle of ``prediabetes``.
        out = _highlight_terms("A prediabetes diagnosis.", "diabet*", max_hits=10)
        assert out == "A prediabetes diagnosis."

    def test_literal_term_is_still_whole_word_only(self) -> None:
        # The guard that the change is prefix-ONLY and not a general
        # substring loosening (mirrors test_word_boundaries_still_apply).
        out = _highlight_terms("cafeteria and cafe", "cafe", max_hits=10)
        assert "**cafeteria**" not in out
        assert "**cafe**" in out

    def test_star_makes_the_same_term_prefix_matching(self) -> None:
        out = _highlight_terms("cafeteria and cafe", "cafe*", max_hits=10)
        assert "**cafeteria**" in out
        assert "**cafe**" in out

    def test_short_prefix_is_ignored(self) -> None:
        # Prefix terms need 4+ chars: ``car*`` would otherwise bold
        # carbon/cardiac/carry/careful.
        text = "Carbon and cardiac and carry."
        assert _highlight_terms(text, "car*", max_hits=10) == text

    def test_four_char_prefix_is_the_floor(self) -> None:
        out = _highlight_terms("Carbon dioxide levels.", "carb*", max_hits=10)
        assert "**Carbon**" in out

    def test_bare_star_query_leaves_text_untouched(self) -> None:
        text = "Nothing should be bolded here."
        assert _highlight_terms(text, "*", max_hits=10) == text
        assert _highlight_terms(text, "**", max_hits=10) == text
        assert not re.search(r"\*\*", _highlight_terms(text, "*", max_hits=10))

    def test_mid_word_star_does_not_prefix_match(self) -> None:
        text = "Climate change is real."
        # ``a*b``-shaped query: both halves are ordinary terms, and both are
        # below the literal 3-char floor, so nothing is bolded.
        assert _highlight_terms(text, "a*b", max_hits=10) == text

    def test_prefix_match_folds_case_and_diacritics(self) -> None:
        out = _highlight_terms("The Café is open.", "cafe*", max_hits=10)
        assert "**Café**" in out

    def test_prefix_match_spans_a_ligature_expansion(self) -> None:
        # ``_fold("ﬁ") == "fi"``: the one-to-many index map must still map
        # the (now longer) prefix span back onto the source characters.
        out = _highlight_terms("The ﬁles are here.", "file*", max_hits=10)
        assert "**ﬁles**" in out

    def test_prefix_match_inside_a_link_is_still_protected(self) -> None:
        text = '[Climate change](Climate_change "Climate change") and climate talk'
        out = _highlight_terms(text, "climat*", max_hits=10)
        assert '[Climate change](Climate_change "Climate change")' in out
        assert "**climate**" in out
        assert out.count("**") == 2

    def test_prefix_match_skips_existing_emphasis(self) -> None:
        text = "**Climate change** is real; climate matters"
        out = _highlight_terms(text, "climat*", max_hits=10)
        assert "**Climate change**" in out
        assert "****" not in out
        assert out.count("**") == 4

    def test_longest_alternative_wins_over_a_shorter_one(self) -> None:
        # First-match-wins alternation: a short term must not shadow a
        # longer alternative that shares its opening characters.
        out = _highlight_terms(
            "Climate variability includes the climate.", "climate climat*", max_hits=10
        )
        assert out == "**Climate** variability includes the **climate**."

    def test_overlapping_terms_produce_no_nested_markers(self) -> None:
        out = _highlight_terms("Climatology matters.", "clim* climat*", max_hits=10)
        assert out == "**Climatology** matters."


class TestPrefixTermSnippetAnchoring:
    """Paragraph selection must agree with what gets bolded."""

    def test_snippet_bolds_the_wildcard_hit(self) -> None:
        proc = ContentProcessor(snippet_length=400)
        markdown = "Climate variability includes all the variations in the climate."
        out = proc.create_snippet(
            markdown, query=_snippet_query("climat*"), max_paragraphs=1
        )
        assert "**Climate**" in out

    def test_anchor_agrees_with_the_highlighter(self) -> None:
        """The 2/3-stem fallback used to anchor a paragraph nothing bolds.

        ``climat`` has no whole-word hit anywhere here, so pass 2 probed the
        4-char stem ``clim`` and stopped on "Climbing" — a paragraph the
        highlighter would leave completely unmarked. The prefix-aware
        whole-word pass now reaches "Climate" in paragraph 2.
        """
        proc = ContentProcessor(snippet_length=400)
        markdown = (
            "Climbing is a popular sport in the alps.\n\n"
            "Climate change is real and ongoing."
        )
        out = proc.create_snippet(
            markdown, query=_snippet_query("climat*"), max_paragraphs=1
        )
        assert out.startswith("**Climate**")
        assert "Climbing" not in out


class TestSnippetQueryStripsFieldPrefixes:
    """``title:diabetes`` used to bold the word "title" in the article body."""

    def test_title_prefix_is_stripped(self) -> None:
        assert _snippet_query("title:diabetes") == "diabetes"

    def test_path_prefix_is_stripped(self) -> None:
        assert _snippet_query("path:Aspirin") == "Aspirin"

    def test_field_prefix_and_wildcard_together(self) -> None:
        assert _snippet_query("title:diabet*") == "diabet*"

    def test_prose_colon_is_not_a_field_prefix(self) -> None:
        # Allowlist, not a generic ``^\w+:`` strip: a ratio must survive.
        assert _snippet_query("3:1 ratio") == "3:1 ratio"
        assert _snippet_query("chapter:2 summary") == "chapter:2 summary"

    def test_bare_field_prefix_is_left_alone(self) -> None:
        assert _snippet_query("title:") == "title:"

    def test_field_name_is_no_longer_highlighted_as_content(self) -> None:
        text = "The title of the article on Diabetes mellitus is set."
        out = _highlight_terms(text, _snippet_query("title:diabetes") or "", max_hits=5)
        assert "**title**" not in out
        assert "**Diabetes**" in out


class TestSynthesizePathNormalisesTheQuery:
    """``search_top_k`` fed the RAW query to the snippet builder.

    D30 stripped operator words from the snippet query on the interactive
    search path only, so the synthesize path kept bolding ``**and**`` and
    anchoring on nav junk.
    """

    def test_search_top_k_strips_operator_words(self, tmp_path) -> None:
        from unittest.mock import MagicMock, patch

        from tests.zim_stubs import make_archive_stub, make_ops, make_search_stub

        ops = make_ops(tmp_path)

        def _entry(eid: str) -> MagicMock:
            entry = MagicMock()
            entry.path = eid
            entry.title = "Hypoglycemia"
            item = MagicMock()
            item.mimetype = "text/html"
            item.content = (
                b"<p>Diagnosis and Tests</p>"
                b"<p>Insulin is a hormone that lowers blood glucose.</p>"
            )
            entry.get_item.return_value = item
            return entry

        with patch("openzim_mcp.zim_operations.Searcher") as searcher:
            searcher.return_value.search.return_value = make_search_stub(["C/Hypo"])
            hits = ops.search_top_k(
                make_archive_stub(_entry), "(insulin) AND (NOT glucose)", k=1
            )

        snippet = hits[0]["snippet"]
        assert "**Insulin**" in snippet, snippet
        assert "**and**" not in snippet
        assert "**AND**" not in snippet

    def test_title_match_hit_keeps_its_raw_title(self, tmp_path) -> None:
        """A title is not a query — ``and`` in it is a word, not an operator.

        Pinned so a later sweep does not "fix" ``title_match_hit`` by
        routing it through ``_snippet_query`` too.
        """
        from unittest.mock import MagicMock, patch

        from tests.zim_stubs import make_archive_stub, make_ops

        ops = make_ops(tmp_path)

        def _entry(eid: str) -> MagicMock:
            entry = MagicMock()
            entry.path = eid
            entry.title = "Sense and Sensibility"
            entry.is_redirect = False
            item = MagicMock()
            item.mimetype = "text/html"
            item.content = b"<p>Sense and Sensibility is a novel by Jane Austen.</p>"
            entry.get_item.return_value = item
            return entry

        archive = make_archive_stub(_entry)
        with patch.object(ops, "_find_entry_fast_path", return_value=_entry("A/Sense")):
            hit = ops.title_match_hit(archive, "Sense and Sensibility")

        assert hit is not None
        assert "**and**" in hit["snippet"], hit["snippet"]
