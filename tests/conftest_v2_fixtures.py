"""V2 golden-file fixture archive builder."""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def v2_phase_a_zim(tmp_path_factory) -> Path:
    """Build a tiny ZIM with articles for Phase A snapshot tests.

    Articles:
      - A/Einstein: contains an infobox table + one large content table
      - A/PlainArticle: no infobox, no large table (control)
      - A/MultiTable: multiple oversized tables
      - A/LongArticle: longer than typical compact_budget (forces truncation)
    """
    from libzim.writer import Creator, Hint, Item, StringProvider

    out_dir = tmp_path_factory.mktemp("v2-golden")
    out_path = out_dir / "v2_phase_a.zim"

    class _HtmlItem(Item):
        def __init__(self, path, title, html):
            super().__init__()
            self._path = path
            self._title = title
            self._html = html

        def get_path(self):
            return self._path

        def get_title(self):
            return self._title

        def get_mimetype(self):
            return "text/html"

        def get_contentprovider(self):
            return StringProvider(self._html)

        def get_hints(self):
            return {Hint.FRONT_ARTICLE: 1}

    fixtures = [
        (
            "A/Einstein",
            "Einstein",
            "<html><body>"
            "<table class='infobox'>"
            "<tr><th>Born</th><td>14 March 1879</td></tr>"
            "<tr><th>Died</th><td>18 April 1955</td></tr>"
            "<tr><th>Field</th><td>Theoretical physics</td></tr>"
            "</table>"
            "<p>Albert Einstein was a German-born theoretical physicist. "
            "He developed the theory of relativity, one of the two pillars "
            "of modern physics.</p>"
            "<table>"
            + "".join(
                f"<tr><td>Award {i}</td><td>Year {1900 + i}</td></tr>"
                for i in range(15)
            )
            + "</table>"
            "</body></html>",
        ),
        (
            "A/PlainArticle",
            "PlainArticle",
            "<html><body><p>This article has no infobox and no large tables. "
            "It is a control case for the snapshot suite.</p></body></html>",
        ),
        (
            "A/MultiTable",
            "MultiTable",
            "<html><body><p>Intro paragraph.</p>"
            "<table>" + "<tr><td>x</td></tr>" * 20 + "</table>"
            "<p>Middle paragraph.</p>"
            "<table>" + "<tr><td>y</td></tr>" * 20 + "</table>"
            "</body></html>",
        ),
        (
            "A/LongArticle",
            "LongArticle",
            "<html><body><p>" + ("Word " * 5000) + "</p></body></html>",
        ),
    ]

    with Creator(out_path).config_indexing(True, "eng") as creator:
        for path, title, html in fixtures:
            creator.add_item(_HtmlItem(path, title, html))
        creator.set_mainpath("A/Einstein")

    return out_path
