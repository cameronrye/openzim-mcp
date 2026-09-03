"""Phase F schema budget enforcement (build-time audit, not runtime config).

Reads ``tests/dispatch_eval/gate_0b_decision.json`` to cross-check that the
rc1 commit's behavior matches the recorded Gate 0b outcome. Production code
does NOT read this JSON at runtime in normal use.

The per-tool ``ALLOCATION`` dict + ``TOTAL_CAP`` are baked here as Python
constants in this commit; the decision JSON ships only under ``tests/``.
"""

import json
import pathlib
import re
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
# these bytes were freed on purpose, as headroom to spend rather than as a new
# baseline. The schema work they were originally held for is not coming: #370
# closed not-planned on 2026-08-24, declining ``outputSchema`` on its per-call
# cost (structured content duplicates the whole body — ~+100% on
# ``zim_get_section``) rather than on budget. They stay reserved as general
# description budget, and for a wider ``zim_search`` input schema should #395
# adopt the oneOf variant. Re-deriving now would hand them straight back and
# make spending a single byte of them a table edit. The property the rebalance
# was protecting still holds meanwhile: every ceiling sits above its tool's
# measurement by less than the total still has free, so a single tool's drift
# trips its own named assertion before the aggregate one. That is no longer
# stated as a pair of hand-copied numbers — it is asserted by
# ``test_per_tool_headroom_stays_under_the_total_headroom``, and the trailing
# comments above are asserted by ``test_allocation_comments_state_the_measured
# _bytes``. Both of those went stale here before they were tests: three of the
# eight comments drifted a release behind the surface they annotate.
# Re-derive at ``(measured + ~130) / 1.2`` once the headroom is actually spent.
TOTAL_CAP = 25 * 1024
# Trailing comments are the wire bytes measured after the schema trim. The
# allocation is deliberately not that number any more, so it is recorded here —
# otherwise the table stops telling a reader what the surface actually costs.
ALLOCATION = {
    "zim_query": 5_550,  # 6,266B
    "zim_search": 3_620,  # 3,937B
    "zim_get": 3_650,  # 3,913B
    "zim_get_section": 1_840,  # 1,863B
    "zim_browse": 2_080,  # 2,170B
    "zim_metadata": 1_310,  # 1,386B
    "zim_links": 2_700,  # 2,990B
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


# --------------------------------------------------------------------------
# The two properties the ALLOCATION table's prose asserts about itself.
# Both were comments before they were tests, and both had gone stale.
# --------------------------------------------------------------------------

# ``"zim_query": 5_550,  # 6,243B`` -> ("zim_query", "6,277")
_ALLOCATION_COMMENT_RE = re.compile(
    r'^\s*"(zim_[a-z_]+)":\s*[\d_]+,\s*#\s*([\d,]+)B\s*$', re.MULTILINE
)


def _allocation_comments() -> dict[str, int]:
    """The measured byte figure each ALLOCATION row records in its comment."""
    source = pathlib.Path(__file__).read_text(encoding="utf-8")
    table = source.split("ALLOCATION = {", 1)[1].split("}", 1)[0]
    return {
        name: int(figure.replace(",", ""))
        for name, figure in _ALLOCATION_COMMENT_RE.findall(table)
    }


def test_allocation_comments_state_the_measured_bytes():
    """Each row's trailing comment must be that tool's real wire footprint.

    The allocation column is a budget decision and deliberately floats away
    from the measurement; the comment is the only place the table says what a
    tool actually costs. Three of the eight drifted a release behind before
    this test existed (zim_query 6,222 -> 6,277, zim_get 3,946 -> 3,913,
    zim_links 2,920 -> 2,985), so the table was quietly describing a surface
    that no longer shipped.
    """
    documented = _allocation_comments()
    assert set(documented) == set(ALLOCATION), (
        "every ALLOCATION row must carry a `# <n>B` comment; parsed "
        f"{sorted(documented)} against {sorted(ALLOCATION)}"
    )
    measured = _measure_tools("advanced")
    stale = [
        f"{name}: comment says {documented[name]:,}B, measures {measured[name]:,}B"
        for name in ALLOCATION
        if documented[name] != measured[name]
    ]
    assert not stale, (
        "ALLOCATION trailing comments no longer match the shipped surface:\n  "
        + "\n  ".join(stale)
    )


def test_per_tool_headroom_stays_under_the_total_headroom():
    """A single tool's drift must trip its own named assertion first.

    That is the whole point of the per-tool split: "the advanced surface is
    130 bytes over" names no culprit, "zim_health exceeds its ceiling" does.
    The property that makes it hold is arithmetic — every tool's remaining
    room (``alloc * 1.2 - measured``) has to be smaller than the room the
    aggregate cap still has (``TOTAL_CAP - total``). Otherwise a tool could
    grow past the total while still sitting under its own ceiling, and
    ``test_advanced_total_under_cap`` would fire first with nothing to name.

    Raising an allocation without checking this is how the guarantee gets
    lost, so it is asserted rather than described.
    """
    measured = _measure_tools("advanced")
    total_headroom = TOTAL_CAP - sum(measured.values())
    assert total_headroom > 0, "aggregate cap already exceeded"
    offenders = [
        f"{name}: ceiling leaves {int(alloc * 1.2) - measured[name]}B, "
        f"total leaves {total_headroom}B"
        for name, alloc in ALLOCATION.items()
        if int(alloc * 1.2) - measured[name] >= total_headroom
    ]
    assert not offenders, (
        "a per-tool ceiling has more room than the aggregate cap does, so "
        "that tool's growth would trip the unnamed total assertion first:\n  "
        + "\n  ".join(offenders)
    )
