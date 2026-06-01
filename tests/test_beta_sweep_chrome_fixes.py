"""Post-v2.0.5 beta-sweep fixes: site-chrome leakage + search dup variants.

Background: on ZIMIT / warc2zim archives (MedlinePlus, IEP) the original
site's banner / nav / header / footer / aside chrome is embedded in the
entry HTML. The content-shape tools that read from the top of the
rendered document (get_entry_summary), or that enumerate every heading /
link (get_table_of_contents, get_related_articles), or that build search
snippets, surfaced that chrome instead of the article body. The shared
fix scopes extraction to the page's main-content landmark
(``<main>`` / ``[role=main]`` / ``<article>``) when present, falling back
to the whole document when absent (so Wikipedia/mwoffliner pages, which
carry no such landmark, are unaffected).

Separately, warc2zim stores query-string URL variants as distinct
entries, so filtered search returned ``foo.htm`` and ``foo.htm?quiz=1``
as two hits; results are now deduped by canonical path.

These mirror the real structures observed on
``medlineplus.gov_en_all_2025-01.zim`` and
``internet-encyclopedia-philosophy_en_all_2025-06.zim``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from openzim_mcp.bundle import extract_entry_bundle
from openzim_mcp.content_processor import ContentProcessor

# A page whose real article lives inside <article>, with the original
# site's chrome (skip-nav, federal banner, header nav, footer, aside)
# surrounding it — the shape seen on MedlinePlus / IEP.
ZIMIT_HTML = """\
<html><body>
<a class="usa-skipnav" href="#main">Skip navigation</a>
<section class="usa-banner"><p>An official website of the United States government</p></section>
<header>
  <h1>MedlinePlus Trusted Health Information</h1>
  <a href="../../healthtopics.html">Health Topics</a>
  <a href="../../encyclopedia.html">Medical Encyclopedia</a>
  <a href="../../about/">About MedlinePlus</a>
</header>
<article>
  <h1>Type 2 Diabetes</h1>
  <p>Type 2 diabetes is a long-term condition in which the body does not
  use insulin properly, causing blood sugar levels to rise over time.</p>
  <h2>Causes</h2>
  <p>Insulin resistance develops in the body's cells, and the pancreas
  cannot keep blood glucose in the normal range.</p>
  <a href="ency/article/000305.htm">Blood glucose test</a>
  <a href="ency/article/000313.htm">Type 1 diabetes</a>
</article>
<footer>
  <h2>Stay Connected</h2>
  <a href="../../about/">About MedlinePlus</a>
  <a href="../../index.html">Home</a>
</footer>
</body></html>
"""

# A Wikipedia/mwoffliner-style page with NO main-content landmark — the
# fallback path must leave these untouched.
PLAIN_HTML = """\
<html><body>
<h1>Berlin</h1>
<p>Berlin is the capital and largest city of Germany.</p>
<h2>Geography</h2>
<p>Berlin's terrain is generally flat.</p>
<a href="A/Spree_River">Spree</a>
</body></html>
"""


def _make_archive(html: str, *, title: str, entry_path: str) -> MagicMock:
    item = MagicMock()
    item.content = html.encode("utf-8")
    item.mimetype = "text/html"
    entry = MagicMock()
    entry.title = title
    entry.path = entry_path
    entry.is_redirect = False
    entry.get_item.return_value = item
    archive = MagicMock()
    archive.get_entry_by_path.return_value = entry
    return archive


@pytest.fixture
def cp() -> ContentProcessor:
    return ContentProcessor()


# --------------------------------------------------------------------------
# select_main_content helper
# --------------------------------------------------------------------------


def test_select_main_content_prefers_article() -> None:
    from bs4 import BeautifulSoup

    from openzim_mcp.content_processor import select_main_content

    soup = BeautifulSoup(ZIMIT_HTML, "html.parser")
    node = select_main_content(soup)
    text = node.get_text()
    assert "Type 2 diabetes is a long-term" in text
    assert "official website" not in text
    assert "Stay Connected" not in text


def test_select_main_content_falls_back_without_landmark() -> None:
    from bs4 import BeautifulSoup

    from openzim_mcp.content_processor import select_main_content

    soup = BeautifulSoup(PLAIN_HTML, "html.parser")
    node = select_main_content(soup)
    # No <main>/<article>/[role=main] -> return the whole document unchanged.
    assert node is soup
    assert "Berlin is the capital" in node.get_text()


def test_select_main_content_ambiguous_multiple_articles_falls_back() -> None:
    from bs4 import BeautifulSoup

    from openzim_mcp.content_processor import select_main_content

    html = "<body><article><p>one</p></article><article><p>two</p></article></body>"
    soup = BeautifulSoup(html, "html.parser")
    node = select_main_content(soup)
    assert node is soup  # >1 article is ambiguous -> no scoping


# --------------------------------------------------------------------------
# #3 get_entry_summary / rendered_markdown — no leading chrome
# --------------------------------------------------------------------------


def test_bundle_rendered_markdown_excludes_site_chrome(cp: ContentProcessor) -> None:
    archive = _make_archive(ZIMIT_HTML, title="Type 2 Diabetes", entry_path="C/000313")
    bundle = extract_entry_bundle(archive, "C/000313", content_processor=cp)
    md = bundle["rendered_markdown"]
    assert "Type 2 diabetes is a long-term" in md
    assert "official website of the United States" not in md
    assert "Stay Connected" not in md
    assert "Health Topics" not in md


def test_bundle_first_section_is_article_lead(cp: ContentProcessor) -> None:
    # The summary slices md[:first_section.char_end]; the first section must
    # be the article H1, not the header/banner chrome.
    archive = _make_archive(ZIMIT_HTML, title="Type 2 Diabetes", entry_path="C/000313")
    bundle = extract_entry_bundle(archive, "C/000313", content_processor=cp)
    assert bundle["sections"], "expected at least one section"
    assert bundle["sections"][0]["title"] == "Type 2 Diabetes"


# --------------------------------------------------------------------------
# #7 get_table_of_contents — headings exclude nav/header/footer chrome
# --------------------------------------------------------------------------


def test_bundle_headings_exclude_chrome(cp: ContentProcessor) -> None:
    archive = _make_archive(ZIMIT_HTML, title="Type 2 Diabetes", entry_path="C/000313")
    bundle = extract_entry_bundle(archive, "C/000313", content_processor=cp)
    titles = [s["title"] for s in bundle["sections"]]
    assert titles == ["Type 2 Diabetes", "Causes"]
    assert "Stay Connected" not in titles
    assert "MedlinePlus Trusted Health Information" not in titles


# --------------------------------------------------------------------------
# #5 get_related_articles — links exclude nav/header/footer chrome
# --------------------------------------------------------------------------


def test_bundle_internal_links_exclude_nav(cp: ContentProcessor) -> None:
    archive = _make_archive(ZIMIT_HTML, title="Type 2 Diabetes", entry_path="C/000313")
    bundle = extract_entry_bundle(archive, "C/000313", content_processor=cp)
    urls = [link["url"] for link in bundle["links"]["internal"]]
    # Real in-article cross-references are kept.
    assert any("ency/article/000305.htm" in u for u in urls)
    # Header/footer navigation links are gone.
    assert not any("healthtopics.html" in u for u in urls)
    assert not any("about/" in u for u in urls)
    assert not any(u.endswith("index.html") for u in urls)


def test_bundle_links_preserved_without_landmark(cp: ContentProcessor) -> None:
    # Fallback path: a page with no landmark keeps its links (no regression).
    archive = _make_archive(PLAIN_HTML, title="Berlin", entry_path="A/Berlin")
    bundle = extract_entry_bundle(archive, "A/Berlin", content_processor=cp)
    urls = [link["url"] for link in bundle["links"]["internal"]]
    assert any("Spree_River" in u for u in urls)


# --------------------------------------------------------------------------
# #4 search snippet — drawn from main content, not chrome
# --------------------------------------------------------------------------


def test_entry_snippet_excludes_chrome(tmp_path) -> None:
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import (
        CacheConfig,
        ContentConfig,
        LoggingConfig,
        OpenZimMcpConfig,
    )
    from openzim_mcp.security import PathValidator
    from openzim_mcp.zim_operations import ZimOperations

    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=True, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=10000, snippet_length=200),
        logging=LoggingConfig(level="WARNING"),
    )
    ops = ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(),
    )
    item = MagicMock()
    item.content = ZIMIT_HTML.encode("utf-8")
    item.mimetype = "text/html"
    entry = MagicMock()
    entry.title = "Type 2 Diabetes"
    entry.get_item.return_value = item

    # No query (or a query whose term lives only outside the body) falls back
    # to the leading paragraphs — which, before the fix, are the federal
    # banner + header nav rather than the article lead.
    snippet = ops._get_entry_snippet(entry, query=None)
    assert "Type 2 diabetes is a long-term" in snippet
    assert "official website" not in snippet
    assert "Health Topics" not in snippet
    assert "Stay Connected" not in snippet


# --------------------------------------------------------------------------
# #8 filtered search — dedupe query-string URL variants by canonical path
# --------------------------------------------------------------------------


def test_canonical_result_path_strips_query_and_fragment() -> None:
    from openzim_mcp.zim.search import canonical_result_path

    assert canonical_result_path("a/b/quiz.htm?quiz=1") == "a/b/quiz.htm"
    assert canonical_result_path("a/b/quiz.htm#frag") == "a/b/quiz.htm"
    assert canonical_result_path("a/b/quiz.htm?x=1#frag") == "a/b/quiz.htm"
    assert canonical_result_path("a/b/quiz.htm") == "a/b/quiz.htm"


def test_filtered_scan_dedupes_query_variants(tmp_path) -> None:
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
    from openzim_mcp.security import PathValidator
    from openzim_mcp.zim_operations import ZimOperations

    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
    )
    ops = ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(),
    )

    # warc2zim surfaces each quiz page twice: bare + ?quiz=1.
    entry_ids = [
        "C/quiz/001214_3.htm",
        "C/quiz/001214_3.htm?quiz=1",
        "C/quiz/000249_49.htm",
        "C/quiz/000249_49.htm?quiz=1",
        "C/quiz/007617_46.htm",
    ]

    def _entry_for(eid):
        e = MagicMock()
        e.path = eid
        e.title = eid.rsplit("/", 1)[-1]
        e.get_item.return_value = MagicMock(mimetype="text/html")
        return e

    archive = MagicMock()
    archive.has_new_namespace_scheme = False
    archive.get_entry_by_path.side_effect = _entry_for

    search = MagicMock()
    search.getResults.side_effect = lambda start, count: entry_ids[
        start : start + count
    ]

    page, _scan = ops._scan_filtered_search(
        archive,
        search,
        total_results=len(entry_ids),
        namespace=None,
        content_type=None,
        limit=10,
        offset=0,
    )
    paths = [m[0] for m in page]
    from openzim_mcp.zim.search import canonical_result_path

    canon = [canonical_result_path(p) for p in paths]
    assert len(canon) == len(set(canon)), f"duplicate canonical paths: {paths}"
    assert len(page) == 3  # three distinct quiz pages, variants collapsed


# --------------------------------------------------------------------------
# Pass-7: select_main_content robustness (empty landmark, precedence)
# --------------------------------------------------------------------------


def test_select_main_content_skips_empty_landmark() -> None:
    """An empty/whitespace-only landmark must not be chosen over real content
    elsewhere; the helper falls back rather than dropping the body."""
    from bs4 import BeautifulSoup

    from openzim_mcp.content_processor import select_main_content

    # The only landmark (<main>) is empty; real content sits in a body
    # sibling. Selecting the empty landmark would drop all content.
    html = "<body><main>   </main><p>The real article body lives here.</p></body>"
    soup = BeautifulSoup(html, "html.parser")
    node = select_main_content(soup)
    assert "The real article body lives here." in node.get_text()


def test_select_main_content_prefers_article_over_broad_role_main() -> None:
    """When [role=main] wraps both <article> and an <aside> sidebar, the
    single <article> (narrower) should win so the sidebar is excluded."""
    from bs4 import BeautifulSoup

    from openzim_mcp.content_processor import select_main_content

    html = (
        "<body><div role='main'>"
        "<article><p>The real article prose.</p></article>"
        "<aside><p>Sidebar navigation junk.</p></aside>"
        "</div></body>"
    )
    soup = BeautifulSoup(html, "html.parser")
    text = select_main_content(soup).get_text()
    assert "The real article prose." in text
    assert "Sidebar navigation junk." not in text


# --------------------------------------------------------------------------
# Pass-7 / C: entry-content fetch (get_zim_entry / get_entries) scoping
# --------------------------------------------------------------------------


def test_process_mime_content_scope_main_content(cp: ContentProcessor) -> None:
    scoped = cp.process_mime_content(
        ZIMIT_HTML.encode("utf-8"), "text/html", compact=True, scope_main_content=True
    )
    full = cp.process_mime_content(
        ZIMIT_HTML.encode("utf-8"), "text/html", compact=True, scope_main_content=False
    )
    assert "Type 2 diabetes is a long-term" in scoped
    assert "official website" not in scoped
    assert "Stay Connected" not in scoped
    # Default (False) is unchanged: full-page chrome still present.
    assert "official website" in full


def test_get_zim_entry_scopes_to_main_content(tmp_path) -> None:
    """get_zim_entry returns article content, not site chrome, for an entry
    wrapped in a main-content landmark."""
    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import CacheConfig, ContentConfig, OpenZimMcpConfig
    from openzim_mcp.security import PathValidator
    from openzim_mcp.zim_operations import ZimOperations

    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=100000, snippet_length=200),
    )
    ops = ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(),
    )
    out = ops._get_zim_entry_from_archive(
        _make_archive(ZIMIT_HTML, title="Type 2 Diabetes", entry_path="C/000313"),
        tmp_path / "x.zim",
        "C/000313",
        100000,
        0,
    )
    assert "Type 2 diabetes is a long-term" in out
    assert "official website" not in out
    assert "Stay Connected" not in out


# --------------------------------------------------------------------------
# Pass-7 / E: heading offset matching tolerates html2text escaping (#6 root)
# --------------------------------------------------------------------------


def test_bundle_locates_html2text_escaped_numbered_headings(
    cp: ContentProcessor,
) -> None:
    """IEP-style numbered headings (<h2><strong>1. X</strong></h2>) render via
    html2text as '## **1\\. X**' (bold + backslash-escaped period). The
    section-offset matcher must still locate them, otherwise the H2 sections
    are silently dropped and their H3 children misnest under the H1 (beta #6)."""
    numbered = (
        "<body><article>"
        "<h1>Doc</h1><p>lead paragraph</p>"
        "<h2><strong>1. First Section</strong></h2><p>alpha body</p>"
        "<h3>a. A Subsection</h3><p>sub body</p>"
        "<h2>2. Second Section</h2><p>beta body</p>"
        "</article></body>"
    )
    archive = _make_archive(numbered, title="Doc", entry_path="C/doc")
    bundle = extract_entry_bundle(archive, "C/doc", content_processor=cp)
    secs = {s["title"]: s for s in bundle["sections"]}
    assert "1. First Section" in secs
    assert "2. Second Section" in secs
    # The H3 nests under its H2 parent, not the H1 — the #6 fix.
    assert secs["a. A Subsection"]["parent_id"] == secs["1. First Section"]["id"]


# --------------------------------------------------------------------------
# Deferred defect: MedlinePlus in-<article> furniture sections
#
# MedlinePlus pages carry boilerplate sections ("Test Your Knowledge",
# "Related Issues", ...) INSIDE the <article> landmark, so the landmark
# scoping above does not remove them. A heading-text denylist (exact,
# normalized, landmark-gated) drops a furniture heading and its content up to
# the next same-or-higher-level heading, while a legitimately-titled section
# whose heading merely CONTAINS a denylisted phrase must survive.
# --------------------------------------------------------------------------

# Real article lead + a legitimate generic-medical section ("Symptoms"), then
# furniture: "Test Your Knowledge" (with an h3 child quiz item) and
# "Related Issues". The adversarial "Learn More About Appendicitis" heading
# CONTAINS the denylisted phrase "learn more" but is a real section and must
# be kept — proving exact-match, not substring.
MED_FURNITURE_HTML = """\
<html><body>
<article>
  <h1>Appendicitis</h1>
  <p>Appendicitis is inflammation of the appendix, a small pouch attached to
  the large intestine, and is a common cause of acute abdominal pain.</p>
  <h2>Symptoms</h2>
  <p>The classic presentation is pain that begins near the navel and later
  shifts to the lower right abdomen, often with nausea and a low fever.</p>
  <h2>Test Your Knowledge</h2>
  <p>Take this quiz to see how much you have learned about appendicitis.</p>
  <h3>Quiz Question 1</h3>
  <p>Where does appendicitis pain usually start?</p>
  <h2>Related Issues</h2>
  <ul><li><a href="ency/article/000256.htm">Abdominal pain</a></li></ul>
  <h2>Learn More About Appendicitis</h2>
  <p>Surgery to remove the appendix, called an appendectomy, is the standard
  treatment and is usually performed promptly.</p>
</article>
</body></html>
"""


def test_strip_furniture_sections_removes_denylisted_heading_and_its_extent() -> None:
    """A denylisted heading takes its content + deeper sub-headings, stopping
    at the next same-or-higher-level heading."""
    from bs4 import BeautifulSoup

    from openzim_mcp.content_processor import _strip_furniture_sections

    soup = BeautifulSoup(MED_FURNITURE_HTML, "html.parser")
    _strip_furniture_sections(soup)
    headings = [h.get_text().strip() for h in soup.find_all(["h1", "h2", "h3"])]
    # Furniture headings (and the quiz h3 nested under "Test Your Knowledge")
    # are gone; legit headings — including the adversarial superset — stay.
    assert headings == [
        "Appendicitis",
        "Symptoms",
        "Learn More About Appendicitis",
    ]
    text = soup.get_text()
    assert "Take this quiz" not in text
    assert "Quiz Question 1" not in text
    assert "Abdominal pain" not in text
    # Legit prose either side of the furniture is untouched.
    assert "inflammation of the appendix" in text
    assert "begins near the navel" in text
    assert "called an appendectomy" in text


def test_bundle_excludes_medlineplus_furniture(cp: ContentProcessor) -> None:
    archive = _make_archive(
        MED_FURNITURE_HTML, title="Appendicitis", entry_path="C/000256"
    )
    bundle = extract_entry_bundle(archive, "C/000256", content_processor=cp)
    titles = [s["title"] for s in bundle["sections"]]
    assert titles == ["Appendicitis", "Symptoms", "Learn More About Appendicitis"]
    md = bundle["rendered_markdown"]
    assert "inflammation of the appendix" in md
    assert "begins near the navel" in md
    assert "Take this quiz" not in md
    assert "Quiz Question 1" not in md
    # Furniture links are dropped with their section.
    urls = [link["url"] for link in bundle["links"]["internal"]]
    assert not any("000256.htm" in u for u in urls)


def test_furniture_strip_not_applied_without_landmark(cp: ContentProcessor) -> None:
    """No main-content landmark -> whole-document fallback -> the denylist must
    never fire, so non-ZIMIT pages stay byte-identical."""
    furniture_no_landmark = (
        "<html><body>"
        "<h1>Quiz Trivia</h1><p>real lead</p>"
        "<h2>Test Your Knowledge</h2><p>this content must survive</p>"
        "</body></html>"
    )
    archive = _make_archive(
        furniture_no_landmark, title="Quiz Trivia", entry_path="A/Quiz"
    )
    bundle = extract_entry_bundle(archive, "A/Quiz", content_processor=cp)
    titles = [s["title"] for s in bundle["sections"]]
    assert "Test Your Knowledge" in titles
    assert "this content must survive" in bundle["rendered_markdown"]
