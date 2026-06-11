"""Regression tests for code-review 2026-06-10 Phase 6 (synthesize / rerank).

H9 (search_all rerank passthrough zeroes later archives), M17 (affinity boost
inverts for negative scores), M18 (possessive tail-rescue prepends a duplicate
already in top_hits), M19 (low-relevance tail filter uses the 1/rank proxy as
relevance).
"""

from typing import Any, Dict
from unittest.mock import MagicMock

import openzim_mcp.ml.reranker as reranker_mod
from openzim_mcp.rerank import _RerankMixin
from openzim_mcp.synthesize import (
    _boost_by_section_affinity,
    _drop_low_relevance_tail,
    _promote_title_match,
)


# H9 — passthrough rerank must not zero out later archives' hits
class _PassthroughReranker:
    """Mimics BGEReranker's skip path: returns candidates[:top_k] in input
    order with NO ``rerank_score`` key."""

    def rerank(self, *, query, candidates, top_k):
        return [dict(c) for c in candidates[:top_k]]


class _Handler(_RerankMixin):
    def __init__(self):
        self.zim_operations = MagicMock()
        self.zim_operations.config.ml.reranker.final_top_k = 10
        self.tracked = []

    def _track(self, event):  # noqa: D401 - test stub
        self.tracked.append(event)


def test_h9_passthrough_preserves_all_archive_hits(monkeypatch):
    monkeypatch.setattr(
        reranker_mod.BGEReranker,
        "get",
        classmethod(lambda cls, cfg: _PassthroughReranker()),
    )
    # 3 archives x 5 hits each.
    per_file = [
        {
            "zim_file_path": f"a{i}.zim",
            "has_hits": True,
            "error": None,
            "result": {"results": [{"path": f"A/{i}_{j}"} for j in range(5)]},
        }
        for i in range(3)
    ]
    handler = _Handler()
    out = handler._maybe_rerank_search_all(per_file=per_file, query="french revolution")

    # Every archive keeps its 5 Xapian hits — none zeroed.
    for entry in out:
        assert entry["has_hits"] is True
        assert len(entry["result"]["results"]) == 5
    assert "reranker_skipped.passthrough" in handler.tracked
    assert "reranker_engaged" not in handler.tracked


def test_h9_real_rerank_still_redistributes(monkeypatch):
    class _ScoringReranker:
        def rerank(self, *, query, candidates, top_k):
            # Tag with a rerank_score so the redistribute path runs.
            return [
                {**dict(c), "rerank_score": 1.0 - n}
                for n, c in enumerate(candidates[:top_k])
            ]

    monkeypatch.setattr(
        reranker_mod.BGEReranker,
        "get",
        classmethod(lambda cls, cfg: _ScoringReranker()),
    )
    per_file = [
        {
            "zim_file_path": "a0.zim",
            "has_hits": True,
            "error": None,
            "result": {"results": [{"path": "A/x"}, {"path": "A/y"}]},
        }
    ]
    handler = _Handler()
    out = handler._maybe_rerank_search_all(per_file=per_file, query="q")
    assert "reranker_engaged" in handler.tracked
    # The internal routing tag is stripped on redistribution.
    assert "_rerank_src_idx" not in out[0]["result"]["results"][0]
    assert len(out[0]["result"]["results"]) == 2


# M17 — affinity boost must promote a matching passage even with a negative score
def test_m17_negative_score_passage_promoted_not_demoted(monkeypatch):
    # Heading for the matching passage's section is "Theory of relativity";
    # the non-matching passage has a section with no query-token overlap.
    monkeypatch.setattr(
        "openzim_mcp.synthesize._section_titles_for",
        lambda archive, entry, *, bundle_lookup, cache: {
            "s1": "Theory of relativity",
            "s2": "External links",
        },
    )
    passages = [
        # Non-matching section, higher (less negative) raw score — would win
        # under the old ``score * boost`` demotion bug.
        {"cite_id": "w/Einstein#s2", "score": -0.9, "rank": 1, "text": "x"},
        # Matching section, lower (more negative) raw score. Old bug:
        # -1.0 * 1.5 = -1.5 (demoted below -0.9). Fixed: -1.0 / 1.5 = -0.667
        # (promoted above -0.9).
        {"cite_id": "w/Einstein#s1", "score": -1.0, "rank": 2, "text": "y"},
    ]
    cfg = MagicMock()
    cfg.section_affinity_threshold = 0.3
    cfg.section_affinity_boost = 1.5
    boosted = _boost_by_section_affinity(
        passages, query="relativity", bundle_lookup=lambda a, e: None, config=cfg
    )
    # The matching (#s1) passage now sorts first (promoted, not demoted).
    assert boosted[0]["cite_id"] == "w/Einstein#s1"
    # Its boosted score moved toward zero (greater than its input -1.0).
    assert boosted[0]["score"] > -1.0


# M18 — possessive tail-rescue must not prepend a canonical already in top_hits
def _rescue_handler(title_index_by_query, hit_by_title):
    """Stub ZimOperations for ``_promote_title_match``'s rescue path.

    ``find_entry_by_title_data`` answers the (apostrophe-preserving) title-index
    probes; ``title_match_hit`` answers the bare-tail fast-path probes.
    """
    m = MagicMock()

    def fake_fetbd(
        _vp: str, q: str, *, cross_file: bool = False, limit: int = 3
    ) -> Dict[str, Any]:
        row = title_index_by_query.get(q.lower())
        return {"results": [row] if row else []}

    m.find_entry_by_title_data.side_effect = fake_fetbd
    m.title_match_hit.side_effect = lambda _archive, title: hit_by_title.get(
        title.lower()
    )
    return m


def test_m18_rescue_reorders_existing_canonical_no_duplicate():
    # ``einstein's theory`` (stripped to ``einstein theory``) tail-rescues the
    # multi-token canonical ``Theory_of_relativity``. Here that canonical is
    # ALREADY a BM25 hit (rank 2): the rescue must reorder it to front, not
    # prepend a second copy (duplicate cite_id / passage / budget spend).
    handler = _rescue_handler(
        title_index_by_query={
            "einstein's theory": {
                "path": "Theory_of_relativity",
                "title": "Theory of relativity",
                "score": 1.0,
            },
            "theory": {"path": "Theory", "title": "Theory", "score": 1.0},
        },
        hit_by_title={
            "theory": {"path": "Theory", "snippet": "...", "score": 1.0},
            "theory of relativity": {
                "path": "Theory_of_relativity",
                "snippet": "rebuilt",
                "score": 1.0,
            },
        },
    )
    archive = object()
    top_hits = [
        ("wikipedia", {"path": "Some_BM25_Noise", "snippet": "", "score": 0.5}),
        # Canonical already present at rank 2 (the documented Einstein case).
        (
            "wikipedia",
            {"path": "Theory_of_relativity", "snippet": "orig", "score": 0.4},
        ),
    ]
    out = _promote_title_match(
        top_hits,
        query="einstein theory",
        original_query="einstein's theory",
        archives=[(archive, "wiki.zim")],
        archives_searched=["wikipedia"],
        search_handler=handler,
    )
    # Canonical reordered to front and tagged promoted.
    assert out[0][1]["path"] == "Theory_of_relativity"
    assert out[0][1].get("promoted") is True
    # No duplicate: length preserved and exactly one canonical entry.
    assert len(out) == len(top_hits)
    canonical = [h for _, h in out if h["path"] == "Theory_of_relativity"]
    assert len(canonical) == 1
    # The existing hit was reused (snippet "orig"), not a freshly built copy.
    assert canonical[0]["snippet"] == "orig"


# M19 — the relevance-tail filter must not drop the rank-5 hit on the 1/rank proxy
def test_m19_fabricated_score_does_not_drop_rank5():
    # search_top_k fabricates score = 1.0/rank; nothing carries a real
    # xapian_score, so the threshold must be a no-op (keep all 5).
    top_hits = [("w", {"path": f"A/{i}", "score": 1.0 / i}) for i in range(1, 6)]
    out = _drop_low_relevance_tail(top_hits, fallback_used="xapian_score")
    assert len(out) == 5


def test_m19_real_xapian_score_still_filters():
    top_hits = [
        ("w", {"path": "A/1", "xapian_score": 10.0}),
        ("w", {"path": "A/2", "xapian_score": 1.0}),  # below 10*0.25 -> dropped
    ]
    out = _drop_low_relevance_tail(top_hits, fallback_used="xapian_score")
    assert len(out) == 1
    assert out[0][1]["path"] == "A/1"
