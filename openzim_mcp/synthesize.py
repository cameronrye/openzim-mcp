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
    from openzim_mcp.config import RerankerConfig, SynthesizeConfig
    from openzim_mcp.content_processor import ContentProcessor

from openzim_mcp import bundle as _bundle_mod
from openzim_mcp.title_promotion import (
    find_title_match,
    has_apostrophe_possessive,
    is_strong_title_match,
    iter_query_tails,
)
from openzim_mcp.tool_schemas import (
    Citation,
    ConsideredArticle,
    ConsideredSection,
    SynthesizePassage,
    SynthesizeResponse,
)

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
    # H19: deterministic tie-breaking. ``sorted`` is stable but the
    # underlying dict insertion order varies with which ranking
    # contributed each path first — across runs of the same multi-archive
    # search with structurally equivalent inputs, that produced different
    # cite_id orderings. Secondary sort by path (ascending) makes ties
    # break the same way every time.
    fused = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
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
) -> list[SynthesizePassage]:
    """Convert hit dicts into SynthesizePassage entries.

    The snippet from ``search_top_k`` is already a plain-markdown string
    produced by ``_get_entry_snippet`` → ``create_snippet`` (which
    decompresses the entry, runs html2text, and slices to a paragraph
    boundary). Re-running ``html_to_plain_text`` on it is a no-op for
    clean output but risks mangling bold-highlight markers via the
    BeautifulSoup → html2text round-trip — trust the upstream pipeline
    instead.

    cite_id is the entry-level form ``f"{archive_name}/{path}"`` —
    the ``"#section_id"`` suffix is added by Stage 5 (``_attribute_sections``)
    once the bundle is consulted.
    """
    passages: list[SynthesizePassage] = []
    for rank, hit in enumerate(hits, start=1):
        snippet = hit.get("snippet") or ""
        text = snippet.strip()
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


# Strip ``**...**`` bold markers that ``create_snippet``'s
# query-highlighting pass added. The bundle's ``rendered_markdown`` is
# rendered WITHOUT the per-query highlight wrap, so a literal
# ``md.find("**Photosynthesis**")`` returns -1 even though the plain
# text matches. Stripping the bold markers before locating restores
# section attribution (D8): every passage now carries its
# ``#section_id`` suffix instead of dropping back to bare entry-level
# citation.
_BOLD_MARKER_RE = re.compile(r"\*\*")


def _strip_bold(text: str) -> str:
    """Remove ``**`` markers added by ``_highlight_terms`` so the
    passage text can be located inside the bundle's plain
    rendered_markdown."""
    return _BOLD_MARKER_RE.sub("", text)


def _strip_bold_with_remap(text: str) -> tuple[str, list[int]]:
    """Return ``(stripped, remap)`` where ``remap[i]`` is the offset in
    ``text`` of the character that became ``stripped[i]``.

    Used by ``_locate_passage`` to back-map find/normalize-search hits
    inside a bold-stripped haystack to offsets in the original
    markdown. Without this back-map, the post-a14 sweep fix
    (stripping ``**`` from both sides before searching) would land
    section attribution on the wrong char offset whenever the natural
    bold markers in Wikipedia lead text shift the index.
    """
    stripped_chars: list[str] = []
    remap: list[int] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "*" and i + 1 < n and text[i + 1] == "*":
            i += 2
            continue
        stripped_chars.append(text[i])
        remap.append(i)
        i += 1
    return "".join(stripped_chars), remap


def _locate_passage(md: str, passage_text: str) -> int:
    """Return the offset of ``passage_text`` within ``md``, or -1 on miss.

    Tries the exact match first (cheap, common). Falls back to a
    whitespace-normalized search so attribution survives whitespace or
    inline-markup drift between the snippet rendering path and the
    bundle's rendered markdown. The returned offset is into the
    *original* ``md`` so callers can map it back to section ranges.

    Strips ``**`` bold markers from BOTH sides before searching.
    ``create_snippet``'s query-highlight wrapper inserts ``**...**``
    around the query term, but real-archive markdown ALSO carries
    natural bold (``**EntityName**`` opens every Wikipedia lead
    paragraph). Without stripping bold from the haystack too,
    ``md.find("Big Rapids is a city")`` returns -1 against
    ``"**Big Rapids** is a city"`` even after stripping bold from the
    passage — the post-a14 beta-test sweep traced every dead
    section-affinity citation back to this asymmetry.
    """
    passage_text = _strip_bold(passage_text)
    md_clean, remap = _strip_bold_with_remap(md)
    pos = md_clean.find(passage_text)
    if pos >= 0:
        # ``remap[pos]`` is the original-md offset of ``md_clean[pos]``,
        # i.e., the first non-bold-marker char at the match site. When
        # the match begins at the very tail (after all non-bold chars)
        # remap is non-empty if md_clean is non-empty; fall back to
        # ``len(md)`` defensively otherwise.
        if pos < len(remap):
            return remap[pos]
        return len(md)

    # Use the first ~80 chars of the normalized passage as a probe — long
    # enough to be specific, short enough that a single intra-passage
    # divergence doesn't kill the match.
    probe = _normalize_ws(passage_text)[:80]
    if len(probe) < 12:
        return -1

    md_clean_norm = _normalize_ws(md_clean)
    probe_pos = md_clean_norm.find(probe)
    if probe_pos < 0:
        return -1

    # Map the normalized-clean offset back to the original md offset.
    # Walk ``md_clean`` in lockstep with ``md_clean_norm`` to find the
    # ``md_clean`` index of the probe match, then look up ``remap`` to
    # get the original-``md`` offset. ``_normalize_ws`` strips leading
    # whitespace, so the run we need to track always begins after
    # non-space content; no guard is required.
    clean_cursor = 0
    norm_cursor = 0
    prev_was_space = False
    while clean_cursor < len(md_clean) and norm_cursor < probe_pos:
        ch = md_clean[clean_cursor]
        if ch.isspace():
            if not prev_was_space:
                norm_cursor += 1
            prev_was_space = True
        else:
            norm_cursor += 1
            prev_was_space = False
        clean_cursor += 1
    # Probes are normalized + trimmed so probe[0] is always a non-space
    # character. After lockstep walk the cursor may sit on the first
    # whitespace of a run that md_clean_norm collapsed to one space —
    # advance past any remaining whitespace so the returned offset
    # points at the first non-space char of the match.
    while clean_cursor < len(md_clean) and md_clean[clean_cursor].isspace():
        clean_cursor += 1
    if clean_cursor < len(remap):
        return remap[clean_cursor]
    return len(md)


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
        # Post-a14 sweep fallback: when the locate position lands in
        # pre-h1 chrome (page nav, breadcrumbs, infobox-without-h1)
        # and no section brackets it, attribute to the article-level
        # FIRST section anyway. Otherwise every BM25 snippet that
        # happens to align with the chrome falls through to entry-
        # level citation — observed against the IEP archive's nav-
        # menu prefix and against any archive whose renderer puts
        # non-section content before the h1 line.
        if best_section is None:
            sections = bundle.get("sections", [])
            if sections:
                best_section = sections[0]
        if best_section is not None:
            new_cite_id = f"{passage['cite_id']}#{best_section['id']}"

        new_passage = dict(passage)
        new_passage["cite_id"] = new_cite_id
        attributed.append(cast(SynthesizePassage, new_passage))
    return attributed


# ---------------------------------------------------------------------------
# Pipeline stage 5b: section-heading affinity boost (A14)
# ---------------------------------------------------------------------------

# Same tokenizer convention used in iter_query_tails / is_strong_title_match.
# Alphanumeric runs only; punctuation and whitespace are token boundaries.
_AFFINITY_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _affinity_tokens(text: str) -> set[str]:
    """Lowercase alphanumeric token set. Empty set for empty input."""
    if not text:
        return set()
    return set(_AFFINITY_TOKEN_RE.findall(text.lower()))


def _section_titles_for(
    archive_name: str,
    entry_path: str,
    *,
    bundle_lookup: Callable[[str, str], Any],
    cache: dict[tuple[str, str], dict[str, str]],
) -> dict[str, str]:
    """Memoized ``section_id → title`` map for one bundle.

    Bundle lookup failures (exceptions or ``None`` returns) are
    cached as empty dicts so a flaky bundle is not retried within
    the same affinity pass.
    """
    key = (archive_name, entry_path)
    if key in cache:
        return cache[key]
    try:
        bundle = bundle_lookup(archive_name, entry_path)
    except Exception as e:
        logger.debug(
            "section-affinity bundle lookup failed for %s/%s: %s",
            archive_name,
            entry_path,
            e,
        )
        cache[key] = {}
        return cache[key]
    if bundle is None:
        cache[key] = {}
        return cache[key]
    titles = {
        str(s.get("id", "")): str(s.get("title", ""))
        for s in bundle.get("sections", [])
        if s.get("id")
    }
    cache[key] = titles
    return titles


def _maybe_boost_passage(
    passage: SynthesizePassage,
    *,
    query_tokens: set[str],
    bundle_lookup: Callable[[str, str], Any],
    cache: dict[tuple[str, str], dict[str, str]],
    threshold: float,
    boost: float,
) -> SynthesizePassage:
    """Return a fresh copy of ``passage`` with its score possibly boosted.

    No-op cases (returned with original score):
      * cite_id has no ``#section_id`` suffix
      * cite_id doesn't parse as ``archive/entry_path#section_id``
      * section isn't found in the bundle (or bundle lookup failed)
      * heading shares fewer than ``threshold`` of its tokens with the query

    Always returns a freshly-allocated dict so the caller may mutate it.
    """
    new_p = cast("SynthesizePassage", dict(passage))
    cite_id = passage["cite_id"]
    if "#" not in cite_id:
        return new_p
    base, _, section_id = cite_id.partition("#")
    archive_name, _, entry_path = base.partition("/")
    if not archive_name or not entry_path or not section_id:
        return new_p
    titles = _section_titles_for(
        archive_name, entry_path, bundle_lookup=bundle_lookup, cache=cache
    )
    heading_tokens = _affinity_tokens(titles.get(section_id, ""))
    if not heading_tokens:
        return new_p
    affinity = len(heading_tokens & query_tokens) / len(heading_tokens)
    if affinity >= threshold:
        new_p["score"] = float(passage["score"]) * boost
    return new_p


def _boost_by_section_affinity(
    passages: list[SynthesizePassage],
    *,
    query: str,
    bundle_lookup: Callable[[str, str], Any],
    config: "SynthesizeConfig",
) -> list[SynthesizePassage]:
    """Re-rank passages by section-heading affinity with the query.

    For each passage with a ``#section_id`` suffix on its cite_id,
    look up the section's heading in the bundle and compute
    ``|query_tokens ∩ heading_tokens| / |heading_tokens|``. When that
    affinity is ≥ ``config.section_affinity_threshold``, multiply the
    passage's score by ``config.section_affinity_boost``. Re-sort the
    list by score descending and re-number ranks.

    Article-level citations, passages whose section isn't in the
    bundle, and bundle-lookup failures are all no-ops: the passage is
    preserved with its original score. No-op when the query has no
    tokens. Bundle lookup is memoized per ``(archive, entry_path)``
    for the duration of the call.
    """
    query_tokens = _affinity_tokens(query)
    if not query_tokens:
        return passages

    cache: dict[tuple[str, str], dict[str, str]] = {}
    # Copy-on-append (each helper call returns a fresh dict) keeps the
    # mutation model uniform: the rank-renumbering loop below can mutate
    # any item in ``boosted`` without leaking back to the caller's list.
    boosted = [
        _maybe_boost_passage(
            p,
            query_tokens=query_tokens,
            bundle_lookup=bundle_lookup,
            cache=cache,
            threshold=config.section_affinity_threshold,
            boost=config.section_affinity_boost,
        )
        for p in passages
    ]
    boosted.sort(key=lambda p: float(p.get("score", 0.0)), reverse=True)
    # A14: rank reflects the post-boost ordering. Without this, downstream
    # consumers of passages[].rank get stale BM25 positions even though the
    # score-sorted order has changed.
    for i, p in enumerate(boosted, start=1):
        p["rank"] = i
    return boosted


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
    include_rank_score: bool = False,
) -> list[Citation]:
    """Expand passages' cite_ids into Citation entries; dedupe by cite_id.

    When ``include_rank_score`` is True (D8/Op4 compact-mode path), the
    passage rank and score fold into the citation row. The verbose
    path keeps citations metadata-only — rank/score live on
    ``SynthesizePassage`` in that mode.
    """
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
        citation: dict[str, Any] = {
            "cite_id": cite_id,
            "archive": archive,
            "entry_path": entry_path,
            "title": title,
            "section_id": section_id,
            "section_title": section_title,
        }
        if include_rank_score:
            citation["rank"] = int(p.get("rank", 0))
            citation["score"] = float(p.get("score", 0.0))
        seen[cite_id] = cast("Citation", citation)
    return list(seen.values())


# ---------------------------------------------------------------------------
# A14: multi-round handle builders for SynthesizeResponse
# ---------------------------------------------------------------------------

_DEFAULT_CONSIDERED_ARTICLES_MAX = 3
_DEFAULT_CONSIDERED_SECTIONS_MAX = 10


def _featured_article_key(
    capped_passages: list[SynthesizePassage],
) -> Optional[tuple[str, str, Optional[str]]]:
    """Decompose the top capped passage's cite_id into
    (archive, entry_path, section_id). Returns None when there are
    no passages.

    Used to identify which article+section to exclude from the
    considered handles — the caller already sees the featured
    citation, so surfacing it again as a "consider this instead"
    is noise.
    """
    if not capped_passages:
        return None
    return _parse_cite_id(capped_passages[0]["cite_id"])


def _humanize_path_title(title: str, entry_path: str) -> str:
    """Return a human-readable display title for a considered_articles
    entry.

    Post-a14 sweep (F5 / A3): some search-hit shapes carry no
    ``title`` field, or carry the underscored path verbatim
    (``"West_Michigan"`` instead of ``"West Michigan"``). The
    ``citations[]`` view in the same response sources titles from the
    entry bundle and always renders spaces, so seeing
    ``"West_Michigan"`` only in ``considered_articles[]`` is a
    cross-view inconsistency.

    Heuristic: if the title is empty or contains no whitespace but
    does contain underscores, treat it as path-shaped and swap
    underscores for spaces. Real Wikipedia display titles either
    already contain spaces or are single tokens — neither case
    triggers the rewrite.
    """
    if title and (" " in title or "_" not in title):
        return title
    source = title or entry_path
    return source.replace("_", " ")


def _build_considered_articles(
    top_hits: list[tuple[str, dict]],
    capped_passages: list[SynthesizePassage],
    *,
    max_n: int = _DEFAULT_CONSIDERED_ARTICLES_MAX,
    archive_titles: Optional[dict[tuple[str, str], str]] = None,
) -> list[ConsideredArticle]:
    """Top-N article hits NOT represented by the featured passage.

    Preserves order from top_hits (post-promotion, post-demotion).
    Each entry carries (archive, entry_path, title, score) — the
    caller can pass it to ``get_zim_entries`` or compose a cite_id.

    Title-source preference (post-a14 sweep, pass 2 self-audit):

      1. ``archive_titles[(archive, entry_path)]`` when supplied —
         this is the bundle's ``title`` field, the most authoritative
         human-readable name. Required for archives like IEP whose
         search-hit ``title`` field carries the entry path verbatim
         (``"iep.utm.edu/kantview/"``) and an underscore-replace
         heuristic can't help.
      2. ``hit.get("title")`` humanized via ``_humanize_path_title``
         — strips underscores when the hit title is path-shaped
         (Wikipedia's ``"West_Michigan"`` pattern).
      3. ``entry_path`` humanized as a last resort.
    """
    featured = _featured_article_key(capped_passages)
    featured_key: Optional[tuple[str, str]] = None
    if featured is not None:
        featured_key = (featured[0], featured[1])
    out: list[ConsideredArticle] = []
    for archive_name, hit in top_hits:
        entry_path = str(hit.get("path", ""))
        if not entry_path:
            continue
        if featured_key is not None and (archive_name, entry_path) == featured_key:
            continue
        bundle_title: Optional[str] = None
        if archive_titles is not None:
            bundle_title = archive_titles.get((archive_name, entry_path))
        # Bundle title wins when present and is not the path verbatim.
        # When the bundle's title equals the entry path (some archives
        # set entry.title to the path), fall through to the humanize
        # heuristic so the path's underscores get spaced.
        chosen_title: str
        if bundle_title and bundle_title != entry_path:
            chosen_title = bundle_title
        else:
            chosen_title = _humanize_path_title(str(hit.get("title", "")), entry_path)
        out.append(
            cast(
                "ConsideredArticle",
                {
                    "archive": archive_name,
                    "entry_path": entry_path,
                    "title": chosen_title,
                    "score": float(hit.get("score", 0.0)),
                },
            )
        )
        if len(out) >= max_n:
            break
    return out


def _build_considered_sections(
    capped_passages: list[SynthesizePassage],
    bundle_lookup: Callable[[str, str], Any],
    *,
    max_n: int = _DEFAULT_CONSIDERED_SECTIONS_MAX,
) -> list[ConsideredSection]:
    """Sections of the featured passage's article, minus the featured
    section itself. Capped at max_n.

    Empty list when:
      - There are no passages.
      - The featured article's bundle lookup returns None or raises.
      - The bundle's section list is empty.

    Post-a14-sweep change: a featured passage *without* a
    ``#section_id`` (article-level citation) no longer short-circuits
    to ``[]``. The common live-Wikipedia case for the post-a14 sweep
    was: section attribution failed because of natural-bold markup
    asymmetry, so featured passages dropped to entry-level cites and
    the next-turn pivot lost its sections. Surfacing the article's
    sections regardless of whether the featured passage itself was
    section-attributed is a strict improvement for that case.
    """
    featured = _featured_article_key(capped_passages)
    if featured is None:
        return []
    archive_name, entry_path, featured_section_id = featured
    try:
        bundle = bundle_lookup(archive_name, entry_path)
    except Exception as e:
        logger.debug(
            "considered_sections bundle lookup failed for %s/%s: %s",
            archive_name,
            entry_path,
            e,
        )
        return []
    if bundle is None:
        return []
    out: list[ConsideredSection] = []
    for section in bundle.get("sections", []):
        section_id = str(section.get("id", ""))
        # Drop empty ids unconditionally; drop the featured section
        # *only* when the featured passage actually had one (otherwise
        # there's nothing to exclude).
        if not section_id:
            continue
        if featured_section_id and section_id == featured_section_id:
            continue
        out.append(
            cast(
                "ConsideredSection",
                {
                    "section_id": section_id,
                    "title": str(section.get("title", section_id)),
                },
            )
        )
        if len(out) >= max_n:
            break
    return out


# Markdown link/image regex shared between simple_tools._strip_markdown_links
# and synthesize. Same disjoint-alternation shape as the simple_tools regex
# so the pattern engine doesn't backtrack against unclosed brackets.
_MD_LINK_RE = re.compile(r"\[([^\[\]]*?)\]\((?:[^()\n\\]|\\.)*\)")
_MD_IMAGE_RE = re.compile(r"!\[[^\[\]]*?\]\((?:[^()\n\\]|\\.)*\)")


def _strip_links_in_passage(p: SynthesizePassage) -> SynthesizePassage:
    """Strip Wikipedia-style markdown link syntax from a passage's text.

    Drops ``![alt](src)`` images entirely (alt-text + URL are rarely
    informative for a small model). Replaces ``[text](href "tooltip")``
    with ``text``. Idempotent on already-stripped text. Op4: useful
    when ``synthesize=True`` is called with ``compact=True``, where
    the simple-mode dispatcher otherwise applies the link strip to
    the rendered markdown but NOT to the passages list.
    """
    body = p["text_markdown"]
    if not body or "[" not in body:
        return p
    body = _MD_IMAGE_RE.sub("", body)
    body = _MD_LINK_RE.sub(r"\1", body)
    new_p = dict(p)
    new_p["text_markdown"] = body
    return cast("SynthesizePassage", new_p)


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
    """Stage 1: run per-archive Xapian search for every archive in the list.

    When two ZIM paths resolve to the same ``.stem`` (the user has
    ``foo/wikipedia.zim`` and ``bar/wikipedia.zim`` both configured), the
    raw stem can't act as a unique key for downstream bundle lookups —
    a collision silently re-routes attribution to whichever archive
    overwrote the dict entry. Detect duplicates and append a numeric
    suffix (``stem~2``, ``stem~3``) so each archive carries a unique
    name in ``archives_searched`` and ``archive_by_name``. The tilde
    keeps the suffix unambiguous to humans without hijacking a
    character that might appear in real ZIM filenames.
    """
    per_archive_hits: list[list[dict]] = []
    archives_searched: list[str] = []
    archive_by_name: dict[str, tuple[Archive, Path]] = {}
    stem_counts: dict[str, int] = {}
    for archive, validated_path in archives:
        base = validated_path.stem
        n = stem_counts.get(base, 0) + 1
        stem_counts[base] = n
        archive_name = base if n == 1 else f"{base}~{n}"
        if n > 1:
            logger.warning(
                "synthesize: duplicate ZIM stem %r — using %r for the %d-th archive "
                "(%s) so attribution stays correct",
                base,
                archive_name,
                n,
                validated_path,
            )
        archives_searched.append(archive_name)
        archive_by_name[archive_name] = (archive, validated_path)
        per_archive_hits.append(
            _per_archive_search(
                archive, search_handler=search_handler, query=query, k=k
            )
        )
    return per_archive_hits, archives_searched, archive_by_name


def _promote_title_match(
    top_hits: list[tuple[str, dict]],
    *,
    query: str,
    archives: list[tuple[Archive, Path]],
    archives_searched: list[str],
    search_handler: Any,
) -> list[tuple[str, dict]]:
    """Promote a canonical title-index hit past BM25 noise (D3 / Op1).

    A14: replaced the M26 4+ token short-circuit with greedy length-down
    tail iteration via ``iter_query_tails``. Long natural-language
    queries with a clear entity tail ("famous people from big rapids
    michigan") now resolve to ``Big_Rapids,_Michigan`` instead of
    falling through to BM25 noise.

    Mirrors the title-promotion logic in ``tell_me_about``: when the
    top BM25 hit isn't a strong title match for the query, ask each
    archive's title-index fast path for the canonical entry. If one
    archive answers, prepend that hit so the synthesized response
    leads with the canonical article instead of a derivative.

    Pre-existing BM25 hits are preserved — the promoted entry just
    moves to rank 1. Already-strong top hits short-circuit so the
    common case pays no extra archive probes.

    Probe order is (tail-length, archive-order): for each tail in
    greedy length-down order, try every archive. The first archive
    that resolves any tail wins. This picks the most specific entity
    that exists in any archive, biasing toward earlier-configured
    archives only when tails of equal length tie.
    """
    if top_hits:
        top_hit_0 = top_hits[0][1]
        top_path = str(top_hit_0.get("path", ""))
        # Use the path as the title proxy — Wikipedia exports preserve the
        # title in the path (``Berlin`` ↔ ``Berlin``) so the token-match
        # comparison works without a second archive read.
        if is_strong_title_match(query, top_path, top_path.replace("_", " ")):
            return top_hits

    # Post-b4 D3: mirror the ``_promote_topic_via_title_index`` pass-0
    # full-query probe at the start, so possessive queries
    # (``Einstein's theory`` → ``Theory_of_relativity``;
    # ``Plato's cave`` → ``Allegory_of_the_cave``) route to the
    # canonical redirect target instead of falling through to the
    # tail iteration below which would strip the apostrophe and
    # promote ``Theory`` / ``Cave``.
    # ``min_score=0.95`` matches the b4 pass-0 convention. The D1
    # ``fuzzy_suggest`` filter rejects raw fuzzy title-prefix
    # suggestions at the same score (``Darwin's evolution`` ≈
    # ``Evolution``) so only canonical redirects are auto-promoted.
    for (archive, _vp), archive_name in zip(archives, archives_searched):
        try:
            full_probe = find_title_match(archive, archive_name, query, min_score=0.95)
        except Exception as e:
            logger.debug(
                "_promote_title_match: pass-0 probe failed for %s on %r: %s",
                archive_name,
                query,
                e,
            )
            continue
        if (
            isinstance(full_probe, dict)
            and full_probe.get("path")
            and full_probe.get("match_type") != "fuzzy_suggest"
        ):
            full_path = str(full_probe["path"])
            existing_paths_p0 = {(name, str(h.get("path", ""))) for name, h in top_hits}
            if (archive_name, full_path) in existing_paths_p0:
                reordered_p0: list[tuple[str, dict]] = [
                    (n, h)
                    for n, h in top_hits
                    if not (n == archive_name and str(h.get("path", "")) == full_path)
                ]
                promoted_hit_p0 = next(
                    h
                    for n, h in top_hits
                    if n == archive_name and str(h.get("path", "")) == full_path
                )
                return [(archive_name, promoted_hit_p0), *reordered_p0]
            return [(archive_name, full_probe), *top_hits]

    title_match_hit = getattr(search_handler, "title_match_hit", None)
    if not callable(title_match_hit):
        return top_hits

    # Post-b4 D2 mirror: tighten the tail-iteration ``min_len`` floor
    # to 2 when the query carries an apostrophe-possessive so a
    # generic 1-token tail (``"theory"`` / ``"cave"``) can't silently
    # outrank the canonical the pass-0 probe just missed.
    pass_tail_min_len = 2 if has_apostrophe_possessive(query) else 1
    existing_paths = {(name, str(h.get("path", ""))) for name, h in top_hits}
    for tail in iter_query_tails(query, min_len=pass_tail_min_len):
        for (archive, _vp), archive_name in zip(archives, archives_searched):
            try:
                promoted = title_match_hit(archive, tail)
            except Exception as e:
                logger.debug(
                    "title_match_hit failed for %s on tail %r: %s",
                    archive_name,
                    tail,
                    e,
                )
                continue
            # Defensive: tolerate mock handlers that return non-dict
            # sentinel values; only act on a real hit payload.
            if not isinstance(promoted, dict):
                continue
            promoted_path = str(promoted.get("path", ""))
            if not promoted_path:
                continue
            if (archive_name, promoted_path) in existing_paths:
                # Already present — re-rank it to first instead of duplicating.
                reordered: list[tuple[str, dict]] = [
                    (n, h)
                    for n, h in top_hits
                    if not (
                        n == archive_name and str(h.get("path", "")) == promoted_path
                    )
                ]
                promoted_hit = next(
                    h
                    for n, h in top_hits
                    if n == archive_name and str(h.get("path", "")) == promoted_path
                )
                return [(archive_name, promoted_hit), *reordered]
            return [(archive_name, promoted), *top_hits]
    return top_hits


_LIST_ARTICLE_PREFIX_RE = re.compile(
    r"^(?:List|Index|Outline|Glossary|Timeline|Bibliography|Lists)_of_",
    re.IGNORECASE,
)

# A11 G1 (post-a10): list-shaped articles whose names don't start with
# ``List_of_`` but behave identically — long enumeration, no narrative.
# ``Listed_buildings_in_North_Yorkshire`` and music-industry catalogs
# (``Rephlex_Records_discography``) ranked top-3 in synthesize for
# unrelated queries (``tell me about cats`` returned a Rephlex
# discography). Match each suffix as a whole-word path component so
# ``Discography`` alone doesn't sweep the canonical
# ``Music_industry_discography`` article — the suffix has to come at
# the tail of the path.
_LIST_ARTICLE_SUFFIX_RE = re.compile(
    r"_(?:discography|filmography|videography|bibliography|"
    r"awards|honors|appearances|albums|singles|recordings|"
    r"appearances_and_filmography)$",
    re.IGNORECASE,
)

# Stem-shaped patterns: ``Listed_buildings_in_…``,
# ``Index_of_…`` (already covered by prefix), ``Member_of_…``
# enumeration articles.
_LIST_ARTICLE_STEM_RE = re.compile(r"^Listed_", re.IGNORECASE)


def _is_list_article(hit: dict) -> bool:
    """O5 (beta) + A11 G1 (post-a10): identify list/index/catalog
    articles to demote in synthesize.

    Wikipedia list articles (``List_of_textbooks_on_classical_mechanics``,
    ``Index_of_…``, ``Outline_of_…``, ``Timeline_of_…``) and their
    plural/stem variants (``Lists_of_musicians``, ``Listed_buildings_in_…``)
    plus music-industry catalog articles (``X_discography``,
    ``X_filmography``) carry a single stub paragraph plus a long
    enumeration. They rank surprisingly high in Xapian search because
    their bodies match many query tokens, but in synthesize their stub
    text adds ~50 tokens of noise without informational signal. We
    don't drop them — sometimes the list IS the answer — just push
    them to the back of the top_n.
    """
    path = hit.get("path") or ""
    if _LIST_ARTICLE_PREFIX_RE.match(path):
        return True
    if _LIST_ARTICLE_STEM_RE.match(path):
        return True
    if _LIST_ARTICLE_SUFFIX_RE.search(path):
        return True
    return False


def _drop_low_relevance_tail(
    top_hits: list[tuple[str, dict]],
    *,
    fallback_used: str,
    threshold_ratio: float = 0.25,
) -> list[tuple[str, dict]]:
    """A11 G2 (post-a10): drop hits whose Xapian score is below
    ``threshold_ratio`` of the top hit's score.

    Live testing showed ``tell me about cats`` returning
    ``Rephlex_Records_discography`` as rank-2 with score 1.0 because
    RRF normalizes scores to ``1/(k+rank)`` regardless of underlying
    relevance — a weak match looks identical to a strong one. The
    original Xapian score is preserved on each hit (when search
    returns it) as ``score`` or ``xapian_score``; use that as the
    relevance signal.

    Conservative behavior:
      * Single-archive (``xapian_score`` fallback): apply the
        threshold because all hits share the same scoring basis.
      * Multi-archive (``rrf_fusion``): keep all hits — the RRF
        score is rank-based, not relevance-based, so a low-rank-in-
        the-fused-list hit might still be a strong match in its
        source archive.
      * Always keep at least one hit so empty-set checks downstream
        don't fall over.
    """
    if not top_hits or fallback_used != "xapian_score":
        return top_hits

    # Read the Xapian relevance score off each hit. Possible keys
    # (varies by search path): ``xapian_score`` (preferred),
    # ``score`` (legacy), ``relevance`` (alt). Fall back to None when
    # absent.
    def _xapian_score(hit: dict) -> Optional[float]:
        for key in ("xapian_score", "score", "relevance"):
            value = hit.get(key)
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
        return None

    scores = [_xapian_score(hit) for _, hit in top_hits]
    top_score = scores[0]
    if top_score is None:
        return top_hits
    threshold = top_score * threshold_ratio
    filtered = [
        (archive, hit)
        for (archive, hit), score in zip(top_hits, scores)
        if score is None or score >= threshold
    ]
    return filtered or top_hits[:1]


def _demote_list_articles(
    top_hits: list[tuple[str, dict]],
) -> list[tuple[str, dict]]:
    """Stable-partition list articles to the bottom of the top_hits set.

    Preserves order within each partition so the fusion's ranking
    decision is preserved for the meaningful articles AND for any list
    articles that survived. Only reorders the top_n that's already been
    selected — does not change the set of included hits.
    """
    if not top_hits:
        return top_hits
    non_list = [t for t in top_hits if not _is_list_article(t[1])]
    list_hits = [t for t in top_hits if _is_list_article(t[1])]
    if not list_hits:
        return top_hits
    return non_list + list_hits


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

    Note: ``_demote_list_articles`` runs in ``synthesize_query`` AFTER
    ``_promote_title_match`` (not here). Demoting before promotion lets
    a list article slip into position 0 of ``top_hits``; that position
    then passes ``_promote_title_match``'s strong-match guard via the
    candidate-extends-topic rule (``Berlin`` → ``Berlin_(…)``) and the
    canonical entry never gets promoted.
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
        return _bundle_mod.get_or_build_bundle(
            archive_val,
            entry_path,
            cache=cache,
            validated_path=validated_path,
            content_processor=content_processor,
        )

    return bundle_lookup


def _extract_passages_for_top_hits(
    top_hits: list[tuple[str, dict]],
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
            "considered_articles": [],
            "considered_sections": [],
        },
    )


def _maybe_rerank_synthesize_passages(
    all_passages: list[SynthesizePassage],
    hit_keys: list[tuple[str, str]],
    *,
    query: str,
    top_hits: list[tuple[str, dict[str, Any]]],
    reranker_config: "Optional[RerankerConfig]",
) -> tuple[list[SynthesizePassage], list[tuple[str, str]]]:
    """Apply cross-encoder rerank to synthesize passage candidates.

    Wraps ``BGEReranker.get()`` and returns ``(reranked_passages,
    parallel_hit_keys)``.  When the [reranker] extra is absent, disabled,
    or ``reranker_config`` is ``None``, returns the inputs unchanged.
    """
    if reranker_config is None:
        return all_passages, hit_keys

    from openzim_mcp.ml.reranker import BGEReranker

    reranker = BGEReranker.get(reranker_config)
    if reranker is None:
        logger.info("telemetry: reranker_skipped.not_installed")
        return all_passages, hit_keys
    if not all_passages:
        logger.info("telemetry: reranker_skipped.no_results")
        return all_passages, hit_keys

    # Build path→passage index for round-trip mapping. cite_id
    # is "archive_name/entry_path"; use it as the envelope path
    # key (unique per passage within this pipeline run).
    envelopes = [
        {
            "path": p["cite_id"],
            "snippet": p["text_markdown"][: reranker_config.max_passage_length],
            "xapian_score": float(p.get("score", 0.0)),
        }
        for p in all_passages
    ]
    # Rerank ALL passages (top_k = len); top-K trim happens later
    # via _enforce_budget after deduplication/attribution steps.
    reranked_envelopes = reranker.rerank(
        query=query,
        candidates=envelopes,
        top_k=len(all_passages),
    )
    if not (reranked_envelopes and "rerank_score" in reranked_envelopes[0]):
        # Short query or inference failure — passthrough.
        logger.info("telemetry: reranker_skipped.passthrough")
        return all_passages, hit_keys

    # Build a lookup from cite_id → rerank_score for sorting.
    score_by_cite_id = {e["path"]: e["rerank_score"] for e in reranked_envelopes}
    # Preserve only passages that survived the reranker
    # (in case of dedup inside rerank); sort descending.
    all_passages = [p for p in all_passages if p["cite_id"] in score_by_cite_id]
    all_passages.sort(
        key=lambda p: score_by_cite_id[p["cite_id"]],
        reverse=True,
    )
    # Propagate rerank_score into the passage's score field so
    # the downstream _boost_by_section_affinity sort (which
    # uses p["score"]) preserves the rerank ordering rather
    # than reverting to Xapian BM25 scores.
    for p in all_passages:
        p["score"] = score_by_cite_id[p["cite_id"]]
    # Re-number ranks to reflect new ordering.
    for i, p in enumerate(all_passages, start=1):
        p["rank"] = i
    logger.info(
        "telemetry: reranker_engaged — reranked %d passages for query %r",
        len(all_passages),
        query,
    )
    # Also re-order hit_keys to stay parallel with all_passages.
    cite_id_to_hit_key = {
        f"{archive_name}/{hit['path']}": (archive_name, hit["path"])
        for archive_name, hit in top_hits
    }
    new_hit_keys: list[tuple[str, str]] = []
    for p in all_passages:
        hit_key = cite_id_to_hit_key.get(p["cite_id"])
        if hit_key is None:
            logger.warning(
                "synthesize: hit_key miss for cite_id %r; "
                "section attribution will degrade for this passage",
                p["cite_id"],
            )
            hit_key = ("", "")
        new_hit_keys.append(hit_key)
    return all_passages, new_hit_keys


def synthesize_query(
    query: str,
    *,
    archives: list[tuple[Archive, Path]],  # (archive, validated_path) pairs
    search_handler: Any,
    cache: OpenZimMcpCache,
    content_processor: ContentProcessor,
    config: SynthesizeConfig,
    reranker_config: "Optional[RerankerConfig]" = None,
    original_query: Optional[str] = None,
    strip_links: bool = False,
    omit_passage_text: bool = False,
) -> SynthesizeResponse:
    """Run the synthesize pipeline end-to-end.

    ``original_query`` is echoed back as ``response["query"]`` when
    supplied — the caller is responsible for any pre-processing
    (intent-prefix stripping for D5) and ``original_query`` lets the
    user-facing query be preserved while ``query`` carries the
    BM25-friendly form.

    ``strip_links`` (Op4): when True, markdown-link soup
    ``[text](href "tooltip")`` in passages is stripped to plain text
    before rendering. Wikipedia exports are ~50% link syntax in the
    head of a typical article; stripping doubles the useful prose
    density for small models that can't follow inline links anyway.

    ``omit_passage_text`` (D8): when True, the ``passages[]`` array
    drops ``text_markdown`` (which is verbatim-duplicated inside
    ``answer_markdown``) and keeps only the lightweight metadata
    (``cite_id``, ``rank``, ``score``). Cuts the response by ~50%
    on a typical 5-passage synthesize call.

    ``reranker_config`` (sub-D-1): when supplied, the cross-encoder
    reranker is consulted after passage extraction and before section
    attribution. If the reranker extra is absent or disabled the
    parameter has no effect.
    """
    per_archive_hits, archives_searched, archive_by_name = _do_per_archive_search(
        archives,
        search_handler=search_handler,
        query=query,
        k=config.per_archive_k,
    )
    top_hits, fallback_used = _select_top_hits(
        per_archive_hits, archives_searched, top_n=config.top_n
    )
    # D3 / Op1: when BM25 ranks "List of songs about Berlin" above the
    # canonical "Berlin" article for query="Berlin", title-index
    # promotion replaces the top hit with the canonical entry — same
    # shape as the simple-mode tell_me_about path. Applied AFTER
    # fusion so multi-archive RRF still drives the lower-ranked
    # ordering, but BEFORE passage extraction so the promoted entry
    # flows through the same bundle / attribution stages as a normal hit.
    top_hits = _promote_title_match(
        top_hits,
        query=query,
        archives=archives,
        archives_searched=archives_searched,
        search_handler=search_handler,
    )
    # O5 (beta): demote list articles after title promotion has run. The
    # promotion's strong-match guard treats ``Berlin_(disambiguation)``
    # as a candidate-extends-topic match for ``Berlin``, so demoting
    # ``List_of_songs_about_Berlin`` to the bottom BEFORE promotion lets
    # ``Berlin_(disambiguation)`` claim rank 0 and skip the canonical
    # promotion. Demoting AFTER preserves the promotion's decision and
    # only reorders the survivors.
    top_hits = _demote_list_articles(top_hits)
    # A11 G2 (post-a10): drop hits whose Xapian relevance score is
    # < 25% of the top hit's score. ``tell me about cats`` was
    # returning ``Rephlex_Records_discography`` at rank 2 with score
    # equal to the top hit (1.0 each) because RRF normalizes scores
    # — but the underlying Xapian relevance was a fraction of the
    # canonical Cats article. Read the original Xapian score from
    # the hit dict to apply the threshold before passage extraction
    # wastes work on weak matches. Conservative: keep all hits when
    # we can't compare scores (RRF-fused multi-archive sets where the
    # underlying scores aren't on the same scale).
    top_hits = _drop_low_relevance_tail(top_hits, fallback_used=fallback_used)
    response_query = original_query if original_query is not None else query
    if not top_hits:
        # Even with empty BM25 hits, a canonical title hit might still
        # exist (rare: the title isn't in the full-text index but is in
        # the title index). Try one more time before declaring 0-hit.
        promoted = _promote_title_match(
            [],
            query=query,
            archives=archives,
            archives_searched=archives_searched,
            search_handler=search_handler,
        )
        if not promoted:
            return _zero_hits_response(response_query, archives_searched, fallback_used)
        top_hits = _demote_list_articles(promoted)

    all_passages, hit_keys = _extract_passages_for_top_hits(top_hits)

    # Phase D sub-D-1: rerank passage candidates before section attribution.
    # Synthesize is the primary content-fragment-query surface; reranking
    # here re-orders passages by semantic relevance before the attribution
    # and budget-enforcement stages commit to a final ordering.
    all_passages, hit_keys = _maybe_rerank_synthesize_passages(
        all_passages,
        hit_keys,
        query=query,
        top_hits=top_hits,
        reranker_config=reranker_config,
    )

    if strip_links:
        all_passages = [_strip_links_in_passage(p) for p in all_passages]
    bundle_lookup = _make_bundle_lookup(
        top_hits,
        archive_by_name,
        cache=cache,
        content_processor=content_processor,
    )
    attributed = _attribute_sections(
        all_passages, bundle_lookup=bundle_lookup, hit_keys=hit_keys
    )
    # A14 (Change B): section-heading affinity boost. Promotes passages
    # whose section heading shares tokens with the query past lexically-
    # weaker BM25 leaders. No-op for article-level citations and for
    # queries with no token overlap against any heading.
    attributed = _boost_by_section_affinity(
        attributed,
        query=query,
        bundle_lookup=bundle_lookup,
        config=config,
    )
    pre_cap_chars = sum(len(p["text_markdown"]) for p in attributed)
    capped = _enforce_budget(attributed, char_budget=config.output_char_budget)
    truncated = sum(len(p["text_markdown"]) for p in capped) < pre_cap_chars
    answer_md = _render_answer(capped)
    archive_titles, section_titles = _build_section_lookups(top_hits, bundle_lookup)
    citations = _build_citations(
        capped,
        archive_titles=archive_titles,
        section_titles=section_titles,
        # D8/Op4: in compact mode, fold rank/score into citations so
        # the dropped passages[] array isn't a data loss.
        include_rank_score=omit_passage_text,
    )
    # Real _meta envelope (not the hardcoded `{}` of earlier versions).
    # ``rendered`` is the answer body — same convention as simple-mode
    # responses, so ``_meta.chars``/``tokens_est`` reflect what the
    # caller actually sees, not the JSON envelope cost.
    from openzim_mcp.meta import build_meta as _build_meta

    # D7 (v2.0.0a9): synthesize is NOT resumable by content offset —
    # the next "page" of the synthesized answer would require re-running
    # the pipeline against a different starting passage, not slicing
    # an already-rendered string. Pass ``content_chars=None`` so the
    # meta envelope omits ``more_at_offset`` (the prior shape emitted a
    # nonsensical value: ``len(answer_md)`` mixed with a ``total_chars``
    # field that measured passage chars, not answer chars). The caller
    # still sees ``truncated=True`` + ``total_chars`` as informational
    # "how much was cut" signals.
    meta = _build_meta(
        rendered=answer_md,
        truncated=truncated,
        content_chars=None,
        total_chars=pre_cap_chars if truncated else None,
    )
    # D8 / Op4 (v2.0.0a9): compact mode drops the passages array
    # entirely. The passages were already structurally redundant
    # after the earlier text-dedup pass (only cite_id/rank/score
    # remained, and cite_id duplicates citations[].cite_id). To preserve
    # the positional rank/score signal, fold those into the citation
    # rows directly. Verbose mode (omit_passage_text=False) keeps the
    # legacy passages array intact for callers doing downstream
    # processing.
    response_passages: list[SynthesizePassage] = capped
    if omit_passage_text:
        response_passages = []
    considered_articles = _build_considered_articles(
        top_hits, capped, archive_titles=archive_titles
    )
    considered_sections = _build_considered_sections(capped, bundle_lookup)
    return cast(
        "SynthesizeResponse",
        {
            "query": response_query,
            "answer_markdown": answer_md,
            "passages": response_passages,
            "citations": citations,
            "archives_searched": archives_searched,
            "fallback_used": fallback_used,
            "total_chars": len(answer_md),
            "total_words": len(answer_md.split()),
            "_meta": cast("Any", meta),
            "considered_articles": considered_articles,
            "considered_sections": considered_sections,
        },
    )
