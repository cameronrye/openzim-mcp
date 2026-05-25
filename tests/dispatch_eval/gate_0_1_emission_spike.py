"""Gate 0.1 — FastMCP `oneOf` emission spike.

Tries three registration patterns and dumps each tool's `parameters` schema
(in memory, before any wire serialisation), reporting whether the literal
substring ``"oneOf"`` appears.

Run::

    python tests/dispatch_eval/gate_0_1_emission_spike.py

Output is JSON on stdout. The companion markdown file
``gate_0_1_emission_spike.md`` records the verdict.
"""

from __future__ import annotations

import json
import traceback
from typing import Any, Dict, List, Literal, Optional, Union

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.tools.base import Tool
from pydantic import BaseModel, Field


def _dump_tool_params(srv: FastMCP, name: str) -> Dict[str, Any]:
    """Pull the registered tool's parameters dict via the documented path."""
    tool = srv._tool_manager._tools[name]
    return tool.parameters


def _contains_one_of(schema_obj: Any) -> bool:
    """Recursive search for a literal ``"oneOf"`` key anywhere in the schema."""
    if isinstance(schema_obj, dict):
        if "oneOf" in schema_obj:
            return True
        return any(_contains_one_of(v) for v in schema_obj.values())
    if isinstance(schema_obj, list):
        return any(_contains_one_of(item) for item in schema_obj)
    return False


def pattern_a_literal_gated() -> Dict[str, Any]:
    """Pattern A — Literal-gated type signature.

    Hope: pydantic emits ``anyOf`` or ``oneOf`` when the parameter set changes
    based on a Literal value. (In practice pydantic produces a flat union;
    schema-conditional emission is not automatic.)
    """
    try:
        srv = FastMCP("pattern-a")

        @srv.tool()
        def probe_a(
            mode: Literal["fulltext", "title", "suggest"] = "fulltext",
            namespace: Optional[str] = None,
            limit: Optional[int] = None,
        ) -> str:
            """Probe tool — Literal-gated mode parameter."""
            return f"{mode}/{namespace}/{limit}"

        params = _dump_tool_params(srv, "probe_a")
        return {
            "pattern": "A — Literal-gated type signature",
            "registered": True,
            "parameters": params,
            "contains_oneOf": _contains_one_of(params),
            "parameters_json_text_has_oneOf": "oneOf" in json.dumps(params),
        }
    except Exception as exc:  # pragma: no cover - diagnostic path
        return {
            "pattern": "A — Literal-gated type signature",
            "registered": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "contains_oneOf": False,
        }


def pattern_b_explicit_input_schema() -> Dict[str, Any]:
    """Pattern B — explicit ``inputSchema=`` override.

    The ``@FastMCP.tool()`` decorator signature does **not** accept an
    ``inputSchema``/``parameters`` kwarg (verified via ``inspect.signature``
    against ``mcp==1.27.0``). ``FastMCP.add_tool`` is identical in that
    respect. The only way to install a hand-written JSON Schema is to mutate
    ``tool.parameters`` on the ``Tool`` instance after registration — which
    we exercise here as the closest available surface.
    """
    try:
        srv = FastMCP("pattern-b")

        @srv.tool()
        def probe_b(
            mode: str = "fulltext",
            namespace: Optional[str] = None,
            limit: Optional[int] = None,
        ) -> str:
            """Probe tool — base flat registration that we then override."""
            return f"{mode}/{namespace}/{limit}"

        # Hand-authored oneOf schema. This is the override surface we have:
        # mutate the stored Tool.parameters dict directly.
        override_schema: Dict[str, Any] = {
            "type": "object",
            "oneOf": [
                {
                    "title": "fulltext",
                    "type": "object",
                    "required": ["mode"],
                    "properties": {
                        "mode": {"const": "fulltext"},
                        "namespace": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                },
                {
                    "title": "title",
                    "type": "object",
                    "required": ["mode"],
                    "properties": {
                        "mode": {"const": "title"},
                    },
                },
                {
                    "title": "suggest",
                    "type": "object",
                    "required": ["mode"],
                    "properties": {
                        "mode": {"const": "suggest"},
                    },
                },
            ],
        }
        tool: Tool = srv._tool_manager._tools["probe_b"]
        tool.parameters = override_schema

        params = _dump_tool_params(srv, "probe_b")
        return {
            "pattern": (
                "B — explicit inputSchema override (via Tool.parameters mutation; "
                "decorator does not accept an inputSchema= kwarg in mcp 1.27.0)"
            ),
            "registered": True,
            "override_method": "Tool.parameters direct assignment",
            "parameters": params,
            "contains_oneOf": _contains_one_of(params),
            "parameters_json_text_has_oneOf": "oneOf" in json.dumps(params),
        }
    except Exception as exc:  # pragma: no cover
        return {
            "pattern": "B — explicit inputSchema override",
            "registered": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "contains_oneOf": False,
        }


class _FulltextArgs(BaseModel):
    mode: Literal["fulltext"]
    namespace: Optional[str] = None
    limit: Optional[int] = None


class _TitleArgs(BaseModel):
    mode: Literal["title"]


class _SuggestArgs(BaseModel):
    mode: Literal["suggest"]


# Module-scope alias so that ``inspect.signature(..., eval_str=True)`` can
# resolve the annotation. Local-scope class definitions inside the pattern
# function break FastMCP's annotation evaluator (NameError under eval_str).
_SearchArgs = Union[_FulltextArgs, _TitleArgs, _SuggestArgs]


def pattern_c_pydantic_discriminator() -> Dict[str, Any]:
    """Pattern C — Pydantic discriminated Union as the tool's parameter type."""
    try:
        srv = FastMCP("pattern-c")

        @srv.tool()
        def probe_c(
            args: _SearchArgs = Field(..., discriminator="mode"),  # type: ignore[assignment]
        ) -> str:
            """Probe tool — Pydantic discriminated Union parameter."""
            return repr(args)

        params = _dump_tool_params(srv, "probe_c")
        return {
            "pattern": "C — Pydantic discriminated Union (mode discriminator)",
            "registered": True,
            "parameters": params,
            "contains_oneOf": _contains_one_of(params),
            "parameters_json_text_has_oneOf": "oneOf" in json.dumps(params),
        }
    except Exception as exc:  # pragma: no cover
        return {
            "pattern": "C — Pydantic discriminated Union",
            "registered": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "contains_oneOf": False,
        }


def main() -> None:
    results: List[Dict[str, Any]] = [
        pattern_a_literal_gated(),
        pattern_b_explicit_input_schema(),
        pattern_c_pydantic_discriminator(),
    ]

    summary = {
        "patterns": results,
        "any_pattern_emits_oneOf": any(r.get("contains_oneOf") for r in results),
        "winning_patterns": [r["pattern"] for r in results if r.get("contains_oneOf")],
    }
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
