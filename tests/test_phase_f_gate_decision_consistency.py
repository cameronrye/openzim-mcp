"""Gate-decision consistency — the rc1 commit's baked-in constants match the
committed Gate 0b decision file.

Production code does NOT read ``gate_0b_decision.json`` at runtime. The
decision values are baked as Python constants in the rc1 commit at PR-author
time. This test enforces that those constants don't drift from the gate
outcome — a future maintainer who re-runs Gate 0b and re-commits the decision
file without updating the production constants will trip this test.
"""

import json
import pathlib
import re
import tempfile

REPO = pathlib.Path(__file__).parent.parent
DECISION = json.loads(
    (REPO / "tests" / "dispatch_eval" / "gate_0b_decision.json").read_text()
)
_ALLOWED_DIR = tempfile.mkdtemp(prefix="openzim_mcp_gate_consistency_")


def test_zim_search_criterion_c_path_matches_decision():
    """zim_search.py's _CRITERION_C_PATH constant matches gate's criterion_c_path."""
    source = (REPO / "openzim_mcp" / "tools" / "zim_search.py").read_text()
    match = re.search(
        r'_CRITERION_C_PATH\s*:\s*Literal\[[^\]]+\]\s*=\s*"(wired|fallback)"',
        source,
    )
    assert match is not None, "_CRITERION_C_PATH constant not found in zim_search.py"
    assert match.group(1) == DECISION["criterion_c_path"], (
        f"Drift: zim_search.py has _CRITERION_C_PATH={match.group(1)!r} but "
        f"gate decision says criterion_c_path={DECISION['criterion_c_path']!r}. "
        "Either re-bake the constant or re-commit the decision file."
    )


def test_config_tool_mode_default_is_simple():
    """config.py's tool_mode Field default matches gate's default_tool_mode."""
    source = (REPO / "openzim_mcp" / "config.py").read_text()
    match = re.search(
        r'tool_mode\s*:\s*Literal\[[^\]]+\]\s*=\s*Field\s*\(\s*default\s*=\s*"(\w+)"',
        source,
    )
    assert match is not None, "tool_mode Field default not found in config.py"
    assert match.group(1) == DECISION["default_tool_mode"], (
        f"Drift: config.py has tool_mode default={match.group(1)!r} but "
        f"gate decision says default_tool_mode={DECISION['default_tool_mode']!r}."
    )


def test_schema_shape_consistent_with_decision():
    """When Gate 0 selected wired_oneof, zim_search and zim_get must emit oneOf;
    when flat, neither emits oneOf. Cross-checks schema-shape against the gate
    decision.
    """
    from openzim_mcp.config import OpenZimMcpConfig
    from openzim_mcp.server import OpenZimMcpServer

    cfg = OpenZimMcpConfig(allowed_directories=[_ALLOWED_DIR], tool_mode="advanced")
    srv = OpenZimMcpServer(cfg)
    expected_wired = DECISION["gate_0_schema_shape"] == "wired_oneof"
    for name in ("zim_search", "zim_get"):
        schema_str = json.dumps(srv.mcp._tool_manager._tools[name].parameters)
        actual_wired = "oneOf" in schema_str
        assert actual_wired is expected_wired, (
            f"Drift: {name} schema_shape="
            f"{'wired_oneof' if actual_wired else 'flat'!r} but "
            f"gate decision says gate_0_schema_shape="
            f"{DECISION['gate_0_schema_shape']!r}."
        )


def test_gate_0_3_verdict_consistent_with_schema_shape():
    """gate_0_3_verdict='failed' (STOP-AMEND-SPEC) implies schema_shape='flat'.
    Catches the case where a maintainer re-runs Gate 0.3, gets a failure verdict,
    commits the new decision file, but forgets to amend the schemas — then ships
    wired_oneof while the verdict says the model can't parse it.

    gate_0_3_verdict='unvalidated' also implies schema_shape='flat' — the spec's
    fallback rule ships the safer flat schema when 0.3 hasn't run.
    """
    verdict = DECISION["gate_0_3_verdict"]
    if verdict in ("failed", "unvalidated"):
        assert DECISION["gate_0_schema_shape"] == "flat", (
            f"Drift: gate_0_3_verdict={verdict!r} but "
            f"gate_0_schema_shape={DECISION['gate_0_schema_shape']!r}. "
            "Both 'failed' (Qwen could not parse oneOf at the prototype) and "
            "'unvalidated' (0.3 never ran) require flat-schema design; either "
            "re-author rc1 with flat signatures and re-snapshot, or re-run "
            "Gate 0.3 with a fixed prototype to validate wired_oneof."
        )
