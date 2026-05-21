# v2 Phase D sub-D-2 — Tier 1 Query Rewriting Design

> Refines the Phase D umbrella spec ([2026-05-20-v2-phase-d-ml-accelerators-design.md](2026-05-20-v2-phase-d-ml-accelerators-design.md), § Sub-D-2) with decisions surfaced by sub-D-1's implementation. Reconciles the design with what's actually shippable in this codebase.

**Status:** Approved for implementation
**Predecessor:** sub-D-1 cross-encoder reranker (shipped 2026-05-20, PR #163, squash commit `023a05c`)
**Release target:** `v2.0.0b1` — first b-series release (sub-D-1 shipped in the a-series; sub-D-2 cuts over to b)

---

## Goal

Lift the query-relevance floor for every search and synthesize call by running four rule-based rewrites before any pattern matching. Zero new dependencies, base install only, no opt-in extras. Every downstream pipeline — Xapian search, intent regex chain, the sub-D-1 reranker — inherits a cleaner query.

The four rules:

1. **Lowercase topic normalization** — pull scattered `.lower()` calls into a named pass.
2. **Misspelling map** — `dict[str, str]` lookup with a title-index probe gating false positives.
3. **Stopword phrase detection** — strip leading articles unless the article is part of a real title (`The Beatles`).
4. **"X of Y" decomposition** — emit a structured `(entity, attribute)` hint AND a cleaner query string.

---

## Why this design

**Why rules, not a model.** A cross-encoder reranker (sub-D-1) corrects ranking after Xapian. Tier 1 query rewriting corrects the *input* to Xapian. Both passes are cheap and additive. Rules-based rewriting is the right tool here because the failure modes (typos, leading articles, paraphrased questions) have known shapes; a model would buy noise.

**Why the base install.** sub-D-2 adds no dependency. Every user — including the base `pip install openzim-mcp` — gets the lift on the next release. No opt-in friction.

**Why the title-index probe.** A naive misspelling map silently rewrites real proper nouns. `Bilogy` is in the Wikipedia misspelling list but is also a surname. The title-index probe checks "does the original token already canonically resolve?" and skips the rewrite when it does. Same probe gates stopword-article stripping (`The Beatles` is a title; `the population of Berlin` is not).

**Why not HyDE, fastText, embeddings.** Explicit non-goals for Tier 1. They belong in later sub-Ds if live evidence justifies them. Tier 1 is the cheapest meaningful lift; ship it and measure.

---

## Architecture

All four rules live in `openzim_mcp/intent_parser.py` (existing, ~1345 lines), extending the established `_strip_*` chain pattern.

```
SimpleToolsHandler.handle_zim_query(query, ...)
    ↓
    IntentParser.parse_intent(query, *, title_probe=None)
        ↓
        # Tier 1 rewrites — new for sub-D-2 —
        _normalize_topic_case(query)                  # rule 1 — no probe
        _apply_misspelling_map(query, title_probe)    # rule 2 — needs probe
        _detect_stopword_phrase(query, title_probe)   # rule 3 — needs probe
        _decompose_x_of_y(query)                      # rule 4 — no probe
        ↓
        # Existing regex chain — unchanged —
        _strip_param_leaks(...)
        _strip_trailing_politeness(...)
        ... etc ...
        ↓
        IntentResult(
            tool="...",
            params={...},
            decomposition_hint=Optional[Dict[str, str]],  # populated by rule 4
        )
```

**Ordering rationale:** lowercase first (cheapest, no dependencies), then per-token fixes (misspellings — needs lowercased tokens), then phrase-level (stopword leading article), then decomposition (extracts structured fields from the now-clean query). Each rule is idempotent; rerunning produces no further change, so we don't use the loop pattern from `_strip_*`.

### Title-index probe contract

```python
TitleProbe = Callable[[str], Optional[float]]
```

Returns the highest title-match score for the given token (range `[0.0, 1.0]`), or `None` if the index is unavailable. Callers pass `None` (the default) when no archive is in scope — rules 2 and 3 then degrade to **non-probing mode** described below.

The probe is supplied by `SimpleToolsHandler` from a lightweight closure over `zim_operations`:

```python
def _title_probe(token: str) -> Optional[float]:
    # ~1 ms cached call against the title index
    ...

result = self.intent_parser.parse_intent(query, title_probe=_title_probe)
```

**Probe-degraded modes** (when `title_probe is None`):
- Rule 2 (misspellings): substitute without probing. Higher false-positive risk; relies on a tight curated list + the explicit exclusions file.
- Rule 3 (stopword phrase): **strip the leading article**. Favors the cleaner query when ambiguity can't be resolved. Operators who depend on title-preservation should run with an archive in scope or pin `enabled=False` on this rule.

### Module structure

```
openzim_mcp/intent_parser.py
    # Existing class IntentParser, extended with 4 new methods.

openzim_mcp/data/misspellings.txt          # new — ~30-50 starter entries
openzim_mcp/data/misspellings_exclusions.txt  # new — empty seed; grows reactively

openzim_mcp/config.py
    # QueryRewriteConfig added; composed onto OpenZimMcpConfig.query_rewrite

tests/test_query_rewrite_tier1.py          # new — per-rule + composition tests
```

Data files ship inside the package (`include_package_data` in `pyproject.toml` if not already configured). Loaded once at `IntentParser.__init__` via a module-level `@functools.lru_cache` helper so repeated `IntentParser()` instantiation doesn't re-read the file.

---

## The four rules in detail

### Rule 1 — `_normalize_topic_case(query: str) -> str`

Lowercase the topic portion of the query (the noun phrase after intent words like `tell me about`, `what is`, `search for`). Mostly consolidates scattered `.lower()` calls into a named pass.

- **No telemetry event.** Fires on essentially every query; zero signal for tuning.
- **Idempotent.** Trivially.
- **No probe.**

### Rule 2 — `_apply_misspelling_map(query: str, title_probe: Optional[TitleProbe]) -> str`

Tokenize on whitespace. For each token, lowercase-lookup in the misspellings dict. Substitute when:
- Token IS in `misspellings` map
- AND token is NOT in `exclusions` set
- AND (`title_probe is None` OR `title_probe(token) < 0.95`)

Otherwise, leave token unchanged.

- **Telemetry:** `query_rewrite.misspelling` on any substitution within the query (counts queries, not tokens).
- **Idempotent.** A corrected word is never itself a key in the map.
- **Probe:** optional; degraded mode = substitute without probing.

**Misspelling list seeding:**
- Ship ~30-50 high-confidence entries seeded from [Wikipedia's "List of common misspellings (for machines)"](https://en.wikipedia.org/wiki/Wikipedia:Lists_of_common_misspellings/For_machines).
- Selection criteria: (a) unambiguously a typo (not regional like `colour`/`color`); (b) observed in past beta-test sweeps OR clearly relevant to encyclopedia content (`Wikipedia`, `Tuesday`, `Photosynthesis`, `Mediterranean`, `independent`, etc.).
- File header annotates the upstream URL + revision timestamp so future maintainers can re-pull and diff.
- Exclusions file (`misspellings_exclusions.txt`) seeded **empty**. Grows reactively when a real proper noun gets misrouted — add the original token, ship a patch release.
- Hard cap at 500 entries to keep the lookup cheap and the file reviewable.

### Rule 3 — `_detect_stopword_phrase(query: str, title_probe: Optional[TitleProbe]) -> str`

If query starts with `the |a |an |of ` (case-insensitive), decide whether the article belongs:
- If `title_probe is not None` AND `title_probe(query) >= 0.95` → keep article. Title is a real entity (`The Beatles`, `Of Mice and Men`).
- Otherwise → strip the leading article.

One probe per query maximum. The probe checks the FULL query (not just the article-stripped form), because we want to confirm the version-with-article is a canonical title.

- **Telemetry:** `query_rewrite.stopword_phrase` on strip.
- **Idempotent.** Stripping a leading article doesn't introduce a new leading article.
- **Probe:** optional; degraded mode = strip without probing (favors cleaner query).

### Rule 4 — `_decompose_x_of_y(query: str) -> Tuple[str, Optional[Dict[str, str]]]`

Two regex shapes (case-insensitive, applied in order):
- `^(?P<attr>\w+) of (?P<entity>.+)$` — `population of Berlin` → `entity=Berlin, attr=population`
- `^(?P<entity>\w+)'s (?P<attr>\w+)$` — `Berlin's population` → `entity=Berlin, attr=population`

Output is a TUPLE:
- Rewritten query string: `Berlin population` (cleaner for any downstream that reads the text).
- `decomposition_hint` dict: `{"entity": "Berlin", "attribute": "population"}` if a regex matched, else `None`.

`parse_intent` attaches the hint to the returned `IntentResult`. `_handle_tell_me_about` reads `result.decomposition_hint` first; if absent, falls back to its existing extraction (the post-a16 P4-D1/P6-D1 hardened path).

- **Telemetry:** `query_rewrite.x_of_y` on match.
- **Idempotent.** A rewritten `Berlin population` no longer matches either regex.
- **No probe.**

**Explicitly NOT in Tier 1:**
- Multi-hop questions (`what year did the inventor of X die`). Deferred to a potential sub-D-3 if evidence warrants.
- HyDE (hypothetical document synthesis). Locked-in non-goal.
- Algorithmic spell correction (`pyspellchecker`/`autocorrect`/`symspellpy`). Wrong precision/recall tradeoff for encyclopedia search; the curated map + probe is the right tool.

---

## Configuration

```python
class QueryRewriteConfig(BaseModel):
    enabled: bool = Field(
        default=True,
        description="Master switch. False short-circuits all four rules.",
    )
    misspelling_map_path: Path | None = Field(
        default=None,
        description="Override the bundled misspellings.txt path. None = use bundled default.",
    )
    misspelling_exclusion_path: Path | None = Field(
        default=None,
        description="Override the bundled exclusions list path. None = use bundled default.",
    )
    stopword_phrase_probe: bool = Field(
        default=True,
        description=(
            "Allow rule 3 to call the title-index probe. False skips the probe "
            "and never strips the leading article (preserves titles like "
            "'The Beatles' but loses cleanup on `the population of Berlin`)."
        ),
    )
```

Composed onto `OpenZimMcpConfig` as `query_rewrite: QueryRewriteConfig = Field(default_factory=QueryRewriteConfig)`.

Env-var overrides follow the existing `OPENZIM_MCP_QUERY_REWRITE__*` pattern.

---

## Telemetry

Three events via the existing `_track()` mechanism on `SimpleToolsHandler` ([simple_tools.py:137-150](../../openzim_mcp/simple_tools.py#L137-L150)):

| Event | Fires when |
|---|---|
| `query_rewrite.misspelling` | Rule 2 substituted at least one token |
| `query_rewrite.stopword_phrase` | Rule 3 stripped a leading article |
| `query_rewrite.x_of_y` | Rule 4 matched either regex shape and emitted a hint |

Rule 1 has no event (fires on essentially every query; zero signal).

Surfaced via the existing `get_server_health` tool. Process-local, no remote sink — same constraint as sub-D-1's `reranker_*` events. Operators read counts via `get_server_health` calls.

**PII safety:** event names carry no query content. Same contract as the spec's original "without printing rewritten text" requirement.

---

## Testing

`tests/test_query_rewrite_tier1.py` — new file.

### Per-rule unit tests

Each rule gets parametrized test cases covering three sides:

1. **Fix side** — input that SHOULD rewrite (`bilogy` → `biology`).
2. **No-op side** — already-correct input passes through unchanged (`biology` → `biology`).
3. **Boundary side** — edge cases that look like rewrite targets but shouldn't be (the title-probe-blocked case for rule 2; the canonical-title case for rule 3).

For rules 2 and 3, parametrized tests with a mocked `title_probe` covering: probe-returns-high-score (suppress rewrite), probe-returns-low-score (allow rewrite), probe-is-None (degraded mode).

### Composition tests

Quick pairwise tests confirming rule ordering produces stable outputs:
- Rule 1 + 2: `Bilogy is interesting` → `biology is interesting`
- Rule 2 + 4: `populaton of Berlin` → `Berlin population` with hint
- Rule 3 + 4: `the population of Berlin` → `Berlin population` with hint

Not full N×M composition — just enough to lock in the order matters.

### Rule-4 hint round-trip

`_handle_tell_me_about` test: when `IntentResult.decomposition_hint` is present, the handler uses it and skips its existing extraction. When absent, the handler's existing path runs unchanged.

### Regression baseline

Full existing `tests/test_post_a*_beta_fixes.py` suite (~90+ tests across 5+ sweep cycles) runs UNCHANGED. If anything regresses, sub-D-2 doesn't ship — the rule-based rewrites are supposed to be additive lift, not behavior breakage.

### Live MCP smoke

Pre-merge sweep follows the established methodology (see [project_a_series_beta_testing memory](../../../../.claude/projects/-Volumes-rye-Developer-openzim-mcp/memory/project_a_series_beta_testing.md)):
- Two-pass adversarial probing on a live MCP server with the new build
- Pass 1: probe each of the four rules with known-good and known-tricky inputs
- Pass 2: cross-feature integration (rewrite + reranker, rewrite + synthesize) to confirm no interactions break

---

## Risk mitigations

**1. Behavior changes on upgrade for every user.**
- Every existing regression test passes UNCHANGED (no rule should alter behavior on already-correct queries).
- The live MCP smoke pass is the final gate. Same methodology that caught 6 defects in the post-a24 sweep ([memory](../../../../.claude/projects/-Volumes-rye-Developer-openzim-mcp/memory/project_a_series_beta_testing.md)).
- Rules 1 and 4 are pure functions, easy to unit-test exhaustively. Rules 2 and 3 are gated by the title probe in archive-aware mode.

**2. Misspelling-map false positives (silent rewrite of real proper nouns).**
- Title-index probe (default ON) suppresses rewrites for canonical hits.
- Explicit exclusions file ships empty; operators add entries when reactive false-positives are observed.
- Start small (~30-50 entries) rather than bulk-importing the full Wikipedia list. Conservative coverage; precision over recall.

**3. Probe latency on high-volume deployments.**
- Rule 2 probes at most once per token; rule 3 probes at most once per query.
- Both probes are ~1 ms and hit the existing title-index cache.
- `stopword_phrase_probe = False` is an operator kill switch for rule 3.
- `enabled = False` is the master kill switch.

**4. Rule-order interactions.**
- Composition tests pin pairwise outcomes.
- All four rules are idempotent so re-running doesn't introduce bugs; the chosen order optimizes for "earlier rules clean input for later rules" (lowercase before per-token lookups, per-token before phrase-level).

**5. Misspelling list maintenance burden.**
- File header annotates upstream Wikipedia URL + revision timestamp.
- "Grow reactively" policy: add entries only when a sweep observes the misspelling. Hard cap at 500 entries.
- Exclusions file documents real proper nouns that shadow misspellings. Grows similarly.

---

## Release timing

- **Target release:** `v2.0.0b1` — first b-series release.
- **Pre-merge gate:** live MCP smoke pass (same methodology as post-a24 sweep).
- **No 2-week telemetry wait before sub-D-2.** Per the discussion that closed sub-D-1 ([PR #163](https://github.com/cameronrye/openzim-mcp/pull/163)), telemetry stays in-memory with no remote sink — the wait can't gather field data because there's no field. Sub-D-2 ships as soon as it passes the smoke pass.

---

## Non-goals (locked in)

- HyDE / hypothetical document synthesis. Permanent non-goal.
- Algorithmic spell-correction libraries (`pyspellchecker`, `autocorrect`, `symspellpy`). Wrong tradeoff for this use case.
- Multi-hop question decomposition (`what year did the inventor of X die`). Deferred to sub-D-3 if evidence warrants; not in Tier 1.
- Embeddings sidecar. Deferred at the Phase D level (#15 in the umbrella spec); revisit only if sub-D-1 reranker hit rate is ≥15% AND operators report semantic-divergent misses.
- Hybrid intent parser (#12). Deferred at the Phase D level; trigger conditions documented in the umbrella spec.

---

## Out of scope (future sub-Ds)

| Item | Trigger to re-open |
|---|---|
| Multi-hop decomposition | Live evidence of repeated `<X> of <inventor of Y>` shaped queries failing |
| fastText classifier path | Live telemetry shows ≥5% of `parse_intent` calls hitting the low-confidence branch |
| Embeddings sidecar | Operator-reported semantic-divergent misses with reranker engaged at ≥15% rate |

8-week silent window: if no trigger fires within 8 weeks of sub-D-2 deploy, formally close each deferred item as "not justified by live evidence."

---

## Self-review

**Placeholder scan:** No TBDs, no TODOs. Every rule has a defined input, output, and edge-case behavior.

**Internal consistency:** Rule ordering matches the architectural diagram. Telemetry events match the testing assertions. Config field names match the design table.

**Scope check:** Four rules, one new file (`tests/test_query_rewrite_tier1.py`), two new data files, modifications to two existing files (`intent_parser.py`, `config.py`). Fits a single implementation plan. No further decomposition needed.

**Ambiguity check:**
- "Topic portion of query" in rule 1: needs the plan to specify which slice of the query is the "topic" (probably whatever the existing `.lower()` calls operate on — discover during implementation).
- "Highest title-match score" in the probe contract: needs the plan to specify the exact `zim_operations` method that produces this score. Documented as a plan-level decision.
- Both items are implementation details, not design ambiguities — flagged for the writing-plans skill.
