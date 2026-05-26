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
# scope_limitations). The total stays well below the 25KB MCP Tax pain band
# the spec targets; per-tool allocations match the measured rc1 footprint
# with explicit headroom and the test enforces a *1.2 slack so a single
# tool's drift trips before total drift does.
TOTAL_CAP = 24_500
ALLOCATION = {
    "zim_query": 6_500,
    "zim_search": 4_200,
    "zim_get": 4_250,
    "zim_get_section": 2_250,
    "zim_browse": 2_100,
    "zim_metadata": 1_250,
    "zim_links": 2_450,
    "zim_health": 1_200,
}


def _measure_tools(mode: str) -> dict[str, int]:
    cfg = OpenZimMcpConfig(allowed_directories=[_ALLOWED_DIR], tool_mode=mode)
    srv = OpenZimMcpServer(cfg)
    return {
        name: len(
            json.dumps(
                {
                    "name": name,
                    "description": tool.description,
                    "inputSchema": tool.parameters,
                }
            ).encode()
        )
        for name, tool in srv.mcp._tool_manager._tools.items()
    }


def test_advanced_total_under_cap():
    bytes_by_tool = _measure_tools("advanced")
    total = sum(bytes_by_tool.values())
    assert total <= TOTAL_CAP, (
        f"Phase F schema budget exceeded: {total} > {TOTAL_CAP}. "
        "Either trim a tool's description or redistribute ALLOCATION; "
        "the total is the hard cap (below 25KB MCP Tax pain band)."
    )


def test_per_tool_allocations():
    """Per-tool 20% slack. If a tool legitimately needs more (e.g., Stage E
    F2 traces a class regression to too-tight description), redistribute by
    editing ALLOCATION above — take budget from a tool that's under-using
    its share, keep TOTAL_CAP fixed. The total is the only hard cap; per-tool
    allocations are a distribution decision the gate can revise (see spec
    §Tool-by-tool budget allocation).
    """
    bytes_by_tool = _measure_tools("advanced")
    for name, alloc in ALLOCATION.items():
        actual = bytes_by_tool[name]
        assert actual <= alloc * 1.2, (
            f"{name} exceeds allocation: {actual} > {int(alloc * 1.2)} "
            f"(alloc={alloc}, slack=20%)"
        )


def test_simple_mode_only_registers_zim_query():
    bytes_by_tool = _measure_tools("simple")
    assert set(bytes_by_tool) == {
        "zim_query"
    }, f"simple mode must register only zim_query; got {set(bytes_by_tool)}"


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
            "The fallback ships only if the legibility fix demonstrably stops Z4 "
            "misroutes."
        )


def test_gate_decision_scope_limitations_documented():
    """The gate's measurement bounds must be machine-readable, not just
    inferable from spec prose. Catches the case where a maintainer re-runs
    Gate 0b under different conditions (different probe set, different model
    coverage, different language) and forgets to update scope_limitations.
    """
    decision = json.loads(GATE_DECISION_PATH.read_text())
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
