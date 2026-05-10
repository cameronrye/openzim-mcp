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
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

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


def _bundle_cache_key(validated_path: "Path", entry_path: str) -> str:
    return f"{_BUNDLE_KEY_PREFIX}:{validated_path}:{entry_path}"


def _normalize_heading_text(text: str) -> str:
    """Match html2text's whitespace handling: collapse runs of whitespace."""
    return " ".join(text.split())


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
    matches: list[tuple[int, str, int, str]] = []

    for h in headings:
        level = int(h["level"])
        text = _normalize_heading_text(h.get("text", ""))
        # _build_headings uses key 'id' (not 'anchor')
        section_id = h.get("id") or ""
        if not text or not section_id:
            continue
        pattern = re.compile(
            rf"^{'#' * level} {re.escape(text)}\s*$",
            re.MULTILINE,
        )
        match = pattern.search(rendered_markdown, cursor)
        if match is None:
            logger.warning(
                "Bundle: could not locate heading %r (level %d) in rendered markdown",
                text,
                level,
            )
            continue
        matches.append((level, text, match.start(), section_id))
        cursor = match.end()

    md_len = len(rendered_markdown)
    for i, (level, text, char_start, section_id) in enumerate(matches):
        # char_end extends to the next heading at the SAME OR HIGHER level
        # (lower number == higher level) — i.e., the next sibling or
        # ancestor-sibling. This makes a parent's range envelope all its
        # descendants, satisfying the parent.char_start <= child.char_start
        # < child.char_end <= parent.char_end invariant.
        char_end = md_len
        for j in range(i + 1, len(matches)):
            if matches[j][0] <= level:
                char_end = matches[j][2]
                break

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

    from openzim_mcp.content_processor import _build_headings

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
    headings = _build_headings(soup)
    raw_links = content_processor.extract_html_links(html)
    link_buckets = _build_link_buckets(raw_links)
    infobox = _extract_infobox(soup, content_processor)
    rendered = content_processor._render_soup_to_text(soup, compact=False)
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
    archive: "Archive",
    entry_path: str,
    *,
    cache: "OpenZimMcpCache",
    validated_path: "Path",
    content_processor: "ContentProcessor",
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
