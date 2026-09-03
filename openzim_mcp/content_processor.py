"""Content processing utilities for OpenZIM MCP server."""

import logging
import re
import unicodedata
from typing import Any, Callable, Dict, List, Optional, Tuple, Union, cast
from urllib.parse import urlparse

import html2text
from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from soupsieve import SelectorSyntaxError

from .constants import (
    DEFAULT_SNIPPET_LENGTH,
    FURNITURE_HEADING_DENYLIST,
    FURNITURE_HEADING_PREFIXES,
    UNWANTED_HTML_SELECTORS,
)
from .recovery_advice import fetch_binary
from .title_promotion import _DISCRIMINATOR_STOP_WORDS

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


_BLOCK_CELL_SEPARATOR = "\x00"  # internal sentinel; replaced post-collapse

# Stack marker for "the children of a block-level tag have all been
# emitted; write its CLOSING separator now". A bare ``object()`` (never a
# ``str``) so the identity test below can never collide with a
# ``NavigableString`` that happens to compare equal to a marker value.
_CELL_CLOSE = object()


def _join_cell_text(cell: Tag) -> str:
    """Extract a table-cell's text, separating block-level children
    with a value-separator (``; ``) and concatenating inline children
    directly.

    This is the safer alternative to ``cell.get_text(separator=" ")``:
    the BeautifulSoup default emits the separator between EVERY
    descendant Tag's text, which corrupts inline span groups used
    for number formatting (``3,913,644``), units (``891.3``), and
    coordinate templates. Iterating descendants ourselves and only
    inserting a separator at block-level tag boundaries (``<br>``,
    ``<li>``, ``<p>``) keeps the inline forms intact while flagging
    multi-value cells with an explicit value boundary.

    a13 D7: the previous version emitted a bare ``" "`` at block
    boundaries, which left ``<td>5th in Europe<br>1st in Germany</td>``
    rendering as ``5th in Europe 1st in Germany`` — a downstream LLM
    saw the two values as one continuous phrase. Emit ``"; "``
    instead so the cell value reads as
    ``5th in Europe; 1st in Germany`` — two distinct items, same row.

    A sentinel character (``\\x00``) marks the block boundary during
    traversal, then the post-collapse pass converts it to ``"; "``.
    This preserves the existing whitespace-collapse semantics
    (so ``"New York"`` from inline spans survives) without the sentinel
    being absorbed into a whitespace run.

    The sentinel is emitted at both the OPEN and CLOSE of a block-level
    child: a flat descendants walk only sees the opening position, so
    text following a closed block child (``<div>5th in Europe</div>1st
    in Germany``) glued directly onto the block's last text. Adjacent /
    leading / trailing sentinels are collapsed by the post-pass, so the
    double emission is harmless for block-then-block shapes.

    The traversal uses an EXPLICIT stack rather than recursion: ``html.parser``
    does not auto-close inline tags, so an infobox cell containing N unclosed
    ``<i>``/``<span>`` tags produces an N-deep tree and a recursive walk hit
    ``RecursionError`` at roughly 900 levels — aborting the whole article
    render (``compact=True``) and propagating out of ``_extract_infobox``.
    A ``_CELL_CLOSE`` marker pushed under a block tag's children reproduces
    the recursive version's closing-separator emission exactly.
    """
    parts: List[str] = []
    sep = f" {_BLOCK_CELL_SEPARATOR} "
    stack: List[Any] = list(cell.children)[::-1]
    while stack:
        el = stack.pop()
        # Identity check first: the marker is a bare ``object()``, so it can
        # never be confused with document content.
        if el is _CELL_CLOSE:
            parts.append(sep)
            continue
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
        elif isinstance(el, Tag):
            is_block = el.name in _BLOCK_CELL_TAGS
            if is_block:
                parts.append(sep)
                # Popped only after every child below has been emitted.
                stack.append(_CELL_CLOSE)
            stack.extend(list(el.children)[::-1])

    # Collapse whitespace per chunk while preserving sentinels, then
    # convert sentinels to the user-facing separator. Adjacent
    # sentinels (empty block boundaries from nested ``<ul>`` → ``<li>``)
    # collapse to a single separator and leading/trailing sentinels
    # are dropped so cells whose only block-level children are empty
    # wrappers don't render with stray ``; `` prefixes.
    raw = "".join(parts)
    chunks = [c.strip() for c in raw.split(_BLOCK_CELL_SEPARATOR)]
    chunks = [" ".join(c.split()) for c in chunks if c.strip()]
    return "; ".join(chunks)


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

# URL schemes that mark an extracted link as pointing outside the archive.
# These are classified, never fetched: the server reads links out of
# archived HTML and reports where they point.
EXTERNAL_LINK_SCHEMES = ("http", "https")


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


def _fold_with_index_map(text: str) -> Tuple[str, List[int]]:
    """Fold ``text`` and return ``(folded, index_map)``.

    ``index_map[i]`` is the index in the ORIGINAL ``text`` of the character
    that produced ``folded[i]``.

    ``_fold`` is not length-preserving — ``_fold("ﬁ") == "fi"``, ``_fold("½")
    == "1⁄2"``, and a lone combining mark folds away to ``""`` — so folding
    the whole string in one call and reusing its offsets against the original
    misaligns. Folding one character at a time and recording the source index
    for every emitted character keeps the mapping exact regardless of how
    many characters each input expands or collapses to.
    """
    out: List[str] = []
    index_map: List[int] = []
    for i, ch in enumerate(text):
        folded_ch = _fold(ch)
        if not folded_ch:
            continue
        out.append(folded_ch)
        index_map.extend([i] * len(folded_ch))
    return "".join(out), index_map


# A query term, plus the trailing ``*`` that marks it as a PREFIX probe.
# Xapian honours ``*`` only at the END of a term, so that is the only
# position treated as a wildcard here: ``a*b`` reads as two ordinary terms,
# exactly as Xapian reads it.
_QUERY_TERM_RE = re.compile(r"(\w+)(\*?)")

# Shortest prefix term that is allowed to match beyond its own characters.
# Higher than the 3-char floor literal terms use: a 3-char prefix is too
# unselective to be informative (``car*`` bolds carbon, cardiac, carry and
# careful alike). Mirrors ``_RELEVANCE_STEM_MIN_LEN`` in
# :mod:`openzim_mcp.zim.search`, the existing "shortest prefix that counts
# as a stem" constant.
_PREFIX_TERM_MIN_LEN = 4


def _split_query_terms_typed(query: str) -> List[Tuple[str, bool]]:
    """``(term, is_prefix)`` pairs; ``diabet*`` -> ``("diabet", True)``.

    WHY the flag: the ``*`` used to be dropped as punctuation, so a
    truncated term could only ever be matched whole-word — and ``diabet``
    is never a whole word, so the very hit Xapian's stemmer found went
    unhighlighted and could even anchor a different paragraph.
    """
    return [
        (m.group(1), bool(m.group(2))) for m in _QUERY_TERM_RE.finditer(_fold(query))
    ]


def _split_query_terms(query: str) -> list:
    """Split a query string into individual terms; drop punctuation."""
    return [t for t, _ in _split_query_terms_typed(query)]


def _word_in(folded_paragraph: str, term: str, *, prefix: bool = False) -> bool:
    """Whole-word match of `term` in already-folded paragraph text.

    With ``prefix=True`` the term only has to open a word (``climat*``
    matches ``climate``), so paragraph selection agrees with what
    ``_highlight_terms`` will actually bold.
    """
    tail = r"\w*" if prefix else r"\b"
    return bool(re.search(rf"\b{re.escape(term)}{tail}", folded_paragraph))


def _keep_highlightable_terms(query: str) -> List[Tuple[str, bool]]:
    """Query terms long enough to be worth matching, with their prefix flag.

    The highlighting set, and the base the anchoring set is drawn from by
    :func:`_keep_anchorable_terms` — anchoring narrows this further, so the
    paragraph a snippet starts on is still always one the highlighter can
    mark up.
    """
    return [
        (term, is_prefix)
        for term, is_prefix in _split_query_terms_typed(query)
        if len(term) >= (_PREFIX_TERM_MIN_LEN if is_prefix else 3)
    ]


def _keep_anchorable_terms(
    typed: List[Tuple[str, bool]],
) -> List[Tuple[str, bool]]:
    """The subset of ``typed`` specific enough to anchor a snippet on.

    Length alone is a poor filter for anchoring: ``what``, ``does`` and
    ``about`` all clear the three-character bar, so a natural-language
    question anchored on whichever paragraph first said "what" — for
    ``what causes migraines`` that was an article's lead sentence about
    "becoming what one is", 11k chars above the paragraph that actually
    discussed migraines. Highlighting keeps the full term set; only the
    anchor decision drops function words.

    Falls back to ``typed`` when filtering empties the list, so an
    all-function-word query keeps its previous behavior instead of
    silently anchoring every result on the lead.
    """
    content_terms = [
        (term, is_prefix)
        for term, is_prefix in typed
        if term not in _DISCRIMINATOR_STOP_WORDS
    ]
    return content_terms or typed


# A complete ``[text](href "title")`` markdown link, matched as ONE unit.
# Shared by all three link regexes below so a fix here can't be applied to
# only one of them.
#
# ``*`` (not ``+``) on the link text so EMPTY-text links ``[](url)`` — the
# shape ZIMIT/warc2zim emits for inline images with no alt text — are
# recognised too; otherwise a query term inside the image URL, e.g.
# ``[](../media/plato.jpg)`` for query "plato", got bolded into
# ``[](../media/**plato**.jpg)`` and broke the path.
#
# ``(?:\\.|[^\n)\\])*`` consumes backslash-escaped parens atomically so only
# an UNESCAPED ``)`` closes the link: html2text emits ``Mercury_\(planet\)``
# for parenthetically-disambiguated titles, and the previous ``[^\n)]*``
# stopped at the first ESCAPED paren — leaving the trailing ``"title")``
# unprotected and defeating the dangling-link repair below.
_LINK_RE_SRC = r"\[[^\]\n]*\]\((?:\\.|[^\n)\\])*\)"

# Regions inside which a query-term match must NOT be wrapped in a second
# layer of emphasis: it produces malformed markdown (e.g. ``**Artificial
# **photosynthesis****`` from a bold heading, ``_****Berlin****_`` from
# italic disambig links, ``[**Photosynthesis**](**Photosynthesis** "…")``
# where bolding inside the link target breaks the URL).
#
# - ``_LINK_RE_SRC`` — a full link, so the URL/tooltip parenthetical only
#   counts when it's attached to a link. An earlier shape matched any
#   ``(...)`` parenthetical — that protected ordinary prose parentheticals
#   like ``(also called assimilation)`` from highlighting too, silently
#   dropping query-term visibility for any term that landed inside them.
#   (Wikipedia scientific articles are loaded with parenthetical gloss;
#   over-protecting them cost more highlights than it saved.)
# - ``\*\*[^*\n]+\*\*`` — existing bold runs (paired markers, single line).
#   ``[^*\n]+`` rules out adjacent ``**`` runs and multi-paragraph spans.
# - ``(?<!\w)_[^_\n]+_(?!\w)`` — italic runs; the lookarounds skip
#   identifier-style underscores like ``foo_bar``.
# - ``` `[^`\n]+` ``` — inline code spans (rarely emitted by html2text on
#   Wikipedia, but cheap to skip and prevents bold-inside-code from
#   breaking code-formatted text).
_HIGHLIGHT_SKIP_RE = re.compile(
    _LINK_RE_SRC + r"|\*\*[^*\n]+\*\*" r"|(?<!\w)_[^_\n]+_(?!\w)" r"|`[^`\n]+`",
)

# A complete markdown link starting at a given ``[``.
_COMPLETE_LINK_RE = re.compile(_LINK_RE_SRC)
# A markdown link whose syntax started (``[`` with no closing ``]``, or
# ``[text](`` with no closing ``)``) but was cut off at end-of-string.
# The trailing ``\\?$`` handles a cut landing exactly on a lone backslash,
# which the escape-pair group cannot consume.
_DANGLING_LINK_RE = re.compile(r"\[[^\]\n]*$|\[[^\]\n]*\]\((?:\\.|[^\n)\\])*\\?$")


# Paragraphs that are site furniture rather than article text, as they
# appear in the compact markdown a snippet is cut from. Each pattern is
# matched against the whole paragraph (anchored), so prose that merely
# mentions the phrase is untouched.
#
# - The MedlinePlus ``<noscript>`` share-widget sentence, which sits
#   directly under every H1 on that corpus (13 of 30 ``insulin`` snippets
#   were that sentence and nothing else).
# - ``On this page`` / ``Skip navigation`` nav headers.
_BOILERPLATE_PARAGRAPH_RE = re.compile(
    r"^\s*(?:"
    r"to use the sharing features on this page, please enable javascript\.?"
    r"|on this page:?"
    r"|skip (?:to main content|navigation)"
    r")\s*$",
    re.IGNORECASE,
)

# One markdown list item: the marker and its text (outer whitespace
# excluded). The text must open with a non-space so the marker gap
# ``\s+`` has exactly one way to end; ``\s+(.*\S)`` let the two share a
# trailing space run and went quadratic on ``* `` + spaces.
_LIST_ITEM_RE = re.compile(r"^\s*(?:[*+-]|\d+[.)])\s+(\S(?:.*\S)?)\s*$")
# ``[text](url)`` -> ``text`` (empty-text image-wrapper links fold to "").
_LINK_TO_TEXT_RE = re.compile(r"\[([^\]\n]*)\]\((?:\\.|[^\n)\\])*\)")
_MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s")
# A leading H1 line and the line break(s) that close it: the heading text
# in group 1 (outer whitespace excluded), the match ending after the last
# newline of the blank run that follows. The text opens and closes on a
# non-space and the tail is ``(non-newline whitespace, newline)+`` so no
# two quantifiers compete for the same characters — the reluctant
# ``(.+?)\s*\n+`` it replaces re-scanned the gap for every candidate end
# and took minutes on ``# `` followed by a few thousand spaces.
_LEADING_H1_RE = re.compile(r"^\s*#\s+(\S(?:.*\S)?)(?:[^\S\n]*\n)+")
# Longest item still read as a navigation label rather than a sentence.
_NAV_ITEM_MAX_WORDS = 6
# A one-item "list" is a bullet, not a menu: too little shape to convict on.
_NAV_LIST_MIN_ITEMS = 2


def _is_nav_list_paragraph(paragraph: str) -> bool:
    """Whether ``paragraph`` is a list of navigation labels, not content.

    Site-scraped pages carry in-page menus (``* Summary`` / ``* Start
    Here`` / ``* Diagnosis and Tests``) and tables of contents as plain
    lists. Those read as short Title-Case labels with no sentence
    punctuation; a content list (``* Being very thirsty``, ``* Deep,
    rapid breathing``) does not, and is left alone.
    """
    lines = [line for line in paragraph.splitlines() if line.strip()]
    if len(lines) < _NAV_LIST_MIN_ITEMS:
        return False
    for line in lines:
        item = _LIST_ITEM_RE.match(line)
        if item is None:
            return False
        text = _LINK_TO_TEXT_RE.sub(r"\1", item.group(1)).strip()
        if not text or text[-1] in ".!?;:":
            return False
        words = re.findall(r"[^\W\d_]+", text)
        if not words or len(text.split()) > _NAV_ITEM_MAX_WORDS:
            return False
        if any(len(word) > 3 and not word[0].isupper() for word in words):
            return False
    return True


def _drop_boilerplate_paragraphs(
    paragraphs: List[str],
    is_query_hit: Optional[Callable[[str], bool]] = None,
) -> List[str]:
    """Remove site furniture from the paragraphs a snippet may be cut from.

    Dropped: known boilerplate sentences, navigation lists, headings that
    merely introduce a navigation list, and paragraphs with no visible
    text (an image-wrapper ``[](…)`` link and nothing else). When that
    would leave nothing, the original list is returned so a snippet is
    still produced.

    ``is_query_hit`` exempts a paragraph from the navigation-list rule
    alone. By shape a menu is indistinguishable from a Title-Case content
    list (sister cities, cast lists, official languages), and dropping the
    one paragraph that carries the search term before the anchor is chosen
    cost the snippet all its relevance — it silently fell back to the lead.
    The named boilerplate sentences stay unconditional; they are furniture
    whichever term matches them.
    """

    def _is_droppable_nav(index: int) -> bool:
        paragraph = paragraphs[index]
        if is_query_hit is not None and is_query_hit(paragraph):
            return False
        return _is_nav_list_paragraph(paragraph)

    keep: List[str] = []
    for index, paragraph in enumerate(paragraphs):
        visible = _LINK_TO_TEXT_RE.sub(r"\1", paragraph).strip()
        if not visible and index > 0:
            # Blank/image-only paragraph. Index 0 is left to the caller's
            # H1 handling so an empty leading slot never shifts it.
            continue
        if _BOILERPLATE_PARAGRAPH_RE.match(paragraph):
            continue
        if _is_droppable_nav(index):
            continue
        if (
            _MARKDOWN_HEADING_RE.match(paragraph)
            and index + 1 < len(paragraphs)
            and _is_droppable_nav(index + 1)
        ):
            continue
        keep.append(paragraph)
    return keep or list(paragraphs)


# An empty-text markdown link: what html2text leaves of a zimit
# anchor-wrapped image once ``ignore_images`` drops the <img>.
_EMPTY_LINK_RE = re.compile(r"\[\s*\]\((?:\\.|[^\n)\\])*\)")
# MathJax spans as html2text escapes them: ``\\( … \\)``, ``\\[ … \\]``
# and display ``$$ … $$``.
_MATHJAX_RE = re.compile(
    r"\\\\\((.+?)\\\\\)|\\\\\[(.+?)\\\\\]|\$\$(.+?)\$\$", re.DOTALL
)
# ``\text{…}``-style wrappers whose argument is the readable part.
_TEX_WRAPPER_RE = re.compile(
    r"\\(?:text|textit|textbf|textrm|textsf|texttt|mathrm|mathbf|mathit"
    r"|mathsf|mathtt|mathcal|mathbb|mathfrak|operatorname)\{([^{}]*)\}"
)
_TEX_COMMAND_RE = re.compile(r"\\([A-Za-z]+)")
_TEX_SYMBOLS = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "Gamma": "Γ",
    "delta": "δ",
    "Delta": "Δ",
    "epsilon": "ε",
    "varepsilon": "ε",
    "theta": "θ",
    "kappa": "κ",
    "lambda": "λ",
    "Lambda": "Λ",
    "mu": "μ",
    "nu": "ν",
    "pi": "π",
    "Pi": "Π",
    "rho": "ρ",
    "sigma": "σ",
    "Sigma": "Σ",
    "tau": "τ",
    "phi": "φ",
    "varphi": "φ",
    "Phi": "Φ",
    "chi": "χ",
    "psi": "ψ",
    "Psi": "Ψ",
    "omega": "ω",
    "Omega": "Ω",
    "aleph": "ℵ",
    "infty": "∞",
    "vDash": "⊨",
    "models": "⊨",
    "vdash": "⊢",
    "neg": "¬",
    "lnot": "¬",
    "land": "∧",
    "wedge": "∧",
    "lor": "∨",
    "vee": "∨",
    "to": "→",
    "rightarrow": "→",
    "Rightarrow": "⇒",
    "leftrightarrow": "↔",
    "Leftrightarrow": "⇔",
    "forall": "∀",
    "exists": "∃",
    "in": "∈",
    "notin": "∉",
    "subseteq": "⊆",
    "subset": "⊂",
    "cup": "∪",
    "cap": "∩",
    "emptyset": "∅",
    "leq": "≤",
    "le": "≤",
    "geq": "≥",
    "ge": "≥",
    "neq": "≠",
    "ne": "≠",
    "times": "×",
    "cdot": "·",
    "ldots": "…",
    "dots": "…",
}


def _tex_to_text(tex: str) -> str:
    """Render a TeX fragment as plain text: ``\\phi(\\kappa)`` -> ``φ(κ)``.

    Best effort for snippets, not a typesetter: wrapper macros keep their
    argument, known symbols become their Unicode glyph, unknown commands
    keep their name, grouping braces go, and escaped set braces stay.
    """
    tex = _TEX_WRAPPER_RE.sub(r"\1", tex)
    tex = tex.replace("\\\\{", "\x00").replace("\\\\}", "\x01")
    tex = _TEX_COMMAND_RE.sub(lambda m: _TEX_SYMBOLS.get(m.group(1), m.group(1)), tex)
    tex = tex.replace("{", "").replace("}", "")
    tex = tex.replace("\x00", "{").replace("\x01", "}")
    return re.sub(r"\s+", " ", tex).strip()


def _strip_snippet_render_junk(text: str) -> str:
    """Drop rendering leftovers that read as junk in a snippet.

    zimit archives wrap lead images in anchors; with images ignored the
    anchor survives as a zero-text ``[](../media/kant2.jpg)`` link. Pages
    using MathJax carry ``\\\\(\\phi(\\kappa)\\\\)`` — backslash soup once
    html2text has escaped it. Both go before the length cap so they stop
    consuming snippet budget.
    """
    text = _EMPTY_LINK_RE.sub("", text)
    return _MATHJAX_RE.sub(
        lambda m: _tex_to_text(next(g for g in m.groups() if g is not None)),
        text,
    )


def _select_snippet_paragraphs(
    paragraphs: List[str], start_idx: int, max_paragraphs: int
) -> List[str]:
    """Take ``max_paragraphs`` content paragraphs from ``start_idx``.

    Headings are context, not content: they do not fill a slot (a page
    whose lead is ``## Summary`` / ``### What is diabetes?`` used to yield
    those two lines and no prose), consecutive headings collapse to the
    one nearest the prose, and a heading with nothing under it is dropped.
    """
    selected: List[str] = []
    content_count = 0
    for paragraph in paragraphs[start_idx:]:
        if content_count >= max_paragraphs:
            break
        if _MARKDOWN_HEADING_RE.match(paragraph):
            if selected and _MARKDOWN_HEADING_RE.match(selected[-1]):
                selected[-1] = paragraph
            else:
                selected.append(paragraph)
            continue
        selected.append(paragraph)
        content_count += 1
    while len(selected) > 1 and _MARKDOWN_HEADING_RE.match(selected[-1]):
        selected.pop()
    return selected


def _truncate_before_dangling_link(text: str) -> str:
    """Back ``text`` up to before an unterminated trailing markdown link.

    M3: ``create_snippet`` truncates ``snippet_text[:cap]`` BEFORE highlighting.
    A cut landing inside a ``[text](url "title")`` construct leaves a dangling
    link; ``_HIGHLIGHT_SKIP_RE`` then no longer matches it (it requires a
    complete ``[..](..)``), so ``_highlight_terms`` bolds query terms inside the
    link text / URL — the exact malformed-markdown shape the skip-regex exists
    to prevent. Detect a dangling trailing link and drop the fragment, mirroring
    the existing dangling-``**`` repair. A bare bracket (``[1]`` / ``[edit]``
    with a closing ``]`` but no ``(``) is left alone — it is not a link.
    """
    open_idx = text.rfind("[")
    if open_idx == -1:
        return text
    tail = text[open_idx:]
    if _COMPLETE_LINK_RE.match(tail):
        return text
    if _DANGLING_LINK_RE.match(tail):
        return text[:open_idx].rstrip()
    return text


def _strip_dangling_bold(text: str) -> str:
    """Drop an unpaired trailing ``**`` left behind by truncation.

    A cut can land inside a ``**bold**`` span — whether the markers came
    from ``_highlight_terms`` or already existed in the source markdown
    (html2text emits ``**`` for ``<b>``/``<strong>``) — leaving an
    unmatched opening marker (e.g. ``…**ter``) that downstream markdown
    renderers treat as runaway bold. Detect the odd marker count and
    resolve the dangling fragment. The ``last_open == 0`` branch covers
    the rare case where the dangling ``**`` is at position 0 — the
    entire text is the start of the first bold span. Slicing
    ``text[:0]`` there would yield ``""`` and the caller would see a
    content-free ``"..."``; instead drop the orphan ``**`` marker and
    keep the term text so the snippet stays useful.
    """
    if text.count("**") % 2 == 1:
        last_open = text.rfind("**")
        if last_open > 0:
            return text[:last_open].rstrip()
        if last_open == 0:
            return text[2:].lstrip()
    return text


def _highlight_terms(text: str, query: str, *, max_hits: int) -> str:
    """Wrap the first `max_hits` occurrences of any query term in **bold**.

    Case- and diacritic-insensitive, preserving the original casing and
    accents of the matched substring. ``_split_query_terms`` folds the query
    (NFKD + strip combining + lower), so the pattern must be applied to an
    equally-folded haystack: matching folded terms against the raw text meant
    ``query="café"`` never highlighted anything, and ``query="cafe"`` never
    matched ``Café``. Paragraph selection already folds both sides — only
    highlighting was comparing across the fold.

    Skips matches that fall inside existing markdown emphasis (``**bold**``,
    ``_italic_``) or markdown link constructs (``[text](url "title")``):
    layering ``**…**`` on top of those produces malformed markdown that
    confuses small models more than it helps them.
    """
    typed = _keep_highlightable_terms(query)
    if not typed:
        return text
    # Longest first: alternation is first-match-wins, so a short term must
    # not shadow a longer alternative sharing its opening characters.
    typed.sort(key=lambda tp: len(tp[0]), reverse=True)
    # A prefix term closes on ``\w*`` — the remainder of the word the
    # stemmer matched; a literal term keeps its closing ``\b``. Both keep
    # the leading ``\b``: Xapian prefixes anchor at a word start, so
    # ``diabet*`` must not light up the middle of ``prediabetes``.
    alts = [
        re.escape(term) + (r"\w*" if is_prefix else r"\b") for term, is_prefix in typed
    ]
    # No ``re.IGNORECASE``: both sides are already lowercased by the fold.
    # The group is non-capturing — only ``m.start()``/``m.end()`` are read.
    pattern = re.compile(r"\b(?:" + "|".join(alts) + r")")
    folded, index_map = _fold_with_index_map(text)

    # Pre-compute spans where we must not wrap. Overlapping markdown
    # constructs (a link inside a bold span, etc.) are collapsed into a
    # single forbidden-position bitmap so the term-replacement pass can
    # do a single membership check per match. These are ORIGINAL-text
    # offsets, so match positions are mapped back before being tested.
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

    # Collect the spans to bold, left to right, so ``max_hits`` selects the
    # same occurrences the old ``pattern.sub`` pass did.
    spans: List[Tuple[int, int]] = []
    for m in pattern.finditer(folded):
        if len(spans) >= max_hits:
            break
        # Map the folded span back onto the original. The end is derived from
        # the LAST matched folded character rather than from ``index_map[fe]``
        # so a match covering only part of a one-to-many expansion (``ﬁ`` ->
        # ``fi``) still spans the whole source character instead of collapsing
        # to a zero-width slice.
        start = index_map[m.start()]
        end = index_map[m.end() - 1] + 1
        if _is_forbidden(start):
            continue
        spans.append((start, end))

    # Splice in REVERSE so earlier offsets stay valid as markers are inserted.
    out = text
    next_start = len(text)
    for start, end in reversed(spans):
        if end > next_start:
            continue  # defensive: overlapping map-backs are never doubled
        out = f"{out[:start]}**{out[start:end]}**{out[end:]}"
        next_start = start
    return out


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


# Main-content landmarks, in priority order. ZIMIT / warc2zim entries embed
# the origin site's full chrome (federal banner, header nav, footer, aside
# sidebars) around the article body. Scoping content extraction to the
# main-content landmark drops that chrome at the source, so every bundle
# consumer (summary, TOC, related-article links) and the search-snippet
# renderer see the article body only. Wikipedia / mwoffliner pages carry no
# such landmark, so the helper returns the document unchanged and their
# behaviour is preserved.
#
# ``<article>`` is tried FIRST (narrower) so that when a ``<main>`` /
# ``[role=main]`` wrapper contains both the article and an ``<aside>``
# sidebar, the single article wins and the sidebar is excluded.
_MAIN_CONTENT_SELECTORS = ("article", "main", "[role=main]")

_HEADING_NAMES = ("h1", "h2", "h3", "h4", "h5", "h6")


def _normalize_heading_text(text: str) -> str:
    """Lowercase, collapse whitespace, and trim trailing punctuation so a
    heading can be matched against the furniture denylist / prefixes."""
    collapsed = re.sub(r"\s+", " ", text).strip().lower()
    return collapsed.rstrip(" :.–—")


def _is_furniture_heading(text: str) -> bool:
    """True if a heading is furniture: an EXACT denylist member, or a PREFIX
    match for a variable-suffix label (e.g. ``Review Date 2/10/2023``).

    Prefix matching requires the prefix to be the whole string or to be
    followed by a space, so ``review dates of treaties`` does NOT match the
    ``review date`` prefix.
    """
    norm = _normalize_heading_text(text)
    if norm in FURNITURE_HEADING_DENYLIST:
        return True
    return any(
        norm == prefix or norm.startswith(prefix + " ")
        for prefix in FURNITURE_HEADING_PREFIXES
    )


def _strip_furniture_sections(soup: BeautifulSoup) -> None:
    """Remove in-article "furniture" sections in place (MedlinePlus etc.).

    A furniture heading (see :func:`_is_furniture_heading`) is removed together
    with everything that follows it — its body, bare text nodes, and any deeper
    sub-headings — up to, but not including, the next heading of the SAME OR
    HIGHER level, so a denylisted ``<h2>`` takes its ``<h3>`` children with it
    but never bleeds into the next peer section.

    Matching is exact / bounded-prefix (never loose substring), so a real
    section like "Learn More About Diabetes" survives the "learn more" entry.
    The walk re-runs after each removal so decomposed siblings can't invalidate
    it. Call sites must gate this to landmark-scoped content only (see
    ``select_main_content``) so chrome-free pages stay byte-identical.

    Note: the extent is computed over DIRECT siblings of the heading, which
    covers MedlinePlus's flat ``<article>`` layout. A furniture heading wrapped
    in its own block (heading and body not siblings) is not handled — validate
    against a live archive before broadening.
    """
    while True:
        target: Optional[Tag] = None
        for heading in soup.find_all(_HEADING_NAMES):
            if not (isinstance(heading, Tag) and heading.name):
                continue
            if _is_furniture_heading(heading.get_text()):
                target = heading
                break
        if target is None:
            return
        level = int(target.name[1])
        # Materialise the sibling list BEFORE removing anything (decomposing
        # mutates the sibling chain). ``next_siblings`` (unlike
        # ``find_next_siblings``) also yields bare NavigableString nodes, so
        # loose furniture text between headings is removed too.
        doomed: List[Any] = [target]
        for sibling in list(target.next_siblings):
            if (
                isinstance(sibling, Tag)
                and sibling.name in _HEADING_NAMES
                and int(sibling.name[1]) <= level
            ):
                break
            doomed.append(sibling)
        for node in doomed:
            if isinstance(node, Tag):
                node.decompose()
            else:
                node.extract()  # NavigableString has no decompose()


# In-page navigation blocks on ZIMIT/warc2zim pages. MedlinePlus renders its
# "On this page" menu as ``<section id="toc-section">`` INSIDE the <article>
# landmark — not a <nav>, no ``.toc`` class, group labels as <h3>, label as a
# <span> — so it survived landmark scoping, ``UNWANTED_HTML_SELECTORS`` and
# the heading-keyed furniture strip, and opened every topic page's body,
# summary slice, and lead. Detected by SHAPE rather than by site id so the
# next archive with the same pattern is covered: a nav/section/div whose
# anchors ALL point at same-page fragments, with at least a few of them and
# no prose of its own. Only containers are candidates — a bare <ol> of
# fragment links (IEP's "Table of Contents") is left alone.
_IN_PAGE_NAV_CONTAINERS = ["nav", "section", "div"]
_IN_PAGE_NAV_MIN_LINKS = 3
_IN_PAGE_NAV_MAX_PARAGRAPH_CHARS = 80
_IN_PAGE_NAV_MAX_NON_LINK_CHARS = 200


def _is_in_page_nav(node: Tag) -> bool:
    """True if ``node`` is a link menu that only points into the same page."""
    anchors = [a for a in node.find_all("a") if isinstance(a, Tag) and a.get("href")]
    if len(anchors) < _IN_PAGE_NAV_MIN_LINKS:
        return False
    if not all(str(a.get("href")).startswith("#") for a in anchors):
        return False
    for paragraph in node.find_all("p"):
        if (
            isinstance(paragraph, Tag)
            and len(paragraph.get_text(strip=True)) > _IN_PAGE_NAV_MAX_PARAGRAPH_CHARS
        ):
            return False
    link_chars = sum(len(a.get_text(strip=True)) for a in anchors)
    non_link_chars = len(node.get_text(strip=True)) - link_chars
    if non_link_chars > _IN_PAGE_NAV_MAX_NON_LINK_CHARS:
        return False
    # A menu is its links; whatever else it carries are group labels, so the
    # links must outweigh them. Without this a Wikipedia ``div.reflist`` --
    # ``^`` backlinks to ``#cite_ref-N`` wrapping short citations -- and any
    # short article whose wrapper holds a lead paragraph plus a fragment TOC
    # both read as pure nav, and the whole References list / article body was
    # decomposed.
    return non_link_chars <= link_chars


def _strip_in_page_nav(soup: BeautifulSoup) -> None:
    """Remove same-page link menus in place (see ``_is_in_page_nav``).

    Outermost match wins: the MedlinePlus block nests ``#toc-section`` >
    ``#table-of-contents`` > ``.toccolumn``, all of which match on their
    own, so descendants of a doomed container are skipped rather than
    decomposed twice. Call sites must gate this to landmark-scoped content
    (``select_main_content``) so chrome-free pages stay byte-identical.
    """
    doomed = [
        node
        for node in soup.find_all(_IN_PAGE_NAV_CONTAINERS)
        if isinstance(node, Tag) and _is_in_page_nav(node)
    ]
    doomed_ids = {id(node) for node in doomed}
    for node in doomed:
        if any(id(parent) in doomed_ids for parent in node.parents):
            continue
        node.decompose()


def select_main_content(soup: BeautifulSoup) -> BeautifulSoup:
    """Return the page's main-content subtree, or ``soup`` if none is clear.

    Tries ``<article>``, then ``<main>``, then ``[role=main]``. A landmark
    is used only when EXACTLY ONE matches AND it carries text — multiple
    matches (e.g. a blog index rendered as many ``<article>`` cards) are
    ambiguous, and an empty/whitespace-only landmark would silently drop the
    real content when it sits in a sibling; in both cases we fall through to
    the next selector and ultimately to the whole document.

    The matched landmark is re-parsed into its OWN document rather than
    returned as a detached child ``Tag``: downstream rendering calls
    BeautifulSoup-only APIs (``new_tag`` during oversized-table replacement),
    which a bare child ``Tag`` does not expose. Re-parsing keeps the return
    type a full ``BeautifulSoup`` for every caller and code path.
    """
    for selector in _MAIN_CONTENT_SELECTORS:
        nodes = soup.select(selector)
        if len(nodes) == 1 and nodes[0].get_text(strip=True):
            scoped = BeautifulSoup(str(nodes[0]), HTML_PARSER)
            # Only landmark-scoped content gets the furniture and in-page
            # nav strips; the whole-document fallback below stays
            # byte-identical.
            _strip_furniture_sections(scoped)
            _strip_in_page_nav(scoped)
            if scoped.get_text(strip=True):
                return scoped
            # Restore-if-empty, as _drop_boilerplate_paragraphs does: both
            # strips match on shape, so a short article that is all furniture
            # heading or all fragment links by shape would otherwise be served
            # as nothing at all. Better a page of menu than a blank entry.
            return BeautifulSoup(str(nodes[0]), HTML_PARSER)
    return soup


def _unwanted_descendant_ids(heading: Tag) -> set:
    """Ids of ``UNWANTED_HTML_SELECTORS`` subtrees inside ``heading``.

    Shared by :func:`_heading_visible_text` and :func:`_heading_line_text`
    so both reason about the same excluded set — a heading's ``[edit]``
    link must be invisible to the locator and to the display text alike.
    """
    unwanted_ids: set = set()
    for selector in UNWANTED_HTML_SELECTORS:
        try:
            for el in heading.select(selector):
                unwanted_ids.add(id(el))
        except (SelectorSyntaxError, NotImplementedError) as exc:
            # The only two failures soupsieve raises from ``select``: a
            # malformed selector, and a pseudo-class the installed engine
            # does not implement. One unusable selector must not cost the
            # heading its whole cleanup, but a bare ``except Exception``
            # would also swallow the diagnostic — a typo in
            # UNWANTED_HTML_SELECTORS looks exactly like a selector that
            # legitimately matched nothing.
            logger.debug("heading cleanup skipped selector %r: %s", selector, exc)
            continue
    return unwanted_ids


def _heading_line_text(heading: Tag) -> str:
    """Visible heading text up to the first ``<br>``, or ``""`` if none.

    html2text turns a ``<br>`` inside a heading into a real newline and
    pushes everything after it onto the *following* markdown line, while
    :func:`_heading_visible_text` concatenates the whole subtree into one
    string. Every matcher in ``bundle._compute_section_offsets`` is
    line-anchored (``^#+ ...$`` under ``re.MULTILINE``), so none of them
    can bridge that break and the heading — with its entire section — was
    dropped from the bundle.

    Returning ``""`` for a heading with no ``<br>`` keeps this a strictly
    additive fallback: callers use the full text as before and only reach
    for this when the break is what defeated them.
    """
    if heading.find("br") is None:
        return ""
    unwanted_ids = _unwanted_descendant_ids(heading)
    parts: List[str] = []
    for node in heading.descendants:
        if isinstance(node, Tag) and node.name == "br":
            break
        if not isinstance(node, NavigableString) or isinstance(node, Comment):
            continue
        if any(id(parent) in unwanted_ids for parent in node.parents):
            continue
        parts.append(str(node))
    return "".join(parts).strip()


def _heading_visible_text(heading: Tag) -> str:
    """Heading text as the rendered markdown will show it.

    ``_render_soup_to_text`` strips ``UNWANTED_HTML_SELECTORS`` before
    rendering, but heading collection runs on the unstripped tree — so a
    heading like ``History<span class="mw-editsection">[edit]</span>`` or
    ``Etymology<sup class="reference">[1]</sup>`` got text the rendered
    markdown never contains, and its section silently vanished from the
    bundle (the preceding section's slice absorbed it). Exclude those
    subtrees here, without mutating the tree (link extraction still runs
    on the same soup afterwards).
    """
    unwanted_ids: set = set()
    for selector in UNWANTED_HTML_SELECTORS:
        try:
            for el in heading.select(selector):
                unwanted_ids.add(id(el))
        except (SelectorSyntaxError, NotImplementedError) as exc:
            # The only two failures soupsieve raises from ``select``: a
            # malformed selector, and a pseudo-class the installed engine
            # does not implement. One unusable selector must not cost the
            # heading its whole cleanup, but the previous bare ``except
            # Exception: continue`` also swallowed the diagnostic — a typo
            # in UNWANTED_HTML_SELECTORS looked exactly like a selector
            # that legitimately matched nothing.
            logger.debug("heading cleanup skipped selector %r: %s", selector, exc)
            continue
    if not unwanted_ids:
        return str(heading.get_text()).strip()
    parts: List[str] = []
    for s in heading.find_all(string=True):
        # ``find_all(string=True)`` yields ``Comment`` nodes as well —
        # the ``get_text()`` branch above drops them, and html2text never
        # renders them, so keeping them here would make the heading text
        # unmatchable against the rendered markdown. Same guard as
        # ``_join_cell_text``.
        if isinstance(s, Comment):
            continue
        if any(id(parent) in unwanted_ids for parent in s.parents):
            continue
        parts.append(str(s))
    return "".join(parts).strip()


def _build_headings(
    soup: BeautifulSoup, include_line_text: bool = False
) -> List[Dict[str, Any]]:
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

    ``include_line_text`` adds a ``line_text`` key carrying
    :func:`_heading_line_text` for headings broken by a ``<br>``. It is
    opt-in because this dict is also the wire payload of
    ``zim_get(view="structure")`` — only ``bundle``, which has to *locate*
    the heading in rendered markdown, needs the extra field, and the
    client-facing shape must not change to serve it.
    """
    headings: List[Dict[str, Any]] = []
    slug_counts: Dict[str, int] = {}
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        if not (isinstance(heading, Tag) and heading.name):
            continue
        text = _heading_visible_text(heading)
        if not text:
            continue
        anchor_id, id_source = resolve_heading_id(heading)
        if anchor_id and id_source == "slug":
            count = slug_counts.get(anchor_id, 0) + 1
            slug_counts[anchor_id] = count
            if count > 1:
                anchor_id = f"{anchor_id}_{count}"
        entry: Dict[str, Any] = {
            "level": int(heading.name[1]),
            "text": text,
            "id": anchor_id,
            "id_source": id_source,
            "position": len(headings),
        }
        if include_line_text:
            line_text = _heading_line_text(heading)
            if line_text and line_text != text:
                entry["line_text"] = line_text
        headings.append(entry)
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

    # Protocol-relative hrefs ("//host/path") carry no scheme but are still
    # external, so they are matched on the leading slashes instead.
    try:
        parsed = urlparse(href)
        scheme, netloc = parsed.scheme, parsed.netloc
    except ValueError:
        # urlparse raises ValueError("Invalid IPv6 URL") on an unbalanced
        # '[' in the authority ("http://[YOUR-DOMAIN]/x", "//[email
        # protected]"). Fall back to a string-only scheme split so one bad
        # anchor can't truncate extraction or abort a link-graph build.
        scheme, _, _ = href.partition(":")
        if any(c in scheme for c in "/?#"):
            scheme = ""
        netloc = ""
    if scheme.lower() in EXTERNAL_LINK_SCHEMES or href.startswith("//"):
        link_info["domain"] = netloc
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
            # H3: only collect "leaf" blocks — a <p>/<div> with no nested
            # heading / <p> / <div> descendant. ``element.get_text()`` includes
            # ALL descendant text, so collecting both a wrapper and its nested
            # blocks counted the same prose 2-3x (word_count 21 instead of 7 on
            # ``<div><div><p>…</p></div></div>``). Worse, a container <div>
            # holding the whole article body appears BEFORE its nested headings
            # in document order, so its get_text() dumped every later section's
            # text into the section preceding it. Collecting only leaf blocks
            # fixes both — wrapper text is gathered via its block children.
            if element.find(["h1", "h2", "h3", "h4", "h5", "h6", "p", "div"]) is None:
                _append_section_content(current_section, element)

    if current_section:
        sections.append(current_section)
    return sections


def paged_slice_length(content: str, max_length: int, current_offset: int = 0) -> int:
    """Characters of ``content`` that one page consumes.

    The single definition of how far a page advances, so the human-readable
    ``content_offset=N`` hint in the body and the machine-readable
    ``_meta.more_at_offset`` cannot drift apart — they did, and the copy that
    drifted silently glued the words on either side of a page boundary
    together. Both are derived from this.

    Trailing whitespace is emitted by neither page but consumed by neither
    either: it belongs to the next one. Leading whitespace is consumed only at
    the very top of the article, where no preceding page can own it.

    Deferral has a floor: when the whole mid-article slice is whitespace,
    deferring it to the next page defers it to *this* page again — the hint
    and ``more_at_offset`` would name the offset the caller is already at,
    and a client following either would loop forever. Such a page consumes
    its full slice, and ``truncate_content`` emits it verbatim so
    reassembly stays lossless.
    """
    if not content or len(content) <= max_length:
        return len(content)
    raw = content[:max_length]
    lead = len(raw) - len(raw.lstrip()) if current_offset == 0 else 0
    consumed = lead + len(raw[lead:].rstrip())
    return consumed if consumed else len(raw)


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
        tool_mode: str = "simple",
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
            tool_mode: Which tool set the client can see. Gates the recovery
                wording on the image branch of ``process_mime_content``,
                which names a tool the caller has to be able to issue.
                Defaults to the fail-safe mode (``simple`` registers
                ``zim_query`` alone), so a caller that forgets to thread it
                degrades to a ``zim_query``-shaped instruction rather than
                to an uncallable tool name.
        """
        self.snippet_length = snippet_length
        self._table_row_threshold = table_row_threshold
        self._table_char_threshold = table_char_threshold
        self._infobox_kv_limit = infobox_kv_limit
        self._tool_mode = tool_mode
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
                            # a13 D1: take the ORIGINAL parent (segment
                            # before the first ``—``), not the trailing
                            # segment. Pre-fix, France rendered as
                            # ``Government — • President`` →
                            # ``• President — • Prime Minister`` →
                            # ``• Prime Minister — • President of the
                            # Senate`` — each bullet row inherited the
                            # PREVIOUS bullet's full label, chaining
                            # them. ``split(" — ", 1)[0]`` keeps the
                            # constant ``"Government"`` parent across
                            # consecutive bullet rows (matching how
                            # Berlin's ``Government`` rows already
                            # render). Falls back to the full label
                            # when there's no ``—`` (the row had no
                            # parent prefix to begin with).
                            virtual_parent = prev_label.split(" — ", 1)[0]
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
            # M2: only remove the matched node when we actually extracted KV
            # rows. The KV loop only emits rows pairing a <th> with a <td>, so
            # a div-based infobox, a <td class="infobox-label"> layout, or any
            # non-table element matched by the broad ``.infobox`` / ``.vcard``
            # selectors yields zero rows — decomposing it then deleted the
            # content from the soup with no placeholder and no signal (compact
            # mode rendered neither the infobox markdown nor the original
            # element). Leave a zero-row node in place so its content still
            # renders, and try the next selector.
            if rows:
                node.decompose()
                return rows
            continue
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
        snippet_length: Optional[int] = None,
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

        effective_len = (
            snippet_length if snippet_length is not None else self.snippet_length
        )

        typed = _keep_highlightable_terms(query) if query else []
        terms = [t for t, _ in typed]
        # Function words are dropped from the anchor decision only; ``typed``
        # still drives highlighting further down.
        anchor_typed = _keep_anchorable_terms(typed) if typed else []
        anchor_terms = [t for t, _ in anchor_typed]

        # Site furniture (share-widget boilerplate, in-page navigation
        # lists) is neither a useful anchor nor useful fill: on MedlinePlus
        # the paragraph under every H1 was the no-JavaScript sentence, so
        # an H1 match produced a snippet with no article text at all. A
        # paragraph the query actually hits is kept regardless — see
        # ``_drop_boilerplate_paragraphs``. The exemption is keyed on the
        # anchorable terms because that is what it exists for: keeping the
        # paragraph the anchor will land on. Keyed on the full set, a nav
        # block survived for containing "what" and could never be chosen.
        paragraphs = _drop_boilerplate_paragraphs(
            content.split("\n\n"),
            is_query_hit=(
                (
                    lambda p: any(
                        _word_in(_fold(p), t, prefix=pfx) for t, pfx in anchor_typed
                    )
                )
                if anchor_typed
                else None
            ),
        )
        start_idx = 0

        if query:
            if terms:
                folded_paragraphs = [_fold(p) for p in paragraphs]
                # Pass 1: whole-word match (most precise — preserves the
                # Phase A #1 spec promise).
                whole_word_idx: Optional[int] = None
                for i, p in enumerate(folded_paragraphs):
                    if any(_word_in(p, t, prefix=pfx) for t, pfx in anchor_typed):
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
                    stems = [t[: max(4, (len(t) * 2 + 2) // 3)] for t in anchor_terms]
                    for i, p in enumerate(folded_paragraphs):
                        if any(stem in p for stem in stems):
                            start_idx = i
                            break

        selected = _select_snippet_paragraphs(paragraphs, start_idx, max_paragraphs)
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
        snippet_text = _strip_snippet_render_junk(snippet_text)

        # Truncate if too long. Reserve 3 chars for the trailing "..." so the
        # final string respects snippet_length rather than overshooting it.
        if len(snippet_text) > effective_len:
            cap = max(effective_len - 3, 0)
            # M3: repair a link the cut split before highlighting runs, so
            # _highlight_terms doesn't bold terms inside a now-dangling link.
            sliced = _truncate_before_dangling_link(snippet_text[:cap].rstrip())
            # The cut can also split a ``**bold**`` span that already
            # existed in the source markdown; repair it here since the
            # post-highlight repair only runs when highlighting pushed
            # the length back over the cap.
            snippet_text = _strip_dangling_bold(sliced)
            snippet_text += "..."

        if query:
            snippet_text = _highlight_terms(snippet_text, query, max_hits=5)
            # Re-check length after bold markers are inserted: they may push the
            # string over snippet_length. Hard-truncate if so, preserving the
            # trailing "..." sentinel so callers see a consistent format.
            if len(snippet_text) > effective_len:
                cap = max(effective_len - 3, 0)
                sliced = snippet_text[:cap].rstrip()
                # M3: a complete link can be re-split by this post-highlight
                # truncation; back up before a dangling link first, then let
                # the dangling-``**`` repair recount on the shortened slice.
                sliced = _truncate_before_dangling_link(sliced)
                # Truncation can land inside a ``**term**`` highlight,
                # leaving an unmatched opening marker; see
                # ``_strip_dangling_bold`` for the repair semantics.
                snippet_text = _strip_dangling_bold(sliced) + "..."

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

        Site-scraped archives suffix the title with the site name
        (``Type 1 diabetes: MedlinePlus Medical Encyclopedia``,
        ``Diabetes | … | MedlinePlus``) while the H1 carries the bare
        article name, so an H1 that the title *starts with*, up to a
        ``:``/``|``/dash separator, is the same duplicate and is stripped
        too. ``# Geography`` under title ``Berlin`` still stays.
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
        stripped = pattern.sub("", content, count=1)
        if stripped != content:
            return stripped
        leading_h1 = _LEADING_H1_RE.match(content)
        if leading_h1 is None:
            return content
        h1 = leading_h1.group(1).strip()
        folded_title = norm_title.lower()
        folded_h1 = h1.lower()
        if not folded_title.startswith(folded_h1):
            return content
        # Index the folded title by the FOLDED length: str.lower() expands
        # some characters ('İ' -> two code points), so the raw H1 length
        # would read the separator probe one character early.
        rest = folded_title[len(folded_h1) :].lstrip()
        if rest and rest[0] not in ":|-–—":
            return content
        return content[leading_h1.end() :]

    def truncate_content(
        self,
        content: str,
        max_length: int,
        *,
        current_offset: int = 0,
        paginatable: bool = True,
        original_total: Optional[int] = None,
        batch_item: bool = False,
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
            batch_item: When True, the continuation hint points at a
                single-entry ``entry_path`` call. Batch mode rejects
                ``content_offset`` (``zim_get`` returns
                ``invalid_path_combination``), so the default ``Pass
                content_offset=N`` tail was advice the emitting mode
                could not act on.

        Returns:
            Truncated content with metadata
        """
        if not content or len(content) <= max_length:
            return content

        # Strip the trailing whitespace for presentation but hand it to the
        # NEXT page rather than deleting it: ``next_offset`` below advances by
        # what was actually emitted, not by ``max_length``. Stripping both ends
        # while advancing the full page size dropped one run of whitespace at
        # every page boundary, so a caller following the footer's own
        # ``content_offset`` instruction and concatenating the pages got the
        # words on either side fused together.
        #
        # Leading whitespace is still trimmed at the top of the article, where
        # there is no preceding page for it to belong to; on later pages it is
        # exactly the boundary whitespace the previous page deferred.
        raw = content[:max_length]
        lead = len(raw) - len(raw.lstrip()) if current_offset == 0 else 0
        truncated = raw[lead:].rstrip()
        consumed = paged_slice_length(content, max_length, current_offset)
        if not truncated and current_offset > 0:
            # An all-whitespace mid-article page: ``paged_slice_length``
            # consumes the whole slice (see its deferral-floor note), so the
            # run must ship verbatim — an empty body here would drop it from
            # the reassembled document and fuse the words on either side.
            truncated = raw
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
        next_offset = current_offset + consumed

        if batch_item:
            # Batch entries are first-page only and the batch branch rejects
            # ``content_offset``; the working recovery is a single-entry call.
            tail = (
                " Batch entries return their first page only; for the rest, "
                "re-fetch this path with a single-entry `entry_path` call and "
                f"`content_offset={next_offset}`."
            )
        elif paginatable:
            # NO thousands separator here: unlike the human-readable counts
            # below, this value is copied back verbatim into the typed
            # ``content_offset`` parameter, and "100,000" is not a valid int
            # (``TypeAdapter(int).validate_python("100,000")`` raises).
            tail = f" Pass `content_offset={next_offset}` to read the next page."
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
        # where they are in the document. Both counts come from
        # ``consumed`` (what this page actually advanced by), not
        # ``max_length``: boundary whitespace is deferred to the next
        # page, so a 600-char cap that lands on a space emits 599 chars
        # and the hint says ``content_offset=599`` — the prose must not
        # contradict it by claiming 600.
        if current_offset > 0:
            body_desc = (
                f"showing chars {current_offset:,}–{next_offset:,} of "
                f"{full_length:,}-char body"
            )
        else:
            body_desc = (
                f"total of {full_length:,} characters of body content, "
                f"only showing first {consumed:,}"
            )

        return f"{truncated}\n\n... [Content truncated, {body_desc}.{tail}] ..."

    def process_mime_content(
        self,
        content_bytes: bytes,
        mime_type: str,
        *,
        compact: bool = False,
        snippet_mode: bool = False,
        scope_main_content: bool = False,
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
                if scope_main_content:
                    # Entry-content fetch (get_zim_entry / get_entries): scope
                    # to the page's main-content landmark so the primary read
                    # path drops ZIMIT/warc2zim site chrome, matching the
                    # bundle-based tools. No landmark -> whole document, so
                    # chrome-free (Wikipedia/mwoffliner) pages are unchanged.
                    soup = BeautifulSoup(raw_content, HTML_PARSER)
                    return self._render_soup_to_text(
                        select_main_content(soup), compact=compact
                    )
                return self.html_to_plain_text(raw_content, compact=compact)
            elif mime_type.startswith("text/"):
                return raw_content.strip()
            elif mime_type.startswith("image/"):
                # The phrasing is mode-aware: ``zim_get`` is not registered
                # in simple mode, where this line is just as reachable
                # (``zim_query('get article <image path>')`` renders it).
                return (
                    "(Image content - Cannot display directly; "
                    f"{fetch_binary(self._tool_mode)})"
                )
            else:
                return f"(Unsupported content type: {mime_type})"

        except Exception as e:
            logger.warning(f"Error processing content with MIME type {mime_type}: {e}")
            return f"(Error processing content: {e})"

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
                try:
                    _classify_anchor(link, links_data)
                except Exception as e:  # one bad anchor must not truncate
                    logger.warning(f"Skipping unparsable anchor: {e}")
                    links_data["error"] = str(e)

            for tag, attr, media_type in _MEDIA_SELECTORS:
                for element in soup.find_all(tag):
                    if not isinstance(element, Tag):
                        continue
                    _append_media_link(element, attr, media_type, links_data)

        except Exception as e:
            logger.warning(f"Error extracting HTML links: {e}")
            links_data["error"] = str(e)

        return links_data
