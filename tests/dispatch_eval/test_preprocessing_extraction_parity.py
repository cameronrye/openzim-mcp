"""Gate 0a — preprocessing orchestration idempotency test.

NOT a parity-vs-new-module test (the helpers are NOT relocated in rc0 — they already
live at module level in ``intent_parser.py`` and ``title_promotion.py``). This test
guards against accidental reordering of the inline chain in ``simple_tools.py``
during the v2 Phase F refactor: a second pass through the canonical Tier 1 chain
must yield byte-identical output for every b1→b13 probe.

Tier 1 chain replayed (matches ``IntentParser._apply_tier1_rewrites`` at
``intent_parser.py:991-992``):

  1. ``IntentParser._apply_misspelling_map``
  2. ``IntentParser._detect_stopword_phrase``

Both classmethods require a ``title_probe`` keyword argument. We pass ``None``
(degrades to ``apply-without-probe``, which is the path that must be idempotent
for the diff-test to be meaningful — a probe-gated run would couple the test
to a live ZIM, defeating the purpose of a unit-level orchestration guard).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openzim_mcp.intent_parser import IntentParser

_PROBES_PATH = Path(__file__).resolve().parent / "data" / "b1_b13_probes.jsonl"


def _load_probes() -> list[dict]:
    """Load the b1→b13 probe set committed alongside this test."""
    return [
        json.loads(line)
        for line in _PROBES_PATH.read_text().splitlines()
        if line.strip()
    ]


def _run_tier1(query: str) -> str:
    """Apply the Tier 1 misspelling + stopword chain exactly as
    ``IntentParser._apply_tier1_rewrites`` does (minus the pre-step
    ``_normalize_topic_case`` and the post-step ``_decompose_x_of_y``,
    which are out of scope for this orchestration guard).
    """
    rewritten = IntentParser._apply_misspelling_map(query, title_probe=None)
    rewritten = IntentParser._detect_stopword_phrase(rewritten, title_probe=None)
    return rewritten


@pytest.mark.parametrize(
    "probe",
    _load_probes(),
    ids=lambda p: p["probe_id"],
)
def test_preprocessing_idempotent(probe: dict) -> None:
    """A second pass through the Tier 1 chain yields byte-identical output."""
    pass1 = _run_tier1(probe["topic"])
    pass2 = _run_tier1(pass1)
    assert pass1 == pass2, (
        f"non-idempotent on {probe['probe_id']}: "
        f"pass1={pass1!r} vs pass2={pass2!r} (input={probe['topic']!r})"
    )
