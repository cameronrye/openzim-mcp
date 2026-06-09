# Dispatch-eval honours `either_acceptable` (#199) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `analyze.py` honour the probe set's existing `tool_eligibility == "either_acceptable"` flag so a `zim_query` dispatch counts as correct for those probes, lifting the measured `zim_get-summary` / `-structure` / `-main-page` accuracy above the ≥70% floor without changing any production/dispatch code.

**Architecture:** A pure helper `_effective_dispatch_correct(outcome, probe)` in `tests/dispatch_eval/analyze.py`, applied inside `aggregate_cell` everywhere `o.dispatch_correct` currently drives scoring (overall rate, composite, per-class). The runner is untouched; the policy lives in analysis, so it re-scores the committed run and any fresh run with one definition.

**Tech Stack:** Python 3.12, pytest. No model needed for the code change or its unit tests.

**Spec:** [docs/specs/2026-06-09-v2.5-dispatch-eval-either-acceptable-design.md](../../specs/2026-06-09-v2.5-dispatch-eval-either-acceptable-design.md)

---

## Task 1: `analyze.py` honours `either_acceptable`

**Files:**

- Modify: `tests/dispatch_eval/analyze.py` (add helper above `aggregate_cell` line 332; use it in the loop lines 339-385)
- Test: `tests/dispatch_eval/test_analyze.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/dispatch_eval/test_analyze.py` (it already imports `aggregate_cell`, `Outcome`, `_make_probe_meta`; add a small local builder for outcomes with an explicit `tool_called` and `dispatch_correct=False`):

```python
def _miss_outcomes(n, *, tool_called, probe_id_prefix="p"):
    return [
        Outcome(
            probe_id=f"{probe_id_prefix}-{i}",
            rep=0,
            tool_called=tool_called,
            parameters={},
            dispatch_correct=False,
            parameter_validity="load_bearing_match",
            spurious_route=False,
            spurious_route_kind=None,
            resolved_entry_path=None,
            cell_variant="rc1",
            cell_mode="advanced",
            cell_model="qwen3-8b-q4",
        )
        for i in range(n)
    ]


def test_either_acceptable_zim_query_counts_correct():
    outcomes = _miss_outcomes(10, tool_called="zim_query")
    probe_meta = _make_probe_meta(
        10, classes=["zim_get-summary"], tool_eligibility="either_acceptable"
    )
    s = aggregate_cell(outcomes, probe_meta)
    # zim_query on an either_acceptable probe is relaxed to correct
    assert s.per_class["zim_get-summary"] == (10, 10)
    assert s.dispatch_correct == 10
    assert s.composite_correct == 10  # parameter_validity != "fail"


def test_either_acceptable_wrong_tool_still_misses():
    outcomes = _miss_outcomes(10, tool_called="zim_metadata")
    probe_meta = _make_probe_meta(
        10, classes=["zim_get-main-page"], tool_eligibility="either_acceptable"
    )
    s = aggregate_cell(outcomes, probe_meta)
    # a dispatch to a third tool is NOT relaxed
    assert s.per_class["zim_get-main-page"] == (10, 0)
    assert s.dispatch_correct == 0


def test_non_either_acceptable_zim_query_unchanged():
    outcomes = _miss_outcomes(10, tool_called="zim_query")
    probe_meta = _make_probe_meta(10, classes=["X"], tool_eligibility="any")
    s = aggregate_cell(outcomes, probe_meta)
    # strict scoring stands when the probe is not either_acceptable
    assert s.per_class["X"] == (10, 0)
    assert s.dispatch_correct == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/dispatch_eval/test_analyze.py -k "either_acceptable or non_either" -v --no-cov`
Expected: FAIL — `test_either_acceptable_zim_query_counts_correct` sees `(10, 0)` / `dispatch_correct == 0` (no relaxation yet); the other two already pass.

- [ ] **Step 3: Add the helper**

In `tests/dispatch_eval/analyze.py`, add directly above `def aggregate_cell` (line 332):

```python
def _effective_dispatch_correct(o: "Outcome", probe: Dict[str, Any]) -> bool:
    """``dispatch_correct``, relaxed to honour the probe's ``tool_eligibility``.

    A probe tagged ``either_acceptable`` declares that BOTH its
    ``expected_tool`` and ``zim_query`` (the documented natural-language
    entry path) are correct outcomes, so a ``zim_query`` dispatch counts
    as correct. A dispatch to any other tool still misses.
    """
    if o.dispatch_correct:
        return True
    if (
        probe.get("tool_eligibility") == "either_acceptable"
        and o.tool_called == "zim_query"
    ):
        return True
    return False
```

- [ ] **Step 4: Apply it in `aggregate_cell`**

In the per-outcome loop (lines 339-385), move the `probe` fetch above the counters and replace the three `o.dispatch_correct` uses with the effective value. The loop body becomes:

```python
    for o in outcomes:
        if not summary.variant:
            summary.variant = o.cell_variant
            summary.mode = o.cell_mode
            summary.model = o.cell_model
            summary.family = _family_of(o.cell_model) or "primary"
        summary.n += 1

        probe = probe_meta.get(o.probe_id, {})
        eff = _effective_dispatch_correct(o, probe)
        if eff:
            summary.dispatch_correct += 1
        if o.parameter_validity == "load_bearing_match":
            summary.load_bearing_match += 1
        if eff and o.parameter_validity != "fail":
            summary.composite_correct += 1

        # Per-class accounting (F1/F2)
        classes = probe.get("operational_classes", []) or []
        for cls in classes:
            per_class_n[cls] += 1
            if eff:
                per_class_correct[cls] += 1

        # Criterion C — zim_query_preferred subset
        if probe.get("tool_eligibility") == "zim_query_preferred":
            summary.zqp_n += 1
            if o.spurious_route:
                summary.zqp_spurious_route += 1
                if o.spurious_route_kind == "answer_degrading":
                    summary.zqp_spurious_answer_degrading += 1
                elif o.spurious_route_kind == "answer_preserving":
                    summary.zqp_spurious_answer_preserving += 1

            # Criterion C3 — Z4 subset of zim_query_preferred
            if "Z4" in classes:
                summary.z4_zqp_n += 1
                if o.spurious_route and o.spurious_route_kind == "answer_degrading":
                    summary.z4_zqp_answer_degrading += 1
```

(Delete the now-duplicated `probe = probe_meta.get(...)` that previously sat above the per-class block.)

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/dispatch_eval/test_analyze.py -v --no-cov`
Expected: PASS (all — the 3 new tests plus every existing test; existing tests use `tool_eligibility` `"any"`/`"zim_query_preferred"`, so `_effective_dispatch_correct` returns the unrelaxed `o.dispatch_correct` for them).

- [ ] **Step 6: Commit**

```bash
git add tests/dispatch_eval/analyze.py tests/dispatch_eval/test_analyze.py
git commit -m "feat(dispatch-eval): analyze.py honours either_acceptable in scoring (#199)"
```

---

## Task 2: Verify the floor is cleared on the committed run

This is the authoritative, deterministic proof — re-score the real 2026-05-27 model outputs with the patched analyzer.

**Files:** none (verification only).

- [ ] **Step 1: Re-analyse the committed rc1 run**

Run:

```bash
uv run python tests/dispatch_eval/analyze.py --sweep-mode \
  --runs tests/dispatch_eval/runs/rc1__advanced__qwen3-8b-q4__2026-05-27T03-31-27Z.jsonl
```

Capture the per-class accuracy for `zim_get-summary`, `zim_get-structure`, `zim_get-main-page`.
Expected: each ≥ 70% (projected ~100% / ~100% / ~90% from the issue's dispatch data). No class regresses (the relaxation is monotonic).

- [ ] **Step 2: Record the before/after numbers**

If `analyze.py`'s sweep output does not already print per-class accuracy in a readable form, capture the three weak-class figures (and a couple of strong classes to show no regression) into the PR description. No code change; this is evidence-gathering.

- [ ] **Step 3 (optional, opportunistic): model-verified spot-check**

If the live endpoint throughput allows (the node's cold first call needs a high timeout to warm the llama.cpp tool-prefix cache), run a fresh sweep over the three weak classes and analyse it the same way:

```bash
OZM_VLLM_BASE_URL=https://chat.owl-atlas.ts.net/v1 \
OZM_OWL_ATLAS_API_KEY=<key> OZM_DISPATCH_TIMEOUT_S=240 \
uv run python tests/dispatch_eval/runner.py --variant rc1 --mode advanced \
  --model qwen3-8b-q4 --reps 3 --probes <weak-class-subset>.jsonl --output <out>.jsonl
uv run python tests/dispatch_eval/analyze.py --sweep-mode --runs <out>.jsonl
```

Expected: the three weak classes clear ≥70% on live data too. This is confirmation, not a gate — the committed-run re-analysis is the proof. Do NOT commit the API key or the fresh run output unless it is intended as a committed artifact.
