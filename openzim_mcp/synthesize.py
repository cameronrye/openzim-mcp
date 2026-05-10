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
from typing import TYPE_CHECKING, Any, Callable, cast

if TYPE_CHECKING:
    from pathlib import Path

    from libzim.reader import Archive  # type: ignore[import-untyped]

    from openzim_mcp.cache import OpenZimMcpCache
    from openzim_mcp.config import SynthesizeConfig
    from openzim_mcp.content_processor import ContentProcessor

from openzim_mcp.tool_schemas import SynthesizePassage, SynthesizeResponse

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
# synthesize_query — main entry point (skeleton; stages added in Tasks 18-21)
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
    """Run the synthesize pipeline. Stages added incrementally in Tasks 18-21."""
    # Stage 1: per-archive search
    per_archive_results: list[list[dict]] = []
    archives_searched: list[str] = []
    for archive, validated_path in archives:
        archive_name = validated_path.stem
        archives_searched.append(archive_name)
        per_archive_results.append(
            _per_archive_search(
                archive,
                search_handler=search_handler,
                query=query,
                k=config.per_archive_k,
            )
        )

    # Subsequent stages added in Tasks 18-21 below this line.
    # For now, return a minimal SynthesizeResponse so the module imports cleanly.
    return cast(
        "SynthesizeResponse",
        {
            "query": query,
            "answer_markdown": "",
            "passages": [],
            "citations": [],
            "archives_searched": archives_searched,
            "fallback_used": "xapian_score" if len(archives) == 1 else "rrf_fusion",
            "total_chars": 0,
            "total_words": 0,
            "_meta": {},
        },
    )
