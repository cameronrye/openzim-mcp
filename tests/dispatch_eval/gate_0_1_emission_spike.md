# Gate 0.1 — `oneOf` emission spike

**Date run:** 2026-05-25
**FastMCP version:** mcp 1.27.0 (per `pip show mcp`; FastMCP ships in the `mcp` SDK)
**Spike script:** [`gate_0_1_emission_spike.py`](./gate_0_1_emission_spike.py)

## Pattern results

```json
{
  "patterns": [
    {
      "pattern": "A — Literal-gated type signature",
      "registered": true,
      "parameters": {
        "properties": {
          "mode": {
            "default": "fulltext",
            "enum": ["fulltext", "title", "suggest"],
            "title": "Mode",
            "type": "string"
          },
          "namespace": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "default": null,
            "title": "Namespace"
          },
          "limit": {
            "anyOf": [{"type": "integer"}, {"type": "null"}],
            "default": null,
            "title": "Limit"
          }
        },
        "title": "probe_aArguments",
        "type": "object"
      },
      "contains_oneOf": false,
      "parameters_json_text_has_oneOf": false
    },
    {
      "pattern": "B — explicit inputSchema override (via Tool.parameters mutation; decorator does not accept an inputSchema= kwarg in mcp 1.27.0)",
      "registered": true,
      "override_method": "Tool.parameters direct assignment",
      "parameters": {
        "type": "object",
        "oneOf": [
          {
            "title": "fulltext",
            "type": "object",
            "required": ["mode"],
            "properties": {
              "mode": {"const": "fulltext"},
              "namespace": {"type": "string"},
              "limit": {"type": "integer"}
            }
          },
          {
            "title": "title",
            "type": "object",
            "required": ["mode"],
            "properties": {"mode": {"const": "title"}}
          },
          {
            "title": "suggest",
            "type": "object",
            "required": ["mode"],
            "properties": {"mode": {"const": "suggest"}}
          }
        ]
      },
      "contains_oneOf": true,
      "parameters_json_text_has_oneOf": true
    },
    {
      "pattern": "C — Pydantic discriminated Union (mode discriminator)",
      "registered": true,
      "parameters": {
        "$defs": {
          "_FulltextArgs": {
            "properties": {
              "mode": {"const": "fulltext", "title": "Mode", "type": "string"},
              "namespace": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": null,
                "title": "Namespace"
              },
              "limit": {
                "anyOf": [{"type": "integer"}, {"type": "null"}],
                "default": null,
                "title": "Limit"
              }
            },
            "required": ["mode"],
            "title": "_FulltextArgs",
            "type": "object"
          },
          "_TitleArgs": {
            "properties": {
              "mode": {"const": "title", "title": "Mode", "type": "string"}
            },
            "required": ["mode"],
            "title": "_TitleArgs",
            "type": "object"
          },
          "_SuggestArgs": {
            "properties": {
              "mode": {"const": "suggest", "title": "Mode", "type": "string"}
            },
            "required": ["mode"],
            "title": "_SuggestArgs",
            "type": "object"
          }
        },
        "properties": {
          "args": {
            "discriminator": {
              "mapping": {
                "fulltext": "#/$defs/_FulltextArgs",
                "title": "#/$defs/_TitleArgs",
                "suggest": "#/$defs/_SuggestArgs"
              },
              "propertyName": "mode"
            },
            "oneOf": [
              {"$ref": "#/$defs/_FulltextArgs"},
              {"$ref": "#/$defs/_TitleArgs"},
              {"$ref": "#/$defs/_SuggestArgs"}
            ],
            "title": "Args"
          }
        },
        "required": ["args"],
        "title": "probe_cArguments",
        "type": "object"
      },
      "contains_oneOf": true,
      "parameters_json_text_has_oneOf": true
    }
  ],
  "any_pattern_emits_oneOf": true,
  "winning_patterns": [
    "B — explicit inputSchema override (via Tool.parameters mutation)",
    "C — Pydantic discriminated Union (mode discriminator)"
  ]
}
```

## Pattern notes

- **Pattern A (Literal-gated):** Emits a flat schema with `enum` on `mode` plus
  `anyOf [type, null]` for the optional fields. No `oneOf` anywhere. As
  expected — pydantic does not know the parameter set is mode-conditional.
- **Pattern B (Tool.parameters override):** The `@FastMCP.tool()` decorator
  signature, verified via `inspect.signature` against `mcp==1.27.0`, accepts
  `name | title | description | annotations | icons | meta | structured_output`
  but **no** `inputSchema=` / `parameters=` / `schema=` kwarg.
  `FastMCP.add_tool` is identical. The only available override surface is
  direct mutation of the registered `Tool` instance's `parameters` dict —
  `srv._tool_manager._tools[name].parameters = {...}`. This works and the
  override survives in-memory inspection. Whether it survives wire
  serialisation is what Gate 0.2 verifies.
- **Pattern C (Pydantic discriminator):** Defining a discriminated Union as
  the parameter type **does** produce a native `oneOf` (with `$defs`,
  `discriminator.propertyName`, and `discriminator.mapping`). This is the
  cleanest of the three since the schema follows directly from the Python
  type and no post-registration mutation is needed. One gotcha: the
  discriminated-Union alias must be defined at **module scope** — FastMCP
  calls `inspect.signature(func, eval_str=True)` which fails to resolve
  names defined in a function's local scope.

## Verdict

**PROCEED-TO-GATE-0.2** — Two patterns produce `oneOf` in-memory:

- Pattern B (explicit `inputSchema` override via `Tool.parameters` mutation)
- Pattern C (Pydantic discriminated Union)

**Recommended rc1 production pattern:** Pattern C (Pydantic discriminator).
It is structurally cleaner (the schema is derived from the type, not bolted
on), it ships with a `discriminator.mapping` block that clients can use, and
it avoids reaching into `_tool_manager._tools` internals at registration time.

Pattern B is retained as a fallback in case Gate 0.2 shows that the
discriminator block does not round-trip cleanly through the wire transport
while a hand-authored bare-`oneOf` schema does.

Gate 0.2 will exercise both patterns in subprocess stdio (and HTTP if
available) to confirm `oneOf` survives the JSON-RPC `tools/list` response.
