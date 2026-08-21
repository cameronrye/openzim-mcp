"""Rerank must not undo the canonical splice one statement after it runs.

Pass 5 (1e1bd8e) made ``_splice_title_match_into_search`` prepend the synthetic
canonical row as an EXTRA rather than a replacement, so a spliced first page
carries ``limit + 1`` rows and ``page_info["source_consumed"]`` records that
only ``limit`` ranked rows were consumed.

``_handle_search`` then hands that page to ``_maybe_rerank_compact`` with the
caller's ``limit``, which set ``effective_top_k = limit`` — re-applying the
very cut pass 5 removed, and violating the invariant its own comment states
("the caller's page size wins; rerank only REORDERS it"). That invariant held
only while ``len(candidates) == limit``, which the splice broke.

Worse, the row that died was near-deterministically the canonical one:
``BGEReranker.rerank`` scores ``snippet or path`` as the passage, and the
synthetic row's snippet is the sentinel ``(canonical title match)``. Measured
on the shipped corpus with the real BAAI/bge-reranker-base, that placeholder
scored -5.5 against +4.6 for a real hit, so the splice's whole purpose was
inverted: with the reranker installed the canonical vanished from the page
entirely, while the control run (reranker disabled) showed it at rank 1.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from openzim_mcp.constants import CANONICAL_TITLE_MATCH_SNIPPET
from openzim_mcp.simple_tools import SimpleToolsHandler


def _handler() -> SimpleToolsHandler:
    return SimpleToolsHandler(MagicMock())


def _spliced_payload(limit: int = 3) -> Dict[str, Any]:
    """A page shaped exactly as the pass-5 splice leaves it."""
    ranked = [
        {"path": f"A/Ranked{i}", "title": f"Ranked{i}", "snippet": f"body {i}"}
        for i in range(limit)
    ]
    canonical = {
        "path": "A/Canonical",
        "title": "Canonical",
        "snippet": CANONICAL_TITLE_MATCH_SNIPPET,
    }
    return {
        "query": "history of the canonical subject matter",
        "results": [canonical, *ranked],
        "next_cursor": "opaque",
        "total": 70,
        "done": False,
        "page_info": {
            "offset": 0,
            "limit": limit,
            "returned_count": limit + 1,
            "source_consumed": limit,
        },
    }


def _scoring_stub(score_fn: Any) -> MagicMock:
    """A reranker that really scores (so the swap-in branch is taken)."""
    stub = MagicMock()

    def _rerank(query: str, candidates: List[dict], top_k: int) -> List[dict]:
        decorated = [(c, score_fn(c)) for c in candidates]
        decorated.sort(key=lambda x: x[1], reverse=True)
        return [{**c, "rerank_score": float(s)} for c, s in decorated[:top_k]]

    stub.rerank = MagicMock(side_effect=_rerank)
    return stub


def test_rerank_does_not_drop_a_row_from_a_spliced_page() -> None:
    """``limit + 1`` rows in, ``limit + 1`` rows out."""
    handler = _handler()
    payload = _spliced_payload(limit=3)
    # Score the canonical last, exactly as the real cross-encoder does when
    # handed the sentinel placeholder as its passage.
    stub = _scoring_stub(
        lambda c: -99.0 if c["snippet"] == CANONICAL_TITLE_MATCH_SNIPPET else 1.0
    )
    with patch("openzim_mcp.ml.reranker.BGEReranker.get", return_value=stub):
        out = handler._maybe_rerank_compact(
            payload=payload, query=payload["query"], limit=3
        )

    paths = [r["path"] for r in out["results"]]
    assert len(paths) == 4, (
        "rerank capped the spliced page back to `limit`, re-creating the "
        "unreachable-row defect pass 5 removed"
    )
    assert set(paths) == {"A/Canonical", "A/Ranked0", "A/Ranked1", "A/Ranked2"}


def test_canonical_row_is_not_scored_against_the_ranked_stream() -> None:
    """The splice put the canonical first; rerank must leave it there.

    Its snippet is a placeholder, not content, so scoring it as a passage
    compares the cross-encoder's view of ``(canonical title match)`` against
    real article text — which the row loses every time.
    """
    handler = _handler()
    payload = _spliced_payload(limit=3)
    stub = _scoring_stub(
        lambda c: -99.0 if c["snippet"] == CANONICAL_TITLE_MATCH_SNIPPET else 1.0
    )
    with patch("openzim_mcp.ml.reranker.BGEReranker.get", return_value=stub):
        out = handler._maybe_rerank_compact(
            payload=payload, query=payload["query"], limit=3
        )

    assert out["results"][0]["path"] == "A/Canonical"
    # The sentinel must never have reached the model as a passage.
    scored_passages = [
        c.get("snippet") for c in stub.rerank.call_args.kwargs["candidates"]
    ]
    assert CANONICAL_TITLE_MATCH_SNIPPET not in scored_passages


def test_ranked_rows_are_still_reordered() -> None:
    """Pinning the canonical must not disable reranking of the rest."""
    handler = _handler()
    payload = _spliced_payload(limit=3)
    # Reverse the ranked rows by score.
    stub = _scoring_stub(
        lambda c: (
            0.0
            if c["snippet"] == CANONICAL_TITLE_MATCH_SNIPPET
            else float(c["path"][-1])
        )
    )
    with patch("openzim_mcp.ml.reranker.BGEReranker.get", return_value=stub):
        out = handler._maybe_rerank_compact(
            payload=payload, query=payload["query"], limit=3
        )

    paths = [r["path"] for r in out["results"]]
    assert paths == ["A/Canonical", "A/Ranked2", "A/Ranked1", "A/Ranked0"]
    assert all("rerank_score" in r for r in out["results"][1:])


def test_unspliced_page_is_unaffected() -> None:
    """Regression guard for the ordinary path: no pin, pure reorder."""
    handler = _handler()
    results = [
        {"path": f"P{i}", "title": f"T{i}", "snippet": f"s{i}"} for i in range(5)
    ]
    payload = {
        "query": "history of the berlin wall",
        "results": results,
        "next_cursor": "o=5",
        "total": 50,
        "done": False,
        "page_info": {"offset": 0, "limit": 5, "returned_count": 5},
    }
    stub = _scoring_stub(lambda c: float(c["path"][-1]))
    with patch("openzim_mcp.ml.reranker.BGEReranker.get", return_value=stub):
        out = handler._maybe_rerank_compact(
            payload=payload, query=payload["query"], limit=5
        )

    assert [r["path"] for r in out["results"]] == ["P4", "P3", "P2", "P1", "P0"]


def test_rerank_never_caps_a_page_larger_than_the_caller_limit() -> None:
    """The invariant, stated directly: rerank reorders, it never cuts.

    Sizing the cut from ``limit`` only ever happened to be safe because
    ``len(candidates) == limit`` on the paths that existed at the time. The
    canonical splice broke that assumption and a row was silently deleted.
    Sizing it from the list actually handed over makes the invariant hold
    however the page was built, so the next thing that grows a page cannot
    reintroduce the same defect — ``page_info``/``next_cursor`` describe the
    whole page, so any row cut here becomes unreachable.
    """
    handler = _handler()
    results = [
        {"path": f"P{i}", "title": f"T{i}", "snippet": f"s{i}"} for i in range(5)
    ]
    payload = {
        "query": "history of the berlin wall",
        "results": results,
        "next_cursor": "o=5",
        "total": 50,
        "done": False,
        "page_info": {"offset": 0, "limit": 5, "returned_count": 5},
    }
    stub = _scoring_stub(lambda c: float(c["path"][-1]))
    with patch("openzim_mcp.ml.reranker.BGEReranker.get", return_value=stub):
        out = handler._maybe_rerank_compact(
            payload=payload, query=payload["query"], limit=3
        )

    assert len(out["results"]) == 5, (
        "rerank cut the page down to the caller's limit; page_info and "
        "next_cursor still describe all 5 rows, so the cut rows are lost"
    )
    assert [r["path"] for r in out["results"]] == ["P4", "P3", "P2", "P1", "P0"]


def test_page_of_only_a_canonical_row_skips_rerank_cleanly() -> None:
    """Nothing rerankable left after pinning must not crash or drop it."""
    handler = _handler()
    payload = {
        "query": "history of the canonical subject matter",
        "results": [
            {
                "path": "A/Canonical",
                "title": "Canonical",
                "snippet": CANONICAL_TITLE_MATCH_SNIPPET,
            }
        ],
        "page_info": {"offset": 0, "limit": 3, "returned_count": 1},
    }
    stub = _scoring_stub(lambda c: 1.0)
    with patch("openzim_mcp.ml.reranker.BGEReranker.get", return_value=stub):
        out = handler._maybe_rerank_compact(
            payload=payload, query=payload["query"], limit=3
        )

    assert [r["path"] for r in out["results"]] == ["A/Canonical"]
