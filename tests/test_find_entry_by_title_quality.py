"""Tests for find_entry_by_title fast-path and result-quality fixes.

Beta-test feedback:
- Lowercase queries (e.g. ``"evolution"``) miss the fast path even when an
  entry with title ``"Evolution"`` exists; the function falls into a
  suggestion search and returns the entry with a misleading ``score: 0.8``.
- Every suggestion-search result was hardcoded to ``score: 0.8`` regardless
  of how good the match is, so callers couldn't tell exact-title matches
  from approximate ones.

Tests run against the real wikipedia_en_climate_change_mini fixture so the
behaviour is validated end-to-end against libzim, not against a mock that
might paper over the bug.
"""

import json
from pathlib import Path
from typing import Dict, Optional

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations


@pytest.fixture
def ops_for_climate(
    real_content_zim_files: Dict[str, Optional[Path]],
) -> ZimOperations:
    """Build ZimOperations rooted at the climate-change ZIM (has a title index).

    Calls ``pytest.skip`` directly when the fixture isn't available so each
    test body can assume a non-None value (cleaner than threading
    ``Optional`` through every test and re-checking).
    """
    zim = real_content_zim_files.get("wikipedia_climate")
    if zim is None:
        pytest.skip("climate-change ZIM fixture not available")
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(zim.parent.parent)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=1000, snippet_length=100),
        logging=LoggingConfig(level="ERROR"),
    )
    return ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=100),
    )


@pytest.fixture
def climate_zim_path(real_content_zim_files: Dict[str, Optional[Path]]) -> Path:
    """Path to the climate-change ZIM fixture (skips when unavailable)."""
    p = real_content_zim_files.get("wikipedia_climate")
    if p is None:
        pytest.skip("climate-change ZIM fixture not available")
    return p


# Tolerance for float "equality" in score assertions. Score values are
# constructed from int ratios in (0, 1] so they're exact within a small
# multiple of the IEEE-754 epsilon; a tiny tolerance lets static analysis
# stop flagging ``score == 1.0``-style comparisons while keeping the test's
# intent unambiguous.
_SCORE_EPS = 1e-9


class TestFindEntryByTitleCaseInsensitiveFastPath:
    """The fast path must hit on case-insensitive title matches."""

    def test_lowercase_query_hits_fast_path(
        self,
        ops_for_climate: ZimOperations,
        climate_zim_path: Path,
    ):
        """A lowercased title must still resolve via the fast path."""
        out = json.loads(
            ops_for_climate.find_entry_by_title(str(climate_zim_path), "climate change")
        )
        assert out["fast_path_hit"] is True, out
        # Top result must be the canonical entry, scored 1.0.
        top = out["results"][0]
        assert top["title"].lower() == "climate change"
        assert abs(top["score"] - 1.0) < _SCORE_EPS

    def test_uppercase_query_hits_fast_path(
        self,
        ops_for_climate: ZimOperations,
        climate_zim_path: Path,
    ):
        """An uppercased title must also resolve via the fast path."""
        out = json.loads(
            ops_for_climate.find_entry_by_title(str(climate_zim_path), "CLIMATE CHANGE")
        )
        assert out["fast_path_hit"] is True, out
        assert abs(out["results"][0]["score"] - 1.0) < _SCORE_EPS


class TestFindEntryByTitleScoring:
    """Suggestion-search results must carry meaningful, distinct scores."""

    def test_suggestion_results_have_decreasing_scores(
        self,
        ops_for_climate: ZimOperations,
        climate_zim_path: Path,
    ):
        """Suggestion-search results must carry rank-derived scores.

        Reject the legacy bug where every result was stamped 0.8: scores
        must vary across the page and be monotonically non-increasing.
        """
        # 'climat' (truncated) forces a suggestion search rather than a fast
        # path hit; results are ranked by libzim's suggestion ordering.
        out = json.loads(
            ops_for_climate.find_entry_by_title(
                str(climate_zim_path), "climat", limit=10
            )
        )
        scores = [r["score"] for r in out["results"]]
        assert len(scores) >= 2, out
        # Reject the legacy "all hits scored 0.8" bug behaviour. Use a small
        # tolerance window so static analysis doesn't flag float equality.
        all_legacy = all(abs(s - 0.8) < _SCORE_EPS for s in scores)
        assert not all_legacy, f"all results received the legacy score 0.8: {scores}"
        # And the ordering should be non-increasing — first result is the
        # best match per libzim's suggestion rank.
        for prev, nxt in zip(scores, scores[1:]):
            assert prev >= nxt, f"scores not rank-monotonic: {scores}"

    def test_results_sorted_by_score_descending(
        self,
        ops_for_climate: ZimOperations,
        climate_zim_path: Path,
    ):
        """Results must come back sorted so the top item has the max score.

        Regression guard for the legacy bug where every result carried the
        same hardcoded ``0.8`` and the field was effectively decorative.
        """
        out = json.loads(
            ops_for_climate.find_entry_by_title(
                str(climate_zim_path), "climat", limit=10
            )
        )
        results = out["results"]
        if len(results) < 2:
            pytest.skip("test archive returned too few results to verify order")
        # Top result must hold (at least) the maximum score in the response.
        # Inequality form sidesteps float-equality complaints from analysers.
        top = results[0]["score"]
        assert all(top >= r["score"] for r in results)
