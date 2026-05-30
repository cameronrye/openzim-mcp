"""Regression tests for the post-v2.1.0 live beta-test sweep.

Defects surfaced by an end-to-end real-world sweep against the live remote
deployment (Wikipedia 2026-02 + superuser.com sotoki) and a local source
build driven over the IEP + MedlinePlus ZIMIT archives.

D1 — query-term highlighting corrupts EMPTY-text markdown links.
     ``[](../wp-content/media/plato.jpg)`` rendered as
     ``[](../wp-content/media/**plato**.jpg)`` because ``_HIGHLIGHT_SKIP_RE``
     required NON-empty link text (``[^\\]\\n]+``) to recognise a link, so
     ZIMIT image links with empty alt text (``[](url)``) were not protected
     and a query term inside the URL got bolded — breaking the image path.
     Observed live in IEP search snippets and synthesize answers.

D2 — "articles related to <X>" surfaces image / media links as articles.
     ``articles related to Plato`` (IEP) returned
     ``iep.utm.edu/wp-content/media/plato.jpg`` (an image, empty link text)
     as the rank-1 "related article". Media links should be excluded from
     the related-article result set.
"""

from __future__ import annotations

import re

from openzim_mcp.content_processor import _highlight_terms
from openzim_mcp.zim_operations import ZimOperations


class TestD1HighlightEmptyLinks:
    """D1 — highlighting must not bold inside an empty-text link's URL."""

    def test_empty_text_image_link_url_not_highlighted(self) -> None:
        text = "[](../wp-content/media/plato.jpg)Plato wrote the Meno."
        out = _highlight_terms(text, "plato", max_hits=10)
        # The URL inside the link must survive verbatim — no ** injected.
        assert "](../wp-content/media/plato.jpg)" in out
        assert "**plato**.jpg" not in out
        # The prose occurrence outside the link is still highlighted.
        assert "**Plato**" in out

    def test_empty_text_link_with_term_in_path(self) -> None:
        text = "[](../plato/) and then Plato again"
        out = _highlight_terms(text, "plato", max_hits=10)
        assert "[](../plato/)" in out  # link target intact
        assert "**Plato**" in out  # prose term highlighted

    def test_nonempty_link_text_still_protected(self) -> None:
        # Pre-existing protection must not regress.
        text = "See [Plato bio](../plato/) for more."
        out = _highlight_terms(text, "plato", max_hits=10)
        assert out == text  # nothing to highlight outside the protected link

    def test_image_with_alt_text_still_protected(self) -> None:
        text = "![alt plato](../media/plato.jpg) text"
        out = _highlight_terms(text, "plato", max_hits=10)
        assert out == text

    def test_plain_prose_highlight_unaffected(self) -> None:
        text = "The Theory of relativity by Einstein."
        out = _highlight_terms(text, "relativity einstein", max_hits=10)
        assert "**relativity**" in out
        assert "**Einstein**" in out

    def test_no_bold_inside_any_link_url(self) -> None:
        """General invariant: no ``**`` may appear between ``](`` and ``)``."""
        text = (
            "[](../wp-content/media/slideshow-plato.jpg)"
            "Plato: Organicism is the position..."
        )
        out = _highlight_terms(text, "plato", max_hits=10)
        # Find every markdown link target and assert no bold markers inside.
        for m in re.finditer(r"\]\(([^)]*)\)", out):
            assert "**" not in m.group(1), f"bold leaked into link URL: {m.group(1)}"


class TestD2RelatedArticlesExcludeMedia:
    """D2 — related-articles must exclude binary-asset link targets."""

    def test_image_targets_are_non_article(self) -> None:
        for path in (
            "iep.utm.edu/wp-content/media/plato.jpg",
            "iep.utm.edu/wp-content/media/slideshow-plato.JPG",
            "I/Foo.png",
            "static/x.svg",
            "a/b/c.webp",
        ):
            assert ZimOperations._is_non_article_target(path) is True, path

    def test_asset_targets_are_non_article(self) -> None:
        for path in (
            "_zim_static/wombat.js",
            "_zim_static/custom.css",
            "cdnjs.cloudflare.com/.../MathJax_AMS-Regular.eot",
            "fonts/X.woff2",
            "doc/manual.pdf",
        ):
            assert ZimOperations._is_non_article_target(path) is True, path

    def test_article_targets_are_articles(self) -> None:
        # Real navigable articles — including MedlinePlus .html/.htm pages —
        # must NOT be treated as assets.
        for path in (
            "iep.utm.edu/plato/",
            "iep.utm.edu/socrates/",
            "Theory_of_relativity",
            "U.S._Route_66",
            "medlineplus.gov/appendicitis.html",
            "medlineplus.gov/ency/article/000256.htm",
        ):
            assert ZimOperations._is_non_article_target(path) is False, path

    def test_query_and_fragment_are_ignored(self) -> None:
        assert ZimOperations._is_non_article_target("x.png?v=2") is True
        assert ZimOperations._is_non_article_target("foo.html#sec") is False
