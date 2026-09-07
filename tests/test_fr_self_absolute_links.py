"""A link to the archive's own host is a link inside the archive.

v3.3.1 field report, fid 17 — graded high, and the largest under-report in
the whole links surface::

    zim_links(IEP, "iep.utm.edu/aristotle/", kind="internal")
      -> total: 3
    category_totals: {"internal": 3, "external": 10, "media": 2, "anchor": 30}

Six of those ten "external" rows are ``https://www.iep.utm.edu/…`` — the
archive's own host — and every one of them resolves inside this very
archive: ``/ibnrushd/`` serves ``iep.utm.edu/ibn-rushd-averroes/``,
``/aris-log/`` serves ``iep.utm.edu/aristotle-logic/``. They shipped as
``{url, text, title, domain}`` with no ``path``, so a model had to guess
the URL→path transform, and the guess it was told to make was wrong.

warc2zim keeps the scraped site's own absolute links absolute; the
classifier is purely scheme-based (``http``/``https`` → external), so it
cannot see that the host is the archive's own. Three properties matter and
each has a test below:

* a same-host absolute URL that RESOLVES becomes internal, with a
  ``path`` that round-trips into ``zim_get``;
* one that does NOT resolve stays external — promoting a dead link would
  trade an under-report for a lie;
* a genuinely off-site URL is untouched, on this archive and on an
  mwoffliner-shaped one that has no host prefix at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest
from libzim.writer import Creator, Hint, Item, StringProvider

from openzim_mcp.zim_operations import ZimOperations
from tests.conftest_v2_fixtures import _HtmlItem, make_zim_ops

HOST = "iep.utm.edu"

# One scraped page whose <a href>s cover every case the classifier has to
# separate. warc2zim leaves the site's own links absolute, complete with the
# ``www.`` the archive's entry paths do not carry.
_ARISTOTLE = f"""<html><body><article>
<h1>Aristotle</h1>
<p>See the <a href="https://www.{HOST}/aris-log/">logic</a> and
   <a href="https://{HOST}/ibnrushd/">Ibn Rushd</a> articles,
   and <a href="https://www.{HOST}/plato/#SH6b">Plato</a>.</p>
<p>A same-host link to a page this archive never captured:
   <a href="https://www.{HOST}/never-scraped/">missing</a>.</p>
<p>A relative link, which always worked:
   <a href="../lyceum/">the Lyceum</a>.</p>
<p>Genuinely elsewhere:
   <a href="https://plato.stanford.edu/entries/aristotle/">SEP</a>.</p>
<p><a href="#section-2">In-page anchor.</a></p>
</article></body></html>"""

_PAGES = {
    f"{HOST}/aristotle/": ("Aristotle | Internet Encyclopedia", _ARISTOTLE),
    f"{HOST}/aristotle-logic/": (
        "Aristotle: Logic",
        "<html><body><p>Logic.</p></body></html>",
    ),
    f"{HOST}/ibn-rushd-averroes/": (
        "Ibn Rushd (Averroes)",
        "<html><body><p>Averroes.</p></body></html>",
    ),
    f"{HOST}/plato/": ("Plato", "<html><body><p>Plato.</p></body></html>"),
    f"{HOST}/lyceum/": ("The Lyceum", "<html><body><p>Lyceum.</p></body></html>"),
}

# The two spellings the page links to that are NOT stored paths. warc2zim
# resolves them with redirects, which is exactly how the finding's own
# examples behaved.
_REDIRECTS = {
    f"{HOST}/aris-log/": f"{HOST}/aristotle-logic/",
    f"{HOST}/ibnrushd/": f"{HOST}/ibn-rushd-averroes/",
}


class _Redirect(Item):
    def __init__(self, path: str, target: str) -> None:
        super().__init__()
        self._path = path
        self._target = target

    def get_path(self) -> str:
        return self._path

    def get_title(self) -> str:
        return self._path

    def get_mimetype(self) -> str:
        return "text/html"

    def get_contentprovider(self) -> StringProvider:
        return StringProvider("")

    def get_hints(self) -> Dict[Hint, int]:
        return {Hint.FRONT_ARTICLE: 1}


@pytest.fixture(scope="module")
def scraped_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A warc2zim-shaped archive: entry paths are host-prefixed."""
    out_dir = tmp_path_factory.mktemp("fr-self-abs")
    out_path = out_dir / "iep_like.zim"
    with Creator(out_path).config_indexing(True, "eng") as creator:
        for path, (title, body) in _PAGES.items():
            creator.add_item(_HtmlItem(path, title, body))
        for src, dst in _REDIRECTS.items():
            creator.add_redirection(src, src, dst, {Hint.FRONT_ARTICLE: 1})
        creator.set_mainpath(f"{HOST}/aristotle/")
    return out_path


@pytest.fixture(scope="module")
def ops(scraped_zim: Path) -> ZimOperations:
    return make_zim_ops(str(scraped_zim.parent))


def _links(ops: ZimOperations, zim: Path, kind: str) -> Dict[str, Any]:
    return ops.extract_article_links_data(
        str(zim), f"{HOST}/aristotle/", kind=kind, limit=50
    )


# ---------------------------------------------------------------------------
# The archive's own host is internal
# ---------------------------------------------------------------------------


def test_a_same_host_link_is_reported_as_internal(ops, scraped_zim):
    internal = _links(ops, scraped_zim, "internal")

    urls = {r.get("url", "") for r in internal["results"]}
    assert any("aris-log" in u for u in urls), sorted(urls)
    assert any("ibnrushd" in u for u in urls), sorted(urls)
    assert any("plato" in u for u in urls), sorted(urls)


def test_the_www_prefix_is_not_a_different_site(ops, scraped_zim):
    """The archive stores ``iep.utm.edu/…``; the page links to
    ``https://www.iep.utm.edu/…``. One host, two spellings."""
    internal = _links(ops, scraped_zim, "internal")

    www_rows = [r for r in internal["results"] if "www." in r.get("url", "")]
    assert www_rows, [r.get("url") for r in internal["results"]]
    assert all(r.get("path") for r in www_rows), www_rows


def test_the_promoted_row_carries_a_path_that_round_trips(ops, scraped_zim):
    """The whole point: the model no longer has to guess the transform."""
    internal = _links(ops, scraped_zim, "internal")

    row = next(r for r in internal["results"] if "ibnrushd" in r.get("url", ""))
    assert row["path"], row
    fetched = ops.get_zim_entry_data(str(scraped_zim), row["path"])
    assert fetched.get("error") is not True, fetched
    assert "Averroes" in fetched["title"], fetched["title"]


def test_the_totals_move_together(ops, scraped_zim):
    """``category_totals`` is what the finding measured as 3-vs-10."""
    totals = _links(ops, scraped_zim, "internal")["category_totals"]

    assert totals["internal"] >= 4, totals
    # Only the genuinely off-site link and the unresolvable same-host one
    # are left outside.
    assert totals["external"] == 2, totals


# ---------------------------------------------------------------------------
# ...but only when the archive can actually serve it
# ---------------------------------------------------------------------------


def test_a_same_host_link_the_archive_lacks_stays_external(ops, scraped_zim):
    """Promoting an unresolvable link would trade an under-report for a
    lie: the row would claim a ``path`` no ``zim_get`` can open."""
    external = _links(ops, scraped_zim, "external")

    urls = {r.get("url", "") for r in external["results"]}
    assert any("never-scraped" in u for u in urls), sorted(urls)


def test_an_offsite_link_is_untouched(ops, scraped_zim):
    external = _links(ops, scraped_zim, "external")

    sep = [r for r in external["results"] if "plato.stanford.edu" in r.get("url", "")]
    assert sep, [r.get("url") for r in external["results"]]
    assert "path" not in sep[0], sep[0]
    assert sep[0].get("domain") == "plato.stanford.edu", sep[0]


def test_a_relative_link_still_works(ops, scraped_zim):
    """Control: the path that always worked must not regress."""
    internal = _links(ops, scraped_zim, "internal")

    row = next(r for r in internal["results"] if r.get("url") == "../lyceum/")
    assert row["path"] == f"{HOST}/lyceum/", row


def test_an_in_page_anchor_is_still_not_a_link(ops, scraped_zim):
    """Controls the other boundary: anchors are counted separately and must
    not be swept into internal by a promotion pass."""
    totals = _links(ops, scraped_zim, "internal")["category_totals"]

    assert totals["anchor"] == 1, totals


def test_an_archive_with_no_host_prefix_is_left_alone(
    tmp_path_factory, real_content_zim_files
):
    """mwoffliner archives store ``A/Article`` — there is no host segment to
    compare against, so no promotion can fire. Guards against a heuristic
    that reads the first path segment as a host on every archive."""
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("wikipedia fixture not in the corpus")
    mw_ops = make_zim_ops(str(Path(zim).parent))

    out = mw_ops.extract_article_links_data(
        str(zim), "A/Climate_change_in_the_Americas", kind="external", limit=20
    )

    for row in out["results"]:
        assert "path" not in row, row


# ---------------------------------------------------------------------------
# What counts as "the archive's own host"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry_path,expected",
    [
        ("iep.utm.edu/aristotle/", "iep.utm.edu"),
        ("medlineplus.gov/druginfo/meds/a696005.html", "medlineplus.gov"),
        ("EXAMPLE.ORG/Page", "example.org"),
        # mwoffliner: a namespace letter is not a host, and reading it as one
        # would let ``https://a/x`` masquerade as a same-site link on every
        # Wikipedia-shaped archive.
        ("A/Climate_change", None),
        ("C/Aspirin", None),
        # An escaped asset name is a path segment, not an authority.
        ("I/Al_Gore%2C_2007.webp", None),
        # Degenerate shapes that must not become a host.
        (".hidden/page", None),
        ("some host.org/page", None),
        ("", None),
    ],
)
def test_only_a_host_shaped_first_segment_is_read_as_the_host(entry_path, expected):
    from openzim_mcp.zim.structure import _self_host

    assert _self_host(entry_path) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.iep.utm.edu/aris-log/", "iep.utm.edu/aris-log/"),
        ("https://iep.utm.edu/plato/#SH6b", "iep.utm.edu/plato/"),
        ("http://iep.utm.edu/a/b.html", "iep.utm.edu/a/b.html"),
        ("//www.iep.utm.edu/x/", "iep.utm.edu/x/"),
        # The site root is the archive's main page, not an article.
        ("https://iep.utm.edu/", None),
        ("https://iep.utm.edu", None),
        # Other hosts, including ones that merely end with the same string.
        ("https://plato.stanford.edu/entries/aristotle/", None),
        ("https://notiep.utm.edu/x/", None),
        ("https://evil.example/?u=iep.utm.edu", None),
        # Not a web URL at all.
        ("mailto:someone@iep.utm.edu", None),
        ("../lyceum/", None),
    ],
)
def test_only_this_archives_own_host_yields_a_candidate(url, expected):
    from openzim_mcp.zim.structure import _self_absolute_target

    assert _self_absolute_target(url, "iep.utm.edu") == expected
