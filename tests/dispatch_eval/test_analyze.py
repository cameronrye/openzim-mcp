"""Unit tests for tests/dispatch_eval/analyze.py — non-inferiority + decision rule.

Runs only with --dispatch-eval flag (matches the other dispatch_eval tests).
Synthetic outcomes; no real model calls.

The tests pin the analyzer's verdict logic on synthetic per-cell outcomes
so a future refactor doesn't silently change the gating math.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from tests.dispatch_eval.analyze import (
    C1_CEILING,
    C2_MIN_EVENTS,
    C3_CEILING,
    C3_MIN_EVENTS,
    F1_CEILING,
    F2_CEILING,
    PRIMARY_MARGIN,
    Outcome,
    _apply_fallback_c_check,
    _build_gate_decision,
    aggregate_cell,
    apply_disagreement_rule,
    criterion_a_b_d,
    criterion_c1,
    criterion_c2,
    criterion_c3,
    criterion_f1,
    criterion_f2,
    non_inferiority_test,
)

# --------------------------------------------------------------------------
# Synthetic outcome builders
# --------------------------------------------------------------------------


def _make_outcomes(
    *,
    n_correct: int,
    n_total: int,
    cell_variant: str,
    cell_model: str,
    cell_mode: str = "advanced",
    probe_id_prefix: str = "p",
    parameter_validity: str = "load_bearing_match",
    spurious_route: bool = False,
    spurious_route_kind: Optional[str] = None,
    resolved_entry_path: Optional[str] = None,
    tool_called: Optional[str] = "zim_query",
) -> List[Outcome]:
    """Build n_total Outcome rows; first n_correct have dispatch_correct=True."""
    out: List[Outcome] = []
    for i in range(n_total):
        is_correct = i < n_correct
        out.append(
            Outcome(
                probe_id=f"{probe_id_prefix}-{i}",
                rep=0,
                tool_called=tool_called if is_correct else "wrong_tool",
                parameters={"query": "x"},
                dispatch_correct=is_correct,
                parameter_validity=parameter_validity if is_correct else "fail",
                spurious_route=spurious_route,
                spurious_route_kind=spurious_route_kind,
                resolved_entry_path=resolved_entry_path,
                cell_variant=cell_variant,
                cell_mode=cell_mode,
                cell_model=cell_model,
            )
        )
    return out


def _make_probe_meta(
    n_probes: int,
    *,
    classes: Optional[List[str]] = None,
    tool_eligibility: str = "any",
    probe_id_prefix: str = "p",
) -> Dict[str, Dict[str, Any]]:
    """Build a {probe_id: probe_dict} stub with the given operational_classes."""
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(n_probes):
        out[f"{probe_id_prefix}-{i}"] = {
            "probe_id": f"{probe_id_prefix}-{i}",
            "operational_classes": list(classes or []),
            "tool_eligibility": tool_eligibility,
            "expected_resolved_entry_path": None,
        }
    return out


# --------------------------------------------------------------------------
# Test 1 — non-inferiority passes when phase-f matches b13
# --------------------------------------------------------------------------


def test_non_inferiority_passes_when_phase_f_matches_b13() -> None:
    """Both variants 90% accurate → primary margin 5pp passes."""
    # Large n (~300) so the z-statistic actually clears 1.645.
    b13 = _make_outcomes(
        n_correct=270, n_total=300, cell_variant="b13", cell_model="qwen2.5-7b-instruct"
    )
    phase_f = _make_outcomes(
        n_correct=270,
        n_total=300,
        cell_variant="phase-f",
        cell_model="qwen2.5-7b-instruct",
    )
    probe_meta = _make_probe_meta(300)
    b13_summary = aggregate_cell(b13, probe_meta)
    pf_summary = aggregate_cell(phase_f, probe_meta)
    verdicts = criterion_a_b_d(b13_summary, pf_summary, PRIMARY_MARGIN)
    assert verdicts["A"]["pass"] is True
    assert verdicts["B"]["pass"] is True
    assert verdicts["D"]["pass"] is True
    assert math.isclose(verdicts["A"]["delta_pp"], 0.0)


# --------------------------------------------------------------------------
# Test 2 — non-inferiority fails when phase-f regresses beyond margin
# --------------------------------------------------------------------------


def test_non_inferiority_fails_when_phase_f_regresses_beyond_margin() -> None:
    """b13 at 90%, phase-f at 80% — 10pp drop fails primary 5pp margin."""
    b13 = _make_outcomes(
        n_correct=270, n_total=300, cell_variant="b13", cell_model="qwen2.5-7b-instruct"
    )
    phase_f = _make_outcomes(
        n_correct=240,
        n_total=300,
        cell_variant="phase-f",
        cell_model="qwen2.5-7b-instruct",
    )
    probe_meta = _make_probe_meta(300)
    b13_summary = aggregate_cell(b13, probe_meta)
    pf_summary = aggregate_cell(phase_f, probe_meta)
    verdicts = criterion_a_b_d(b13_summary, pf_summary, PRIMARY_MARGIN)
    assert verdicts["A"]["pass"] is False
    assert verdicts["A"]["delta_pp"] < -5.0


# --------------------------------------------------------------------------
# Test 3 — secondary failure at 10pp margin blocks gate
# --------------------------------------------------------------------------


def test_secondary_failure_at_10pp_margin_blocks() -> None:
    """Qwen passes at 5pp; Haiku regresses by 12pp → gate BLOCKS."""
    probe_meta = _make_probe_meta(300, probe_id_prefix="q")
    haiku_meta = _make_probe_meta(150, probe_id_prefix="h")
    probe_meta.update(haiku_meta)

    # Qwen primary — matched accuracy
    qwen_b13 = _make_outcomes(
        n_correct=270,
        n_total=300,
        cell_variant="b13",
        cell_model="qwen2.5-7b-instruct",
        probe_id_prefix="q",
    )
    qwen_pf = _make_outcomes(
        n_correct=265,
        n_total=300,
        cell_variant="phase-f",
        cell_model="qwen2.5-7b-instruct",
        probe_id_prefix="q",
    )

    # Haiku — regresses by 12pp (b13: 90%, phase-f: 78%)
    haiku_b13 = _make_outcomes(
        n_correct=135,
        n_total=150,
        cell_variant="b13",
        cell_model="haiku-4.5",
        probe_id_prefix="h",
    )
    haiku_pf = _make_outcomes(
        n_correct=117,
        n_total=150,
        cell_variant="phase-f",
        cell_model="haiku-4.5",
        probe_id_prefix="h",
    )

    decision = _build_gate_decision(
        qwen_b13 + haiku_b13, qwen_pf + haiku_pf, probe_meta
    )
    assert decision["gate_passed"] is False, decision["criteria"]["D"]
    secondary_fails = decision["secondary_blocking_failures"]
    # Should include at least one of criterion_A/B/D for the secondary family
    assert any(
        "criterion_" in f for f in secondary_fails
    ), f"expected criterion_X in {secondary_fails}"


# --------------------------------------------------------------------------
# Test 4 — Criterion C1 ceiling enforced
# --------------------------------------------------------------------------


def test_criterion_c1_ceiling_5pp_enforced() -> None:
    """6% answer-degrading rate fails C1 (5% ceiling)."""
    n_zqp = 100
    probe_meta = _make_probe_meta(n_zqp, tool_eligibility="zim_query_preferred")
    # 6 out of 100 zim_query_preferred probes spurious-route to a degrading
    # answer. We model this via spurious_route=True AND
    # spurious_route_kind="answer_degrading".
    outcomes: List[Outcome] = []
    for i in range(n_zqp):
        outcomes.append(
            Outcome(
                probe_id=f"p-{i}",
                rep=0,
                tool_called="zim_search",
                parameters={"mode": "title"},
                dispatch_correct=False,
                parameter_validity="schema_only",
                spurious_route=i < 6,
                spurious_route_kind="answer_degrading" if i < 6 else None,
                resolved_entry_path=None,
                cell_variant="phase-f",
                cell_mode="advanced",
                cell_model="qwen2.5-7b-instruct",
            )
        )
    summary = aggregate_cell(outcomes, probe_meta)
    c1 = criterion_c1(summary)
    assert c1["pass"] is False
    assert c1["rate"] > C1_CEILING
    # Sanity: at 4 events, the rate would clear the ceiling
    outcomes_pass: List[Outcome] = []
    for i in range(n_zqp):
        outcomes_pass.append(
            Outcome(
                probe_id=f"p-{i}",
                rep=0,
                tool_called="zim_search",
                parameters={"mode": "title"},
                dispatch_correct=False,
                parameter_validity="schema_only",
                spurious_route=i < 4,
                spurious_route_kind="answer_degrading" if i < 4 else None,
                resolved_entry_path=None,
                cell_variant="phase-f",
                cell_mode="advanced",
                cell_model="qwen2.5-7b-instruct",
            )
        )
    summary_pass = aggregate_cell(outcomes_pass, probe_meta)
    c1_pass = criterion_c1(summary_pass)
    assert c1_pass["pass"] is True
    assert c1_pass["rate"] <= C1_CEILING


# --------------------------------------------------------------------------
# Test 5 — C2 underpowered below 10 events
# --------------------------------------------------------------------------


def test_criterion_c2_underpowered_below_10_events() -> None:
    """Fewer than 10 misroute events → C2 reported as null (underpowered)."""
    n_zqp = 100
    probe_meta = _make_probe_meta(n_zqp, tool_eligibility="zim_query_preferred")
    # Only 5 misroutes total — below the C2_MIN_EVENTS=10 floor
    outcomes: List[Outcome] = []
    for i in range(n_zqp):
        outcomes.append(
            Outcome(
                probe_id=f"p-{i}",
                rep=0,
                tool_called="zim_search" if i < 5 else "zim_query",
                parameters={"mode": "title"} if i < 5 else {},
                dispatch_correct=i >= 5,
                parameter_validity="load_bearing_match" if i >= 5 else "schema_only",
                spurious_route=i < 5,
                spurious_route_kind="answer_preserving" if i < 5 else None,
                resolved_entry_path=None,
                cell_variant="phase-f",
                cell_mode="advanced",
                cell_model="qwen2.5-7b-instruct",
            )
        )
    summary = aggregate_cell(outcomes, probe_meta)
    c2 = criterion_c2(summary)
    assert c2["pass"] is None, c2
    assert c2["rate"] is None
    assert c2["events"] < C2_MIN_EVENTS


# --------------------------------------------------------------------------
# Test 6 — C3 Z4 floor enforced
# --------------------------------------------------------------------------


def test_criterion_c3_z4_floor_enforced() -> None:
    """Z4-specific answer-degrading rate > 5% fails C3 even if C1 passes globally."""
    # 100 z-q-preferred probes; 25 of them are Z4 with 4 answer-degrading
    # routes (16% Z4 rate). Only 4 / 100 = 4% global degrading, so C1 passes.
    n_zqp = 100
    n_z4 = 25
    probe_meta: Dict[str, Dict[str, Any]] = {}
    for i in range(n_zqp):
        probe_meta[f"p-{i}"] = {
            "probe_id": f"p-{i}",
            "operational_classes": ["Z4"] if i < n_z4 else [],
            "tool_eligibility": "zim_query_preferred",
        }

    outcomes: List[Outcome] = []
    for i in range(n_zqp):
        is_z4 = i < n_z4
        is_degrading = is_z4 and i < 4
        outcomes.append(
            Outcome(
                probe_id=f"p-{i}",
                rep=0,
                tool_called="zim_search" if is_degrading else "zim_query",
                parameters={"mode": "title"} if is_degrading else {},
                dispatch_correct=not is_degrading,
                parameter_validity=(
                    "schema_only" if is_degrading else "load_bearing_match"
                ),
                spurious_route=is_degrading,
                spurious_route_kind="answer_degrading" if is_degrading else None,
                resolved_entry_path=None,
                cell_variant="phase-f",
                cell_mode="advanced",
                cell_model="qwen2.5-7b-instruct",
            )
        )
    summary = aggregate_cell(outcomes, probe_meta)
    c1 = criterion_c1(summary)
    c3 = criterion_c3(summary)
    # C1 should pass (4/100 = 4%); C3 should fail (4/25 = 16%)
    assert c1["pass"] is True
    assert c1["rate"] <= C1_CEILING
    assert c3["pass"] is False
    assert c3["rate"] > C3_CEILING
    assert c3["events"] >= C3_MIN_EVENTS


# --------------------------------------------------------------------------
# Test 7 — F1 per-class failure blocks
# --------------------------------------------------------------------------


def test_f1_failure_blocks_per_class() -> None:
    """Z3 class regresses by 9pp (above 8pp F1 ceiling) → blocked."""
    # 100 probes labeled Z3, b13 100% correct, phase-f 91% — delta -9pp
    n = 100
    probe_meta = _make_probe_meta(n, classes=["Z3"])
    b13 = _make_outcomes(
        n_correct=n,
        n_total=n,
        cell_variant="b13",
        cell_model="qwen2.5-7b-instruct",
    )
    phase_f = _make_outcomes(
        n_correct=91,
        n_total=n,
        cell_variant="phase-f",
        cell_model="qwen2.5-7b-instruct",
    )
    b13_summary = aggregate_cell(b13, probe_meta)
    pf_summary = aggregate_cell(phase_f, probe_meta)
    f1 = criterion_f1(b13_summary, pf_summary)
    assert f1["pass"] is False
    assert "Z3" in f1["failures"]
    assert f1["per_class_deltas"]["Z3"] <= -F1_CEILING * 100


# --------------------------------------------------------------------------
# Test 8 — F2 per-class failure blocks
# --------------------------------------------------------------------------


def test_f2_failure_blocks_per_class() -> None:
    """zim_get-toc regresses by 11pp (above 10pp F2 ceiling) → blocked."""
    n = 100
    probe_meta = _make_probe_meta(n, classes=["zim_get-toc"])
    b13 = _make_outcomes(
        n_correct=n,
        n_total=n,
        cell_variant="b13",
        cell_model="qwen2.5-7b-instruct",
    )
    phase_f = _make_outcomes(
        n_correct=89,
        n_total=n,
        cell_variant="phase-f",
        cell_model="qwen2.5-7b-instruct",
    )
    b13_summary = aggregate_cell(b13, probe_meta)
    pf_summary = aggregate_cell(phase_f, probe_meta)
    f2 = criterion_f2(b13_summary, pf_summary)
    assert f2["pass"] is False
    assert "zim_get-toc" in f2["failures"]
    assert f2["per_class_deltas"]["zim_get-toc"] <= -F2_CEILING * 100


# --------------------------------------------------------------------------
# Test 9 — secondary unavailable does not block
# --------------------------------------------------------------------------


def test_secondary_unavailable_does_not_block() -> None:
    """Haiku absent; primary passes → gate passes on primary alone."""
    probe_meta = _make_probe_meta(300)
    b13 = _make_outcomes(
        n_correct=270,
        n_total=300,
        cell_variant="b13",
        cell_model="qwen2.5-7b-instruct",
    )
    phase_f = _make_outcomes(
        n_correct=270,
        n_total=300,
        cell_variant="phase-f",
        cell_model="qwen2.5-7b-instruct",
    )
    decision = _build_gate_decision(b13, phase_f, probe_meta)
    assert decision["secondary_status"] == "unavailable"
    assert decision["tertiary_status"] == "unavailable"
    assert decision["quaternary_status"] == "unavailable"
    assert decision["gate_passed"] is True
    assert decision["secondary_blocking_failures"] == []
    assert decision["tertiary_blocking_failures"] == []
    assert decision["quaternary_blocking_failures"] == []


# --------------------------------------------------------------------------
# Test 10 — fallback C1/C2/C3 all must pass to open rc1
# --------------------------------------------------------------------------


def test_fallback_c1_c2_c3_all_must_pass_to_open_rc1() -> None:
    """Wired C1 fails; fallback C1 passes but fallback C2 fails → STOP."""
    n_zqp = 100
    probe_meta = _make_probe_meta(n_zqp, tool_eligibility="zim_query_preferred")

    # Wired path: C1 fails (10 answer-degrading routes / 100 = 10% > 5%)
    wired_outcomes: List[Outcome] = []
    for i in range(n_zqp):
        is_degrading = i < 10
        wired_outcomes.append(
            Outcome(
                probe_id=f"p-{i}",
                rep=0,
                tool_called="zim_search" if is_degrading else "zim_query",
                parameters={"mode": "title"} if is_degrading else {},
                dispatch_correct=not is_degrading,
                parameter_validity=(
                    "schema_only" if is_degrading else "load_bearing_match"
                ),
                spurious_route=is_degrading,
                spurious_route_kind="answer_degrading" if is_degrading else None,
                resolved_entry_path=None,
                cell_variant="phase-f",
                cell_mode="advanced",
                cell_model="qwen2.5-7b-instruct",
            )
        )
    b13_outcomes = _make_outcomes(
        n_correct=n_zqp,
        n_total=n_zqp,
        cell_variant="b13",
        cell_model="qwen2.5-7b-instruct",
    )
    decision = _build_gate_decision(b13_outcomes, wired_outcomes, probe_meta)
    assert decision["criteria"]["C1"]["pass"] is False
    assert decision["gate_passed"] is False

    # Now simulate the fallback re-run. We need the C1-passes/C2-fails shape:
    #   C1 needs answer-degrading rate over zim_query_preferred probes ≤5%.
    #   C2 needs ≥10 misroute events AND degrading/misroute ratio >30%.
    # 100 probes, exactly 10 misroutes, 4 answer-degrading
    # (the rest answer_preserving). C1 = 4/100 = 4% (passes ≤5%);
    # C2 events = 10 (meets MIN_EVENTS), rate = 4/10 = 40% (FAILS >30%).
    fallback_outcomes: List[Outcome] = []
    for i in range(n_zqp):
        is_misroute = i < 10
        is_degrading = i < 4
        fallback_outcomes.append(
            Outcome(
                probe_id=f"p-{i}",
                rep=0,
                tool_called="zim_search" if is_misroute else "zim_query",
                parameters={"mode": "title"} if is_misroute else {},
                dispatch_correct=not is_misroute,
                parameter_validity=(
                    "schema_only" if is_misroute else "load_bearing_match"
                ),
                spurious_route=is_misroute,
                spurious_route_kind=(
                    "answer_degrading"
                    if is_degrading
                    else ("answer_preserving" if is_misroute else None)
                ),
                resolved_entry_path=None,
                cell_variant="phase-f-fallback",
                cell_mode="advanced",
                cell_model="qwen2.5-7b-instruct",
            )
        )

    decision = _apply_fallback_c_check(decision, fallback_outcomes, probe_meta)
    assert decision["fallback_c1_pass"] is True
    assert decision["fallback_c2_pass"] is False
    # gate stays failed; criterion_c_path stays "wired" (fallback path not
    # adopted because C2 failed)
    assert decision["criterion_c_path"] == "wired"
    assert decision["gate_passed"] is False


# --------------------------------------------------------------------------
# Test 11 — scope_limitations required non-empty
# --------------------------------------------------------------------------


def test_scope_limitations_required_nonempty() -> None:
    """scope_limitations must include the four required prefixes."""
    probe_meta = _make_probe_meta(300)
    b13 = _make_outcomes(
        n_correct=270,
        n_total=300,
        cell_variant="b13",
        cell_model="qwen2.5-7b-instruct",
    )
    phase_f = _make_outcomes(
        n_correct=270,
        n_total=300,
        cell_variant="phase-f",
        cell_model="qwen2.5-7b-instruct",
    )
    decision = _build_gate_decision(b13, phase_f, probe_meta)
    limitations = decision.get("scope_limitations", [])
    assert isinstance(limitations, list)
    assert len(limitations) >= 4
    for prefix in (
        "probe-distribution:",
        "model-coverage:",
        "size-range:",
        "probe-language:",
    ):
        assert any(
            lim.startswith(prefix) for lim in limitations
        ), f"scope_limitations missing {prefix} entry; got {limitations}"


# --------------------------------------------------------------------------
# Test 12 — F1/F2 are primary-only verdicts (secondary failure observational)
# --------------------------------------------------------------------------


def test_secondary_f1_f2_failure_is_observational_not_blocking() -> None:
    """Pin the design choice: F1/F2 verdicts are PRIMARY-ONLY.

    If a future refactor starts computing F1/F2 per family (e.g. surfacing
    criteria["F1"]["secondary"]), this test will trip. The contract is:
      - criteria["F1"] / criteria["F2"] are flat dicts with pass/per_class_deltas/
        failures — NOT keyed by family slot.
      - A secondary cell with a 20pp Z3 regression (well above the 8pp F1
        ceiling) does NOT block the gate, because F1/F2 are computed against
        the primary pair only — secondary class deltas never enter the
        decision math.
      - The secondary's own A/B/D verdicts at 10pp margin are still checked;
        we therefore keep the secondary's overall accuracy passing here so the
        only "issue" is the per-class Z3 split (which the analyzer ignores).
    """
    probe_meta: Dict[str, Dict[str, Any]] = {}
    # 300 probes for primary (all clean — pass A/B/D + F1)
    for i in range(300):
        probe_meta[f"q-{i}"] = {
            "probe_id": f"q-{i}",
            "operational_classes": ["Z3"],
            "tool_eligibility": "any",
        }
    # 150 probes for secondary; first 75 are Z3, of which phase-f gets only
    # 60 correct (60/75 = 80%) vs b13 100% → -20pp Z3 delta on secondary.
    for i in range(150):
        probe_meta[f"h-{i}"] = {
            "probe_id": f"h-{i}",
            "operational_classes": ["Z3"] if i < 75 else ["other"],
            "tool_eligibility": "any",
        }

    # Primary — matched accuracy on Z3 (no F1 issue)
    qwen_b13 = _make_outcomes(
        n_correct=300,
        n_total=300,
        cell_variant="b13",
        cell_model="qwen2.5-7b-instruct",
        probe_id_prefix="q",
    )
    qwen_pf = _make_outcomes(
        n_correct=300,
        n_total=300,
        cell_variant="phase-f",
        cell_model="qwen2.5-7b-instruct",
        probe_id_prefix="q",
    )

    # Secondary (Haiku) — construct cells so overall A/B/D is matched (no
    # A/B/D failure at the 10pp margin) but the Z3 per-class split is badly
    # regressed on phase-f. Specifically:
    #   b13: 75/75 Z3 correct, 50/75 non-Z3 correct → 125/150 = 83.3%
    #   phase-f: 60/75 Z3 correct, 65/75 non-Z3 correct → 125/150 = 83.3%
    # Overall accuracy identical (delta_pp=0 → A passes), but the Z3 slice
    # alone moved -20pp (75/75 → 60/75) — a regression that would trip an
    # 8pp F1 ceiling IF F1 were computed per family.
    haiku_b13_list: List[Outcome] = []
    for i in range(150):
        # b13: all 75 Z3 correct (i<75); non-Z3 only 50 of 75 correct.
        is_correct = i < 75 or i < (75 + 50)
        haiku_b13_list.append(
            Outcome(
                probe_id=f"h-{i}",
                rep=0,
                tool_called="zim_query" if is_correct else "wrong_tool",
                parameters={"query": "x"},
                dispatch_correct=is_correct,
                parameter_validity=("load_bearing_match" if is_correct else "fail"),
                spurious_route=False,
                spurious_route_kind=None,
                resolved_entry_path=None,
                cell_variant="b13",
                cell_mode="advanced",
                cell_model="haiku-4.5",
            )
        )
    haiku_pf_list: List[Outcome] = []
    for i in range(150):
        # phase-f: 60/75 Z3 correct (miss 15 in Z3 slice);
        # non-Z3 65/75 correct (miss 10 outside Z3 slice).
        if i < 75:
            is_correct = i >= 15  # miss the first 15 Z3 probes
        else:
            is_correct = i >= (75 + 10)  # miss the first 10 non-Z3 probes
        haiku_pf_list.append(
            Outcome(
                probe_id=f"h-{i}",
                rep=0,
                tool_called="zim_query" if is_correct else "wrong_tool",
                parameters={"query": "x"},
                dispatch_correct=is_correct,
                parameter_validity=("load_bearing_match" if is_correct else "fail"),
                spurious_route=False,
                spurious_route_kind=None,
                resolved_entry_path=None,
                cell_variant="phase-f",
                cell_mode="advanced",
                cell_model="haiku-4.5",
            )
        )
    # Sanity (math check encoded for the reader):
    #   Haiku b13 correct  = 75 (Z3) + 50 (non-Z3) = 125 / 150
    #   Haiku phase-f correct = 60 (Z3) + 65 (non-Z3) = 125 / 150
    #   Overall delta = 0.0 → A/B/D pass cleanly.
    #   Z3 slice delta = (60/75 - 75/75)*100 = -20pp → well above F1 ceiling.

    decision = _build_gate_decision(
        qwen_b13 + haiku_b13_list, qwen_pf + haiku_pf_list, probe_meta
    )

    # PIN 1: criteria["F1"] is flat — no per-family verdict keyed by slot.
    f1 = decision["criteria"]["F1"]
    assert (
        "secondary" not in f1
    ), f"F1 must remain a primary-only verdict; got per-family key in: {f1}"
    assert "primary" not in f1, f"F1 is a flat verdict, not nested by family; got: {f1}"
    f2 = decision["criteria"]["F2"]
    assert (
        "secondary" not in f2
    ), f"F2 must remain a primary-only verdict; got per-family key in: {f2}"

    # PIN 2: F1/F2 on the primary pair both pass (Qwen primary is clean) and
    # the gate passes despite the secondary's bad Z3 split.
    assert f1["pass"] is True, f1
    assert f2["pass"] is True, f2
    assert decision["gate_passed"] is True, (
        f"secondary's per-class regression must not block; "
        f"failures={decision.get('secondary_blocking_failures')} "
        f"obs={decision.get('secondary_observational_failures')}"
    )

    # PIN 3: secondary observational/blocking lists must not surface F1/F2
    # for the secondary — those verdicts simply aren't computed per family.
    sec_blocking = decision["secondary_blocking_failures"]
    sec_obs = decision["secondary_observational_failures"]
    assert not any("F1" in f or "F2" in f for f in sec_blocking), sec_blocking
    assert not any("F1" in f or "F2" in f for f in sec_obs), sec_obs


# --------------------------------------------------------------------------
# Bonus tests — z-test edge cases
# --------------------------------------------------------------------------


def test_non_inferiority_test_handles_empty_cells() -> None:
    """Both cells empty → return delta=0, fall back to delta>=-margin check."""
    p, delta = non_inferiority_test(0, 0, 0, 0, 0.05)
    assert math.isclose(delta, 0.0)
    assert p is True  # 0 >= -0.05


def test_non_inferiority_test_handles_exact_match() -> None:
    """p1=p2 → delta=0, passes at primary 5pp margin when n is large enough.

    The pooled-variance Wald z-statistic at delta=0 is z = margin/SE. For
    p≈0.9 and n=300/cell that's ~2.04, clearing the alpha=0.05 one-sided
    threshold of 1.645. Lower accuracy (p≈0.67) at the same n yields
    z<1.645 — non-inferiority is then INDETERMINATE not falsified, hence
    this test uses the high-accuracy case where matched outcomes pass.
    """
    p, delta = non_inferiority_test(270, 300, 270, 300, 0.05)
    assert p is True
    assert math.isclose(delta, 0.0)


def test_disagreement_rule_primary_d_failure_blocks() -> None:
    """Primary criterion D failure → gate blocked."""
    criteria = {
        "A": {"primary": {"pass": True, "delta_pp": 0.0}},
        "B": {"primary": {"pass": True, "delta_pp": 0.0}},
        "D": {"primary": {"pass": False, "delta_pp": -10.0}},
        "F1": {"pass": True},
        "F2": {"pass": True},
        "C1": {"pass": True, "rate": 0.0},
        "C2": {"pass": None},
        "C3": {"pass": True, "rate": 0.0},
    }
    gate_passed, _ = apply_disagreement_rule(
        criteria,
        {
            "primary": "available",
            "secondary": "unavailable",
            "tertiary": "unavailable",
            "quaternary": "unavailable",
        },
    )
    assert gate_passed is False


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
    """zim_query dispatch on an either_acceptable probe is relaxed to correct."""
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
    """A dispatch to a third tool on an either_acceptable probe still misses."""
    outcomes = _miss_outcomes(10, tool_called="zim_metadata")
    probe_meta = _make_probe_meta(
        10, classes=["zim_get-main-page"], tool_eligibility="either_acceptable"
    )
    s = aggregate_cell(outcomes, probe_meta)
    # a dispatch to a third tool is NOT relaxed
    assert s.per_class["zim_get-main-page"] == (10, 0)
    assert s.dispatch_correct == 0


def test_non_either_acceptable_zim_query_unchanged():
    """Strict scoring stands when the probe is not either_acceptable."""
    outcomes = _miss_outcomes(10, tool_called="zim_query")
    probe_meta = _make_probe_meta(10, classes=["X"], tool_eligibility="any")
    s = aggregate_cell(outcomes, probe_meta)
    # strict scoring stands when the probe is not either_acceptable
    assert s.per_class["X"] == (10, 0)
    assert s.dispatch_correct == 0


def test_disagreement_rule_observational_secondary_does_not_block() -> None:
    """Secondary unavailable + primary pass → gate passes."""
    criteria = {
        "A": {"primary": {"pass": True, "delta_pp": 0.0}},
        "B": {"primary": {"pass": True, "delta_pp": 0.0}},
        "D": {"primary": {"pass": True, "delta_pp": 0.0}},
        "F1": {"pass": True},
        "F2": {"pass": True},
        "C1": {"pass": True, "rate": 0.0},
        "C2": {"pass": True, "rate": 0.0},
        "C3": {"pass": True, "rate": 0.0},
    }
    gate_passed, _ = apply_disagreement_rule(
        criteria,
        {
            "primary": "available",
            "secondary": "unavailable",
            "tertiary": "unavailable",
            "quaternary": "unavailable",
        },
    )
    assert gate_passed is True
