# v2 Phase F — Tool Surface Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the 22-tool advanced MCP surface to 8, clearing the [MCP Tax](https://www.mmntm.net/articles/mcp-context-tax) pain band (25–50KB schema) for small-model dispatch, while protecting against regressions via a four-stage release (Gate 0 transport check → rc0 refactor → Gate 0.3 small-model parsing + Gate 0b dispatch eval against prototype skeletons → rc1 surface). Pass criteria: A (dispatch), B (parameter-validity), C1/C2/C3 (dispatch-confusion ceilings — ALL re-checked on fallback cell if wired path fails C), D (8-tool-vs-22-tool non-regression), F1 (per-class non-regression at 8pp for hardened b-series classes), F2 (per-class non-regression at 10pp for new Phase F classes — enforced at BOTH Gate 0b AND Stage E to catch prototype-to-rc1 regressions). Qwen-2.5-7B-Instruct is the primary (100% of cells, target population); Haiku-4.5 is the Anthropic-family secondary (50%, VETO on A/B/D/C at 10pp); Llama-3.1-8B-Instruct is the architecturally-distinct ~8B-class open-weights tertiary (50%, VETO on A/B/D/C at 10pp); Phi-3.5-mini-instruct (3.8B) is the sub-7B-class open-weights quaternary (50%, VETO on A/B/D/C at 10pp — matched to tertiary; sub-4B variance handled via reps=5 rather than wider margin, because the sub-4B size class is the deployment population most at risk from the surface change).

**Architecture:** Four ship vehicles in sequence. (0) **Gate 0 — 2 sub-gates.** Gate 0.1: `oneOf` emission spike. Gate 0.2: transport round-trip verification on stdio + HTTP. Each sub-gate has a pre-decided STOP path that triggers a spec amendment to flat-schema-plus-prose. **Gate 0.3 (small-model `oneOf`-parsing benchmark) moves to Stage B**, after the prototype skeletons exist, so it measures the actual production schemas rc1 will ship — not synthetic stand-ins. (1) `v2.0.0rc0` — extract `_promote_topic_via_title_index` from `SimpleToolsHandler` to a module-level function in new `openzim_mcp/topic_preprocessing.py`, diff-tested against the b1 → b13 cumulative probe set. (2) Gate 0.3 + Gate 0b — Qwen-7B (primary, 100% of cells), Haiku-4.5 (secondary, 50%), Llama-8B (tertiary, 50%), Phi-3.5-mini (quaternary, 50%, sub-7B size class) dispatch eval against a prototype branch wiring the 8-tool surface using the same type-signature pattern Gate 0.1 selected. Pre-decided Criterion C circuit-breaker (legibility framing — fallback to explicit-string title mode if dispatch-confusion exceeds any of C1/C2/C3; **all of C1/C2/C3 are re-checked on the fallback cell** to confirm the legibility fix actually changes routing and doesn't introduce new confusion). (3) `v2.0.0rc1` — implements the 8 per-tool modules with schema-conditional `oneOf` (or flat schemas, per Gate 0 outcome); a prototype↔rc1 schema parity test blocks merge if rc1's per-tool wire footprint drifts beyond ±5% of what the prototype measured. Stage E stabilization sweep runs against the FULL b1 → b13 probe set with all four models (Haiku/Llama at reps=3 for matched power; Phi at reps=5 because its 10pp veto on the sub-4B size class would otherwise be strictly weaker than the same margin on 8B-class secondaries) AND re-runs the Gate 0b 300-probe set to enforce F2 at Stage E (catches the prototype-to-rc1 rewrite as the riskiest moment for localized per-class regressions).

**Tech Stack:** Python 3.12+, FastMCP, pytest, Pydantic v2, libzim 3.9.0, Qwen-2.5-7B-Instruct via vLLM or llama.cpp (Gate 0.3 + Gate 0b primary, 100% of cells), Anthropic SDK with Haiku-4.5 (Gate 0b secondary, 50% of cells), Llama-3.1-8B-Instruct via vLLM (Gate 0b tertiary, 50% of cells), Phi-3.5-mini-instruct via vLLM (Gate 0b quaternary, 50% of cells; documented fallback to Qwen-2.5-3B-Instruct if vLLM's `pythonic` parser is flaky for Phi in the deployer's vLLM version).

**Spec:** [`docs/superpowers/specs/2026-05-24-v2-phase-f-tool-surface-design.md`](../specs/2026-05-24-v2-phase-f-tool-surface-design.md).

---

## File Structure

### New files

**rc0:**

- `openzim_mcp/topic_preprocessing.py` — module-level `promote_topic_via_title_index(zim_operations, zim_file_path, topic, ...)` AND `auto_select_zim_file(zim_operations)` extracted from `SimpleToolsHandler`. Both are needed by `zim_search` at rc1.
- `tests/test_topic_preprocessing.py` — unit tests for the extracted module (covers both functions).
- `tests/dispatch_eval/__init__.py` — package marker.
- `tests/dispatch_eval/test_promotion_extraction_parity.py` — Gate 0a diff-test (promotion).
- `tests/dispatch_eval/test_auto_select_extraction_parity.py` — Gate 0a diff-test (auto-archive-select).
- `tests/dispatch_eval/test_preprocessing_extraction_parity.py` — Gate 0a diff-test (preprocessing orchestration).
- `tests/dispatch_eval/data/b1_b13_probes.jsonl` — cumulative b-series probe set.

**Gate 0b infrastructure (lands on `v2-phase-f-prototype`, not merged):**

- `tests/dispatch_eval/probes.jsonl` — 300-probe gold-labeled set.
- `tests/dispatch_eval/baselines/b13.json` — committed b13 baseline run.
- `tests/dispatch_eval/runner.py` — boots MCP server with a chosen surface variant, drives the model, records per-probe outcomes.
- `tests/dispatch_eval/analyze.py` — non-inferiority tests + spurious-routing computation + decision rule rendering.
- `tests/dispatch_eval/gate_0b_decision.json` — committed gate outcome. Top-level keys: `gate_passed`, `default_tool_mode` (always `"simple"`), `criterion_c_path` (`"wired"` or `"fallback"`), `gate_0_schema_shape` (`"wired_oneof"` or `"flat"`), `gate_0_3_verdict` (`"validated"`, `"unvalidated"`, or `"failed"`), `secondary_status` / `tertiary_status` / `quaternary_status` (each `"available"` or `"unavailable"`), `quaternary_model_substituted` (only present if Phi → Qwen-3B substitution was taken — string like `"qwen-2.5-3b-instruct"`), `secondary_blocking_failures` / `tertiary_blocking_failures` / `quaternary_blocking_failures` (lists), `secondary_observational_failures` / `tertiary_observational_failures` / `quaternary_observational_failures` (lists), `fallback_c1_pass` / `fallback_c2_pass` / `fallback_c3_pass` (each `null` if wired path passed C and fallback didn't run, `true`/`false` otherwise; `fallback_c2_pass` may also be `null` if the fallback cell's confusion-conditional subset had <10 events — hand-audit required), `scope_limitations` (list of strings making the gate's measurement bounds machine-readable — see [spec §scope_limitations field](../specs/2026-05-24-v2-phase-f-tool-surface-design.md#gate-0b-pre-rc1--dispatch-eval-against-prototype-branch)), `criteria` (nested object — A/B/D record `primary`/`secondary`/`tertiary`/`quaternary` verdicts and per-cell deltas; C1/C2/C3 record rate + events count; F1/F2 record `per_class_deltas`).
- `tests/dispatch_eval/prototype_schema_snapshot.json` — per-tool snapshot captured from the prototype skeletons (`bytes`, `description` prose, and `inputSchema` per tool). Cherry-picked into rc1 and consumed by `tests/test_phase_f_prototype_parity.py` to enforce the ±5% byte budget + structural inputSchema identity + ≤30% Levenshtein edit distance on the description text.

**rc1:**

- `openzim_mcp/tools/zim_query.py`
- `openzim_mcp/tools/zim_search.py`
- `openzim_mcp/tools/zim_get.py`
- `openzim_mcp/tools/zim_get_section.py`
- `openzim_mcp/tools/zim_browse.py`
- `openzim_mcp/tools/zim_metadata.py`
- `openzim_mcp/tools/zim_links.py`
- `openzim_mcp/tools/zim_health.py`
- `tests/test_phase_f_schema_budget.py` — total + per-tool byte cap, reads `gate_0b_decision.json` at build time.
- `tests/test_phase_f_schema_shapes.py` — asserts `oneOf` branch structure on `zim_get` and `zim_search`.
- `tests/test_phase_f_schema_bypass.py` — wire-level invalid-payload defense-in-depth tests.
- `tests/test_phase_f_migration_conformance.py` — synthetic-client conformance over every row in the v1 → v2 migration table.
- `tests/test_phase_f_gate_decision_consistency.py` — cross-checks rc1 commit artifacts against the gate decision file.
- `tests/test_phase_f_prototype_parity.py` — three-axis parity: per-tool wire footprint within ±5% bytes of the prototype's snapshot, `inputSchema` shape structurally identical (oneOf branches, parameter names, types, enum values), AND per-tool description within ≤30% Levenshtein edit distance of the prototype's prose. The edit-distance check catches prose rewrites that fit inside the byte budget but change the dispatch signal Gate 0b measured.
- `tests/test_zim_*.py` — per-tool tests (8), restructured from existing per-tool test files.

### Modified files

**rc0:**

- `openzim_mcp/simple_tools.py` — `_promote_topic_via_title_index` AND `_auto_select_zim_file` both become thin delegating wrappers around the extracted module-level functions.
- `tests/conftest.py` — add `--dispatch-eval` opt-in flag + auto-skip for `dispatch_eval/*` tests (Task A1 Step 2).
- `docs/v2/README.md` — Phase F row to `In Design`.

**rc1:**

- `openzim_mcp/server.py` — replace `_register_simple_tools` + `register_all_tools` with single `register_phase_f_tools`; make `simple_tools_handler` initialization unconditional (Task D11 Step 2).
- `openzim_mcp/config.py:293` — stale docstring (21 → 8 tools, simple/advanced reframed).
- `openzim_mcp/async_operations.py` — add `get_health_data` (combined health+config+archives) and `get_archive_metadata_data` (combined metadata+namespaces).
- `openzim_mcp/tool_schemas.py` — add `ArchiveMetadataResponse`, enriched `ServerHealthResponse`; preserve all existing types.
- `openzim_mcp/tools/__init__.py` — `register_phase_f_tools(server)` entry point.
- `pyproject.toml` — add `*.md` to `tool.setuptools.package-data` so `zim_query_description.md` ships in the wheel (Task D3 Step 3).
- `CHANGELOG.md` — migration table + default-behavior-changes sub-section.

### Deleted files (rc1)

- `openzim_mcp/tools/content_tools.py`
- `openzim_mcp/tools/file_tools.py`
- `openzim_mcp/tools/metadata_tools.py`
- `openzim_mcp/tools/navigation_tools.py`
- `openzim_mcp/tools/search_tools.py`
- `openzim_mcp/tools/server_tools.py`
- `openzim_mcp/tools/structure_tools.py`

`openzim_mcp/tools/prompts.py` and `openzim_mcp/tools/resource_tools.py` survive untouched.

### Boundary discipline

- One file per tool under `openzim_mcp/tools/`. No domain-grouped files.
- `topic_preprocessing.py` is a sibling helper, not under `tools/`.
- `tests/dispatch_eval/` is excluded from default `pytest` runs (paid API calls; manual invocation only).

---

## Stage 0 — Architecture Verification (2 sub-gates, PRE-rc0)

**Goal:** Verify that (Gate 0.1) FastMCP can emit `oneOf` at all from at least one available registration pattern AND (Gate 0.2) the production MCP transports preserve `oneOf` round-trip. Either failure triggers a pre-decided STOP-AMEND-SPEC path.

**Gate 0.3 (small-model `oneOf`-parsing benchmark) is deferred to Stage B**, after the prototype skeletons exist. The earlier draft ran Gate 0.3 against synthetic schemas "modeled on" the production tools; the spec now requires Gate 0.3 to measure the actual production shapes the prototype skeletons emit. See Task B2a.

**Branch plan.** Stage 0 work lands on `v2-phase-f-gate-0`, gets reviewed and merged to `main` BEFORE Stage A creates `v2-phase-f-rc0` from `main`.

**Sub-gate ordering (cheapest-first):**

1. **Gate 0.1 first.** Fails the design fast if FastMCP can't emit `oneOf` at all. If it fails, skip Gate 0.2 entirely.
2. **Gate 0.2 second.** Only run if Gate 0.1 passed. Verifies the schema survives transport.

### Task Z0: Create `v2-phase-f-gate-0` branch

- [ ] **Step 1: Create branch from main**

```bash
git checkout main
git pull
git checkout -b v2-phase-f-gate-0
```

- [ ] **Step 2: Add the GitHub label if it doesn't already exist**

```bash
gh label create v2-phase-f --description "v2 phase F: tool surface consolidation" --color C5DEF5 2>/dev/null || true
```

### Task Z0a: Gate 0.1 — `oneOf` emission spike

**Files:**

- Create: `tests/dispatch_eval/gate_0_1_emission_spike.py` (throwaway probe — committed for reproducibility but never run in CI)
- Create: `tests/dispatch_eval/gate_0_1_emission_spike.md` (record of outcome)

**Goal:** before committing to the Gate 0.2 transport verification, prove that FastMCP can emit `oneOf` *at all* from one of the available registration patterns.

- [ ] **Step 1: Write the spike script** — tries three FastMCP registration patterns (Pattern A: Literal-gated type signature, Pattern B: explicit `inputSchema=` override, Pattern C: Pydantic discriminator field) and dumps `tool.parameters` for each. Looks for the literal substring `"oneOf"` in the in-memory dump.

- [ ] **Step 2: Run it**

```bash
python tests/dispatch_eval/gate_0_1_emission_spike.py | tee /tmp/gate_0_1.json
```

- [ ] **Step 3: Write the verdict record** in `tests/dispatch_eval/gate_0_1_emission_spike.md`:

```markdown
# Gate 0.1 — `oneOf` emission spike

**Date run:** <ISO date>
**FastMCP version:** <from `pip show fastmcp`>

## Pattern results

<paste the JSON output>

## Verdict

One of:
- **PROCEED-TO-GATE-0.2** — At least one pattern produces `oneOf` in-memory. Patterns that worked: <list>. Use the first working pattern as the rc1 production pattern.
- **STOP-AMEND-SPEC (NO-ONEOF-EMISSION)** — Zero patterns produce `oneOf`. Skip Gate 0.2 and Gate 0.3. Open the spec-amendment PR immediately (flat-schema design).
```

- [ ] **Step 4: Commit and decide**

```bash
git add tests/dispatch_eval/gate_0_1_emission_spike.py tests/dispatch_eval/gate_0_1_emission_spike.md
git commit -m "test(gate-0.1): oneOf emission spike (verdict: <VERDICT>)"
```

If verdict is STOP-AMEND-SPEC, skip Task Z1 and go directly to Task Z2 with the STOP verdict. Otherwise proceed to Task Z1. (Gate 0.3 is no longer a Stage 0 sub-gate — it runs in Stage B against the actual prototype skeletons; see Task B2a.)

### Task Z1: Gate 0.2 — `oneOf` transport round-trip verification

**Files:**

- Create: `tests/dispatch_eval/check_transport.py`
- Create: `tests/dispatch_eval/transport_oneof_verification.md`

- [ ] **Step 1: Write the transport probe** — boot a minimal `@server.mcp.tool()` registration using the Gate 0.1 winning pattern. Dump the in-memory `tool.parameters` AND the on-wire `tools/list` payload from both stdio and HTTP transports. Walk for `"oneOf"` at any depth.

The probe uses an env-flag-gated registration block in `server.py` (`OZM_GATE_0_PROBE=1`) so the same code path drives both in-memory check and subprocess wire checks. The probe registrations register exactly one tool — `probe_tool` — and return early so no other tools are registered.

- [ ] **Step 2: Add the env-flag-gated probe to `server.py`** — short-lived; reverted when Gate 0 completes.

- [ ] **Step 3: Run it and write verdict** in `transport_oneof_verification.md`:

```markdown
# Gate 0 — `oneOf` transport verification

**Date run:** <ISO date>
**FastMCP version:** <from `pip show fastmcp`>

## Probe results

<paste in-memory + stdio wire + HTTP wire dumps>

## Verdict

One of:
- **PROCEED-AS-DESIGNED** — oneOf round-trips on both transports from the Gate 0.1 winning pattern.
- **PROCEED-WITH-OVERRIDE** — oneOf round-trips only through an explicit override pattern. Plan amended to use the override pattern in zim_search.py / zim_get.py AND in the Gate 0b prototype skeletons.
- **STOP-AMEND-SPEC (NO-TRANSPORT-PRESERVATION)** — oneOf does not round-trip. Skip Gate 0.3. Open the spec-amendment PR (flat-schema design).
```

- [ ] **Step 4: Commit**

```bash
git add tests/dispatch_eval/check_transport.py tests/dispatch_eval/transport_oneof_verification.md openzim_mcp/server.py
git commit -m "test(gate-0.2): oneOf transport verification (verdict: <VERDICT>)"
```

### Task Z2: Decision routing (combined Gate 0.1 + 0.2 verdict)

- [ ] **Step 1: Revert the env-flag-gated probe block from `server.py`**

Task Z1 Step 2 added an `OZM_GATE_0_PROBE=1`-gated registration block to `server.py` so the in-memory and subprocess wire checks shared one code path. That block is verification scaffolding, not production logic — it MUST be removed before the Gate 0 PR opens to main. Otherwise rc0 (which branches from main) inherits dead code triggered by a magic env var.

```bash
git diff main -- openzim_mcp/server.py
# Confirm the only server.py change is the OZM_GATE_0_PROBE block.
# Revert the block. The verification artifacts (transport_oneof_verification.md,
# oneof_parse_benchmark.md, the gate scripts in tests/dispatch_eval/) stay committed —
# they're the evidence for the gate verdict — only the production-source probe is removed.
```

- [ ] **Step 2: If any sub-gate reports STOP-AMEND-SPEC**, open the spec amendment PR on this branch:

Edit `docs/superpowers/specs/2026-05-24-v2-phase-f-tool-surface-design.md`:

- Drop the `oneOf` design from Design decisions → Schema-conditional parameters; replace with flat-schema-plus-prose + handler-level runtime validation.
- Re-budget the schema table: `zim_search` ~2,200, `zim_get` ~3,000, total ~17,000.
- Update the relevant sections to refer to the flat-schema design throughout.

Also update this plan file to match (replace `oneOf`-gated branches with flat schemas in Stages B and D).

- [ ] **Step 3: Open the Gate 0 PR**

```bash
git push -u origin v2-phase-f-gate-0
gh pr create --base main --label v2-phase-f --title "phase-f gate 0: oneOf transport verification (0.1 emission + 0.2 round-trip)" --body "..."
```

The PR body summarizes the two sub-gate verdicts and links to the committed verification artifacts. If either sub-gate reported STOP, the PR also carries the spec amendment commit. Confirm in the PR description that `server.py` was reverted (Step 1). Note in the PR body that Gate 0.3 will run in Stage B against the prototype skeletons.

- [ ] **Step 4: Once merged, proceed to Stage A.**

---

## Stage A — `v2.0.0rc0` (Pure Refactor)

**Goal:** extract `_promote_topic_via_title_index` from `SimpleToolsHandler` to a module-level function in `openzim_mcp/topic_preprocessing.py`, with no surface change. Diff-tested against the b1 → b13 cumulative probe set.

### Task A0: Create `v2-phase-f-rc0` branch

- [ ] **Step 1: Branch from main** (which now includes Gate 0's verdict artifacts)

```bash
git checkout main
git pull
git checkout -b v2-phase-f-rc0
```

### Task A1: Add `tests/dispatch_eval/` scaffold

`pytest_addoption` MUST live in the rootdir conftest (`tests/conftest.py`), not in a subdirectory's conftest — pytest only invokes `pytest_addoption` hooks from plugins and rootdir conftest. Putting it in `tests/dispatch_eval/conftest.py` registers nothing and `--dispatch-eval` is silently ignored.

- [ ] **Step 1: Create the package marker**

`tests/dispatch_eval/__init__.py` (empty).

- [ ] **Step 2: Add `--dispatch-eval` option to the existing rootdir conftest**

Edit `tests/conftest.py` (the existing file) to add the option and a collection-modify hook that auto-skips `dispatch_eval/*` tests unless the flag is set:

```python
# tests/conftest.py — additions (preserve everything already in the file)

def pytest_addoption(parser):
    parser.addoption(
        "--dispatch-eval",
        action="store_true",
        default=False,
        help="Opt into tests/dispatch_eval/ — paid API calls, manual invocation only.",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--dispatch-eval", default=False):
        return
    import pytest
    skip_marker = pytest.mark.skip(reason="dispatch_eval opt-in only; pass --dispatch-eval")
    for item in items:
        if "dispatch_eval" in str(item.fspath):
            item.add_marker(skip_marker)
```

Verify the option registers:

```bash
pytest --help 2>&1 | grep dispatch-eval
# Expected: a line describing --dispatch-eval. If missing, the hook is in the wrong location.
```

Verify the collection skip fires:

```bash
pytest tests/dispatch_eval/ --collect-only 2>&1 | tail -5
# Expected: items listed but each marked SKIPPED.

pytest tests/dispatch_eval/ --collect-only --dispatch-eval 2>&1 | tail -5
# Expected: items listed and NOT skipped.
```

### Task A2: Capture the b1 → b13 cumulative probe set

**Files:**

- Create: `tests/dispatch_eval/data/b1_b13_probes.jsonl`

- [ ] **Step 1: Sweep b-series commit messages and beta-test sweeps** to extract every distinct probe from b1 → b13. Format each as a JSONL row:

```python
# Per-line schema:
# {
#   "probe_id": "<unique slug>",
#   "topic": "<input string as passed to _promote_topic_via_title_index>",
#   "expected_entry_path": "<resolved entry path at b13 — the byte-identical target>",
#   "zim_archive_hint": "<archive name used to obtain the baseline>",
#   "operational_classes": ["<class>", ...],
#   "b_series_origin": "b<N>",
#   "notes": "<one-line rationale; optional>"
# }
```

- [ ] **Step 2: Verify counts** — expect ~150 distinct probes after dedup across the 13 betas.

```bash
wc -l tests/dispatch_eval/data/b1_b13_probes.jsonl
```

### Task A3: Write the failing promotion-extraction diff-test (RED)

**Files:**

- Create: `tests/dispatch_eval/test_promotion_extraction_parity.py`

- [ ] **Step 1: Write the test** — for each probe in `b1_b13_probes.jsonl`, call both the old `SimpleToolsHandler._promote_topic_via_title_index` and the new (not-yet-existing) `topic_preprocessing.promote_topic_via_title_index`. Assert byte-identical resolved entry paths.

```python
"""Gate 0a — promotion-extraction parity diff-test.

For each probe in b1_b13_probes.jsonl, run BOTH the legacy instance method
(SimpleToolsHandler._promote_topic_via_title_index) and the new module-level
function (topic_preprocessing.promote_topic_via_title_index). Assert
byte-identical resolved entry paths.
"""

import json
from pathlib import Path
import pytest

from openzim_mcp.simple_tools import SimpleToolsHandler

# Will be filled in once Task A4 lands the extraction.
try:
    from openzim_mcp.topic_preprocessing import promote_topic_via_title_index
except ImportError:
    promote_topic_via_title_index = None


def load_probes():
    path = Path("tests/dispatch_eval/data/b1_b13_probes.jsonl")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.mark.parametrize("probe", load_probes(), ids=lambda p: p["probe_id"])
def test_promotion_parity(probe, configured_server, zim_archives):
    """Old method and new module-level function resolve byte-identical paths."""
    assert promote_topic_via_title_index is not None, "topic_preprocessing extraction missing"
    handler = configured_server.simple_tools_handler
    archive_path = zim_archives[probe["zim_archive_hint"]]

    old_result = handler._promote_topic_via_title_index(probe["topic"], archive_path)
    new_result = promote_topic_via_title_index(
        zim_operations=handler.zim_operations,
        zim_file_path=archive_path,
        topic=probe["topic"],
    )
    assert old_result == new_result, f"divergence on {probe['probe_id']}: old={old_result} new={new_result}"
```

- [ ] **Step 2: Run, confirm RED**

```bash
pytest tests/dispatch_eval/test_promotion_extraction_parity.py --dispatch-eval -x
# Expected: ImportError — promote_topic_via_title_index doesn't exist yet
```

### Task A3a: Write the failing auto-select-extraction diff-test (RED)

**Files:**

- Create: `tests/dispatch_eval/test_auto_select_extraction_parity.py`

**Context.** `_auto_select_zim_file` is shorter than the promotion orchestrator (~30 lines vs ~160) but carries operator-visible side effects: log emits on each of the 0-files / 1-file / N-files / exception arms. zim_search at rc1 calls the extracted function in the auto-archive case; if the extraction drops a log emit or changes the exception-handling envelope, the diff-test must catch it.

- [ ] **Step 1: Write the test** — for each of four scenarios (0 / 1 / N files loaded; list_zim_files_data raises), call BOTH the old `SimpleToolsHandler._auto_select_zim_file` and the new (not-yet-existing) `topic_preprocessing.auto_select_zim_file`. Assert byte-identical return value AND identical log records (via pytest's `caplog`).

```python
"""Gate 0a — auto-select-extraction parity diff-test.

For each archive-count scenario (0, 1, N, exception-raising), assert that
the old instance method and the extracted module-level function produce
byte-identical return AND identical log records.
"""

import logging
import pytest

from openzim_mcp.simple_tools import SimpleToolsHandler

try:
    from openzim_mcp.topic_preprocessing import auto_select_zim_file
except ImportError:
    auto_select_zim_file = None


@pytest.mark.parametrize("scenario", ["zero_files", "one_file", "n_files", "raises"])
def test_auto_select_parity(scenario, configured_server, monkeypatch, caplog):
    """Old method and new module-level function return identical values AND emit identical logs."""
    assert auto_select_zim_file is not None, "topic_preprocessing extraction missing"
    handler = configured_server.simple_tools_handler

    # Stub zim_operations.list_zim_files_data per scenario
    if scenario == "zero_files":
        monkeypatch.setattr(handler.zim_operations, "list_zim_files_data", lambda: [])
    elif scenario == "one_file":
        monkeypatch.setattr(handler.zim_operations, "list_zim_files_data", lambda: [{"path": "/a/b.zim"}])
    elif scenario == "n_files":
        monkeypatch.setattr(handler.zim_operations, "list_zim_files_data", lambda: [{"path": "/a/b.zim"}, {"path": "/c/d.zim"}])
    else:  # raises
        def boom():
            raise RuntimeError("simulated")
        monkeypatch.setattr(handler.zim_operations, "list_zim_files_data", boom)

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        old_result = handler._auto_select_zim_file()
    old_records = [(r.levelname, r.message) for r in caplog.records]

    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        new_result = auto_select_zim_file(handler.zim_operations)
    new_records = [(r.levelname, r.message) for r in caplog.records]

    assert old_result == new_result, f"divergence on {scenario}: old={old_result} new={new_result}"
    assert old_records == new_records, f"log divergence on {scenario}: old={old_records} new={new_records}"
```

- [ ] **Step 2: Run, confirm RED**

```bash
pytest tests/dispatch_eval/test_auto_select_extraction_parity.py --dispatch-eval -x
# Expected: ImportError — auto_select_zim_file doesn't exist yet
```

### Task A4: Extract `_promote_topic_via_title_index` AND `_auto_select_zim_file` to `topic_preprocessing.py`

**Files:**

- Create: `openzim_mcp/topic_preprocessing.py`
- Modify: `openzim_mcp/simple_tools.py`

**Context.** rc1's `zim_search(mode="title")` needs BOTH functions: the promotion orchestrator AND auto-archive-select. The earlier draft inlined a ~5-line auto-select reimplementation in `zim_search.py` to avoid a "cross-module private-API dependency," but the existing `_auto_select_zim_file` (simple_tools.py:5784) carries exception handling and operator-visible log emits that the inline form drops. Reimplementing it inline silently regresses the diagnostic surface (operators using `zim_search(mode="title")` with multiple archives loaded and no `zim_file_path` would lose the "Auto-select skipped: N ZIM files found" log line, and `list_zim_files_data` raising would crash the request rather than fall through). Extracting both via the same pattern keeps the rc1 surface byte-equivalent on these paths.

- [ ] **Step 1: Read the current implementations** (simple_tools.py:3896-4056 for promotion; simple_tools.py:5784-5817 for auto-select)

- [ ] **Step 2: Create `openzim_mcp/topic_preprocessing.py`** with both extracted module-level functions. Take `zim_operations` (and `zim_file_path` where applicable) as explicit arguments. Inline `_probe` as a local closure that captures the args. Inline `_passes_z4` and `_accept_with_multi_entity_check` as module-level helpers (or local closures inside the orchestrator — equivalent at the byte-output level). `auto_select_zim_file` is a verbatim port preserving the try/except + 4-arm log behavior.

```python
"""topic_preprocessing — NL-topic promotion orchestrator + archive auto-select extracted from SimpleToolsHandler.

Pure functions. Take zim_operations (and zim_file_path where applicable) as explicit arguments.
Used by:
  - SimpleToolsHandler._promote_topic_via_title_index + ._auto_select_zim_file (thin wrappers) — always
  - openzim_mcp.tools.zim_search (Phase F mode='title') — auto_select_zim_file always; promote_topic_via_title_index IFF Gate 0b takes the wired path
"""

from __future__ import annotations
import logging
from typing import Any, Optional, Protocol

logger = logging.getLogger(__name__)


class ZimOperationsProtocol(Protocol):
    def find_entry_by_title_data(self, zim_file_path: str, title: str, ...) -> dict[str, Any]: ...
    def list_zim_files_data(self) -> list[dict[str, Any]]: ...


def promote_topic_via_title_index(
    zim_operations: ZimOperationsProtocol,
    zim_file_path: str,
    topic: str,
    # ... additional parameters as needed
) -> Optional[dict[str, Any]]:
    """Z3/Z4/OPP-1 promotion orchestrator. Module-level pure function.

    Behavior is byte-identical to SimpleToolsHandler._promote_topic_via_title_index
    (proven by Gate 0a diff-test).
    """
    # <Verbatim port of simple_tools.py:3896-4056 with self.zim_operations replaced
    # by the zim_operations parameter.>


def auto_select_zim_file(zim_operations: ZimOperationsProtocol) -> Optional[str]:
    """Auto-select a ZIM file if exactly one is loaded.

    Behavior is byte-identical to SimpleToolsHandler._auto_select_zim_file
    (simple_tools.py:5784) — preserves the try/except + 4-arm log emits
    (0-files info / 1-file debug / N-files info / exception warning).
    Proven by Gate 0a diff-test.
    """
    # <Verbatim port of simple_tools.py:5784-5817 with self.zim_operations
    # replaced by the zim_operations parameter.>
```

- [ ] **Step 3: Reduce BOTH `SimpleToolsHandler` methods to thin wrappers**

```python
def _promote_topic_via_title_index(self, topic: str, zim_file_path: str, ...) -> Optional[Dict[str, Any]]:
    """Phase F: thin wrapper delegating to topic_preprocessing.promote_topic_via_title_index."""
    from openzim_mcp.topic_preprocessing import promote_topic_via_title_index
    return promote_topic_via_title_index(
        zim_operations=self.zim_operations,
        zim_file_path=zim_file_path,
        topic=topic,
        ...
    )


def _auto_select_zim_file(self) -> Optional[str]:
    """Phase F: thin wrapper delegating to topic_preprocessing.auto_select_zim_file."""
    from openzim_mcp.topic_preprocessing import auto_select_zim_file
    return auto_select_zim_file(self.zim_operations)
```

- [ ] **Step 4: Run BOTH parity tests — expected GREEN**

```bash
pytest tests/dispatch_eval/test_promotion_extraction_parity.py tests/dispatch_eval/test_auto_select_extraction_parity.py --dispatch-eval -x
```

The auto-select diff-test (Task A3a) replays each probe's archive-hint scenario through both the old method and the extracted function, asserting byte-identical return AND log-emit equivalence (captured via `caplog`).

- [ ] **Step 5: Run the full suite to confirm no regressions**

```bash
pytest -x 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/topic_preprocessing.py openzim_mcp/simple_tools.py tests/dispatch_eval/test_promotion_extraction_parity.py tests/dispatch_eval/test_auto_select_extraction_parity.py
git commit -m "refactor(rc0): extract promote_topic_via_title_index + auto_select_zim_file to topic_preprocessing"
```

### Task A5: Write the preprocessing-orchestration parity diff-test

**Files:**

- Create: `tests/dispatch_eval/test_preprocessing_extraction_parity.py`

The Tier 1 / filler-prose / possessive helpers are already at module level in `intent_parser.py` and `title_promotion.py`. What needs a test is the **orchestration order** of the classmethod calls in `simple_tools.py` — accidental reordering during the refactor would shift post-rewrite strings on edge probes.

- [ ] **Step 1: Write the test** — replay each probe's raw query through the canonical Tier 1 chain (`IntentParser._apply_misspelling_map` → `IntentParser._detect_stopword_phrase`) as currently invoked in `simple_tools.py`. Assert the chain is idempotent (a second pass yields byte-identical output).

```python
"""Gate 0a — preprocessing orchestration idempotency test.

NOT a parity-vs-new-module test (the helpers are NOT relocated in rc0 — they already
live at module level in intent_parser.py and title_promotion.py). This test guards
against accidental reordering of the inline chain in simple_tools.py during the refactor.
"""

import json
from pathlib import Path
import pytest

from openzim_mcp.intent_parser import IntentParser


def load_probes():
    path = Path("tests/dispatch_eval/data/b1_b13_probes.jsonl")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.mark.parametrize("probe", load_probes(), ids=lambda p: p["probe_id"])
def test_preprocessing_idempotent(probe):
    """A second pass through the Tier 1 chain yields byte-identical output."""
    pass1 = IntentParser._apply_misspelling_map(probe["topic"])
    pass1 = IntentParser._detect_stopword_phrase(pass1)
    pass2 = IntentParser._apply_misspelling_map(pass1)
    pass2 = IntentParser._detect_stopword_phrase(pass2)
    assert pass1 == pass2, f"non-idempotent on {probe['probe_id']}: {pass1} vs {pass2}"
```

- [ ] **Step 2: Run, commit**

```bash
pytest tests/dispatch_eval/test_preprocessing_extraction_parity.py --dispatch-eval -x
git add tests/dispatch_eval/test_preprocessing_extraction_parity.py
git commit -m "test(rc0): preprocessing orchestration idempotency diff-test"
```

### Task A6: Direct unit tests for `topic_preprocessing` module

**Files:**

- Create: `tests/test_topic_preprocessing.py`

- [ ] **Step 1: Write focused unit tests for the module-level function** — not just parity with the old method (Task A3 covers that), but direct unit coverage that documents the function's contract.

```python
"""Unit tests for openzim_mcp.topic_preprocessing.

Documents the module-level function's contract independently of its
call sites. Mirrors the most important behavior pins from the b-series
sweep history (Z3/Z4/OPP-1 acceptance, biographical exemption,
digit-specificity exemption, type-extension exemption).
"""
```

Cover at least: Z3 probe-based discriminator, Z4 multi-token tangential rejection, Z4 biographical exemption (`Picasso Paris cubism` → `Pablo_Picasso`), Z4 digit-specificity exemption (`Beethoven 9th symphony` → `Symphony_No._9_(Beethoven)`), Z4 type-extension exemption (`Big Rapids Michigan Ferris State` → `Ferris_State_University`), OPP-1 possessive promotion (`Newton's gravity` → `Newton's_law_of_universal_gravitation`).

- [ ] **Step 2: Run, commit**

```bash
pytest tests/test_topic_preprocessing.py -v
git add tests/test_topic_preprocessing.py
git commit -m "test(rc0): direct unit tests for topic_preprocessing module"
```

### Task A7: Update v2 README + spec link

- [ ] **Step 1: Mark Phase F row as `In Design` and link the spec.**

```bash
sed -i '' 's|^| Phase F |...In Design|' docs/v2/README.md  # adjust to actual format
git add docs/v2/README.md
git commit -m "docs(v2): mark Phase F In Design"
```

### Task A8: Open rc0 PR, merge, tag

- [ ] **Step 1: Push branch and open PR**

```bash
git push -u origin v2-phase-f-rc0
gh pr create --base main --label v2-phase-f --title "v2.0.0rc0: promotion-extraction refactor" --body "..."
```

PR body template:

```markdown
## What

Extract `SimpleToolsHandler._promote_topic_via_title_index` to a module-level function in `openzim_mcp/topic_preprocessing.py`. `SimpleToolsHandler._promote_topic_via_title_index` becomes a thin delegating wrapper. No tool-surface change.

## Why

The extraction is necessary for Phase F rc1's `zim_search(mode='title')` to apply Z3/Z4/OPP-1 promotion as a post-filter on `find_entry_by_title` results. The current instance-method form (with `self.zim_operations` and a `_probe` closure) is not callable from `zim_search.py` directly.

Splitting the refactor from the rc1 surface change scopes blame domain — a defect in rc1's live sweep cannot be attributed to refactor code.

## Tests

- `tests/dispatch_eval/test_promotion_extraction_parity.py` — byte-identical resolved entry paths on the b1 → b13 cumulative probe set (~150 probes).
- `tests/dispatch_eval/test_preprocessing_extraction_parity.py` — orchestration order of `IntentParser` classmethod calls in `simple_tools.py` is idempotent.
- `tests/test_topic_preprocessing.py` — direct unit coverage of the extracted module.

## Spec

[docs/superpowers/specs/2026-05-24-v2-phase-f-tool-surface-design.md](docs/superpowers/specs/2026-05-24-v2-phase-f-tool-surface-design.md)
```

- [ ] **Step 2: Merge after review, tag `v2.0.0rc0`**

```bash
git checkout main
git pull
git tag v2.0.0rc0
git push origin v2.0.0rc0
```

### Task A9: Manual sign-off hold

rc0 is a pure-refactor diff-tested against the b1 → b13 cumulative set (~150 probes) AND `caplog`-record-equality on the four auto-select archive-count scenarios. The diff-tests cover the load-bearing risks; sign-off catches edge cases the diff-test missed (telemetry shapes, caching behavior, error-message wording). There is no calendar-soak timer.

- [ ] **Step 1: Ad-hoc probing** — Cameron runs rc0 against a representative ZIM (e.g., Wikipedia) for a short session (hours, not days). Draws probes from b13's known-good shapes. Notes any unexpected behavior.

- [ ] **Step 2: Website demo integration is non-blocking** — the demo upgrade happens whenever convenient. Any regression discovered post-tag is handled as `v2.0.0rc0.post1`, not as a Stage B block.

- [ ] **Step 3: If ad-hoc probing reports a divergence**, file an issue, root-cause, fix, tag `v2.0.0rc0.post1`, re-probe.

- [ ] **Step 4: Once ad-hoc probing reports clean**, sign off in the rc0 PR and proceed to Stage B.

The rationale for the earlier 14-day calendar timer (bounding the wait for external integration coordination) does not apply: the website demo is decoupled, and ad-hoc probing on a single-maintainer project is hours not days. The diff-tests already constitute the primary regression gate.

---

## Stage B — Gate 0b Infrastructure (Against Prototype Branch)

**Goal:** Build the eval harness and prototype the 8-tool surface enough to run the dispatch eval, without merging to main. The prototype is throwaway scaffolding for the Gate 0b measurement.

### Task B1: Create the prototype branch

- [ ] **Step 1: Branch off rc0**

```bash
git checkout v2.0.0rc0
git checkout -b v2-phase-f-prototype
```

The prototype branch is never merged to main; it exists only to host the Gate 0b eval.

### Task B2: Draft all 8 tool descriptions in skeleton modules

**Files:**

- Create skeleton modules for `zim_query.py`, `zim_search.py`, `zim_get.py`, `zim_get_section.py`, `zim_browse.py`, `zim_metadata.py`, `zim_links.py`, `zim_health.py`.

**Context:** Gate 0b measures schema bytes from real tool descriptions, not estimates. Each skeleton registers a tool with the full signature and production-quality description (sized per the per-tool budget in the spec). The implementation delegates to existing legacy tools (so behavior is unchanged from rc0).

- [ ] **Step 1: For each of the 8 tools, write a skeleton module that exposes `register(server)`**

Example for `openzim_mcp/tools/zim_search.py`:

```python
"""zim_search — full-text / title-lookup / suggest entry point (3-mode dispatch).

Phase F prototype skeleton. Behavior delegates to existing zim_operations methods;
description is production-quality and consumes the schema budget.
"""

from __future__ import annotations

from typing import Literal, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from openzim_mcp.server import OpenZimMcpServer


def register(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def zim_search(
        query: str,
        mode: Literal["fulltext", "title", "suggest"] = "fulltext",
        zim_file_path: Optional[str] = None,
        cross_file: bool = False,
        namespace: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        cursor: Optional[str] = None,
    ):
        """<COPY THE FULL ~2,400-BYTE DESCRIPTION FROM SPEC §2 zim_search>"""
        # Skeleton: delegate to existing tool.
        from openzim_mcp.async_operations import AsyncZimOperations
        ops = AsyncZimOperations(server.zim_operations)
        if mode == "fulltext":
            return await ops.search_zim_file_data(...)
        elif mode == "title":
            return await ops.find_entry_by_title_data(...)
        elif mode == "suggest":
            return await ops.get_search_suggestions_data(...)
```

Repeat for all 8 tools.

**For `oneOf`-conditional tools (`zim_get`, `zim_search`), the prototype MUST use the SAME type-signature pattern Gate 0.1 selected as the winning pattern.** If the prototype uses flat signatures while rc1 uses `oneOf`, Gate 0b's dispatch eval measures models against a flat-schema wire shape and then rc1 ships an entirely different schema shape that was never measured.

| Gate 0 verdict | Prototype skeleton uses | rc1 ships |
| --- | --- | --- |
| PROCEED-AS-DESIGNED (Pattern A won) | `Literal["fulltext","title","suggest"]`-gated parameters in `zim_search`; per-branch parameter models for `zim_get` | Same |
| PROCEED-WITH-OVERRIDE (Pattern B won) | Explicit `inputSchema=<oneOf-dict>` kwarg on `@tool()` | Same |
| PROCEED-AS-DESIGNED (Pattern C won) | Pydantic discriminator parameter model | Same |
| STOP-AMEND-SPEC (any cause) | Flat parameter signature, prose-only conditionals | Flat parameter signature, prose-only conditionals |

**Verification step.** After writing all 8 prototype skeletons, dump each tool's `inputSchema` and confirm `oneOf` appears in `zim_search` and `zim_get` schemas (or absent if STOP-AMEND-SPEC took the flat path):

```bash
OZM_PHASE_F_PROTOTYPE=1 python -c "
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.config import OpenZimMcpConfig
import json

cfg = OpenZimMcpConfig(allowed_directories=['/tmp'], tool_mode='advanced')
srv = OpenZimMcpServer(cfg)
for name in ['zim_search', 'zim_get']:
    tool = srv.mcp._tool_manager._tools[name]
    schema_str = json.dumps(tool.parameters)
    has_oneof = '\"oneOf\"' in schema_str
    print(f'{name}: oneOf in schema = {has_oneof}')
"
```

- [ ] **Step 2: Add `register_phase_f_tools` orchestrator**

Edit `openzim_mcp/tools/__init__.py`:

```python
def register_phase_f_tools(server: "OpenZimMcpServer") -> None:
    """Phase F prototype registration. Surface: 8 tools in advanced, 1 in simple."""
    from . import zim_query
    zim_query.register(server)

    if server.config.tool_mode == "simple":
        return  # 1-tool surface

    # advanced: all 8
    from . import zim_search, zim_get, zim_get_section, zim_browse, zim_metadata, zim_links, zim_health
    for module in (zim_search, zim_get, zim_get_section, zim_browse, zim_metadata, zim_links, zim_health):
        module.register(server)
```

- [ ] **Step 3: Wire the prototype into `server.py` behind a feature flag**

Edit `openzim_mcp/server.py`. Find the existing registration code:

```python
if self.config.tool_mode == TOOL_MODE_SIMPLE:
    self._register_simple_tools()
else:
    register_all_tools(self)
```

Add an env-var gate so the prototype activates ONLY for the eval harness, never in normal runs:

```python
import os
if os.environ.get("OZM_PHASE_F_PROTOTYPE") == "1":
    proto_tool_mode = os.environ.get("OZM_TOOL_MODE")
    if proto_tool_mode:
        self.config.tool_mode = proto_tool_mode  # type: ignore[assignment]
    from .tools import register_phase_f_tools
    register_phase_f_tools(self)
elif self.config.tool_mode == TOOL_MODE_SIMPLE:
    self._register_simple_tools()
else:
    register_all_tools(self)
```

**Pydantic `validate_assignment=True` required for the env-var override.** Check:

```bash
grep -nA2 "model_config\|ConfigDict" openzim_mcp/config.py | head -20
```

If `validate_assignment=True` is not already set, add it to the prototype branch's `config.py`.

The runner's `OZM_CRITERION_C_PATH` env var is read by `tools/zim_search.py` (picks wired vs fallback). Wire that read in the Step 1 skeleton.

- [ ] **Step 4: Boot the server with the env var and dump tool list**

```bash
OZM_PHASE_F_PROTOTYPE=1 python -c "
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.config import OpenZimMcpConfig
cfg = OpenZimMcpConfig(allowed_directories=['/tmp'], tool_mode='advanced')
srv = OpenZimMcpServer(cfg)
import json
for name, tool in srv.mcp._tool_manager._tools.items():
    schema = json.dumps({'name': name, 'description': tool.description, 'inputSchema': tool.parameters}).encode()
    print(name, len(schema))
"
```

Expected: 8 tools listed with byte counts roughly matching the per-tool budget table.

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/tools/zim_*.py openzim_mcp/tools/__init__.py openzim_mcp/server.py
git commit -m "proto(gate-0b): skeleton 8-tool surface with prod-quality descriptions"
```

- [ ] **Step 6: Snapshot the prototype's per-tool wire footprints** for the rc1 parity check

```bash
OZM_PHASE_F_PROTOTYPE=1 OZM_TOOL_MODE=advanced python -c "
import json
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.config import OpenZimMcpConfig

cfg = OpenZimMcpConfig(allowed_directories=['/tmp'], tool_mode='advanced')
srv = OpenZimMcpServer(cfg)
snapshot = {}
for name, tool in srv.mcp._tool_manager._tools.items():
    wire = json.dumps({'name': name, 'description': tool.description, 'inputSchema': tool.parameters})
    snapshot[name] = {
        'bytes': len(wire.encode()),
        'description': tool.description,  # captured so Task D14b edit-distance check has the source-of-truth prose
        'inputSchema': tool.parameters,
    }
print(json.dumps(snapshot, indent=2))
" > tests/dispatch_eval/prototype_schema_snapshot.json

git add tests/dispatch_eval/prototype_schema_snapshot.json
git commit -m "data(gate-0b): prototype per-tool wire-footprint snapshot for rc1 parity check"
```

The snapshot lands on the prototype branch and is cherry-picked into rc1 alongside the Gate 0b decision artifact. Task D14b consumes it to enforce the ±5% byte parity invariant + structural-identity check.

### Task B2a: Gate 0.3 — small-model `oneOf`-parsing benchmark (against prototype skeletons)

**Files:**

- Create: `tests/dispatch_eval/oneof_parse_benchmark.py`
- Create: `tests/dispatch_eval/oneof_parse_benchmark.jsonl`
- Create: `tests/dispatch_eval/oneof_parse_benchmark.md`

**Context:** moved here from Stage 0 — the earlier draft ran Gate 0.3 against synthetic schemas "modeled on" the production tools, which decoupled the measurement from the production surface. Now Gate 0.3 imports the prototype skeletons' actual `inputSchema` bytes (committed in Task B2 Step 6) and runs the ablation against THOSE. Whatever passes here is what rc1 ships (modulo the prototype↔rc1 parity check in Task D14b).

Runs only if Gate 0.2 produced a wired-`oneOf` verdict (`gate_0_schema_shape: wired_oneof` in the Stage 0 artifacts). Skip entirely if Gate 0 chose flat schemas.

- [ ] **Step 1: Author the 100-probe `oneOf` ablation set** in `oneof_parse_benchmark.jsonl`. Each probe is an NL query targeting one of the actual Phase F production tools — `zim_get`'s 4-branch shape and `zim_search`'s 3-branch shape, as drafted in the Task B2 prototype skeletons. Gold-labeled expected branch and parameter shape. Curated against `zim_get` + `zim_search` only (the two tools that use `oneOf`).

- [ ] **Step 2: Build two registrations of the same target tools**

- `oneof_variant` — `zim_get` and `zim_search` with the `oneOf` schemas the prototype skeletons emit (byte-identical via direct import of the prototype tool modules under `OZM_PHASE_F_PROTOTYPE=1`).
- `flat_variant` — `zim_get` and `zim_search` with flat parameter schemas where the conditionals are described in prose only. Throwaway local module that mirrors the prototype's `register(server)` shape but with `Optional[...]` parameters instead of `Literal`-gated ones.

- [ ] **Step 3: Run both variants against Qwen-2.5-7B-Instruct** (local, vLLM with `--tool-call-parser hermes`), temperature=0.2, 5 reps per probe.

```bash
# Boot Qwen (vLLM, single GPU) — see Task B7 inference_setup.md
python -m vllm.entrypoints.openai.api_server --model Qwen/Qwen2.5-7B-Instruct \
  --tool-call-parser hermes --enable-auto-tool-choice &

# Wait for ready, then:
python tests/dispatch_eval/oneof_parse_benchmark.py | tee /tmp/oneof_parse.json
```

- [ ] **Step 4: Write verdict** in `oneof_parse_benchmark.md`:

```markdown
# Gate 0.3 — small-model `oneOf` parsing benchmark (against prototype skeletons)

**Date run:** <ISO date>
**Model:** Qwen-2.5-7B-Instruct
**Probe count:** 100
**Reps per probe:** 5
**Source schemas:** prototype skeletons at <commit-sha> on v2-phase-f-prototype

## Results

| Metric | oneof_variant | flat_variant | Delta (1-sided z-test α=0.05) |
| --- | --- | --- | --- |
| Branch-selection accuracy | ... | ... | ... |
| Parameter-validity rate | ... | ... | ... |

## Verdict

One of:
- **PROCEED-AS-DESIGNED-VALIDATED** — oneOf wins by ≥7pp on either metric. Surface design empirically supported.
- **PROCEED-AS-DESIGNED-UNVALIDATED** — oneOf is statistically indistinguishable from flat. Surface design proceeds (transport works, byte cost is acceptable) but the small-model benefit is unmeasured.
- **STOP-AMEND-SPEC (ONEOF-DOWNGRADES-DISPATCH)** — oneOf loses by ≥7pp. Open the spec amendment to flat schemas. Re-author the prototype skeletons with flat parameter signatures. Re-snapshot. Skip Gate 0b's wired path entirely; Gate 0b runs against the flat-schema prototype.
```

- [ ] **Step 5: Commit**

```bash
git add tests/dispatch_eval/oneof_parse_benchmark.py tests/dispatch_eval/oneof_parse_benchmark.jsonl tests/dispatch_eval/oneof_parse_benchmark.md
git commit -m "test(gate-0.3): oneOf parsing benchmark against prototype (verdict: <VERDICT>)"
```

- [ ] **Step 6: If verdict is STOP-AMEND-SPEC**, open spec amendment PR (same template as Stage 0 Task Z2 Step 2 — drop wired `oneOf` design, re-budget, amend plan). Then re-author Task B2 skeletons with flat signatures, re-snapshot in Task B2 Step 6, and commit. Gate 0b's prototype is now the flat variant.

### Task B3: Build the 300-probe dispatch eval probe set

**Files:**

- Create: `tests/dispatch_eval/probes.jsonl`
- Create: `tests/dispatch_eval/check_probe_coverage.py`

**Context:** 300 probes, gold-labeled with four fields per spec: operation, expected_parameters, tool_eligibility, AND operational-class tag list. Per-class minimum 20 probes (operational-class tags can be lists — one probe can count toward multiple classes).

- [ ] **Step 1: Write probes JSON schema doc**

```python
# Per-line schema:
# {
#   "probe_id": "<unique slug>",
#   "query": "<NL question as a model would receive it>",
#   "operation": "search" | "entry_fetch" | "summary" | "toc" | "structure" | "namespace_browse" | "links" | "metadata" | "main_page" | "health",
#   "expected_tool": "zim_query" | "zim_search" | "zim_get" | "zim_get_section" | "zim_browse" | "zim_metadata" | "zim_links" | "zim_health",
#   "expected_parameters": { "<load-bearing field>": "<value>", ... },
#   "tool_eligibility": "zim_query_preferred" | "zim_search_title_preferred" | "either_acceptable",
#   "operational_classes": ["<class>", ...],
#     # Valid classes:
#     #   b-series defect: "Z1", "Z2", "Z3", "Z4", "OPP-1", "Sub-pattern-C",
#     #                    "filler-prose", "possessive"
#     #   Phase F operation: "zim_get-toc", "zim_get-summary", "zim_get-structure",
#     #                      "zim_get-binary", "zim_get-main-page", "zim_get-batch",
#     #                      "zim_browse-page", "zim_browse-walk", "zim_metadata",
#     #                      "zim_links-outbound", "zim_links-related", "zim_health"
#   "zim_archive_hint": "<archive name>",
#   "expected_resolved_entry_path": "<for either_acceptable + zim_query_preferred probes — used by Criterion C>"
# }
```

- [ ] **Step 2: Author the probes — composition 130 b-series + 120 representative + 50 Phase F operations**

The composition mitigates sourcing bias (b-series probes are by construction queries previous releases got *wrong*, so over-weighting inflates apparent rigor on historical failure shapes) while ensuring the ≥20-per-class F1 floor holds across all 8 b-series defect classes. Acknowledged sourcing bias documented in the spec's Gate 0b procedure step 1.

- **~130 probes** sampled from `tests/dispatch_eval/data/b1_b13_probes.jsonl`. Biased toward at least 2× coverage of each b-series defect class. If `b1_b13_probes.jsonl` lacks ≥20 candidates for a class, fill the gap by hand-authoring new probes flagged `"source": "b-series-author-extended"`.
- **~120 probes** authored fresh against a representative-query distribution.
- **~50 probes** specifically targeting Phase F operation classes.

**Pin Z4 coverage explicitly.** The Z4 class is the freshest b-series hardening and the most likely casualty of the dispatch surface change. The probe set must include ≥20 `Z4`-tagged probes that are also `zim_query_preferred` (i.e., Criterion C3 can compute on them — they cover the case where the model might spuriously route to `zim_search(mode="title")`). Examples: "Tesla electricity", "Lenin Russia", "Mozart Vienna", "Beethoven symphony", "Mao China revolution", "Marie Curie radioactivity", "Darwin evolution Galapagos", "Shakespeare England plays".

- [ ] **Step 3: Write coverage validator**

```python
# tests/dispatch_eval/check_probe_coverage.py
"""Validate the probe set meets per-class minimum coverage (Criterion F)."""

import json
from collections import Counter
from pathlib import Path


REQUIRED_CLASSES = {
    "Z1", "Z2", "Z3", "Z4", "OPP-1", "Sub-pattern-C", "filler-prose", "possessive",
    "zim_get-toc", "zim_get-summary", "zim_get-structure", "zim_get-binary",
    "zim_get-main-page", "zim_get-batch", "zim_browse-page", "zim_browse-walk",
    "zim_metadata", "zim_links-outbound", "zim_links-related", "zim_health",
}

MIN_PER_CLASS = 20


def main():
    probes = [json.loads(line) for line in Path("tests/dispatch_eval/probes.jsonl").read_text().splitlines() if line.strip()]
    counts = Counter()
    z4_zim_query_preferred = 0
    for p in probes:
        for cls in p["operational_classes"]:
            counts[cls] += 1
        if "Z4" in p["operational_classes"] and p["tool_eligibility"] == "zim_query_preferred":
            z4_zim_query_preferred += 1

    failures = []
    for cls in REQUIRED_CLASSES:
        if counts[cls] < MIN_PER_CLASS:
            failures.append(f"{cls}: {counts[cls]} (need {MIN_PER_CLASS})")
    if z4_zim_query_preferred < 20:
        failures.append(f"Z4 zim_query_preferred: {z4_zim_query_preferred} (need 20 for Criterion C3)")

    if failures:
        print("PROBE COVERAGE FAILURE:")
        for f in failures:
            print(f"  - {f}")
        raise SystemExit(1)
    print(f"OK: {len(probes)} probes, all {len(REQUIRED_CLASSES)} classes meet ≥{MIN_PER_CLASS} threshold.")
    print(f"OK: {z4_zim_query_preferred} Z4 zim_query_preferred probes for Criterion C3.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run coverage check, commit**

```bash
python tests/dispatch_eval/check_probe_coverage.py
git add tests/dispatch_eval/probes.jsonl tests/dispatch_eval/check_probe_coverage.py
git commit -m "data(gate-0b): 300-probe gold-labeled dispatch eval set"
```

### Task B3a: Curate the 25-probe b-series stabilization subset

**Files:**

- Create: `tests/dispatch_eval/data/b_series_25.jsonl`

A smoke-test subset for fast defect triage between Stage E sweep iterations. NOT the stabilization-gate signal (Stage E pass criteria use the full b1 → b13 set).

- [ ] **Step 1: Curate 25 representative probes** spanning the b-series defect classes with at least 2× Z4 coverage.

- [ ] **Step 2: Commit**

```bash
git add tests/dispatch_eval/data/b_series_25.jsonl
git commit -m "data(gate-0b): 25-probe b-series smoke-test subset"
```

### Task B3b: Author the model system prompt

**Files:**

- Create: `tests/dispatch_eval/system_prompt.md`

The system prompt drives both Qwen-2.5-7B (primary) and Haiku-4.5 (secondary). Identical across cells so dispatch comparison is fair.

- [ ] **Step 1: Write the prompt** — short instructional preamble framing the model as an MCP-tool-using assistant for ZIM archive lookup. No exemplars (would bias dispatch toward specific tools).

- [ ] **Step 2: Commit**

```bash
git add tests/dispatch_eval/system_prompt.md
git commit -m "data(gate-0b): system prompt for dispatch eval"
```

### Task B4: Build the dispatch-eval runner

**Files:**

- Create: `tests/dispatch_eval/runner.py`

The runner boots the MCP server with a chosen variant × mode cell, drives the model with the system prompt + probe query, and records per-probe outcomes.

- [ ] **Step 1: Write the runner** — CLI surface:

```bash
python tests/dispatch_eval/runner.py \
  --variant {b13,phase-f} \
  --mode {simple,advanced} \
  --model {qwen2.5-7b-instruct,haiku-4.5} \
  --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output /tmp/<variant>__<mode>__<model>__<timestamp>.jsonl
```

For each probe × rep:

1. Boot the MCP server (in-process or subprocess) with the chosen variant + mode.
2. Send the system prompt + probe query to the model.
3. Capture the model's tool call: tool name, parameters, raw response.
4. Record per-probe outcome row: `{probe_id, rep, tool_called, parameters, parameters_validity, dispatch_correct, resolved_entry_path, spurious_route, ...}`.

For `zim_query_preferred` probes: if the model called `zim_search(mode="title")`, mark `spurious_route=True` and compare resolved entries.

**Per-model tool-call parser dispatch.** Different model families emit tool-call payloads in different formats. The runner MUST dispatch by the `--model` flag value:

| `--model` prefix | Tool-call format | Notes |
| --- | --- | --- |
| `qwen*` | Hermes JSON (vLLM `--tool-call-parser hermes`) | Default for Qwen-2.5-7B primary AND for Qwen-2.5-3B if used as the quaternary substitute. |
| `llama-3*` | Llama 3 JSON (vLLM `--tool-call-parser llama3_json`) | Required for the Llama-3.1-8B tertiary; missing this maps tool calls to malformed-JSON and reports 100% parameter-validity failure that looks like a Llama regression but is a wiring bug. |
| `phi-3.5*` | Python-flavored (vLLM `--tool-call-parser pythonic`, requires vLLM ≥0.6.2) | Required for the Phi-3.5-mini quaternary. Same wiring-bug risk: missing parser → reports as a Phi regression. If `pythonic` is broken in the deployer's vLLM, substitute Qwen-2.5-3B (covered by the `qwen*` row) and record the substitution in the gate decision JSON. |
| `haiku*`, `claude*` | Anthropic SDK's `tool_use` content block | Native parsed JSON from the SDK; no extra adapter needed. |

The dispatch lives in `runner.py` as a `_parse_tool_call(model, raw_response)` helper. Adding a future model family is a small per-family branch (≤10 lines).

**Filename convention:** `<variant>__<mode>__<model>__<timestamp>.jsonl` (double-underscore separator).

- [ ] **Step 2: Commit**

```bash
git add tests/dispatch_eval/runner.py
git commit -m "test(gate-0b): dispatch eval runner"
```

### Task B5: Build the non-inferiority analysis script

**Files:**

- Create: `tests/dispatch_eval/analyze.py`

The analyzer takes per-cell outcome JSONL files and emits the criterion verdicts: Criteria A, B, C1, C2, C3, D, F1, F2.

- [ ] **Step 1: Write the analyzer**

```python
"""Gate 0b non-inferiority analyzer.

Reads per-cell outcome JSONL files. Emits criterion verdicts per
the spec's tiered decision rule.

Margins (sample-size-aware):
  Primary (Qwen-7B, 100% coverage, n=300/cell): 5pp non-inferiority on A/B/D.
  Secondary (Haiku, 50% coverage, n=150/cell): 10pp non-inferiority on A/B/D.
  Tertiary (Llama-8B, 50% coverage, n=150/cell): 10pp non-inferiority on A/B/D.
  Quaternary (Phi-3.5-mini, 50% coverage, n=150/cell, reps=5 for matched power):
    10pp non-inferiority on A/B/D — matched to tertiary. Size-induced variance
    handled via increased rep count (reps cheap on 3.8B) rather than wider margin,
    because the sub-4B size class is the deployment population most at risk
    from the surface change.

Per-class (F1): 8pp ceiling for b-series hardened classes.
Per-class (F2): 10pp ceiling for new Phase F operation classes (tightened
  from 15pp — at 10pp a real per-class regression remains detectable rather
  than camouflaged by the larger margin). Enforced at BOTH Gate 0b AND
  Stage E Task E3 — the prototype-to-rc1 rewrite is the riskiest moment
  in the timeline for localized per-class regressions.

Criterion C (dispatch-confusion):
  C1: answer-degrading spurious-routing rate ≤ 5% (zim_query_preferred denominator).
  C2: of probes that misroute, the fraction whose resolved entry differs ≤ 30%.
       Computed when confusion-conditional subset has ≥10 events.
  C3: Z4-tagged zim_query_preferred probes — answer-degrading rate ≤ 5% absolute.
       Computed when Z4 subset has ≥20 events.
  ALL THREE re-checked on the fallback cell if wired-C fails — the legibility
  fix must demonstrably reduce routing harm without introducing new dispatch
  confusion. Fallback ships only if all three of fallback_c1_pass /
  fallback_c2_pass / fallback_c3_pass are true (or null+hand-audit for
  underpowered C2).
"""

# F1 classes (b-series hardened):
F1_CLASSES = {"Z1", "Z2", "Z3", "Z4", "OPP-1", "Sub-pattern-C", "filler-prose", "possessive"}
# F2 classes (new at Phase F):
F2_CLASSES = {"zim_get-toc", "zim_get-summary", "zim_get-structure", "zim_get-binary",
              "zim_get-main-page", "zim_get-batch", "zim_browse-page", "zim_browse-walk",
              "zim_metadata", "zim_links-outbound", "zim_links-related", "zim_health"}

PRIMARY_MARGIN = 0.05
SECONDARY_MARGIN = 0.10
TERTIARY_MARGIN = 0.10
QUATERNARY_MARGIN = 0.10  # matched to tertiary; size-induced variance addressed via reps=5
F1_CEILING = 0.08
F2_CEILING = 0.10  # tightened from 0.15 per review
C1_CEILING = 0.05
C2_CEILING = 0.30
C2_MIN_EVENTS = 10
C3_CEILING = 0.05
C3_MIN_EVENTS = 20

# ... non-inferiority test + criterion rendering ...
```

**CLI surface.** The analyzer accepts three modes, switched by flag:

```bash
# Default: full gate decision (Stage C Task C3 Step 1)
python tests/dispatch_eval/analyze.py \
  --b13-runs <glob> --phase-f-runs <glob> \
  --output tests/dispatch_eval/gate_0b_decision.json

# Fallback C1+C2+C3 re-check (Stage C Task C3 Step 3)
python tests/dispatch_eval/analyze.py \
  --b13-runs <glob> --phase-f-runs <glob> \
  --fallback-c3-check \
  --output-update tests/dispatch_eval/gate_0b_decision.json
# Flag name retained for backwards compatibility, but computes ALL THREE of
# fallback_c1_pass, fallback_c2_pass, fallback_c3_pass on the fallback cells
# and writes them into the existing decision artifact. Does NOT re-write
# A/B/C/D/F wired-path verdicts — those stay committed from the wired run.
# fallback_c2_pass may be null if the conditional subset on the fallback cell
# had <10 events; hand-audit required (record in secondary_observational_failures).

# Sweep mode (Stage E Task E1)
python tests/dispatch_eval/analyze.py \
  --sweep-mode --runs <run.jsonl> [--check-divergence <other.jsonl>]
# Reports per-class deltas vs the committed b13 baseline; with
# --check-divergence, also flags model-disagreement on per-probe outcomes
# between primary and secondary/tertiary/quaternary runs.

# F2 enforcement only (Stage E Task E3 Step 3)
python tests/dispatch_eval/analyze.py \
  --b13-runs <glob> --phase-f-runs <glob> \
  --f2-enforcement-only \
  --output /tmp/rc1_f2_verdict.json
# Computes per-class F2 deltas on rc1 vs b13 baseline, skipping A/B/C/D
# verdicts (those are owned by Gate 0b). Writes a focused F2-only verdict.
# Pass criterion: every F2 class delta ≥ -10pp on the primary model.
```

- [ ] **Step 2: Write `tests/dispatch_eval/test_analyze.py`** — unit tests pinning the analyzer's verdict logic on synthetic per-cell outcomes (so a future refactor doesn't silently change the gating math).

- [ ] **Step 3: Commit**

```bash
git add tests/dispatch_eval/analyze.py tests/dispatch_eval/test_analyze.py
git commit -m "test(gate-0b): non-inferiority analyzer + unit tests"
```

### Task B6: (REMOVED — moved to Stage 0 / Task Z1)

The transport `oneOf` check is now Gate 0.2, lands on the `v2-phase-f-gate-0` branch before rc0.

### Task B7: Inference plumbing (Qwen primary + Haiku secondary + Llama tertiary + Phi quaternary)

**Files:**

- Document: `tests/dispatch_eval/inference_setup.md`

- [ ] **Step 1: Write the inference setup doc**

````markdown
# Inference setup (Gate 0b)

## Primary: Qwen-2.5-7B-Instruct (100% of cells)

Local inference via vLLM (preferred) or llama.cpp.

```bash
# vLLM single-GPU
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct \
  --tool-call-parser hermes \
  --enable-auto-tool-choice \
  --port 8000
```

Runner connects via OpenAI-compatible API at `http://localhost:8000/v1`.

## Secondary (Anthropic-family): Haiku-4.5 (50% of cells)

```bash
export ANTHROPIC_API_KEY=<key>
# runner picks haiku-4.5 via --model flag; no extra setup
```

## Tertiary (architecturally-distinct open-weights): Llama-3.1-8B-Instruct (50% of cells)

**Prerequisites — license + access.** Meta's Llama 3.1 weights are gated. Before any inference run, the operator must:

1. Accept the Llama 3.1 Community License at https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct (logged-in HuggingFace account required).
2. Generate a HuggingFace access token with `read` scope at https://huggingface.co/settings/tokens.
3. `export HF_TOKEN=<token>` in the shell that boots vLLM.

If the license has not been accepted, vLLM's first download attempt 403s with a HuggingFace error — fail-fast, not a silent skip. Operators who can't accept the license set `tertiary_status: "unavailable"` per the disagreement rule.

**Tool-call format.** Llama 3.1 emits tool calls in a JSON format distinct from Qwen's hermes parser. The Task B4 runner must dispatch by `--model` flag to the right parser — `hermes` for `qwen*`, `llama3_json` for `llama-3*`. Anthropic-API responses (Haiku) are already JSON via the SDK; no parser dispatch needed. The runner's per-model adapter is small (≤20 lines) but MUST exist — a missing adapter means Llama's tool-call payloads parse as malformed and the runner reports 100% parameter-validity failure on every probe, which would look like a Llama-architecture regression but is actually a wiring bug.

Local inference via vLLM. **Cannot share a single GPU with the Qwen server** — they bind separate processes and the vLLM workers consume the full GPU. Two options:

```bash
# Option A: Sequential runs on a single GPU
# Run Qwen cells to completion, kill the Qwen server, boot Llama:
kill $(pgrep -f Qwen2.5-7B-Instruct)
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --tool-call-parser llama3_json \
  --enable-auto-tool-choice \
  --port 8001

# Option B: Two GPUs (preferred if available)
# Boot Llama on a second GPU concurrently with Qwen on the first:
CUDA_VISIBLE_DEVICES=1 python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --tool-call-parser llama3_json \
  --enable-auto-tool-choice \
  --port 8001 &
```

Runner connects to Llama via OpenAI-compatible API at `http://localhost:8001/v1`.

**If Llama is unavailable** (no second-GPU capacity AND insufficient time for sequential runs), set `tertiary_status: "unavailable"` in the gate decision artifact with a brief justification per spec §Gate 0b disagreement rule. This is a documented decision, not a silent skip — Llama coverage is the explicit response to the "Qwen-family overfit" risk.

## Quaternary (sub-7B size class): Phi-3.5-mini-instruct (50% of cells)

**Why a fourth model.** Llama-8B covers the architecture-diversity axis at the same size as Qwen-7B. The sub-7B size class — where schema-handling quality is known to fall off sharply — is the actual deployment boundary for the "small models" claim. Phi-3.5-mini at 3.8B is the strongest tool-using sub-4B open-weights model and ships under MIT license (no HuggingFace gating like Llama). It doubles as a third architecturally-distinct family (Microsoft, ≠ Qwen, ≠ Meta).

**Prerequisites.** None for license — Phi-3.5 is MIT-licensed and freely pullable from HuggingFace without an access token. (Contrast with Llama-3.1 which requires accepting the Meta license + having an `HF_TOKEN` per the tertiary section above.)

**Tool-call format.** Phi-3.5 emits tool calls in a Python-flavored format. vLLM exposes this via `--tool-call-parser pythonic` (requires vLLM ≥0.6.2). The runner's `_parse_tool_call(model, raw_response)` dispatch (see Task B4) routes `--model phi-3.5*` to the pythonic parser.

**Substitution fallback if `pythonic` parser is broken.** vLLM tool-call parsing for Phi has had rough edges in older versions. If the deployer's vLLM version doesn't cleanly produce structured tool calls from Phi-3.5 (manifest: every probe returns 100% parameter-validity failure with parser-error reasons), substitute **Qwen-2.5-3B-Instruct** instead:

```bash
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-3B-Instruct \
  --tool-call-parser hermes \
  --enable-auto-tool-choice \
  --port 8002
```

Qwen-3B uses the same `hermes` parser as the Qwen-7B primary, so the runner adapter table doesn't need a new branch. The substitution costs the architecture-diversity-at-small-size signal but preserves the size signal. Record the substitution in `gate_0b_decision.json` under `quaternary_model_substituted: "qwen-2.5-3b-instruct"`.

**Boot Phi (preferred):**

```bash
# Phi-3.5-mini is small enough to share a single GPU with Qwen-7B on >=24GB VRAM
# IF vLLM is configured with gpu_memory_utilization tuned. Easier path: sequential
# runs (kill Qwen first), or third GPU.
python -m vllm.entrypoints.openai.api_server \
  --model microsoft/Phi-3.5-mini-instruct \
  --tool-call-parser pythonic \
  --enable-auto-tool-choice \
  --port 8002
```

Runner connects to Phi via OpenAI-compatible API at `http://localhost:8002/v1`.

**If Phi is unavailable** (no GPU capacity AND no time for sequential runs AND substitution refused), set `quaternary_status: "unavailable"` per spec §Gate 0b disagreement rule. Same documented-decision discipline as Llama: this is the response to the sub-7B-size blind spot, and going without it surfaces the limitation in the decision artifact rather than burying it.

## Cell coverage

- **Qwen** runs ALL 4 default cells (b13×simple, b13×advanced, phase-f×simple, phase-f×advanced) + 1 conditional fallback cell (`phase-f-fallback × advanced`) if Criterion C fails.
- **Haiku** runs 2 of 4 — `phase-f×advanced` (load-bearing for Criterion D) and `b13×advanced` (baseline) — for cross-validation. Skips simple cells.
- **Llama** runs the same 2 of 4 cells as Haiku — `phase-f×advanced` and `b13×advanced` — plus the conditional `phase-f-fallback × advanced` if Criterion C fails.
- **Phi** runs the same 2 of 4 cells as Haiku/Llama — `phase-f×advanced` and `b13×advanced` — plus the conditional `phase-f-fallback × advanced` if Criterion C fails. The sub-7B size class is part of "small model" the spec claims to support, so Z4 C3/C2/C1 re-checks include Phi.
````

- [ ] **Step 2: Commit**

```bash
git add tests/dispatch_eval/inference_setup.md
git commit -m "docs(gate-0b): inference setup for Qwen primary + Haiku secondary"
```

---

## Stage C — Gate 0b Runs + Decision

### Task C1: Run b13 baseline cells

- [ ] **Step 1: Boot Qwen, run b13 × simple + b13 × advanced cells**

```bash
# In the b13 worktree (or main if b13 has been merged):
git worktree add /tmp/b13-worktree v2.0.0b13
cd /tmp/b13-worktree

# Boot Qwen as in Task B7

python tests/dispatch_eval/runner.py \
  --variant b13 --mode simple --model qwen2.5-7b-instruct --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/b13__simple__qwen.jsonl

python tests/dispatch_eval/runner.py \
  --variant b13 --mode advanced --model qwen2.5-7b-instruct --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/b13__advanced__qwen.jsonl
```

- [ ] **Step 2: Run Haiku secondary on b13 × advanced only** (cross-validation baseline)

```bash
python tests/dispatch_eval/runner.py \
  --variant b13 --mode advanced --model haiku-4.5 --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/b13__advanced__haiku.jsonl
```

- [ ] **Step 3: Run Llama tertiary on b13 × advanced** (architectural cross-validation baseline)

```bash
# Boot Llama per Task B7 inference_setup.md (skip if tertiary_status=unavailable).
python tests/dispatch_eval/runner.py \
  --variant b13 --mode advanced --model llama-3.1-8b-instruct --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/b13__advanced__llama.jsonl
```

- [ ] **Step 4: Run Phi quaternary on b13 × advanced** (sub-7B size-class baseline)

```bash
# Boot Phi per Task B7 inference_setup.md (or Qwen-3B if substituted; skip if quaternary_status=unavailable).
python tests/dispatch_eval/runner.py \
  --variant b13 --mode advanced --model phi-3.5-mini-instruct --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/b13__advanced__phi.jsonl
```

- [ ] **Step 5: Commit baselines to the prototype branch**

```bash
git add tests/dispatch_eval/runs/
git commit -m "data(gate-0b): b13 baseline runs (Qwen + Haiku + Llama + Phi)"
```

### Task C2: Run phase-f cells

- [ ] **Step 1: Switch to the prototype branch, run phase-f × simple + phase-f × advanced cells with Qwen**

```bash
git checkout v2-phase-f-prototype

python tests/dispatch_eval/runner.py \
  --variant phase-f --mode simple --model qwen2.5-7b-instruct --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/phase-f__simple__qwen.jsonl

python tests/dispatch_eval/runner.py \
  --variant phase-f --mode advanced --model qwen2.5-7b-instruct --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/phase-f__advanced__qwen.jsonl
```

- [ ] **Step 2: Run Haiku secondary on phase-f × advanced**

```bash
python tests/dispatch_eval/runner.py \
  --variant phase-f --mode advanced --model haiku-4.5 --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/phase-f__advanced__haiku.jsonl
```

- [ ] **Step 3: Run Llama tertiary on phase-f × advanced**

```bash
# Boot Llama per Task B7 inference_setup.md (skip if tertiary_status=unavailable).
python tests/dispatch_eval/runner.py \
  --variant phase-f --mode advanced --model llama-3.1-8b-instruct --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/phase-f__advanced__llama.jsonl
```

- [ ] **Step 4: Run Phi quaternary on phase-f × advanced**

```bash
# Boot Phi per Task B7 inference_setup.md (or Qwen-3B if substituted; skip if quaternary_status=unavailable).
python tests/dispatch_eval/runner.py \
  --variant phase-f --mode advanced --model phi-3.5-mini-instruct --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/phase-f__advanced__phi.jsonl
```

- [ ] **Step 5: Commit**

```bash
git add tests/dispatch_eval/runs/
git commit -m "data(gate-0b): phase-f prototype runs (Qwen + Haiku + Llama + Phi)"
```

### Task C3: Apply decision rule + commit gate_0b_decision.json

- [ ] **Step 1: Run the analyzer**

```bash
python tests/dispatch_eval/analyze.py \
  --b13-runs tests/dispatch_eval/runs/b13__*.jsonl \
  --phase-f-runs tests/dispatch_eval/runs/phase-f__*.jsonl \
  --output tests/dispatch_eval/gate_0b_decision.json
```

The analyzer writes a JSON object with shape:

```json
{
  "gate_passed": true,
  "default_tool_mode": "simple",
  "criterion_c_path": "wired",
  "gate_0_schema_shape": "wired_oneof",
  "gate_0_3_verdict": "validated",
  "criteria": {
    "A": {
      "primary": {"pass": true, "delta_pp": -1.2},
      "secondary": {"pass": true, "delta_pp": -3.4},
      "tertiary": {"pass": true, "delta_pp": -4.1},
      "quaternary": {"pass": true, "delta_pp": -6.8}
    },
    "B": {
      "primary": {"pass": true, "delta_pp": -0.8},
      "secondary": {"pass": true, "delta_pp": -2.1},
      "tertiary": {"pass": true, "delta_pp": -2.9},
      "quaternary": {"pass": true, "delta_pp": -5.3}
    },
    "C1": {"pass": true, "rate": 0.034},
    "C2": {"pass": true, "rate": 0.21, "events": 23},
    "C3": {"pass": true, "rate": 0.045, "events": 26},
    "D": {
      "primary": {"pass": true, "delta_pp": -1.2},
      "secondary": {"pass": true, "delta_pp": -3.4},
      "tertiary": {"pass": true, "delta_pp": -4.1},
      "quaternary": {"pass": true, "delta_pp": -6.8}
    },
    "F1": {"pass": true, "per_class_deltas": {"Z1": -2, "Z2": -1, "Z3": -3, "Z4": -4, ...}},
    "F2": {"pass": true, "per_class_deltas": {"zim_get-toc": -6, "zim_browse-walk": -8, ...}}
  },
  "secondary_status": "available",
  "tertiary_status": "available",
  "quaternary_status": "available",
  "quaternary_model_substituted": null,
  "secondary_blocking_failures": [],
  "secondary_observational_failures": [],
  "tertiary_blocking_failures": [],
  "tertiary_observational_failures": [],
  "quaternary_blocking_failures": [],
  "quaternary_observational_failures": [],
  "fallback_c1_pass": null,
  "fallback_c2_pass": null,
  "fallback_c3_pass": null,
  "scope_limitations": [
    "probe-distribution: wikipedia-dominant",
    "model-coverage: qwen-7b + llama-8b + phi-3.5-mini + haiku-4.5",
    "size-range: 3.8B–8B (open-weights)",
    "probe-language: english-only"
  ],
  "criterion_f1_class_failures": [],
  "criterion_f2_class_failures": []
}
```

`fallback_c1_pass` / `fallback_c2_pass` / `fallback_c3_pass` are each `null` if the wired path passed C and the fallback didn't run; populated as `true`/`false` only when the fallback cell runs (Step 3 below). `fallback_c2_pass` may also be `null` after a fallback run if the confusion-conditional subset had <10 events — hand-audit required, gate authors record the audit verdict in `secondary_observational_failures` for traceability.

`quaternary_model_substituted` is `null` if Phi-3.5-mini ran cleanly; populated with `"qwen-2.5-3b-instruct"` if the deployer fell back to Qwen-3B per the documented Phi substitution rule.

`scope_limitations` is required non-empty (asserted by `tests/test_phase_f_gate_decision_consistency.py`). If the deployer substituted Phi → Qwen-3B, append `"substitution: phi-3.5-mini → qwen-2.5-3b"` to surface the architecture-diversity-at-small-size signal trade.

- [ ] **Step 2: Apply tiered decision rule**

| Outcome | Action |
| --- | --- |
| Criterion D fails (`phase-f` regresses against `b13` in advanced mode, beyond margin on any of Qwen/Haiku/Llama/Phi at their respective margins) | STOP. rc1 does not open. Investigate which probes regress; amend spec or prototype; re-run Gate 0b. |
| Any of C1/C2/C3 fails on the wired path | Apply pre-decided Criterion C circuit-breaker (legibility fallback). Re-run `phase-f-fallback × advanced` cell on Qwen + Haiku + Llama + Phi. **Compute fallback-C1 AND fallback-C2 AND fallback-C3.** If A/B/D/F all pass AND ALL of `fallback_c1_pass` / `fallback_c2_pass` / `fallback_c3_pass` are true (or null+hand-audit for underpowered C2), open rc1 with `criterion_c_path: "fallback"`. If any of fallback-C1/C2/C3 is false, STOP — the legibility-fix premise has failed (the fix either didn't reduce harm or introduced new confusion); gate authors choose between **(a) dropping title mode from advanced entirely or (b) returning to design.** Shipping a known Z4 silent-wrong-answer harm is NOT an option — the b-series spent 17 sweeps eliminating exactly this regression class. (Per spec §Criterion C circuit-breaker decision flow.) |
| Criterion F1 fails on any b-series class | Investigate. Localized fix (a leaked behavior in the rc0 wrapper, a removed routing hint). rc1 does not open until all F1 classes pass. |
| Criterion F2 fails on any Phase F class | Investigate. F2 ceiling is 10pp (tightened from 15pp); a class failing here likely means dispatch confusion within the collapsed surface (e.g., `view="toc"` vs `view="summary"`) — fix the description prose or `oneOf` shape, re-run. rc1 does not open until F2 classes pass. |
| Haiku secondary failure on A/B/D at the ≥10pp margin | BLOCKS rc1. Write `tests/dispatch_eval/qwen_haiku_divergence.md` and either fix the prototype to pass on both, or amend the spec acknowledging the surface targets one population only. |
| Llama tertiary failure on A/B/D at the ≥10pp margin | BLOCKS rc1. Write `tests/dispatch_eval/qwen_llama_divergence.md`. A Qwen-pass / Llama-fail signals open-weights family overfitting (the "small models" claim only holds for Qwen); same resolution options. |
| Phi quaternary failure on A/B/D at the ≥10pp margin | BLOCKS rc1. Write `tests/dispatch_eval/qwen_phi_divergence.md`. A Qwen-pass / Phi-fail signals size-overfit (the "small models" claim holds at 7-8B but not below); same resolution options. |
| Haiku OR Llama OR Phi failure on C1/C2/C3 | BLOCKS rc1. C-criteria are rate ceilings, not non-inferiority comparisons. Z4 harm is family-agnostic AND size-agnostic. |
| Haiku OR Llama OR Phi observational failures on F1/F2 | Documented under `secondary_observational_failures` / `tertiary_observational_failures` / `quaternary_observational_failures`; investigated but not blocking. |
| Tertiary status unavailable | DOES NOT block. Documented in `tertiary_status: "unavailable"` with brief justification. The architecture-overfit risk is acknowledged unmeasured. |
| Quaternary status unavailable | DOES NOT block. Documented in `quaternary_status: "unavailable"` with brief justification. The sub-7B-size blind spot is acknowledged unmeasured. |
| All pass | Proceed to Stage D with the recorded `criterion_c_path`, `gate_0_schema_shape`, `gate_0_3_verdict`, and `scope_limitations`. |

- [ ] **Step 3: Run Criterion C fallback cell if needed (Qwen + Haiku + Llama + Phi)**

```bash
# Set the fallback env var, re-run phase-f advanced on all four models.
# All of fallback-C1/C2/C3 are the load-bearing new checks: does the legibility fix
# actually reduce routing harm (C1/C2) AND not introduce new dispatch confusion (C2),
# AND does it stop Z4 misroutes specifically (C3)?

OZM_CRITERION_C_PATH=fallback python tests/dispatch_eval/runner.py \
  --variant phase-f-fallback --mode advanced --model qwen2.5-7b-instruct --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/phase-f-fallback__advanced__qwen.jsonl

OZM_CRITERION_C_PATH=fallback python tests/dispatch_eval/runner.py \
  --variant phase-f-fallback --mode advanced --model haiku-4.5 --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/phase-f-fallback__advanced__haiku.jsonl

OZM_CRITERION_C_PATH=fallback python tests/dispatch_eval/runner.py \
  --variant phase-f-fallback --mode advanced --model llama-3.1-8b-instruct --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/phase-f-fallback__advanced__llama.jsonl

OZM_CRITERION_C_PATH=fallback python tests/dispatch_eval/runner.py \
  --variant phase-f-fallback --mode advanced --model phi-3.5-mini-instruct --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/phase-f-fallback__advanced__phi.jsonl

python tests/dispatch_eval/analyze.py \
  --b13-runs tests/dispatch_eval/runs/b13__advanced__*.jsonl \
  --phase-f-runs tests/dispatch_eval/runs/phase-f-fallback__advanced__*.jsonl \
  --fallback-c3-check \
  --output-update tests/dispatch_eval/gate_0b_decision.json
```

`--fallback-c3-check` is the dedicated analyzer flag — despite the name (kept for backwards compatibility with Task B5's CLI surface table), it computes ALL THREE of `fallback_c1_pass`, `fallback_c2_pass`, `fallback_c3_pass` on the fallback cells and writes them into the decision artifact. The `*` glob picks up whichever models actually ran (skip cells for unavailable tertiary/quaternary).

- [ ] **Step 4: Commit decision artifact**

```bash
git add tests/dispatch_eval/gate_0b_decision.json
git commit -m "decision(gate-0b): verdict and per-criterion outcomes"
```

The prototype branch is NOT merged. Only the decision artifact + per-cell runs travel to rc1 via cherry-pick.

- [ ] **Step 5: Pin prototype HEAD as permanent annotated tag**

The prototype branch is throwaway scaffolding — it exists to produce the Gate 0b measurements and is never merged. After cherry-pick to rc1, the branch is logically abandoned and may be pruned by GitHub's branch-cleanup automation or a future `git gc`. If a post-v2.0 regression requires re-running Gate 0b under matched conditions (same surface, same probes, same vLLM/Anthropic-API revisions), the operator needs to either resurrect the prototype branch from reflogs or rebuild it from scratch — both error-prone.

**Pin the prototype HEAD as an annotated tag so it's never garbage-collected:**

```bash
git tag -a v2.0.0-gate-0b-prototype -m "Gate 0b prototype HEAD; preserved for Gate 0b reproducibility. \
Surface measured: 8-tool Phase F per <prototype-decision-commit-sha>. \
Decision artifact: tests/dispatch_eval/gate_0b_decision.json. \
Snapshot: tests/dispatch_eval/prototype_schema_snapshot.json."
git push origin v2.0.0-gate-0b-prototype
```

The tag is annotated (not lightweight) so the message carries the audit trail. A future operator running Gate 0b under matched conditions checks out `v2.0.0-gate-0b-prototype` directly — no archaeology required.

Document the tag's purpose in the rc0 PR description and in the v2.0.0 release notes under "reproducibility":

```markdown
**Gate 0b reproducibility.** The prototype branch HEAD used for Gate 0b is preserved as the
annotated tag `v2.0.0-gate-0b-prototype`. Re-running Gate 0b under matched conditions:
1. `git checkout v2.0.0-gate-0b-prototype`
2. Boot inference per `tests/dispatch_eval/inference_setup.md` (note: pin vLLM + model versions
   against the originals if reproducing exactly).
3. Re-run `tests/dispatch_eval/runner.py` against `tests/dispatch_eval/probes.jsonl`.
```

---

## Stage D — `v2.0.0rc1` Surface Implementation

**Goal:** lands the 8-tool surface on a fresh branch from rc0 (now signed off). Cherry-picks the Gate 0b decision artifact and per-cell runs from the prototype branch. Implements the 8 per-tool modules with schema-conditional `oneOf` (or flat schemas, per Gate 0).

### Task D0: Create `v2-phase-f-rc1` branch + cherry-pick decision

- [ ] **Step 1: Branch from rc0**

```bash
git checkout v2.0.0rc0
git checkout -b v2-phase-f-rc1
```

- [ ] **Step 2: Cherry-pick the Gate 0b decision artifact + run data + prototype schema snapshot**

```bash
git cherry-pick <prototype-decision-commit-sha>
git cherry-pick <prototype-runs-commit-sha>
git cherry-pick <prototype-snapshot-commit-sha>  # tests/dispatch_eval/prototype_schema_snapshot.json
```

The probe set + runner + analyzer + decision artifact + prototype wire-footprint snapshot land on rc1; the skeleton tool modules (which were prototype-only and delegated to legacy code) do NOT cherry-pick — rc1 writes the real implementations from scratch. The snapshot is the rc1 author's contract: per-tool wire footprints must stay within ±5% bytes and inputSchema shape must be structurally identical to what the prototype emitted, enforced by [Task D14b](#task-d14b-prototype-rc1-schema-parity-test).

**Cherry-pick conflict handling.** All cherry-picked files live under `tests/dispatch_eval/` (decision JSON, per-cell run JSONLs, schema snapshot). The prototype branch was created from `v2.0.0rc0` (Task B1) and Stage B authored these files fresh — they're not modifying anything rc0 owns. Conflicts are therefore unlikely. **Conflict resolution is asymmetric — favor "prototype" only for files whose value is "this is what Gate 0b measured":**

| File | Conflict-resolution rule | Why |
| --- | --- | --- |
| `tests/dispatch_eval/gate_0b_decision.json` | Favor prototype-branch version. | Load-bearing Gate 0b verdict artifact. Any main-side edit to it post-rc0 is illegitimate (Gate 0b ran once on the prototype; the decision can't change without re-running). |
| `tests/dispatch_eval/runs/*.jsonl` | Favor prototype-branch version. | The per-cell run data is the source of truth for the decision artifact. |
| `tests/dispatch_eval/prototype_schema_snapshot.json` | Favor prototype-branch version. | The schema-parity test's source of truth (Task D14b). |
| `tests/dispatch_eval/probes.jsonl` | **Three-way merge required.** Take both sides of the change set semantically — keep the prototype's probe set composition AND any new probes added on main between rc0 sign-off and rc1 branching. Then re-run Gate 0b for the new probes against the prototype's surface (small, targeted re-run) and update `gate_0b_decision.json` accordingly. | Probe-set improvements landed on main between rc0 sign-off and rc1 branching represent real domain knowledge (e.g., a sweep-discovered Z4 shape) — silently rolling them back via the "favor prototype" rule would discard hardening work. |
| `tests/dispatch_eval/data/b1_b13_probes.jsonl` | Same as `probes.jsonl` — three-way merge. | The cumulative b-series set is actively maintained; new probes added on main are real improvements, not conflicts. |
| `tests/dispatch_eval/runner.py`, `tests/dispatch_eval/analyze.py` | Take both sides. Test that both pass after merge. | Both are infrastructure code; main-side improvements (bug fixes, new analyzer modes) should land. |

After conflict resolution, MUST run `pytest tests/test_phase_f_gate_decision_consistency.py` AND `pytest tests/test_phase_f_prototype_parity.py` (with `--dispatch-eval` opt-in if the parity test needs the harness) to confirm the merged tree is internally consistent. Any unrelated `tests/dispatch_eval/` work that resists resolution should be re-applied as a follow-up commit on the rc1 branch with an explicit note in the PR description.

### Task D1: Add response types to `tool_schemas.py`

**Files:**

- Modify: `openzim_mcp/tool_schemas.py`

- [ ] **Step 1: Add `ArchiveMetadataResponse`**

```python
class ArchiveMetadataResponse(TypedDict):
    metadata: dict[str, str]
    namespaces: list[NamespaceInfo]
    _meta: MetaEnvelope
```

- [ ] **Step 2: Enrich `ServerHealthResponse`** with `loaded_archives`

```python
class ServerHealthResponse(TypedDict):
    health: HealthStatus
    configuration: ServerConfig
    loaded_archives: list[ArchiveInfo]
    _meta: MetaEnvelope
```

- [ ] **Step 3: Commit**

```bash
git add openzim_mcp/tool_schemas.py
git commit -m "feat(rc1): add ArchiveMetadataResponse + enrich ServerHealthResponse"
```

### Task D2: Add `async_operations.py` combined wrappers

**Files:**

- Modify: `openzim_mcp/async_operations.py`
- Create: `tests/test_async_operations_combined.py`

- [ ] **Step 1: Add `get_health_data` and `get_archive_metadata_data`** — each composes existing single-purpose data calls.

- [ ] **Step 2: Unit tests** — verify each new wrapper assembles the expected combined response.

- [ ] **Step 3: Commit**

```bash
git add openzim_mcp/async_operations.py tests/test_async_operations_combined.py
git commit -m "feat(rc1): combined wrappers for zim_health and zim_metadata"
```

### Task D3: Implement `zim_query.py`

**Files:**

- Modify: `openzim_mcp/tools/zim_query.py` (replace skeleton)
- Create: `openzim_mcp/tools/zim_query_description.md` (committed description — the unchanged b13 docstring)
- Create: `tests/test_zim_query.py`

The implementation hoists the registration from `server._register_simple_tools`. The function body delegates to `SimpleToolsHandler` as today; only the registration site moves. **The description ships as a single committed file** — V0 from b13, unchanged. No V0/V1 variant machinery.

- [ ] **Step 1: Commit `zim_query_description.md`** — the unchanged b13 description from `simple_tools.py`'s `zim_query` docstring, copied verbatim.

- [ ] **Step 2: Write `zim_query.py`**

```python
"""zim_query — natural-language entry point. Phase F surface."""
from __future__ import annotations
import pathlib
from typing import Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from openzim_mcp.server import OpenZimMcpServer

# Read description at IMPORT TIME from committed file in the package itself.
_DIR = pathlib.Path(__file__).parent
_DESCRIPTION = (_DIR / "zim_query_description.md").read_text()


def register(server: "OpenZimMcpServer") -> None:
    handler = server.simple_tools_handler

    @server.mcp.tool(description=_DESCRIPTION)
    async def zim_query(
        query: str,
        zim_file_path: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        content_offset: int = 0,
        cursor: Optional[str] = None,
        max_content_length: Optional[int] = None,
        compact: bool = True,
        compact_budget: Optional[Union[str, int]] = None,
        synthesize: bool = False,
    ):
        return await handler.handle_zim_query(
            query=query,
            zim_file_path=zim_file_path,
            limit=limit,
            offset=offset,
            content_offset=content_offset,
            cursor=cursor,
            max_content_length=max_content_length,
            compact=compact,
            compact_budget=compact_budget,
            synthesize=synthesize,
        )
```

- [ ] **Step 3: Verify and configure `pyproject.toml` package data for `*.md` files**

Earlier drafts trusted `include-package-data = true` to ship Markdown; some backends require explicit globs. Do this actively:

```bash
# Check pyproject.toml for existing package-data configuration:
grep -nA10 "package-data\|package_data\|\\[tool.setuptools.package-data\\]\|include-package-data" pyproject.toml
test -f MANIFEST.in && cat MANIFEST.in
```

Add explicit `*.md` inclusion if not already there:

```toml
[tool.setuptools.package-data]
openzim_mcp = ["tools/*.md", "*.md"]
```

Build the wheel locally and inspect it:

```bash
python -m build --wheel
unzip -l dist/openzim_mcp-2.0.0rc1-py3-none-any.whl | grep zim_query_description
```

Expected: a line for `zim_query_description.md`.

Install in a fresh venv and import:

```bash
python -m venv /tmp/wheel_check && source /tmp/wheel_check/bin/activate
pip install dist/openzim_mcp-2.0.0rc1-py3-none-any.whl
python -c "from openzim_mcp.tools import zim_query; print('bytes:', len(zim_query._DESCRIPTION))"
deactivate && rm -rf /tmp/wheel_check
```

- [ ] **Step 4: Add regression test pinning packaging invariant**

```python
# tests/test_phase_f_packaging.py
"""Regression guard: the zim_query description file is packaged."""

import importlib.resources as resources
import pytest


def test_zim_query_description_packaged():
    try:
        ref = resources.files("openzim_mcp.tools").joinpath("zim_query_description.md")
        contents = ref.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError) as e:
        pytest.fail(
            f"zim_query_description.md is not packaged with openzim_mcp.tools. "
            f"Likely cause: pyproject.toml package-data does not include *.md. "
            f"Original error: {e}"
        )
    assert len(contents) > 1000, "description suspiciously small; did the file ship truncated?"
```

- [ ] **Step 5: Write `tests/test_zim_query.py`**

```python
def test_zim_query_registered_under_phase_f_orchestrator(phase_f_server):
    assert "zim_query" in phase_f_server.mcp._tool_manager._tools


async def test_zim_query_dispatches_to_simple_tools_handler(phase_f_server):
    tool = phase_f_server.mcp._tool_manager._tools["zim_query"]
    result = await tool.fn(query="test", zim_file_path=None)
    assert result is not None
```

- [ ] **Step 6: Run tests, commit**

```bash
pytest tests/test_zim_query.py tests/test_phase_f_packaging.py -v
git add openzim_mcp/tools/zim_query.py openzim_mcp/tools/zim_query_description.md tests/test_zim_query.py tests/test_phase_f_packaging.py pyproject.toml
git commit -m "feat(rc1): implement zim_query tool with committed description"
```

### Task D4: Implement `zim_search.py` (3-mode + promotion wiring)

**Files:**

- Modify: `openzim_mcp/tools/zim_search.py`
- Create: `tests/test_zim_search.py`

**Context:** Three modes (`fulltext`, `title`, `suggest`) via `mode` parameter. Schema-conditional `oneOf` exposes `namespace`/`content_type` only in `mode="fulltext"`, exposes `cross_file` only in `mode in {"fulltext","title"}`. `mode="title"` runs results through `topic_preprocessing.promote_topic_via_title_index` **when `cross_file=False`** and Gate 0b's `criterion_c_path == "wired"`.

**Criterion C path is a baked-in Python constant**, NOT a runtime read of `tests/dispatch_eval/gate_0b_decision.json`. The rc1 PR author reads the gate decision at PR time, picks the `criterion_c_path` value, and hard-codes it as `_CRITERION_C_PATH = "wired"` (or `"fallback"`) in `zim_search.py`. `tests/test_phase_f_gate_decision_consistency.py` (Task D14a) asserts the baked constant matches the committed decision file — drift between them blocks the merge. The decision file lives in `tests/` and is NOT shipped in the wheel, so production code that read it at import time would `FileNotFoundError` on the installed package.

- [ ] **Step 1: Read the Gate 0b decision and pick the constant**

```bash
python -c "
import json, pathlib
d = json.loads(pathlib.Path('tests/dispatch_eval/gate_0b_decision.json').read_text())
print('criterion_c_path:', d['criterion_c_path'])
"
```

- [ ] **Step 2: Write the tool with `_CRITERION_C_PATH` baked in**

Use the value from Step 1 as the literal in line `_CRITERION_C_PATH = "..."`. If the gate decision later changes, the rc1 commit needs amending.

```python
"""zim_search — full-text / title / suggest dispatch."""
from __future__ import annotations
from typing import Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from openzim_mcp.server import OpenZimMcpServer


# Baked-in at rc1 PR time from gate_0b_decision.json. See Task D14a — a
# gate-decision-consistency test asserts this constant matches the committed
# decision file, so drift trips before merge. Production code does NOT read
# the JSON at runtime.
_CRITERION_C_PATH: Literal["wired", "fallback"] = "wired"  # ← edit to match gate outcome


def register(server: "OpenZimMcpServer") -> None:
    from openzim_mcp.async_operations import AsyncZimOperations
    ops = AsyncZimOperations(server.zim_operations)

    @server.mcp.tool()
    async def zim_search(
        query: str,
        mode: Literal["fulltext", "title", "suggest"] = "fulltext",
        zim_file_path: Optional[str] = None,
        cross_file: bool = False,
        namespace: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        cursor: Optional[str] = None,
    ):
        """<COPY THE FULL ~2,400-BYTE DESCRIPTION FROM SPEC §2 zim_search>"""
        if mode == "fulltext":
            return await ops.search_zim_file_data(
                query=query, zim_file_path=zim_file_path, cross_file=cross_file,
                namespace=namespace, content_type=content_type,
                limit=limit, offset=offset, cursor=cursor,
            )
        if mode == "title":
            return await _handle_title_mode(
                ops, server, query, zim_file_path, cross_file, limit, offset, cursor,
            )
        if mode == "suggest":
            if cross_file:
                return _tool_error(
                    "invalid_combination",
                    hint="mode='suggest' does not support cross_file=True (libzim SuggestionSearcher is per-archive)",
                )
            return await ops.get_search_suggestions_data(
                prefix=query, zim_file_path=zim_file_path,
                limit=limit, offset=offset, cursor=cursor,
            )


async def _handle_title_mode(ops, server, query, zim_file_path, cross_file, limit, offset, cursor):
    """Title-mode dispatch with conditional preprocessing + promotion.

    Behavior depends on Gate 0b's criterion_c_path:
      - wired:    apply Tier 1 + filler-prose preprocessing AND Z3/Z4/OPP-1 promotion
                  IFF cross_file=False (promotion is per-archive)
      - fallback: pass-through; explicit-string-only title lookup
    """
    if _CRITERION_C_PATH == "fallback":
        # Legibility fallback: byte-identical query to find_entry_by_title.
        return await ops.find_entry_by_title_data(
            query=query, zim_file_path=zim_file_path, cross_file=cross_file,
            limit=limit, offset=offset, cursor=cursor,
        )

    # Wired path
    from openzim_mcp.intent_parser import IntentParser
    preprocessed = IntentParser._apply_misspelling_map(query)
    preprocessed = IntentParser._detect_stopword_phrase(preprocessed)

    raw = await ops.find_entry_by_title_data(
        query=preprocessed, zim_file_path=zim_file_path, cross_file=cross_file,
        limit=limit, offset=offset, cursor=cursor,
    )

    if cross_file:
        # Promotion is per-archive — cannot run safely across multiple archives.
        # Surface the limitation in _meta so callers can pin an archive if they need promotion.
        raw["_meta"]["promotion_applied"] = False
        raw["_meta"]["hint"] = "Z3/Z4/OPP-1 promotion is per-archive. Pin a specific zim_file_path to enable promotion."
        return raw

    # Single-archive title mode: apply promotion. Use the rc0-extracted
    # auto_select_zim_file (NOT an inline reimplementation) so the diagnostic
    # surface — try/except envelope + the four log-emit arms in
    # SimpleToolsHandler._auto_select_zim_file (simple_tools.py:5784) — is
    # preserved byte-for-byte. Pinned by the Task A3a diff-test.
    from openzim_mcp.topic_preprocessing import auto_select_zim_file, promote_topic_via_title_index
    resolved_path = zim_file_path if zim_file_path else auto_select_zim_file(server.zim_operations)
    if resolved_path is None:
        # Multiple archives loaded but no zim_file_path pinned — promotion
        # cannot run safely. Surface in _meta and return raw results.
        raw["_meta"]["promotion_applied"] = False
        raw["_meta"]["hint"] = "Pin zim_file_path to a specific archive to enable Z3/Z4/OPP-1 promotion."
        return raw
    promoted = promote_topic_via_title_index(
        zim_operations=server.zim_operations,
        zim_file_path=resolved_path,
        topic=preprocessed,
    )
    return _merge_promotion_into_title_results(raw, promoted)


def _merge_promotion_into_title_results(raw, promoted):
    """Apply Z3/Z4/OPP-1 promotion as a post-filter on raw title-lookup results.

    If promotion accepted a candidate, the promoted entry is hoisted to the
    top of results['matches']. Other matches remain in their original ranking
    (no reordering — small models reading the list rely on relative ranking
    being stable).

    If promotion rejected all candidates (returned None), raw results pass
    through unchanged.
    """
    if promoted is None:
        return raw
    matches = raw.get("matches", [])
    if not matches or matches[0].get("entry_path") == promoted["entry_path"]:
        return raw
    # Hoist promoted entry to top; preserve order of remaining matches.
    hoisted = [m for m in matches if m["entry_path"] != promoted["entry_path"]]
    matches[:] = [promoted] + hoisted
    raw["_meta"]["promotion_applied"] = True
    return raw
```

- [ ] **Step 3: Tests**

```python
# tests/test_zim_search.py

async def test_zim_search_fulltext_passes_filters(phase_f_server):
    ...

async def test_zim_search_title_applies_preprocessing(phase_f_server):
    # "what is the population of detroit" → "detroit" → title match
    result = await ...zim_search(query="what is the population of detroit", mode="title")
    assert result["matches"][0]["entry_path"] == "Detroit"

async def test_zim_search_title_applies_promotion_single_archive(phase_f_server):
    # "Tesla electricity" → should NOT return Tesla's_Wireless_Electricity
    result = await ...zim_search(query="Tesla electricity", mode="title", zim_file_path=PATH)
    if result["matches"]:
        assert "Wireless_Electricity" not in result["matches"][0]["entry_path"]

async def test_zim_search_title_disables_promotion_on_cross_file(phase_f_server):
    # cross_file=True + mode=title → promotion NOT applied, hint in _meta
    result = await ...zim_search(query="Tesla electricity", mode="title", cross_file=True)
    assert result["_meta"]["promotion_applied"] is False
    assert "per-archive" in result["_meta"]["hint"]

async def test_zim_search_suggest_no_preprocessing(phase_f_server):
    # Prefix autocomplete — must NOT apply Tier 1 rewriting
    ...

async def test_zim_search_cross_file_with_title_mode(phase_f_server):
    # cross_file=True on mode=title must work (preserves find_entry_by_title cross-file behavior)
    ...

async def test_zim_search_suggest_rejects_cross_file(phase_f_server):
    result = await ...zim_search(query="prefix", mode="suggest", cross_file=True)
    assert result["error"]["code"] == "invalid_combination"

async def test_zim_search_title_auto_select_archive(phase_f_server):
    # mode=title with no zim_file_path AND cross_file=False → auto-selects single loaded archive
    result = await ...zim_search(query="Detroit", mode="title")
    assert result.get("error") is None  # no missing-archive error
```

- [ ] **Step 4: Run, commit**

```bash
pytest tests/test_zim_search.py -v
git add openzim_mcp/tools/zim_search.py tests/test_zim_search.py
git commit -m "feat(rc1): implement zim_search with 3-mode dispatch and conditional promotion wiring"
```

### Task D5: Implement `zim_get.py` (4-branch oneOf)

**Files:**

- Modify: `openzim_mcp/tools/zim_get.py`
- Create: `tests/test_zim_get.py`

**Context:** 4 oneOf branches: single-entry-body, single-entry-binary, batch, main-page. **`compact` defaults to `False`** at v2.0 to preserve legacy `get_zim_entry` behavior. The `compact` parameter exists for surface uniformity; v2.5 revisits the default with adoption telemetry.

- [ ] **Step 1: Write the tool**

```python
"""zim_get — single/batch/binary/main-page entry fetch with 4-branch oneOf."""
from __future__ import annotations
from typing import Literal, Optional, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from openzim_mcp.server import OpenZimMcpServer


def register(server: "OpenZimMcpServer") -> None:
    from openzim_mcp.async_operations import AsyncZimOperations
    ops = AsyncZimOperations(server.zim_operations)

    @server.mcp.tool()
    async def zim_get(
        zim_file_path: str,
        entry_path: Optional[str] = None,
        entry_paths: Optional[list[str]] = None,
        view: Literal["full", "summary", "toc", "structure"] = "full",
        binary: bool = False,
        main_page: bool = False,
        max_content_length: Optional[int] = None,
        content_offset: int = 0,
        compact: bool = False,  # legacy-preserving default per spec; v2.5 revisits
        compact_budget: Optional[Union[str, int]] = None,
    ):
        """<COPY THE FULL ~3,200-BYTE DESCRIPTION FROM SPEC §3 zim_get>"""
        # Defense-in-depth: validate the branch combination even if oneOf isn't honored.
        if entry_path and entry_paths:
            return _tool_error("invalid_path_combination", hint="entry_path and entry_paths are mutually exclusive")
        if binary and entry_paths:
            return _tool_error("invalid_path_combination", hint="binary mode is single-entry only; use entry_path")
        if binary and view != "full":
            return _tool_error("invalid_path_combination", hint="binary mode locks view to 'full'")
        if binary and main_page:
            return _tool_error("invalid_path_combination", hint="main_page cannot be combined with binary")
        if main_page and (entry_path or entry_paths):
            return _tool_error("invalid_path_combination", hint="main_page is path-free; omit entry_path/entry_paths")
        if main_page and view != "full":
            return _tool_error("invalid_path_combination", hint="main_page locks view to 'full'")
        if not (entry_path or entry_paths or main_page):
            return _tool_error("invalid_path_combination", hint="provide one of entry_path, entry_paths, or main_page=True")

        # Branch dispatch
        if main_page:
            return await ops.get_main_page_data(zim_file_path)
        if binary:
            return await ops.get_binary_entry_data(zim_file_path, entry_path)
        if entry_paths:
            return await ops.get_entries_data(zim_file_path, entry_paths, view=view, compact=compact, compact_budget=compact_budget)
        return await ops.get_entry_data(zim_file_path, entry_path, view=view, compact=compact, compact_budget=compact_budget)
```

If Gate 0's `oneOf` path is selected, override the auto-generated `inputSchema` to emit the 4-branch `oneOf` using the Gate-0.1-winning pattern.

- [ ] **Step 2: Tests for each oneOf branch**

```python
# tests/test_zim_get.py
async def test_zim_get_single_entry_full(phase_f_server): ...
async def test_zim_get_single_entry_summary(phase_f_server): ...
async def test_zim_get_single_entry_toc(phase_f_server): ...
async def test_zim_get_single_entry_structure(phase_f_server): ...
async def test_zim_get_single_entry_binary(phase_f_server): ...
async def test_zim_get_batch(phase_f_server): ...
async def test_zim_get_main_page(phase_f_server):
    # main_page=True dispatches to get_main_page_data, no entry_path needed
    result = await phase_f_server.mcp._tool_manager._tools["zim_get"].fn(
        zim_file_path=PATH, main_page=True,
    )
    assert result.get("error") is None


async def test_zim_get_compact_default_is_false(phase_f_server):
    """v2.0 preserves legacy get_zim_entry behavior. v2.5 revisits."""
    result = await ...zim_get(zim_file_path=path, entry_path="big_article")
    # compact=False default → raw markdown shape, matching legacy behavior
    assert result.get("compacted") is not True


async def test_zim_get_invalid_path_combination_returns_structured_error(phase_f_server):
    """Defense-in-depth for clients that flatten oneOf."""
    result = await ...zim_get(zim_file_path=path, entry_path="a", entry_paths=["b"])
    assert result["error"]["code"] == "invalid_path_combination"
```

- [ ] **Step 3: Run, commit**

```bash
pytest tests/test_zim_get.py -v
git add openzim_mcp/tools/zim_get.py tests/test_zim_get.py
git commit -m "feat(rc1): implement zim_get with 4-branch oneOf; compact defaults to False"
```

### Task D6: Implement `zim_get_section.py`

**Files:** `openzim_mcp/tools/zim_get_section.py`, `tests/test_zim_get_section.py`

- [ ] **Step 1: Write the tool** — rename `get_section` to `zim_get_section`, add `compact` and `compact_budget` parameters with `compact=True` default. Body delegates to existing `_get_section_data`. Description ~1,300 bytes.
- [ ] **Step 2: Tests** — verify renamed registration, verify `compact=True` default response shape, verify `compact=False` returns the legacy raw text.
- [ ] **Step 3: Commit.**

### Task D7: Implement `zim_browse.py`

**Files:** `openzim_mcp/tools/zim_browse.py`, `tests/test_zim_browse.py`

- [ ] **Step 1: Write the tool** — `mode: Literal["page", "walk"] = "page"` dispatch. `"page"` delegates to current `browse_namespace`; `"walk"` to current `walk_namespace`. Description ~1,500 bytes.
- [ ] **Step 2: Tests** — both modes, pagination edge cases.
- [ ] **Step 3: Commit.**

### Task D8: Implement `zim_metadata.py`

**Files:** `openzim_mcp/tools/zim_metadata.py`, `tests/test_zim_metadata.py`

- [ ] **Step 1: Write the tool** — calls `async_operations.get_archive_metadata_data`. **No `main_page_path` field.** Description ~850 bytes.
- [ ] **Step 2: Tests** — verify the response shape lacks `main_page_path`, verify metadata + namespaces are both populated.
- [ ] **Step 3: Commit.**

### Task D9: Implement `zim_links.py`

**Files:** `openzim_mcp/tools/zim_links.py`, `tests/test_zim_links.py`

- [ ] **Step 1: Write the tool** — `direction: Literal["outbound", "related"] = "outbound"`. `"outbound"` → current `extract_article_links`; `"related"` → current `get_related_articles`. **`"inbound"` is NOT in the v2.0 enum.** Description ~1,250 bytes including the brief v2.5-inbound forward-compatibility note.
- [ ] **Step 2: Tests** — both directions, schema does not include `"inbound"` as an enum value.
- [ ] **Step 3: Commit.**

### Task D10: Implement `zim_health.py`

**Files:** `openzim_mcp/tools/zim_health.py`, `tests/test_zim_health.py`

- [ ] **Step 1: Write the tool** — zero parameters. Calls `async_operations.get_health_data`. Description ~600 bytes.
- [ ] **Step 2: Tests** — verify combined response shape with `health`, `configuration`, `loaded_archives`.
- [ ] **Step 3: Commit.**

### Task D11: Replace `tools/__init__.py` with `register_phase_f_tools`

**Files:**

- Modify: `openzim_mcp/tools/__init__.py`
- Modify: `openzim_mcp/server.py`

- [ ] **Step 1: Replace `register_all_tools` with `register_phase_f_tools`**

The orchestrator reads `server.config.tool_mode` only. The `tool_mode` default at v2.0.0 is unchanged — `'simple'`.

```python
"""Phase F tool registration orchestrator."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openzim_mcp.server import OpenZimMcpServer


def register_phase_f_tools(server: "OpenZimMcpServer") -> None:
    """Register the v2 Phase F tool surface. Honors server.config.tool_mode."""
    from . import zim_query
    zim_query.register(server)

    mode = server.config.tool_mode

    if mode == "simple":
        return  # 1-tool surface (the v2.0.0 default)

    # advanced — all 8
    from . import zim_search, zim_get, zim_get_section, zim_browse, zim_metadata, zim_links, zim_health
    for module in (zim_search, zim_get, zim_get_section, zim_browse, zim_metadata, zim_links, zim_health):
        module.register(server)
```

**`register_all_tools` shim is deliberately NOT added.** The v2 foundational decisions forbid aliases. Any caller still importing `register_all_tools` must be renamed in this commit.

**Required call-site edits in this commit** (verified by `grep -r "register_all_tools" openzim_mcp/ tests/` at plan-authoring time — current `main` has 4 sites):

1. `openzim_mcp/server.py:30` — change `from .tools import register_all_tools` to `from .tools import register_phase_f_tools`.
2. `openzim_mcp/server.py:446` — change `register_all_tools(self)` to `register_phase_f_tools(self)`.
3. `openzim_mcp/tools/__init__.py:24` — `__all__` export list: remove `"register_all_tools"`, add `"register_phase_f_tools"`.
4. `openzim_mcp/tools/__init__.py:37` — replace function definition with the orchestrator above.

**Final verification step before commit:**

```bash
grep -rn "register_all_tools" openzim_mcp/ tests/
```

Must return zero results — any remaining hit means a call site was missed.

- [ ] **Step 2: Make `simple_tools_handler` initialization unconditional**

At v2.0.0b13, `server.py` only initializes `simple_tools_handler` when `tool_mode == TOOL_MODE_SIMPLE`:

```python
self.simple_tools_handler = None
if config.tool_mode == TOOL_MODE_SIMPLE:
    self.simple_tools_handler = SimpleToolsHandler(self.zim_operations)
```

Phase F registers `zim_query` in BOTH modes (advanced now includes it), and `zim_query.py` reaches into `server.simple_tools_handler` for `handle_zim_query`. The handler must therefore exist in advanced mode too. (`zim_search.py` does not depend on the handler — it calls `topic_preprocessing.auto_select_zim_file` and `topic_preprocessing.promote_topic_via_title_index` directly, both extracted in rc0 — but the handler is still required for `zim_query`.) Replace the conditional initialization with unconditional:

```python
# Phase F: simple_tools_handler backs zim_query in BOTH simple and advanced modes
# (the simple/advanced split is now a registration-time filter on the SAME code path).
# zim_search.py does NOT use the handler — it calls topic_preprocessing functions
# directly — but the handler is still load-bearing for zim_query. Always initialize.
self.simple_tools_handler = SimpleToolsHandler(self.zim_operations)
```

- [ ] **Step 3: Update `server.py` to call `register_phase_f_tools` unconditionally**

Replace:

```python
if self.config.tool_mode == TOOL_MODE_SIMPLE:
    self._register_simple_tools()
else:
    register_all_tools(self)
```

With:

```python
from .tools import register_phase_f_tools
register_phase_f_tools(self)
```

Delete `_register_simple_tools` method entirely.

- [ ] **Step 4: Verify the server boots and exposes 8 tools in advanced mode, 1 in simple mode, and that `simple_tools_handler` is non-None in both**

```bash
for mode in simple advanced; do
  python -c "
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.config import OpenZimMcpConfig
cfg = OpenZimMcpConfig(allowed_directories=['/tmp'], tool_mode='$mode')
srv = OpenZimMcpServer(cfg)
print('mode=$mode handler=', type(srv.simple_tools_handler).__name__)
print('mode=$mode tools=', list(srv.mcp._tool_manager._tools.keys()))
"
done
```

Expected:

- `mode=simple handler= SimpleToolsHandler` / `tools= ['zim_query']`
- `mode=advanced handler= SimpleToolsHandler` / `tools= ['zim_query', 'zim_search', ..., 'zim_health']` (8 tools)

Critical: `handler= NoneType` in either mode means Step 2 wasn't applied and `zim_query.py` will AttributeError on `handle_zim_query` at first call.

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/tools/__init__.py openzim_mcp/server.py
git commit -m "feat(rc1): register_phase_f_tools orchestrator replaces _register_simple_tools"
```

### Task D12: Delete legacy per-domain tool files

- [ ] **Step 1: Verify nothing imports from them anymore**

```bash
grep -rn "from openzim_mcp.tools.content_tools\|from openzim_mcp.tools.file_tools\|from openzim_mcp.tools.metadata_tools\|from openzim_mcp.tools.navigation_tools\|from openzim_mcp.tools.search_tools\|from openzim_mcp.tools.server_tools\|from openzim_mcp.tools.structure_tools" --include="*.py" .
```

Expected: no matches.

- [ ] **Step 2: Delete the files**

```bash
rm openzim_mcp/tools/content_tools.py openzim_mcp/tools/file_tools.py openzim_mcp/tools/metadata_tools.py openzim_mcp/tools/navigation_tools.py openzim_mcp/tools/search_tools.py openzim_mcp/tools/server_tools.py openzim_mcp/tools/structure_tools.py
```

- [ ] **Step 3: Run the full test suite**

```bash
pytest -x 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git add -A openzim_mcp/tools/
git commit -m "chore(rc1): delete legacy per-domain tool files"
```

### Task D13: Schema-budget enforcement test

**Files:**

- Create: `tests/test_phase_f_schema_budget.py`

- [ ] **Step 1: Write the test**

```python
"""Phase F schema budget enforcement (build-time audit, not runtime config).

Reads tests/dispatch_eval/gate_0b_decision.json to cross-check that the rc1
commit's behavior matches the recorded Gate 0b outcome.

Production code does NOT read this JSON at runtime in normal use.
"""
import json
import pathlib

from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.config import OpenZimMcpConfig


GATE_DECISION_PATH = pathlib.Path("tests/dispatch_eval/gate_0b_decision.json")

# Selected at PR-author time from gate_0b_decision.json. Hard-coded as Python
# constants in this commit so production code does not depend on the JSON.
TOTAL_CAP = 17_400  # ~17,400 wired / ~17,000 flat — selected from gate decision
ALLOCATION = {
    "zim_query": 6_300,
    "zim_search": 2_400,  # 2_200 if flat
    "zim_get": 3_200,     # 3_000 if flat
    "zim_get_section": 1_300,
    "zim_browse": 1_500,
    "zim_metadata": 850,
    "zim_links": 1_250,
    "zim_health": 600,
}


def _measure_tools(mode):
    cfg = OpenZimMcpConfig(allowed_directories=["/tmp"], tool_mode=mode)
    srv = OpenZimMcpServer(cfg)
    return {
        name: len(json.dumps({"name": name, "description": tool.description, "inputSchema": tool.parameters}).encode())
        for name, tool in srv.mcp._tool_manager._tools.items()
    }


def test_advanced_total_under_cap():
    bytes_by_tool = _measure_tools("advanced")
    total = sum(bytes_by_tool.values())
    assert total <= TOTAL_CAP, f"Phase F schema budget exceeded: {total} > {TOTAL_CAP}"


def test_per_tool_allocations():
    """Per-tool 20% slack. If a tool legitimately needs more (e.g., Gate 0b's F2 traces
    a class regression to too-tight description), redistribute by editing ALLOCATION
    above — take budget from a tool that's under-using its share, keep TOTAL_CAP fixed.
    The total is the only hard cap; per-tool allocations are a distribution decision
    the gate can revise (see spec §Tool-by-tool budget allocation)."""
    bytes_by_tool = _measure_tools("advanced")
    for name, alloc in ALLOCATION.items():
        actual = bytes_by_tool[name]
        assert actual <= alloc * 1.2, f"{name} exceeds allocation: {actual} > {alloc * 1.2}"


def test_gate_decision_criterion_d_passed():
    decision = json.loads(GATE_DECISION_PATH.read_text())
    assert decision["gate_passed"] is True
    assert decision["criteria"]["D"]["primary"]["pass"] is True
    # Secondary, tertiary, and quaternary are conditional on availability.
    if decision["secondary_status"] == "available":
        assert decision["criteria"]["D"]["secondary"]["pass"] is True
    if decision["tertiary_status"] == "available":
        assert decision["criteria"]["D"]["tertiary"]["pass"] is True
    if decision["quaternary_status"] == "available":
        assert decision["criteria"]["D"]["quaternary"]["pass"] is True


def test_gate_decision_default_tool_mode_is_simple():
    decision = json.loads(GATE_DECISION_PATH.read_text())
    assert decision["default_tool_mode"] == "simple"


def test_gate_decision_criterion_c_path_known_value():
    decision = json.loads(GATE_DECISION_PATH.read_text())
    assert decision["criterion_c_path"] in {"wired", "fallback"}
    # Fallback path is only valid if ALL of fallback_c1_pass, fallback_c2_pass,
    # fallback_c3_pass are True — the legibility fix must reduce routing harm
    # AND not introduce new dispatch confusion. fallback_c2_pass may be null
    # if the conditional subset was underpowered (<10 events); hand-audit case
    # noted in secondary_observational_failures.
    if decision["criterion_c_path"] == "fallback":
        assert decision["fallback_c1_pass"] is True, (
            "criterion_c_path='fallback' but fallback_c1_pass is not True. "
            "Fallback ships only if all of fallback_c1_pass/c2_pass/c3_pass are true."
        )
        assert decision["fallback_c2_pass"] in (True, None), (
            "criterion_c_path='fallback' but fallback_c2_pass is False. "
            "If null, hand-audit must be recorded in secondary_observational_failures."
        )
        assert decision["fallback_c3_pass"] is True, (
            "criterion_c_path='fallback' but fallback_c3_pass is not True. "
            "The fallback ships only if the legibility fix demonstrably stops Z4 misroutes."
        )


def test_gate_decision_scope_limitations_documented():
    """The gate's measurement bounds must be machine-readable, not just
    inferable from spec prose. Catches the case where a maintainer re-runs
    Gate 0b under different conditions (different probe set, different model
    coverage, different language) and forgets to update scope_limitations."""
    decision = json.loads(GATE_DECISION_PATH.read_text())
    limitations = decision.get("scope_limitations", [])
    assert isinstance(limitations, list) and limitations, (
        "gate_0b_decision.json must include a non-empty scope_limitations list. "
        "See spec §scope_limitations field for required entries at v2.0."
    )
    # Required prefixes at v2.0 — re-runs that add models or change probe scope must
    # update these entries, not silently drop them.
    required_prefixes = ("probe-distribution:", "model-coverage:", "size-range:", "probe-language:")
    for prefix in required_prefixes:
        assert any(item.startswith(prefix) for item in limitations), (
            f"scope_limitations missing required '{prefix}' entry. "
            f"Got: {limitations}. See spec §scope_limitations field."
        )
```

- [ ] **Step 2: Run, commit**

```bash
pytest tests/test_phase_f_schema_budget.py -v
git add tests/test_phase_f_schema_budget.py
git commit -m "test(rc1): schema budget regression guard"
```

### Task D14: Schema-shape tests (`oneOf` branches)

**Files:**

- Create: `tests/test_phase_f_schema_shapes.py`

Asserts the `inputSchema` generator emits the correct `oneOf` branch structure for `zim_get` and `zim_search` (or absence thereof if Gate 0 selected flat schemas).

- [ ] **Step 1: Write the test** — reads `gate_0b_decision.json` to know whether to assert presence or absence of `oneOf`.

```python
import json
import pathlib

from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.config import OpenZimMcpConfig


SCHEMA_SHAPE = json.loads(pathlib.Path("tests/dispatch_eval/gate_0b_decision.json").read_text())["gate_0_schema_shape"]


def _get_tool_schema(name):
    cfg = OpenZimMcpConfig(allowed_directories=["/tmp"], tool_mode="advanced")
    srv = OpenZimMcpServer(cfg)
    return json.dumps(srv.mcp._tool_manager._tools[name].parameters)


def test_zim_get_schema_shape():
    schema_str = _get_tool_schema("zim_get")
    if SCHEMA_SHAPE == "wired_oneof":
        assert "oneOf" in schema_str
        # Optional: assert 4 branches present
    else:
        assert "oneOf" not in schema_str


def test_zim_search_schema_shape():
    schema_str = _get_tool_schema("zim_search")
    if SCHEMA_SHAPE == "wired_oneof":
        assert "oneOf" in schema_str
    else:
        assert "oneOf" not in schema_str
```

- [ ] **Step 2: Run, commit**

```bash
pytest tests/test_phase_f_schema_shapes.py -v
git add tests/test_phase_f_schema_shapes.py
git commit -m "test(rc1): schema-shape verification (oneOf vs flat)"
```

### Task D14a: Gate-decision-consistency test

**Files:**

- Create: `tests/test_phase_f_gate_decision_consistency.py`

Asserts that the Python constants baked into the rc1 commit (the Criterion C path in `zim_search.py`, the schema shape in `zim_search.py` / `zim_get.py`, the `tool_mode` default in `config.py`) match the values recorded in `tests/dispatch_eval/gate_0b_decision.json`. Drift between them blocks the merge — a future maintainer who re-runs Gate 0b and re-commits the decision file without updating the production constants will trip this test.

- [ ] **Step 1: Write the test**

```python
"""Gate-decision consistency — the rc1 commit's baked-in constants match the
committed Gate 0b decision file.

Production code does NOT read gate_0b_decision.json at runtime. The decision
values are baked as Python constants in the rc1 commit at PR-author time.
This test enforces that those constants don't drift from the gate outcome.
"""

import json
import pathlib
import re

REPO = pathlib.Path(__file__).parent.parent
DECISION = json.loads((REPO / "tests" / "dispatch_eval" / "gate_0b_decision.json").read_text())


def test_zim_search_criterion_c_path_matches_decision():
    """zim_search.py's _CRITERION_C_PATH constant matches gate's criterion_c_path."""
    source = (REPO / "openzim_mcp" / "tools" / "zim_search.py").read_text()
    match = re.search(r'_CRITERION_C_PATH\s*:\s*Literal\[[^\]]+\]\s*=\s*"(wired|fallback)"', source)
    assert match is not None, "_CRITERION_C_PATH constant not found in zim_search.py"
    assert match.group(1) == DECISION["criterion_c_path"], (
        f"Drift: zim_search.py has _CRITERION_C_PATH={match.group(1)!r} but "
        f"gate decision says criterion_c_path={DECISION['criterion_c_path']!r}. "
        "Either re-bake the constant or re-commit the decision file."
    )


def test_config_tool_mode_default_is_simple():
    """config.py's tool_mode Field default matches gate's default_tool_mode."""
    source = (REPO / "openzim_mcp" / "config.py").read_text()
    # Look for the tool_mode Field declaration. Tolerate whitespace variations.
    match = re.search(r'tool_mode\s*:\s*Literal\[[^\]]+\]\s*=\s*Field\s*\(\s*default\s*=\s*"(\w+)"', source)
    assert match is not None, "tool_mode Field default not found in config.py"
    assert match.group(1) == DECISION["default_tool_mode"], (
        f"Drift: config.py has tool_mode default={match.group(1)!r} but "
        f"gate decision says default_tool_mode={DECISION['default_tool_mode']!r}."
    )


def test_schema_shape_consistent_with_decision():
    """When Gate 0 selected wired_oneof, zim_search and zim_get must emit oneOf;
    when flat, neither emits oneOf. Cross-checks schema-shape against the gate decision."""
    from openzim_mcp.server import OpenZimMcpServer
    from openzim_mcp.config import OpenZimMcpConfig

    cfg = OpenZimMcpConfig(allowed_directories=["/tmp"], tool_mode="advanced")
    srv = OpenZimMcpServer(cfg)
    expected_wired = DECISION["gate_0_schema_shape"] == "wired_oneof"
    for name in ("zim_search", "zim_get"):
        schema_str = json.dumps(srv.mcp._tool_manager._tools[name].parameters)
        actual_wired = "oneOf" in schema_str
        assert actual_wired is expected_wired, (
            f"Drift: {name} schema_shape={'wired_oneof' if actual_wired else 'flat'!r} but "
            f"gate decision says gate_0_schema_shape={DECISION['gate_0_schema_shape']!r}."
        )


def test_gate_0_3_verdict_consistent_with_schema_shape():
    """gate_0_3_verdict='failed' (STOP-AMEND-SPEC) implies schema_shape='flat'.
    Catches the case where a maintainer re-runs Gate 0.3, gets a failure verdict,
    commits the new decision file, but forgets to amend the schemas — then ships
    wired_oneof while the verdict says the model can't parse it.
    """
    if DECISION["gate_0_3_verdict"] == "failed":
        assert DECISION["gate_0_schema_shape"] == "flat", (
            f"Drift: gate_0_3_verdict='failed' (Qwen could not parse oneOf at the prototype) "
            f"but gate_0_schema_shape='{DECISION['gate_0_schema_shape']}'. "
            "STOP-AMEND-SPEC verdict requires flat-schema design; either re-author rc1 with flat "
            "signatures and re-snapshot, or re-run Gate 0.3 with a fixed prototype."
        )
```

- [ ] **Step 2: Run, commit**

```bash
pytest tests/test_phase_f_gate_decision_consistency.py -v
git add tests/test_phase_f_gate_decision_consistency.py
git commit -m "test(rc1): gate-decision-consistency guard against constant drift"
```

### Task D14b: Prototype-rc1 schema parity test

**Files:**

- Create: `tests/test_phase_f_prototype_parity.py`
- Read at test time: `tests/dispatch_eval/prototype_schema_snapshot.json` (cherry-picked from prototype branch in Task D0 Step 2)

**Context:** the rc1 implementation rewrites the prototype skeletons from scratch ([Task D0 Step 2](#task-d0-create-v2-phase-f-rc1-branch--cherry-pick-decision)). If a rc1 author edits a description for clarity, reorders parameters, trims prose to fit the per-tool byte cap, or otherwise diverges from the prototype, Gate 0b / Gate 0.3 measured a different surface than what ships. The byte-cap test ([Task D13](#task-d13-schema-budget-enforcement-test)) catches gross divergence but does NOT catch description-quality drift inside the cap.

Parity invariant: per-tool wire footprint stays within **±5% bytes** of the prototype's recorded snapshot AND the `inputSchema` shape (oneOf branches, parameter names, parameter types, enum values) is structurally identical AND the per-tool description has a **Levenshtein edit distance ≤30%** of the prototype's recorded description. The edit-distance check catches the case where an rc1 author rewrites a description significantly while preserving its byte count — a pure prose rewrite within the byte budget can materially change the dispatch signal a small model reads, but the byte-budget + structural-identity checks alone would silently pass it. 30% is a deliberately generous threshold: minor rewording for grammar/clarity stays well under (typical copy-edits land 5–10%), but a substantive rewrite of the description's load-bearing operations list or examples trips it.

**If the edit-distance check fails, the remediation is one of:** (a) revert the description toward the prototype's prose (preferred — preserves the measurement), or (b) re-run Gate 0b for the affected tool and re-snapshot (`tests/dispatch_eval/prototype_schema_snapshot.json` updates to match the rewritten description, and the F2 verdict for that tool's operation class is re-derived against the new measurement). Option (b) is escape-hatch territory — the implicit contract of cherry-picking the Gate 0b decision is that rc1 ships what was measured.

- [ ] **Step 1: Write the test**

```python
"""Prototype↔rc1 schema parity.

Drift > ±5% bytes OR any structural change to inputSchema OR description
edit distance > 30% invalidates the Gate 0b / Gate 0.3 measurements
(which were taken against the prototype).

Allowed: minor prose edits inside the ±5% byte slack AND ≤30% edit distance
(rewording for grammar/clarity typically lands 5-10% edit distance).

Blocked:
  - Schema-shape changes (adding/removing oneOf branches, renaming a
    parameter, changing a Literal's enum values).
  - Substantive description rewrites that change the dispatch signal
    (operations list, examples, mode semantics) while staying inside the
    byte budget.

Both force a Gate 0b re-run.
"""

import json
import pathlib

from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.config import OpenZimMcpConfig


SNAPSHOT_PATH = pathlib.Path("tests/dispatch_eval/prototype_schema_snapshot.json")
BYTE_TOLERANCE = 0.05  # ±5%
DESCRIPTION_EDIT_DISTANCE_TOLERANCE = 0.30  # ≤30% Levenshtein / max(len_a, len_b)


def _rc1_footprints():
    cfg = OpenZimMcpConfig(allowed_directories=["/tmp"], tool_mode="advanced")
    srv = OpenZimMcpServer(cfg)
    out = {}
    for name, tool in srv.mcp._tool_manager._tools.items():
        wire = json.dumps({"name": name, "description": tool.description, "inputSchema": tool.parameters})
        out[name] = {"bytes": len(wire.encode()), "description": tool.description, "inputSchema": tool.parameters}
    return out


def _strip_descriptions(schema):
    """Walk inputSchema dict and drop 'description' fields so structural compare ignores prose."""
    if isinstance(schema, dict):
        return {k: _strip_descriptions(v) for k, v in schema.items() if k != "description"}
    if isinstance(schema, list):
        return [_strip_descriptions(item) for item in schema]
    return schema


def _normalized_edit_distance(a: str, b: str) -> float:
    """Levenshtein distance normalized by max(len(a), len(b)). Returns 0.0 if both empty."""
    if not a and not b:
        return 0.0
    # Use a small pure-Python Levenshtein (no extra deps; descriptions are <4KB).
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return 1.0
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        curr = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[n] / max(m, n)


def test_prototype_parity_byte_budget():
    snapshot = json.loads(SNAPSHOT_PATH.read_text())
    rc1 = _rc1_footprints()
    failures = []
    for name, proto in snapshot.items():
        if name not in rc1:
            failures.append(f"{name}: missing from rc1 surface")
            continue
        proto_bytes = proto["bytes"]
        rc1_bytes = rc1[name]["bytes"]
        delta = abs(rc1_bytes - proto_bytes) / proto_bytes
        if delta > BYTE_TOLERANCE:
            failures.append(
                f"{name}: rc1={rc1_bytes}B vs prototype={proto_bytes}B "
                f"({delta:.1%} drift > {BYTE_TOLERANCE:.0%} tolerance). "
                f"Either tighten the rc1 description to match the prototype's measured footprint, "
                f"or re-run Gate 0b against the rewritten rc1 surface and re-commit the snapshot."
            )
    assert not failures, "\n".join(failures)


def test_prototype_parity_input_schema_shape():
    snapshot = json.loads(SNAPSHOT_PATH.read_text())
    rc1 = _rc1_footprints()
    failures = []
    for name, proto in snapshot.items():
        if name not in rc1:
            continue  # caught by byte-budget test
        proto_shape = _strip_descriptions(proto["inputSchema"])
        rc1_shape = _strip_descriptions(rc1[name]["inputSchema"])
        if proto_shape != rc1_shape:
            failures.append(
                f"{name}: inputSchema shape differs from prototype (descriptions ignored). "
                f"Schema-shape changes (oneOf branches, parameter names, types, enums) require "
                f"re-running Gate 0b. Diff: see snapshot vs rc1 _measure run output."
            )
    assert not failures, "\n".join(failures)


def test_prototype_parity_description_edit_distance():
    """Catches substantive prose rewrites that fit inside the byte budget but
    change the dispatch signal Gate 0b measured. 30% is deliberately generous —
    typical grammar/clarity edits land 5-10%; anything past 30% means the
    description was meaningfully rewritten and the measurement is stale.
    """
    snapshot = json.loads(SNAPSHOT_PATH.read_text())
    rc1 = _rc1_footprints()
    failures = []
    for name, proto in snapshot.items():
        if name not in rc1:
            continue  # caught by byte-budget test
        proto_desc = proto.get("description", "")
        rc1_desc = rc1[name]["description"]
        distance = _normalized_edit_distance(proto_desc, rc1_desc)
        if distance > DESCRIPTION_EDIT_DISTANCE_TOLERANCE:
            failures.append(
                f"{name}: description edit distance {distance:.1%} > "
                f"{DESCRIPTION_EDIT_DISTANCE_TOLERANCE:.0%} tolerance. "
                f"A pure prose rewrite within the byte budget can change the dispatch "
                f"signal Gate 0b measured. Either revert toward the prototype's description, "
                f"or re-run Gate 0b for this tool and re-snapshot."
            )
    assert not failures, "\n".join(failures)
```

- [ ] **Step 2: Run, commit**

```bash
pytest tests/test_phase_f_prototype_parity.py -v
git add tests/test_phase_f_prototype_parity.py
git commit -m "test(rc1): prototype↔rc1 schema parity (±5% bytes + structural identity)"
```

### Task D15: Schema-bypass defense-in-depth tests

**Files:**

- Create: `tests/test_phase_f_schema_bypass.py`

Hand-construct wire-level invalid payloads that bypass `oneOf` and assert structured validation errors at the handler.

**Coverage requirement.** ≥1 probe per oneOf-forbidden combination. Earlier drafts shipped 6 probes covering a partial subset; the expanded set below enumerates every distinct forbidden combination across the 4 branches × {entry_path, entry_paths, binary, view, main_page} dimensions. Schema-respecting clients can't construct these; only the defense-in-depth handler validation can — which is exactly what these probes test.

- [ ] **Step 1: Write the test** — 13 probes hand-constructing every distinct invalid `zim_get` payload:

```python
"""Defense-in-depth tests — clients that flatten oneOf must still get structured errors.

These probes bypass the schema layer by calling the tool function directly
with invalid combinations. The handler's runtime validation must catch them.

Coverage is per-combination, not per-branch — at least one probe per distinct
forbidden combination across the four oneOf branches. If a future API change
adds a forbidden combination (e.g., a new parameter that locks others out),
this list must be extended.
"""
import pytest


@pytest.mark.parametrize("kwargs,expected_hint_substring", [
    # Mutex paths
    (dict(entry_path="a", entry_paths=["b"]), "exclusive"),
    # Binary single-only
    (dict(binary=True, entry_paths=["a"]), "single-entry"),
    # Binary locks view to "full"
    (dict(binary=True, entry_path="a", view="summary"), "binary"),
    (dict(binary=True, entry_path="a", view="toc"), "binary"),
    (dict(binary=True, entry_path="a", view="structure"), "binary"),
    # Binary + main_page conflict
    (dict(binary=True, main_page=True), "main_page"),
    # main_page is path-free
    (dict(main_page=True, entry_path="a"), "path-free"),
    (dict(main_page=True, entry_paths=["a"]), "path-free"),
    # main_page locks view to "full"
    (dict(main_page=True, view="summary"), "main_page"),
    (dict(main_page=True, view="toc"), "main_page"),
    (dict(main_page=True, view="structure"), "main_page"),
    # At-least-one-path required
    (dict(view="full"), "provide one of"),
    (dict(view="summary"), "provide one of"),
])
async def test_zim_get_invalid_combinations_surface_structured_error(phase_f_server, kwargs, expected_hint_substring):
    tool = phase_f_server.mcp._tool_manager._tools["zim_get"]
    result = await tool.fn(zim_file_path=PATH, **kwargs)
    assert result.get("error", {}).get("code") == "invalid_path_combination"
    assert expected_hint_substring in result["error"]["hint"]
```

- [ ] **Step 2: Run, commit**

```bash
pytest tests/test_phase_f_schema_bypass.py -v
git add tests/test_phase_f_schema_bypass.py
git commit -m "test(rc1): schema-bypass defense-in-depth tests (≥1 per forbidden combination)"
```

### Task D16: Per-tool test module updates (~22 modules)

- [ ] **Step 1: Walk each existing per-tool test file** (e.g., `tests/test_search_zim_file.py`) and update imports + registered-tool-name lookups. Underlying assertions about response shape stay the same.

```bash
# Find candidates:
ls tests/test_*.py | xargs grep -l "search_zim_file\|find_entry_by_title\|get_zim_entry\|get_zim_entries\|get_search_suggestions\|list_zim_files\|get_zim_metadata\|list_namespaces\|get_main_page\|search_all\|search_with_filters\|browse_namespace\|walk_namespace\|extract_article_links\|get_related_articles\|get_article_structure\|get_entry_summary\|get_table_of_contents\|get_binary_entry\|get_section\|get_server_health\|get_server_configuration"
```

For each: update test file name (if appropriate) and update lookups.

- [ ] **Step 2: Run the full suite** to confirm no regressions.

```bash
pytest -x 2>&1 | tail -5
```

- [ ] **Step 3: Commit**

```bash
git add tests/
git commit -m "test(rc1): rename per-tool test modules + tool-name lookups"
```

### Task D17: Golden snapshot re-record

- [ ] **Step 1: Find golden-snapshot files** that mention old tool names.

```bash
grep -rln "search_zim_file\|find_entry_by_title\|get_zim_entry\|get_zim_entries\|get_search_suggestions\|list_zim_files\|get_zim_metadata\|list_namespaces\|get_main_page\|search_all\|search_with_filters\|browse_namespace\|walk_namespace\|extract_article_links\|get_related_articles\|get_article_structure\|get_entry_summary\|get_table_of_contents\|get_binary_entry\|get_section\|get_server_health\|get_server_configuration" tests/ | grep -E "\.(json|yaml|yml|txt)$"
```

- [ ] **Step 2: Re-record snapshots against the new tool names.**

- [ ] **Step 3: Run, commit**

```bash
pytest -x 2>&1 | tail -5
git add tests/
git commit -m "test(rc1): re-record golden snapshots against Phase F tool names"
```

### Task D18: Update `config.py` — fix stale docstring

**Files:**

- Modify: `openzim_mcp/config.py`

- [ ] **Step 1: Fix the stale docstring**

`openzim_mcp/config.py:293` currently describes `tool_mode='advanced'` as registering "21 tools" (off-by-one from when `get_section` shipped — actual count at b13 is 22). Update to describe the Phase F behavior:

```python
tool_mode: Literal["simple", "advanced"] = Field(
    default="simple",
    description=(
        "Tool registration mode. "
        "'simple' (default) registers only zim_query — the NL entry point. "
        "'advanced' registers the full 8-tool Phase F surface: zim_query, "
        "zim_search, zim_get, zim_get_section, zim_browse, zim_metadata, "
        "zim_links, zim_health."
    ),
)
```

- [ ] **Step 2: Commit**

```bash
git add openzim_mcp/config.py
git commit -m "fix(rc1): tool_mode docstring describes Phase F 8-tool surface"
```

### Task D19: Update CHANGELOG

**Files:**

- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add a Phase F section**

```markdown
## v2.0.0rc1 — Phase F tool surface consolidation

### Migrating from v1.x / v2 beta

<copy the full migration table from the spec's `## Migration story → Full call-site map` section>

### Default behavior changes (silent breaks if not handled)

- **`zim_get_section` adds a `compact` parameter that defaults to `True`.** The legacy `get_section` returned raw text; the renamed `zim_get_section` returns compacted text. Pass `compact=False` to preserve the pre-Phase-F shape.
- **`zim_metadata` no longer exposes `main_page_path`.** Callers who used it to construct an explicit `entry_path` round-trip to `zim_get` should switch to `zim_get(path, main_page=True)` — a single-call, null-safe path. (Note: `main_page` is a dedicated boolean flag, NOT a value of the `view` enum — earlier Phase F drafts overloaded `view="main_page"` but it now stands as its own parameter to keep the `view` enum focused on bundle slicers.)

The `zim_get` rename from `get_zim_entry` is **behavior-preserving** on the `compact` axis (default is `False`, matching legacy). v2.5 will revisit the `zim_get` default with telemetry from real adoption.

### Surface change

- 22 tools → 8 tools in `tool_mode='advanced'`. `tool_mode='simple'` still registers only `zim_query`. Default tool_mode is unchanged (`'simple'`).
- All tools renamed with the `zim_*` prefix.
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(rc1): CHANGELOG with migration table and default-behavior-changes"
```

### Task D20: Migration conformance test

**Files:**

- Create: `tests/test_phase_f_migration_conformance.py`

Synthetic-client conformance over every row in the migration table. Catches mapping errors the website demo cannot.

- [ ] **Step 1: Write the test** — for each row in the migration table, construct the v2.0 call and assert: (a) it succeeds, (b) the response shape matches what the v1.x call shape would have produced.

```python
"""Migration conformance — every row in the v1/v2-beta → v2.0 mapping works."""

import pytest


@pytest.mark.parametrize("v1_call,v2_call_factory", [
    # ("list_zim_files()", lambda: ("zim_health", {})),  # picks .loaded_archives
    # ... rows from the migration table ...
])
async def test_migration_row(phase_f_server, v1_call, v2_call_factory):
    tool_name, kwargs = v2_call_factory()
    tool = phase_f_server.mcp._tool_manager._tools[tool_name]
    result = await tool.fn(**kwargs)
    # row-specific assertions on response shape


async def test_zim_get_compact_default_preserves_legacy(phase_f_server):
    """zim_get(view='full') without compact=True returns raw markdown (legacy shape)."""
    result = await phase_f_server.mcp._tool_manager._tools["zim_get"].fn(
        zim_file_path=PATH, entry_path="Big_Rapids,_Michigan",
    )
    # Assert response is the raw shape — markdown content, not compacted
    assert "compacted" not in result or result["compacted"] is False
```

- [ ] **Step 2: Commit**

```bash
git add tests/test_phase_f_migration_conformance.py
git commit -m "test(rc1): migration conformance covers every v1→v2 row"
```

### Task D21: Update v2 README to In Implementation

- [ ] **Step 1: Edit `docs/v2/README.md`** Phase F row to `In Implementation` status. Commit.

### Task D22: Open rc1 PR, merge, tag

- [ ] **Step 1: Push branch and open PR**

```bash
git push -u origin v2-phase-f-rc1
gh pr create --base main --label v2-phase-f --title "v2.0.0rc1: 8-tool Phase F surface" --body "..."
```

- [ ] **Step 2: Merge after review, tag `v2.0.0rc1`**

```bash
git checkout main
git pull
git tag v2.0.0rc1
git push origin v2.0.0rc1
```

---

## Stage E — `v2.0.0rc1` Stabilization Sweep

### Task E1: Multi-pass live Wikipedia sweep — full b1 → b13 set

The stabilization gate runs against the full b1 → b13 cumulative probe set (~150 probes × 5 reps = 750 effective observations), which restores statistical sensitivity commensurate with Gate 0b's 5pp non-inferiority margin. A 25-probe subset (n=125 effective) is statistically incapable of detecting 5pp regressions; that subset survives only as a smoke-test tool for quick defect triage (see `tests/dispatch_eval/data/b_series_25.jsonl`).

- [ ] **Step 1: Run the FULL b1 → b13 cumulative probe set against rc1 with the PRIMARY (Qwen-2.5-7B), 5 reps**

```bash
python tests/dispatch_eval/runner.py --variant rc1 --mode advanced --model qwen2.5-7b-instruct --reps 5 --probes tests/dispatch_eval/data/b1_b13_probes.jsonl --output /tmp/rc1_sweep.jsonl
python tests/dispatch_eval/analyze.py --sweep-mode --runs /tmp/rc1_sweep.jsonl
```

Secondary Haiku-4.5 cross-validation (Haiku has VETO on advanced-mode A/B/D per the disagreement rule — a Haiku-only failure on these criteria blocks final tag even if Qwen passes). **Reps=3 for matched power** — earlier draft used reps=2, which gave the veto rule asymmetric power (Haiku's effective n was below what the 10pp margin assumes). Bumping to 3 closes the gap.

```bash
export ANTHROPIC_API_KEY=<key>
python tests/dispatch_eval/runner.py --variant rc1 --mode advanced --model haiku-4.5 --reps 3 --probes tests/dispatch_eval/data/b1_b13_probes.jsonl --output /tmp/rc1_sweep_haiku.jsonl
python tests/dispatch_eval/analyze.py --sweep-mode --runs /tmp/rc1_sweep_haiku.jsonl --check-divergence /tmp/rc1_sweep.jsonl
```

Tertiary Llama-3.1-8B cross-validation (Llama has VETO on advanced-mode A/B/D per the disagreement rule — same blocking semantics as Haiku, catches Qwen-family overfitting). **Reps=3 for matched power.** If `tertiary_status: unavailable` was recorded at Gate 0b, this run is skipped here too — same documented decision.

```bash
# Boot Llama per Task B7 inference_setup.md.
python tests/dispatch_eval/runner.py --variant rc1 --mode advanced --model llama-3.1-8b-instruct --reps 3 --probes tests/dispatch_eval/data/b1_b13_probes.jsonl --output /tmp/rc1_sweep_llama.jsonl
python tests/dispatch_eval/analyze.py --sweep-mode --runs /tmp/rc1_sweep_llama.jsonl --check-divergence /tmp/rc1_sweep.jsonl
```

Quaternary Phi-3.5-mini cross-validation (Phi has VETO on advanced-mode A/B/D at 10pp per the disagreement rule — catches sub-7B-size-overfit, tightened from 12pp because the sub-4B size class is the deployment population most at risk from the surface change). **Reps=5 for matched power** — matched to the primary so the 10pp veto on the sub-4B size class isn't strictly weaker than the same margin on the 8B-class secondaries. Reps are cheap on a 3.8B model — variance reduction without sacrificing detection power. If `quaternary_status: unavailable` (or `quaternary_model_substituted` was recorded), follow the same path: skip if unavailable, or run the substitute (Qwen-2.5-3B) instead.

```bash
# Boot Phi per Task B7 inference_setup.md (or Qwen-3B if substituted).
python tests/dispatch_eval/runner.py --variant rc1 --mode advanced --model phi-3.5-mini-instruct --reps 5 --probes tests/dispatch_eval/data/b1_b13_probes.jsonl --output /tmp/rc1_sweep_phi.jsonl
python tests/dispatch_eval/analyze.py --sweep-mode --runs /tmp/rc1_sweep_phi.jsonl --check-divergence /tmp/rc1_sweep.jsonl
```

- [ ] **Step 2: For each defect surfaced, file an issue, fix, re-sweep**

The b-series methodology has been the de-facto pattern for b2 → b13 — same loop. Failing probes go into the next iteration's targeted fix list.

- [ ] **Step 3: Repeat until full-set pass criteria are met**

Pass criteria:

- (a) all ~150 probes succeed at ≥90% pass rate aggregate on Qwen-2.5-7B,
- (b) per-class accuracy on b-series F1 hardened classes (Z1–Z4, OPP-1, Sub-pattern-C, filler-prose, possessive) within 8pp of b13 baseline,
- (c) Z4-specific harm rate ≤5% absolute (Criterion C3 under live conditions),
- (d) Haiku, Llama, and Phi (where available) do not flag A/B/D regressions at their respective veto margins (10pp / 10pp / 10pp; Phi at reps=5 for matched power) — if any does, final tag blocks until reconciled.

### Task E2: `zim_get` dispatch sweep

- [ ] **Step 1: Run the 24 legal probes + ≥13 schema-bypass probes** (full set from Task D15 — one probe per oneOf-forbidden combination across the 4 branches)

(Per spec §rc1 stabilization step 2.)

- [ ] **Step 2: Pass criteria: ≥95% legal probes succeed AND 100% of bypass probes return structured `tool_error("invalid_path_combination", hint=...)` with the expected hint substring**

The bypass count tightened from "≥6" to "≥13" to match the per-forbidden-combination coverage requirement Task D15 enforces. If Task D15's parametrize list grows (e.g., a new combination becomes forbidden), this sweep grows in lockstep.

### Task E3: A/B confirmation sweep vs b13 baseline — full b-series set + F2 enforcement on Gate 0b set

The A/B confirmation runs the full b1 → b13 set at the same 5pp non-inferiority margin Gate 0b's Criterion D uses, AND re-runs the 300-probe Gate 0b set to enforce F2 at Stage E. F2 enforcement here (not just at Gate 0b) catches the case where a fix between Gate 0b and rc1 patches one defect at the cost of a localized per-class regression that Gate 0b never saw — the prototype-to-rc1 rewrite is the riskiest moment in the timeline for this.

- [ ] **Step 1: Run the FULL b1 → b13 probe set against rc1 with Qwen, 5 reps**

```bash
python tests/dispatch_eval/runner.py --variant rc1 --mode advanced --model qwen2.5-7b-instruct --reps 5 --probes tests/dispatch_eval/data/b1_b13_probes.jsonl --output /tmp/rc1_ab.jsonl
python tests/dispatch_eval/analyze.py --ab-confirmation --baseline tests/dispatch_eval/baselines/b13.json --runs /tmp/rc1_ab.jsonl
```

If Task E1 already ran with `--reps 5` against the same probe set, the output files can be reused.

- [ ] **Step 2: Pass criterion: `rc1_correct ≥ b13_correct - 5 points`** (1-sided non-inferiority α=0.05). A regression here means the prototype-vs-rc1 divergence is real and must be investigated before final tag.

- [ ] **Step 3: Re-run the 300-probe Gate 0b set against rc1 with all available models, enforce F2 at the 10pp ceiling**

```bash
# Primary (Qwen-7B)
python tests/dispatch_eval/runner.py --variant rc1 --mode advanced --model qwen2.5-7b-instruct --reps 5 --probes tests/dispatch_eval/probes.jsonl --output /tmp/rc1_300__qwen.jsonl

# Secondary (Haiku, reps=3 for matched veto power)
python tests/dispatch_eval/runner.py --variant rc1 --mode advanced --model haiku-4.5 --reps 3 --probes tests/dispatch_eval/probes.jsonl --output /tmp/rc1_300__haiku.jsonl

# Tertiary (Llama-8B, reps=3); skip if tertiary_status=unavailable in gate decision
python tests/dispatch_eval/runner.py --variant rc1 --mode advanced --model llama-3.1-8b-instruct --reps 3 --probes tests/dispatch_eval/probes.jsonl --output /tmp/rc1_300__llama.jsonl

# Quaternary (Phi-3.5-mini, reps=5 — matched to primary; sub-4B variance handled via reps not margin); skip if quaternary_status=unavailable
python tests/dispatch_eval/runner.py --variant rc1 --mode advanced --model phi-3.5-mini-instruct --reps 5 --probes tests/dispatch_eval/probes.jsonl --output /tmp/rc1_300__phi.jsonl

# F2 enforcement: re-use Gate 0b analyzer to compute per-class deltas vs b13
python tests/dispatch_eval/analyze.py \
  --b13-runs tests/dispatch_eval/runs/b13__advanced__*.jsonl \
  --phase-f-runs /tmp/rc1_300__*.jsonl \
  --f2-enforcement-only \
  --output /tmp/rc1_f2_verdict.json
```

`--f2-enforcement-only` is a new analyzer mode that computes per-class F2 deltas on the rc1 runs vs the committed b13 baseline cells, skipping A/B/C/D verdicts (those are owned by Gate 0b). Writes a focused F2-only verdict file.

- [ ] **Step 4: Pass criterion: F2 holds at 10pp ceiling per Phase F operation class on the primary AND no secondary/tertiary/quaternary veto fires at the secondary/tertiary/quaternary's respective margins on A/B/D**

A failure here is a hard STOP for the v2.0.0 final tag. Localized fix → re-run E3 Step 3 → re-verify F2. A class that regressed at Stage E but passed Gate 0b means the rc1 implementation's actual descriptions / `oneOf` shapes diverged from the prototype's in a way the prototype↔rc1 parity test ([Task D14b](#task-d14b-prototype-rc1-schema-parity-test)) didn't catch (e.g., the description bytes fit inside ±5% but the prose meaningfully changed the dispatch signal). Investigation may require tightening the prototype↔rc1 parity test, not just patching the regressing class.

### Task E4: Migration conformance test in CI

- [ ] **Step 1: Verify `test_phase_f_migration_conformance.py` runs in default CI** (should already be picked up by `pytest`).

### Task E5: Update website demo to rc1

(Out-of-tree integration. Coordinate with maintainer.)

### Task E6: Cut `v2.0.0` final tag

- [ ] **Step 1: When all of E1–E5 pass cleanly:**

```bash
git checkout main
git tag v2.0.0
git push origin v2.0.0
```

- [ ] **Step 2: Update `docs/v2/README.md` Phase F row to `Shipped`**

- [ ] **Step 3: Document v1.x maintenance scope in the v1.x branch README and the v2.0.0 release notes**

Per the spec's [v1.x maintenance commitment](../specs/2026-05-24-v2-phase-f-tool-surface-design.md#v1x-maintenance-commitment-rollback-runway):

- Accepted backports: security fixes (always), data-corruption fixes (always), pre-v2.0.0 crash bugs.
- Rejected: new features, new tools, performance work, refactors.
- EOL trigger: the FIRST of {`v2.5.0` ships, 6 calendar months after v2.0.0}.

---

## Self-review checklist

Run through this after the plan is complete:

- [ ] **Spec coverage.** Every spec section has a task:
  - Gate 0 (`oneOf` transport verification — 2 sub-gates now) → Tasks Z0, Z0a, Z1, Z2 (Stage 0)
  - rc0 refactor + Gate 0a diff-tests (promotion AND auto-select extractions) → Tasks A0–A9 (Stage A), including Task A3a for the auto-select parity test
  - Gate 0b harness build (probe set + runner + analyzer) + prototype skeletons + Gate 0.3 against actual prototype schemas → Tasks B1–B7 (Stage B; Gate 0.3 is now Task B2a, moved from Stage 0)
  - Prototype wire-footprint snapshot for parity check → Task B2 Step 6
  - Gate 0b runs (Qwen + Haiku + Llama + Phi) + decision rule + decision artifact + fallback C1/C2/C3 re-check → Tasks C1–C3 (Stage C)
  - 8 per-tool implementations → Tasks D3–D10 (Stage D)
  - Schema-budget + schema-shape + gate-decision-consistency + prototype↔rc1 parity + schema-bypass tests → Tasks D13–D15 (D14a + D14b inclusive)
  - `tool_mode` stale-docstring fix → Task D18
  - Migration story (CHANGELOG + conformance test) → Tasks D19–D20
  - Stabilization sweep (b-series + `zim_get` dispatch + A/B confirmation **with F2 enforcement on Gate 0b set** + migration conformance) on Qwen primary + Haiku + Llama (reps=3) + Phi (reps=5 for matched power) secondaries → Tasks E1–E6
- [ ] **No placeholders.** Every task has either complete code, a reference to existing code, or an explicit command to run.
- [ ] **Type consistency.** `ArchiveMetadataResponse` in Task D1 matches usage in Task D2 and D8. `register_phase_f_tools` defined in Task D11 referenced by all per-tool register tasks (D3–D10).
- [ ] **Production code does NOT read `gate_0b_decision.json` at runtime — no exceptions.** Verify:
  - `openzim_mcp/tools/zim_query.py` reads description from committed `zim_query_description.md`. NOT from the decision JSON.
  - `openzim_mcp/tools/__init__.py`'s `register_phase_f_tools` reads only `server.config.tool_mode` (Task D11). NOT the decision JSON.
  - `openzim_mcp/tools/zim_get.py` has `compact: bool = False` baked in as a literal default. NOT a runtime read.
  - `openzim_mcp/tools/zim_search.py` has `_CRITERION_C_PATH: Literal["wired","fallback"] = "..."` baked in as a literal at module level (Task D4 Step 2). NOT a runtime read. Drift between the constant and the decision file is caught by `tests/test_phase_f_gate_decision_consistency.py` (Task D14a).
  - `openzim_mcp/config.py` `tool_mode` Literal is binary (`simple` / `advanced`); default is `simple`. NOT a runtime read of the gate file.
  - Only `tests/test_phase_f_schema_budget.py`, `tests/test_phase_f_schema_shapes.py`, and `tests/test_phase_f_gate_decision_consistency.py` read the JSON — at test time only, NOT shipped in the wheel.
- [ ] **Decision routing.** Task C3 (Gate 0b outcome) explicitly handles each criterion:
  - Criterion D failure → STOP (rc1 does not open).
  - Any of C1/C2/C3 failure on wired path → apply pre-decided fallback (legibility framing); re-run fallback cell on Qwen + Haiku + Llama + Phi; **re-check ALL of fallback-C1 + fallback-C2 + fallback-C3 on the fallback cell** (the legibility fix must reduce routing harm AND not introduce new dispatch confusion); proceed if A/B/D/F AND all three fallback-C all pass.
  - Any of fallback-C1/C2/C3 fails → STOP. Gate authors choose between dropping title mode from advanced entirely or returning to design. Shipping a known Z4 silent-wrong-answer harm is NOT an option — the b-series spent 17 sweeps eliminating exactly that regression class.
  - Criterion F1 failure (per-class, b-series hardened, 8pp ceiling) → localized investigation, no architectural amend.
  - Criterion F2 failure (per-class, Phase F operation, **10pp ceiling — tightened from 15pp; enforced at BOTH Gate 0b AND Stage E Task E3**) → localized investigation (likely a description-prose or oneOf-shape fix), no architectural amend.
  - Haiku OR Llama OR Phi secondary blocking failure on A/B/D/C at their respective margins (10pp / 10pp / 10pp; Phi at reps=5 for matched power) → STOP per disagreement rule.
  - Tertiary status unavailable → documented decision, does not block (but flags the architecture-overfit risk in the artifact).
  - Quaternary status unavailable → documented decision, does not block (but flags the sub-7B-size blind spot in the artifact).
  - All pass → proceed to Stage D.
- [ ] **Migration safety.** Task D19 CHANGELOG sub-section calls out:
  - `zim_get_section` new `compact=True` default.
  - `zim_metadata` removal of `main_page_path`.
  - The `zim_get` rename is behavior-preserving (compact=False default).
  Task D20 conformance test exercises both default and explicit `compact` shapes on every body-returning row.
- [ ] **All three of C1/C2/C3 are enforced on wired AND fallback paths.** Task B3 pins ≥20 Z4-tagged `zim_query_preferred` probes (powers C3). Task B5's analyzer computes C1/C2/C3 on the wired cell AND on the fallback cell when it runs (Task C3 Step 3 `--fallback-c3-check` computes all three, despite the flag name). Task C3 decision rule blocks rc1 if any wired-C OR any fallback-C fails — fallback must reduce harm AND not introduce new confusion.
- [ ] **cross_file + mode=title handling is correct.** Task D4 disables promotion when `cross_file=True` and surfaces `_meta.promotion_applied: false` plus a hint. Tested in `test_zim_search.py`.
- [ ] **`zim_search` uses the rc0-extracted `auto_select_zim_file`, not an inline reimplementation.** Task A4 extracts BOTH `promote_topic_via_title_index` AND `auto_select_zim_file` to `topic_preprocessing.py`. Task D4 Step 2's title-mode handler imports both. The auto-select extraction preserves the operator-visible diagnostic surface (try/except envelope + 4-arm log emits) that an inline ~5-line reimplementation would silently lose. Pinned by Task A3a's `test_auto_select_extraction_parity.py` diff-test (return value AND `caplog`-captured log records across 4 archive-count scenarios).
- [ ] **Document-and-ship Z4 harm is NOT an option.** Task C3 Step 2 decision-rule row for "any of C1/C2/C3 fails" requires that gate authors choose between (a) dropping title mode from advanced or (b) returning to design. The earlier (c) "document a known Z4 harm in v2.0 release notes and ship anyway" option is removed — the b-series spent 17 sweeps eliminating exactly this regression class, and the surface change must not reintroduce it. Mirrored in spec §Criterion C circuit-breaker decision flow.
- [ ] **Two open-weights small-model families + two open-weights size classes are measured.** Task B7 plumbs Qwen-2.5-7B (primary), Llama-3.1-8B (tertiary, ~8B class, different family), Phi-3.5-mini (quaternary, sub-4B class, third family). Task C1 + Task C2 run all three secondaries on `b13×advanced` + `phase-f×advanced` cells. Task C3 decision rule blocks rc1 on any secondary's blocking failure. **Phi quaternary uses 10pp veto margin (matched to tertiary, tightened from 12pp) with reps=5 (matched to primary) — variance handled via rep count rather than wider margin because the sub-4B size class is the deployment population most at risk from the surface change.** Each unavailable status is a documented decision, not a silent skip.
- [ ] **Phi substitution fallback is documented.** If vLLM's `pythonic` parser is flaky for Phi-3.5 in the deployer's vLLM version, substitute Qwen-2.5-3B-Instruct (same `hermes` parser as primary). Record under `quaternary_model_substituted` in the gate decision and append a `"substitution: ..."` entry to `scope_limitations`. Substitution costs the architecture-diversity-at-small-size signal but preserves the size signal.
- [ ] **Prototype↔rc1 schema parity is enforced on three axes.** Task B2 Step 6 snapshots per-tool wire footprints AND descriptions. Task D0 Step 2 cherry-picks the snapshot. Task D14b's test blocks rc1 merge on (a) >±5% byte drift, (b) any structural inputSchema change, OR (c) >30% Levenshtein edit distance on the description prose. The edit-distance check catches the case where an rc1 author rewrites a description significantly while preserving byte count — pure prose rewrites can change the dispatch signal Gate 0b measured even when bytes and structure are preserved.
- [ ] **Gate 0.3 measures actual production schemas.** Task B2a (moved from Stage 0) imports the prototype skeleton schemas directly and runs the ablation against them — not synthetic stand-ins. STOP-AMEND-SPEC path re-authors the prototype with flat signatures + re-snapshots.
- [ ] **F2 is enforced at BOTH Gate 0b AND Stage E.** Gate 0b's Task C3 catches prototype-level regressions; Stage E's Task E3 Step 3 re-runs the 300-probe Gate 0b set against rc1 with all available models and asserts F2 holds at the 10pp ceiling on the primary. A class that passed Gate 0b but regresses at Stage E means the rc1 implementation drifted from the prototype's behavior in a way the byte-parity test didn't catch — investigation may require tightening Task D14b.
- [ ] **`scope_limitations` field is non-empty + required prefixes present.** Task D13's `test_gate_decision_scope_limitations_documented` asserts `probe-distribution:`, `model-coverage:`, `size-range:`, `probe-language:` entries exist. A maintainer re-running Gate 0b under different conditions and forgetting to update this trips the test.
- [ ] **Cherry-pick conflict handling is asymmetric and documented.** Task D0 Step 2 specifies per-file rules: favor prototype for load-bearing Gate 0b artifacts (decision JSON, per-cell runs, schema snapshot) but require three-way merge for probe sets (`probes.jsonl`, `b1_b13_probes.jsonl`) AND take-both for infrastructure code (`runner.py`, `analyze.py`). This prevents silently rolling back probe-set improvements landed on main between rc0 sign-off and rc1 branching (e.g., a sweep-discovered Z4 shape that should ship in the v2.0 baseline).
- [ ] **Prototype branch HEAD is pinned for long-term Gate 0b reproducibility.** Task C3 Step 5 creates the annotated tag `v2.0.0-gate-0b-prototype` carrying the audit trail in its message. A post-v2.0 Gate 0b re-run checks out the tag directly; no archaeology required to resurrect the throwaway prototype branch. v2.0.0 release notes document the reproducibility recipe.
