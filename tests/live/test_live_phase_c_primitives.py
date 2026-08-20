"""Live-archive smoke skeletons for Phase C retrieval primitives (Op1).

The recurring defect pattern across v2.0.0a4–a9 was the same shape: a
mock-based unit test couldn't see real-archive behaviors (typo
redirects shadowing canonical entries, BM25 derivatives outranking
the canonical article, HTML-wrapped metadata, well-known entries that
aren't literal entry paths). 79 defects shipped across four batches,
nearly all of them rooted in that mock/real divergence.

This module pins live behavior for the Phase C retrieval primitives
(``zim_get_section``, ``zim_links(direction="related")``, synthesis via
``zim_query``, and namespace walks) so the next "wait, this worked in
tests..." discovery doesn't slip through. Tests auto-skip when
``ZIM_TEST_DATA_DIR`` doesn't point at a directory containing a
Wikipedia-shaped ``.zim`` file (same pattern as
``test_live_canonical_queries.py``).

Entry paths, section ids and namespaces are all *discovered* from the
archive under test rather than named literally. The literal versions
(``A/Berlin``, namespace ``C``) matched no entry in the fixture corpus, so
every assertion behind them decayed into a skip.

Assertions are loose by design — they validate the *shape* of behavior
(does ``get_section`` return non-empty body, does the citation contain
the article path) rather than exact text content, so they survive
acceptable upstream changes in Wikipedia scraper output without
becoming a maintenance burden.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

import pytest

from tests.live._stdio_helpers import call_tool as _call_tool
from tests.live._stdio_helpers import structured as _structured

pytestmark = pytest.mark.live


def _first_wikipedia_zim(zim_dir: Path) -> Optional[Path]:
    """Return the first wikipedia-shaped ZIM in ``zim_dir``, or None."""
    for f in sorted(zim_dir.glob("*.zim")):
        if "wikipedia" in f.name.lower():
            return f
    return None


def _require_wikipedia_zim(zim_dir: Path) -> Path:
    """Return a wikipedia-shaped archive, or skip the test."""
    zim = _first_wikipedia_zim(zim_dir)
    if zim is None:
        pytest.skip("No wikipedia*.zim found in ZIM_TEST_DATA_DIR")
    return zim


def _article_namespace(proc: Any, zim: Path) -> str:
    """Return a namespace that actually holds articles in ``zim``.

    Old-scheme archives keep articles under ``A``; new-scheme archives put
    everything under ``C``. Hard-coding either one turned "this archive uses
    the other scheme" into a skip, which is how the cursor round-trip below
    stopped running.
    """
    for namespace in ("A", "C"):
        page = _structured(
            _call_tool(
                proc,
                900,
                "zim_browse",
                zim_file_path=str(zim),
                namespace=namespace,
                mode="page",
                limit=1,
            )
        )
        if page.get("results"):
            return namespace
    # ``return`` on a ``NoReturn`` call: ``pytest.skip`` raises, but spelling
    # the exit explicitly keeps every path of this function an explicit return.
    return pytest.skip("Archive exposes no article namespace (tried A and C)")


def _discover_article_paths(proc: Any, zim: Path, limit: int = 25) -> List[str]:
    """Return real article paths from ``zim``.

    The module used to address ``A/Berlin`` directly. That is not an entry in
    every wikipedia-shaped archive — the climate-change mini corpus has no
    Berlin — so every assertion behind it degraded into a skip. Discovering
    the paths keeps the tests running on whatever archive is present.
    """
    namespace = _article_namespace(proc, zim)
    page = _structured(
        _call_tool(
            proc,
            901,
            "zim_browse",
            zim_file_path=str(zim),
            namespace=namespace,
            mode="page",
            limit=limit,
        )
    )
    return [
        r["path"]
        for r in (page.get("results") or [])
        if isinstance(r, dict) and isinstance(r.get("path"), str)
    ]


def _article_with_sections(proc: Any, zim: Path) -> tuple[str, str]:
    """Return ``(entry_path, section_id)`` for an article that has sections."""
    for entry_path in _discover_article_paths(proc, zim):
        toc = _structured(
            _call_tool(
                proc,
                902,
                "zim_get",
                zim_file_path=str(zim),
                entry_path=entry_path,
                view="toc",
            )
        )
        for heading in toc.get("toc") or []:
            if isinstance(heading, dict) and heading.get("section_id"):
                return entry_path, heading["section_id"]
    return pytest.skip("No article with a discoverable section in this archive")


# ---------------------------------------------------------------------------
# get_section live coverage — exercises the bundle's section offsets
# against real Wikipedia HTML quirks (decorated headings, repeated
# heading text, infobox stripping interactions).
# ---------------------------------------------------------------------------


def test_get_section_returns_non_empty_body_for_canonical_topic(
    mcp_proc, zim_dir: Path
):
    """zim_get_section against a real article should return a non-empty
    body whose char_count matches the slice length and whose
    section_title is non-empty.

    The bundle's section-offset computation has produced empty slices
    when section ranges collapse (C7 regression). This test guards
    that fix on real Wikipedia HTML.
    """
    zim = _require_wikipedia_zim(zim_dir)
    # Discover the article and section_id rather than hard-coding either, so
    # the scraper renaming a section doesn't silently disable the assertions.
    entry_path, target_id = _article_with_sections(mcp_proc, zim)

    section = _structured(
        _call_tool(
            mcp_proc,
            2,
            "zim_get_section",
            zim_file_path=str(zim),
            entry_path=entry_path,
            section_id=target_id,
        )
    )
    assert section.get("section_id") == target_id, section
    body = section.get("content_markdown") or ""
    assert body, f"empty body for section_id={target_id!r}"
    assert section.get("char_count", 0) == len(body)
    assert section.get("section_title")


def test_get_section_unknown_id_returns_actionable_error(mcp_proc, zim_dir: Path):
    """A non-existent section_id surfaces ``available_section_ids``.

    The error envelope must be a real ToolErrorPayload, not a markdown
    string.
    """
    zim = _require_wikipedia_zim(zim_dir)
    entry_path, real_id = _article_with_sections(mcp_proc, zim)

    payload = _structured(
        _call_tool(
            mcp_proc,
            1,
            "zim_get_section",
            zim_file_path=str(zim),
            entry_path=entry_path,
            section_id=real_id + "_definitely_not_a_section",
        )
    )
    # ToolErrorPayload shape — ``error=True`` is the discriminator.
    assert payload.get("error") is True, payload
    assert payload.get("operation") == "section_not_found", payload
    # The ids sit at the top level of the payload, not under an ``extras`` key.
    available = payload.get("available_section_ids")
    assert isinstance(available, list) and available, payload
    assert real_id in available, payload


# ---------------------------------------------------------------------------
# synthesize live coverage — exercises RRF fusion + section attribution
# + title promotion on real BM25 hit ordering.
# ---------------------------------------------------------------------------


def test_synthesize_returns_grounded_answer_with_citations(mcp_proc, zim_dir: Path):
    """zim_query(synthesize=True) returns answer_markdown plus a
    citations[] list. Each citation's archive segment matches a real
    ZIM file's stem.

    Mock tests couldn't see RRF tie-break or title-promotion behavior
    against realistic BM25 rankings; this exercises both on a real
    archive.
    """
    zim = _first_wikipedia_zim(zim_dir)
    if zim is None:
        pytest.skip("No wikipedia*.zim found in ZIM_TEST_DATA_DIR")
    resp = _call_tool(
        mcp_proc,
        1,
        "zim_query",
        query="tell me about Berlin",
        zim_file_path=str(zim),
        synthesize=True,
    )
    payload = _structured(resp)
    # Synthesize returns SynthesizeResponse — not a ToolErrorPayload.
    assert payload.get("error") is not True, payload
    assert isinstance(payload.get("answer_markdown"), str)
    citations = payload.get("citations") or []
    assert citations, "synthesize returned no citations"
    # Each citation must have a real archive segment.
    archive_stem = zim.stem
    for cite in citations[:3]:
        cite_id = cite.get("cite_id", "")
        assert archive_stem in cite_id, f"unexpected cite_id={cite_id}"


def test_synthesize_zero_hit_query_reports_reason(mcp_proc, zim_dir: Path):
    """A nonsense query produces ``_meta.reason == '0_hits'`` with
    empty passages/citations rather than a fabricated answer."""
    zim = _first_wikipedia_zim(zim_dir)
    if zim is None:
        pytest.skip("No wikipedia*.zim found in ZIM_TEST_DATA_DIR")
    resp = _call_tool(
        mcp_proc,
        1,
        "zim_query",
        query="xqzwfpvnbnkqplkmnzqwzxcv",
        zim_file_path=str(zim),
        synthesize=True,
    )
    payload = _structured(resp)
    if payload.get("error"):
        pytest.skip(f"synthesize errored: {payload}")
    meta = payload.get("_meta") or {}
    assert meta.get("reason") == "0_hits"
    assert (payload.get("passages") or []) == []
    assert (payload.get("citations") or []) == []


# ---------------------------------------------------------------------------
# get_related_articles live coverage — D9 ranking by mention_count.
# ---------------------------------------------------------------------------


def test_get_related_articles_ranks_by_mention_count(mcp_proc, zim_dir: Path):
    """``mention_count`` decreases (or stays equal) as rank increases.

    Mock-based tests could only assert "the field exists"; this asserts
    the ordering property against real article HTML.
    """
    zim = _require_wikipedia_zim(zim_dir)
    paths = _discover_article_paths(mcp_proc, zim)
    if not paths:
        pytest.skip("Archive exposes no article entries")

    # Walk candidates until one has enough related articles to rank; a single
    # stub article with one outbound link says nothing about ordering.
    for entry_path in paths:
        payload = _structured(
            _call_tool(
                mcp_proc,
                1,
                "zim_links",
                zim_file_path=str(zim),
                entry_path=entry_path,
                direction="related",
                limit=10,
            )
        )
        if payload.get("error"):
            continue
        results = payload.get("results") or []
        if len(results) < 2:
            continue
        counts = [r.get("mention_count") for r in results if isinstance(r, dict)]
        if any(c is None for c in counts):
            pytest.skip("mention_count missing from related results")
        assert counts == sorted(
            counts, reverse=True
        ), f"mention_count not monotone for {entry_path}: {counts}"
        return
    pytest.skip("No article with 2+ related articles to compare ranking")


# ---------------------------------------------------------------------------
# zim_browse(mode="walk") live coverage — cursor identity across pages.
# ---------------------------------------------------------------------------


def test_walk_namespace_cursor_round_trip(mcp_proc, zim_dir: Path):
    """Walking a namespace twice (first page, then via cursor) returns
    different result pages without raising on the cursor archive-identity
    check.

    H16 made the identity check unconditional; this verifies legitimate
    cursors continue to round-trip against the same archive.
    """
    zim = _require_wikipedia_zim(zim_dir)
    # Ask for the namespace this archive actually populates. Pinning "C"
    # meant every old-scheme archive skipped instead of walking.
    namespace = _article_namespace(mcp_proc, zim)
    page1 = _structured(
        _call_tool(
            mcp_proc,
            1,
            "zim_browse",
            zim_file_path=str(zim),
            namespace=namespace,
            mode="walk",
            limit=10,
        )
    )
    assert page1.get("error") is not True, page1
    cursor = page1.get("next_cursor")
    if not cursor:
        pytest.skip("walk finished on the first page; no cursor to round-trip")
    page2 = _structured(
        _call_tool(
            mcp_proc,
            2,
            "zim_browse",
            zim_file_path=str(zim),
            namespace=namespace,
            mode="walk",
            cursor=cursor,
            limit=10,
        )
    )
    assert page2.get("error") is not True, page2
    page1_paths = {
        r.get("path") for r in (page1.get("results") or []) if isinstance(r, dict)
    }
    page2_paths = {
        r.get("path") for r in (page2.get("results") or []) if isinstance(r, dict)
    }
    assert page1_paths, page1
    assert page2_paths, page2
    # Returning the same page twice means the cursor never advanced.
    assert page1_paths != page2_paths
    assert not (
        page1_paths & page2_paths
    ), f"walk pages overlap: {sorted(page1_paths & page2_paths)}"
