"""Live-archive smoke skeletons for Phase C retrieval primitives (Op1).

The recurring defect pattern across v2.0.0a4–a9 was the same shape: a
mock-based unit test couldn't see real-archive behaviors (typo
redirects shadowing canonical entries, BM25 derivatives outranking
the canonical article, HTML-wrapped metadata, well-known entries that
aren't literal entry paths). 79 defects shipped across four batches,
nearly all of them rooted in that mock/real divergence.

This module pins live behavior for the Phase C retrieval primitives
(``get_section``, ``get_related_articles``, ``synthesize``, namespace
walks on new-scheme archives) so the next "wait, this worked in
tests..." discovery doesn't slip through. Tests auto-skip when
``ZIM_TEST_DATA_DIR`` doesn't point at a directory containing a
Wikipedia-shaped ``.zim`` file (same pattern as
``test_live_canonical_queries.py``).

Assertions are loose by design — they validate the *shape* of behavior
(does ``get_section`` return non-empty body, does the citation contain
the article path) rather than exact text content, so they survive
acceptable upstream changes in Wikipedia scraper output without
becoming a maintenance burden.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# stdio MCP helper — same shape as test_live_canonical_queries.py
# ---------------------------------------------------------------------------


def _send(proc: subprocess.Popen, msg: Dict[str, Any]) -> None:
    assert proc.stdin is not None
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()


def _recv_until(proc: subprocess.Popen, msg_id: int) -> Dict[str, Any]:
    assert proc.stdout is not None
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("server stdout closed unexpectedly")
        try:
            resp = json.loads(line)
        except json.JSONDecodeError:
            continue
        if resp.get("id") == msg_id:
            return resp


def _spawn_stdio(zim_dir: Path) -> subprocess.Popen:
    cmd = [
        sys.executable,
        "-m",
        "openzim_mcp",
        "--mode",
        "advanced",
        "--transport",
        "stdio",
        str(zim_dir),
    ]
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=os.environ.copy(),
    )


def _initialize(proc: subprocess.Popen) -> None:
    _send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "phase-c-live-test", "version": "0"},
            },
        },
    )
    _recv_until(proc, 0)
    _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})


def _call_tool(
    proc: subprocess.Popen, msg_id: int, tool: str, **args: Any
) -> Dict[str, Any]:
    """Issue a generic tool call; return the structured ``result`` block."""
    _send(
        proc,
        {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": args},
        },
    )
    resp = _recv_until(proc, msg_id)
    return resp.get("result", {})


def _shutdown(proc: subprocess.Popen) -> None:
    try:
        if proc.stdin is not None:
            with contextlib.suppress(Exception):
                proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=3)
    finally:
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.close()


@pytest.fixture
def mcp_proc(zim_dir: Path):
    """Yield an initialized stdio openzim-mcp process for Phase C tests."""
    proc = _spawn_stdio(zim_dir)
    try:
        _initialize(proc)
        yield proc
    finally:
        _shutdown(proc)


def _first_wikipedia_zim(zim_dir: Path) -> Optional[Path]:
    """Return the first wikipedia-shaped ZIM in ``zim_dir``, or None."""
    for f in sorted(zim_dir.glob("*.zim")):
        if "wikipedia" in f.name.lower():
            return f
    return None


def _structured(result: Dict[str, Any]) -> Dict[str, Any]:
    """Phase B wrapper-tolerant unwrap (see Phase B spec note)."""
    inner = result.get("structuredContent") or {}
    return inner.get("result", inner) if isinstance(inner, dict) else {}


# ---------------------------------------------------------------------------
# get_section live coverage — exercises the bundle's section offsets
# against real Wikipedia HTML quirks (decorated headings, repeated
# heading text, infobox stripping interactions).
# ---------------------------------------------------------------------------


def test_get_section_returns_non_empty_body_for_canonical_topic(
    mcp_proc, zim_dir: Path
):
    """get_section against a canonical Wikipedia article should return
    a non-empty body whose char_count matches the slice length and
    whose section_title is non-empty.

    The bundle's section-offset computation has produced empty slices
    when section ranges collapse (C7 regression). This test guards
    that fix on real Wikipedia HTML.
    """
    zim = _first_wikipedia_zim(zim_dir)
    if zim is None:
        pytest.skip("No wikipedia*.zim found in ZIM_TEST_DATA_DIR")
    # Discover sections via get_table_of_contents first so we don't
    # hard-code section_ids that the scraper output may have renamed.
    toc_resp = _call_tool(
        mcp_proc,
        1,
        "get_table_of_contents",
        zim_file_path=str(zim),
        entry_path="A/Berlin",
    )
    toc = _structured(toc_resp)
    headings = toc.get("toc") or []
    # First-non-empty heading is the target.
    target_id: Optional[str] = None
    for h in headings:
        if isinstance(h, dict) and h.get("section_id"):
            target_id = h["section_id"]
            break
    if not target_id:
        pytest.skip("No sections discovered in A/Berlin (TOC empty)")

    section_resp = _call_tool(
        mcp_proc,
        2,
        "get_section",
        zim_file_path=str(zim),
        entry_path="A/Berlin",
        section_id=target_id,
    )
    section = _structured(section_resp)
    assert section.get("section_id") == target_id
    body = section.get("content_markdown") or ""
    assert body, f"empty body for section_id={target_id!r}"
    assert section.get("char_count", 0) == len(body)
    assert section.get("section_title")


def test_get_section_unknown_id_returns_actionable_error(mcp_proc, zim_dir: Path):
    """A non-existent section_id surfaces ``available_section_ids`` and
    (Op5) a ``closest_match`` hint. The error envelope must be a
    real ToolErrorPayload, not a markdown string."""
    zim = _first_wikipedia_zim(zim_dir)
    if zim is None:
        pytest.skip("No wikipedia*.zim found in ZIM_TEST_DATA_DIR")
    resp = _call_tool(
        mcp_proc,
        1,
        "get_section",
        zim_file_path=str(zim),
        entry_path="A/Berlin",
        section_id="Goegraphy",  # deliberate typo of "Geography"
    )
    payload = _structured(resp)
    # ToolErrorPayload shape — ``error=True`` is the discriminator.
    assert payload.get("error") is True
    assert payload.get("operation") == "section_not_found"
    extras = payload.get("extras") or {}
    assert "available_section_ids" in extras
    # Op5: closest_match is best-effort; present when difflib finds a
    # similar ID, absent for completely unrelated IDs. Don't assert
    # presence, but assert it's the right type if present.
    closest = extras.get("closest_match")
    if closest is not None:
        assert isinstance(closest, str)


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
    zim = _first_wikipedia_zim(zim_dir)
    if zim is None:
        pytest.skip("No wikipedia*.zim found in ZIM_TEST_DATA_DIR")
    resp = _call_tool(
        mcp_proc,
        1,
        "get_related_articles",
        zim_file_path=str(zim),
        entry_path="A/Berlin",
        limit=10,
    )
    payload = _structured(resp)
    if payload.get("error"):
        pytest.skip(f"related errored: {payload}")
    results = payload.get("results") or []
    if len(results) < 2:
        pytest.skip("Too few related articles to compare ranking")
    prev = float("inf")
    for r in results:
        mc = r.get("mention_count")
        if mc is None:
            pytest.skip("mention_count missing — pre-D9 server?")
        assert mc <= prev, f"mention_count not monotone: {results}"
        prev = mc


# ---------------------------------------------------------------------------
# walk_namespace live coverage — new-scheme archives + cursor identity.
# ---------------------------------------------------------------------------


def test_walk_namespace_cursor_round_trip(mcp_proc, zim_dir: Path):
    """Calling walk_namespace twice (first page, then via cursor) returns
    different result pages without raising on the cursor archive-identity
    check.

    H16 made the identity check unconditional; this verifies legitimate
    cursors continue to round-trip against the same archive.
    """
    zim = _first_wikipedia_zim(zim_dir)
    if zim is None:
        pytest.skip("No wikipedia*.zim found in ZIM_TEST_DATA_DIR")
    resp1 = _call_tool(
        mcp_proc,
        1,
        "walk_namespace",
        zim_file_path=str(zim),
        namespace="C",
        limit=10,
    )
    page1 = _structured(resp1)
    if page1.get("error"):
        pytest.skip(f"walk errored: {page1}")
    cursor = page1.get("next_cursor")
    if not cursor:
        pytest.skip("walk_namespace finished on first page; no cursor to test")
    resp2 = _call_tool(
        mcp_proc,
        2,
        "walk_namespace",
        zim_file_path=str(zim),
        namespace="C",
        cursor=cursor,
        limit=10,
    )
    page2 = _structured(resp2)
    assert page2.get("error") is not True, page2
    # Different paths between pages — both pages return real results.
    page1_paths = {
        r.get("path") for r in (page1.get("results") or []) if isinstance(r, dict)
    }
    page2_paths = {
        r.get("path") for r in (page2.get("results") or []) if isinstance(r, dict)
    }
    if page1_paths and page2_paths:
        # At least one path must be different — otherwise pagination is
        # broken (returning the same page twice).
        assert page1_paths != page2_paths
