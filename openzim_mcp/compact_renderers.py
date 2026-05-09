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
from typing import Any, Dict, Mapping


def compact_structure_payload(payload: Dict[str, Any]) -> str:
    """Render a compact JSON view of an article-structure payload.

    Drops the per-heading ``preview`` field (~3000 chars each, the
    bulk of the response budget) and keeps only the navigation-shaped
    fields (level, text, id) plus the article-level summary. Reduces
    a typical structure response from ~17k chars to ~1-2k while
    preserving everything an LLM needs to choose a next operation.

    Returns a JSON string (matching the shape of the legacy
    ``get_article_structure`` text path) so callers can swap in
    compact mode without changing how they parse the result.
    """
    if not isinstance(payload, dict):
        return json.dumps(payload)
    compact: Dict[str, Any] = {
        "title": payload.get("title"),
        "path": payload.get("path"),
        "headings": [
            {
                "level": h.get("level"),
                "text": h.get("text"),
                "id": h.get("id"),
            }
            for h in payload.get("headings") or []
            if isinstance(h, dict)
        ],
    }
    # Preserve a couple of small article-level summary fields that
    # callers may want for context — they're a few bytes each, not a
    # response-budget concern.
    for k in ("word_count", "character_count", "content_type"):
        if k in payload:
            compact[k] = payload[k]
    return json.dumps(compact)


def render_links(data: Dict[str, Any]) -> str:
    """Render a links payload as a flat markdown list.

    The legacy ``extract_article_links`` JSON shape allocates ~150
    chars per link (object with url/text/title/type fields). On a
    Wikipedia-scale article that's ~36k chars of response. The
    compact variant uses ``- text -> path`` per link, drops media
    items entirely (rarely useful for navigation), and surfaces the
    full counts in a header so the caller can request more via
    ``offset`` if they need them.
    """
    if not isinstance(data, dict):
        return json.dumps(data)

    title = data.get("title") or ""
    path = data.get("path") or ""
    internal = data.get("internal_links") or []
    external = data.get("external_links") or []
    total_int = data.get("total_internal_links", len(internal))
    total_ext = data.get("total_external_links", len(external))
    pagination = data.get("pagination") or {}

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

    if pagination.get("has_more"):
        offset = pagination.get("offset", 0)
        limit = pagination.get("limit", len(internal) + len(external))
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


def render_related(data: Dict[str, Any], entry_path: str) -> str:
    """Render a get_related_articles payload as a compact list."""
    if not isinstance(data, dict):
        return json.dumps(data)
    # The data shape is ``{entry_path, outbound_results: [{path,
    # title, link_text}], outbound_error?}``. Errors surface as the
    # backend's textual reason — preserve that for diagnosability.
    if data.get("outbound_error"):
        return (
            f'**Could not extract related articles for "{entry_path}"**\n\n'
            f"{data['outbound_error']}"
        )
    outbound = data.get("outbound_results") or []
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

    if archive_total:
        header = (
            f"# Namespace `{ns}` — entries {offset + 1}-{offset + returned} "
            f"(archive total: {archive_total:,})"
        )
    else:
        header = (
            f"# Namespace `{ns}` — entries {offset + 1}-{offset + returned}"
        )
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
