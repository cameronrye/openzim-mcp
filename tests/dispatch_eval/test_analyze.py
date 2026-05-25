"""Unit tests for tests/dispatch_eval/analyze.py — non-inferiority + decision rule.

Runs only with --dispatch-eval flag (matches the other dispatch_eval tests).
Synthetic outcomes; no real model calls.

The tests pin the analyzer's verdict logic on synthetic per-cell outcomes
so a future refactor doesn't silently change the gating math.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from tests.dispatch_eval.analyze import (
    C1_CEILING,
    C2_MIN_EVENTS,
    C3_CEILING,
    C3_MIN_EVENTS,
    F1_CEILING,
    F2_CEILING,
    PRIMARY_MARGIN,
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
    Outcome,
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
    assert verdicts["A"]["delta_pp"] == 0.0


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
                spurious_route=True if i < 6 else False,
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
                spurious_route=True if i < 4 else False,
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

    # Now simulate the fallback re-run: fallback-C1 passes (4 degrading / 100)
    # BUT fallback-C2 fails (degrading / misroutes = 4/4 = 100% > 30%)
    fallback_outcomes: List[Outcome] = []
    for i in range(n_zqp):
        # 4 misroutes, ALL answer-degrading — that fails C2's 30% ceiling
        is_misroute = i < 4
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
                spurious_route_kind="answer_degrading" if is_misroute else None,
                resolved_entry_path=None,
                cell_variant="phase-f-fallback",
                cell_mode="advanced",
                cell_model="qwen2.5-7b-instruct",
            )
        )
    # C2 needs >=10 events to be powered; we have 4 misroutes. So C2 stays
    # "null/underpowered". Bump misroutes up to 15 to make the test
    # explicit-failure rather than underpowered.
    fallback_outcomes = []
    for i in range(n_zqp):
        is_misroute = i < 15
        # 12 of the 15 misroutes are answer-degrading → 80% > 30% (C2 fails)
        is_degrading = i < 12
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
    # Now fallback-C1 = 12/100 = 12% (fails!), so we need to flip more to
    # answer_preserving to make fallback-C1 pass. Drop degrading count to 3.
    fallback_outcomes = []
    for i in range(n_zqp):
        is_misroute = i < 15  # 15 misroutes overall → C2 has enough events
        is_degrading = i < 3  # only 3 are degrading → C1 = 3% (PASSES)
        # 12 of the misroutes are answer_preserving → C2 = 3/15 = 20% (PASSES)
        # Wait — C2 ceiling is 30%; 3/15 = 20% passes. Need fallback C2 to FAIL.
        # Make 7/15 degrading → C1 = 7%, fails. Need C1 pass + C2 fail:
        # Set is_misroute on 15, with 5 degrading → C1 = 5% (boundary; we use
        # 4 to be safely under 5%), C2 = 4/15 = 26.7% (under 30% — passes).
        # The constraint "C1 passes AND C2 fails AND C3 ok" needs:
        #   C1 ≤ 5% absolute degrading rate over zqp probes
        #   C2 > 30% conditional degrading rate over misroutes
        # i.e. degrading is small but misroutes_total is even smaller — at
        # the minimum 10 events. degrading=4, misroutes=10 → C2 = 40% fails.
        # Adjusted: 100 probes, 10 misroutes, 4 degrading.
        pass  # placeholder; rewritten below

    # Final fallback: 100 probes, exactly 10 misroutes, 4 answer-degrading
    # (the rest answer_preserving). C1 = 4/100 = 4% (passes ≤5%);
    # C2 events = 10 (meets MIN_EVENTS), rate = 4/10 = 40% (FAILS >30%).
    fallback_outcomes = []
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
# Bonus tests — z-test edge cases
# --------------------------------------------------------------------------


def test_non_inferiority_test_handles_empty_cells() -> None:
    """Both cells empty → return delta=0, fall back to delta>=-margin check."""
    p, delta = non_inferiority_test(0, 0, 0, 0, 0.05)
    assert delta == 0.0
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
    assert delta == 0.0


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
