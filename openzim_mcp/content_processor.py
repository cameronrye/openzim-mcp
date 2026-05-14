"""Content processing utilities for OpenZIM MCP server."""

import logging
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple, Union, cast
from urllib.parse import urlparse

import html2text
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from .constants import DEFAULT_SNIPPET_LENGTH, UNWANTED_HTML_SELECTORS

logger = logging.getLogger(__name__)


# A11 D1 (post-a10 second pass): block-level tag names that should
# inject whitespace at their boundary when extracting cell text.
# Inline tags (``span``, ``b``, ``i``, ``sup``, ``sub``, ``a``,
# ``wbr``, ``small``, ``abbr``, ``code``, etc.) are intentionally
# excluded — Wikipedia uses inline spans for number-separator hints
# (``3<span>,</span>913<span>,</span>644``), unit microformats
# (``891<wbr>.<wbr>3``), and coordinate templates
# (``52<span>°</span>31<span>′</span>N``), so inserting whitespace
# between adjacent inline children mangles those forms. The first
# revision of D1 used ``td.get_text(separator=" ")`` and surfaced
# exactly that regression; the helper below restores the inline
# concatenation while still separating block-level siblings.
_BLOCK_CELL_TAGS = frozenset(
    {
        "br",
        "li",
        "p",
        "div",
        "tr",
        "td",
        "th",
        "ul",
        "ol",
        "dl",
        "dt",
        "dd",
        "blockquote",
        "section",
        "article",
        "header",
        "footer",
    }
)


def _join_cell_text(cell: Tag) -> str:
    """Extract a table-cell's text, separating block-level children
    with whitespace and concatenating inline children directly.

    This is the safer alternative to ``cell.get_text(separator=" ")``:
    the BeautifulSoup default emits the separator between EVERY
    descendant Tag's text, which corrupts inline span groups used
    for number formatting (``3,913,644``), units (``891.3``), and
    coordinate templates. Iterating descendants ourselves and only
    inserting whitespace at block-level tag boundaries (and
    ``<br>``) keeps the inline forms intact while still fixing the
    multi-line concatenation cases the original bug report flagged
    (``5th in Europe1st in Germany``, ``Berliner(s) (English)Berliner
    (m)``, ``TokyoTamaNorthern Izu Islands``).

    The outer ``" ".join(text.split())`` collapses any whitespace
    runs the insertion produces, so legitimate text like
    ``"New York"`` survives.
    """
    parts: List[str] = []
    for el in cell.descendants:
        # ``Comment`` is a ``NavigableString`` subclass; the
        # ``isinstance(NavigableString)`` test below would catch it
        # and leak the comment text into the rendered value. Wikipedia
        # templates emit invisible coordinate / microformat comments
        # inside infobox cells routinely — without this guard,
        # ``3<!-- a-template -->,913,644`` rendered as
        # ``3 a-template ,913,644``. Filter before the string path.
        if isinstance(el, Comment):
            continue
        if isinstance(el, NavigableString):
            parts.append(str(el))
        elif isinstance(el, Tag) and el.name in _BLOCK_CELL_TAGS:
            parts.append(" ")
    return " ".join("".join(parts).split())


# BeautifulSoup parser name; pinned so the dependency footprint stays minimal
# (no lxml/html5lib needed) and the parsing semantics stay consistent.
HTML_PARSER = "html.parser"

# Link schemes that are not navigable as ZIM-internal links and should be
# excluded from extracted-link results. Keeps results actionable for an LLM.
NON_NAVIGABLE_LINK_SCHEMES = (
    "javascript:",
    "mailto:",
    "tel:",
    "data:",
    "blob:",
    "vbscript:",
)


def _slugify_heading(text: str) -> str:
    """Generate a stable, URL-safe slug from heading text.

    MediaWiki/MDN-style: NFKC-normalised, lowercased, whitespace collapsed
    to hyphens, characters that aren't word characters or hyphens stripped,
    leading/trailing hyphens removed. Unicode word characters (Arabic,
    Chinese, Cyrillic, Japanese, etc.) are preserved — the previous
    NFKD + ASCII-encode approach silently dropped non-Latin scripts and
    broke TOC anchors for the majority of Wikipedia ZIM files by language.
    Returns "" for empty/whitespace input so callers can decide how to
    handle.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^\w\-]", "", text, flags=re.UNICODE)  # NOSONAR(python:S3776)
    return text.strip("-")


def _fold(text: str) -> str:
    """Lowercase + strip diacritics."""
    nf = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nf if not unicodedata.combining(c)).lower()


def _split_query_terms(query: str) -> list:
    """Split a query string into individual terms; drop punctuation."""
    return [t for t in re.split(r"\W+", _fold(query)) if t]


def _word_in(folded_paragraph: str, term: str) -> bool:
    """Whole-word match of `term` in already-folded paragraph text."""
    return bool(re.search(rf"\b{re.escape(term)}\b", folded_paragraph))


# Regions inside which a query-term match must NOT be wrapped in a second
# layer of emphasis: it produces malformed markdown (e.g. ``**Artificial
# **photosynthesis****`` from a bold heading, ``_****Berlin****_`` from
# italic disambig links, ``[**Photosynthesis**](**Photosynthesis** "…")``
# where bolding inside the link target breaks the URL).
#
# - ``\[[^\]\n]+\]\([^\n)]*\)`` — full ``[text](href "title")`` link,
#   matched as ONE unit so the URL/tooltip parenthetical only counts
#   when it's attached to a link. An earlier shape matched any ``(...)``
#   parenthetical — that protected ordinary prose parentheticals like
#   ``(also called assimilation)`` from highlighting too, silently
#   dropping query-term visibility for any term that landed inside
#   them. (Wikipedia scientific articles are loaded with parenthetical
#   gloss; over-protecting them cost more highlights than it saved.)
# - ``\*\*[^*\n]+\*\*`` — existing bold runs (paired markers, single line).
#   ``[^*\n]+`` rules out adjacent ``**`` runs and multi-paragraph spans.
# - ``(?<!\w)_[^_\n]+_(?!\w)`` — italic runs; the lookarounds skip
#   identifier-style underscores like ``foo_bar``.
# - ``` `[^`\n]+` ``` — inline code spans (rarely emitted by html2text on
#   Wikipedia, but cheap to skip and prevents bold-inside-code from
#   breaking code-formatted text).
_HIGHLIGHT_SKIP_RE = re.compile(
    r"\[[^\]\n]+\]\([^\n)]*\)"
    r"|\*\*[^*\n]+\*\*"
    r"|(?<!\w)_[^_\n]+_(?!\w)"
    r"|`[^`\n]+`",
)


def _highlight_terms(text: str, query: str, *, max_hits: int) -> str:
    """Wrap the first `max_hits` occurrences of any query term in **bold**.

    Case-insensitive, preserves original casing of the matched substring.
    Skips matches that fall inside existing markdown emphasis (``**bold**``,
    ``_italic_``) or markdown link constructs (``[text](url "title")``):
    layering ``**…**`` on top of those produces malformed markdown that
    confuses small models more than it helps them.
    """
    terms = [t for t in _split_query_terms(query) if len(t) >= 3]
    if not terms:
        return text
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(t) for t in terms) + r")\b",
        flags=re.IGNORECASE,
    )
    # Pre-compute spans where we must not wrap. Overlapping markdown
    # constructs (a link inside a bold span, etc.) are collapsed into a
    # single forbidden-position bitmap so the term-replacement pass can
    # do a single membership check per match.
    forbidden_starts: List[int] = []
    forbidden_ends: List[int] = []
    for m in _HIGHLIGHT_SKIP_RE.finditer(text):
        forbidden_starts.append(m.start())
        forbidden_ends.append(m.end())

    def _is_forbidden(pos: int) -> bool:
        for s, e in zip(forbidden_starts, forbidden_ends):
            if s <= pos < e:
                return True
        return False

    hits = [0]

    def repl(m: re.Match[str]) -> str:
        if hits[0] >= max_hits or _is_forbidden(m.start()):
            return str(m.group(0))
        hits[0] += 1
        return f"**{m.group(0)}**"

    return pattern.sub(repl, text)


def resolve_heading_id(heading: Tag) -> Tuple[str, str]:
    """Return (id, source) for a heading, falling back to anchors and slugs.

    Resolution order:
      1. ``id`` attribute on the heading itself.
      2. ``id``/``name`` attribute of any descendant ``<a>`` (e.g. MediaWiki
         puts ``<span class="mw-headline" id="...">`` inside the heading).
      3. ``id``/``name`` of the immediately-preceding ``<a>`` sibling
         (older MediaWiki and many gov.* pages put ``<a name="">`` right
         before the heading).
      4. Slugified heading text — best-effort synthetic anchor.

    The second value is one of ``id``, ``descendant_anchor``,
    ``preceding_anchor``, or ``slug`` so consumers know the provenance and
    can decide whether the anchor is real (referenced in the HTML) or
    synthetic.
    """
    direct = heading.get("id")
    if direct and isinstance(direct, str) and direct.strip():
        return direct.strip(), "id"

    # Descendant anchors — typical MediaWiki ``mw-headline`` pattern.
    for anchor in heading.find_all(["a", "span"]):
        if not isinstance(anchor, Tag):
            continue
        candidate = anchor.get("id") or anchor.get("name")
        if candidate and isinstance(candidate, str) and candidate.strip():
            return candidate.strip(), "descendant_anchor"

    # Preceding anchor — common in older HTML and government health pages
    # where the named anchor sits *just* before the heading.
    prev = heading.find_previous_sibling()
    if isinstance(prev, Tag) and prev.name == "a":
        candidate = prev.get("id") or prev.get("name")
        if candidate and isinstance(candidate, str) and candidate.strip():
            return candidate.strip(), "preceding_anchor"

    # Synthetic slug — guarantees consumers always get a usable identifier
    # even when the source HTML is anchor-free.
    text = heading.get_text().strip()
    slug = _slugify_heading(text)
    if slug:
        return slug, "slug"
    return "", "none"


def _collect_meta_tag_metadata(soup: BeautifulSoup) -> Dict[str, str]:
    """Pull ``name|property|http-equiv`` → ``content`` pairs from <meta> tags.

    Called before unwanted-element pruning so meta tags inside <head> aren't
    accidentally removed.
    """
    metadata: Dict[str, str] = {}
    for meta in soup.find_all("meta"):
        if not isinstance(meta, Tag):
            continue
        name = meta.get("name") or meta.get("property") or meta.get("http-equiv")
        content = meta.get("content")
        if name and content:
            metadata[str(name)] = str(content)
    return metadata


def _build_headings(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """Collect headings (h1-h6) in document order with disambiguated anchors.

    Iterating level-first would group all h1s before any h2 even when they
    appear later in the document, breaking the position contract and the
    implicit alignment with the sections list (which DOES walk in document
    order).

    Collision disambiguation: when two headings share the same synthetic
    slug (e.g. three "Intro" h1s), MediaWiki appends ``_2``, ``_3`` to keep
    anchors unique. Mirror that. Explicit author-provided ids
    (``id_source != "slug"``) pass through untouched — disambiguating real
    anchors would silently break cross-page links.
    """
    headings: List[Dict[str, Any]] = []
    slug_counts: Dict[str, int] = {}
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if not (isinstance(heading, Tag) and heading.name):
            continue
        text = heading.get_text().strip()
        if not text:
            continue
        anchor_id, id_source = resolve_heading_id(heading)
        if anchor_id and id_source == "slug":
            count = slug_counts.get(anchor_id, 0) + 1
            slug_counts[anchor_id] = count
            if count > 1:
                anchor_id = f"{anchor_id}_{count}"
        headings.append(
            {
                "level": int(heading.name[1]),
                "text": text,
                "id": anchor_id,
                "id_source": id_source,
                "position": len(headings),
            }
        )
    return headings


def _append_section_content(
    current_section: Dict[str, Union[str, int]], element: Tag
) -> None:
    """Append paragraph/div text into the current section's preview + word count."""
    text = element.get_text().strip()
    if not text:
        return
    preview = cast(str, current_section["content_preview"])
    if len(preview) < 300:
        if preview:
            preview += " "
        preview += text[: 300 - len(preview)]
        current_section["content_preview"] = preview
    current_section["word_count"] = cast(int, current_section["word_count"]) + len(
        text.split()
    )


# (tag, attribute, classification) tuples for media-link extraction.
_MEDIA_SELECTORS = (
    ("img", "src", "image"),
    ("video", "src", "video"),
    ("audio", "src", "audio"),
    ("source", "src", "media"),
    ("embed", "src", "embed"),
    ("object", "data", "object"),
)


def _classify_anchor(link: Tag, links_data: Dict[str, Any]) -> None:
    """Categorise one ``<a href>`` into internal/external/anchor lists.

    Skips empty hrefs and non-navigable schemes (``javascript:``, ``mailto:``,
    ``tel:``, ``data:``, ``blob:``, ``vbscript:``) which pollute results
    without being useful navigation targets.
    """
    href_attr = link.get("href")
    if not (href_attr and isinstance(href_attr, str)):
        return
    href = href_attr.strip()
    if not href:
        return
    if href.lower().startswith(NON_NAVIGABLE_LINK_SCHEMES):
        return

    title_attr = link.get("title", "")
    link_info: Dict[str, Any] = {
        "url": href,
        "text": link.get_text().strip(),
        "title": str(title_attr) if title_attr else "",
    }

    if href.startswith(("http://", "https://", "//")):
        link_info["domain"] = urlparse(href).netloc
        links_data["external_links"].append(link_info)
    elif href.startswith("#"):
        link_info["type"] = "anchor"
        links_data["internal_links"].append(link_info)
    else:
        link_info["type"] = "internal"
        links_data["internal_links"].append(link_info)


def _append_media_link(
    element: Tag, attr: str, media_type: str, links_data: Dict[str, Any]
) -> None:
    """Append a single media element (img/video/etc.) into ``media_links``."""
    src = element.get(attr)
    if not (src and isinstance(src, str)):
        return
    alt_attr = element.get("alt", "")
    title_attr = element.get("title", "")
    links_data["media_links"].append(
        {
            "url": src.strip(),
            "type": media_type,
            "alt": str(alt_attr) if alt_attr else "",
            "title": str(title_attr) if title_attr else "",
        }
    )


def _build_sections(soup: BeautifulSoup) -> List[Dict[str, Union[str, int]]]:
    """Walk the document in order, grouping <p>/<div> content under headings."""
    sections: List[Dict[str, Union[str, int]]] = []
    current_section: Optional[Dict[str, Union[str, int]]] = None

    for page_element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "div"]):
        if not (isinstance(page_element, Tag) and page_element.name):
            continue
        element = cast(Tag, page_element)
        if element.name.startswith("h"):
            if current_section:
                sections.append(current_section)
            current_section = {
                "title": element.get_text().strip(),
                "level": int(element.name[1]),
                "content_preview": "",
                "word_count": 0,
            }
        elif current_section and element.name in ("p", "div"):
            _append_section_content(current_section, element)

    if current_section:
        sections.append(current_section)
    return sections


class ParsedHTML:
    """Container for pre-parsed HTML to enable reuse across multiple operations.

    This class allows parsing HTML once and using it for multiple extraction
    operations (text conversion, structure extraction, link extraction) without
    re-parsing the HTML each time.

    Example:
        >>> processor = ContentProcessor()
        >>> parsed = processor.parse_html("<html><body><h1>Title</h1></body></html>")
        >>> text = processor.html_to_plain_text_from_parsed(parsed)
        >>> structure = processor.extract_html_structure_from_parsed(parsed)
    """

    def __init__(self, html_content: str):
        """Parse HTML content once for reuse.

        Args:
            html_content: Raw HTML string to parse
        """
        self.original_html = html_content
        self._soup = BeautifulSoup(html_content, HTML_PARSER)
        # Store a copy of the original parsed soup for operations that modify it
        self._original_soup_html = str(self._soup)

    @property
    def soup(self) -> BeautifulSoup:
        """Return a fresh copy of the parsed soup for modifying operations."""
        return BeautifulSoup(self._original_soup_html, HTML_PARSER)

    @property
    def soup_for_reading(self) -> BeautifulSoup:
        """Get the original soup for read-only operations (more efficient)."""
        return self._soup


class ContentProcessor:
    """Handles HTML to text conversion and content processing."""

    # Configuration for the per-call ``html2text.HTML2Text`` converter.
    # ``HTML2Text`` keeps mutable parser state on ``self`` (``out``,
    # ``outtextlist``, ``style``, ``pre``, ...), so a single shared instance
    # is not safe to reuse across ``asyncio.to_thread`` calls — concurrent
    # ``handle()`` invocations corrupt each other's output. We instead build
    # a fresh converter per call (constructor is pure-Python and cheap) and
    # apply these settings to it.
    _HTML_IGNORE_LINKS = False
    _HTML_IGNORE_IMAGES = True
    _HTML_IGNORE_TABLES = False
    _HTML_UNICODE_SNOB = True  # Use Unicode instead of ASCII
    _HTML_BODY_WIDTH = 0  # No line wrapping

    # CSS selectors tried in order when searching for the article infobox.
    # The first match wins and is removed from soup before html2text renders.
    INFOBOX_SELECTORS = [
        "table.infobox",
        "table.vcard",
        ".infobox",
        ".vcard",
    ]

    def __init__(
        self,
        snippet_length: int = DEFAULT_SNIPPET_LENGTH,
        *,
        table_row_threshold: int = 8,
        table_char_threshold: int = 600,
        infobox_kv_limit: int = 30,
    ):
        """
        Initialize content processor.

        Args:
            snippet_length: Maximum length for content snippets
            table_row_threshold: Tables with more rows than this are replaced
                in compact mode.
            table_char_threshold: Tables with more characters than this are
                replaced in compact mode.
            infobox_kv_limit: Maximum KV pairs returned by extract_infobox.
        """
        self.snippet_length = snippet_length
        self._table_row_threshold = table_row_threshold
        self._table_char_threshold = table_char_threshold
        self._infobox_kv_limit = infobox_kv_limit
        logger.debug(
            f"ContentProcessor initialized with snippet_length={snippet_length}"
        )

    def _create_html_converter(self) -> html2text.HTML2Text:
        """Create and configure a fresh HTML to text converter.

        A new instance is returned on every call so concurrent callers do
        not share the converter's mutable parser state.
        """
        converter = html2text.HTML2Text()
        converter.ignore_links = self._HTML_IGNORE_LINKS
        converter.ignore_images = self._HTML_IGNORE_IMAGES
        converter.ignore_tables = self._HTML_IGNORE_TABLES
        converter.unicode_snob = self._HTML_UNICODE_SNOB
        converter.body_width = self._HTML_BODY_WIDTH
        return converter

    def extract_infobox(
        self, soup: BeautifulSoup, *, kv_limit: Optional[int] = None
    ) -> List[Dict[str, str]]:
        """Extract the first matching infobox from ``soup`` as a list of KV rows.

        Returns ``[{"label": str, "value": str}]``. Mutates ``soup`` to remove
        the extracted infobox so it doesn't get pipe-soup'd by html2text
        downstream.

        Section-header rows (``<th colspan=...>`` only — no ``<td>``) act as
        parent context for the rows that follow. Without that context, a
        Wikipedia infobox renders three rows labelled ``City/State`` —
        one each for Government / Area / Population — which is meaningless
        to a small model. Carrying the section header through as
        ``"Area — City/State"`` restores the disambiguation that the
        original two-column rendering provided visually.
        """
        if kv_limit is None:
            kv_limit = self._infobox_kv_limit
        for selector in self.INFOBOX_SELECTORS:
            node = soup.select_one(selector)
            if node is None:
                continue
            rows: List[Dict[str, str]] = []
            current_section: Optional[str] = None
            section_emitted_count = 0
            title_row_consumed = False
            # Only rows whose nearest ``<table>`` ancestor is the infobox
            # ITSELF count — Wikipedia infoboxes frequently embed nested
            # tables inside data cells (chronology rows, coordinates
            # microformats, sub-component sub-tables), and a naive
            # ``select("tr")`` would pull those nested rows into the
            # KV list as if they were top-level infobox fields. The
            # previous code emitted things like ``"prev|1959": "next"``
            # rows lifted out of an album-chronology nested table.
            #
            # Only ``th.find("th")`` would have to look up to skip — but
            # the cleanest filter is at the row level: keep only rows
            # whose ``parent`` chain reaches ``node`` before reaching any
            # other ``<table>``.

            # M33: bind ``node`` via a default arg so the closure can't
            # accidentally pick up a different ``node`` if the outer
            # ``for selector in self.INFOBOX_SELECTORS:`` loop is ever
            # restructured to call this after the loop advances. Python
            # closures bind by name (late binding), so the original
            # ``return cell.find_parent("table") is node`` was correct
            # only because the function happened to be called inside
            # the same loop iteration that defined ``node`` — fragile.
            # ``node`` was narrowed from ``Tag | None`` to ``Tag`` by the
            # ``if node is None: continue`` guard above, but mypy does not
            # carry that narrowing into the default-arg expression. Bind
            # via a local intermediate so the narrowed type flows in.
            node_bound: Tag = node

            def _cell_belongs_to_infobox(
                cell: Optional[Tag], _node: Tag = node_bound
            ) -> bool:
                """``True`` iff ``cell``'s nearest enclosing table is
                ``_node`` itself — i.e. not buried inside a nested table.

                ``tr.find("th")`` searches descendants, so a top-level row
                with an empty layout-only ``<td>`` followed by a nested
                table could otherwise borrow the nested ``<th>`` for its
                label. Guard at the cell level so the outer row's
                label/value pairing only counts when both cells live in
                this infobox directly.
                """
                if cell is None or not isinstance(cell, Tag):
                    return False
                return cell.find_parent("table") is _node

            for tr in node.select("tr"):
                ancestor_table = tr.find_parent("table")
                if ancestor_table is not node:
                    continue
                th_candidate = tr.find("th")
                td_candidate = tr.find("td")
                th = th_candidate if _cell_belongs_to_infobox(th_candidate) else None
                td = td_candidate if _cell_belongs_to_infobox(td_candidate) else None
                if th and not td:
                    # Section-header row: a single ``<th>`` (usually with a
                    # colspan that visually spans the table). The first
                    # such row of the infobox is the title (a duplicate
                    # of the article title at the top of the infobox);
                    # subsequent ones act as parent context for the
                    # rows that follow.
                    classes_raw: Any = th.get("class") or []
                    classes: List[str]
                    if isinstance(classes_raw, str):
                        classes = classes_raw.split()
                    else:
                        classes = [str(c) for c in classes_raw]
                    if any("above" in c for c in classes) or not title_row_consumed:
                        # First th-only row OR an explicitly-marked
                        # ``infobox-above`` row: drop it. The flag stays
                        # set so subsequent th-only rows are treated as
                        # section dividers regardless of whether a KV
                        # row has been seen yet.
                        title_row_consumed = True
                        continue
                    candidate = " ".join(th.get_text().split())
                    if candidate:
                        current_section = candidate
                        section_emitted_count = 0
                    continue
                if th and td:
                    # A11 D1 (post-a10, second pass): use
                    # ``_join_cell_text`` so block-level children
                    # (``<br>``, ``<li>``, ``<p>``) get whitespace
                    # while inline groups (``<span>`` for number
                    # separators, ``<wbr>`` for soft breaks)
                    # concatenate directly. The first revision used
                    # ``get_text(separator=" ")`` which corrupted
                    # population numbers (``3,913,644`` →
                    # ``3 , 913 , 644``) and coordinate templates
                    # (``52°31′N`` → ``52 ° 31 ′ N``). The helper
                    # restores the inline forms while still fixing
                    # the original ``5th in Europe1st in Germany`` /
                    # ``TokyoTamaNorthern Izu Islands`` /
                    # ``0.967very high`` concatenations.
                    raw_label = _join_cell_text(th)
                    value = _join_cell_text(td)
                    if not raw_label or not value:
                        continue
                    # D1 (beta): Wikipedia infoboxes end with trailing
                    # "free-floating" terminal rows (Time zone, Area code,
                    # ISO 3166 code, Website, HDI) that don't belong to
                    # any preceding ``infobox-header`` section but visually
                    # carry top-border separators. The HTML marks each such
                    # row with ``<tr class="mergedtoprow">`` — the same
                    # class section header rows themselves carry. For KV
                    # rows the class signals "this starts a new visual
                    # group, NOT a continuation of the prior section";
                    # reset the carried section context so the row emits
                    # bare (``Time zone``) instead of inheriting the last
                    # ``infobox-header`` row's name (``GDP — Time zone``).
                    # Section header rows (th-only) handle ``mergedtoprow``
                    # in their own branch and are unaffected.
                    #
                    # D1 (beta, second pass): Wikipedia ALSO marks the
                    # first KV row inside a section with ``mergedtoprow``
                    # — that row is the section's visual lead, NOT a
                    # break out of it. Resetting unconditionally regressed
                    # the original bug in the opposite direction
                    # (``Government — Body`` collapsed to ``Body``).
                    # Reset only after we've already emitted at least one
                    # KV row under the current section, so the section's
                    # lead row keeps its prefix and only trailing
                    # ``mergedtoprow`` rows break out.
                    tr_classes_raw: Any = tr.get("class") or []
                    tr_classes: List[str]
                    if isinstance(tr_classes_raw, str):
                        tr_classes = tr_classes_raw.split()
                    else:
                        tr_classes = [str(c) for c in tr_classes_raw]
                    if (
                        "mergedtoprow" in tr_classes
                        and current_section is not None
                        and section_emitted_count > 0
                    ):
                        current_section = None
                        section_emitted_count = 0
                    # A11 D2 (post-a10): bullet-prefixed continuation
                    # rows ("• Summer (DST)") have no
                    # ``infobox-header`` section header above them but
                    # are visually owned by the immediately-preceding
                    # KV row's label ("Time zone"). When the label
                    # starts with a bullet character AND we have no
                    # ``current_section``, treat the previous KV row's
                    # label as a virtual parent FOR THIS ROW ONLY so
                    # the orphan bullet row inherits context. Without
                    # this, Berlin rendered ``**• Summer (DST):**
                    # UTC+02:00 (CEST)`` with no clue that "Summer
                    # (DST)" belongs to "Time zone". The virtual
                    # parent is applied locally rather than persisted
                    # via ``current_section`` so the row that follows
                    # the bullet row (e.g. ``Area code``) doesn't
                    # inherit the same parent.
                    virtual_parent: Optional[str] = None
                    if (
                        current_section is None
                        and rows
                        and raw_label.lstrip().startswith(("•", "·", "‣", "▪"))
                    ):
                        prev_label = rows[-1].get("label", "")
                        if prev_label:
                            virtual_parent = prev_label.split(" — ", 1)[-1]
                    # Prefix with current section when present so labels
                    # disambiguate across sections. Drop the prefix when
                    # the label already starts with the section name
                    # (e.g. some infoboxes have ``Population total`` /
                    # ``Population density`` inside a "Population"
                    # section — don't write ``Population — Population
                    # total``).
                    effective_section = current_section or virtual_parent
                    if effective_section and not raw_label.lower().startswith(
                        effective_section.lower()
                    ):
                        label = f"{effective_section} — {raw_label}"
                    else:
                        label = raw_label
                    rows.append({"label": label, "value": value})
                    title_row_consumed = True
                    if current_section is not None:
                        section_emitted_count += 1
                    if len(rows) >= kv_limit:
                        break
            node.decompose()
            return rows
        return []

    def replace_oversized_tables(
        self,
        soup: BeautifulSoup,
        *,
        row_threshold: Optional[int] = None,
        char_threshold: Optional[int] = None,
    ) -> None:
        """Replace oversized ``<table>`` elements with a placeholder paragraph.

        Tables with more rows than ``row_threshold`` OR more text characters
        than ``char_threshold`` are replaced in document order with a
        ``[Table N: M rows x P cols - pass compact=False to expand]`` paragraph.
        """
        if row_threshold is None:
            row_threshold = self._table_row_threshold
        if char_threshold is None:
            char_threshold = self._table_char_threshold
        # Iterate only OUTER tables (those whose nearest ancestor is not
        # itself a ``<table>``). The previous ``find_all("table")`` walk
        # enumerated nested tables too, and replacing an outer table
        # detached its inner tables from the tree — subsequent
        # ``replace_with`` calls on those detached nodes silently
        # no-op'd, leaving inner tables un-placeholdered when they
        # weren't reached first (Phase A #14 fix).
        outer_tables = [
            t for t in soup.find_all("table") if t.find_parent("table") is None
        ]
        for index, table in enumerate(outer_tables, start=1):
            rows = table.find_all("tr")
            text = table.get_text()
            if len(rows) <= row_threshold and len(text) <= char_threshold:
                continue
            cols = max(
                (len(row.find_all(["th", "td"])) for row in rows),
                default=0,
            )
            placeholder = soup.new_tag("p")
            # ASCII-only placeholder: the earlier ``× ... —`` form
            # round-tripped fine on macOS / Ubuntu CI but produced
            # ``� ... �`` (replacement chars) on Windows runners.
            # Snippet-level html2text rendering hits an encoding boundary
            # somewhere — likely a sys-default-codec fallback inside
            # html2text or BeautifulSoup. Using ASCII ``x`` / ``-``
            # bypasses the issue entirely; the placeholder is internal
            # diagnostic text, not user-facing prose, so the slight
            # downgrade in glyph fidelity has no practical cost.
            placeholder.string = (
                f"[Table {index}: {len(rows)} rows x {cols} cols - "
                f"pass compact=False to expand]"
            )
            table.replace_with(placeholder)

    def parse_html(self, html_content: str) -> ParsedHTML:
        """Parse HTML content once for reuse across multiple operations.

        Use this method when you need to perform multiple operations on the same
        HTML content (e.g., extract text AND structure AND links). This avoids
        re-parsing the HTML for each operation.

        Args:
            html_content: Raw HTML string to parse

        Returns:
            ParsedHTML container that can be passed to *_from_parsed methods

        Example:
            >>> parsed = processor.parse_html(html_content)
            >>> text = processor.html_to_plain_text_from_parsed(parsed)
            >>> links = processor.extract_html_links_from_parsed(parsed)
        """
        return ParsedHTML(html_content)

    def _render_soup_to_text(self, soup: BeautifulSoup, *, compact: bool) -> str:
        """Render a BeautifulSoup tree to clean plain text.

        Strips ``UNWANTED_HTML_SELECTORS``, optionally extracts infoboxes
        and replaces oversized tables when ``compact=True``, then runs
        ``html2text`` and collapses excess blank lines. Mutates the
        provided soup; callers that need to preserve the original tree
        should pass a copy.
        """
        for selector in UNWANTED_HTML_SELECTORS:
            for element in soup.select(selector):
                element.decompose()

        infobox_md = ""
        if compact:
            kv_rows = self.extract_infobox(soup)
            if kv_rows:
                infobox_md = (
                    "\n".join(f"**{r['label']}:** {r['value']}" for r in kv_rows)
                    + "\n\n"
                )
            self.replace_oversized_tables(soup)

        # Per-call HTML2Text so concurrent callers don't corrupt each
        # other's parser state.
        text = self._create_html_converter().handle(str(soup))
        text = re.sub(r"\n{3,}", "\n\n", text)
        return (infobox_md + text).strip()

    def html_to_plain_text_from_parsed(
        self, parsed: ParsedHTML, *, compact: bool = False
    ) -> str:
        """Convert pre-parsed HTML to clean plain text.

        More efficient when used with parse_html() for multiple operations.

        Args:
            parsed: Pre-parsed HTML container
            compact: When True, extract infoboxes and replace oversized tables
                with placeholders before rendering. Defaults to False, which
                preserves byte-identical v1.2.0 behavior.

        Returns:
            Converted plain text
        """
        try:
            return self._render_soup_to_text(parsed.soup, compact=compact)
        except Exception as e:
            logger.warning(f"Error converting HTML to text: {e}")
            # Fallback: return raw text content
            return str(parsed.soup_for_reading.get_text().strip())

    def html_to_plain_text(self, html_content: str, *, compact: bool = False) -> str:
        """Convert HTML to clean plain text.

        Args:
            html_content: HTML content to convert
            compact: When True, extract infoboxes and replace oversized tables
                with placeholders before rendering. Defaults to False, which
                preserves byte-identical v1.2.0 behavior.

        Returns:
            Converted plain text
        """
        if not html_content:
            return ""
        try:
            soup = BeautifulSoup(html_content, HTML_PARSER)
            return self._render_soup_to_text(soup, compact=compact)
        except Exception as e:
            logger.warning(f"Error converting HTML to text: {e}")
            # Fallback: return raw text content
            soup = BeautifulSoup(html_content, HTML_PARSER)
            return str(soup.get_text().strip())

    def create_snippet(
        self,
        content: str,
        *,
        query: Optional[str] = None,
        max_paragraphs: int = 2,
        title: Optional[str] = None,
    ) -> str:
        """Create a snippet from content, optionally query-aware.

        When `query` is supplied, locate the first paragraph that contains a
        whole-word match for any term in the query (case-insensitive,
        diacritic-folded) and start the snippet there. Falls back to a
        substring (morphological) match when no whole-word paragraph hits —
        captures stemmed forms like ``photosynthetic`` for query
        ``photosynthesis`` instead of dropping to the lead paragraph
        (which often carries zero query relevance for inflected matches).

        ``title`` is the entry title; when supplied, a leading ``# <title>``
        markdown H1 that duplicates the title is stripped from the snippet
        (the title is already shown in the result header above the
        snippet, so the H1 burns 5-15 tokens per result for no signal).

        Up to 5 occurrences of any matched term inside the returned slice are
        wrapped in `**bold**` for visibility.
        """
        if not content:
            return ""

        # Strip a leading ``# <title>`` H1 that duplicates the entry title
        # before any paragraph selection happens — otherwise we'd select a
        # paragraph that contains the H1 and waste 5-15 tokens on a heading
        # the caller already has from the result row. Done after the empty
        # check so empty inputs short-circuit unchanged.
        if title:
            content = self._strip_leading_title_heading(content, title)
            if not content:
                return ""

        paragraphs = content.split("\n\n")
        start_idx = 0

        if query:
            terms = [t for t in _split_query_terms(query) if len(t) >= 3]
            if terms:
                folded_paragraphs = [_fold(p) for p in paragraphs]
                # Pass 1: whole-word match (most precise — preserves the
                # Phase A #1 spec promise).
                whole_word_idx: Optional[int] = None
                for i, p in enumerate(folded_paragraphs):
                    if any(_word_in(p, t) for t in terms):
                        whole_word_idx = i
                        break
                if whole_word_idx is not None:
                    start_idx = whole_word_idx
                else:
                    # Pass 2: stem-prefix substring match catches
                    # inflected/stemmed forms (``photosynthetic`` for
                    # query ``photosynthesis``). Use the first
                    # ``ceil(2/3 * len)`` chars of each query term as a
                    # prefix probe — long enough to be specific to the
                    # query stem ("photosynthe" for "photosynthesis"),
                    # short enough to match plausible inflections
                    # (-ic, -is, -ise, -ate). Falls through to the
                    # legacy lead-text behavior (start_idx=0) when no
                    # paragraph carries even a stem-prefix.
                    stems = [t[: max(4, (len(t) * 2 + 2) // 3)] for t in terms]
                    for i, p in enumerate(folded_paragraphs):
                        if any(stem in p for stem in stems):
                            start_idx = i
                            break

        selected = paragraphs[start_idx : start_idx + max_paragraphs]
        # H11: join with blank line (``\n\n``), not a single space, so a
        # second paragraph that opens with a markdown heading (``## Foo``)
        # remains a heading instead of becoming inline mid-line text.
        # Heading renderers require the marker to start the line; a
        # single-space join silently disables them.
        snippet_text = (
            "\n\n".join(selected)
            if len(selected) > 1
            else (selected[0] if selected else "")
        )

        # Truncate if too long. Reserve 3 chars for the trailing "..." so the
        # final string respects snippet_length rather than overshooting it.
        if len(snippet_text) > self.snippet_length:
            cap = max(self.snippet_length - 3, 0)
            snippet_text = snippet_text[:cap].rstrip() + "..."

        if query:
            snippet_text = _highlight_terms(snippet_text, query, max_hits=5)
            # Re-check length after bold markers are inserted: they may push the
            # string over snippet_length. Hard-truncate if so, preserving the
            # trailing "..." sentinel so callers see a consistent format.
            if len(snippet_text) > self.snippet_length:
                cap = max(self.snippet_length - 3, 0)
                sliced = snippet_text[:cap].rstrip()
                # Truncation can land inside a ``**term**`` highlight, leaving
                # an unmatched opening marker (e.g. ``…**ter``) that downstream
                # markdown renderers will treat as runaway bold. Detect an
                # unpaired trailing ``**`` and resolve the dangling fragment.
                # The ``last_open == 0`` branch covers the rare case where the
                # dangling ``**`` is at position 0 — the entire sliced snippet
                # is the start of the first highlighted term. Slicing
                # ``sliced[:0]`` there yields ``""`` and the caller sees a
                # content-free ``"..."``; instead drop the orphan ``**``
                # marker and keep the term text so the snippet stays useful.
                if sliced.count("**") % 2 == 1:
                    last_open = sliced.rfind("**")
                    if last_open > 0:
                        sliced = sliced[:last_open].rstrip()
                    elif last_open == 0:
                        sliced = sliced[2:].lstrip()
                snippet_text = sliced + "..."

        return snippet_text

    @staticmethod
    def _strip_leading_title_heading(content: str, title: str) -> str:
        """Drop a leading ``# <title>`` line that duplicates the entry title.

        Wikipedia exports prepend ``<h1>Title</h1>`` to the article body;
        ``html2text`` renders that as ``# Title``. When the snippet/preview
        is going to be displayed under a separate ``## N. <Title>``
        result header, the duplicate H1 wastes 5-15 tokens per result.

        Match is case-insensitive on the title and tolerant of one
        trailing whitespace run (collapsed by html2text). Leaves
        non-matching headings (real article subheadings) alone.
        """
        if not content or not title:
            return content
        norm_title = title.strip()
        if not norm_title:
            return content
        # ``re.escape`` on the title keeps disambiguation parens / dots
        # literal so ``# Mercury (planet)`` matches title
        # ``Mercury (planet)``.
        pattern = re.compile(
            rf"^\s*#\s+{re.escape(norm_title)}\s*\n+",
            flags=re.IGNORECASE,
        )
        return pattern.sub("", content, count=1)

    def truncate_content(
        self,
        content: str,
        max_length: int,
        *,
        current_offset: int = 0,
        paginatable: bool = True,
        original_total: Optional[int] = None,
    ) -> str:
        """
        Truncate content to maximum length with informative message.

        The message explicitly references "body content" so callers don't
        confuse the truncation budget with the response wrapper headers
        (``# Title``, ``Path:``, ``## Content``, etc.) that surround the
        body in the final output. ``max_length`` applies only to the body.

        Args:
            content: Content to truncate. When the caller already sliced
                the article (``current_offset > 0``), ``len(content)`` is
                the post-slice length, NOT the article's full length —
                pass ``original_total`` so the footer's "of N" denominator
                stays correct.
            max_length: Maximum allowed length
            current_offset: Where this slice starts in the source
                content. Lets the truncation hint compute the correct
                next-page offset for paginated reads.
            paginatable: When False, omit the ``content_offset=N``
                hint and emit a tighter "use get article ... for the
                rest" hint instead. Main-page rendering passes False:
                ``_handle_main_page`` doesn't expose
                ``content_offset`` (the operation always re-resolves
                the main entry from scratch), so suggesting it would
                point the caller at a parameter the main-page path
                ignores. A11 third-pass fix.
            original_total: Pre-slice length of the source body, used
                as the denominator in the footer. Defaults to
                ``len(content) + current_offset`` so callers that pass
                an already-sliced ``content`` still produce a correct
                "of N" — A11 post-a11 M4 fix. Without this, the footer
                read "total of N characters of body content" using the
                post-slice length, so paginated reads under-reported
                the article's length by ``current_offset`` chars.

        Returns:
            Truncated content with metadata
        """
        if not content or len(content) <= max_length:
            return content

        truncated = content[:max_length].strip()
        # A11 post-a11 M4: prefer the caller-supplied pre-slice length;
        # fall back to a computed approximation that still beats the
        # previous "len(post-slice content)" bug. Either way the
        # footer's "of N" denominator now matches the article's actual
        # length, regardless of where in the article we're paged into.
        full_length = (
            original_total
            if original_total is not None
            else len(content) + current_offset
        )
        # A11 F2 + Opp4: the truncation marker now tells the caller
        # how to fetch the rest. Before, a small LLM saw
        # ``[Content truncated, total of 146,250 chars, only showing
        # first 1,500]`` with no clue what offset to pass next; the
        # ``content_offset`` parameter is now exposed on ``zim_query``
        # (A1) so the hint is actionable. ``current_offset`` lets
        # paginated reads compute the next offset relative to where
        # this slice STARTED in the original article.
        next_offset = current_offset + max_length

        if paginatable:
            tail = f" Pass `content_offset={next_offset:,}` to read the " "next page."
        else:
            # Main-page rendering: ``_handle_main_page`` re-resolves
            # from ``archive.main_entry`` on every call and never
            # threads a content_offset. Point the caller at the
            # ``get article`` route, which DOES support paging.
            tail = (
                " For the rest, switch to `get article` on the main-"
                "page path with `content_offset`."
            )

        # Body of the slice description switches shape based on
        # whether we're paginating mid-article: at offset 0 the
        # "showing first N" wording is honest; mid-article the user
        # wants to see "chars X–Y of Z" so they can reason about
        # where they are in the document.
        if current_offset > 0:
            slice_end = current_offset + max_length
            body_desc = (
                f"showing chars {current_offset:,}–{slice_end:,} of "
                f"{full_length:,}-char body"
            )
        else:
            body_desc = (
                f"total of {full_length:,} characters of body content, "
                f"only showing first {max_length:,}"
            )

        return f"{truncated}\n\n... [Content truncated, {body_desc}.{tail}] ..."

    def process_mime_content(
        self,
        content_bytes: bytes,
        mime_type: str,
        *,
        compact: bool = False,
        snippet_mode: bool = False,
    ) -> str:
        """
        Process content based on MIME type.

        Args:
            content_bytes: Raw content bytes
            mime_type: MIME type of the content
            compact: When True, forward to ``html_to_plain_text`` with
                ``compact=True`` so infobox extraction and oversized-table
                replacement run. Defaults to False (v1.2.0-compatible).
            snippet_mode: M29 — when True, skip the structural rewrites
                (infobox extraction, oversized-table replacement) and run
                html2text directly. Search-result snippets only need the
                first paragraph or two, so the per-result cost of the
                full compact pipeline (10 ms each × N results) was
                burning cycles on data the snippet discards. ``compact``
                is ignored when ``snippet_mode`` is True.

        Returns:
            Processed text content
        """
        try:
            # Decode bytes to string
            raw_content = content_bytes.decode("utf-8", errors="replace")

            if mime_type.startswith("text/html"):
                if snippet_mode:
                    # Skip structural rewrites; render the soup as-is.
                    soup = BeautifulSoup(raw_content, HTML_PARSER)
                    return self._render_soup_to_text(soup, compact=False)
                return self.html_to_plain_text(raw_content, compact=compact)
            elif mime_type.startswith("text/"):
                return raw_content.strip()
            elif mime_type.startswith("image/"):
                return "(Image content - Cannot display directly)"
            else:
                return f"(Unsupported content type: {mime_type})"

        except Exception as e:
            logger.warning(f"Error processing content with MIME type {mime_type}: {e}")
            return f"(Error processing content: {e})"

    def extract_html_structure_from_parsed(self, parsed: ParsedHTML) -> Dict[str, Any]:
        """Extract structure from pre-parsed HTML including headings and sections.

        More efficient when used with parse_html() for multiple operations.

        Args:
            parsed: Pre-parsed HTML container

        Returns:
            Dictionary containing structure information
        """
        return self._extract_structure_from_soup(parsed.soup)

    def extract_html_structure(self, html_content: str) -> Dict[str, Any]:
        """
        Extract structure from HTML content including headings and sections.

        Args:
            html_content: HTML content to analyze

        Returns:
            Dictionary containing structure information
        """
        try:
            soup = BeautifulSoup(html_content, HTML_PARSER)
            return self._extract_structure_from_soup(soup)
        except Exception as e:
            logger.warning(f"Error extracting HTML structure: {e}")
            return {
                "headings": [],
                "sections": [],
                "metadata": {},
                "word_count": 0,
                "error": str(e),
            }

    def _extract_structure_from_soup(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract structure from a BeautifulSoup object.

        Args:
            soup: BeautifulSoup object (will be modified)

        Returns:
            Dictionary containing structure information
        """
        structure: Dict[str, Any] = {
            "headings": [],
            "sections": [],
            "metadata": {},
            "word_count": 0,
        }

        try:
            structure["metadata"] = _collect_meta_tag_metadata(soup)

            # Strip unwanted elements before walking headings/sections so the
            # text-content + word counts ignore navigation, footers, etc.
            for selector in UNWANTED_HTML_SELECTORS:
                for element in soup.select(selector):
                    element.decompose()

            structure["headings"] = _build_headings(soup)
            structure["sections"] = _build_sections(soup)
            structure["word_count"] = len(soup.get_text().split())

        except Exception as e:
            logger.warning(f"Error extracting HTML structure: {e}")
            structure["error"] = str(e)

        return structure

    def extract_html_links_from_parsed(self, parsed: ParsedHTML) -> Dict[str, Any]:
        """Extract links from pre-parsed HTML content.

        More efficient when used with parse_html() for multiple operations.

        Args:
            parsed: Pre-parsed HTML container

        Returns:
            Dictionary containing link information
        """
        # Links extraction is read-only, so we can use the original soup
        return self._extract_links_from_soup(parsed.soup_for_reading)

    def extract_html_links(self, html_content: str) -> Dict[str, Any]:
        """
        Extract links from HTML content.

        Args:
            html_content: HTML content to analyze

        Returns:
            Dictionary containing link information
        """
        try:
            soup = BeautifulSoup(html_content, HTML_PARSER)
            return self._extract_links_from_soup(soup)
        except Exception as e:
            logger.warning(f"Error extracting HTML links: {e}")
            return {
                "internal_links": [],
                "external_links": [],
                "media_links": [],
                "error": str(e),
            }

    def _extract_links_from_soup(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract links from a BeautifulSoup object.

        Args:
            soup: BeautifulSoup object (read-only operation)

        Returns:
            Dictionary containing link information
        """
        links_data: Dict[str, Any] = {
            "internal_links": [],
            "external_links": [],
            "media_links": [],
        }
        try:
            for link in soup.find_all("a", href=True):
                if not isinstance(link, Tag):
                    continue
                _classify_anchor(link, links_data)

            for tag, attr, media_type in _MEDIA_SELECTORS:
                for element in soup.find_all(tag):
                    if not isinstance(element, Tag):
                        continue
                    _append_media_link(element, attr, media_type, links_data)

        except Exception as e:
            logger.warning(f"Error extracting HTML links: {e}")
            links_data["error"] = str(e)

        return links_data
