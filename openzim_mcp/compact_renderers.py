"""Pure renderers for the simple-tools compact-mode response pipeline.

Each function here takes structured backend data (typically the JSON
shape returned by ``ZimOperations.*_data`` methods) and produces the
small-LLM-friendly markdown rendering used when ``compact=True``.

These renderers are deliberately stateless and have no dependency on
:class:`~openzim_mcp.zim_operations.ZimOperations` or any I/O — they're
the formatting layer, not the dispatcher. Keeping them in their own
module lets :mod:`openzim_mcp.simple_tools` focus on intent dispatch and
keeps each renderer trivially unit-testable in isolation.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Mapping, Optional


def compact_structure_payload(payload: Mapping[str, Any]) -> str:
    """Render a compact JSON view of an article-structure payload.

    Drops the per-heading 300-char ``content_preview`` and substitutes
    a tight 80-char ``summary`` derived from each section's leading
    prose. Op2: surfacing a per-section summary closes the small-LLM
    gap where the legacy compact form had only the heading text —
    enough to know *that* a section exists, not enough to choose
    which one to drill into. The 80-char cap keeps total response
    size bounded: a typical 50-section Wikipedia article comes in
    around 2-4 kB even with summaries, vs ~17 kB with full previews
    or ~1 kB with bare-heading list.

    Returns a JSON string (matching the shape of the legacy
    ``get_article_structure`` text path) so callers can swap in
    compact mode without changing how they parse the result.
    """
    if not isinstance(payload, dict):
        return json.dumps(payload)

    # Build a quick (title → first_preview) lookup so we can pair
    # each heading with the matching ``sections[]`` entry without
    # an O(n²) inner loop. Sections and headings share the same
    # document-order layout, but joining by title is more robust
    # to future shape changes than joining by index.
    section_summary_by_title: Dict[str, str] = {}
    for s in payload.get("sections") or []:
        if not isinstance(s, dict):
            continue
        st = s.get("title")
        sp = s.get("content_preview") or ""
        if (
            isinstance(st, str)
            and isinstance(sp, str)
            and st not in section_summary_by_title
        ):
            # 80-char cap: short enough to keep the compact response
            # tight, long enough to give a small model a sense of
            # what each section covers ("Climate", "Demographics",
            # etc. are themselves uninformative without context).
            section_summary_by_title[st] = sp.strip()[:80]

    compact_headings = []
    for h in payload.get("headings") or []:
        if not isinstance(h, dict):
            continue
        entry: Dict[str, Any] = {
            "level": h.get("level"),
            "text": h.get("text"),
            "id": h.get("id"),
        }
        summary = section_summary_by_title.get(h.get("text") or "")
        if summary:
            entry["summary"] = summary
        compact_headings.append(entry)

    compact: Dict[str, Any] = {
        "title": payload.get("title"),
        "path": payload.get("path"),
        "headings": compact_headings,
    }
    # Preserve a couple of small article-level summary fields that
    # callers may want for context — they're a few bytes each, not a
    # response-budget concern.
    for k in ("word_count", "character_count", "content_type"):
        if k in payload:
            compact[k] = payload[k]
    return json.dumps(compact)


def render_links(
    internal_data: Mapping[str, Any],
    external_data: Optional[Mapping[str, Any]] = None,
) -> str:
    """Render a v2 Phase B links payload as a flat markdown list.

    v2 Phase B contract delivers a single category per
    ``extract_article_links_data`` call, so the compact view fetches
    internal + external separately and stitches them here. ``title``,
    ``path``, and ``category_totals`` are read from ``internal_data``
    (both responses share them). ``external_data`` may be omitted for
    callers that only want the internal block.

    The compact variant uses ``- text -> path`` per link, drops media
    items entirely (rarely useful for navigation), and surfaces the
    full counts in a header so the caller can request more via
    ``offset`` if they need them.
    """
    if not isinstance(internal_data, dict):
        return json.dumps(internal_data)

    title = internal_data.get("title") or ""
    path = internal_data.get("path") or ""
    internal = internal_data.get("results") or []
    external = (
        external_data.get("results") if isinstance(external_data, dict) else []
    ) or []
    category_totals = internal_data.get("category_totals") or {}
    total_int = category_totals.get("internal", len(internal))
    total_ext = category_totals.get("external", len(external))

    lines = []
    if title or path:
        header = f"# Links from {title or path}"
        if path and path != title:
            header += f" ({path})"
        lines.append(header)
        lines.append("")

    def _fmt_one(link: Dict[str, Any]) -> str:
        text = (link.get("text") or "").strip() or link.get("url", "")
        url = link.get("url", "")
        return f"- {text} -> {url}"

    if internal:
        lines.append(f"## Internal ({len(internal)} of {total_int})")
        lines.extend(_fmt_one(link) for link in internal if isinstance(link, dict))
        lines.append("")

    if external:
        lines.append(f"## External ({len(external)} of {total_ext})")
        lines.extend(_fmt_one(link) for link in external if isinstance(link, dict))
        lines.append("")

    has_more = (not internal_data.get("done", True)) or (
        external_data is not None and not external_data.get("done", True)
    )
    if has_more:
        page_info = internal_data.get("page_info") or {}
        offset = page_info.get("offset", 0)
        limit = page_info.get("limit", len(internal) + len(external))
        lines.append(
            f"---\nMore links available — pass `offset={offset + limit}` "
            f"for the next page."
        )
    else:
        lines.append("---\n_End of links._")

    return "\n".join(lines)


def render_find_by_title(data: Mapping[str, Any], title: str) -> str:
    """Render a find_by_title payload as a compact markdown list.

    Saves the LLM from parsing nested JSON to extract the path it
    actually wants to fetch next. Names the score on each result so
    the caller can spot exact matches without doing string compares.
    """
    if not isinstance(data, dict):
        return json.dumps(data)
    results = data.get("results") or []
    if not results:
        return (
            f'**No article found titled "{title}"**\n\n'
            f"Try `suggestions for {title[:30]}` for autocomplete-based "
            f"name matching, or `search for {title[:30]}` for full-text "
            f"search."
        )
    lines = [f'# Title lookup for "{title}"', ""]
    for i, r in enumerate(results, 1):
        if not isinstance(r, dict):
            continue
        t = r.get("title", "(untitled)")
        p = r.get("path", "")
        score = r.get("score")
        if score is not None:
            lines.append(f"{i}. **{t}** — `{p}` (score: {float(score):.2f})")
        else:
            lines.append(f"{i}. **{t}** — `{p}`")
    if data.get("fast_path_hit"):
        lines.append("")
        lines.append("_Resolved via direct title lookup._")
    return "\n".join(lines)


def render_related(data: Mapping[str, Any], entry_path: str) -> str:
    """Render a get_related_articles payload as a compact list."""
    if not isinstance(data, dict):
        return json.dumps(data)
    # v2 Phase B contract shape: ``{entry_path, results: [{path,
    # title, link_text}], next_cursor, total, done, page_info,
    # outbound_error?}``. Errors surface as the backend's textual
    # reason — preserve that for diagnosability.
    if data.get("outbound_error"):
        return (
            f'**Could not extract related articles for "{entry_path}"**\n\n'
            f"{data['outbound_error']}"
        )
    outbound = data.get("results") or []
    if not outbound:
        return (
            f'No outbound article links found for "{entry_path}".\n\n'
            f"Some article types (lists, redirects, stubs) carry few or no "
            f"outbound links — try `tell me about {entry_path}` for the "
            f"article body."
        )
    lines = [f'# Articles linked from "{entry_path}"', ""]
    for r in outbound:
        if not isinstance(r, dict):
            continue
        t = r.get("title", "(untitled)")
        p = r.get("path", "")
        link_text = r.get("link_text") or ""
        if link_text and link_text.lower() != t.lower():
            lines.append(f"- **{t}** (`{p}`) — linked as “{link_text}”")
        else:
            lines.append(f"- **{t}** (`{p}`)")
    return "\n".join(lines)


def render_walk_namespace(data: Mapping[str, Any]) -> str:
    """Render a walk_namespace payload as a compact entry list.

    Reads the v2 Phase B contract: ``results`` / ``next_cursor`` (opaque
    str) / ``done`` / ``page_info`` plus walk-specific extras
    (``archive_entry_count``). ``total`` is always None for walk; the
    header reports the file-level count from ``archive_entry_count`` to
    give callers a sense of scale.
    """
    if not isinstance(data, dict):
        return json.dumps(data)
    ns = data.get("namespace", "?")
    next_cursor = data.get("next_cursor")
    page_info = data.get("page_info") or {}
    offset = page_info.get("offset", 0)
    returned = page_info.get("returned_count", 0)
    # walk doesn't know per-namespace total mid-scan; surface the
    # file-level archive count as a scale hint instead.
    archive_total = data.get("archive_entry_count", 0)
    entries = data.get("results") or []
    done = data.get("done", False)

    # D10 (v2.0.0a9): the prior wording read ``(archive total: 27M)``
    # for ``walk namespace M`` even though the M namespace only has 13
    # entries — the figure was the WHOLE-archive count. That confused
    # callers into thinking M had millions of entries. Label the
    # number explicitly as ``archive-wide entries`` so the scope is
    # unambiguous.
    if archive_total:
        header = (
            f"# Namespace `{ns}` — entries {offset + 1}-{offset + returned} "
            f"(of ~{archive_total:,} archive-wide entries)"
        )
    else:
        header = f"# Namespace `{ns}` — entries {offset + 1}-{offset + returned}"
    lines = [header, ""]
    for e in entries:
        if not isinstance(e, dict):
            continue
        t = e.get("title", "(untitled)")
        p = e.get("path", "")
        if t and t != p:
            lines.append(f"- **{t}** (`{p}`)")
        else:
            lines.append(f"- `{p}`")
    lines.append("")
    if not done and next_cursor is not None:
        lines.append(f"---\nPass `cursor={next_cursor}` for the next page.")
    else:
        lines.append("---\n_End of namespace._")
    return "\n".join(lines)


def render_search_all(data: Mapping[str, Any], query: str) -> str:
    """Render a search_all fan-out payload as a compact per-archive list.

    H10: previously the simple-mode dispatcher always called the legacy
    markdown ``search_all`` which bypassed ``search_all_data`` entirely —
    no per-file ``_meta`` survived the rendering, so the structured
    suggestions ``_meta.suggestions`` populated by the search backend
    were unreachable from compact mode. Routing through this renderer
    keeps the model-friendly compact prose while preserving the
    ``reason``/``suggestions`` signals on zero-hit aggregate responses.
    """
    if not isinstance(data, dict):
        return json.dumps(data)
    per_file = data.get("results") or []
    files_with_hits = int(data.get("files_with_hits", 0) or 0)
    files_searched = int(data.get("files_searched", len(per_file)) or 0)
    lines = [f'# Search across {files_searched} ZIM files for "{query}"', ""]

    if files_with_hits == 0:
        lines.append(
            "No results in any archive. Try `suggestions for "
            f"{query[:30]}`, broaden the terms, or check `list_zim_files`."
        )
        return "\n".join(lines)

    for entry in per_file:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("zim_file_path") or "(unnamed)"
        # H14: per-file payload may be a SearchResponse OR a sibling
        # error key. Branch on success first.
        result = entry.get("result")
        if entry.get("error"):
            lines.append(f"## `{name}` — error")
            lines.append(f"_{entry.get('error_message', 'unknown failure')}_")
            lines.append("")
            continue
        if not isinstance(result, dict):
            continue
        results = result.get("results") or []
        total = result.get("total")
        if not results:
            continue
        header = f"## `{name}` — {len(results)} hits"
        if total is not None:
            header += f" (of {total})"
        lines.append(header)
        for r in results[:5]:
            if not isinstance(r, dict):
                continue
            t = r.get("title", "(untitled)")
            p = r.get("path", "")
            lines.append(f"- **{t}** — `{p}`")
        lines.append("")
    return "\n".join(lines).rstrip()


def render_namespaces(data: Mapping[str, Any]) -> str:
    """Render a list_namespaces payload as a compact namespace table.

    Accepts ``Mapping`` rather than ``Dict`` so the typed
    ``ListNamespacesResponse`` TypedDict from the v2 Phase B migration
    flows through without an explicit ``cast`` at call sites.
    """
    if not isinstance(data, dict):
        return json.dumps(data)
    total_entries = data.get("total_entries", 0)
    is_authoritative = data.get("is_total_authoritative", True)
    method = data.get("discovery_method", "unknown")
    namespaces = data.get("namespaces") or {}

    total_str = f"{total_entries:,}" if is_authoritative else f"~{total_entries:,}"
    lines = [
        f"# Namespaces — {total_str} total entries",
        f"_Discovery: {method}._",
        "",
    ]
    # Sort by entry count (descending) so the most populous
    # namespaces — usually C — surface first. Phase B v2: per-namespace
    # count moved from ``count`` to ``total``.
    items = sorted(
        namespaces.items(),
        key=lambda kv: (-(kv[1].get("total", 0) if isinstance(kv[1], dict) else 0)),
    )
    for ns, info in items:
        if not isinstance(info, dict):
            continue
        count = info.get("total", 0)
        desc = info.get("description") or ""
        lines.append(f"- **`{ns}`** — {count:,} entries: {desc}")
    return "\n".join(lines)
