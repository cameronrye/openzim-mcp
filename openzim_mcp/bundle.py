"""Per-entry bundle extraction.

Phase C #11: First touch of an entry runs ONE HTML parse → produces a
single EntryBundle value cached under 'bundle:v2c:{validated_path}:{entry_path}'.
The four content-shape tools (get_entry_summary, get_table_of_contents,
get_article_structure, extract_article_links) and get_section all slice
into the bundle without re-parsing.

This module is intentionally pure: extract_entry_bundle takes an open
archive and returns the bundle. The cache-aware accessor
get_or_build_bundle handles cache lookups and is the entry point used
by the data-layer methods.
"""

from __future__ import annotations

import logging
import re
from itertools import groupby
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, cast

from openzim_mcp.tool_schemas import (
    EntryBundle,
    InfoboxData,
    InfoboxField,
    LinkBuckets,
    SectionMeta,
)

if TYPE_CHECKING:
    from libzim.reader import Archive  # type: ignore[import-untyped]

    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.content_processor import ContentProcessor

logger = logging.getLogger(__name__)


# v2d: SectionMeta grew ``heading_start`` — cached v2c bundles lack the
# field, so the narrow-slice fix would silently keep serving the child
# heading until TTL expiry without the key bump.
#
# v2e: the heading LOCATOR changed, so the same entry now yields sections a
# v2d bundle does not contain — an H1 whose title html2text italicises
# (``#  _2040_ (film)``) and a heading split across two lines by a ``<br>``
# were both dropped before. Nothing else in the key encodes the extractor's
# behaviour: it is keyed on the archive path, mtime, size, entry and render
# mode, all unchanged by a code fix. So without this bump an operator running
# with ``persistence_enabled`` restores a snapshot written by the previous
# release and keeps getting ``heading_count: 0`` for every affected article
# until the TTL expires — the fix silently inert on exactly the entries it
# was written for. Same reasoning as the v2c bump above; the rule is that a
# change to what a bundle CONTAINS needs a new prefix, not just a change to
# its shape.
# v2e -> v2f: the eighth pass fixed two more ways a real heading failed to be
# located — inline markup abutting the text beside it, and a link to a
# parenthetically-disambiguated article — so affected articles gain sections
# they previously lacked. Same rule as the bumps above: a change to what a
# bundle CONTAINS needs a new prefix.
# v2f -> v2g: duplicate explicit anchors are now disambiguated
# (``SH4b``, ``SH4b_2``), and ``section_id`` is the handle ``get_section``
# fetches by — so a v2f bundle does not just look different, it hands the
# caller ids that resolve to the wrong occurrence. Same rule as the bumps
# above.
_BUNDLE_KEY_PREFIX = "bundle:v2g"

# The stat token below tells a cached value that the ARCHIVE changed. Nothing
# told it that this SERVER changed what it renders from an unchanged archive,
# and every release does: 3.0.1 strips ``noscript`` and in-page nav menus and
# disambiguates duplicate anchors, which moves the rendered markdown, every
# offset derived from it, and the ``section_id`` fetch handles. The remedy
# used so far is a per-key prefix bump, which only protects the keys whose
# author remembered one — this release's bundle, entry and snippet keys were
# all missed. Folding an epoch into the token instead reaches every
# content-derived cache at once, because embedding the token is already the
# contract for all of them.
#
# Bump this in any release that changes what the server renders from an
# unchanged archive; tests/test_v3_cache_render_epoch.py fails until you do.
_RENDER_EPOCH = "r1"


def archive_stat_token(validated_path: Any) -> str:
    """Return ``<mtime_ns>:<size>:<epoch>`` (``"0:0:<epoch>"`` on OSError).

    Cache keys for any data derived from a ZIM file's contents should
    include this token so that an atomic file replacement (the typical
    monthly Wikipedia ZIM refresh) invalidates entries instead of
    serving stale data. The bundle cache uses it; namespace listings,
    binary metadata, and path-resolution caches all need the same
    guarantee.

    ``_RENDER_EPOCH`` extends that guarantee to the other way a cached
    value goes stale: the server, not the archive, changing what it
    renders. See the comment on the constant.

    Falls back to ``"0:0"`` when ``stat()`` fails (path removed, race
    with replacement) — the cache continues to function, just without
    the invalidation guarantee for that key. The epoch is still appended,
    so an upgrade invalidates those keys too.

    ``validated_path`` is typed loosely so callers don't have to import
    ``pathlib.Path``; a ``Path`` or a plain ``str`` path both work (a bare
    ``str`` has no ``.stat()``, so it is coerced to ``Path`` first).
    """
    try:
        if isinstance(validated_path, str):
            validated_path = Path(validated_path)
        st = validated_path.stat()
        return f"{st.st_mtime_ns}:{st.st_size}:{_RENDER_EPOCH}"
    except OSError:
        return f"0:0:{_RENDER_EPOCH}"


def _bundle_cache_key(validated_path: "Path", entry_path: str, compact: bool) -> str:
    """Cache key that invalidates when the underlying ZIM is replaced.

    Includes `st_mtime_ns` so an atomic file replacement (a monthly
    Wikipedia ZIM update) causes prior bundles to be reseen as cache
    misses rather than served as stale. `st_size` is included too —
    cheap defence-in-depth against filesystems with low-precision mtime
    or in-place rewrites that preserve the timestamp.

    The `compact` render mode is part of the key: a compact bundle
    (table placeholders) and a raw bundle (full tables) for the same
    entry are distinct entries and must never collide.

    Falls back gracefully when stat() fails (path no longer exists, race
    with replacement): the key drops to the prior shape so the cache
    still works, just without the invalidation guarantee.
    """
    mode = "compact" if compact else "raw"
    return (
        f"{_BUNDLE_KEY_PREFIX}:{validated_path}:"
        f"{archive_stat_token(validated_path)}:{entry_path}:{mode}"
    )


def _normalize_heading_text(text: str) -> str:
    """Match html2text's whitespace handling: collapse runs of whitespace."""
    return " ".join(text.split())


def _loose_escaped_text(text: str) -> str:
    r"""Return regex source matching ``text`` with optional backslash-escaping.

    html2text escapes markdown-significant punctuation by prefixing a
    backslash — a numbered heading ``1. Topic`` renders as ``1\. Topic``,
    so a plain ``re.escape`` pattern never matches and the section is dropped
    (this is the root cause of the IEP "flattened TOC": every ``## 1.``,
    ``## 2.`` ... H2 vanished, leaving the H3 subsections misnested under the
    H1). Allowing an optional backslash before each character matches the
    escaped and unescaped forms alike. Used only by the relaxed fallback, so
    the larger pattern is paid only for headings the strict match missed.

    A run of literal backslashes gets one bounded quantifier rather than a
    per-character optional escape: the surrounding inline-markup class also
    accepts backslashes, so per-character units let the engine split a run of
    n backslashes 2**n ways and backtrack for hours before conceding a miss.
    """
    parts: list[str] = []
    for is_backslash, group in groupby(text, key=lambda ch: ch == "\\"):
        chars = "".join(group)
        if is_backslash:
            parts.append(rf"\\{{{len(chars)},{2 * len(chars)}}}")
        else:
            parts.append("".join(r"\\?" + re.escape(ch) for ch in chars))
    return "".join(parts)


def _resolve_entry_html(
    archive: "Archive", entry_path: str
) -> tuple[str, str, str, str]:
    """Fetch the entry's HTML, returning (title, mimetype, html, resolved_path).

    Raises whatever the libzim layer raises; callers wrap.
    """
    entry = archive.get_entry_by_path(entry_path)
    item = entry.get_item()
    title = entry.title or "Untitled"
    mime = item.mimetype or ""
    html = bytes(item.content).decode("utf-8", errors="replace")
    # get_item() transparently follows redirects; item.path is the path of
    # the entry actually SERVED, and is what the relative hrefs in `html`
    # are relative to. For non-redirects it equals entry_path. The
    # ``isinstance(served, str)`` guard is load-bearing: the mock archives
    # used throughout the test suite are ``MagicMock``s whose ``item.path``
    # is itself a ``MagicMock`` (as is ``entry.is_redirect``, which is why
    # this must not branch on it).
    served = getattr(item, "path", None)
    resolved_path = served if isinstance(served, str) and served else entry_path
    return title, mime, html, resolved_path


def _extract_infobox(
    soup: Any, content_processor: "ContentProcessor"
) -> Optional[InfoboxData]:
    """Extract the first infobox as InfoboxData, or None if absent.

    Degrades to ``None`` on any extraction failure: every other step in
    ``extract_entry_bundle`` already survives malformed markup, and an
    infobox is supplementary. Without this, a pathological cell (e.g. one
    deeply nested enough to blow the recursion limit) propagated out of
    ``get_or_build_bundle`` and took summary/toc/structure/section with it.
    """
    try:
        rows = content_processor.extract_infobox(soup)
    except Exception as exc:
        logger.warning("Infobox extraction failed; continuing without: %s", exc)
        return None
    if not rows:
        return None
    fields: list[InfoboxField] = [
        {"label": r["label"], "value": r["value"]} for r in rows
    ]
    return cast("InfoboxData", {"fields": fields})


def _build_link_buckets(links_dict: Dict[str, Any]) -> LinkBuckets:
    """Convert extract_html_links() output into LinkBuckets.

    extract_html_links returns {'internal_links': [...], 'external_links': [...],
    'media_links': [...]} where each item already matches the LinkItem
    TypedDict (carrying 'url', 'type', and category-specific NotRequired
    fields). The bundle exposes these as-is so downstream consumers
    (extract_article_links, etc.) can pass bundle["links"][kind] straight
    into LinksResponse.results without re-mapping.
    """
    return cast(
        "LinkBuckets",
        {
            "internal": list(links_dict.get("internal_links", [])),
            "external": list(links_dict.get("external_links", [])),
            "media": list(links_dict.get("media_links", [])),
        },
    )


# Markdown link / image syntax emitted by html2text inside heading lines
# (``## [Linked](X) part``). The relaxed character-class pattern in
# ``_compute_section_offsets`` can't tolerate the brackets/URL, so headings
# containing an inline link were dropped from the bundle entirely.
# ``(?:[^()\n\\]|\\.)*`` rather than ``[^)]*``: html2text backslash-escapes
# parens inside a link target, so a heading linking to a
# parenthetically-disambiguated article — ``Mercury_\(mythology\)``, which is
# most disambiguated Wikipedia titles — stopped the old pattern at the first
# ``)`` and left ``Mercury (mythology) "Mercury (mythology)")`` behind. That
# never matches the soup-side visible text, so the heading was dropped, its
# section vanished from the bundle, and the PRECEDING section's slice ran on
# through it and swallowed its body. Each character belongs to exactly one
# branch, so the alternation is ReDoS-safe — the same form
# ``compact_format._MARKDOWN_LINK_RE`` already adopted for the CodeQL
# ``py/redos`` finding.
_MD_LINK_RE = re.compile(r"!?\[([^\]]*)\]\((?:[^()\n\\]|\\.)*\)")


# Emphasis-shaped underscore runs: those leading or trailing a word, which
# is the only position html2text emits them in for ``<i>``/``<em>``. An
# underscore *between* two alphanumerics (``snake_case``) is literal text and
# must survive — a blanket ``replace("_", "")`` would make the two sides of
# the comparison disagree for any heading whose text really carries one.
_MD_EMPHASIS_UNDERSCORE_RE = re.compile(r"(?<![^\W_])_+|_+(?![^\W_])")


def _strip_md_inline_decorations(line: str) -> str:
    """Reduce an html2text heading line to its visible text.

    Unwraps ``[text](url)`` / ``![alt](url)`` (repeatedly, for multiple
    links), drops emphasis/code markers, unescapes backslash-escaped
    punctuation, and collapses whitespace — the same visible text
    ``_heading_visible_text`` produces from the soup side.

    ``_`` is html2text's marker for ``<i>``/``<em>``, and dropping only
    ``*``/backtick left it in: Wikipedia italicises the work title in the
    H1 of every article about a film, book, album, or newspaper
    (``<h1><i>2040</i> (film)</h1>`` renders as ``#  _2040_ (film)``), so
    this comparison saw ``'_2040_ (film)'`` against ``'2040 (film)'``, the
    locator missed, and the article's only heading — with its whole
    section — was dropped from the bundle. Applied to both sides of the
    comparison (see :func:`_match_decorated_heading_line`), so the
    word-boundary rule cannot desynchronise them.
    """
    prev = None
    while prev != line:
        prev = line
        line = _MD_LINK_RE.sub(r"\1", line)
    line = line.replace("*", "").replace("`", "")
    line = re.sub(r"\\(.)", r"\1", line)
    line = _MD_EMPHASIS_UNDERSCORE_RE.sub("", line)
    return " ".join(line.split())


def _match_decorated_heading_line(
    rendered_markdown: str, level: int, text: str, cursor: int
) -> Optional[re.Match]:
    """Last-resort heading locator: scan ``#`` lines of the right level and
    compare their link-stripped visible text against the heading text."""
    # Normalise the soup side through the SAME reduction as the rendered
    # side. Only then is the emphasis-underscore rule above symmetric: a
    # heading whose text legitimately ends in ``_`` loses it on both sides
    # and still matches, instead of matching on neither.
    wanted = _strip_md_inline_decorations(text)
    line_re = re.compile(rf"^{'#' * level} (.+?)\s*$", re.MULTILINE)
    candidates = list(line_re.finditer(rendered_markdown, cursor))
    for m in candidates:
        if _strip_md_inline_decorations(m.group(1)) == wanted:
            return m
    # Last resort within the last resort: compare with the spaces removed.
    #
    # html2text emits a space after emphasis it closes even when the source
    # had none, so ``<h2><b>Foo</b>bar</h2>`` renders as ``## **Foo** bar``
    # while the soup side reads ``Foobar``. The decoration-stripped forms are
    # then ``'Foo bar'`` and ``'Foobar'`` and the exact pass above misses, so
    # the section is dropped from the bundle entirely — ``view="toc"`` never
    # lists it and ``zim_get_section`` answers ``section_not_found`` for it.
    # Code spans do not gain the space, which is why a ``<code>`` fixture
    # matches either way and this went unnoticed.
    #
    # Only reached when the section would otherwise be lost, and the two
    # sides still have to agree on every non-space character, so this cannot
    # promote a match the exact pass would have rejected on content.
    squashed = wanted.replace(" ", "")
    if squashed:
        for m in candidates:
            if _strip_md_inline_decorations(m.group(1)).replace(" ", "") == squashed:
                return m
    return None


def _locate_heading_text(
    rendered_markdown: str, level: int, text: str, cursor: int
) -> Optional[re.Match]:
    """Run the strict → relaxed → decorated matcher cascade for one spelling.

    Split out so a heading can be retried under a second spelling (see
    ``line_text`` in :func:`_compute_section_offsets`) without duplicating
    the cascade or reordering it.
    """
    # Strict pattern first; relaxed fallback covers html2text decorating
    # the heading text with inline markup (italics, bold, code spans)
    # that the soup-level get_text() stripped — without the fallback
    # those sections are silently absent from the bundle and
    # ``get_section`` returns "not found".
    strict = re.compile(
        rf"^{'#' * level} {re.escape(text)}\s*$",
        re.MULTILINE,
    )
    match = strict.search(rendered_markdown, cursor)
    if match is None:
        # H17: the relaxed pattern previously read
        # ``[^\n]*{re.escape(text)}[^\n]*$`` — a substring match that
        # accidentally picked up a heading like ``## Notes and See also``
        # when the bundle was probing for ``See also``. Constrain the
        # prefix/suffix to inline-markup characters html2text actually
        # emits (``*``, ``_``, ``` ` ```, backslashes, whitespace) so
        # the relaxed branch only catches decorated-heading cases, not
        # any heading containing the text anywhere.
        # Inline markup (``**bold**`` etc.) is tolerated as a prefix/suffix
        # wrapper; ``_loose_escaped_text`` additionally tolerates html2text's
        # backslash-escaped interior punctuation (e.g. ``1\.`` for ``1.``).
        _MD_INLINE = r"[ \t\*_`\\]*"
        relaxed = re.compile(
            rf"^{'#' * level} {_MD_INLINE}{_loose_escaped_text(text)}"
            rf"{_MD_INLINE}\s*$",
            re.MULTILINE,
        )
        match = relaxed.search(rendered_markdown, cursor)
    if match is None:
        # Inline links in the heading (``## [Linked](X) part``) carry
        # brackets and a URL the relaxed character class can't cover.
        match = _match_decorated_heading_line(rendered_markdown, level, text, cursor)
    return match


def _compute_section_offsets(
    rendered_markdown: str,
    headings: list[dict],
) -> list[SectionMeta]:
    """Locate each heading in rendered_markdown and emit SectionMeta.

    Headings in _build_headings() carry key 'id' (the resolved anchor slug).
    We search rendered_markdown in document order from the last cursor position
    so repeated identical headings are disambiguated correctly.

    Section ids are made unique here as well. ``_build_headings`` suffixes
    colliding *slugs* but deliberately passes author-provided anchors
    through untouched, so an archive that reuses an anchor name (the IEP
    has ``<a name="SH4b">`` twice on ~1% of articles) produced two TOC
    nodes with the same ``section_id`` — and ``get_section`` resolved both
    to the first. ``section_id`` is the tool's fetch handle, so the second
    and later occurrences get the same ``_2``/``_3`` ordinal the slug path
    uses. Only the repeats are renamed: the first occurrence keeps the real
    anchor, so in-archive ``#SH4b`` links still land where they did.
    """
    sections: list[SectionMeta] = []
    cursor = 0
    parent_stack: list[tuple[int, str]] = []
    # Each match carries both the heading-line start (used as the
    # *next* section's char_end boundary, so siblings don't include
    # each other's heading lines) and the body start (where the section
    # content actually begins, used as char_start). The trailing
    # ``id_source`` is propagated to SectionMeta so TocHeading consumers
    # can tell stable author-provided anchors from generated slugs.
    matches: list[tuple[int, str, int, int, str, str]] = []
    # tuple shape: (level, text, heading_start, body_start, id, id_source)

    for h in headings:
        level = int(h["level"])
        text = _normalize_heading_text(h.get("text", ""))
        # _build_headings uses key 'id' (not 'anchor')
        section_id = h.get("id") or ""
        id_source = h.get("id_source", "slug")
        if not text or not section_id:
            continue
        match = _locate_heading_text(rendered_markdown, level, text, cursor)
        if match is None:
            # A ``<br>`` inside the heading becomes a real newline in the
            # rendered markdown, so only the text BEFORE it stays on the
            # heading line while ``text`` carries the whole subtree. Every
            # matcher above is line-anchored and none can bridge that, so
            # retry with the pre-break spelling ``_build_headings`` recorded
            # (absent unless the heading actually contains a ``<br>``).
            line_text = _normalize_heading_text(h.get("line_text", ""))
            if line_text and line_text != text:
                match = _locate_heading_text(
                    rendered_markdown, level, line_text, cursor
                )
        if match is None:
            logger.warning(
                "Bundle: could not locate heading %r (level %d) in rendered markdown",
                text,
                level,
            )
            continue
        # ``char_start`` points to the first character of the body — the
        # newline after the heading line, then past it. The heading text
        # is already exposed as ``section_title`` and ``level`` on every
        # consumer, so including it in the sliced content is redundant
        # and inflates ``char_count``/``word_count``.
        body_start = match.end()
        if (
            body_start < len(rendered_markdown)
            and rendered_markdown[body_start] == "\n"
        ):
            body_start += 1
        matches.append((level, text, match.start(), body_start, section_id, id_source))
        cursor = match.end()

    md_len = len(rendered_markdown)
    # Every id the document declares, so a generated ``X_2`` can never
    # collide with a heading that genuinely carries that anchor.
    declared_ids = {m[4] for m in matches}
    emitted_ids: set[str] = set()
    for i, (
        level,
        text,
        heading_start,
        char_start,
        section_id,
        id_source,
    ) in enumerate(matches):
        # char_end extends to the next heading at the SAME OR HIGHER level
        # (lower number == higher level) — i.e., the next sibling or
        # ancestor-sibling. Use the *heading_start* of the next match
        # (not its body_start) so the current section doesn't include
        # the sibling's heading line.
        char_end = md_len
        for j in range(i + 1, len(matches)):
            if matches[j][0] <= level:
                char_end = matches[j][2]  # heading_start of next sibling
                break

        # Spec invariant: ``0 <= char_start < char_end <= len(rendered_markdown)``.
        # A heading that sits at the very end of the document with no
        # trailing body content lands with ``char_start == char_end`` —
        # legal markdown, but a zero-length section is useless to ``get_section``
        # (returns empty body, ``word_count=0``). Drop those rather than
        # ship a degenerate SectionMeta.
        if char_end <= char_start:
            continue

        if section_id in emitted_ids:
            ordinal = 2
            while (
                f"{section_id}_{ordinal}" in emitted_ids
                or f"{section_id}_{ordinal}" in declared_ids
            ):
                ordinal += 1
            section_id = f"{section_id}_{ordinal}"
        emitted_ids.add(section_id)

        while parent_stack and parent_stack[-1][0] >= level:
            parent_stack.pop()
        parent_id = parent_stack[-1][1] if parent_stack else None
        sections.append(
            cast(
                "SectionMeta",
                {
                    "id": section_id,
                    "title": text,
                    "level": level,
                    "heading_start": heading_start,
                    "char_start": char_start,
                    "char_end": char_end,
                    "parent_id": parent_id,
                    "id_source": id_source,
                },
            )
        )
        parent_stack.append((level, section_id))

    return sections


def extract_entry_bundle(
    archive: "Archive",
    entry_path: str,
    *,
    content_processor: "ContentProcessor",
    compact: bool = True,
) -> EntryBundle:
    """Run the single HTML parse and produce the bundle.

    Pure: no caching, no I/O beyond the archive read.

    ``compact`` selects the render fidelity: ``True`` (default) replaces
    oversized tables with ``[Table N: ...]`` placeholders matching the
    ``get_zim_entry`` path; ``False`` keeps full pipe-delimited tables.
    """
    from bs4 import BeautifulSoup

    from openzim_mcp.content_processor import _build_headings, select_main_content

    # ``entry_path`` is rebound to the POST-redirect path: the relative hrefs
    # in the returned HTML resolve against the served entry's directory, so a
    # bundle keyed on the caller's pre-redirect path handed downstream
    # consumers (``extract_article_links_data`` -> ``payload["path"]``,
    # ``get_related_articles_data``) a base path that yields dangling links.
    title, mime, html, entry_path = _resolve_entry_html(archive, entry_path)

    if not mime.startswith("text/html"):
        empty: EntryBundle = cast(
            "EntryBundle",
            {
                "entry_path": entry_path,
                "title": title,
                "content_type": mime,
                "word_count": 0,
                "char_count": 0,
                "rendered_markdown": "",
                "sections": [],
                "links": cast(
                    "LinkBuckets", {"internal": [], "external": [], "media": []}
                ),
                "infobox": None,
            },
        )
        return empty

    soup = BeautifulSoup(html, "html.parser")
    # Scope every downstream extraction to the page's main-content landmark
    # so ZIMIT/warc2zim site chrome (banner, header nav, footer, aside) does
    # not leak into headings (TOC), links (related articles), or the rendered
    # markdown (summary). No landmark -> the whole document, unchanged.
    # ``extract_html_links`` is fed the scoped subtree's HTML rather than the
    # raw entry HTML so nav links are excluded too; capture it BEFORE
    # ``_extract_infobox`` decomposes the infobox, preserving the prior order
    # in which links were extracted ahead of infobox removal.
    content_root = select_main_content(soup)
    headings = _build_headings(content_root, include_line_text=True)
    raw_links = content_processor.extract_html_links(str(content_root))
    link_buckets = _build_link_buckets(raw_links)
    infobox = _extract_infobox(content_root, content_processor)
    # Render in the requested mode. ``compact=True`` (the default, used by
    # summary/TOC/structure/synthesize) carries the same table-stripping
    # placeholders that direct ``get_zim_entry`` callers see, so a section
    # slice matches the article-fetch path. ``compact=False`` (the #18
    # raw-text path) keeps full pipe-delimited tables. The infobox is
    # already ``decompose()``d above in both modes.
    rendered = content_processor._render_soup_to_text(content_root, compact=compact)
    sections = _compute_section_offsets(rendered, headings)

    bundle: EntryBundle = cast(
        "EntryBundle",
        {
            "entry_path": entry_path,
            "title": title,
            "content_type": mime,
            "word_count": len(rendered.split()),
            "char_count": len(rendered),
            "rendered_markdown": rendered,
            "sections": sections,
            "links": link_buckets,
            "infobox": infobox,
        },
    )
    return bundle


def get_or_build_bundle(
    archive: Archive,
    entry_path: str,
    *,
    cache: OpenZimMcpCache,
    validated_path: Path,
    content_processor: ContentProcessor,
    compact: bool = True,
) -> EntryBundle:
    """Cache-aware bundle accessor. Builds on miss; returns cached on hit."""
    key = _bundle_cache_key(validated_path, entry_path, compact)
    cached = cache.get(key)
    if cached is not None:
        logger.debug("Bundle cache hit: %s (compact=%s)", entry_path, compact)
        return cast("EntryBundle", cached)
    logger.debug("Bundle cache miss: %s (compact=%s) — building", entry_path, compact)
    bundle = extract_entry_bundle(
        archive, entry_path, content_processor=content_processor, compact=compact
    )
    cache.set(key, bundle)
    return bundle
