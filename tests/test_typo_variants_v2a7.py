"""Tests for the v2.0.0a7 expansion of ``_typo_variants``.

Phase A #14 named ``"Photosythesis" → "Photosynthesis"`` as the explicit
regression target. v2.0.0a4 shipped only transposition + deletion edits,
which mathematically cannot reach the target (the missing 'n' requires
INSERTION). v2.0.0a7 adds insertion + substitution against the full a-z
alphabet so all four single-edit cases are reachable.
"""

import time
from contextlib import contextmanager
from unittest.mock import MagicMock

from openzim_mcp.zim.search import _SearchMixin


def test_insertion_reaches_phase_a_named_target():
    """Photosythesis → Photosynthesis (missing 'n', insertion edit)."""
    variants = _SearchMixin._typo_variants("Photosythesis")
    assert "Photosynthesis" in variants


def test_insertion_handles_deletion_typo_in_long_word():
    """Photosynthsis → Photosynthesis (missing 'e', insertion edit)."""
    variants = _SearchMixin._typo_variants("Photosynthsis")
    assert "Photosynthesis" in variants


def test_substitution_handles_wrong_key():
    """Wikipidia → Wikipedia (i → e at position 5, substitution)."""
    variants = _SearchMixin._typo_variants("Wikipidia")
    assert "Wikipedia" in variants


def test_transposition_still_works():
    """Einstien → Einstein (transposition; pre-existing behavior)."""
    variants = _SearchMixin._typo_variants("Einstien")
    assert "Einstein" in variants


def test_deletion_still_works():
    """Pythoon → Python (extra 'o' removed; deletion edit)."""
    variants = _SearchMixin._typo_variants("Pythoon")
    assert "Python" in variants


def test_short_query_skips_expensive_edits():
    """4-char inputs skip insertion/substitution to keep cost bounded.

    Transposition (cheap, n-1 variants) is still applied; insertion and
    substitution (26n each) are gated to ``len >= 5`` so short queries
    like ``"DNA "`` don't blow up the variant count.
    """
    # 4-char input
    variants = _SearchMixin._typo_variants("Test")
    # Transposition: "etst", "Tset", "Tets" (some equal to original or
    # skipped due to no-op rule).
    # Insertion/substitution must not run → variant count stays modest.
    assert len(variants) < 30, (
        f"Short query produced {len(variants)} variants — gate broken"
    )


def test_variant_count_bounded():
    """Long query stays within the documented ~700-variant budget."""
    variants = _SearchMixin._typo_variants("Photosythesis")
    # 13 chars: transposition (~12) + deletion (~13) + insertion
    # (26 × 14 = 364) + substitution (~26 × 13 = 338) - dedupe = ~700.
    # Cap-check at 800 leaves headroom for de-dup variations.
    assert len(variants) < 800


def test_variants_deduplicated():
    """``set(variants) == variants`` after generation — no duplicates."""
    variants = _SearchMixin._typo_variants("Photosythesis")
    assert len(set(variants)) == len(variants)


def test_original_input_not_in_variants():
    """The input itself is never emitted as a variant."""
    title = "Photosythesis"
    variants = _SearchMixin._typo_variants(title)
    assert title not in variants


def test_typo_variants_runs_in_reasonable_time():
    """700-variant generation finishes in well under 100ms on commodity
    hardware. Guards against accidental quadratic regressions in the
    insertion / substitution loops."""
    start = time.perf_counter()
    for _ in range(10):
        _SearchMixin._typo_variants("Photosynthesis")
    elapsed_ms = (time.perf_counter() - start) * 1000
    # 10 iterations on a ~14-char input. 100ms total = 10ms per call.
    # The earlier transposition-only path ran in <1ms; bumping the
    # budget to 100ms for full alphabet edits leaves ample headroom.
    assert elapsed_ms < 100, f"_typo_variants too slow: {elapsed_ms:.0f}ms / 10 calls"


# ---------------------------------------------------------------------------
# End-to-end: insertion-variant typo fallback through find_entry_by_title_data
# ---------------------------------------------------------------------------


@contextmanager
def _ctx(value):
    """Mimic ``zim_archive`` context-manager shape for monkeypatching."""
    yield value


def test_photosythesis_resolves_to_photosynthesis_via_typo_fallback(
    test_config, monkeypatch
):
    """Full-stack test of the named Phase A #14 regression target.

    Wires a mock archive whose ``has_entry_by_path`` returns True only for
    ``C/Photosynthesis`` and ``A/Photosynthesis`` — i.e. the canonical
    entry — and ``get_entry_by_path`` returns a matching entry. The
    suggestion searcher returns nothing (mirroring the live behaviour
    we measured against the real Wikipedia archive).

    The expected flow:
      1. fast path probes ``C/Photosythesis`` (etc.) → miss
      2. ``SuggestionSearcher`` returns nothing → miss
      3. ``_find_entry_typo_fallback`` generates ~700 variants
      4. Among them is ``Photosynthesis`` (single-character insertion of 'n')
      5. ``_find_entry_fast_path(archive, "Photosynthesis")`` hits
         ``C/Photosynthesis`` → fuzzy_path_hit = True
      6. The response surfaces the canonical entry with the
         ``typo_corrected`` match_type and the alt-spelling suggestion.
    """
    from openzim_mcp.server import OpenZimMcpServer

    server = OpenZimMcpServer(test_config)

    mock_archive = MagicMock()
    valid_paths = {"C/Photosynthesis", "A/Photosynthesis"}
    mock_archive.has_entry_by_path.side_effect = lambda p: p in valid_paths
    mock_entry = MagicMock()
    mock_entry.path = "C/Photosynthesis"
    mock_entry.title = "Photosynthesis"
    mock_archive.get_entry_by_path.return_value = mock_entry

    mock_suggest = MagicMock()
    mock_suggest.getEstimatedMatches.return_value = 0
    mock_suggest.getResults.return_value = []
    mock_searcher = MagicMock()
    mock_searcher.suggest.return_value = mock_suggest

    monkeypatch.setattr(
        "openzim_mcp.zim_operations.SuggestionSearcher",
        lambda archive: mock_searcher,
    )
    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive",
        lambda *a, **kw: _ctx(mock_archive),
    )
    # Bypass path-validator (the test uses a fake test zim path).
    monkeypatch.setattr(
        server.zim_operations.path_validator,
        "validate_path",
        lambda p: __import__("pathlib").Path(p),
    )
    monkeypatch.setattr(
        server.zim_operations.path_validator,
        "validate_zim_file",
        lambda p: p,
    )

    result = server.zim_operations.find_entry_by_title_data(
        "/fake/test.zim", "Photosythesis", cross_file=False, limit=10
    )

    # The whole point: the named-target typo MUST resolve.
    assert (
        result["fuzzy_path_hit"] is True
    ), "Photosythesis → Photosynthesis must resolve via the insertion-variant typo fallback"
    assert len(result["results"]) >= 1
    hit = result["results"][0]
    assert hit["path"] == "C/Photosynthesis"
    assert hit["title"] == "Photosynthesis"
    assert hit.get("match_type") == "typo_corrected"
    # The applied correction surfaces as an alt_spelling suggestion so a
    # caller can verify what auto-correct decision was made.
    meta = result.get("_meta", {})
    suggestions = meta.get("suggestions") or []
    assert any(
        s.get("type") == "alt_spelling" and "Photosynthesis" in s.get("value", "")
        for s in suggestions
    ), f"Expected alt_spelling=Photosynthesis in suggestions, got {suggestions!r}"


def test_photosynthsis_deletion_also_resolves(test_config, monkeypatch):
    """``Photosynthsis`` (missing 'e' — a deletion typo) should also
    reach ``Photosynthesis`` via the insertion edit."""
    from openzim_mcp.server import OpenZimMcpServer

    server = OpenZimMcpServer(test_config)

    mock_archive = MagicMock()
    valid_paths = {"C/Photosynthesis"}
    mock_archive.has_entry_by_path.side_effect = lambda p: p in valid_paths
    mock_entry = MagicMock()
    mock_entry.path = "C/Photosynthesis"
    mock_entry.title = "Photosynthesis"
    mock_archive.get_entry_by_path.return_value = mock_entry

    mock_suggest = MagicMock()
    mock_suggest.getEstimatedMatches.return_value = 0
    mock_suggest.getResults.return_value = []
    mock_searcher = MagicMock()
    mock_searcher.suggest.return_value = mock_suggest

    monkeypatch.setattr(
        "openzim_mcp.zim_operations.SuggestionSearcher",
        lambda archive: mock_searcher,
    )
    monkeypatch.setattr(
        "openzim_mcp.zim_operations.zim_archive",
        lambda *a, **kw: _ctx(mock_archive),
    )
    monkeypatch.setattr(
        server.zim_operations.path_validator,
        "validate_path",
        lambda p: __import__("pathlib").Path(p),
    )
    monkeypatch.setattr(
        server.zim_operations.path_validator,
        "validate_zim_file",
        lambda p: p,
    )

    result = server.zim_operations.find_entry_by_title_data(
        "/fake/test.zim", "Photosynthsis", cross_file=False, limit=10
    )
    assert result["fuzzy_path_hit"] is True
    assert result["results"][0]["path"] == "C/Photosynthesis"
