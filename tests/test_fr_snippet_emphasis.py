"""Snippet emphasis must point at content words, not at articles.

v3.3.1 field report, fid 68 — and the audit that caught the first fix not
fixing it. On the finding's own repro queries the rendered output was
unchanged: ``what is the trolley problem`` bolded ``the`` eight times out of
eight, with nothing on *trolley* or *problem*, both before and after.

The first attempt rationed ``max_hits`` per term. That cannot move this
case, and the arithmetic says why: terms ``[what, the, trolley, problem]``
give ``per_term_cap = max(1, 5 // 4) = 1``, so ``the`` gets one rationed
slot and the remaining four are refilled left-to-right from the runners-up
— which, on a real snippet containing no *trolley* and no *problem*, are
more occurrences of ``the``. The backfill restores exactly the behaviour
the rationing was meant to replace, in precisely the situation that
produced the report.

The finding offered a second remedy, and it is the one that holds: keep
function words out of the highlight set entirely. The anchor decision
already drops them through ``_keep_anchorable_terms``, whose docstring said
"Highlighting keeps the full term set" — that sentence was the bug.

Emphasis on ``the`` is not merely useless: it tells a reader the entry
matched on an article. No emphasis is better, which is what an all-function
-word snippet now gets.
"""

from __future__ import annotations

import pytest

from openzim_mcp.content_processor import ContentProcessor

# The real-world shape: a page about the trolley problem whose SNIPPET
# window — the first paragraphs — happens to carry neither content word.
_NO_CONTENT_WORDS = (
    "<html><body>"
    "<p>The article below is part of the series on ethics. "
    "The editors of the encyclopedia maintain the entry, and the "
    "reader is invited to consult the bibliography at the end of "
    "the page for the sources.</p>"
    "</body></html>"
)

_WITH_CONTENT_WORDS = (
    "<html><body>"
    "<p>The trolley problem is a thought experiment in ethics. "
    "The problem asks whether the driver of a runaway trolley should "
    "divert it.</p>"
    "</body></html>"
)


@pytest.fixture
def processor() -> ContentProcessor:
    return ContentProcessor(snippet_length=600)


def _bolded(text: str) -> list[str]:
    import re

    return re.findall(r"\*\*(.+?)\*\*", text)


def test_articles_are_not_bolded_when_nothing_else_matches(processor):
    """The finding's headline number: 8 of 8 bold spans were ``the``."""
    snippet = processor.create_snippet(
        _NO_CONTENT_WORDS, query="what is the trolley problem", max_paragraphs=2
    )

    assert "the" not in [b.lower() for b in _bolded(snippet)], _bolded(snippet)


def test_the_snippet_itself_is_unharmed(processor):
    """Dropping the emphasis must not drop the text. Paired with the test
    above so "no bold spans" cannot be satisfied by an empty snippet."""
    snippet = processor.create_snippet(
        _NO_CONTENT_WORDS, query="what is the trolley problem", max_paragraphs=2
    )

    assert "series on ethics" in snippet, snippet
    assert len(snippet) > 100, snippet


def test_content_words_are_bolded_when_they_are_there(processor):
    """The positive half: this is what the emphasis budget is for."""
    snippet = processor.create_snippet(
        _WITH_CONTENT_WORDS, query="what is the trolley problem", max_paragraphs=2
    )

    bolded = {b.lower() for b in _bolded(snippet)}
    assert "trolley" in bolded, _bolded(snippet)
    assert "problem" in bolded, _bolded(snippet)
    assert "the" not in bolded, _bolded(snippet)


def test_the_budget_is_no_longer_spent_before_reaching_them(processor):
    """The precise mechanism the audit identified.

    ``the`` appears five times before ``trolley`` does here, which is more
    than the whole ``max_hits`` budget — under a left-to-right cap, or under
    a per-term cap whose leftovers backfill from ``the``, the content words
    are never reached.
    """
    body = (
        "<html><body><p>The first of the several notes on the topic, and "
        "the second of the notes, precede the trolley problem discussion "
        "entirely.</p></body></html>"
    )

    snippet = processor.create_snippet(
        body, query="what is the trolley problem", max_paragraphs=2
    )

    bolded = {b.lower() for b in _bolded(snippet)}
    assert "trolley" in bolded, _bolded(snippet)


def test_a_query_that_is_only_function_words_still_highlights(processor):
    """Control: filtering must not empty the term set.

    ``The Who`` and ``It`` are real article titles. When every term is a
    function word there is nothing else to point at, so the old behaviour
    is the right one.
    """
    body = "<html><body><p>The Who formed in London in 1964.</p></body></html>"

    snippet = processor.create_snippet(body, query="the who", max_paragraphs=2)

    assert _bolded(snippet), snippet


def test_a_single_content_word_query_is_unchanged(processor):
    """Control: the common case must not regress."""
    snippet = processor.create_snippet(
        _WITH_CONTENT_WORDS, query="trolley", max_paragraphs=2
    )

    assert {b.lower() for b in _bolded(snippet)} == {"trolley"}, _bolded(snippet)


def test_highlighting_and_anchoring_now_use_the_same_terms():
    """The docstring said highlighting keeps the full term set. It was the
    only place that still did, and that sentence was the defect.

    Asserted on what ``_highlight_terms`` actually bolds, against a text
    carrying every term of the query, rather than on the helper's return
    value — the filter is applied at the call site, so reading the helper
    would check the wrong seam and pass whatever the call site did.
    """
    from openzim_mcp.content_processor import (
        _highlight_terms,
        _keep_anchorable_terms,
        _keep_highlightable_terms,
    )

    query = "what is the trolley problem"
    text = "what the trolley problem is"

    out = _highlight_terms(text, query, max_hits=10)
    bolded = {b.lower() for b in _bolded(out)}
    anchorable = {
        t for t, _ in _keep_anchorable_terms(_keep_highlightable_terms(query))
    }

    assert bolded == anchorable, (bolded, anchorable)
