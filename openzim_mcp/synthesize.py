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
    archive: "Archive",
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
    content_processor: "ContentProcessor",
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


def _attribute_sections(
    passages: list[SynthesizePassage],
    *,
    bundle_lookup: Callable[[str], Any],
    hit_paths: list[str],
) -> list[SynthesizePassage]:
    """For each passage, find its containing section in the bundle and append #section_id.

    On bundle-build failure for an entry, leave the cite_id at entry level
    (no #section suffix). The passage is never dropped — section attribution
    is best-effort.
    """
    attributed: list[SynthesizePassage] = []
    for passage, hit_path in zip(passages, hit_paths):
        new_cite_id = passage["cite_id"]
        try:
            bundle = bundle_lookup(hit_path)
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

        pos = md.find(passage_text)
        if pos < 0:
            attributed.append(passage)
            continue

        for section in bundle.get("sections", []):
            if section["char_start"] <= pos < section["char_end"]:
                new_cite_id = f"{passage['cite_id']}#{section['id']}"
                break

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
    archive_titles: dict[str, str],  # entry_path -> entry title
    section_titles: dict[
        tuple[str, str], str
    ],  # (entry_path, section_id) -> section title
) -> list[Citation]:
    """Expand passages' cite_ids into Citation entries; dedupe by cite_id."""
    seen: dict[str, Citation] = {}
    for p in passages:
        cite_id = p["cite_id"]
        if cite_id in seen:
            continue
        archive, entry_path, section_id = _parse_cite_id(cite_id)
        title = archive_titles.get(entry_path, entry_path)
        section_title = (
            section_titles.get((entry_path, section_id)) if section_id else None
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


def synthesize_query(
    query: str,
    *,
    archives: list[tuple["Archive", "Path"]],  # (archive, validated_path) pairs
    search_handler: Any,
    cache: "OpenZimMcpCache",
    content_processor: "ContentProcessor",
    config: "SynthesizeConfig",
) -> SynthesizeResponse:
    """Run the synthesize pipeline end-to-end."""
    # Stage 1: per-archive search
    per_archive_hits: list[list[dict]] = []
    archives_searched: list[str] = []
    archive_by_name: dict[str, tuple["Archive", "Path"]] = {}
    for archive, validated_path in archives:
        archive_name = validated_path.stem
        archives_searched.append(archive_name)
        archive_by_name[archive_name] = (archive, validated_path)
        per_archive_hits.append(
            _per_archive_search(
                archive,
                search_handler=search_handler,
                query=query,
                k=config.per_archive_k,
            )
        )

    hit_to_archive: dict[tuple[str, str], dict] = {}
    for archive_name, hits in zip(archives_searched, per_archive_hits):
        for hit in hits:
            hit_to_archive[(archive_name, hit["path"])] = hit

    # Stage 2-3: fuse + (identity) rerank
    is_multi = len(archives) > 1
    top_hits: list[tuple[str, dict]] = []
    if is_multi:
        per_archive_rankings = [
            [(hit["path"], hit["score"]) for hit in hits] for hits in per_archive_hits
        ]
        fused = _rrf_fuse(per_archive_rankings, k=60)[: config.top_n]
        fallback_used: str = "rrf_fusion"
        for path, fused_score in fused:
            for archive_name in archives_searched:
                if (archive_name, path) in hit_to_archive:
                    h = dict(hit_to_archive[(archive_name, path)])
                    h["score"] = fused_score
                    top_hits.append((archive_name, h))
                    break
    else:
        archive_name = archives_searched[0] if archives_searched else "unknown"
        top_hits = (
            [(archive_name, hit) for hit in per_archive_hits[0][: config.top_n]]
            if per_archive_hits
            else []
        )
        fallback_used = "xapian_score"

    # Zero hits short-circuit
    if not top_hits:
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
                "_meta": {"reason": "0_hits"},
            },
        )

    # Stage 4: passage extraction
    all_passages: list[SynthesizePassage] = []
    all_paths: list[str] = []
    for archive_name, hit in top_hits:
        passages = _extract_passages(
            [hit],
            archive_name=archive_name,
            content_processor=content_processor,
        )
        all_passages.extend(passages)
        all_paths.append(hit["path"])
    for i, p in enumerate(all_passages, start=1):
        p["rank"] = i

    # Stage 5: section attribution
    archive_for_path: dict[str, tuple["Archive", "Path"]] = {}
    for archive_name, hit in top_hits:
        archive_for_path[hit["path"]] = archive_by_name[archive_name]

    def bundle_lookup(entry_path: str) -> Any:
        pair = archive_for_path.get(entry_path)
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

    attributed = _attribute_sections(
        all_passages,
        bundle_lookup=bundle_lookup,
        hit_paths=all_paths,
    )

    # Stage 7: budget enforcement
    capped = _enforce_budget(attributed, char_budget=config.output_char_budget)

    # Stage 6: render + build citations
    answer_md = _render_answer(capped)

    archive_titles: dict[str, str] = {}
    section_titles: dict[tuple[str, str], str] = {}
    for archive_name, hit in top_hits:
        try:
            b = bundle_lookup(hit["path"])
        except Exception:
            continue
        if b is None:
            continue
        archive_titles[hit["path"]] = b["title"]
        for s in b["sections"]:
            section_titles[(hit["path"], s["id"])] = s["title"]

    citations = _build_citations(
        capped,
        archive_titles=archive_titles,
        section_titles=section_titles,
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
            "_meta": {},
        },
    )
