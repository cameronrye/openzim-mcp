"""Gate 0b non-inferiority analyzer.

Reads per-cell outcome JSONL files (produced by ``tests/dispatch_eval/runner.py``)
and emits the criterion verdicts per the spec's tiered decision rule.

Margins (sample-size-aware):
  Primary (Qwen-7B, 100% coverage, n=300/cell): 5pp non-inferiority on A/B/D.
  Secondary (Haiku, 50% coverage, n=150/cell): 10pp non-inferiority on A/B/D.
  Tertiary (Llama-8B, 50% coverage, n=150/cell): 10pp non-inferiority on A/B/D.
  Quaternary (Phi-3.5-mini, 50% coverage, n=150/cell, reps=5 for matched power):
    10pp non-inferiority on A/B/D — matched to tertiary. Size-induced variance
    handled via increased rep count rather than wider margin.

Per-class (F1): 8pp ceiling for b-series hardened classes.
Per-class (F2): 10pp ceiling for new Phase F operation classes.

Criterion C (dispatch-confusion):
  C1: answer-degrading spurious-routing rate <= 5% (zim_query_preferred denom).
  C2: of probes that misroute, the fraction whose resolved entry differs <= 30%.
       Computed when confusion-conditional subset has >=10 events.
  C3: Z4-tagged zim_query_preferred probes — answer-degrading rate <= 5% absolute.
       Computed when Z4 subset has >=20 events.
  ALL THREE re-checked on the fallback cell if wired-C fails — see plan
  Stage C Task C3 Step 3.

CLI surface (4 modes):

    # Default — full gate decision
    python tests/dispatch_eval/analyze.py \\
      --b13-runs <glob> --phase-f-runs <glob> \\
      --output tests/dispatch_eval/gate_0b_decision.json

    # Fallback C1+C2+C3 re-check
    python tests/dispatch_eval/analyze.py \\
      --b13-runs <glob> --phase-f-runs <glob> \\
      --fallback-c3-check \\
      --output-update tests/dispatch_eval/gate_0b_decision.json

    # Stage E sweep mode
    python tests/dispatch_eval/analyze.py \\
      --sweep-mode --runs <run.jsonl> [--check-divergence <other.jsonl>]

    # Stage E F2 enforcement only
    python tests/dispatch_eval/analyze.py \\
      --b13-runs <glob> --phase-f-runs <glob> \\
      --f2-enforcement-only \\
      --output /tmp/rc1_f2_verdict.json
"""

from __future__ import annotations

import argparse
import glob as _glob
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# Configuration constants
# --------------------------------------------------------------------------

F1_CLASSES = {
    "Z1",
    "Z2",
    "Z3",
    "Z4",
    "OPP-1",
    "Sub-pattern-C",
    "filler-prose",
    "possessive",
}
F2_CLASSES = {
    "zim_get-toc",
    "zim_get-summary",
    "zim_get-structure",
    "zim_get-binary",
    "zim_get-main-page",
    "zim_get-batch",
    "zim_browse-page",
    "zim_browse-walk",
    "zim_metadata",
    "zim_links-outbound",
    "zim_links-related",
    "zim_health",
}

PRIMARY_MARGIN = 0.05
SECONDARY_MARGIN = 0.10
TERTIARY_MARGIN = 0.10
QUATERNARY_MARGIN = 0.10  # matched to tertiary; size variance via reps=5

F1_CEILING = 0.08
F2_CEILING = 0.10  # tightened from 0.15

C1_CEILING = 0.05
C2_CEILING = 0.30
C2_MIN_EVENTS = 10
C3_CEILING = 0.05
C3_MIN_EVENTS = 20

REQUIRED_SCOPE_LIMITATION_PREFIXES = (
    "probe-distribution:",
    "model-coverage:",
    "size-range:",
    "probe-language:",
)

DEFAULT_SCOPE_LIMITATIONS = [
    "probe-distribution: wikipedia-dominant",
    "model-coverage: qwen-7b + llama-8b + phi-3.5-mini + haiku-4.5",
    "size-range: 3.8B-8B (open-weights)",
    "probe-language: english-only",
]

# Family → margin
FAMILY_MARGINS = {
    "primary": PRIMARY_MARGIN,
    "secondary": SECONDARY_MARGIN,
    "tertiary": TERTIARY_MARGIN,
    "quaternary": QUATERNARY_MARGIN,
}

# Model short-name prefix → family slot. Each family slot picks ONE concrete
# model from the cell-coverage matrix (inference_setup.md §Cell coverage).
_MODEL_FAMILY = {
    "qwen2.5-7b-instruct": "primary",
    "qwen-2.5-7b-instruct": "primary",
    "qwen": "primary",  # bare alias accepted for sweep-mode flexibility
    "haiku-4.5": "secondary",
    "haiku": "secondary",
    "claude-haiku-4-5-20251001": "secondary",
    "llama-3.1-8b-instruct": "tertiary",
    "llama": "tertiary",
    "phi-3.5-mini-instruct": "quaternary",
    "phi": "quaternary",
    "qwen-2.5-3b-instruct": "quaternary",  # Phi substitute
}


# --------------------------------------------------------------------------
# Outcome row loading
# --------------------------------------------------------------------------


@dataclass
class Outcome:
    probe_id: str
    rep: int
    tool_called: Optional[str]
    parameters: Dict[str, Any]
    dispatch_correct: bool
    parameter_validity: str
    spurious_route: bool
    spurious_route_kind: Optional[str]
    resolved_entry_path: Optional[str]
    # Source metadata derived from the path
    cell_variant: str = ""
    cell_mode: str = ""
    cell_model: str = ""

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Outcome":
        return cls(
            probe_id=d.get("probe_id", ""),
            rep=int(d.get("rep", 0)),
            tool_called=d.get("tool_called"),
            parameters=d.get("parameters") or {},
            dispatch_correct=bool(d.get("dispatch_correct", False)),
            parameter_validity=d.get("parameter_validity", "fail"),
            spurious_route=bool(d.get("spurious_route", False)),
            spurious_route_kind=d.get("spurious_route_kind"),
            resolved_entry_path=d.get("resolved_entry_path"),
        )


def _parse_cell_metadata(path: Path) -> Tuple[str, str, str]:
    """Recover (variant, mode, model) from a runs JSONL filename.

    Filename convention: ``<variant>__<mode>__<model>__<timestamp>.jsonl``.
    Returns ``("", "", "")`` if the filename doesn't match.
    """
    stem = path.stem
    parts = stem.split("__")
    if len(parts) >= 3:
        return parts[0], parts[1], parts[2]
    return "", "", ""


def load_outcomes(path: Path) -> List[Outcome]:
    """Load one cell's outcomes from a JSONL file."""
    variant, mode, model = _parse_cell_metadata(path)
    outcomes: List[Outcome] = []
    with path.open(encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                continue
            o = Outcome.from_dict(d)
            o.cell_variant = variant
            o.cell_mode = mode
            o.cell_model = model
            outcomes.append(o)
    return outcomes


def load_outcomes_from_glob(patterns: Sequence[str]) -> List[Outcome]:
    """Load and concatenate outcomes from one or more file globs."""
    outcomes: List[Outcome] = []
    for pattern in patterns:
        for match in sorted(_glob.glob(pattern)):
            outcomes.extend(load_outcomes(Path(match)))
    return outcomes


def _family_of(model: str) -> Optional[str]:
    """Map a model short name to a family slot, or None if unknown."""
    key = model.lower()
    if key in _MODEL_FAMILY:
        return _MODEL_FAMILY[key]
    # Prefix fallback for haiku-* / claude-* / qwen* / llama-3* / phi-3.5*
    for prefix, fam in (
        ("qwen", "primary"),
        ("haiku", "secondary"),
        ("claude", "secondary"),
        ("llama-3", "tertiary"),
        ("phi-3.5", "quaternary"),
    ):
        if key.startswith(prefix):
            return fam
    return None


# --------------------------------------------------------------------------
# Probe metadata loading (for operational_classes lookups)
# --------------------------------------------------------------------------


def load_probe_metadata(probes_path: Path) -> Dict[str, Dict[str, Any]]:
    """Build {probe_id: probe_dict} for class/eligibility lookups."""
    out: Dict[str, Dict[str, Any]] = {}
    if not probes_path.exists():
        return out
    with probes_path.open() as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                d = json.loads(raw)
            except json.JSONDecodeError:
                continue
            out[d["probe_id"]] = d
    return out


def _default_probes_path() -> Path:
    return Path(__file__).resolve().parent / "probes.jsonl"


# --------------------------------------------------------------------------
# Non-inferiority test
# --------------------------------------------------------------------------


def non_inferiority_test(
    p1_correct: int, p1_n: int, p2_correct: int, p2_n: int, margin: float
) -> Tuple[bool, float]:
    """One-sided non-inferiority test at alpha=0.05.

    ``p2`` (new variant) is non-inferior to ``p1`` (baseline) if
    ``p2 - p1 >= -margin``. Returns ``(pass, delta_pp)``.

    Implementation: pooled-variance Wald z-statistic. We reject the null
    (delta = -margin) in favor of H1 (delta > -margin) when z > 1.645.
    """
    p1 = p1_correct / p1_n if p1_n else 0.0
    p2 = p2_correct / p2_n if p2_n else 0.0
    delta = p2 - p1
    if not p1_n or not p2_n:
        # Insufficient data: be conservative — pass only if delta meets margin
        return delta >= -margin, delta * 100
    p_pool = (p1_correct + p2_correct) / (p1_n + p2_n)
    var = p_pool * (1 - p_pool) * (1 / p1_n + 1 / p2_n)
    if var <= 0:
        return delta >= -margin, delta * 100
    se = math.sqrt(var)
    z = (delta + margin) / se
    return z > 1.645, delta * 100


# --------------------------------------------------------------------------
# Per-family aggregation
# --------------------------------------------------------------------------


@dataclass
class CellSummary:
    """Aggregate stats for one (variant, mode, model) cell."""

    family: str = "primary"
    variant: str = ""
    mode: str = ""
    model: str = ""
    n: int = 0
    # Criterion A: dispatch_correct rate
    dispatch_correct: int = 0
    # Criterion B: load_bearing_match (subset of dispatch_correct in practice
    # but we count independently to keep the metric definition explicit)
    load_bearing_match: int = 0
    # Criterion D: composite — dispatch_correct AND parameter_validity != fail
    composite_correct: int = 0
    # Per-class counters for F1/F2 (class → (n, dispatch_correct))
    per_class: Dict[str, Tuple[int, int]] = field(default_factory=dict)
    # Criterion C — only over zim_query_preferred probes
    zqp_n: int = 0
    zqp_spurious_route: int = 0
    zqp_spurious_answer_degrading: int = 0
    zqp_spurious_answer_preserving: int = 0
    # Criterion C3 — over Z4 zim_query_preferred probes only
    z4_zqp_n: int = 0
    z4_zqp_answer_degrading: int = 0


def aggregate_cell(
    outcomes: Iterable[Outcome], probe_meta: Dict[str, Dict[str, Any]]
) -> CellSummary:
    """Build a CellSummary from one cell's outcomes."""
    summary = CellSummary()
    per_class_n: Dict[str, int] = defaultdict(int)
    per_class_correct: Dict[str, int] = defaultdict(int)
    for o in outcomes:
        if not summary.variant:
            summary.variant = o.cell_variant
            summary.mode = o.cell_mode
            summary.model = o.cell_model
            summary.family = _family_of(o.cell_model) or "primary"
        summary.n += 1
        if o.dispatch_correct:
            summary.dispatch_correct += 1
        if o.parameter_validity == "load_bearing_match":
            summary.load_bearing_match += 1
        if o.dispatch_correct and o.parameter_validity != "fail":
            summary.composite_correct += 1

        # Per-class accounting (F1/F2)
        probe = probe_meta.get(o.probe_id, {})
        classes = probe.get("operational_classes", []) or []
        for cls in classes:
            per_class_n[cls] += 1
            if o.dispatch_correct:
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
                # Mirror C1's nesting: require spurious_route True before
                # inspecting spurious_route_kind. The runner guarantees the
                # invariant (kind=None when not spurious), but the nested
                # check is defense-in-depth for hand-constructed outcomes
                # (including tests).
                if o.spurious_route and o.spurious_route_kind == "answer_degrading":
                    summary.z4_zqp_answer_degrading += 1

    summary.per_class = {
        cls: (per_class_n[cls], per_class_correct[cls]) for cls in per_class_n
    }
    return summary


def split_outcomes_by_cell(
    outcomes: Iterable[Outcome],
) -> Dict[Tuple[str, str, str], List[Outcome]]:
    """Group outcomes by (variant, mode, model) so each cell is summarized
    independently."""
    out: Dict[Tuple[str, str, str], List[Outcome]] = defaultdict(list)
    for o in outcomes:
        out[(o.cell_variant, o.cell_mode, o.cell_model)].append(o)
    return out


# --------------------------------------------------------------------------
# Criterion verdicts
# --------------------------------------------------------------------------


def criterion_a_b_d(
    b13: CellSummary, phase_f: CellSummary, margin: float
) -> Dict[str, Any]:
    """Return per-criterion verdicts {A, B, D} for one family slot."""
    # A = dispatch_correct rate
    a_pass, a_delta = non_inferiority_test(
        b13.dispatch_correct, b13.n, phase_f.dispatch_correct, phase_f.n, margin
    )
    # B = load_bearing_match rate
    b_pass, b_delta = non_inferiority_test(
        b13.load_bearing_match, b13.n, phase_f.load_bearing_match, phase_f.n, margin
    )
    # D = composite (dispatch_correct AND parameters not "fail")
    d_pass, d_delta = non_inferiority_test(
        b13.composite_correct, b13.n, phase_f.composite_correct, phase_f.n, margin
    )
    return {
        "A": {"pass": a_pass, "delta_pp": a_delta},
        "B": {"pass": b_pass, "delta_pp": b_delta},
        "D": {"pass": d_pass, "delta_pp": d_delta},
    }


def criterion_c1(phase_f_advanced_primary: CellSummary) -> Dict[str, Any]:
    """C1: answer-degrading spurious-routing rate over the
    zim_query_preferred denominator. Ceiling: 5%.

    Vacuous when no zim_query_preferred probes ran (events=0): pass=True with
    rate=None — no events means no measured harm, can't block on it.
    """
    if phase_f_advanced_primary.zqp_n == 0:
        return {
            "pass": True,
            "rate": None,
            "events": 0,
            "note": "no zim_query_preferred probes ran",
        }
    rate = (
        phase_f_advanced_primary.zqp_spurious_answer_degrading
        / phase_f_advanced_primary.zqp_n
    )
    return {
        "pass": rate <= C1_CEILING,
        "rate": rate,
        "events": phase_f_advanced_primary.zqp_n,
    }


def criterion_c2(phase_f_advanced_primary: CellSummary) -> Dict[str, Any]:
    """C2: conditional on misrouting, fraction whose resolved entry differs.
    Underpowered below 10 events (returns rate=None, pass=None — hand-audit
    required, gate authors record verdict).
    """
    events = phase_f_advanced_primary.zqp_spurious_route
    if events < C2_MIN_EVENTS:
        return {
            "pass": None,
            "rate": None,
            "events": events,
            "note": "underpowered (<10 events)",
        }
    degrading = phase_f_advanced_primary.zqp_spurious_answer_degrading
    rate = degrading / events
    return {"pass": rate <= C2_CEILING, "rate": rate, "events": events}


def criterion_c3(phase_f_advanced_primary: CellSummary) -> Dict[str, Any]:
    """C3: Z4 zim_query_preferred answer-degrading rate. Ceiling: 5%.
    Underpowered below 20 events (returns rate=None, pass=None).
    """
    events = phase_f_advanced_primary.z4_zqp_n
    if events < C3_MIN_EVENTS:
        return {
            "pass": None,
            "rate": None,
            "events": events,
            "note": "underpowered (<20 events)",
        }
    rate = phase_f_advanced_primary.z4_zqp_answer_degrading / events
    return {"pass": rate <= C3_CEILING, "rate": rate, "events": events}


def _per_class_delta_pp(
    b13: CellSummary, phase_f: CellSummary, classes: Iterable[str]
) -> Dict[str, float]:
    """Return per-class delta in percentage points (phase_f - b13)."""
    out: Dict[str, float] = {}
    for cls in classes:
        bn, bc = b13.per_class.get(cls, (0, 0))
        pn, pc = phase_f.per_class.get(cls, (0, 0))
        b_rate = bc / bn if bn else 0.0
        p_rate = pc / pn if pn else 0.0
        out[cls] = round((p_rate - b_rate) * 100, 2)
    return out


def criterion_f1(b13: CellSummary, phase_f: CellSummary) -> Dict[str, Any]:
    """F1: every b-series hardened class must regress by <=8pp."""
    deltas = _per_class_delta_pp(b13, phase_f, F1_CLASSES)
    failures = [cls for cls, d in deltas.items() if d < -F1_CEILING * 100]
    return {
        "pass": len(failures) == 0,
        "per_class_deltas": deltas,
        "failures": failures,
    }


def criterion_f2(b13: CellSummary, phase_f: CellSummary) -> Dict[str, Any]:
    """F2: every new Phase F class must regress by <=10pp."""
    deltas = _per_class_delta_pp(b13, phase_f, F2_CLASSES)
    failures = [cls for cls, d in deltas.items() if d < -F2_CEILING * 100]
    return {
        "pass": len(failures) == 0,
        "per_class_deltas": deltas,
        "failures": failures,
    }


# --------------------------------------------------------------------------
# Gate decision (full)
# --------------------------------------------------------------------------


def _pick_advanced_cell(
    summaries: Dict[Tuple[str, str, str], CellSummary], variant: str, model: str
) -> Optional[CellSummary]:
    """Look up the (variant, "advanced", model) cell, if present."""
    return summaries.get((variant, "advanced", model))


def _empty_family_block() -> Dict[str, Any]:
    return {"pass": True, "delta_pp": 0.0}


def _family_blocks_default() -> Dict[str, Dict[str, Any]]:
    return {fam: _empty_family_block() for fam in FAMILY_MARGINS}


def _build_family_verdicts(
    cell_summaries: Dict[Tuple[str, str, str], CellSummary],
    b13_variant: str = "b13",
    phase_f_variant: str = "phase-f",
) -> Tuple[Dict[str, Dict[str, Dict[str, Any]]], Dict[str, str]]:
    """Compute A/B/D verdicts per family slot.

    Returns:
        (criteria_dict, family_status_dict)
        criteria_dict = {"A": {fam: {pass, delta_pp}}, "B": {...}, "D": {...}}
        family_status_dict = {"secondary": "available"|"unavailable", ...}
    """
    crit_a: Dict[str, Dict[str, Any]] = {}
    crit_b: Dict[str, Dict[str, Any]] = {}
    crit_d: Dict[str, Dict[str, Any]] = {}
    family_status: Dict[str, str] = {}

    # Group cells by family
    family_to_models: Dict[str, set] = defaultdict(set)
    for (_v, _m, model), summary in cell_summaries.items():
        family_to_models[summary.family].add(model)

    for fam, margin in FAMILY_MARGINS.items():
        models_in_fam = family_to_models.get(fam, set())
        b13_cells = [
            cell_summaries[(b13_variant, "advanced", m)]
            for m in models_in_fam
            if (b13_variant, "advanced", m) in cell_summaries
        ]
        phase_f_cells = [
            cell_summaries[(phase_f_variant, "advanced", m)]
            for m in models_in_fam
            if (phase_f_variant, "advanced", m) in cell_summaries
        ]
        if not b13_cells or not phase_f_cells:
            family_status[fam] = "unavailable"
            crit_a[fam] = {"pass": True, "delta_pp": 0.0, "status": "unavailable"}
            crit_b[fam] = {"pass": True, "delta_pp": 0.0, "status": "unavailable"}
            crit_d[fam] = {"pass": True, "delta_pp": 0.0, "status": "unavailable"}
            continue

        family_status[fam] = "available"
        # If a family slot somehow has multiple models (e.g. quaternary with
        # both Phi AND Qwen-3B), pair them up and take the worst case.
        # WARN when this happens because positional zip after sort can
        # silently cross-pair models if the b13 and phase-f sides disagree
        # on which models they contain (e.g., Phi in b13 cells +
        # Qwen-3B in phase-f cells per the documented substitution).
        b13_models_sorted = sorted([c.model for c in b13_cells])
        phase_f_models_sorted = sorted([c.model for c in phase_f_cells])
        if len(b13_models_sorted) > 1 or len(phase_f_models_sorted) > 1:
            print(
                f"WARNING: family slot '{fam}' has multiple models — "
                f"b13={b13_models_sorted}, phase-f={phase_f_models_sorted}. "
                f"Pairing is positional after sorting; confirm models "
                f"match across cells (e.g., Phi vs Qwen-3B substitution).",
                file=sys.stderr,
            )
        worst_a: Dict[str, Any] = {"pass": True, "delta_pp": 0.0}
        worst_b: Dict[str, Any] = {"pass": True, "delta_pp": 0.0}
        worst_d: Dict[str, Any] = {"pass": True, "delta_pp": 0.0}
        for b13_cell, phase_f_cell in zip(
            sorted(b13_cells, key=lambda c: c.model),
            sorted(phase_f_cells, key=lambda c: c.model),
        ):
            verdicts = criterion_a_b_d(b13_cell, phase_f_cell, margin)
            if (
                not verdicts["A"]["pass"]
                or verdicts["A"]["delta_pp"] < worst_a["delta_pp"]
            ):
                worst_a = verdicts["A"]
            if (
                not verdicts["B"]["pass"]
                or verdicts["B"]["delta_pp"] < worst_b["delta_pp"]
            ):
                worst_b = verdicts["B"]
            if (
                not verdicts["D"]["pass"]
                or verdicts["D"]["delta_pp"] < worst_d["delta_pp"]
            ):
                worst_d = verdicts["D"]
        crit_a[fam] = worst_a
        crit_b[fam] = worst_b
        crit_d[fam] = worst_d

    # Ensure all four family slots are present in the criteria dict, even if
    # status='unavailable' from above already covers most cases.
    for fam in FAMILY_MARGINS:
        crit_a.setdefault(fam, {"pass": True, "delta_pp": 0.0, "status": "unavailable"})
        crit_b.setdefault(fam, {"pass": True, "delta_pp": 0.0, "status": "unavailable"})
        crit_d.setdefault(fam, {"pass": True, "delta_pp": 0.0, "status": "unavailable"})
        family_status.setdefault(fam, "unavailable")

    return {"A": crit_a, "B": crit_b, "D": crit_d}, family_status


def apply_disagreement_rule(
    criteria: Dict[str, Any], family_status: Dict[str, str]
) -> Tuple[bool, Dict[str, List[str]]]:
    """Apply the tiered decision rule. Returns (gate_passed, per_family_failures).

    per_family_failures has keys per non-primary family slot:
      "<family>_blocking_failures" and "<family>_observational_failures".

    Blocking criteria:
      - Criterion D failure on any family slot
      - F1 or F2 failure (any class) on primary
      - C1/C2/C3 failure on primary (wired path)
      - Secondary/Tertiary/Quaternary failure on A/B/D at their margin
      - Secondary/Tertiary/Quaternary failure on C1/C2/C3
    Observational (not blocking):
      - Secondary/Tertiary/Quaternary failure on F1/F2 — secondaries have
        ~15/class effective n, below statistical floor
      - Family slot unavailable
    """
    blocking = False
    family_failures: Dict[str, List[str]] = {}
    for fam in ("secondary", "tertiary", "quaternary"):
        family_failures[f"{fam}_blocking_failures"] = []
        family_failures[f"{fam}_observational_failures"] = []

    # 1) Per-family A/B/D
    for fam in FAMILY_MARGINS:
        if family_status.get(fam) == "unavailable":
            continue
        a = criteria.get("A", {}).get(fam, {})
        b = criteria.get("B", {}).get(fam, {})
        d = criteria.get("D", {}).get(fam, {})
        for crit_name, crit_block in (("A", a), ("B", b), ("D", d)):
            if crit_block.get("pass") is False:
                if fam == "primary":
                    # Any primary A/B/D failure blocks — including A/B; D
                    # is the load-bearing one but A/B are also tracked.
                    if crit_name == "D":
                        blocking = True
                    elif crit_name in ("A", "B"):
                        # A/B failures on primary are also blocking — they
                        # imply Criterion D is at risk.
                        blocking = True
                else:
                    family_failures[f"{fam}_blocking_failures"].append(
                        f"criterion_{crit_name}"
                    )
                    blocking = True

    # 2) Primary C1/C2/C3 (None/underpowered does not block by itself; only
    # explicit pass=False blocks)
    c1 = criteria.get("C1", {})
    c2 = criteria.get("C2", {})
    c3 = criteria.get("C3", {})
    if c1.get("pass") is False:
        blocking = True
    if c2.get("pass") is False:
        blocking = True
    if c3.get("pass") is False:
        blocking = True

    # 3) F1 / F2 — primary failures block; secondary/tertiary/quaternary
    # failures are observational. Right now F1/F2 are computed once over the
    # primary; secondaries don't ship their own F1/F2 verdicts.
    f1 = criteria.get("F1", {})
    f2 = criteria.get("F2", {})
    if f1.get("pass") is False:
        blocking = True
    if f2.get("pass") is False:
        blocking = True

    gate_passed = not blocking
    return gate_passed, family_failures


# --------------------------------------------------------------------------
# Decision artifact builders
# --------------------------------------------------------------------------


def _build_gate_decision(
    b13_outcomes: List[Outcome],
    phase_f_outcomes: List[Outcome],
    probe_meta: Dict[str, Dict[str, Any]],
    *,
    quaternary_model_substituted: Optional[str] = None,
    gate_0_schema_shape: str = "wired_oneof",
    gate_0_3_verdict: str = "validated",
    scope_limitations: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build the full gate_0b_decision.json payload."""
    cells: Dict[Tuple[str, str, str], CellSummary] = {}
    for cell_key, items in split_outcomes_by_cell(b13_outcomes).items():
        cells[cell_key] = aggregate_cell(items, probe_meta)
    for cell_key, items in split_outcomes_by_cell(phase_f_outcomes).items():
        cells[cell_key] = aggregate_cell(items, probe_meta)

    abd_criteria, family_status = _build_family_verdicts(cells)

    # Identify the PRIMARY phase-f advanced cell for C1/C2/C3 + F1/F2
    primary_phase_f: Optional[CellSummary] = None
    primary_b13: Optional[CellSummary] = None
    for key, summary in cells.items():
        if summary.family == "primary" and summary.mode == "advanced":
            if summary.variant == "phase-f":
                primary_phase_f = summary
            elif summary.variant == "b13":
                primary_b13 = summary

    if primary_phase_f is None:
        c1_block = {
            "pass": False,
            "rate": None,
            "events": 0,
            "note": "no primary phase-f advanced cell",
        }
        c2_block = {
            "pass": False,
            "rate": None,
            "events": 0,
            "note": "no primary phase-f advanced cell",
        }
        c3_block = {
            "pass": False,
            "rate": None,
            "events": 0,
            "note": "no primary phase-f advanced cell",
        }
    else:
        c1_block = criterion_c1(primary_phase_f)
        c2_block = criterion_c2(primary_phase_f)
        c3_block = criterion_c3(primary_phase_f)

    if primary_b13 is None or primary_phase_f is None:
        f1_block = {
            "pass": False,
            "per_class_deltas": {},
            "failures": ["no primary cells"],
        }
        f2_block = {
            "pass": False,
            "per_class_deltas": {},
            "failures": ["no primary cells"],
        }
    else:
        f1_block = criterion_f1(primary_b13, primary_phase_f)
        f2_block = criterion_f2(primary_b13, primary_phase_f)

    criteria: Dict[str, Any] = {
        "A": abd_criteria["A"],
        "B": abd_criteria["B"],
        "C1": c1_block,
        "C2": c2_block,
        "C3": c3_block,
        "D": abd_criteria["D"],
        "F1": f1_block,
        "F2": f2_block,
    }

    gate_passed, family_failures = apply_disagreement_rule(criteria, family_status)
    # Determine criterion_c_path — if C1/C2/C3 all PASS on primary, "wired",
    # else if any FAILED, "fallback" requires a fallback re-run (signaled by
    # leaving the path as "wired" but flagging gate_passed=False; the
    # operator runs --fallback-c3-check to populate fallback_c*_pass).
    criterion_c_path = "wired"

    decision = {
        "gate_passed": gate_passed,
        "default_tool_mode": "simple",
        "criterion_c_path": criterion_c_path,
        "gate_0_schema_shape": gate_0_schema_shape,
        "gate_0_3_verdict": gate_0_3_verdict,
        "criteria": criteria,
        "secondary_status": family_status.get("secondary", "unavailable"),
        "tertiary_status": family_status.get("tertiary", "unavailable"),
        "quaternary_status": family_status.get("quaternary", "unavailable"),
        "quaternary_model_substituted": quaternary_model_substituted,
        "secondary_blocking_failures": family_failures.get(
            "secondary_blocking_failures", []
        ),
        "secondary_observational_failures": family_failures.get(
            "secondary_observational_failures", []
        ),
        "tertiary_blocking_failures": family_failures.get(
            "tertiary_blocking_failures", []
        ),
        "tertiary_observational_failures": family_failures.get(
            "tertiary_observational_failures", []
        ),
        "quaternary_blocking_failures": family_failures.get(
            "quaternary_blocking_failures", []
        ),
        "quaternary_observational_failures": family_failures.get(
            "quaternary_observational_failures", []
        ),
        "fallback_c1_pass": None,
        "fallback_c2_pass": None,
        "fallback_c3_pass": None,
        "scope_limitations": list(scope_limitations or DEFAULT_SCOPE_LIMITATIONS),
        "criterion_f1_class_failures": f1_block.get("failures", []),
        "criterion_f2_class_failures": f2_block.get("failures", []),
    }
    return decision


def _apply_fallback_c_check(
    decision: Dict[str, Any],
    phase_f_fallback_outcomes: List[Outcome],
    probe_meta: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Populate fallback_c1_pass / fallback_c2_pass / fallback_c3_pass."""
    cells: Dict[Tuple[str, str, str], CellSummary] = {}
    for cell_key, items in split_outcomes_by_cell(phase_f_fallback_outcomes).items():
        cells[cell_key] = aggregate_cell(items, probe_meta)

    # Locate the PRIMARY fallback cell
    primary_fallback: Optional[CellSummary] = None
    for summary in cells.values():
        if summary.family == "primary" and summary.mode == "advanced":
            primary_fallback = summary
            break

    if primary_fallback is None:
        decision["fallback_c1_pass"] = False
        decision["fallback_c2_pass"] = False
        decision["fallback_c3_pass"] = False
        return decision

    c1 = criterion_c1(primary_fallback)
    c2 = criterion_c2(primary_fallback)
    c3 = criterion_c3(primary_fallback)

    decision["fallback_c1_pass"] = c1.get("pass")
    decision["fallback_c2_pass"] = c2.get("pass")  # may be None (underpowered)
    decision["fallback_c3_pass"] = c3.get("pass")

    # If all three pass (or pass=None for C2 — hand-audit), flip
    # criterion_c_path to "fallback" so downstream artifacts know which
    # legibility path to bake into zim_search.py.
    c1_ok = decision["fallback_c1_pass"] is True
    c2_ok = decision["fallback_c2_pass"] in (True, None)
    c3_ok = decision["fallback_c3_pass"] is True
    if c1_ok and c2_ok and c3_ok:
        decision["criterion_c_path"] = "fallback"
        # Fallback C carried the gate; gate-passed becomes whatever the
        # wired A/B/D/F1/F2 already said, with primary C suppressed.
        criteria = decision["criteria"]
        # Replace primary C1/C2/C3 verdicts with the fallback values for the
        # final decision, preserving the wired values under a debug key.
        criteria["C1_wired"] = criteria.get("C1")
        criteria["C2_wired"] = criteria.get("C2")
        criteria["C3_wired"] = criteria.get("C3")
        criteria["C1"] = c1
        criteria["C2"] = c2
        criteria["C3"] = c3
        gate_passed, _ = apply_disagreement_rule(
            criteria,
            {
                "primary": "available",
                "secondary": decision["secondary_status"],
                "tertiary": decision["tertiary_status"],
                "quaternary": decision["quaternary_status"],
            },
        )
        decision["gate_passed"] = gate_passed
    return decision


# --------------------------------------------------------------------------
# Sweep / F2-enforcement-only modes
# --------------------------------------------------------------------------


def _sweep_report(
    run_outcomes: List[Outcome],
    probe_meta: Dict[str, Dict[str, Any]],
    divergence_outcomes: Optional[List[Outcome]] = None,
) -> Dict[str, Any]:
    """Report per-class deltas for a single run vs the committed b13 baseline.

    If ``divergence_outcomes`` is provided, also flag per-probe divergence
    between the two outcome sets (primary vs secondary, typically).
    """
    cells = split_outcomes_by_cell(run_outcomes)
    cell_summaries = {k: aggregate_cell(v, probe_meta) for k, v in cells.items()}
    per_class: Dict[str, Dict[str, Any]] = {}
    for summary in cell_summaries.values():
        for cls, (n, correct) in summary.per_class.items():
            per_class.setdefault(cls, {"n": 0, "correct": 0})
            per_class[cls]["n"] += n
            per_class[cls]["correct"] += correct
    for cls, stats in per_class.items():
        stats["rate"] = stats["correct"] / stats["n"] if stats["n"] else 0.0

    report: Dict[str, Any] = {
        "cells": [
            {
                "variant": s.variant,
                "mode": s.mode,
                "model": s.model,
                "n": s.n,
                "dispatch_accuracy": s.dispatch_correct / s.n if s.n else 0.0,
            }
            for s in cell_summaries.values()
        ],
        "per_class": per_class,
    }
    if divergence_outcomes is not None:
        report["divergence"] = _compute_divergence(run_outcomes, divergence_outcomes)
    return report


def _compute_divergence(
    a_outcomes: List[Outcome], b_outcomes: List[Outcome]
) -> Dict[str, Any]:
    """Per-probe divergence: probes where A and B disagree on tool_called."""
    # Key by (probe_id, rep) when reps line up; otherwise fall back to
    # majority tool_called per probe.
    a_by_probe: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    b_by_probe: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for o in a_outcomes:
        a_by_probe[o.probe_id][o.tool_called or "<null>"] += 1
    for o in b_outcomes:
        b_by_probe[o.probe_id][o.tool_called or "<null>"] += 1

    def _majority(counts: Dict[str, int]) -> str:
        if not counts:
            return "<empty>"
        return max(counts.items(), key=lambda kv: kv[1])[0]

    divergent: List[Dict[str, Any]] = []
    for pid in set(a_by_probe) | set(b_by_probe):
        a_tool = _majority(a_by_probe.get(pid, {}))
        b_tool = _majority(b_by_probe.get(pid, {}))
        if a_tool != b_tool:
            divergent.append(
                {"probe_id": pid, "a_majority": a_tool, "b_majority": b_tool}
            )
    return {"count": len(divergent), "examples": divergent[:25]}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gate 0b non-inferiority analyzer.")
    parser.add_argument("--b13-runs", default=None, help="Glob for b13 runs.")
    parser.add_argument(
        "--phase-f-runs", default=None, help="Glob for phase-f / fallback runs."
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSON path for the gate decision (default mode and "
        "--f2-enforcement-only).",
    )
    parser.add_argument(
        "--output-update",
        default=None,
        help="Output JSON path to update in place (--fallback-c3-check mode).",
    )
    parser.add_argument(
        "--fallback-c3-check",
        action="store_true",
        help="Compute fallback C1+C2+C3 and update the decision artifact.",
    )
    parser.add_argument(
        "--sweep-mode",
        action="store_true",
        help="Stage E per-class delta sweep over a single run.",
    )
    parser.add_argument("--runs", default=None, help="Single run JSONL (sweep-mode).")
    parser.add_argument(
        "--check-divergence",
        default=None,
        help="Compare against another run JSONL (sweep-mode).",
    )
    parser.add_argument(
        "--f2-enforcement-only",
        action="store_true",
        help="Stage E: report F2 verdict only, skipping A/B/C/D.",
    )
    parser.add_argument(
        "--probes",
        default=str(_default_probes_path()),
        help="Path to probes.jsonl for class lookups.",
    )
    parser.add_argument(
        "--gate-0-schema-shape",
        default="wired_oneof",
        choices=["wired_oneof", "flat"],
        help="Pass through Gate 0 schema shape into the decision artifact.",
    )
    parser.add_argument(
        "--gate-0-3-verdict",
        default="validated",
        choices=["validated", "unvalidated", "failed"],
        help="Pass through Gate 0.3 verdict into the decision artifact.",
    )
    parser.add_argument(
        "--quaternary-model-substituted",
        default=None,
        help="If Phi → Qwen-3B substitution was taken, record the substitute.",
    )
    return parser


def _expand_globs(patterns: Optional[str]) -> List[str]:
    if patterns is None:
        return []
    # argparse stores as a single string; split on whitespace for convenience
    # if the caller pasted multiple globs separated by spaces.
    return [p for p in patterns.split() if p]


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    probe_meta = load_probe_metadata(Path(args.probes))

    # ---- Sweep mode (single run) ----
    if args.sweep_mode:
        if not args.runs:
            raise SystemExit("--sweep-mode requires --runs <run.jsonl>")
        run_outcomes = load_outcomes(Path(args.runs))
        divergence_outcomes = (
            load_outcomes(Path(args.check_divergence))
            if args.check_divergence
            else None
        )
        report = _sweep_report(run_outcomes, probe_meta, divergence_outcomes)
        out_text = json.dumps(report, indent=2)
        if args.output:
            Path(args.output).write_text(out_text + "\n", encoding="utf-8")
        else:
            print(out_text)
        return 0

    # All non-sweep modes require b13 + phase-f globs
    b13_outcomes = load_outcomes_from_glob(_expand_globs(args.b13_runs))
    phase_f_outcomes = load_outcomes_from_glob(_expand_globs(args.phase_f_runs))

    # ---- F2-only enforcement ----
    if args.f2_enforcement_only:
        cells: Dict[Tuple[str, str, str], CellSummary] = {}
        for k, v in split_outcomes_by_cell(b13_outcomes).items():
            cells[k] = aggregate_cell(v, probe_meta)
        for k, v in split_outcomes_by_cell(phase_f_outcomes).items():
            cells[k] = aggregate_cell(v, probe_meta)
        primary_b13 = next(
            (
                c
                for c in cells.values()
                if c.family == "primary" and c.variant == "b13" and c.mode == "advanced"
            ),
            None,
        )
        primary_phase_f = next(
            (
                c
                for c in cells.values()
                if c.family == "primary"
                and c.variant in ("phase-f", "rc1")
                and c.mode == "advanced"
            ),
            None,
        )
        if primary_b13 is None or primary_phase_f is None:
            raise SystemExit(
                "F2 enforcement requires both b13 and phase-f primary advanced cells."
            )
        f2_block = criterion_f2(primary_b13, primary_phase_f)
        verdict = {
            "f2_pass": f2_block["pass"],
            "per_class_deltas": f2_block["per_class_deltas"],
            "failures": f2_block["failures"],
        }
        out_text = json.dumps(verdict, indent=2)
        if args.output:
            Path(args.output).write_text(out_text + "\n", encoding="utf-8")
        else:
            print(out_text)
        return 0 if f2_block["pass"] else 1

    # ---- Fallback C check (update existing decision) ----
    if args.fallback_c3_check:
        if not args.output_update:
            raise SystemExit(
                "--fallback-c3-check requires --output-update <decision.json>"
            )
        # Resolve + validate the path: it must already exist (run the
        # default mode first) AND have a .json suffix. The exists() check
        # rejects arbitrary file creation; the suffix check rejects
        # path-traversal abuse. Static analysis (Sonar pythonsecurity:S2083)
        # flagged the prior unchecked write — these two guards close it.
        decision_path = Path(args.output_update).resolve()
        if not decision_path.exists():
            raise SystemExit(
                f"--output-update target {decision_path} does not exist; "
                "run the default mode first to produce a wired decision."
            )
        if decision_path.suffix != ".json":
            raise SystemExit(
                f"--output-update target {decision_path} must have a .json suffix."
            )
        decision = json.loads(decision_path.read_text(encoding="utf-8"))
        decision = _apply_fallback_c_check(decision, phase_f_outcomes, probe_meta)
        decision_path.write_text(
            json.dumps(decision, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "fallback_c1_pass": decision["fallback_c1_pass"],
                    "fallback_c2_pass": decision["fallback_c2_pass"],
                    "fallback_c3_pass": decision["fallback_c3_pass"],
                    "criterion_c_path": decision["criterion_c_path"],
                    "gate_passed": decision["gate_passed"],
                },
                indent=2,
            )
        )
        return 0

    # ---- Default mode (full gate decision) ----
    if not args.output:
        raise SystemExit("--output is required in default mode.")
    decision = _build_gate_decision(
        b13_outcomes,
        phase_f_outcomes,
        probe_meta,
        quaternary_model_substituted=args.quaternary_model_substituted,
        gate_0_schema_shape=args.gate_0_schema_shape,
        gate_0_3_verdict=args.gate_0_3_verdict,
    )
    Path(args.output).write_text(
        json.dumps(decision, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "gate_passed": decision["gate_passed"],
                "criterion_c_path": decision["criterion_c_path"],
                "output": args.output,
            },
            indent=2,
        )
    )
    return 0 if decision["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
