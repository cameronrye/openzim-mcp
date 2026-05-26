"""Prototype↔rc1 schema parity.

Drift > ±5% bytes OR any structural change to ``inputSchema`` OR description
edit distance > 30% invalidates the Gate 0b / Gate 0.3 measurements (which
were taken against the prototype). The snapshot is committed under
``tests/dispatch_eval/prototype_schema_snapshot.json``.

Allowed: minor prose edits inside the ±5% byte slack AND ≤30% edit distance
(rewording for grammar/clarity typically lands 5–10% edit distance).

Blocked:
  - Schema-shape changes (adding/removing oneOf branches, renaming a
    parameter, changing a Literal's enum values).
  - Substantive description rewrites that change the dispatch signal
    (operations list, examples, mode semantics) while staying inside the
    byte budget.

Both force a Gate 0b re-run.

Re-snapshot path: when the rc1 surface intentionally diverges from the
prototype (description rewrites, parameter additions), re-capture the
snapshot AND append a ``scope_limitations`` entry to gate_0b_decision.json
naming the divergence. The Stage E F2 enforcement (Task E3 Step 3) is the
post-hoc dispatch check covering the re-snapshotted surface.
"""

import json
import pathlib

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

SNAPSHOT_PATH = (
    pathlib.Path(__file__).parent / "dispatch_eval" / "prototype_schema_snapshot.json"
)
BYTE_TOLERANCE = 0.05  # ±5%
DESCRIPTION_EDIT_DISTANCE_TOLERANCE = 0.30  # ≤30% Levenshtein / max(len_a, len_b)


def _rc1_footprints() -> dict[str, dict]:
    cfg = OpenZimMcpConfig(allowed_directories=["/tmp"], tool_mode="advanced")
    srv = OpenZimMcpServer(cfg)
    out = {}
    for name, tool in srv.mcp._tool_manager._tools.items():
        wire = json.dumps(
            {
                "name": name,
                "description": tool.description,
                "inputSchema": tool.parameters,
            }
        )
        out[name] = {
            "bytes": len(wire.encode()),
            "description": tool.description,
            "inputSchema": tool.parameters,
        }
    return out


def _strip_descriptions(schema):
    """Walk inputSchema dict and drop ``description`` fields so the structural
    comparison ignores prose."""
    if isinstance(schema, dict):
        return {
            k: _strip_descriptions(v) for k, v in schema.items() if k != "description"
        }
    if isinstance(schema, list):
        return [_strip_descriptions(item) for item in schema]
    return schema


def _normalized_edit_distance(a: str, b: str) -> float:
    """Levenshtein distance normalized by ``max(len(a), len(b))``.

    Returns 0.0 if both empty, 1.0 if either is empty.
    """
    if not a and not b:
        return 0.0
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
                f"Either tighten the rc1 description to match the prototype's "
                f"measured footprint, or re-run Gate 0b against the rewritten "
                f"rc1 surface and re-commit the snapshot."
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
                f"{name}: inputSchema shape differs from prototype "
                "(descriptions ignored). Schema-shape changes (oneOf branches, "
                "parameter names, types, enums) require re-running Gate 0b."
            )
    assert not failures, "\n".join(failures)


def test_prototype_parity_description_edit_distance():
    """Catches substantive prose rewrites that fit inside the byte budget but
    change the dispatch signal Gate 0b measured. 30% is deliberately generous —
    typical grammar/clarity edits land 5–10%; anything past 30% means the
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
                "A pure prose rewrite within the byte budget can change the "
                "dispatch signal Gate 0b measured. Either revert toward the "
                "prototype's description, or re-run Gate 0b for this tool "
                "and re-snapshot."
            )
    assert not failures, "\n".join(failures)


def test_prototype_snapshot_covers_all_rc1_tools():
    """A new tool added to rc1 without a snapshot entry would silently slip
    parity. Pin parity coverage to the full rc1 surface.
    """
    snapshot = json.loads(SNAPSHOT_PATH.read_text())
    rc1 = _rc1_footprints()
    missing = set(rc1) - set(snapshot)
    assert not missing, (
        f"rc1 tools missing from prototype snapshot: {sorted(missing)}. "
        "Re-capture the snapshot (tests/dispatch_eval/prototype_schema_snapshot.json)."
    )
