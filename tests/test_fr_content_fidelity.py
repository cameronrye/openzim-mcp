"""Field-report fixes: content-extraction fidelity on real, messy archives.

Every test here drives a real object end to end (``ZimOperations`` over a
mock archive, or ``ContentProcessor`` on real markup) and asserts on the
RENDERED output, never on a renderer called with a hand-picked kwarg.

Covered findings:

* 114 — furniture-heading strip deleted the heading but kept its body when
  the heading was wrapped in its own block (MedlinePlus), silently merging
  site furniture into the preceding real section.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations


def _stub_entry(path: str, title: str, html: str, mime: str) -> Any:
    item = MagicMock()
    item.content = html.encode("utf-8")
    item.mimetype = mime
    entry = MagicMock()
    entry.title = title
    entry.path = path
    entry.is_redirect = False
    entry.get_item.return_value = item
    return entry


def _make_archive(
    html: str,
    *,
    title: str,
    entry_path: str,
    mime: str = "text/html",
    uuid: str = "u-test",
) -> Any:
    """Minimal libzim ``Archive`` mock serving one non-redirect entry.

    Any OTHER path resolves to a distinct empty stub whose ``path`` echoes
    the request, so link-target canonicalization behaves like a real archive
    instead of folding every target back onto the source entry.
    """
    main = _stub_entry(entry_path, title, html, mime)

    def _get(path: str) -> Any:
        if path == entry_path:
            return main
        return _stub_entry(path, f"Title of {path}", "<html><body></body></html>", mime)

    archive = MagicMock()
    archive.uuid = uuid
    archive.get_entry_by_path.side_effect = _get
    archive.has_entry_by_path.return_value = True
    return archive


@pytest.fixture
def ops(tmp_path: Path) -> ZimOperations:
    zim = tmp_path / "test.zim"
    zim.touch()
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=50, ttl_seconds=300),
        content=ContentConfig(max_content_length=100_000, snippet_length=200),
        logging=LoggingConfig(level="ERROR"),
    )
    return ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache, enable_background_cleanup=False),
        ContentProcessor(snippet_length=200),
    )


# ---------------------------------------------------------------------------
# 114 — wrapped furniture headings
# ---------------------------------------------------------------------------

# The real MedlinePlus topic-page shape: every <h2> is buried under
# <section><div.section><div.section-header><div.section-title>, and the
# section BODY is an aunt node, not a sibling of the heading. Verified
# against medlineplus.gov/asthma.html in
# medlineplus.gov_en_all_2025-01.zim (h2 "Patient Handouts" ->
# div.section-title -> div.section-header -> div.section ->
# section#cat_69_section -> div.main -> article).
MEDLINEPLUS_WRAPPED_HTML = """\
<html><body>
<div id="topic">
<article>
  <div class="main">
    <h1>Asthma</h1>
    <p>Asthma is a chronic disease that affects your airways.</p>
    <section id="cat_23_section">
      <div class="section">
        <div class="section-header"><div class="section-title">
          <h2>Older Adults</h2>
        </div></div>
        <div class="section-body">
          <ul class="withtabs">
            <li><a href="https://www.aaaai.org/conditions">Medications and Older Adults</a></li>
          </ul>
        </div>
      </div>
    </section>
    <section id="cat_69_section">
      <div class="section">
        <div class="section-header"><div class="section-title">
          <h2>Patient Handouts</h2>
        </div></div>
        <div class="section-body">
          <ul class="withtabs">
            <li><a href="ency/article/000512.htm">Allergies, asthma, and dust</a></li>
            <li><a href="ency/patientinstructions/000064.htm">How to use a nebulizer</a></li>
          </ul>
        </div>
      </div>
    </section>
  </div>
</article>
</div>
</body></html>
"""


def _wrapped_archive() -> Any:
    return _make_archive(
        MEDLINEPLUS_WRAPPED_HTML, title="Asthma", entry_path="C/asthma"
    )


def test_wrapped_furniture_body_is_not_merged_into_preceding_section(
    ops: ZimOperations, tmp_path: Path
) -> None:
    """f114: zim_get_section('older-adults') must return ONLY that section.

    Before the fix the ``Patient Handouts`` <h2> was decomposed while its
    body survived, so the handout list was re-attributed to the preceding
    real section and served under its title.
    """
    zim_path = str(tmp_path / "test.zim")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = _wrapped_archive()
        response = ops.get_section_data(zim_path, "C/asthma", section_id="older-adults")

    assert response.get("error") is not True, response
    body = response["content_markdown"]
    assert response["section_title"] == "Older Adults"
    # Positive: the section's own content is still served.
    assert "Medications and Older Adults" in body
    # Negative: the furniture section's body must not be inside it.
    assert "How to use a nebulizer" not in body
    assert "Allergies, asthma, and dust" not in body


def test_wrapped_furniture_section_is_removed_from_the_rendered_body(
    ops: ZimOperations, tmp_path: Path
) -> None:
    """f114: the same removal, observed through ``zim_get(view='full')``."""
    zim_path = str(tmp_path / "test.zim")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = _wrapped_archive()
        result = ops.get_zim_entry_data(zim_path, "C/asthma")

    content = result["content"]
    # Positive: real article content survives, headings and all.
    assert "chronic disease that affects your airways" in content
    assert "Older Adults" in content
    assert "Medications and Older Adults" in content
    # Negative: the furniture heading AND its body are gone.
    assert "Patient Handouts" not in content
    assert "How to use a nebulizer" not in content
    assert "ency/patientinstructions/000064.htm" not in content


# ---------------------------------------------------------------------------
# 88 — ``about:`` hrefs classified as internal article links
# ---------------------------------------------------------------------------

# warc2zim/browsertrix rewrites an unarchived link to <a href="about:blank">,
# keeping the original URL as the anchor text. Observed on
# iep.utm.edu/hazlitt/ and iep.utm.edu/locke-ep/ in
# internet-encyclopedia-philosophy_en_all_2025-06.zim.
ABOUT_BLANK_HTML = """\
<html><body>
<article>
  <h1>William Hazlitt</h1>
  <p>Hazlitt was an English essayist.</p>
  <p>See <a href="about:blank">http://www.blupete.com/Hazlitt.htm</a>
  and <a href="../schopenhauer/">Schopenhauer</a>.</p>
</article>
</body></html>
"""


def test_about_blank_href_is_not_an_internal_link(
    ops: ZimOperations, tmp_path: Path
) -> None:
    """f88: ``about:`` is a non-navigable scheme, not an entry path.

    It used to be joined onto the source directory, fabricating
    ``iep.utm.edu/hazlitt/about:blank`` — a path ``zim_get`` cannot fetch,
    which then out-ranked every real neighbour in ``direction="related"``.
    """
    zim_path = str(tmp_path / "test.zim")
    archive = _make_archive(
        ABOUT_BLANK_HTML, title="William Hazlitt", entry_path="iep.utm.edu/hazlitt/"
    )
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        response = ops.extract_article_links_data(
            zim_path, "iep.utm.edu/hazlitt/", kind="internal", limit=100
        )

    urls = [row["url"] for row in response["results"]]
    paths = [row.get("path") for row in response["results"]]
    # Positive: the real relative link is still extracted.
    assert "../schopenhauer/" in urls
    # Negative: the rewrite artifact is dropped, and no path is fabricated
    # from it.
    assert "about:blank" not in urls
    assert not any(p and "about:" in p for p in paths)
    assert response["category_totals"]["internal"] == 1


# ---------------------------------------------------------------------------
# 97 — leading-slash entry_path accepted by zim_get, rejected by the
#      structure surfaces as "the ZIM file may be corrupted"
# ---------------------------------------------------------------------------

SLASH_HTML = """\
<html><body>
<article>
  <h1>Stoicism</h1>
  <p>Stoicism was a school of Hellenistic philosophy.</p>
  <h2>Physics</h2>
  <p>The Stoics held that the cosmos is a single living being.</p>
  <p>See <a href="../seneca/">Seneca</a>.</p>
</article>
</body></html>
"""


def _slash_archive() -> Any:
    return _make_archive(
        SLASH_HTML, title="Stoicism", entry_path="iep.utm.edu/stoicism/"
    )


@pytest.mark.parametrize(
    "call",
    [
        "toc",
        "structure",
        "section",
        "links",
    ],
)
def test_leading_slash_entry_path_is_normalized_on_structure_surfaces(
    ops: ZimOperations, tmp_path: Path, call: str
) -> None:
    """f97: ``/iep.utm.edu/stoicism/`` must behave like the un-slashed path.

    ``zim_get`` already normalized it (``normalize_entry_path``); the six
    ``reject_path_traversal`` boundaries in ``zim/structure.py`` did not, so
    the same argument that served a body answered TOC/structure/section/links
    with an "Archive Operation Error — the ZIM file may be corrupted"
    envelope naming ``<path-hidden>``.
    """
    zim_path = str(tmp_path / "test.zim")
    slashed = "/iep.utm.edu/stoicism/"
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = _slash_archive()
        if call == "toc":
            got: Any = ops.get_table_of_contents_data(zim_path, slashed)
            assert got["heading_count"] == 2
            assert got["toc"][0]["text"] == "Stoicism"
        elif call == "structure":
            got = ops.get_article_structure_data(zim_path, slashed)
            assert [h["text"] for h in got["headings"]] == ["Stoicism", "Physics"]
        elif call == "section":
            got = ops.get_section_data(zim_path, slashed, section_id="physics")
            assert got.get("error") is not True, got
            assert "single living being" in got["content_markdown"]
        else:
            got = ops.extract_article_links_data(
                zim_path, slashed, kind="internal", limit=10
            )
            assert [row["url"] for row in got["results"]] == ["../seneca/"]

    # Negative: none of them returns the archive-corruption envelope.
    assert got.get("error") is not True, got


def test_leading_slash_still_rejects_a_traversal_segment(
    ops: ZimOperations, tmp_path: Path
) -> None:
    """f97 guard: normalizing the leading ``/`` must not loosen the guard."""
    from openzim_mcp.exceptions import OpenZimMcpArchiveError

    zim_path = str(tmp_path / "test.zim")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = _slash_archive()
        with pytest.raises(OpenZimMcpArchiveError):
            ops.get_table_of_contents_data(zim_path, "/../secret")


# ---------------------------------------------------------------------------
# 87 — direction="related" reported the truncated page size as ``total``
# ---------------------------------------------------------------------------

MANY_NEIGHBOURS_HTML = """\
<html><body>
<article>
  <h1>Locke: Epistemology</h1>
  <p>Locke's epistemology is empiricist.</p>
  <p>
    <a href="../locke/">Locke</a>
    <a href="../rene-descartes/">Descartes</a>
    <a href="../plato/">Plato</a>
    <a href="../hume/">Hume</a>
    <a href="../berkeley/">Berkeley</a>
  </p>
</article>
</body></html>
"""


def test_related_total_counts_every_neighbour_not_just_the_page(
    ops: ZimOperations, tmp_path: Path
) -> None:
    """f87: ``total``/``done`` must describe the full ranked neighbour set.

    They used to be ``len(results)`` and ``True``, so a caller that asked for
    10 of 221 neighbours was told it had them all — with no cursor and no
    truncation flag, the remaining 211 were unreachable and invisible.
    """
    zim_path = str(tmp_path / "test.zim")
    archive = _make_archive(
        MANY_NEIGHBOURS_HTML, title="Locke: Epistemology", entry_path="iep/locke-ep/"
    )
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        capped = ops.get_related_articles_data(zim_path, "iep/locke-ep/", limit=2)
        full = ops.get_related_articles_data(zim_path, "iep/locke-ep/", limit=10)

    # Positive: an uncapped call is complete and says so.
    assert len(full["results"]) == 5
    assert full["total"] == 5
    assert full["done"] is True
    # Negative: a capped call must not claim completeness.
    assert len(capped["results"]) == 2
    assert capped["total"] == 5
    assert capped["done"] is False
    assert capped["page_info"]["returned_count"] == 2


# ---------------------------------------------------------------------------
# 19 — zim_get_section accepted only opaque ids, and its miss listed bare ids
# ---------------------------------------------------------------------------

# warc2zim gives scholarly-site headings machine anchors (SH5b, SSH2gii),
# so the human-meaningful handle is the only one a model can generate.
# Shape taken from iep.utm.edu/kantview/.
ANCHOR_ID_HTML = """\
<html><body>
<article>
  <h1 id="immanuel-kant">Immanuel Kant</h1>
  <p>Kant was a German philosopher.</p>
  <h2 id="H5">Kant's Ethics</h2>
  <p>Kant grounded morality in reason.</p>
  <h3 id="SH5b">b. The Categorical Imperative</h3>
  <p>Act only according to that maxim whereby you can will it a law.</p>
  <h3 id="SH5c">c. The Kingdom of Ends</h3>
  <p>Every rational being is a legislating member.</p>
</article>
</body></html>
"""


def _kant_archive() -> Any:
    return _make_archive(
        ANCHOR_ID_HTML, title="Immanuel Kant", entry_path="iep.utm.edu/kantview/"
    )


@pytest.mark.parametrize(
    "asked",
    ["b. The Categorical Imperative", "the categorical imperative"],
)
def test_get_section_accepts_a_heading_title(
    ops: ZimOperations, tmp_path: Path, asked: str
) -> None:
    """f19: a heading title resolves to its section, like it does in simple mode.

    ``bundle["sections"]`` already carries ``title`` beside ``id``; only the
    id was ever consulted, so a title-shaped ``section_id`` produced 37 bare
    anchor slugs and an 8.4 KB ``view='toc'`` round trip to recover from.
    """
    zim_path = str(tmp_path / "test.zim")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = _kant_archive()
        got = ops.get_section_data(zim_path, "iep.utm.edu/kantview/", section_id=asked)

    assert got.get("error") is not True, got
    # The canonical id is echoed back, so the caller learns the real handle.
    assert got["section_id"] == "SH5b"
    assert got["section_title"] == "b. The Categorical Imperative"
    assert "whereby you can will it a law" in got["content_markdown"]
    # Negative: it must not have matched the neighbouring section instead.
    assert "legislating member" not in got["content_markdown"]


def test_section_not_found_lists_titles_beside_ids(
    ops: ZimOperations, tmp_path: Path
) -> None:
    """f19: the miss envelope must be self-recovering in one call."""
    zim_path = str(tmp_path / "test.zim")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = _kant_archive()
        got = ops.get_section_data(
            zim_path, "iep.utm.edu/kantview/", section_id="Transcendental Aesthetic"
        )

    assert got.get("error") is True, got
    assert got["operation"] == "section_not_found"
    # Positive: id+title pairs, so a model can pick without a second call.
    assert {"id": "SH5b", "title": "b. The Categorical Imperative"} in got[
        "available_sections"
    ]
    # The legacy id-only key is kept for existing clients.
    assert "SH5b" in got["available_section_ids"]
    # Negative: the message must not still claim ids are the only handle.
    assert "heading title" in got["message"]


# ---------------------------------------------------------------------------
# 116 — view="summary" collapsed every newline whenever it truncated
# ---------------------------------------------------------------------------

LONG_SUMMARY_HTML = (
    "<html><body><article>"
    "<h1>Diabetes</h1>"
    "<h2>Summary</h2>"
    "<h3>What is diabetes?</h3>"
    "<p>" + " ".join(f"word{i}" for i in range(60)) + "</p>"
    "<h3>What are the types of diabetes?</h3>"
    "<ul><li>Type 1 diabetes.</li><li>Type 2 diabetes.</li></ul>"
    "<p>" + " ".join(f"tail{i}" for i in range(60)) + "</p>"
    "</article></body></html>"
)


def test_truncated_summary_keeps_its_line_structure(
    ops: ZimOperations, tmp_path: Path
) -> None:
    """f116: a truncated summary must stay readable markdown.

    ``" ".join(words[:max_words])`` destroyed every newline, so the common
    case (any article long enough to need a summary) rendered as one blob
    with ``##``/``###``/``*`` markers stranded mid-sentence.
    """
    zim_path = str(tmp_path / "test.zim")
    archive = _make_archive(
        LONG_SUMMARY_HTML, title="Diabetes", entry_path="C/diabetes"
    )
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        got = ops.get_entry_summary_data(zim_path, "C/diabetes", max_words=40)

    summary = got["summary"]
    # Positive: it really did truncate, and the word budget is honoured.
    assert got["is_truncated"] is True
    assert got["word_count"] == 40
    assert len(summary.split()) == 40
    # Negative: the newlines that make it markdown are still there, so a
    # heading marker still opens its own line.
    assert "\n" in summary
    assert any(line.startswith("#") for line in summary.splitlines())
    assert "# Diabetes ## Summary" not in summary


# ---------------------------------------------------------------------------
# 72 — snippets on list-shaped index pages never reached the query term
# ---------------------------------------------------------------------------


def _drug_index_html() -> str:
    """A MedlinePlus-style alphabetical brand-name index.

    html2text renders the whole ``<ul>`` as one blank-line-free block, so the
    anchor pass correctly selects it and then the hard cut lands long before
    the first "aspirin" — the shape of medlineplus.gov/druginfo/drug_Aa.html
    (49,532 chars, 55 hits, the first at char 4,834).
    """
    rows = [f"<li>Brand Name Product Number {i} Suspension</li>" for i in range(40)]
    rows.append("<li>Bayer Aspirin Regimen tablets</li>")
    rows += [f"<li>Other Product Number {i} Tablets</li>" for i in range(40)]
    return "<html><body><article><h1>Drugs, Herbs and Supplements: Aa</h1><ul>{}</ul></article></body></html>".format(
        "".join(rows)
    )


def test_snippet_on_a_list_page_reaches_the_query_term(
    ops: ZimOperations, tmp_path: Path
) -> None:
    """f72: a snippet must explain its match or be short — not neither.

    The selected block is a single 3 KB+ list with no blank line, so the
    hard cut at ``snippet_length`` returned the head of the alphabet and
    zero highlights: 47% of one real search response was two such snippets.
    """
    entry = _stub_entry("C/drug_Aa", "Drugs: Aa", _drug_index_html(), "text/html")
    snippet = ops._get_entry_snippet(entry, query="aspirin")

    # Sanity: the fixture really does hide the term past the snippet cap.
    rendered = ops.content_processor.process_mime_content(
        _drug_index_html().encode("utf-8"), "text/html", compact=True
    )
    assert rendered.lower().index("aspirin", 40) > ops.content_processor.snippet_length

    # Positive: the snippet carries the term, highlighted.
    assert "aspirin" in snippet.lower()
    assert "**" in snippet
    # Negative: it did not just return the head of the list.
    assert not snippet.startswith("  * Brand Name Product Number 0")


# ---------------------------------------------------------------------------
# 119 — text/* passthrough dumped stylesheets and scripts verbatim
# ---------------------------------------------------------------------------

BIG_CSS = '@charset "UTF-8";.vjs-modal{' + "x" * 4000 + "}"


@pytest.mark.parametrize(
    ("mime", "word"),
    [("text/css", "Stylesheet"), ("text/javascript", "Script")],
)
def test_stylesheets_and_scripts_get_a_placeholder_not_a_dump(
    ops: ZimOperations, tmp_path: Path, mime: str, word: str
) -> None:
    """f119: 47 KB / ~19k estimated tokens of minified CSS is not content.

    ``mime_type.startswith("text/")`` returned the file verbatim — including
    a base64 ``data:application/font-woff`` blob — with ``truncated: false``,
    while image/* and application/pdf already returned one-line placeholders.
    """
    zim_path = str(tmp_path / "test.zim")
    archive = _make_archive(
        BIG_CSS, title="videojs.css", entry_path="C/css/videojs.css", mime=mime
    )
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        got = ops.get_zim_entry_data(zim_path, "C/css/videojs.css")

    content = got["content"]
    # Positive: the caller is told what it is, how big, and how to get bytes.
    assert word in content
    assert mime in content
    assert "binary=True" in content or "binary content" in content
    assert len(content) < 200
    # Negative: the file itself is gone.
    assert "@charset" not in content
    assert "xxxxxxxxxx" not in content


def test_plain_text_and_subtitles_still_pass_through(
    ops: ZimOperations, tmp_path: Path
) -> None:
    """f119 guard: only stylesheets/scripts are placeheld, not all text/*."""
    zim_path = str(tmp_path / "test.zim")
    vtt = "WEBVTT\n\n00:00.000 --> 00:02.000\nAsthma affects the airways."
    archive = _make_archive(vtt, title="clip", entry_path="C/clip.vtt", mime="text/vtt")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        got = ops.get_zim_entry_data(zim_path, "C/clip.vtt")

    assert "Asthma affects the airways." in got["content"]
    assert "Stylesheet" not in got["content"]


# ---------------------------------------------------------------------------
# 68 — stopwords consumed the whole snippet-highlight budget
# ---------------------------------------------------------------------------

TROLLEY_HTML = (
    "<html><body><article><h1>Trolley Problem</h1>"
    "<p>The essay begins with the observation that the reader of the "
    "literature on the ethics of killing meets the trolley problem "
    "early, and the problem recurs.</p>"
    "</article></body></html>"
)


def test_content_words_get_highlighted_not_only_articles(
    ops: ZimOperations, tmp_path: Path
) -> None:
    """f68: the five-span budget was spent left to right on ``the``.

    ``max_hits`` was a single global cap, so any question containing an
    article exhausted it on function words before a content term was
    reached — the bolding then said the entry matched on "the".
    """
    import re as _re

    entry = _stub_entry("C/trolley", "Trolley Problem", TROLLEY_HTML, "text/html")
    snippet = ops._get_entry_snippet(entry, query="what is the trolley problem")
    marked = {m.lower() for m in _re.findall(r"\*\*(.+?)\*\*", snippet)}

    # Positive: the words the caller actually asked about are marked.
    assert "trolley" in marked
    assert "problem" in marked
    # Negative: the budget is no longer entirely function words.
    assert marked != {"the"}


# ---------------------------------------------------------------------------
# 89 — inbound on a missing path blamed the sidecar, not the path
# ---------------------------------------------------------------------------


def test_inbound_without_a_sidecar_still_reports_a_bad_path_as_not_found(
    ops: ZimOperations, tmp_path: Path
) -> None:
    """f89: a typo and a valid path got byte-identical "build a link-graph".

    The reader open ran before the entry check, so the one error the caller
    could actually act on — "that path is not in this archive" — was masked
    by an operator instruction on every archive without a sidecar.
    """
    from openzim_mcp.exceptions import OpenZimMcpEntryNotFoundError
    from openzim_mcp.linkgraph.reader import LinkGraphUnavailable

    zim_path = str(tmp_path / "test.zim")
    archive = _make_archive(SLASH_HTML, title="Stoicism", entry_path="iep/stoicism/")
    # A path the archive does not hold at all.
    archive.get_entry_by_path.side_effect = KeyError("Cannot find entry")
    archive.has_entry_by_path.return_value = False
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        with pytest.raises(OpenZimMcpEntryNotFoundError):
            ops.get_inbound_links_data(zim_path, "iep/THIS-DOES-NOT-EXIST/")

    # Positive: a path that DOES resolve still gets the sidecar instruction.
    good = _make_archive(SLASH_HTML, title="Stoicism", entry_path="iep/stoicism/")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = good
        with pytest.raises(LinkGraphUnavailable):
            ops.get_inbound_links_data(zim_path, "iep/stoicism/")


# ---------------------------------------------------------------------------
# 94 — inbound/related on a non-article entry returned a bare total:0
# ---------------------------------------------------------------------------


def _build_sidecar(zim_path: Path) -> None:
    from openzim_mcp.linkgraph.builder import build_from_link_stream
    from openzim_mcp.linkgraph.reader import sidecar_path_for

    build_from_link_stream(
        sidecar_path_for(zim_path),
        archive_uuid="u-test",
        link_stream=iter(
            [("iep/stoicism/", [("iep/seneca/", "Seneca")])],
        ),
    )


def test_inbound_on_an_asset_entry_explains_the_empty_result(
    ops: ZimOperations, tmp_path: Path
) -> None:
    """f94: outbound explains itself on a non-HTML entry; inbound did not.

    ``total: 0`` on an image read as "nothing links to this file", when the
    truth is that the graph indexes article-to-article anchors only.
    """
    zim_path = tmp_path / "test.zim"
    _build_sidecar(zim_path)
    archive = _make_archive(
        "binarybytes", title="plato.jpg", entry_path="iep/plato.jpg", mime="image/jpeg"
    )
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        got = ops.get_inbound_links_data(str(zim_path), "iep/plato.jpg")

    assert got["total"] == 0
    # Positive: the payload says why, naming the content type.
    assert "image/jpeg" in got.get("message", "")
    assert "not indexed" in got.get("message", "")


def test_inbound_on_an_article_carries_no_such_message(
    ops: ZimOperations, tmp_path: Path
) -> None:
    """f94 guard: the explanation is for asset entries only."""
    zim_path = tmp_path / "test.zim"
    _build_sidecar(zim_path)
    archive = _make_archive(
        SLASH_HTML, title="Seneca", entry_path="iep/seneca/", mime="text/html"
    )
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        got = ops.get_inbound_links_data(str(zim_path), "iep/seneca/")

    assert got["total"] == 1
    assert "message" not in got


def test_related_on_an_asset_entry_explains_the_empty_result(
    ops: ZimOperations, tmp_path: Path
) -> None:
    """f94: the same gap on ``direction="related"``."""
    zim_path = str(tmp_path / "test.zim")
    archive = _make_archive(
        "binarybytes", title="plato.jpg", entry_path="iep/plato.jpg", mime="image/jpeg"
    )
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        got = ops.get_related_articles_data(zim_path, "iep/plato.jpg")

    assert got["total"] == 0
    assert "image/jpeg" in got.get("message", "")


# ---------------------------------------------------------------------------
# 93 — kind="media" rows usually carried no fetchable ``path``
# ---------------------------------------------------------------------------

MEDIA_HTML = """\
<html><body>
<article>
  <h1>Plato</h1>
  <img src="../media/plato.jpg" alt="Plato bust">
  <img src="https://example.org/remote.png" alt="Remote">
  <p>Plato founded the Academy.</p>
</article>
</body></html>
"""


def test_media_rows_carry_a_fetchable_path(ops: ZimOperations, tmp_path: Path) -> None:
    """f93: the bucket whose whole point is ``zim_get(binary=True)``.

    Only anchor-wrapped assets got a resolved ``path``; a plain ``<img>``
    row shipped the raw document-relative ``src``, so the field was present
    or absent unpredictably page to page within one archive.
    """
    zim_path = str(tmp_path / "test.zim")
    archive = _make_archive(MEDIA_HTML, title="Plato", entry_path="iep/plato/")
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        got = ops.extract_article_links_data(
            zim_path, "iep/plato/", kind="media", limit=10
        )

    by_url = {row["url"]: row for row in got["results"]}
    # Positive: the archive-relative image is now addressable.
    assert by_url["../media/plato.jpg"]["path"] == "iep/media/plato.jpg"
    # Negative: an off-archive URL is left alone — there is no entry to name.
    assert "path" not in by_url["https://example.org/remote.png"]


# ---------------------------------------------------------------------------
# 121 — <br>-stacked table cells rendered as a mismatched pipe table
# ---------------------------------------------------------------------------

# The IEP's conjunction truth table: 2 <tr>, 3 <td>, each cell a <br>-stacked
# column of values — below the replace_oversized_tables thresholds (8 rows /
# 600 chars), so it goes straight to html2text.
TRUTH_TABLE_HTML = """\
<html><body>
<article>
  <h1>Propositional Logic</h1>
  <table>
    <tr><td>&alpha;</td><td>&beta;</td><td>(&alpha; &and; &beta;)</td></tr>
    <tr>
      <td valign="Top"><div>T<br />T<br />F<br />F</div></td>
      <td valign="Top"><div>T<br />F<br />T<br />F</div></td>
      <td valign="Top"><div>T<br />F<br />F<br />F</div></td>
    </tr>
  </table>
</article>
</body></html>
"""


@pytest.mark.parametrize("compact", [True, False])
def test_stacked_truth_table_cells_stay_on_their_row(
    ops: ZimOperations, tmp_path: Path, compact: bool
) -> None:
    """f121: a <br> inside a cell used to split the markdown row.

    html2text turned each 4-value column into four LINES, so a 3-column
    header was followed by one row whose cells each held a newline stack —
    valid-looking markdown that encodes the four logical rows in a way that
    invites a wrong reading. ``_join_cell_text`` already fixed this shape
    for infoboxes ("5th in Europe; 1st in Germany"); the ordinary table path
    never got it.
    """
    zim_path = str(tmp_path / "test.zim")
    archive = _make_archive(
        TRUTH_TABLE_HTML, title="Propositional Logic", entry_path="iep/pl/"
    )
    with patch("openzim_mcp.zim_operations.zim_archive") as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = archive
        got = ops.get_zim_entry_data(zim_path, "iep/pl/", compact=compact)

    content = got["content"]
    row = next(line for line in content.splitlines() if "T; T; F; F" in line)
    # Positive: all three columns are on one line, values separated.
    assert "T; F; T; F" in row
    assert "T; F; F; F" in row
    assert row.count("|") >= 2
    # Negative: no cell's values are split across lines any more.
    assert "\nT  \n" not in content
    assert "\n F  \n" not in content


# ---------------------------------------------------------------------------
# 114's blast radius — audit residue
# ---------------------------------------------------------------------------

# The same wrapped shape, but with real article prose AFTER the furniture
# section instead of before it. On the shipped MedlinePlus pages every
# furniture block sits at the end, which is why a 390-page corpus sweep saw
# no harm — and why nothing tested this.
FURNITURE_FOLLOWED_BY_PROSE = """\
<html><body><article>
  <div class="main">
    <h1>Asthma</h1>
    <p>Asthma is a chronic disease that affects your airways.</p>
    <section id="cat_69_section">
      <div class="section">
        <div class="section-header"><div class="section-title">
          <h2>Patient Handouts</h2>
        </div></div>
        <div class="section-body"><ul><li><a href="x">How to use a nebulizer</a></li></ul></div>
      </div>
    </section>
    <p>REAL PROSE THAT MUST SURVIVE.</p>
    <div class="also"><p>ANOTHER REAL PARAGRAPH.</p></div>
  </div>
</article></body></html>
"""


def test_promoting_a_furniture_wrapper_does_not_eat_what_follows_it() -> None:
    """Audit residue on 114: the promotion widened what gets deleted.

    Before promotion, the extent was the heading plus the heading's own
    siblings — inside ``div.section-title`` that is nothing. After it, the
    extent is the promoted ``<section>`` PLUS every following sibling up to
    the next peer heading — and when the furniture block is not followed by
    one, that is the rest of the article.

    A promoted wrapper already contains the whole section (heading and
    body), which is the entire reason for promoting to it, so the sibling
    walk has nothing left to collect there and only risk to add.

    Measured on the shipped MedlinePlus archive: over 250 wrapped pages the
    walk removed nothing the promotion had not already removed — furniture
    leakage is identical with and without it — while 165 pages recover 29
    characters each and none gets shorter. Those 29 characters are the
    "Learn how to cite this page" footer, i.e. chrome that was being
    deleted as collateral rather than by any rule. Removing chrome by
    accident is not a behaviour worth preserving: the same accident is what
    ate the prose below.
    """
    from openzim_mcp.content_processor import ContentProcessor

    rendered = ContentProcessor().process_mime_content(
        FURNITURE_FOLLOWED_BY_PROSE.encode(), "text/html", scope_main_content=True
    )

    # Positive: the article's own prose is still there, both paragraphs.
    assert "REAL PROSE THAT MUST SURVIVE." in rendered, rendered
    assert "ANOTHER REAL PARAGRAPH." in rendered, rendered
    # Negative: and the furniture it follows is still gone.
    assert "Patient Handouts" not in rendered, rendered
    assert "nebulizer" not in rendered, rendered


def test_the_flat_layout_still_uses_the_sibling_walk() -> None:
    """Control. Where the heading is NOT wrapped, its body really is a set
    of following siblings, and dropping the walk there would leave the
    furniture body behind under the previous section's title — which is the
    defect 114 was filed for."""
    from openzim_mcp.content_processor import ContentProcessor

    flat = (
        "<html><body><article>"
        "<h1>Asthma</h1><p>Lead prose.</p>"
        "<h2>Patient Handouts</h2>"
        "<ul><li><a href='x'>How to use a nebulizer</a></li></ul>"
        "<h2>Diagnosis</h2><p>Real section body.</p>"
        "</article></body></html>"
    )

    rendered = ContentProcessor().process_mime_content(
        flat.encode(), "text/html", scope_main_content=True
    )

    assert "Patient Handouts" not in rendered, rendered
    assert "nebulizer" not in rendered, rendered
    assert "Real section body." in rendered, rendered
    assert "Lead prose." in rendered, rendered
