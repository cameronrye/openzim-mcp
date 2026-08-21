"""v3.0.0 field-defect fixes — content cluster (zim_get bodies, lead extraction).

Each test pins one defect from the 2026-08-19 real-world sweep against the
MedlinePlus / IEP corpora. Fixtures are trimmed copies of the real archive
HTML so the shapes that broke in the field are the shapes under test.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations


@pytest.fixture
def ops(
    test_config: OpenZimMcpConfig,
    path_validator: PathValidator,
    openzim_mcp_cache: OpenZimMcpCache,
    content_processor: ContentProcessor,
) -> ZimOperations:
    return ZimOperations(
        test_config, path_validator, openzim_mcp_cache, content_processor
    )


@pytest.fixture
def zim_file(temp_dir: Path) -> Path:
    """A placeholder file inside the allowed directory; the archive is mocked."""
    path = temp_dir / "corpus.zim"
    path.write_text("x")
    return path


def _html_entry(path: str, title: str, html: str) -> MagicMock:
    entry = MagicMock()
    entry.is_redirect = False
    entry.path = path
    entry.title = title
    item = MagicMock()
    item.mimetype = "text/html"
    item.content = html.encode("utf-8")
    entry.get_item.return_value = item
    return entry


def _archive_with(entries: dict[str, MagicMock]) -> MagicMock:
    """A mock libzim Archive that resolves exactly the given path spellings."""
    inst = MagicMock()
    inst.has_new_namespace_scheme = True

    def _get(path: str) -> MagicMock:
        if path in entries:
            return entries[path]
        raise KeyError("Cannot find entry")

    inst.get_entry_by_path.side_effect = _get
    inst.has_entry_by_path.side_effect = lambda p: p in entries
    return inst


# ---------------------------------------------------------------------------
# D07 — percent-encoded paths served by the archive's own links must resolve
# ---------------------------------------------------------------------------

_IEP_RAW = "iep.utm.edu/gauḍapad/"
_IEP_ENCODED = "iep.utm.edu/gau%E1%B8%8Dapad/"


@patch("openzim_mcp.zim_operations.Archive")
def test_percent_encoded_path_resolves_before_search_fallback(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D07: the IEP G-index links ``../gau%E1%B8%8Dapad/`` exactly as archived;
    libzim stores the raw UTF-8 spelling. Feeding the served link back into
    zim_get must resolve via percent-decoding, not dead-end in not-found."""
    mock_archive.return_value = _archive_with(
        {_IEP_RAW: _html_entry(_IEP_RAW, "Gaudapada", "<h1>Gaudapada</h1><p>x</p>")}
    )
    search = MagicMock(return_value=None)
    with patch.object(ops, "_find_entry_by_search", search):
        result = ops.get_zim_entry_data(str(zim_file), _IEP_ENCODED)

    assert not result.get("error"), result
    assert result["path"] == _IEP_RAW
    assert result["requested_path"] == _IEP_ENCODED
    assert "Gaudapada" in result["content"]
    # The decoded spelling is a cheap exact probe; it must win before the
    # search-based fallback is consulted at all.
    search.assert_not_called()


@patch("openzim_mcp.zim_operations.Archive")
def test_literal_percent_path_is_not_decoded_away(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """warc2zim stores some asset names with a literal ``%``; the raw spelling
    must still be tried first so those keep resolving."""
    literal = "I/Al_Gore%2C_2007.webp"
    mock_archive.return_value = _archive_with(
        {literal: _html_entry(literal, "Al Gore", "<p>photo</p>")}
    )
    result = ops.get_zim_entry_data(str(zim_file), literal)
    assert result["path"] == literal
    assert "requested_path" not in result


# ---------------------------------------------------------------------------
# D08 — not-found guidance must name tools the v3 surface actually exposes
# ---------------------------------------------------------------------------

_STALE_TOOL_NAMES = ("search_zim_file", "browse_namespace")


def _assert_names_real_tools(message: str) -> None:
    for stale in _STALE_TOOL_NAMES:
        assert stale not in message, message
    assert "zim_search" in message or "zim_health" in message, message


@patch("openzim_mcp.zim_operations.Archive")
def test_entry_not_found_guidance_names_real_tools(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D08: the ladder's not-found text pointed at pre-v3 helper names."""
    from openzim_mcp.exceptions import OpenZimMcpArchiveError

    mock_archive.return_value = _archive_with({})
    with patch.object(ops, "_find_entry_by_search", MagicMock(return_value=None)):
        with pytest.raises(OpenZimMcpArchiveError) as exc:
            ops.get_zim_entry_data(str(zim_file), "medlineplus.gov/nope.html")
    _assert_names_real_tools(str(exc.value))
    assert "zim_browse" in str(exc.value)


@patch("openzim_mcp.zim_operations.Archive")
def test_search_fallback_failure_guidance_names_real_tools(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    from openzim_mcp.exceptions import OpenZimMcpArchiveError

    mock_archive.return_value = _archive_with({})
    boom = MagicMock(side_effect=RuntimeError("xapian down"))
    with patch.object(ops, "_find_entry_by_search", boom):
        with pytest.raises(OpenZimMcpArchiveError) as exc:
            ops.get_zim_entry_data(str(zim_file), "medlineplus.gov/nope.html")
    _assert_names_real_tools(str(exc.value))


@patch("openzim_mcp.zim_operations.Archive")
def test_file_level_failure_guidance_names_real_tools(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    from openzim_mcp.exceptions import OpenZimMcpArchiveError

    mock_archive.return_value = _archive_with({})
    with patch.object(ops, "_smart_retrieve_entry", MagicMock(side_effect=ValueError)):
        with pytest.raises(OpenZimMcpArchiveError) as data_exc:
            ops.get_zim_entry_data(str(zim_file), "A/x")
        with pytest.raises(OpenZimMcpArchiveError) as text_exc:
            ops.get_zim_entry(str(zim_file), "A/x")
    _assert_names_real_tools(str(data_exc.value))
    _assert_names_real_tools(str(text_exc.value))


@patch("openzim_mcp.zim_operations.zim_archive")
def test_binary_not_found_guidance_names_real_tools(
    mock_zim_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    from openzim_mcp.exceptions import OpenZimMcpArchiveError

    mock_zim_archive.return_value.__enter__.return_value = _archive_with({})
    with patch.object(ops, "_find_entry_by_search", MagicMock(return_value=None)):
        with pytest.raises(OpenZimMcpArchiveError) as exc:
            ops.get_binary_entry_data(str(zim_file), "I/nope.png")
    _assert_names_real_tools(str(exc.value))


def test_resolve_with_fallback_guidance_names_real_tools(ops: ZimOperations) -> None:
    from openzim_mcp.exceptions import OpenZimMcpArchiveError

    archive = _archive_with({})
    with patch.object(ops, "_find_entry_by_search", MagicMock(return_value=None)):
        with pytest.raises(OpenZimMcpArchiveError) as exc:
            ops._resolve_entry_with_fallback(archive, "A/nope")
    _assert_names_real_tools(str(exc.value))


@patch("openzim_mcp.zim_operations.Archive")
def test_simple_mode_sanitizer_still_strips_reworded_guidance(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """zim_query has no zim_search/zim_browse either; its leak sanitizer must
    keep stripping the backend sentence after the rewording."""
    from openzim_mcp.exceptions import OpenZimMcpArchiveError
    from openzim_mcp.simple_tools import SimpleToolsHandler

    mock_archive.return_value = _archive_with({})
    with patch.object(ops, "_find_entry_by_search", MagicMock(return_value=None)):
        with pytest.raises(OpenZimMcpArchiveError) as exc:
            ops.get_zim_entry_data(str(zim_file), "medlineplus.gov/nope.html")
    stripped = SimpleToolsHandler._BACKEND_API_LEAK_RE.sub("", str(exc.value))
    assert "zim_search" not in stripped
    assert "zim_browse" not in stripped
    assert "Entry not found" in stripped


# ---------------------------------------------------------------------------
# D09 — binary oversize hint must name the knob zim_get actually exposes
# ---------------------------------------------------------------------------


@patch("openzim_mcp.zim_operations.zim_archive")
def test_binary_oversize_message_names_max_content_length(
    mock_zim_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D09: zim_get maps ``max_content_length`` onto the byte cap; the hint
    offered ``include_data`` / ``max_size_bytes``, neither reachable over
    the wire, so following it changed nothing."""
    entry = MagicMock()
    entry.is_redirect = False
    entry.path = "I/big.jpg"
    entry.title = "big"
    item = MagicMock()
    item.mimetype = "image/jpeg"
    item.size = 9944
    item.content = b"x" * 9944
    entry.get_item.return_value = item
    mock_zim_archive.return_value.__enter__.return_value = _archive_with(
        {"I/big.jpg": entry}
    )

    result = ops.get_binary_entry_data(str(zim_file), "I/big.jpg", max_size_bytes=100)

    assert result["truncated"] is True
    message = result["message"]
    assert "max_content_length" in message, message
    assert "include_data" not in message, message
    assert "max_size_bytes" not in message, message
    # The cap the caller hit is still reported so they can size the retry.
    assert "100 B" in message


# ---------------------------------------------------------------------------
# D10 / D11 — main_page must be scoped and capped like a path fetch
# ---------------------------------------------------------------------------

# Trimmed from medlineplus.gov/ (warc2zim): federal banner + skip-nav +
# header menus OUTSIDE <article>, the welcome prose INSIDE it.
_MEDLINEPLUS_HOME_HTML = """\
<html><body>
<a class="usa-skipnav" href="#main">Skip navigation</a>
<section class="usa-banner"><p>An official website of the United States government</p>
<p>Here's how you know</p><p><strong>Official websites use .gov</strong></p></section>
<header><nav><ul><li><a href="healthtopics.html">Health Topics</a></li>
<li><a href="druginfo/">Drugs &amp; Supplements</a></li></ul></nav></header>
<article>
<h1>Welcome to MedlinePlus</h1>
<p>MedlinePlus is an online health information resource for patients and
their families and friends.</p>
<h2>Health Topics</h2>
<p>Find information on health, wellness, disorders and conditions.</p>
</article>
<footer><p>Stay Connected</p></footer>
</body></html>
"""


def _archive_with_main_page(html: str, path: str = "medlineplus.gov/") -> MagicMock:
    entry = _html_entry(path, "MedlinePlus", html)
    inst = _archive_with({path: entry})
    inst.main_entry = entry
    return inst


@patch("openzim_mcp.zim_operations.Archive")
def test_main_page_scopes_site_chrome_like_a_path_fetch(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D10: main_page=True served the banner/skip-nav/menus that fetching the
    identical entry by path already strips; both branches must agree."""
    mock_archive.return_value = _archive_with_main_page(_MEDLINEPLUS_HOME_HTML)

    main = ops.get_main_page_data(str(zim_file))
    by_path = ops.get_zim_entry_data(str(zim_file), "medlineplus.gov/")

    assert "Skip navigation" not in main["content"], main["content"]
    assert "official website" not in main["content"], main["content"]
    assert main["content"].lstrip().startswith("# Welcome to MedlinePlus")
    assert main["content"] == by_path["content"]


@patch("openzim_mcp.zim_operations.Archive")
def test_main_page_honors_max_content_length(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D11: max_content_length was silently ignored on the main_page branch;
    every other unsupported combination on this tool errors loudly."""
    long_html = _MEDLINEPLUS_HOME_HTML.replace(
        "<h2>Health Topics</h2>",
        # ~1.2K chars: above the 200 cap under test, below the branch's
        # 5000-char default so the uncapped control read is NOT truncated.
        "<h2>Health Topics</h2>" + "<p>" + ("lorem ipsum " * 100) + "</p>",
    )
    mock_archive.return_value = _archive_with_main_page(long_html)

    capped = ops.get_main_page_data(str(zim_file), max_content_length=200)
    body, sep, footer = capped["content"].partition("\n\n... [Content truncated")
    assert sep, capped["content"]
    assert len(body) <= 200
    assert capped["_meta"]["truncated"] is True
    assert capped["_meta"]["total_chars"] > 200
    # The footer must not advertise content_offset: the branch never reads it.
    assert "content_offset=" not in footer

    # The cap is part of the response identity — an uncapped call right after
    # must not be served the capped rendering from cache.
    uncapped = ops.get_main_page_data(str(zim_file))
    assert len(uncapped["content"]) > len(capped["content"])
    assert uncapped["_meta"]["truncated"] is False


@pytest.mark.asyncio
async def test_zim_get_forwards_max_content_length_to_main_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool layer dropped max_content_length on the main_page branch."""
    from unittest.mock import AsyncMock

    from openzim_mcp.tools.zim_get import register as register_zim_get

    srv = MagicMock()
    store: dict = {}

    def _tool(*, description: str = ""):
        def decorate(fn):
            store[fn.__name__] = fn
            return fn

        return decorate

    srv.mcp.tool = _tool
    mock_ops = MagicMock()
    mock_ops.get_main_page_data = AsyncMock(return_value={"content": "Welcome"})
    monkeypatch.setattr(
        "openzim_mcp.async_operations.AsyncZimOperations", lambda _ops: mock_ops
    )
    register_zim_get(srv)

    await store["zim_get"](
        zim_file_path="/x.zim", main_page=True, max_content_length=200
    )

    mock_ops.get_main_page_data.assert_awaited_once_with(
        "/x.zim", compact=False, max_content_length=200
    )


# ---------------------------------------------------------------------------
# D12 / D13 — batch items: clean body, and a footer batch mode can act on
# ---------------------------------------------------------------------------

_LONG_ARTICLE_HTML = (
    "<html><body><article><h1>Diabetes</h1><p>"
    + ("Diabetes is a long-term condition in which blood sugar runs high. " * 60)
    + "</p></article></body></html>"
)


@patch("openzim_mcp.zim_operations.Archive")
def test_batch_footer_points_at_single_entry_paging(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D12: batch mode rejects content_offset, yet truncated batch bodies told
    the caller to pass it — unusable advice in the mode that emitted it."""
    path = "medlineplus.gov/diabetes.html"
    mock_archive.return_value = _archive_with(
        {path: _html_entry(path, "Diabetes", _LONG_ARTICLE_HTML)}
    )

    result = ops.get_entries_data(
        [{"zim_file_path": str(zim_file), "entry_path": path}],
        max_content_length=300,
    )

    item = result["results"][0]
    assert item["success"] is True, item
    content = item["content"]
    assert "[Content truncated" in content
    assert "Pass `content_offset=" not in content, content
    # The working recovery: a single-entry call on this path, with the
    # offset where this slice ended (299 here — the boundary space is
    # deferred to the next page, so the hint is not simply the cap).
    assert "single-entry `entry_path` call" in content
    assert "`content_offset=299`" in content


@patch("openzim_mcp.zim_operations.Archive")
def test_batch_item_content_is_the_clean_body(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D13: each batch item embedded the legacy ``# title / Path: / Type: /
    ## Content`` document; the description promises full bodies, and the
    item already carries entry_path."""
    path = "medlineplus.gov/diabetes.html"
    mock_archive.return_value = _archive_with(
        {path: _html_entry(path, "Diabetes", _LONG_ARTICLE_HTML)}
    )

    batch = ops.get_entries_data(
        [{"zim_file_path": str(zim_file), "entry_path": path}],
        max_content_length=300,
    )
    single = ops.get_zim_entry_data(str(zim_file), path, max_content_length=300)

    content = batch["results"][0]["content"]
    assert "## Content" not in content
    assert "\nPath: " not in content
    assert "\nType: " not in content
    # Same body slice as the single-entry branch; only the footer differs.
    batch_body = content.partition("\n\n... [Content truncated")[0]
    single_body = single["content"].partition("\n\n... [Content truncated")[0]
    assert batch_body == single_body
    assert batch_body.startswith("# Diabetes")


# ---------------------------------------------------------------------------
# D14 — view=summary on a MedlinePlus topic page must not spend its budget on
# the in-page "On this page" navigation block
# ---------------------------------------------------------------------------

# Trimmed from medlineplus.gov/measles.html (warc2zim, 2025-01). The in-page
# TOC is NOT a <nav>, has no .toc class, and its group labels are <h3>s, so
# it escaped every existing chrome/furniture strip.
_MEDLINEPLUS_TOPIC_HTML = """\
<html><body>
<a class="usa-skipnav" href="#main">Skip navigation</a>
<header><nav><a href="../healthtopics.html">Health Topics</a></nav></header>
<article>
  <div class="page-info">
    <div class="page-title syndicate">
      <a id="start" name="start"></a>
      <h1 itemprop="name" class="with-also">Measles</h1>
      <span class="alsocalled">Also called: Rubeola</span>
    </div>
    <div class="page-actions"></div>
  </div>
  <div class="main">
    <section id="toc-section">
      <div id="table-of-contents">
        <span class="toc-label">On this page</span>
        <div class="toccolumn">
          <h3>Basics</h3>
          <ul class="bulletlist">
            <li><a title="Go to: Summary" href="#summary">Summary</a></li>
            <li><a title="Go to: Start Here" href="#cat_51">Start Here</a></li>
            <li><a title="Go to: Symptoms" href="#cat_95">Symptoms</a></li>
          </ul>
        </div>
        <div class="toccolumn">
          <h3>Learn More</h3>
          <ul class="bulletlist">
            <li><a title="Go to: Related Issues" href="#cat_47">Related Issues</a></li>
          </ul>
        </div>
        <p class="evencols clearsection hrdividor"></p>
        <div class="toccolumn">
          <h3>For You</h3>
          <ul class="bulletlist">
            <li><a title="Go to: Children" href="#cat_8">Children</a></li>
            <li><a title="Go to: Women" href="#cat_7">Women</a></li>
          </ul>
        </div>
      </div>
    </section>
    <a name="summary"></a>
    <section id="topsum_section">
      <div class="summary-title syndicate"><h2>Summary</h2></div>
      <div id="topic-summary" class="syndicate">
        <p>Measles is an infectious disease caused by a virus. It spreads
        easily from person to person. It causes a blotchy red rash. The rash
        often starts on the head and moves down the body. Other symptoms
        include:</p>
        <ul><li>Fever</li><li>Cough</li><li>Runny nose</li></ul>
        <p>Sometimes measles can lead to serious problems. There is no
        treatment for measles, but the measles-mumps-rubella (MMR) vaccine
        can prevent it.</p>
        <p>"German measles", also known as <a href="rubella.html">rubella</a>,
        is a completely different illness.</p>
        <p class="attribution">Centers for Disease Control and Prevention</p>
      </div>
    </section>
    <a name="cat_51"></a>
    <section id="cat_51_section">
      <div class="section">
        <div class="section-header expanded">
          <div class="section-title syndicate"><h2>Start Here</h2></div>
        </div>
        <div class="section-body">
          <ul class="bulletlist">
            <li><a href="../www.cdc.gov/measles/about/index.html">About Measles</a>
              (Centers for Disease Control and Prevention)</li>
            <li><a href="ency/article/001569.htm">Measles</a> (Medical Encyclopedia)</li>
          </ul>
        </div>
      </div>
    </section>
    <a name="cat_95"></a>
    <section id="cat_95_section">
      <div class="section-title syndicate"><h2>Symptoms</h2></div>
      <ul class="bulletlist">
        <li><a href="../www.cdc.gov/measles/signs-symptoms/">Signs and Symptoms</a></li>
      </ul>
    </section>
  </div>
</article>
<footer><p>Stay Connected</p></footer>
</body></html>
"""

_NAV_MARKERS = ("On this page", "Go to:", "### Basics", "### For You", "* Start Here")


def test_select_main_content_drops_in_page_fragment_nav() -> None:
    from bs4 import BeautifulSoup

    from openzim_mcp.content_processor import HTML_PARSER, select_main_content

    scoped = select_main_content(BeautifulSoup(_MEDLINEPLUS_TOPIC_HTML, HTML_PARSER))
    text = scoped.get_text(" ", strip=True)
    assert "On this page" not in text
    assert "Related Issues" not in text  # lived only in the nav block
    # Real content survives: the summary prose and the sections that follow.
    assert "Measles is an infectious disease" in text
    assert "Start Here" in text
    assert "About Measles" in text


def test_fragment_nav_strip_keeps_mixed_and_list_only_shapes() -> None:
    """Guard rails: a container with any non-fragment link is content, and an
    IEP-style bare <ol> of anchors (no wrapping nav/section/div of its own) is
    left to the furniture pass, not this one."""
    from bs4 import BeautifulSoup

    from openzim_mcp.content_processor import HTML_PARSER, select_main_content

    html = """<html><body><article>
    <h1>Gaudapada</h1>
    <div class="entry-content">
      <p>Gaudapada is one of the early philosophers of the Vedanta school.</p>
      <h3>Table of Contents</h3>
      <ol><li><a href="#H1">Life and Works</a></li><li><a href="#H2">Overview</a></li>
      <li><a href="#H3">Legacy</a></li></ol>
      <div class="see-also"><a href="#H1">top</a><a href="../adv-veda/">Advaita</a>
      <a href="#H2">mid</a></div>
    </div></article></body></html>"""
    text = select_main_content(BeautifulSoup(html, HTML_PARSER)).get_text(
        " ", strip=True
    )
    assert "Table of Contents" in text
    assert "Life and Works" in text
    assert "Advaita" in text
    assert "top" in text


@patch("openzim_mcp.zim_operations.Archive")
def test_summary_view_skips_on_this_page_nav(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D14: ~55 of the 200 summary words were the nav menu; the budget must go
    to the page's own Summary prose."""
    path = "medlineplus.gov/measles.html"
    mock_archive.return_value = _archive_with(
        {
            path: _html_entry(
                path, "Measles | Rubeola | MedlinePlus", _MEDLINEPLUS_TOPIC_HTML
            )
        }
    )

    result = ops.get_entry_summary_data(str(zim_file), path, max_words=60)

    summary = result["summary"]
    for marker in _NAV_MARKERS:
        assert marker not in summary, summary
    assert "Measles is an infectious disease" in summary, summary


# ---------------------------------------------------------------------------
# D15 — <noscript> share-widget boilerplate must not open article bodies
# ---------------------------------------------------------------------------

# Trimmed from medlineplus.gov/ency/article/001214.htm: the no-JS message is
# a <noscript> block INSIDE <article>, directly under the H1, so the main-
# content scoper kept it and it led thousands of encyclopedia / genetics /
# lab-test bodies and their search snippets.
_MEDLINEPLUS_ENCY_HTML = """\
<html><body>
<article><div id="d-article"><div class="page-info"><div class="page-title">
<a name="start" id="start"></a><h1 class="with-also" itemprop="name">Diabetes</h1>
</div><div class="page-actions"></div>
<noscript>
  <span class="js-disabled-message">To use the sharing features on this page, please enable JavaScript.</span>
</noscript></div>
<div class="main"><div id="ency_summary"><p>Diabetes is a long-term (chronic)
disease in which the body cannot regulate the amount of sugar in the blood.</p></div>
<section><div class="section"><div class="section-title"><h2>Causes</h2></div>
<div class="section-body"><p>Insulin is a hormone produced by the pancreas to
control blood sugar.</p></div></div></section></div></div></article>
</body></html>
"""

_NOSCRIPT_JUNK = "To use the sharing features on this page, please enable JavaScript."


@pytest.mark.parametrize(
    "render",
    [
        pytest.param(
            lambda cp, html: cp.process_mime_content(
                html.encode(), "text/html", scope_main_content=True
            ),
            id="entry-body",
        ),
        pytest.param(
            lambda cp, html: cp.process_mime_content(
                html.encode(), "text/html", snippet_mode=True
            ),
            id="search-snippet",
        ),
        pytest.param(
            lambda cp, html: cp.html_to_plain_text(html),
            id="plain",
        ),
    ],
)
def test_noscript_boilerplate_is_stripped(
    content_processor: ContentProcessor, render
) -> None:
    """D15: browser-only <noscript> text carries nothing for an offline reader
    and ate into summary budgets and small max_content_length windows."""
    text = render(content_processor, _MEDLINEPLUS_ENCY_HTML)
    assert _NOSCRIPT_JUNK not in text, text
    assert "Diabetes is a long-term (chronic)" in text


# ---------------------------------------------------------------------------
# D16 — the footer's human-readable count must match what was emitted
# ---------------------------------------------------------------------------


def test_truncation_footer_count_matches_emitted_slice(
    content_processor: ContentProcessor,
) -> None:
    """D16: with a space at index 599 the page emits 599 chars and says
    ``content_offset=599``, but the prose claimed 'showing first 600'."""
    import re

    body = ("w" * 599) + " " + ("x" * 2000)
    out = content_processor.truncate_content(body, 600)
    emitted = out.partition("\n\n... [Content truncated")[0]
    assert len(emitted) == 599
    assert "only showing first 599" in out, out
    assert "first 600" not in out
    hint = re.search(r"content_offset=(\d+)", out)
    assert hint is not None
    assert int(hint.group(1)) == 599

    # Mid-article: the range end must be where the next page starts, not
    # offset + cap.
    page2 = content_processor.truncate_content(
        body[599:], 600, current_offset=599, original_total=len(body)
    )
    assert "showing chars 599–1,199 of" in page2, page2
    hint2 = re.search(r"content_offset=(\d+)", page2)
    assert hint2 is not None
    assert int(hint2.group(1)) == 1199


@patch("openzim_mcp.zim_operations.Archive")
def test_entry_footer_count_agrees_with_more_at_offset(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    import re

    path = "medlineplus.gov/bloodglucose.html"
    html = "<article><h1>Blood Glucose</h1><p>" + ("glucose " * 300) + "</p></article>"
    mock_archive.return_value = _archive_with(
        {path: _html_entry(path, "Blood Glucose", html)}
    )
    # Pick a cap whose last char is a space so the boundary deferral fires.
    full = ops.get_zim_entry_data(str(zim_file), path, max_content_length=10_000)
    cap = full["content"].index(" ", 500) + 1

    result = ops.get_zim_entry_data(str(zim_file), path, max_content_length=cap)

    shown = re.search(r"only showing first ([\d,]+)", result["content"])
    assert shown is not None, result["content"]
    assert result["_meta"]["more_at_offset"] == cap - 1
    assert int(shown.group(1).replace(",", "")) == cap - 1


# ---------------------------------------------------------------------------
# D17 — a leading slash is a plausible client slip; the ladder should try the
# un-slashed spelling before giving up
# ---------------------------------------------------------------------------


@patch("openzim_mcp.zim_operations.Archive")
def test_leading_slash_path_resolves_via_alternate_spelling(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D17: ``/medlineplus.gov/diabetes.html`` failed not-found (and the
    redactor then mangled the echoed path) although the un-slashed spelling
    resolves. The search fallback cannot rescue it either — its matcher splits
    the first segment off both sides asymmetrically."""
    path = "medlineplus.gov/diabetes.html"
    mock_archive.return_value = _archive_with(
        {path: _html_entry(path, "Diabetes", "<h1>Diabetes</h1><p>x</p>")}
    )
    search = MagicMock(return_value=None)
    with patch.object(ops, "_find_entry_by_search", search):
        result = ops.get_zim_entry_data(str(zim_file), "/" + path)

    assert result["path"] == path
    assert result["requested_path"] == "/" + path
    search.assert_not_called()


@patch("openzim_mcp.zim_operations.Archive")
def test_leading_slash_and_percent_encoding_combine(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    mock_archive.return_value = _archive_with(
        {_IEP_RAW: _html_entry(_IEP_RAW, "Gaudapada", "<h1>G</h1><p>x</p>")}
    )
    with patch.object(ops, "_find_entry_by_search", MagicMock(return_value=None)):
        result = ops.get_zim_entry_data(str(zim_file), "/" + _IEP_ENCODED)
    assert result["path"] == _IEP_RAW


# ---------------------------------------------------------------------------
# D43 — tell_me_about on a MedlinePlus topic page must surface the Summary
# prose, not stop at a prose-free lead
# ---------------------------------------------------------------------------

# The legacy text shape ``get_zim_entry`` hands ``_lead_with_toc`` for the
# measles page once the in-page nav (D14) and noscript (D15) strips apply:
# the pre-H2 lead is the H1 plus an "Also called:" label — no sentence at
# all — and the real content starts under ``## Summary``.
_MEASLES_ARTICLE_TEXT = (
    "# Measles | Rubeola | MedlinePlus\n\n"
    "Path: medlineplus.gov/measles.html\nType: text/html\n## Content\n\n"
    "#  Measles \n\nAlso called: Rubeola\n\n"
    "## Summary\n\n"
    "Measles is an infectious disease caused by a virus. It spreads easily "
    "from person to person. It causes a blotchy red rash.\n\n"
    "## Start Here\n\n"
    "  * [About Measles](../www.cdc.gov/measles/about/index.html) (CDC)\n\n"
    "## Symptoms\n\n"
    "  * [Signs and Symptoms](../www.cdc.gov/measles/signs-symptoms/) (CDC)\n"
)

_MEASLES_HEADINGS = {
    "headings": [
        {"level": 1, "text": "Measles"},
        {"level": 2, "text": "Summary"},
        {"level": 2, "text": "Start Here"},
        {"level": 2, "text": "Symptoms"},
    ]
}


def _simple_handler(article_text: str):
    from unittest.mock import Mock

    from openzim_mcp.simple_tools import SimpleToolsHandler

    zim_ops = Mock()
    zim_ops.get_zim_entry.return_value = article_text
    zim_ops.get_article_structure_data.return_value = _MEASLES_HEADINGS
    zim_ops.list_zim_files.return_value = (
        '[{"path": "/zim/medlineplus.zim", "name": "medlineplus.zim"}]'
    )
    # The pipe-suffixed title is not a bare topic, so tell_me_about resolves
    # it through search before fetching; give it a matching top hit.
    zim_ops.search_zim_file_data.return_value = {
        "results": [
            {
                "path": "medlineplus.gov/measles.html",
                "title": "Measles | Rubeola | MedlinePlus",
                "snippet": "Measles is an infectious disease caused by a virus.",
            }
        ]
    }
    return SimpleToolsHandler(zim_ops)


def test_lead_with_toc_advances_past_prose_free_lead() -> None:
    """D43: 'Also called: Rubeola' is a label, not a lead; the cut must reach
    the first real section so the caller gets the Summary prose."""
    handler = _simple_handler(_MEASLES_ARTICLE_TEXT)
    out = handler._lead_with_toc(
        "/zim/medlineplus.zim", "medlineplus.gov/measles.html", _MEASLES_ARTICLE_TEXT
    )
    assert "Measles is an infectious disease" in out, out
    assert "Also called: Rubeola" in out  # the label is kept, just not alone
    assert "About Measles" not in out  # still cut before the second section
    assert "Sections in this article" in out


def test_tell_me_about_topic_page_surfaces_summary_prose() -> None:
    handler = _simple_handler(_MEASLES_ARTICLE_TEXT)
    result = handler.handle_zim_query(
        "tell me about Measles | Rubeola | MedlinePlus",
        zim_file_path="/zim/medlineplus.zim",
        options={"compact": True, "max_content_length": 8000},
    )
    assert "Measles is an infectious disease" in result, result


def test_one_sentence_lead_is_still_a_lead() -> None:
    """A short real lead must keep the standard lead-section cut."""
    text = (
        "# Tiger\n\nPath: Tiger\nType: text/html\n## Content\n\n"
        "# Tiger\n\nThe tiger is the largest living cat species.\n\n"
        "## Taxonomy\n\nTaxonomy body.\n\n## Range\n\nRange body."
    )
    handler = _simple_handler(text)
    out = handler._lead_with_toc("/zim/wiki.zim", "Tiger", text)
    assert "largest living cat species" in out
    assert "Taxonomy body" not in out
    assert "Lead was empty" not in out
