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


_BUNDLE_KEY_PREFIX = "bundle:v2c"


def archive_stat_token(validated_path: Any) -> str:
    """Return ``<mtime_ns>:<size>`` for ``validated_path`` (``"0:0"`` on OSError).

    Cache keys for any data derived from a ZIM file's contents should
    include this token so that an atomic file replacement (the typical
    monthly Wikipedia ZIM refresh) invalidates entries instead of
    serving stale data. The bundle cache uses it; namespace listings,
    binary metadata, and path-resolution caches all need the same
    guarantee.

    Falls back to ``"0:0"`` when ``stat()`` fails (path removed, race
    with replacement) — the cache continues to function, just without
    the invalidation guarantee for that key.

    ``validated_path`` is typed loosely so callers don't have to import
    ``pathlib.Path``; any path-like with ``.stat()`` works.
    """
    try:
        st = validated_path.stat()
        return f"{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return "0:0"


def _bundle_cache_key(validated_path: "Path", entry_path: str) -> str:
    """Cache key that invalidates when the underlying ZIM is replaced.

    Includes `st_mtime_ns` so an atomic file replacement (a monthly
    Wikipedia ZIM update) causes prior bundles to be reseen as cache
    misses rather than served as stale. `st_size` is included too —
    cheap defence-in-depth against filesystems with low-precision mtime
    or in-place rewrites that preserve the timestamp.

    Falls back gracefully when stat() fails (path no longer exists, race
    with replacement): the key drops to the prior shape so the cache
    still works, just without the invalidation guarantee.
    """
    return f"{_BUNDLE_KEY_PREFIX}:{validated_path}:{archive_stat_token(validated_path)}:{entry_path}"


def _normalize_heading_text(text: str) -> str:
    """Match html2text's whitespace handling: collapse runs of whitespace."""
    return " ".join(text.split())


def _loose_escaped_text(text: str) -> str:
    """Regex source matching ``text`` even when html2text backslash-escaped
    interior punctuation.

    html2text escapes markdown-significant punctuation by prefixing a
    backslash — a numbered heading ``1. Topic`` renders as ``1\\. Topic``,
    so a plain ``re.escape`` pattern never matches and the section is dropped
    (this is the root cause of the IEP "flattened TOC": every ``## 1.``,
    ``## 2.`` ... H2 vanished, leaving the H3 subsections misnested under the
    H1). Allowing an optional backslash before each character matches the
    escaped and unescaped forms alike. Used only by the relaxed fallback, so
    the larger pattern is paid only for headings the strict match missed.
    """
    return "".join(r"\\?" + re.escape(ch) for ch in text)


def _resolve_entry_html(archive: "Archive", entry_path: str) -> tuple[str, str, str]:
    """Fetch the entry's HTML, returning (title, mimetype, html).

    Raises whatever the libzim layer raises; callers wrap.
    """
    entry = archive.get_entry_by_path(entry_path)
    item = entry.get_item()
    title = entry.title or "Untitled"
    mime = item.mimetype or ""
    html = bytes(item.content).decode("utf-8", errors="replace")
    return title, mime, html


def _extract_infobox(
    soup: Any, content_processor: "ContentProcessor"
) -> Optional[InfoboxData]:
    """Extract the first infobox as InfoboxData, or None if absent."""
    rows = content_processor.extract_infobox(soup)
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


def _compute_section_offsets(
    rendered_markdown: str,
    headings: list[dict],
) -> list[SectionMeta]:
    """Locate each heading in rendered_markdown and emit SectionMeta.

    Headings in _build_headings() carry key 'id' (the resolved anchor slug).
    We search rendered_markdown in document order from the last cursor position
    so repeated identical headings are disambiguated correctly.
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
    for i, (
        level,
        text,
        _heading_start,
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
) -> EntryBundle:
    """Run the single HTML parse and produce the bundle.

    Pure: no caching, no I/O beyond the archive read.
    """
    from bs4 import BeautifulSoup

    from openzim_mcp.content_processor import _build_headings, select_main_content

    title, mime, html = _resolve_entry_html(archive, entry_path)

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
    headings = _build_headings(content_root)
    raw_links = content_processor.extract_html_links(str(content_root))
    link_buckets = _build_link_buckets(raw_links)
    infobox = _extract_infobox(content_root, content_processor)
    # Render with compact=True so that the bundle's rendered_markdown
    # carries the same table-stripping placeholders that direct
    # ``get_zim_entry`` callers see. Without this, get_section returns
    # raw pipe-soup tables for the climate / standings / etc. data
    # tables embedded in Wikipedia articles — a UX regression vs. the
    # surrounding article-fetch path. The infobox is already
    # ``decompose()``d above, so compact rendering won't re-extract it.
    rendered = content_processor._render_soup_to_text(content_root, compact=True)
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
) -> EntryBundle:
    """Cache-aware bundle accessor. Builds on miss; returns cached on hit."""
    key = _bundle_cache_key(validated_path, entry_path)
    cached = cache.get(key)
    if cached is not None:
        logger.debug("Bundle cache hit: %s", entry_path)
        return cast("EntryBundle", cached)
    logger.debug("Bundle cache miss: %s — building", entry_path)
    bundle = extract_entry_bundle(
        archive, entry_path, content_processor=content_processor
    )
    cache.set(key, bundle)
    return bundle
