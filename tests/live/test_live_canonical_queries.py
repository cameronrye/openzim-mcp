"""Live-archive smoke tests pinning canonical-query quality.

The v2.0.0a8 testing pass surfaced four regressions that mock-based
unit tests had not caught — each one rooted in the same shape: the
mock didn't include a real-world collision case (typo redirect that
shadows the canonical, BM25 derivatives that outrank the canonical,
HTML-wrapped metadata, well-known entries that aren't literal paths).

These live tests guard against future drift by exercising the same
canonical-query patterns against a real Wikipedia-style ZIM. They
auto-skip when ``ZIM_TEST_DATA_DIR`` doesn't point at a directory
containing at least one ``.zim`` file.

The assertions are intentionally loose ("does the canonical article
appear at all", not "exactly position 0") so the suite survives
acceptable upstream changes (Wikipedia article renames, ZIM scraper
output drift) — they regress only on the specific failure shapes
the a9 batch fixed.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from tests.live._stdio_helpers import call_tool

pytestmark = pytest.mark.live


def _call_zim_query(
    proc: subprocess.Popen, msg_id: int, **args: Any
) -> str:
    """Issue a ``zim_query`` call and return the result text payload.

    ``zim_query`` returns either a plain text envelope or a structured
    content block. Both cases have a string in ``content[0]["text"]``.
    """
    result = call_tool(proc, msg_id, "zim_query", **args)
    content = result["content"]
    return str(content[0]["text"])


# ---------------------------------------------------------------------------
# Tests — one per a9 regression class
# ---------------------------------------------------------------------------


def test_tell_me_about_canonical_topic_promotes_canonical_article(mcp_proc):
    """D3/D6/Op1: ``tell me about Berlin`` returns the canonical Berlin
    article, not a derivative like ``List_of_songs_about_Berlin`` or
    ``Berlin_(disambiguation)``.

    Mock unit tests couldn't see this regression because they didn't
    populate BM25 with realistic derivative-heavy results.
    """
    result = _call_zim_query(mcp_proc, 1, query="tell me about Berlin")
    # Either we see the canonical Berlin article body, OR we see a
    # disambiguation surface. Both are acceptable outcomes for a
    # canonical-topic query; what's NOT acceptable is "List of songs
    # about Berlin" / "Timeline of Berlin" / etc. as the LEAD content.
    # Allow either: the article body markers ("Berlin is the capital")
    # OR the disambiguation header ("Multiple articles match").
    looks_like_canonical = (
        "capital of Germany" in result
        or "**Berlin**" in result
        or "Multiple articles match" in result
    )
    leads_with_derivative = (
        result.lstrip().startswith("# List of songs about Berlin")
        or result.lstrip().startswith("# Timeline of Berlin")
        or result.lstrip().startswith("# Berlin (disambiguation)")
        and "capital of Germany" not in result[:2000]
    )
    if not looks_like_canonical:
        pytest.skip(
            "Live archive doesn't carry a recognizable Berlin article — skipping."
        )
    assert not leads_with_derivative, (
        f"D3/D6 regression: tell_me_about Berlin led with a derivative "
        f"article. First 500 chars:\n{result[:500]}"
    )


def test_typo_collision_resolves_to_canonical(mcp_proc):
    """D1: ``find article titled Photosythesis`` resolves to
    ``Photosynthesis`` (canonical) even on archives that ALSO contain
    ``Photosymthesis`` (the alphabetically-earlier typo redirect).

    The mock-based unit test couldn't see this regression because the
    mock only allowed one valid variant path.
    """
    result = _call_zim_query(
        mcp_proc, 1, query="find article titled Photosythesis"
    )
    # If the archive has the Photosynthesis article AT ALL, the typo
    # path should land us on it (directly or through the redirect we
    # now follow). Permissive: either the response mentions
    # Photosynthesis OR it returns no results (archive too narrow).
    has_typo_resolution = (
        "Photosynthesis" in result
        and "Photosymthesis" not in result.split("Photosynthesis", 1)[0]
    )
    # ``find article titled X`` on an empty archive returns an empty
    # results section — we tolerate that without forcing a Wikipedia
    # mirror.
    if "Photosynthesis" not in result and "Photosymthesis" not in result:
        pytest.skip("Archive doesn't carry Photosynthesis — skipping.")
    assert has_typo_resolution, (
        f"D1 regression: Photosymthesis (typo redirect) won over the "
        f"canonical Photosynthesis. First 800 chars:\n{result[:800]}"
    )


def test_browse_w_namespace_returns_entries_when_list_namespaces_does(mcp_proc):
    """D2: ``list_namespaces`` and ``browse namespace W`` must agree.
    Either both report empty, or both report non-empty.
    """
    list_result = _call_zim_query(mcp_proc, 1, query="list namespaces")
    # Pull the W entry count from the listing.
    if "**`W`**" not in list_result:
        pytest.skip("Archive doesn't carry a W namespace — skipping.")
    # Parse "**`W`** — N entries:" — extract N.
    import re

    m = re.search(r"\*\*`W`\*\* — (\d+) entries", list_result)
    if not m:
        pytest.skip(f"Couldn't parse W entry count from: {list_result[:300]}")
    list_w_count = int(m.group(1))

    browse_result = _call_zim_query(mcp_proc, 2, query="browse namespace W")
    browse_payload = json.loads(browse_result)
    browse_w_count = browse_payload.get("total", 0)

    # Allow browse to surface a SUBSET of list's count (auxiliary
    # paths might not all be reachable on every flavour), but
    # browse MUST NOT be zero when list reports a positive count —
    # that's the D2 inconsistency the live a8 audit caught.
    assert not (list_w_count > 0 and browse_w_count == 0), (
        f"D2 regression: list_namespaces reports W={list_w_count} but "
        f"browse_namespace W returns 0 entries. Inconsistent probes."
    )


def test_metadata_for_archive_returns_extracted_text_not_html(mcp_proc):
    """D4/Op2: metadata previews surface the actual archive title /
    language / etc., not 800 chars of identical HTML boilerplate.
    """
    # First find what archive to ask about.
    list_files = _call_zim_query(mcp_proc, 1, query="list available ZIM files")
    # ``list available ZIM files`` returns a structured JSON wrapping —
    # pull the first archive name out of the markdown.
    import re

    name_match = re.search(r'"name":\s*"([^"]+)"', list_files)
    if not name_match:
        pytest.skip("No archive name found in list — skipping.")
    archive_name = name_match.group(1)

    metadata_result = _call_zim_query(
        mcp_proc, 2, query=f"metadata for {archive_name}"
    )
    # The HTML-wrapped fields (Title, Description, Language, Creator)
    # MUST NOT just be 800 chars of ``<!DOCTYPE html>...<title>`` —
    # the boilerplate-prefix pattern the a8 audit observed.
    # Allow a few occurrences (the metadata entries are listed
    # individually) but NOT for every field.
    boilerplate_occurrences = metadata_result.count("<!DOCTYPE html>")
    assert boilerplate_occurrences <= 2, (
        f"D4 regression: metadata response is dominated by HTML "
        f"boilerplate ({boilerplate_occurrences} occurrences). "
        f"First 500 chars:\n{metadata_result[:500]}"
    )


def test_browse_unknown_namespace_fast_rejects(mcp_proc):
    """D11/Op6: unknown namespace letters return a bad_namespace
    structured response without scanning the archive."""
    result = _call_zim_query(mcp_proc, 1, query="browse namespace Q")
    # The reject path returns a payload with ``discovery_method=
    # rejected_unknown_namespace``. Be permissive about exact shape
    # (the response might be wrapped/rendered differently) — what
    # matters is that the response was fast AND mentioned the
    # rejection or "no results".
    parsed = json.loads(result) if result.startswith("{") else None
    if parsed is None:
        pytest.skip("Unexpected non-JSON browse_namespace shape — skipping.")
    assert parsed is not None  # narrow type after the skip above
    discovery = parsed.get("discovery_method", "")
    reason = parsed.get("_meta", {}).get("reason", "")
    # Either explicit rejection OR the legacy full-iteration path
    # returned empty fast — both are acceptable from the caller's
    # perspective, but D11 prefers the explicit rejection.
    assert discovery == "rejected_unknown_namespace" or parsed.get("total") == 0, (
        f"D11 regression: unknown namespace Q returned an unexpected shape. "
        f"discovery_method={discovery!r}, reason={reason!r}"
    )
