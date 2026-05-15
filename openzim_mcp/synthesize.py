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

from openzim_mcp import bundle as _bundle_mod
from openzim_mcp.title_promotion import is_strong_title_match, iter_query_tails
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


def _locate_passage(md: str, passage_text: str) -> int:
    """Return the offset of ``passage_text`` within ``md``, or -1 on miss.

    Tries the exact match first (cheap, common). Falls back to a
    whitespace-normalized search so attribution survives whitespace or
    inline-markup drift between the snippet rendering path and the
    bundle's rendered markdown. The returned offset is into the
    *original* ``md`` so callers can map it back to section ranges.

    Passes the bold-stripped form to both probes — ``create_snippet``'s
    query-highlight wrapper inserts ``**...**`` around the query term,
    but the bundle markdown is rendered without highlighting, so a
    literal ``md.find(passage_text)`` misses every snippet that
    carries a highlighted term. Section attribution (D8) depends on
    these probes hitting.
    """
    passage_text = _strip_bold(passage_text)
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
    # in lockstep with md_norm, advancing the normalized cursor only when
    # we cross a non-space boundary or a single whitespace run. The
    # ``norm_cursor > 0`` guard the previous version carried suppressed
    # counting the first whitespace run, which made the cursor undercount
    # whenever ``md`` opened with whitespace before the matched span —
    # attribution then landed in the *next* section. ``_normalize_ws``
    # already strips leading whitespace from ``md_norm`` so the run we
    # need to track always begins after non-space content; no guard is
    # required.
    md_cursor = 0
    norm_cursor = 0
    prev_was_space = False
    while md_cursor < len(md) and norm_cursor < probe_pos:
        ch = md[md_cursor]
        if ch.isspace():
            if not prev_was_space:
                norm_cursor += 1
            prev_was_space = True
        else:
            norm_cursor += 1
            prev_was_space = False
        md_cursor += 1
    # Probes are normalized + trimmed so probe[0] is always a non-space
    # character. After lockstep walk the cursor may sit on the first
    # whitespace of a run that md_norm collapsed to one space — advance
    # past any remaining whitespace so the returned offset points at the
    # first non-space char of the match in the original md. Without this
    # step, attribution can land in an earlier section when two section
    # boundaries hug a whitespace run.
    while md_cursor < len(md) and md[md_cursor].isspace():
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

    title_match_hit = getattr(search_handler, "title_match_hit", None)
    if not callable(title_match_hit):
        return top_hits

    existing_paths = {(name, str(h.get("path", ""))) for name, h in top_hits}
    for tail in iter_query_tails(query):
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
                    if not (n == archive_name and str(h.get("path", "")) == promoted_path)
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
        },
    )
