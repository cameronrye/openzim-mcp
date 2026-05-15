# Search-engine-style `zim_query` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `zim_query` return useful answers to natural-language questions like *"who are some famous people from big rapids, michigan"* by adding greedy-tail entity resolution to both default and synthesize paths, plus section-heading affinity ranking and multi-round handles to the synthesize response.

**Architecture:** Three coordinated changes across five existing files. A new tail-iteration helper in `title_promotion.py` is shared between `synthesize._promote_title_match` (synthesize path) and `simple_tools._promote_topic_via_title_index` (default `tell_me_about` path). A new section-affinity boost stage in `synthesize.py` re-ranks passages whose section heading shares tokens with the query. `SynthesizeResponse` gains `considered_articles` + `considered_sections` so the next conversation turn can pivot without re-running search.

**Tech Stack:** Python 3.11, Pydantic v2 (config), TypedDicts (response shapes), pytest with `MagicMock` fixtures (heavy mock-based testing per project convention).

**Spec:** [`docs/superpowers/specs/2026-05-15-search-engine-zim-query-design.md`](../specs/2026-05-15-search-engine-zim-query-design.md)

---

## File Structure

### Create
- `tests/test_iter_query_tails.py` — Unit tests for the new `iter_query_tails` helper.
- `tests/test_simple_tools_tail_probe.py` — Tests that `_promote_topic_via_title_index` uses the tail probe on prose-shaped topics.
- `tests/test_synthesize_section_affinity.py` — Tests for the new `_boost_by_section_affinity` stage.
- `tests/test_synthesize_considered_handles.py` — Tests for the new `considered_articles` + `considered_sections` response fields.

### Modify
- `openzim_mcp/title_promotion.py` — Add `iter_query_tails(query, max_len=4, min_len=1)` helper.
- `openzim_mcp/simple_tools.py` — `_promote_topic_via_title_index` iterates `iter_query_tails(topic)` and probes each tail before giving up.
- `openzim_mcp/synthesize.py` — `_promote_title_match` replaces the 4+ token short-circuit with `iter_query_tails`. New `_boost_by_section_affinity` stage. Response builder populates `considered_articles` + `considered_sections`.
- `openzim_mcp/tool_schemas.py` — Add `ConsideredArticle` and `ConsideredSection` TypedDicts; extend `SynthesizeResponse` with two new optional fields (`total=False`).
- `openzim_mcp/config.py` — Extend `SynthesizeConfig` with `section_affinity_threshold` (default `0.25`) and `section_affinity_boost` (default `1.5`).
- `tests/test_synthesize_title_promotion_v2a9.py` — Existing test that asserts the 4-token short-circuit needs updating (the short-circuit is being removed).

### One file, one responsibility
- `iter_query_tails`: pure query-tokenization + tail-iteration. No I/O, no archive references. Lives in `title_promotion.py` because that module already houses the title-promotion utilities.
- `_boost_by_section_affinity`: pure ranking-stage function. Takes passages + bundle_lookup + query + config; returns re-sorted passages. Lives in `synthesize.py` adjacent to `_attribute_sections` since both consume the same bundle.
- `_build_considered_articles` / `_build_considered_sections`: pure helpers that derive the two new fields from existing state (`top_hits`, `bundle_lookup`, `capped`). Live in `synthesize.py`.

---

## Task 1: Add affinity-boost tunables to `SynthesizeConfig`

**Files:**
- Modify: `openzim_mcp/config.py:98-115`
- Test: `tests/test_config.py` (existing — add one test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_synthesize_config_has_section_affinity_tunables():
    """Section-affinity ranking knobs default to documented values."""
    from openzim_mcp.config import SynthesizeConfig

    cfg = SynthesizeConfig()
    assert cfg.section_affinity_threshold == 0.25
    assert cfg.section_affinity_boost == 1.5


def test_synthesize_config_rejects_invalid_section_affinity_bounds():
    """Threshold must be in [0,1]; boost must be >= 1.0 (a multiplier)."""
    from pydantic import ValidationError

    from openzim_mcp.config import SynthesizeConfig

    with pytest.raises(ValidationError):
        SynthesizeConfig(section_affinity_threshold=1.5)
    with pytest.raises(ValidationError):
        SynthesizeConfig(section_affinity_threshold=-0.1)
    with pytest.raises(ValidationError):
        SynthesizeConfig(section_affinity_boost=0.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_synthesize_config_has_section_affinity_tunables tests/test_config.py::test_synthesize_config_rejects_invalid_section_affinity_bounds -v`
Expected: FAIL with `AttributeError: 'SynthesizeConfig' object has no attribute 'section_affinity_threshold'`.

- [ ] **Step 3: Add the fields to `SynthesizeConfig`**

In `openzim_mcp/config.py`, modify `SynthesizeConfig`:

```python
class SynthesizeConfig(BaseModel):
    """Phase C: tunables for `zim_query(synthesize=True)`.

    All knobs are advisory — the synthesize pipeline obeys these as
    soft budgets (e.g., output_char_budget truncates the *last* passage
    rather than refusing to include it).
    """

    top_n: int = Field(default=5, ge=1, le=50, description="Final passages returned.")
    per_archive_k: int = Field(
        default=10, ge=1, le=100, description="Top-K from each archive before fusion."
    )
    output_char_budget: int = Field(
        default=4800,
        ge=500,
        le=20000,
        description="Soft cap on answer_markdown chars (~1200 tokens).",
    )
    section_affinity_threshold: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description=(
            "Minimum |query ∩ heading| / |heading| ratio before a "
            "section-attributed passage gets the affinity boost."
        ),
    )
    section_affinity_boost: float = Field(
        default=1.5,
        ge=1.0,
        le=10.0,
        description=(
            "Multiplier applied to a passage's score when its section "
            "heading affinity-matches the query. Conservative: won't "
            "dominate strong BM25 hits."
        ),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py::test_synthesize_config_has_section_affinity_tunables tests/test_config.py::test_synthesize_config_rejects_invalid_section_affinity_bounds -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/config.py tests/test_config.py
git commit -m "feat(v2): SynthesizeConfig knobs for section-affinity ranking"
```

---

## Task 2: Add `iter_query_tails` helper to `title_promotion.py`

**Files:**
- Modify: `openzim_mcp/title_promotion.py` (add new function at module level)
- Test: `tests/test_iter_query_tails.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_iter_query_tails.py`:

```python
"""Tests for iter_query_tails — greedy length-down tail iteration over
a natural-language query for entity-resolution title-index probes.

Replaces the M26 4+ token short-circuit in _promote_title_match: instead
of giving up on multi-word prose queries, generate every plausible
entity tail and let the caller probe each one.
"""

from __future__ import annotations

import pytest

from openzim_mcp.title_promotion import iter_query_tails


def test_iter_query_tails_yields_longest_first():
    """Greedy: 4-token tail before 3-token before 2-token before 1-token."""
    tails = list(iter_query_tails("a b c d e"))
    assert tails == ["b c d e", "c d e", "d e", "e"]


def test_iter_query_tails_caps_at_max_len_4_by_default():
    """A 9-token query yields at most 4 tails (lengths 4, 3, 2, 1)."""
    tails = list(iter_query_tails("who are some famous people from big rapids michigan"))
    assert tails == [
        "from big rapids michigan",
        "big rapids michigan",
        "rapids michigan",
        "michigan",
    ]


def test_iter_query_tails_short_query_yields_what_fits():
    """3-token query yields tails of length 3, 2, 1."""
    tails = list(iter_query_tails("big rapids michigan"))
    assert tails == ["big rapids michigan", "rapids michigan", "michigan"]


def test_iter_query_tails_single_token_yields_one_tail():
    tails = list(iter_query_tails("detroit"))
    assert tails == ["detroit"]


def test_iter_query_tails_empty_query_yields_nothing():
    assert list(iter_query_tails("")) == []
    assert list(iter_query_tails("   ")) == []


def test_iter_query_tails_normalizes_whitespace():
    """Multiple spaces / tabs collapse; surrounding whitespace stripped."""
    tails = list(iter_query_tails("  big   rapids\tmichigan  "))
    assert tails == ["big rapids michigan", "rapids michigan", "michigan"]


def test_iter_query_tails_preserves_original_case_per_token():
    """Tokens kept verbatim — case-sensitive callers (title-index) get
    the user's casing untouched. The tail-probe API is responsible for
    lowercasing if it needs to."""
    tails = list(iter_query_tails("Big Rapids Michigan"))
    assert tails[0] == "Big Rapids Michigan"


def test_iter_query_tails_custom_max_len():
    """Caller can cap the longest tail tried."""
    tails = list(iter_query_tails("a b c d e f", max_len=2))
    assert tails == ["e f", "f"]


def test_iter_query_tails_custom_min_len():
    """Caller can require multi-token tails (skip single-token misfires)."""
    tails = list(iter_query_tails("a b c d e", min_len=2))
    assert tails == ["b c d e", "c d e", "d e"]


def test_iter_query_tails_punctuation_treated_as_token_break():
    """Punctuation between words breaks tokens — 'big rapids, michigan'
    has three tokens, not 'rapids,' as one."""
    tails = list(iter_query_tails("big rapids, michigan"))
    assert tails == ["big rapids michigan", "rapids michigan", "michigan"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_iter_query_tails.py -v`
Expected: FAIL with `ImportError: cannot import name 'iter_query_tails' from 'openzim_mcp.title_promotion'`.

- [ ] **Step 3: Add `iter_query_tails` to `title_promotion.py`**

Append to `openzim_mcp/title_promotion.py` (after `find_title_match`):

```python
import re as _re

# Tokenizer: alphanumeric runs only. Punctuation, whitespace, and
# control chars all act as token boundaries. Matches the tokenization
# convention already used elsewhere in the codebase (e.g.
# is_strong_title_match) so tail-probe behavior is consistent with the
# rest of the title-promotion module.
_TAIL_TOKEN_RE = _re.compile(r"[\w]+", _re.UNICODE)


def iter_query_tails(
    query: str,
    *,
    max_len: int = 4,
    min_len: int = 1,
) -> Iterator[str]:
    """Yield greedy length-down trailing token windows of ``query``.

    Used by both ``_promote_title_match`` (synthesize path) and
    ``_promote_topic_via_title_index`` (tell_me_about path) to probe
    a multi-word natural-language query for an entity that resolves
    against a ZIM archive's title index.

    Example:
        ``"who are some famous people from big rapids michigan"``
        with default bounds yields:
            ``"from big rapids michigan"``
            ``"big rapids michigan"``
            ``"rapids michigan"``
            ``"michigan"``

    The caller probes each yielded tail in order; the first to resolve
    wins. Greedy length-down picks the most specific entity that
    actually exists (``"big rapids michigan"`` beats ``"michigan"``
    when both resolve).

    Args:
        query: Natural-language query. Tokenized on alphanumeric runs,
            so punctuation between words is treated as a boundary
            (``"big rapids, michigan"`` → 3 tokens).
        max_len: Longest tail to yield. Default 4 — empirically, ZIM
            article titles rarely exceed 4 tokens, and the cost of a
            failed probe is microseconds, so a tight cap is safe.
        min_len: Shortest tail to yield. Default 1. Callers that want
            to skip single-token false positives can raise this.

    Yields:
        Tail strings reconstructed by joining tokens with single
        spaces, in the order they were found in ``query``. Original
        case is preserved (the caller is responsible for any
        lowercasing the title index needs).
    """
    if not query or not query.strip():
        return
    tokens = _TAIL_TOKEN_RE.findall(query)
    if not tokens:
        return
    upper = min(max_len, len(tokens))
    lower = max(1, min_len)
    for tail_len in range(upper, lower - 1, -1):
        yield " ".join(tokens[-tail_len:])
```

Also add to the top of the file (if not already imported):

```python
from typing import Iterator
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_iter_query_tails.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/title_promotion.py tests/test_iter_query_tails.py
git commit -m "feat(v2): iter_query_tails helper for entity tail-probe"
```

---

## Task 3: Use `iter_query_tails` in `_promote_topic_via_title_index` (default `tell_me_about` path)

**Files:**
- Modify: `openzim_mcp/simple_tools.py:2141-2169` (`_promote_topic_via_title_index`)
- Test: `tests/test_simple_tools_tail_probe.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_simple_tools_tail_probe.py`:

```python
"""Tests that the default-mode tell_me_about title-promotion path
probes greedy tails of a prose-shaped topic before giving up.

Without the tail probe, "some famous people from big rapids michigan"
is passed verbatim to find_title_match, which returns nothing because
no article has that exact title. The probe falls back to shorter tails
and resolves "big rapids michigan" → Big_Rapids,_Michigan.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from openzim_mcp.simple_tools import SimpleToolsHandler


def _make_handler(title_responses: Dict[str, Optional[Dict[str, Any]]]) -> Any:
    """Construct a SimpleToolsHandler whose find_entry_by_title_data
    consults a topic→result dict. Returns the handler with mocked
    zim_operations.find_entry_by_title_data."""
    handler = SimpleToolsHandler.__new__(SimpleToolsHandler)
    handler.zim_operations = MagicMock()

    def fake_find(zim_path: str, topic: str, *, cross_file: bool = False, limit: int = 3):
        result = title_responses.get(topic)
        if result is None:
            return {"results": []}
        return {"results": [result]}

    handler.zim_operations.find_entry_by_title_data.side_effect = fake_find
    return handler


def test_promote_resolves_via_shorter_tail():
    """Full prose topic misses; 3-token tail hits."""
    handler = _make_handler(
        {
            "big rapids michigan": {
                "path": "Big_Rapids,_Michigan",
                "title": "Big Rapids, Michigan",
                "score": 1.0,
                "zim_file": "wiki.zim",
            }
        }
    )
    result = handler._promote_topic_via_title_index(
        "/fake/wiki.zim",
        "some famous people from big rapids michigan",
    )
    assert result is not None
    assert result["path"] == "Big_Rapids,_Michigan"


def test_promote_resolves_via_single_token_tail():
    """A 1-token entity at the end ('detroit') resolves when longer
    tails miss."""
    handler = _make_handler(
        {
            "detroit": {
                "path": "Detroit",
                "title": "Detroit",
                "score": 1.0,
                "zim_file": "wiki.zim",
            }
        }
    )
    result = handler._promote_topic_via_title_index(
        "/fake/wiki.zim",
        "what is the population of detroit",
    )
    assert result is not None
    assert result["path"] == "Detroit"


def test_promote_prefers_longest_resolving_tail():
    """When both 'big rapids michigan' and 'michigan' resolve, the
    longer (more specific) one wins."""
    handler = _make_handler(
        {
            "big rapids michigan": {
                "path": "Big_Rapids,_Michigan",
                "title": "Big Rapids, Michigan",
                "score": 1.0,
                "zim_file": "wiki.zim",
            },
            "michigan": {
                "path": "Michigan",
                "title": "Michigan",
                "score": 1.0,
                "zim_file": "wiki.zim",
            },
        }
    )
    result = handler._promote_topic_via_title_index(
        "/fake/wiki.zim",
        "famous people from big rapids michigan",
    )
    assert result is not None
    assert result["path"] == "Big_Rapids,_Michigan"


def test_promote_returns_none_when_no_tail_resolves():
    """All tails miss → None, caller falls back to BM25 search."""
    handler = _make_handler({})  # nothing resolves
    result = handler._promote_topic_via_title_index(
        "/fake/wiki.zim", "completely unknown phrase here"
    )
    assert result is None


def test_promote_single_token_topic_still_works():
    """The existing exact-topic case (single-word topic) still
    resolves via the 1-token tail (which equals the whole query)."""
    handler = _make_handler(
        {
            "berlin": {
                "path": "Berlin",
                "title": "Berlin",
                "score": 1.0,
                "zim_file": "wiki.zim",
            }
        }
    )
    result = handler._promote_topic_via_title_index("/fake/wiki.zim", "berlin")
    assert result is not None
    assert result["path"] == "Berlin"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_simple_tools_tail_probe.py -v`
Expected: FAIL — `test_promote_resolves_via_shorter_tail` and `test_promote_resolves_via_single_token_tail` fail because `find_title_match` is currently called once with the full topic.

- [ ] **Step 3: Rewrite `_promote_topic_via_title_index` to use tail iteration**

In `openzim_mcp/simple_tools.py`, replace the body of `_promote_topic_via_title_index` ([line 2141](openzim_mcp/simple_tools.py#L2141)):

```python
def _promote_topic_via_title_index(
    self, zim_file_path: str, topic: str
) -> Optional[Dict[str, Any]]:
    """Promote a canonical title-index hit for ``topic`` past noisy BM25
    ranking. Tries the strict 1.0-score gate first, then falls back to
    the 0.8-score typo-tolerant gate.

    Returns the resolved ``{path, title, zim_file}`` dict, or ``None``
    when neither gate fires.

    A14: when the full topic doesn't resolve, fall back to greedy
    length-down tail probes (``iter_query_tails``). The motivating case
    is prose-shaped tell_me_about topics ("famous people from big
    rapids michigan") where the full string never resolves but a
    trailing entity ("big rapids michigan") does. Greedy length-down
    picks the most specific entity that exists.

    D6 fix (v2.0.0a9): Xapian ranks ``List of songs about Berlin``
    above the canonical ``Berlin`` article for ``query=Berlin``
    because the title-match boost isn't strong enough. The 1.0 gate
    promotes the canonical past that ranking.

    D3 (beta): the 0.8 gate catches single-edit typos via the
    ``_find_entry_typo_fallback`` chain
    (``Photosythesis`` → ``Photosynthesis``, score 0.85). Without
    this step ``tell me about Photosythesis`` fell all the way
    through to Xapian search and returned a totally unrelated
    article. The chain is conservative by construction
    (length-gated at ≥5 chars, ≤700 variants).
    """
    from openzim_mcp.title_promotion import iter_query_tails

    for tail in iter_query_tails(topic):
        promoted = find_title_match(self.zim_operations, zim_file_path, tail)
        if promoted is not None:
            return promoted
        promoted = find_title_match(
            self.zim_operations, zim_file_path, tail, min_score=0.8
        )
        if promoted is not None:
            return promoted
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_simple_tools_tail_probe.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full simple_tools test suite to verify no regression**

Run: `uv run pytest tests/test_simple_tools.py -v`
Expected: All previously-passing tests still pass. (If any test asserted that `find_title_match` was called exactly once with the full topic, it will need to be updated to accept the tail-probe sequence — this is a known behavior change documented in the spec.)

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/simple_tools.py tests/test_simple_tools_tail_probe.py
git commit -m "feat(v2): tail-probe entity resolution in tell_me_about

Prose-shaped topics like 'famous people from big rapids michigan'
now resolve to Big_Rapids,_Michigan via greedy length-down tail
iteration over iter_query_tails(topic). Previously such topics were
passed verbatim to find_title_match, missed, and fell through to
BM25 noise."
```

---

## Task 4: Use `iter_query_tails` in `_promote_title_match` (synthesize path)

**Files:**
- Modify: `openzim_mcp/synthesize.py:498-582` (`_promote_title_match`)
- Modify: `tests/test_synthesize_title_promotion_v2a9.py` (existing test of the 4-token short-circuit needs updating)
- Test: extends `tests/test_synthesize_title_promotion_v2a9.py` with new tail-probe coverage

- [ ] **Step 1: Inspect the existing test that depends on the 4-token short-circuit**

Look at `tests/test_synthesize_title_promotion_v2a9.py` for tests asserting the short-circuit. The expected one is named or commented around M26 / 4-token behavior. Read the file:

Run: `uv run pytest tests/test_synthesize_title_promotion_v2a9.py -v --collect-only`

Identify any test that depends on the 4-token cap firing. There should not be many — the cap was a recent addition. If one exists, it needs to be updated to reflect the new tail-probe behavior in a follow-up step.

- [ ] **Step 2: Write new failing tests for the tail-probe behavior**

Append to `tests/test_synthesize_title_promotion_v2a9.py`:

```python
def test_promote_title_match_tail_probe_resolves_short_tail():
    """A14: prose-shaped query (>4 tokens) now probes greedy tails
    instead of short-circuiting. 'famous people from big rapids
    michigan' → 'big rapids michigan' resolves Big_Rapids,_Michigan."""
    bm25_top_hits = [
        ("wiki", {"path": "Famous_People_(film)", "snippet": "...", "score": 0.5}),
    ]

    def fake_title_match(archive: Any, query: str) -> Any:
        if query == "big rapids michigan":
            return {"path": "Big_Rapids,_Michigan", "snippet": "...", "score": 1.0}
        return None

    search_handler = MagicMock()
    search_handler.title_match_hit.side_effect = fake_title_match
    archive = MagicMock()

    promoted = _promote_title_match(
        bm25_top_hits,
        query="famous people from big rapids michigan",
        archives=[(archive, Path("/fake/wiki.zim"))],
        archives_searched=["wiki"],
        search_handler=search_handler,
    )
    assert promoted[0][1]["path"] == "Big_Rapids,_Michigan"


def test_promote_title_match_tail_probe_prefers_longest_resolving_tail():
    """When both 'big rapids michigan' and 'michigan' would resolve,
    the longer (more specific) one wins."""
    bm25_top_hits = [
        ("wiki", {"path": "Some_Other_Article", "snippet": "...", "score": 0.5}),
    ]

    def fake_title_match(archive: Any, query: str) -> Any:
        if query == "big rapids michigan":
            return {"path": "Big_Rapids,_Michigan", "snippet": "...", "score": 1.0}
        if query == "michigan":
            return {"path": "Michigan", "snippet": "...", "score": 1.0}
        return None

    search_handler = MagicMock()
    search_handler.title_match_hit.side_effect = fake_title_match
    archive = MagicMock()

    promoted = _promote_title_match(
        bm25_top_hits,
        query="famous people from big rapids michigan",
        archives=[(archive, Path("/fake/wiki.zim"))],
        archives_searched=["wiki"],
        search_handler=search_handler,
    )
    assert promoted[0][1]["path"] == "Big_Rapids,_Michigan"


def test_promote_title_match_tail_probe_no_short_circuit_for_long_queries():
    """A14: M26's 4+ token short-circuit is removed. Long queries with
    a clear entity tail now probe and resolve."""
    bm25_top_hits = []

    def fake_title_match(archive: Any, query: str) -> Any:
        if query == "detroit":
            return {"path": "Detroit", "snippet": "...", "score": 1.0}
        return None

    search_handler = MagicMock()
    search_handler.title_match_hit.side_effect = fake_title_match
    archive = MagicMock()

    promoted = _promote_title_match(
        bm25_top_hits,
        query="what is the population of detroit",
        archives=[(archive, Path("/fake/wiki.zim"))],
        archives_searched=["wiki"],
        search_handler=search_handler,
    )
    assert len(promoted) == 1
    assert promoted[0][1]["path"] == "Detroit"


def test_promote_title_match_tail_probe_falls_through_when_no_tail_resolves():
    """All tails miss → return top_hits unchanged."""
    bm25_top_hits = [
        ("wiki", {"path": "Unrelated_Article", "snippet": "...", "score": 0.3}),
    ]
    search_handler = MagicMock()
    search_handler.title_match_hit.return_value = None
    archive = MagicMock()

    promoted = _promote_title_match(
        bm25_top_hits,
        query="completely unknown phrase here that nothing matches",
        archives=[(archive, Path("/fake/wiki.zim"))],
        archives_searched=["wiki"],
        search_handler=search_handler,
    )
    assert promoted == bm25_top_hits
```

- [ ] **Step 3: Run new tests to verify they fail**

Run: `uv run pytest tests/test_synthesize_title_promotion_v2a9.py::test_promote_title_match_tail_probe_resolves_short_tail tests/test_synthesize_title_promotion_v2a9.py::test_promote_title_match_tail_probe_prefers_longest_resolving_tail tests/test_synthesize_title_promotion_v2a9.py::test_promote_title_match_tail_probe_no_short_circuit_for_long_queries tests/test_synthesize_title_promotion_v2a9.py::test_promote_title_match_tail_probe_falls_through_when_no_tail_resolves -v`
Expected: FAIL — current code short-circuits on long queries and only probes the full query string.

- [ ] **Step 4: Rewrite `_promote_title_match` to use tail iteration**

In `openzim_mcp/synthesize.py`, replace the body of `_promote_title_match` ([line 498](openzim_mcp/synthesize.py#L498)). Keep the strong-top-hit guard intact; replace the 4-token cap + single-probe with the tail loop:

```python
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
    from openzim_mcp.title_promotion import iter_query_tails

    if top_hits:
        top_hit_0 = top_hits[0][1]
        top_path = str(top_hit_0.get("path", ""))
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
            if not isinstance(promoted, dict):
                continue
            promoted_path = str(promoted.get("path", ""))
            if not promoted_path:
                continue
            if (archive_name, promoted_path) in existing_paths:
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
```

- [ ] **Step 5: Run new tests to verify they pass**

Run: `uv run pytest tests/test_synthesize_title_promotion_v2a9.py -v`
Expected: All new tail-probe tests PASS. Pre-existing tests should continue to pass — the strong-top-hit guard and the existing single-token / canonical-title cases all go through the tail loop with the same outcome.

- [ ] **Step 6: Run the full synthesize test suite to verify no regression**

Run: `uv run pytest tests/test_synthesize.py tests/test_synthesize_title_promotion_v2a9.py tests/test_synthesize_meta_d7d8_v2a9.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add openzim_mcp/synthesize.py tests/test_synthesize_title_promotion_v2a9.py
git commit -m "feat(v2): tail-probe entity resolution in synthesize

Drops the M26 4+ token short-circuit in _promote_title_match.
Replaces it with greedy length-down tail iteration via the shared
iter_query_tails helper. Long question-shaped queries with a clear
entity tail now resolve canonically instead of falling through to
BM25 noise."
```

---

## Task 5: Section-affinity boost stage in `synthesize.py`

**Files:**
- Modify: `openzim_mcp/synthesize.py` (add `_boost_by_section_affinity` and wire it into `synthesize_query`)
- Test: `tests/test_synthesize_section_affinity.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_synthesize_section_affinity.py`:

```python
"""Tests for _boost_by_section_affinity — re-ranks section-attributed
passages whose section heading shares tokens with the query.

The motivating case: query 'famous people from big rapids michigan'
should bubble the #Notable_people passage above the #History passage
because 'people' (query token) appears in 'Notable people' (heading
tokens) but not in 'History'.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

from openzim_mcp.config import SynthesizeConfig
from openzim_mcp.synthesize import _boost_by_section_affinity


def _passage(cite_id: str, score: float, rank: int = 0) -> Dict[str, Any]:
    return {
        "cite_id": cite_id,
        "text_markdown": f"text for {cite_id}",
        "rank": rank,
        "score": score,
    }


def _bundle_lookup_for(
    sections_by_path: Dict[str, List[Dict[str, Any]]],
) -> Any:
    """Build a fake bundle_lookup that returns sections for known paths."""

    def lookup(archive_name: str, entry_path: str) -> Any:
        sections = sections_by_path.get(entry_path)
        if sections is None:
            return None
        return {"sections": sections, "rendered_markdown": ""}

    return lookup


def test_boost_promotes_passage_when_section_heading_matches_query():
    """'famous people' query → 'Notable people' heading gets boosted
    past 'History'."""
    passages = [
        _passage("wiki/Big_Rapids,_Michigan#History", score=1.0, rank=1),
        _passage("wiki/Big_Rapids,_Michigan#Notable_people", score=0.6, rank=2),
    ]
    bundle_lookup = _bundle_lookup_for(
        {
            "Big_Rapids,_Michigan": [
                {"id": "History", "title": "History", "char_start": 0, "char_end": 100},
                {
                    "id": "Notable_people",
                    "title": "Notable people",
                    "char_start": 100,
                    "char_end": 200,
                },
            ]
        }
    )
    cfg = SynthesizeConfig()  # threshold=0.25, boost=1.5

    out = _boost_by_section_affinity(
        passages,
        query="famous people from big rapids michigan",
        bundle_lookup=bundle_lookup,
        config=cfg,
    )

    # Affinity: 'Notable people' has tokens {notable, people}; query has
    # {famous, people, from, big, rapids, michigan}. Intersect = {people}.
    # Affinity = 1/2 = 0.5 >= 0.25. Score becomes 0.6 * 1.5 = 0.9, still
    # below 1.0. So this test verifies the score is boosted but History
    # may still be rank 0 unless we also raise the boost. Adjust: drop
    # the History score below Notable_people post-boost.
    paths_in_order = [p["cite_id"] for p in out]
    notable_idx = paths_in_order.index("wiki/Big_Rapids,_Michigan#Notable_people")
    history_idx = paths_in_order.index("wiki/Big_Rapids,_Michigan#History")
    # Notable_people boosted to 0.9, History stays at 1.0. History first.
    # This test asserts the BOOST is applied, not necessarily that it
    # flips the order (which depends on the gap).
    notable_passage = out[notable_idx]
    assert notable_passage["score"] == 0.6 * 1.5


def test_boost_flips_order_when_boosted_passage_overtakes():
    """When the boosted passage's new score exceeds the prior leader,
    it ranks first."""
    passages = [
        _passage("wiki/Big_Rapids,_Michigan#History", score=0.5, rank=1),
        _passage("wiki/Big_Rapids,_Michigan#Notable_people", score=0.4, rank=2),
    ]
    bundle_lookup = _bundle_lookup_for(
        {
            "Big_Rapids,_Michigan": [
                {"id": "History", "title": "History", "char_start": 0, "char_end": 100},
                {
                    "id": "Notable_people",
                    "title": "Notable people",
                    "char_start": 100,
                    "char_end": 200,
                },
            ]
        }
    )
    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="famous people from big rapids",
        bundle_lookup=bundle_lookup,
        config=cfg,
    )
    # Notable_people: 0.4 * 1.5 = 0.6. History: 0.5. Notable_people wins.
    assert out[0]["cite_id"] == "wiki/Big_Rapids,_Michigan#Notable_people"


def test_boost_no_op_when_no_query_token_in_heading():
    """No shared tokens → no boost, original order preserved."""
    passages = [
        _passage("wiki/Big_Rapids,_Michigan#History", score=1.0, rank=1),
        _passage("wiki/Big_Rapids,_Michigan#Geography", score=0.6, rank=2),
    ]
    bundle_lookup = _bundle_lookup_for(
        {
            "Big_Rapids,_Michigan": [
                {"id": "History", "title": "History", "char_start": 0, "char_end": 100},
                {
                    "id": "Geography",
                    "title": "Geography",
                    "char_start": 100,
                    "char_end": 200,
                },
            ]
        }
    )
    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="who founded big rapids",
        bundle_lookup=bundle_lookup,
        config=cfg,
    )
    # No 'history' or 'geography' tokens in query → no boost
    assert out[0]["score"] == 1.0
    assert out[1]["score"] == 0.6


def test_boost_skips_article_level_citations():
    """Passages without a #section_id suffix are left untouched."""
    passages = [
        _passage("wiki/Big_Rapids,_Michigan", score=1.0, rank=1),
        _passage("wiki/Big_Rapids,_Michigan#Notable_people", score=0.6, rank=2),
    ]
    bundle_lookup = _bundle_lookup_for(
        {
            "Big_Rapids,_Michigan": [
                {
                    "id": "Notable_people",
                    "title": "Notable people",
                    "char_start": 0,
                    "char_end": 200,
                },
            ]
        }
    )
    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="famous people",
        bundle_lookup=bundle_lookup,
        config=cfg,
    )
    # Article-level passage score unchanged
    article_passage = next(
        p for p in out if p["cite_id"] == "wiki/Big_Rapids,_Michigan"
    )
    assert article_passage["score"] == 1.0


def test_boost_threshold_gate_blocks_weak_overlap():
    """Single token overlap against a 5-token heading is 1/5 = 0.2,
    below the default threshold of 0.25. No boost."""
    passages = [
        _passage(
            "wiki/Foo#A_Very_Long_Heading_Name_Here", score=1.0, rank=1
        ),
    ]
    bundle_lookup = _bundle_lookup_for(
        {
            "Foo": [
                {
                    "id": "A_Very_Long_Heading_Name_Here",
                    "title": "A very long heading name here",
                    "char_start": 0,
                    "char_end": 100,
                },
            ]
        }
    )
    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="long stuff",  # 'long' overlaps; 1/6 ≈ 0.167 (after dedupe) < 0.25
        bundle_lookup=bundle_lookup,
        config=cfg,
    )
    assert out[0]["score"] == 1.0


def test_boost_handles_missing_section_in_bundle():
    """Section_id present on cite_id but not found in bundle → skip
    silently, no boost, no crash."""
    passages = [
        _passage("wiki/Foo#nonexistent_section", score=1.0, rank=1),
    ]
    bundle_lookup = _bundle_lookup_for({"Foo": []})  # empty sections list
    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="anything goes here",
        bundle_lookup=bundle_lookup,
        config=cfg,
    )
    assert out[0]["score"] == 1.0


def test_boost_handles_bundle_lookup_returning_none():
    """Bundle lookup returns None → no crash, no boost."""
    passages = [
        _passage("wiki/Foo#Section", score=1.0, rank=1),
    ]

    def none_lookup(archive_name: str, entry_path: str) -> Any:
        return None

    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="anything",
        bundle_lookup=none_lookup,
        config=cfg,
    )
    assert out[0]["score"] == 1.0


def test_boost_handles_bundle_lookup_raising():
    """Bundle lookup raises → no crash, no boost, logged at debug."""
    passages = [
        _passage("wiki/Foo#Section", score=1.0, rank=1),
    ]

    def raising_lookup(archive_name: str, entry_path: str) -> Any:
        raise RuntimeError("bundle build failed")

    cfg = SynthesizeConfig()

    out = _boost_by_section_affinity(
        passages,
        query="anything",
        bundle_lookup=raising_lookup,
        config=cfg,
    )
    assert out[0]["score"] == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_synthesize_section_affinity.py -v`
Expected: FAIL — `_boost_by_section_affinity` does not yet exist.

- [ ] **Step 3: Implement `_boost_by_section_affinity` and wire into pipeline**

Add to `openzim_mcp/synthesize.py` after `_attribute_sections` (around line 311):

```python
# ---------------------------------------------------------------------------
# Pipeline stage 5b: section-heading affinity boost (A14)
# ---------------------------------------------------------------------------

# Same tokenizer used in iter_query_tails — alphanumeric runs only.
_AFFINITY_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def _affinity_tokens(text: str) -> set[str]:
    """Lowercase alphanumeric token set. Empty set for empty input."""
    if not text:
        return set()
    return {t.lower() for t in _AFFINITY_TOKEN_RE.findall(text)}


def _boost_by_section_affinity(
    passages: list[SynthesizePassage],
    *,
    query: str,
    bundle_lookup: Callable[[str, str], Any],
    config: SynthesizeConfig,
) -> list[SynthesizePassage]:
    """Re-rank passages by section-heading affinity with the query.

    For each passage with a ``#section_id`` suffix on its cite_id,
    look up the section's heading in the bundle and compute
    ``|query_tokens ∩ heading_tokens| / |heading_tokens|``. When that
    affinity is ≥ ``config.section_affinity_threshold``, multiply the
    passage's score by ``config.section_affinity_boost``. Re-sort the
    list by score descending.

    Article-level citations (no section_id), passages whose section
    isn't in the bundle, and bundle-lookup failures are all no-ops:
    the passage is preserved with its original score.

    No-op when the query has no tokens (empty or whitespace-only).

    Bundle caching: each (archive, entry_path) is looked up once and
    its section→title map memoized for the duration of the call.
    """
    query_tokens = _affinity_tokens(query)
    if not query_tokens:
        return passages

    threshold = config.section_affinity_threshold
    boost = config.section_affinity_boost

    # Memoize section title lookups per (archive, entry_path) so a bundle
    # with multiple matching passages doesn't re-fetch.
    titles_by_key: dict[tuple[str, str], dict[str, str]] = {}

    def section_titles_for(archive_name: str, entry_path: str) -> dict[str, str]:
        key = (archive_name, entry_path)
        if key in titles_by_key:
            return titles_by_key[key]
        try:
            bundle = bundle_lookup(archive_name, entry_path)
        except Exception as e:
            logger.debug(
                "section-affinity bundle lookup failed for %s/%s: %s",
                archive_name,
                entry_path,
                e,
            )
            titles_by_key[key] = {}
            return titles_by_key[key]
        if bundle is None:
            titles_by_key[key] = {}
            return titles_by_key[key]
        titles = {
            str(s.get("id", "")): str(s.get("title", ""))
            for s in bundle.get("sections", [])
            if s.get("id")
        }
        titles_by_key[key] = titles
        return titles

    boosted: list[SynthesizePassage] = []
    for passage in passages:
        cite_id = passage["cite_id"]
        if "#" not in cite_id:
            boosted.append(passage)
            continue
        base, _, section_id = cite_id.partition("#")
        archive_name, _, entry_path = base.partition("/")
        if not archive_name or not entry_path or not section_id:
            boosted.append(passage)
            continue
        titles = section_titles_for(archive_name, entry_path)
        heading = titles.get(section_id, "")
        heading_tokens = _affinity_tokens(heading)
        if not heading_tokens:
            boosted.append(passage)
            continue
        overlap = heading_tokens & query_tokens
        affinity = len(overlap) / len(heading_tokens)
        if affinity >= threshold:
            new_p = dict(passage)
            new_p["score"] = float(passage["score"]) * boost
            boosted.append(cast("SynthesizePassage", new_p))
        else:
            boosted.append(passage)

    boosted.sort(key=lambda p: float(p.get("score", 0.0)), reverse=True)
    return boosted
```

Wire it into `synthesize_query` (around [line 997-1001](openzim_mcp/synthesize.py#L997)):

```python
    attributed = _attribute_sections(
        all_passages, bundle_lookup=bundle_lookup, hit_keys=hit_keys
    )
    # A14 (Change B): section-heading affinity boost. Promotes passages
    # whose section heading shares tokens with the query past lexically-
    # weaker BM25 leaders. No-op for article-level citations and for
    # queries with no token overlap against any heading.
    attributed = _boost_by_section_affinity(
        attributed,
        query=query,
        bundle_lookup=bundle_lookup,
        config=config,
    )
    pre_cap_chars = sum(len(p["text_markdown"]) for p in attributed)
    capped = _enforce_budget(attributed, char_budget=config.output_char_budget)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_synthesize_section_affinity.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 5: Run the full synthesize test suite to verify no regression**

Run: `uv run pytest tests/test_synthesize.py tests/test_synthesize_title_promotion_v2a9.py tests/test_synthesize_meta_d7d8_v2a9.py tests/test_synthesize_section_affinity.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/synthesize.py tests/test_synthesize_section_affinity.py
git commit -m "feat(v2): section-heading affinity boost in synthesize

New _boost_by_section_affinity stage runs after _attribute_sections.
Passages whose section heading shares >= 25%% of its tokens with the
query get a 1.5x score multiplier and re-sort. Bounded archive-
agnostic — the archive's own section headings provide the matching
vocabulary, no curated synonym tables."
```

---

## Task 6: Extend `SynthesizeResponse` with `considered_articles` + `considered_sections`

**Files:**
- Modify: `openzim_mcp/tool_schemas.py:555-564` (`SynthesizeResponse`)
- Test: `tests/test_tool_schemas.py` (existing — add one test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tool_schemas.py` (or create a new test file if no `test_tool_schemas.py` exists — check first with `ls tests/test_tool_schemas.py`):

```python
def test_synthesize_response_accepts_considered_articles_and_sections():
    """A14: SynthesizeResponse exposes considered_articles and
    considered_sections for multi-round refinement. Both fields are
    optional (total=False) so existing callers aren't forced to set
    them."""
    from openzim_mcp.tool_schemas import (
        ConsideredArticle,
        ConsideredSection,
        SynthesizeResponse,
    )

    article: ConsideredArticle = {
        "archive": "wiki",
        "entry_path": "Big_Rapids_Township,_Michigan",
        "title": "Big Rapids Township, Michigan",
        "score": 0.42,
    }
    section: ConsideredSection = {
        "section_id": "History",
        "title": "History",
    }
    response: SynthesizeResponse = {
        "query": "q",
        "answer_markdown": "a",
        "passages": [],
        "citations": [],
        "archives_searched": ["wiki"],
        "fallback_used": "rrf_fusion",
        "total_chars": 1,
        "total_words": 1,
        "_meta": {},  # type: ignore[typeddict-item]
        "considered_articles": [article],
        "considered_sections": [section],
    }
    # The TypedDict accepts the shape — assertion is structural.
    assert response["considered_articles"][0]["title"] == "Big Rapids Township, Michigan"
    assert response["considered_sections"][0]["title"] == "History"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tool_schemas.py::test_synthesize_response_accepts_considered_articles_and_sections -v`
Expected: FAIL with `ImportError: cannot import name 'ConsideredArticle' from 'openzim_mcp.tool_schemas'`.

- [ ] **Step 3: Add the new TypedDicts and extend `SynthesizeResponse`**

In `openzim_mcp/tool_schemas.py`, add before `SynthesizeResponse` (around line 555):

```python
class ConsideredArticle(TypedDict, total=False):
    """A14: an article hit not selected as the featured citation, surfaced
    so the caller can pivot in a follow-up turn without re-running search.

    ``archive`` + ``entry_path`` form the handle the caller passes to
    ``get_zim_entries`` (or composes into a `cite_id`). ``score`` is the
    underlying ranking score at the point of selection — informational,
    not part of the handle.
    """

    archive: str
    entry_path: str
    title: str
    score: float


class ConsideredSection(TypedDict, total=False):
    """A14: a section of the featured article not selected as the featured
    passage. ``section_id`` is the handle the caller passes to
    ``get_section`` (or composes into a `cite_id` suffix).
    """

    section_id: str
    title: str
```

Modify `SynthesizeResponse` (around line 555). Change from `class SynthesizeResponse(TypedDict):` to `class SynthesizeResponse(TypedDict, total=False):` so the new fields are optional. Add the two fields:

```python
class SynthesizeResponse(TypedDict, total=False):
    query: str
    answer_markdown: str
    passages: list[SynthesizePassage]
    citations: list[Citation]
    archives_searched: list[str]
    fallback_used: Literal["xapian_score", "rrf_fusion", "reranker"]
    total_chars: int
    total_words: int
    _meta: MetaEnvelope
    # A14: multi-round handles. Empty lists when no candidate space
    # exists (zero-hit response, or no resolved entity article).
    considered_articles: list[ConsideredArticle]
    considered_sections: list[ConsideredSection]
```

**Note:** Switching the existing fields to `total=False` is intentional — pre-existing callers continue to populate them (they're always set in the synthesize_query return path), so runtime behavior is unchanged. The TypedDict signature loosens to allow the additive shape.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tool_schemas.py::test_synthesize_response_accepts_considered_articles_and_sections -v`
Expected: PASS.

- [ ] **Step 5: Run mypy to verify no type regression**

Run: `uv run mypy openzim_mcp/synthesize.py openzim_mcp/tool_schemas.py openzim_mcp/simple_tools.py`
Expected: No new errors. Pre-existing errors (if any) unchanged.

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/tool_schemas.py tests/test_tool_schemas.py
git commit -m "feat(v2): ConsideredArticle + ConsideredSection types

Two new optional fields on SynthesizeResponse expose the candidate
space — articles ranked but not featured, sections of the featured
article not picked — as handles a follow-up turn can drill into."
```

---

## Task 7: Populate `considered_articles` + `considered_sections` in `synthesize_query`

**Files:**
- Modify: `openzim_mcp/synthesize.py` (add `_build_considered_articles`, `_build_considered_sections`, wire into return)
- Test: `tests/test_synthesize_considered_handles.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_synthesize_considered_handles.py`:

```python
"""Tests for considered_articles + considered_sections population in
synthesize_query (A14).

The featured passage's article and section are excluded from the
considered lists — these surfaces are for *alternatives* the caller can
pivot to, not duplicates of what's already in citations[].
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from openzim_mcp.config import SynthesizeConfig
from openzim_mcp.synthesize import (
    _build_considered_articles,
    _build_considered_sections,
    synthesize_query,
)


def test_build_considered_articles_excludes_featured_and_caps_at_3():
    """Top_hits with 6 entries; passage capped to 1 (featured). The
    considered_articles list has the remaining 5 sorted by their
    original ranking, capped at 3."""
    top_hits = [
        ("wiki", {"path": "Big_Rapids,_Michigan", "title": "Big Rapids, Michigan", "score": 1.0}),
        ("wiki", {"path": "Big_Rapids_Township,_Michigan", "title": "Big Rapids Twp", "score": 0.7}),
        ("wiki", {"path": "Ferris_State_University", "title": "Ferris State", "score": 0.6}),
        ("wiki", {"path": "Mecosta_County,_Michigan", "title": "Mecosta County", "score": 0.5}),
        ("wiki", {"path": "Pere_Marquette_River", "title": "Pere Marquette River", "score": 0.4}),
        ("wiki", {"path": "Muskegon_River", "title": "Muskegon River", "score": 0.3}),
    ]
    capped_passages = [
        {"cite_id": "wiki/Big_Rapids,_Michigan#Notable_people", "text_markdown": "...", "rank": 1, "score": 1.5}
    ]
    result = _build_considered_articles(top_hits, capped_passages, max_n=3)
    assert len(result) == 3
    assert all(a["entry_path"] != "Big_Rapids,_Michigan" for a in result)
    # Preserved order
    assert result[0]["entry_path"] == "Big_Rapids_Township,_Michigan"
    assert result[1]["entry_path"] == "Ferris_State_University"
    assert result[2]["entry_path"] == "Mecosta_County,_Michigan"


def test_build_considered_articles_empty_when_only_featured():
    """One top_hit, captured as the featured passage → empty list."""
    top_hits = [
        ("wiki", {"path": "Big_Rapids,_Michigan", "title": "Big Rapids", "score": 1.0}),
    ]
    capped_passages = [
        {"cite_id": "wiki/Big_Rapids,_Michigan#Notable_people", "text_markdown": "...", "rank": 1, "score": 1.5}
    ]
    result = _build_considered_articles(top_hits, capped_passages, max_n=3)
    assert result == []


def test_build_considered_sections_returns_sections_minus_featured():
    """Featured passage cites Big_Rapids,_Michigan#Notable_people.
    considered_sections returns all OTHER sections in that article's
    bundle."""
    capped_passages = [
        {"cite_id": "wiki/Big_Rapids,_Michigan#Notable_people", "text_markdown": "...", "rank": 1, "score": 1.5}
    ]

    def bundle_lookup(archive_name: str, entry_path: str) -> Any:
        if entry_path == "Big_Rapids,_Michigan":
            return {
                "sections": [
                    {"id": "History", "title": "History"},
                    {"id": "Geography", "title": "Geography"},
                    {"id": "Notable_people", "title": "Notable people"},
                    {"id": "Demographics", "title": "Demographics"},
                ]
            }
        return None

    result = _build_considered_sections(capped_passages, bundle_lookup, max_n=10)
    ids = [s["section_id"] for s in result]
    assert "Notable_people" not in ids
    assert set(ids) == {"History", "Geography", "Demographics"}


def test_build_considered_sections_empty_when_featured_is_article_level():
    """Featured passage has no #section_id → no featured article-and-
    section pair to anchor against. Return empty list."""
    capped_passages = [
        {"cite_id": "wiki/Big_Rapids,_Michigan", "text_markdown": "...", "rank": 1, "score": 1.0}
    ]

    def bundle_lookup(archive_name: str, entry_path: str) -> Any:
        return {"sections": [{"id": "History", "title": "History"}]}

    result = _build_considered_sections(capped_passages, bundle_lookup, max_n=10)
    assert result == []


def test_build_considered_sections_empty_when_no_passages():
    """Zero-hit response → no featured article → empty list."""
    result = _build_considered_sections([], lambda a, e: None, max_n=10)
    assert result == []


def test_build_considered_sections_caps_at_max_n():
    """A long article (20 sections) capped at max_n=10."""
    sections = [
        {"id": f"S{i}", "title": f"Section {i}"} for i in range(20)
    ]
    capped_passages = [
        {"cite_id": "wiki/Foo#S0", "text_markdown": "...", "rank": 1, "score": 1.0}
    ]

    def bundle_lookup(archive_name: str, entry_path: str) -> Any:
        return {"sections": sections}

    result = _build_considered_sections(capped_passages, bundle_lookup, max_n=10)
    assert len(result) == 10
    # S0 (featured) is excluded
    assert all(s["section_id"] != "S0" for s in result)


def test_synthesize_response_includes_considered_fields():
    """End-to-end check: synthesize_query returns a response that
    includes both new fields. Heavy mock-based test reusing the test
    fixtures from test_synthesize_title_promotion_v2a9.py style."""
    # This is a focused smoke test that verifies the fields are present
    # in the response shape. A full integration test would require live
    # ZIM fixtures, which are out of scope for unit tests.
    archive = MagicMock()
    search_handler = MagicMock()
    # Minimal hit: one search result, no title-index promotion.
    search_handler.search_top_k.return_value = [
        {"path": "Foo", "title": "Foo", "snippet": "snippet body", "score": 1.0}
    ]
    search_handler.title_match_hit.return_value = None
    cache = MagicMock()
    cache.get.return_value = None
    cache.set = MagicMock()
    content_processor = MagicMock()
    content_processor.html_to_plain_text.side_effect = lambda html: html

    # Patch the bundle build to return a minimal bundle with one section.
    with patch("openzim_mcp.synthesize._make_bundle_lookup") as mock_make:
        def fake_lookup(archive_name: str, entry_path: str) -> Any:
            return {
                "rendered_markdown": "snippet body",
                "sections": [
                    {"id": "Lead", "title": "Lead", "char_start": 0, "char_end": 100},
                    {"id": "Other", "title": "Other", "char_start": 100, "char_end": 200},
                ],
            }

        mock_make.return_value = fake_lookup

        response = synthesize_query(
            "foo",
            archives=[(archive, Path("/fake/wiki.zim"))],
            search_handler=search_handler,
            cache=cache,
            content_processor=content_processor,
            config=SynthesizeConfig(),
        )

    assert "considered_articles" in response
    assert "considered_sections" in response
    assert isinstance(response["considered_articles"], list)
    assert isinstance(response["considered_sections"], list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_synthesize_considered_handles.py -v`
Expected: FAIL — `_build_considered_articles` and `_build_considered_sections` do not yet exist.

- [ ] **Step 3: Implement the two helpers**

Add to `openzim_mcp/synthesize.py` near the response-assembly section (after `_build_citations`, around line 416):

```python
# ---------------------------------------------------------------------------
# A14: multi-round handle builders for SynthesizeResponse
# ---------------------------------------------------------------------------

_DEFAULT_CONSIDERED_ARTICLES_MAX = 3
_DEFAULT_CONSIDERED_SECTIONS_MAX = 10


def _featured_article_key(
    capped_passages: list[SynthesizePassage],
) -> Optional[tuple[str, str, Optional[str]]]:
    """Decompose the top capped passage's cite_id into (archive, entry_path,
    section_id). Returns None when there are no passages.

    Used to identify which article+section to exclude from the considered
    handles — the caller already sees the featured citation, so surfacing
    it again as a "consider this instead" is noise.
    """
    if not capped_passages:
        return None
    return _parse_cite_id(capped_passages[0]["cite_id"])


def _build_considered_articles(
    top_hits: list[tuple[str, dict]],
    capped_passages: list[SynthesizePassage],
    *,
    max_n: int = _DEFAULT_CONSIDERED_ARTICLES_MAX,
) -> list[Any]:
    """Top-N article hits NOT represented in capped_passages.

    Preserves the order from top_hits (which is post-promotion, post-
    demotion ranking). Each entry exposes (archive, entry_path, title,
    score) so the caller can pass it directly to get_zim_entries or
    compose a cite_id.
    """
    featured = _featured_article_key(capped_passages)
    featured_key: Optional[tuple[str, str]] = None
    if featured is not None:
        featured_key = (featured[0], featured[1])
    out: list[dict[str, Any]] = []
    for archive_name, hit in top_hits:
        entry_path = str(hit.get("path", ""))
        if not entry_path:
            continue
        if featured_key is not None and (archive_name, entry_path) == featured_key:
            continue
        out.append(
            {
                "archive": archive_name,
                "entry_path": entry_path,
                "title": str(hit.get("title", entry_path)),
                "score": float(hit.get("score", 0.0)),
            }
        )
        if len(out) >= max_n:
            break
    return cast("list[Any]", out)


def _build_considered_sections(
    capped_passages: list[SynthesizePassage],
    bundle_lookup: Callable[[str, str], Any],
    *,
    max_n: int = _DEFAULT_CONSIDERED_SECTIONS_MAX,
) -> list[Any]:
    """Sections of the featured passage's article, minus the featured
    section itself. Capped at max_n.

    Returns an empty list when:
      - There are no passages.
      - The featured passage has no #section_id (article-level
        citation — there's no "featured section" to anchor against).
      - The featured article's bundle lookup returns None or raises.
      - The bundle's section list is empty.
    """
    featured = _featured_article_key(capped_passages)
    if featured is None:
        return []
    archive_name, entry_path, featured_section_id = featured
    if not featured_section_id:
        return []
    try:
        bundle = bundle_lookup(archive_name, entry_path)
    except Exception as e:
        logger.debug(
            "considered_sections bundle lookup failed for %s/%s: %s",
            archive_name,
            entry_path,
            e,
        )
        return []
    if bundle is None:
        return []
    out: list[dict[str, Any]] = []
    for section in bundle.get("sections", []):
        section_id = str(section.get("id", ""))
        if not section_id or section_id == featured_section_id:
            continue
        out.append(
            {
                "section_id": section_id,
                "title": str(section.get("title", section_id)),
            }
        )
        if len(out) >= max_n:
            break
    return cast("list[Any]", out)
```

Wire into `synthesize_query` return (replace lines 1045-1058):

```python
    considered_articles = _build_considered_articles(top_hits, capped)
    considered_sections = _build_considered_sections(capped, bundle_lookup)
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
            "considered_articles": considered_articles,
            "considered_sections": considered_sections,
        },
    )
```

Also update `_zero_hits_response` ([search for its definition](openzim_mcp/synthesize.py) — Bash: `grep -n "def _zero_hits_response" openzim_mcp/synthesize.py`) to set both new fields to empty lists, keeping the response shape consistent.

- [ ] **Step 4: Find and update `_zero_hits_response`**

Run: `grep -n "_zero_hits_response\|def _zero" openzim_mcp/synthesize.py`

Add `considered_articles: []` and `considered_sections: []` to whatever dict it returns. Show the edit by adding to the returned dict literal.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_synthesize_considered_handles.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 6: Run the full synthesize test suite to verify no regression**

Run: `uv run pytest tests/test_synthesize.py tests/test_synthesize_title_promotion_v2a9.py tests/test_synthesize_meta_d7d8_v2a9.py tests/test_synthesize_section_affinity.py tests/test_synthesize_considered_handles.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add openzim_mcp/synthesize.py tests/test_synthesize_considered_handles.py
git commit -m "feat(v2): considered_articles + considered_sections in synthesize

Synthesize responses now surface the candidate space — top-3 article
hits not featured, top-10 sections of the featured article not picked
— so a follow-up turn can pivot via get_zim_entries / get_section
without re-running search. The featured citation's article and
section are excluded from these lists."
```

---

## Task 8: End-to-end smoke test against the motivating query

**Files:**
- Modify: `CHANGELOG.md` — add unreleased a14 entry
- No code changes; pure verification

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS. Watch for any pre-existing tests that depended on the M26 4-token short-circuit or the old `SynthesizeResponse` shape (`total=False` change) — update them inline if needed.

- [ ] **Step 2: Run mypy on the touched files**

Run: `uv run mypy openzim_mcp/synthesize.py openzim_mcp/simple_tools.py openzim_mcp/title_promotion.py openzim_mcp/tool_schemas.py openzim_mcp/config.py`
Expected: No new errors.

- [ ] **Step 3: Run the linter / formatter**

Run: `uv run black --check openzim_mcp/ tests/ && uv run isort --check-only openzim_mcp/ tests/`
Expected: PASS. If any formatting drift, run `uv run black openzim_mcp/ tests/ && uv run isort openzim_mcp/ tests/` and re-commit.

- [ ] **Step 4: Add an unreleased CHANGELOG entry**

Read the existing `CHANGELOG.md`, find the unreleased section (or create one above the most recent `## [X.Y.Za<N>]` header following the same format), and add:

```markdown
## [Unreleased]

### Added

- `zim_query` natural-language search-engine path: prose-shaped queries
  like *"who are some famous people from big rapids, michigan"* now
  resolve to the canonical entity (`Big_Rapids,_Michigan`) via greedy
  length-down tail iteration in both default and `synthesize=True`
  modes (`iter_query_tails` shared helper in `title_promotion`).
- `synthesize=True` responses: section-heading affinity boost re-ranks
  section-attributed passages so the *Notable people* section of a
  city article leads when the query mentions "people". Tunable via
  `SynthesizeConfig.section_affinity_threshold` (default 0.25) and
  `section_affinity_boost` (default 1.5).
- `synthesize=True` responses: new `considered_articles` and
  `considered_sections` fields expose the candidate space for
  multi-round refinement without re-running search.

### Changed

- Removed the 4-token short-circuit in `_promote_title_match`
  (M26). Long prose queries with a clear entity tail now resolve
  canonically instead of falling through to BM25 noise.
- `SynthesizeResponse` TypedDict is now `total=False` to accommodate
  the new optional fields. Existing callers populating all the
  previously-required fields are unaffected.
```

- [ ] **Step 5: Commit the CHANGELOG entry**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): a14 search-engine zim_query path"
```

- [ ] **Step 6: Live beta-test sweep (manual, against the 118 GB Wikipedia ZIM)**

This step is **manual** and follows the [a-series beta-testing methodology](../../v2/README.md). It is NOT scripted into the implementation plan; it runs after the alpha is cut.

Test set (from the spec's testing section):

- Motivating: `zim_query("who are some famous people from big rapids michigan")` — verify the response leads with Big_Rapids,_Michigan content. In `synthesize=True`, verify `citations[0].section_id == "Notable_people"` (or whatever the bundle calls it; check `considered_sections` for the actual heading list).
- Wikipedia question-shape battery: *"history of Detroit"*, *"geography of Iceland"*, *"economy of Vietnam"*, *"notable people from Big Rapids"*, *"famous residents of Detroit"*. Verify section targeting.
- Cross-article: *"jazz musicians from Detroit"*, *"WWII battles in Africa"*. Verify `considered_articles` surfaces useful pivots.
- Regression on existing adversarial set: single-word topics, politeness-tail variants, canonical-with-disambig-twin (Berlin, Tokyo, Mercury, Apollo 11), single-edit typos, chained-intent queries. Confirms no regression from the 4-token short-circuit removal.
- Non-Wikipedia archive if available — Stack Exchange or Wikitravel ZIM with a question whose answer is in a known section. Verify the affinity boost matches against *that archive's* section vocabulary.

Findings cycle back as new unit tests in subsequent commits, per the a8 → a13 pattern.

---

## Spec Coverage Check

| Spec section | Task(s) |
|---|---|
| Change A₀ (shared `iter_query_tails`) | Task 2 |
| Change A₁ (synthesize tail probe) | Task 4 |
| Change A₂ (tell_me_about tail probe) | Task 3 |
| Change B (section affinity) | Task 1 (config), Task 5 (logic) |
| Change C (`considered_*`) | Task 6 (schema), Task 7 (population) |
| "Why no stopword strip" — design rationale | Implemented as the absence of any stopword strip in Tasks 2, 3, 4, 5. Affinity tokens come straight from `_AFFINITY_TOKEN_RE.findall(text)` with no removal pass. |
| Default-mode vs synthesize-mode coverage | Task 3 (default), Tasks 4–7 (synthesize) |
| Edge cases: no entity / no heading match / no section / non-English | Covered by tests in Tasks 2, 3, 4, 5, 7 |
| Performance bound | Task 8 step 1 (full test suite); not separately measured (implementation cost is sub-millisecond per the spec's analysis) |
| Live beta-test sweep | Task 8 step 6 (manual) |

## Open Items For Implementation

- **`Iterator` import in `title_promotion.py` (Task 2):** the file may already import from `typing`; verify and merge into the existing import block.
- **`_zero_hits_response` shape (Task 7 step 4):** the implementer needs to find and update this helper. The grep command is provided.
- **`tests/test_tool_schemas.py` existence (Task 6):** the implementer should check whether the file exists. If not, create it with a minimal header and the one new test.
- **Pre-existing M26 short-circuit test (Task 4 step 1):** if `tests/test_synthesize_title_promotion_v2a9.py` has a test that explicitly asserts the 4-token short-circuit behavior, it needs to be deleted or rewritten to assert the new tail-probe behavior. The implementer should grep for "M26" or "4-token" in the test file before starting.
