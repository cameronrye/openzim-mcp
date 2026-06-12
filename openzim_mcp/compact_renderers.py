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
        # Post-v2.0.5 D-N: add `tell me about X` cross-intent path
        # to the recovery options. A caller who tried
        # `find article titled X` and got no hits is exactly the
        # caller who benefits from fuzzy title-index + RAG
        # fallback (which is what `tell me about` does). Same
        # defect class as D-L on the compact-search no-results
        # footer.
        return (
            f'**No article found titled "{title}"**\n\n'
            f"Try `suggestions for {title[:30]}` for autocomplete-based "
            f"name matching, `tell me about {title[:30]}` for fuzzy "
            f"title-index lookup with RAG fallback, or `search for "
            f"{title[:30]}` for full-text search."
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


def _render_related_link_line(r: Mapping[str, Any]) -> Optional[str]:
    """Format one outbound-link row as a bullet line. Returns None when
    the row is not a dict (defensive against partial payloads).

    A11 Opp7 (post-a10, second pass): surface the backend's
    ``mention_count`` field as a ``N×`` suffix so a small LLM can
    rank which related article is most central to the source. A
    single-occurrence "See also" link is less load-bearing than a
    20-occurrence backbone reference. The first-pass H1 read a
    ``link_count`` field that didn't exist on the payload — the
    structured backend (D9 / v2.0.0a9) actually stores the per-
    target frequency rank as ``mention_count``.
    """
    if not isinstance(r, dict):
        return None
    t = r.get("title", "(untitled)")
    p = r.get("path", "")
    link_text = r.get("link_text") or ""
    mention_count = r.get("mention_count")
    count_suffix = ""
    if isinstance(mention_count, int) and mention_count > 1:
        count_suffix = f" · {mention_count}×"
    if link_text and link_text.lower() != t.lower():
        return f"- **{t}** (`{p}`) — linked as “{link_text}”{count_suffix}"
    return f"- **{t}** (`{p}`){count_suffix}"


def _scan_truncated_footer(data: Mapping[str, Any]) -> Optional[str]:
    """D5 (beta): build the scan-truncated footer, or None when the
    signal isn't set. Hub articles ("List of …", "Index of …") carry
    1000-5000 internal links; the underlying ``extract_article_links_data``
    caps the scan at 500. Surface that to the model."""
    if not data.get("scan_truncated"):
        return None
    total = data.get("scan_total_internal")
    limit = data.get("scan_limit")
    if total and limit:
        return (
            f"_Scan truncated: ranked from the first {limit:,} of "
            f"~{total:,} internal links (document-head bias). The "
            f"true top-by-frequency may differ from this sample._"
        )
    return (
        "_Scan truncated: ranked from a head-biased sample of "
        "the article's internal links._"
    )


def render_related(data: Mapping[str, Any], entry_path: str) -> str:
    """Render a get_related_articles payload as a compact list."""
    if not isinstance(data, dict):
        return json.dumps(data)
    # v2 Phase B contract shape: ``{entry_path, results: [{path,
    # title, link_text}], next_cursor, total, done, page_info,
    # outbound_error?}``. Errors surface as the backend's textual
    # reason — preserve that for diagnosability.
    if data.get("outbound_error"):
        # A11 F3 (post-a10, second pass): the first-pass F3 fix wrapped
        # the raise-path, but the live "Cannot find entry" case actually
        # surfaces here via ``outbound_error`` (the backend catches and
        # serialises rather than re-raising). Append recovery guidance
        # to this branch too so a small LLM has concrete next-step
        # commands instead of a bare two-line error.
        # Post-v2.0.5 D-P sibling: mirror the recovery shape from
        # ``SimpleToolsHandler._render_not_found_recovery``; the
        # ``tell me about`` bullet adds the RAG-fallback signal on
        # top of pure title-index lookup.
        recovery = (
            f"\n\n**Try one of these to recover:**\n"
            f"- `suggestions for {entry_path[:40]}` — autocomplete to "
            "catch typos / partial names\n"
            f"- `find article titled {entry_path}` — title-index lookup "
            "with fuzzy fallback\n"
            f"- `search for {entry_path}` — full-text search\n"
            f"- `tell me about {entry_path}` — fuzzy title-index lookup "
            "with RAG fallback when no exact title matches\n"
        )
        return (
            f'**Could not extract related articles for "{entry_path}"**\n\n'
            f"{data['outbound_error']}{recovery}"
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
        line = _render_related_link_line(r)
        if line is not None:
            lines.append(line)
    footer = _scan_truncated_footer(data)
    if footer is not None:
        lines.extend(["", "---", footer])
    return "\n".join(lines)


def _walk_namespace_header(
    ns: str,
    offset: int,
    returned: int,
    archive_total: int,
    namespace_total: int = 0,
) -> str:
    """Build the header line for ``render_walk_namespace``.

    Four shapes:
      - ``returned == 0``: ``# Namespace 'X' — no entries`` (D8 fix).
        ``entries 1-0`` was the previous nonsense range.
      - ``namespace_total > 0``: ``X of N in this namespace`` — the
        denominator that actually matches what's being walked (A11 F4).
      - ``archive_total > 0``: archive-wide scale hint as a fallback.
      - otherwise: bare range.
    """
    range_str = f"entries {offset + 1}-{offset + returned}"
    # A11 F4 (post-a10): prefer the per-namespace denominator so the
    # walk header isn't misleading. ``walk namespace M`` with 13
    # entries used to render ``of ~27,199,904 archive-wide entries``
    # — readers expected the denominator to match the namespace
    # being walked. Fall through to the archive total only when no
    # per-namespace count is known.
    if namespace_total:
        scale_suffix = f" (of {namespace_total:,} in namespace `{ns}`)"
    elif archive_total:
        scale_suffix = f" (archive total: ~{archive_total:,} entries)"
    else:
        scale_suffix = ""
    if returned == 0:
        return f"# Namespace `{ns}` — no entries{scale_suffix}"
    return f"# Namespace `{ns}` — {range_str}{scale_suffix}"


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
    # walk doesn't know per-namespace total mid-scan when scanning the
    # iterator; well-known small namespaces (M, W) can supply a
    # ``namespace_entry_count`` ahead of time. Prefer that for a more
    # honest denominator (A11 F4).
    archive_total = data.get("archive_entry_count", 0)
    namespace_total = int(data.get("namespace_entry_count", 0) or 0)
    entries = data.get("results") or []
    done = data.get("done", False)

    lines = [
        _walk_namespace_header(
            ns, offset, returned, archive_total, namespace_total=namespace_total
        ),
        "",
    ]
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
    files_failed = int(data.get("files_failed", 0) or 0)
    lines = [f'# Search across {files_searched} ZIM files for "{query}"', ""]

    if files_with_hits == 0:
        # Distinguish "no archive matched the query" from "every archive
        # errored before returning hits". The latter is a server-side
        # signal — telling the model to ``try suggestions`` on a query the
        # archives never actually evaluated wastes turns chasing a
        # not-the-real-problem fix.
        if files_failed > 0 and files_failed >= files_searched:
            lines.append(
                f"All {files_failed} archive(s) returned errors before search "
                "completed. Check `list_zim_files` and server logs; the query "
                "itself was not the problem."
            )
        else:
            # Post-v2.0.5 D-O: add `tell me about X` cross-intent
            # path. When `search all files` returns nothing across
            # every loaded archive, the natural escape hatch is
            # `tell me about X` with `synthesize=True` — which
            # also auto-opens every loaded archive but does
            # structured topic lookup with fuzzy title resolution
            # instead of literal full-text matching. Same defect
            # class as D-L / D-N on the other compact no-results
            # bodies.
            lines.append(
                "No results in any archive. Try `suggestions for "
                f"{query[:30]}`, `tell me about {query[:30]}` (with "
                "`synthesize=True` for cross-archive auto-fetch), "
                "broaden the terms, or check `list_zim_files`."
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
    # A11 F5 (post-a10): the header reports ``archive.entry_count``
    # (typically the C-namespace article count); the per-namespace
    # rows below include W/M well-knowns + redirects, so their sum
    # slightly exceeds the header total. Compute and surface the
    # per-namespace sum alongside so readers don't think the
    # numbers are inconsistent — they're different views (article
    # count vs. all-entries-by-namespace).
    #
    # A16 post-a16 D10: the bare ``(per-namespace sum: N)`` annotation
    # left readers uncertain which value was authoritative and why
    # they didn't match. Spell out the relationship: the header is
    # ``archive.entry_count`` (the canonical count exposed in
    # ``metadata for <file>``); the per-namespace sum may exceed it
    # by the count of well-knowns + redirects (W/M extras that
    # ``entry_count`` excludes). When the two are equal, drop the
    # annotation altogether — same info, less noise.
    per_ns_sum = sum(
        int(info.get("total", 0) or 0)
        for info in namespaces.values()
        if isinstance(info, dict)
    )
    if per_ns_sum and per_ns_sum != total_entries:
        diff = per_ns_sum - total_entries
        if diff > 0:
            # The per-namespace rows sum to MORE than ``entry_count`` because
            # ``entry_count`` excludes the W/M well-known + metadata entries
            # the rows include. Lead with the true inventory (the sum) and
            # state the relationship as an explicit equation so the arithmetic
            # is legible instead of reading like an unexplained shortfall.
            header = (
                f"# Namespaces — per-namespace sum: {per_ns_sum:,} entries "
                f"(= entry_count {total_str} +{diff:,} W/M well-knowns/metadata "
                f"excluded from entry_count)"
            )
        else:
            # Sampling under-count: the sampled per-namespace sum is a lower
            # bound below the authoritative ``entry_count``.
            header = (
                f"# Namespaces — entry_count {total_str} "
                f"(per-namespace sample sum: {per_ns_sum:,}; "
                f"{-diff:,} fewer — sampling under-count)"
            )
    else:
        header = f"# Namespaces — {total_str} total entries"
    lines = [
        header,
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
