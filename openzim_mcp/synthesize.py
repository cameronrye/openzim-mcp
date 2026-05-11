"""Server-side synthesize mode for zim_query.

Phase C #10: when zim_query is called with synthesize=True, this module
runs the pipeline:

    per-archive search → fuse (RRF for multi-archive) → rerank (identity
    in Phase C; cross-encoder hook in Phase D) → passage extraction via
    libzim.SearchIterator.getSnippet → section attribution via the
    EntryBundle → citation rendering → budget enforcement

Returns SynthesizeResponse (defined in tool_schemas.py).
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Callable, Optional, cast

if TYPE_CHECKING:
    from pathlib import Path

    from libzim.reader import Archive  # type: ignore[import-untyped]

    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import SynthesizeConfig
    from openzim_mcp.content_processor import ContentProcessor

from openzim_mcp.bundle import get_or_build_bundle
from openzim_mcp.tool_schemas import Citation, SynthesizePassage, SynthesizeResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RRF helper — Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


def _rrf_fuse(
    rankings: list[list[tuple[str, float]]],
    *,
    k: int = 60,
) -> list[tuple[str, float]]:
    """Combine multiple per-archive rankings into a single fused ranking.

    For each document, score = sum over rankings of 1 / (k + rank). k=60
    is the standard from the Cormack et al. reference. Documents missing
    from a ranking contribute 0 from that ranking.

    Args:
        rankings: list of per-source rankings; each ranking is a list of
                  (entry_path, source_score) in rank order.
        k: smoothing constant.

    Returns:
        list of (entry_path, fused_score) sorted by fused_score descending.
    """
    if not rankings:
        return []
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        for rank, (path, _src_score) in enumerate(ranking, start=1):
            scores[path] += 1.0 / (k + rank)
    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return fused


# ---------------------------------------------------------------------------
# Pipeline stage 1: per-archive search
# ---------------------------------------------------------------------------


def _per_archive_search(
    archive: Archive,
    *,
    search_handler: Any,  # SearchToolsHandler — typed loosely to avoid circular import
    query: str,
    k: int,
) -> list[dict]:
    """Run Xapian search on one archive, return top-K hits as dicts.

    Hit shape: {"path": str, "snippet": str, "score": float}.
    """
    return cast(list[dict], search_handler.search_top_k(archive, query, k=k))


# ---------------------------------------------------------------------------
# Pipeline stage 4: passage extraction
# ---------------------------------------------------------------------------


def _extract_passages(
    hits: list[dict],
    *,
    archive_name: str,
    content_processor: ContentProcessor,
) -> list[SynthesizePassage]:
    """Convert hit dicts into SynthesizePassage entries.

    Each hit's snippet (potentially HTML from libzim.getSnippet) is
    rendered to markdown. cite_id is the entry-level form
    f"{archive_name}/{path}" — the "#section_id" suffix is added by
    Stage 5 (_attribute_sections) once the bundle is consulted.
    """
    passages: list[SynthesizePassage] = []
    for rank, hit in enumerate(hits, start=1):
        snippet = hit.get("snippet") or ""
        text = content_processor.html_to_plain_text(snippet) if snippet else ""
        text = text.strip()
        cite_id = f"{archive_name}/{hit['path']}"
        passages.append(
            cast(
                SynthesizePassage,
                {
                    "cite_id": cite_id,
                    "text_markdown": text,
                    "rank": rank,
                    "score": float(hit.get("score", 0.0)),
                },
            )
        )
    return passages


# ---------------------------------------------------------------------------
# Pipeline stage 5: section attribution
# ---------------------------------------------------------------------------


# Collapse whitespace runs to single spaces. Snippets are produced by a
# different rendering path than the bundle's markdown (today: html2text
# applied per-snippet vs per-article), and incidental whitespace
# divergence is the most common reason a literal ``md.find`` misses.
_WS_RE = re.compile(r"\s+")


def _normalize_ws(text: str) -> str:
    """Collapse whitespace runs so attribution survives format drift."""
    return _WS_RE.sub(" ", text).strip()


def _locate_passage(md: str, passage_text: str) -> int:
    """Return the offset of ``passage_text`` within ``md``, or -1 on miss.

    Tries the exact match first (cheap, common). Falls back to a
    whitespace-normalized search so attribution survives whitespace or
    inline-markup drift between the snippet rendering path and the
    bundle's rendered markdown. The returned offset is into the
    *original* ``md`` so callers can map it back to section ranges.
    """
    pos = md.find(passage_text)
    if pos >= 0:
        return pos

    # Use the first ~80 chars of the normalized passage as a probe — long
    # enough to be specific, short enough that a single intra-passage
    # divergence doesn't kill the match.
    probe = _normalize_ws(passage_text)[:80]
    if len(probe) < 12:
        return -1

    md_norm = _normalize_ws(md)
    probe_pos = md_norm.find(probe)
    if probe_pos < 0:
        return -1

    # Map the normalized offset back to the original md offset. Walk md
    # in lockstep with md_norm, advancing the original cursor only when
    # the normalized character matches.
    md_cursor = 0
    norm_cursor = 0
    prev_was_space = False
    while md_cursor < len(md) and norm_cursor < probe_pos:
        ch = md[md_cursor]
        if ch.isspace():
            if not prev_was_space and norm_cursor > 0:
                norm_cursor += 1
            prev_was_space = True
        else:
            norm_cursor += 1
            prev_was_space = False
        md_cursor += 1
    return md_cursor


def _attribute_sections(
    passages: list[SynthesizePassage],
    *,
    bundle_lookup: Callable[[str, str], Any],
    hit_keys: list[tuple[str, str]],
) -> list[SynthesizePassage]:
    """For each passage, find its containing section in the bundle and append #section_id.

    On bundle-build failure for an entry, leave the cite_id at entry level
    (no #section suffix). The passage is never dropped — section attribution
    is best-effort.

    ``hit_keys`` is a parallel list of ``(archive_name, entry_path)`` tuples;
    using the tuple as the bundle-lookup key avoids cross-archive
    collisions (issue Phase C #4).

    When multiple nested sections contain the passage offset (a child
    section sits inside its parent's range), the *most specific*
    (smallest, deepest) section wins. Citing "Berlin#Geography" beats
    "Berlin" when the snippet sits inside the Geography subsection.
    """
    attributed: list[SynthesizePassage] = []
    for passage, (archive_name, hit_path) in zip(passages, hit_keys):
        new_cite_id = passage["cite_id"]
        try:
            bundle = bundle_lookup(archive_name, hit_path)
        except Exception as e:
            logger.info(
                "Bundle build failed for %s during synthesize attribution: %s",
                hit_path,
                e,
            )
            attributed.append(passage)
            continue

        if bundle is None:
            attributed.append(passage)
            continue

        md = bundle.get("rendered_markdown", "")
        passage_text = passage["text_markdown"]
        if not passage_text or not md:
            attributed.append(passage)
            continue

        pos = _locate_passage(md, passage_text)
        if pos < 0:
            attributed.append(passage)
            continue

        # Pick the smallest-range containing section so nested attribution
        # cites the deepest heading (e.g. h3 inside h2 inside h1).
        best_section: Optional[dict] = None
        best_span = None
        for section in bundle.get("sections", []):
            cs = section["char_start"]
            ce = section["char_end"]
            if cs <= pos < ce:
                span = ce - cs
                if best_span is None or span < best_span:
                    best_section = section
                    best_span = span
        if best_section is not None:
            new_cite_id = f"{passage['cite_id']}#{best_section['id']}"

        new_passage = dict(passage)
        new_passage["cite_id"] = new_cite_id
        attributed.append(cast(SynthesizePassage, new_passage))
    return attributed


# ---------------------------------------------------------------------------
# Pipeline stage 6: answer rendering
# ---------------------------------------------------------------------------


def _render_answer(passages: list[SynthesizePassage]) -> str:
    """Concatenate passages with inline [cite: ...] markers."""
    parts: list[str] = []
    for p in passages:
        parts.append(f"{p['text_markdown']}\n[cite: {p['cite_id']}]")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Pipeline stage 7: budget enforcement
# ---------------------------------------------------------------------------


def _enforce_budget(
    passages: list[SynthesizePassage],
    *,
    char_budget: int,
) -> list[SynthesizePassage]:
    """Truncate passages so total text_markdown chars <= char_budget.

    Iterates in rank order; the last passage that doesn't fit is truncated
    to fit the remaining budget. Subsequent passages are dropped if budget
    is exhausted. Citation markers are NOT counted against the budget
    (they're small and rendering happens after this stage).
    """
    budget = char_budget
    capped: list[SynthesizePassage] = []
    for p in passages:
        body = p["text_markdown"]
        if len(body) <= budget:
            capped.append(p)
            budget -= len(body)
            continue
        if budget > 0:
            new_p = dict(p)
            new_p["text_markdown"] = body[:budget]
            capped.append(cast("SynthesizePassage", new_p))
        break
    return capped


# ---------------------------------------------------------------------------
# Pipeline stage 8: citation building
# ---------------------------------------------------------------------------


def _parse_cite_id(cite_id: str) -> tuple[str, str, Optional[str]]:
    """Decompose 'archive/entry_path#section_id' into its parts.

    archive/entry_path is everything before '#'; section_id is the suffix
    after '#' (or None if absent). The archive identifier is the FIRST
    path segment (basename of the .zim, minus extension).
    """
    base, _, section_id = cite_id.partition("#")
    archive, _, entry_path = base.partition("/")
    return archive, entry_path, (section_id or None)


def _build_citations(
    passages: list[SynthesizePassage],
    *,
    archive_titles: dict[tuple[str, str], str],  # (archive, entry_path) -> entry title
    section_titles: dict[
        tuple[str, str, str], str
    ],  # (archive, entry_path, section_id) -> section title
) -> list[Citation]:
    """Expand passages' cite_ids into Citation entries; dedupe by cite_id."""
    seen: dict[str, Citation] = {}
    for p in passages:
        cite_id = p["cite_id"]
        if cite_id in seen:
            continue
        archive, entry_path, section_id = _parse_cite_id(cite_id)
        title = archive_titles.get((archive, entry_path), entry_path)
        section_title = (
            section_titles.get((archive, entry_path, section_id))
            if section_id
            else None
        )
        seen[cite_id] = cast(
            "Citation",
            {
                "cite_id": cite_id,
                "archive": archive,
                "entry_path": entry_path,
                "title": title,
                "section_id": section_id,
                "section_title": section_title,
            },
        )
    return list(seen.values())


# ---------------------------------------------------------------------------
# synthesize_query — main entry point
# ---------------------------------------------------------------------------


def _do_per_archive_search(
    archives: list[tuple[Archive, Path]],
    *,
    search_handler: Any,
    query: str,
    k: int,
) -> tuple[list[list[dict]], list[str], dict[str, tuple[Archive, Path]]]:
    """Stage 1: run per-archive Xapian search for every archive in the list."""
    per_archive_hits: list[list[dict]] = []
    archives_searched: list[str] = []
    archive_by_name: dict[str, tuple[Archive, Path]] = {}
    for archive, validated_path in archives:
        archive_name = validated_path.stem
        archives_searched.append(archive_name)
        archive_by_name[archive_name] = (archive, validated_path)
        per_archive_hits.append(
            _per_archive_search(
                archive, search_handler=search_handler, query=query, k=k
            )
        )
    return per_archive_hits, archives_searched, archive_by_name


def _select_top_hits(
    per_archive_hits: list[list[dict]],
    archives_searched: list[str],
    *,
    top_n: int,
) -> tuple[list[tuple[str, dict]], str]:
    """Stages 2–3: fuse (RRF for multi-archive, identity for single) + rerank.

    Returns ``(top_hits, fallback_used)`` where ``top_hits`` is a list of
    ``(archive_name, hit)`` tuples and ``fallback_used`` is
    ``"rrf_fusion"`` or ``"xapian_score"``.
    """
    if len(per_archive_hits) > 1:
        return _select_top_hits_multi(per_archive_hits, archives_searched, top_n=top_n)
    archive_name = archives_searched[0] if archives_searched else "unknown"
    top_hits = (
        [(archive_name, hit) for hit in per_archive_hits[0][:top_n]]
        if per_archive_hits
        else []
    )
    return top_hits, "xapian_score"


def _select_top_hits_multi(
    per_archive_hits: list[list[dict]],
    archives_searched: list[str],
    *,
    top_n: int,
) -> tuple[list[tuple[str, dict]], str]:
    """Multi-archive RRF fusion path of :func:`_select_top_hits`.

    On a path that appears in multiple archives (common for Wikipedia
    ZIMs that share entry paths), credit the archive that ranked it
    highest in its own per-archive list — not the first archive in
    ``archives_searched`` iteration order. ``hit_to_archive`` carries
    the original ranking position so we can pick the best contributor
    deterministically.
    """
    # (archive_name, path) -> (rank_in_archive, hit_dict)
    hit_to_archive: dict[tuple[str, str], tuple[int, dict]] = {}
    for archive_name, hits in zip(archives_searched, per_archive_hits):
        for rank_in_archive, hit in enumerate(hits):
            hit_to_archive[(archive_name, hit["path"])] = (rank_in_archive, hit)
    rankings = [
        [(hit["path"], hit["score"]) for hit in hits] for hits in per_archive_hits
    ]
    fused = _rrf_fuse(rankings, k=60)[:top_n]
    top_hits: list[tuple[str, dict]] = []
    for path, fused_score in fused:
        # Among archives that contain this path, pick the one with the
        # best (lowest) rank — i.e., the archive that contributed the
        # highest signal to RRF. Ties broken by ``archives_searched``
        # order for determinism.
        candidates = [
            (rank, archive_name)
            for archive_name in archives_searched
            if (archive_name, path) in hit_to_archive
            for rank, _ in (hit_to_archive[(archive_name, path)],)
        ]
        if not candidates:
            continue
        _, best_archive = min(
            candidates, key=lambda t: (t[0], archives_searched.index(t[1]))
        )
        h = dict(hit_to_archive[(best_archive, path)][1])
        h["score"] = fused_score
        top_hits.append((best_archive, h))
    return top_hits, "rrf_fusion"


def _make_bundle_lookup(
    top_hits: list[tuple[str, dict]],
    archive_by_name: dict[str, tuple[Archive, Path]],
    *,
    cache: OpenZimMcpCache,
    content_processor: ContentProcessor,
) -> Callable[[str, str], Any]:
    """Build an (archive_name, path)→bundle closure used by attribution and
    citation lookups.

    Keying on ``(archive_name, entry_path)`` rather than ``entry_path``
    alone is required for multi-archive synthesis: Wikipedia-style ZIMs
    share entry paths (``A/Photosynthesis`` exists in every archive), so
    a path-only dict silently collapses entries from different archives
    and attributes citations to the wrong source.
    """
    archive_for_key: dict[tuple[str, str], tuple[Archive, Path]] = {
        (archive_name, hit["path"]): archive_by_name[archive_name]
        for archive_name, hit in top_hits
    }

    def bundle_lookup(archive_name: str, entry_path: str) -> Any:
        pair = archive_for_key.get((archive_name, entry_path))
        if pair is None:
            return None
        archive_val, validated_path = pair
        return get_or_build_bundle(
            archive_val,
            entry_path,
            cache=cache,
            validated_path=validated_path,
            content_processor=content_processor,
        )

    return bundle_lookup


def _extract_passages_for_top_hits(
    top_hits: list[tuple[str, dict]],
    *,
    content_processor: ContentProcessor,
) -> tuple[list[SynthesizePassage], list[tuple[str, str]]]:
    """Stage 4: extract per-hit passages and renumber rank globally.

    Returns ``(passages, hit_keys)`` where ``hit_keys`` is a parallel
    list of ``(archive_name, entry_path)`` tuples — used downstream for
    multi-archive-safe bundle lookups.
    """
    all_passages: list[SynthesizePassage] = []
    hit_keys: list[tuple[str, str]] = []
    for archive_name, hit in top_hits:
        all_passages.extend(
            _extract_passages(
                [hit],
                archive_name=archive_name,
                content_processor=content_processor,
            )
        )
        hit_keys.append((archive_name, hit["path"]))
    for i, p in enumerate(all_passages, start=1):
        p["rank"] = i
    return all_passages, hit_keys


def _build_section_lookups(
    top_hits: list[tuple[str, dict]],
    bundle_lookup: Callable[[str, str], Any],
) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str, str], str]]:
    """Per-(archive, entry, section) title maps used by :func:`_build_citations`.

    Bundle build failures are swallowed at info level by the caller pattern
    (the bundle is best-effort); on failure the entry is skipped and its
    citations stay at entry level.

    Keying on ``(archive_name, ...)`` tuples avoids the multi-archive
    collision documented in :func:`_make_bundle_lookup`.
    """
    archive_titles: dict[tuple[str, str], str] = {}
    section_titles: dict[tuple[str, str, str], str] = {}
    for archive_name, hit in top_hits:
        try:
            b = bundle_lookup(archive_name, hit["path"])
        except Exception:
            continue
        if b is None:
            continue
        archive_titles[(archive_name, hit["path"])] = b["title"]
        for s in b["sections"]:
            section_titles[(archive_name, hit["path"], s["id"])] = s["title"]
    return archive_titles, section_titles


def _zero_hits_response(
    query: str, archives_searched: list[str], fallback_used: str
) -> SynthesizeResponse:
    from openzim_mcp.meta import build_meta as _build_meta

    meta = _build_meta(rendered="", reason="0_hits")
    return cast(
        "SynthesizeResponse",
        {
            "query": query,
            "answer_markdown": "",
            "passages": [],
            "citations": [],
            "archives_searched": archives_searched,
            "fallback_used": fallback_used,
            "total_chars": 0,
            "total_words": 0,
            "_meta": cast("Any", meta),
        },
    )


def synthesize_query(
    query: str,
    *,
    archives: list[tuple[Archive, Path]],  # (archive, validated_path) pairs
    search_handler: Any,
    cache: OpenZimMcpCache,
    content_processor: ContentProcessor,
    config: SynthesizeConfig,
) -> SynthesizeResponse:
    """Run the synthesize pipeline end-to-end."""
    per_archive_hits, archives_searched, archive_by_name = _do_per_archive_search(
        archives,
        search_handler=search_handler,
        query=query,
        k=config.per_archive_k,
    )
    top_hits, fallback_used = _select_top_hits(
        per_archive_hits, archives_searched, top_n=config.top_n
    )
    if not top_hits:
        return _zero_hits_response(query, archives_searched, fallback_used)

    all_passages, hit_keys = _extract_passages_for_top_hits(
        top_hits, content_processor=content_processor
    )
    bundle_lookup = _make_bundle_lookup(
        top_hits,
        archive_by_name,
        cache=cache,
        content_processor=content_processor,
    )
    attributed = _attribute_sections(
        all_passages, bundle_lookup=bundle_lookup, hit_keys=hit_keys
    )
    pre_cap_chars = sum(len(p["text_markdown"]) for p in attributed)
    capped = _enforce_budget(attributed, char_budget=config.output_char_budget)
    truncated = sum(len(p["text_markdown"]) for p in capped) < pre_cap_chars
    answer_md = _render_answer(capped)
    archive_titles, section_titles = _build_section_lookups(top_hits, bundle_lookup)
    citations = _build_citations(
        capped, archive_titles=archive_titles, section_titles=section_titles
    )
    # Real _meta envelope (not the hardcoded `{}` of earlier versions).
    # ``rendered`` is the answer body — same convention as simple-mode
    # responses, so ``_meta.chars``/``tokens_est`` reflect what the
    # caller actually sees, not the JSON envelope cost.
    from openzim_mcp.meta import build_meta as _build_meta

    meta = _build_meta(
        rendered=answer_md,
        truncated=truncated,
        content_chars=len(answer_md) if truncated else None,
        total_chars=pre_cap_chars if truncated else None,
    )
    return cast(
        "SynthesizeResponse",
        {
            "query": query,
            "answer_markdown": answer_md,
            "passages": capped,
            "citations": citations,
            "archives_searched": archives_searched,
            "fallback_used": fallback_used,
            "total_chars": len(answer_md),
            "total_words": len(answer_md.split()),
            "_meta": cast("Any", meta),
        },
    )
