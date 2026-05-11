"""Tests for the v2.0.0a7 expansion of ``_typo_variants``.

Phase A #14 named ``"Photosythesis" → "Photosynthesis"`` as the explicit
regression target. v2.0.0a4 shipped only transposition + deletion edits,
which mathematically cannot reach the target (the missing 'n' requires
INSERTION). v2.0.0a7 adds insertion + substitution against the full a-z
alphabet so all four single-edit cases are reachable.
"""

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
