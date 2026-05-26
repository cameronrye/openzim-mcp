"""Phase F schema-shape tests.

Asserts the ``inputSchema`` generator emits the correct ``oneOf`` branch
structure for ``zim_get`` and ``zim_search`` — or absence thereof if Gate 0
selected flat schemas.

The expected shape is read from ``tests/dispatch_eval/gate_0b_decision.json``
at test time only. Production code does NOT read this JSON at runtime.
"""

import json
import pathlib

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

DECISION_PATH = (
    pathlib.Path(__file__).parent / "dispatch_eval" / "gate_0b_decision.json"
)
SCHEMA_SHAPE = json.loads(DECISION_PATH.read_text())["gate_0_schema_shape"]


def _get_tool_schema(name: str) -> str:
    cfg = OpenZimMcpConfig(allowed_directories=["/tmp"], tool_mode="advanced")
    srv = OpenZimMcpServer(cfg)
    return json.dumps(srv.mcp._tool_manager._tools[name].parameters)


def test_zim_get_schema_shape():
    schema_str = _get_tool_schema("zim_get")
    if SCHEMA_SHAPE == "wired_oneof":
        assert "oneOf" in schema_str, (
            "gate_0_schema_shape='wired_oneof' but zim_get schema lacks oneOf. "
            "Either wire the 4-branch oneOf or re-record the gate decision to "
            "gate_0_schema_shape='flat'."
        )
    else:
        assert "oneOf" not in schema_str, (
            "gate_0_schema_shape='flat' but zim_get schema contains oneOf. "
            "Flat schema ships with handler-level invalid_path_combination "
            "validation; the oneOf wiring is deferred until Gate 0.3 runs."
        )


def test_zim_search_schema_shape():
    schema_str = _get_tool_schema("zim_search")
    if SCHEMA_SHAPE == "wired_oneof":
        assert "oneOf" in schema_str, (
            "gate_0_schema_shape='wired_oneof' but zim_search schema lacks oneOf. "
            "Either wire the 3-mode oneOf or re-record the gate decision to "
            "gate_0_schema_shape='flat'."
        )
    else:
        assert "oneOf" not in schema_str, (
            "gate_0_schema_shape='flat' but zim_search schema contains oneOf. "
            "Flat schema ships with handler-level mode-routing dispatch."
        )
