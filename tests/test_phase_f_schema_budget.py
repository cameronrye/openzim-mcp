"""Phase F schema budget enforcement (build-time audit, not runtime config).

Reads ``tests/dispatch_eval/gate_0b_decision.json`` to cross-check that the
rc1 commit's behavior matches the recorded Gate 0b outcome. Production code
does NOT read this JSON at runtime in normal use.

The per-tool ``ALLOCATION`` dict + ``TOTAL_CAP`` are baked here as Python
constants in this commit; the decision JSON ships only under ``tests/``.
"""

import json
import pathlib
import tempfile

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

GATE_DECISION_PATH = (
    pathlib.Path(__file__).parent / "dispatch_eval" / "gate_0b_decision.json"
)

# Per-process unique dir; avoids the "publicly writable directory" flag that
# strict static analyzers raise on bare /tmp usage in test code.
_ALLOWED_DIR = tempfile.mkdtemp(prefix="openzim_mcp_schema_budget_")

# Budget caps are baked from the rc1-re-snapshotted baseline (see
# ``tests/dispatch_eval/prototype_schema_snapshot.json`` and the
# ``rc1-description-rewrite`` entry in gate_0b_decision.json's
# scope_limitations). The total stays below the 25KB MCP Tax pain band the
# spec targets; the per-tool entries below are pre-slack budgets whose
# enforced ceiling is ``alloc * 1.2``, sized so a single tool's drift trips
# its own named assertion before the aggregate total does — "the advanced
# surface is 130 bytes over" names no culprit, "zim_health exceeds its
# ceiling" does.
#
# v2.5.2: added the ``kind`` (zim_links) and ``include_assets`` (zim_browse)
# params for the bucket-reachability and binary-discovery fixes. That nudges
# the advanced surface just past 25KB, so the total cap and those two
# allocations are raised to match the re-snapshotted footprint.
#
# 3.0.0: the cap is the pain band itself, 25KiB, now that ``_measure_tools``
# counts the bytes that actually ship rather than ``json.dumps`` padding. The
# allocations below are unchanged and still measured against the same tools,
# so every per-tool ceiling simply gained the padding back as real headroom.
#
# Post-3.1.2: rebalanced. The allocations had stayed at the rc1 footprints
# while the surface grew into the cap, so the eight ceilings summed to 29,940
# against a 25,600 total — headroom the total cap would never honour, handed
# out unevenly. zim_query's ceiling floated 1,266B above its measurement;
# zim_health's sat 4B above its own, so a one-word edit to zim_health failed
# the budget while 168B of the total was still free. Sizing now runs the other
# way round: the *ceiling* is what tracks the measurement, so each allocation
# is ``(measured + ~130) / 1.2``. That leaves every tool 121–133B of room — a
# phrase, not a rewrite — and keeps each ceiling under the 168B the total has
# left, which is what makes the per-tool assertion fire first. Re-derive the
# same way after any surface change, keeping the margin below
# ``TOTAL_CAP - total``. In aggregate the ceilings over-commit on purpose
# (26,460 > 25,600): eight tools each drifting 100B is precisely the drift no
# per-tool ceiling can see and TOTAL_CAP exists to catch.
#
# Post-3.1.2, second change: ``openzim_mcp.schema_slimming`` stopped publishing
# pydantic's ``title`` echoes and ``default: null`` entries, which cost 1,621B
# and said nothing (25,432 → 23,811). The allocations below are deliberately
# NOT re-derived from the new measurements, which is the opposite of the call
# made above — the difference is where the bytes came from. That rebalance was
# correcting ceilings that had drifted away from a surface nobody had shrunk;
# these bytes were freed on purpose, as budget for the description and schema
# work #370 defers. Re-deriving now would hand them straight back and make
# spending a single byte of them a table edit. The property the rebalance was
# protecting still holds meanwhile: every ceiling sits 186–438B above its
# tool's measurement, all of them under the 1,789B the total now has left, so a
# single tool's drift still trips its own named assertion first. Re-derive at
# ``(measured + ~130) / 1.2`` once that work lands and the headroom is spent.
TOTAL_CAP = 25 * 1024
# Trailing comments are the wire bytes measured after the schema trim. The
# allocation is deliberately not that number any more, so it is recorded here —
# otherwise the table stops telling a reader what the surface actually costs.
ALLOCATION = {
    "zim_query": 5_550,  # 6,222B
    "zim_search": 3_620,  # 3,937B
    "zim_get": 3_650,  # 3,946B
    "zim_get_section": 1_840,  # 1,863B
    "zim_browse": 2_080,  # 2,170B
    "zim_metadata": 1_310,  # 1,386B
    "zim_links": 2_700,  # 2,920B
    "zim_health": 1_300,  # 1,367B
}


def _measure_tools(mode: str) -> dict[str, int]:
    """Per-tool wire bytes, counting every field that ships in ``tools/list``.

    ``outputSchema`` used to be omitted here. That blind spot is what let the
    documented footprint go stale: ``zim_query``'s typed return annotation
    generated a 4.7KB output schema, so the real advanced payload was 28.9KB —
    inside the pain band this cap exists to keep it out of — while this
    function measured 24.8KB and the budget stayed green. Anything the client
    receives has to be counted, or the cap is measuring a number nobody pays.

    The same rule cuts the other way, which is why the separators are pinned.
    ``json.dumps`` defaults to ``", "`` and ``": "``, and the wire uses neither
    — pydantic emits compact JSON. Counting a space after every comma and colon
    inflated the measurement by ~620 bytes across the eight advanced tools, so
    the budget read 25,499 of 25,500 and stood one byte from tripping on a
    surface that actually costs 24,881 bytes on the wire, envelope included.
    A cap that fails on padding nobody transmits is measuring a number nobody
    pays just as surely as one that skips a field they do.
    """
    cfg = OpenZimMcpConfig(allowed_directories=[_ALLOWED_DIR], tool_mode=mode)
    srv = OpenZimMcpServer(cfg)
    measured = {}
    for name, tool in srv.mcp._tool_manager._tools.items():
        payload = {
            "name": name,
            "description": tool.description,
            "inputSchema": tool.parameters,
        }
        if tool.output_schema is not None:
            payload["outputSchema"] = tool.output_schema
        measured[name] = len(json.dumps(payload, separators=(",", ":")).encode())
    return measured


def test_advanced_total_under_cap():
    bytes_by_tool = _measure_tools("advanced")
    total = sum(bytes_by_tool.values())
    assert total <= TOTAL_CAP, (
        f"Phase F schema budget exceeded: {total} > {TOTAL_CAP}. "
        "Either trim a tool's description or redistribute ALLOCATION; "
        "the total is the hard cap (below 25KB MCP Tax pain band)."
    )


def test_measurement_counts_wire_bytes_not_serializer_padding():
    """The budget must count what ships, not ``json.dumps`` whitespace.

    ``json.dumps`` defaults to ``", "``/``": "`` separators; the wire is
    compact. Counting the padding put the total one byte from its cap on a
    surface with ~600 bytes of real headroom, which would have failed the
    next description edit for a cost no client ever pays.
    """
    cfg = OpenZimMcpConfig(allowed_directories=[_ALLOWED_DIR], tool_mode="advanced")
    srv = OpenZimMcpServer(cfg)
    measured = _measure_tools("advanced")
    for name, tool in srv.mcp._tool_manager._tools.items():
        payload = {
            "name": name,
            "description": tool.description,
            "inputSchema": tool.parameters,
        }
        if tool.output_schema is not None:
            payload["outputSchema"] = tool.output_schema
        padded = len(json.dumps(payload).encode())
        assert measured[name] < padded, (
            f"{name} is being measured with the padded serializer "
            f"({measured[name]} == {padded}); the wire emits compact JSON."
        )


def test_per_tool_allocations():
    """Per-tool ceiling: the allocation plus its 20% slack.

    A tool that legitimately needs more (e.g., Stage E F2 traces a class
    regression to a too-tight description) can no longer just be handed a
    bigger number without saying where the bytes come from. Raising an
    allocation on its own only moves the failure to
    ``test_advanced_total_under_cap``, which names no tool. The total is the
    only hard cap — the per-tool split stays a distribution decision the gate
    can revise (see spec §Tool-by-tool budget allocation).

    The schema trim left 1,789B under TOTAL_CAP, so for the moment a tool can
    be handed some of that rather than taken from a neighbour's prose. That is
    what the headroom is for; it is not a reason to raise a ceiling past its
    measurement by more than the total can still absorb, which is the condition
    that keeps this assertion firing before the aggregate one.
    """
    bytes_by_tool = _measure_tools("advanced")
    for name, alloc in ALLOCATION.items():
        actual = bytes_by_tool[name]
        assert actual <= alloc * 1.2, (
            f"{name} exceeds its ceiling: {actual} > {int(alloc * 1.2)} "
            f"(allocation {alloc} + 20% slack). Free the bytes elsewhere on "
            f"the surface first, then re-derive this tool's allocation from "
            f"its new measurement."
        )


def test_simple_mode_only_registers_zim_query():
    bytes_by_tool = _measure_tools("simple")
    assert set(bytes_by_tool) == {
        "zim_query"
    }, f"simple mode must register only zim_query; got {set(bytes_by_tool)}"


def test_gate_decision_criterion_d_passed():
    decision = json.loads(GATE_DECISION_PATH.read_text(encoding="utf-8"))
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
    decision = json.loads(GATE_DECISION_PATH.read_text(encoding="utf-8"))
    assert decision["default_tool_mode"] == "simple"


def test_gate_decision_criterion_c_path_known_value():
    decision = json.loads(GATE_DECISION_PATH.read_text(encoding="utf-8"))
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
            "The fallback ships only if the legibility fix demonstrably stops Z4 "
            "misroutes."
        )


def test_gate_decision_scope_limitations_documented():
    """The gate's measurement bounds must be machine-readable, not just
    inferable from spec prose. Catches the case where a maintainer re-runs
    Gate 0b under different conditions (different probe set, different model
    coverage, different language) and forgets to update scope_limitations.
    """
    decision = json.loads(GATE_DECISION_PATH.read_text(encoding="utf-8"))
    limitations = decision.get("scope_limitations", [])
    assert isinstance(limitations, list) and limitations, (
        "gate_0b_decision.json must include a non-empty scope_limitations list. "
        "See spec §scope_limitations field for required entries at v2.0."
    )
    # Required prefixes at v2.0 — re-runs that add models or change probe scope
    # must update these entries, not silently drop them.
    required_prefixes = (
        "probe-distribution:",
        "model-coverage:",
        "size-range:",
        "probe-language:",
    )
    for prefix in required_prefixes:
        assert any(item.startswith(prefix) for item in limitations), (
            f"scope_limitations missing required '{prefix}' entry. "
            f"Got: {limitations}. See spec §scope_limitations field."
        )
