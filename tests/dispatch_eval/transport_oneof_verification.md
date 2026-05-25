# Gate 0.2 — `oneOf` transport verification

**Date run:** 2026-05-25
**FastMCP version:** mcp 1.27.0
**Check script:** [`check_transport.py`](./check_transport.py)

## Setup

The probe registers a single tool — `probe_tool` — gated on
`OZM_GATE_0_PROBE=1` in `openzim_mcp/server.py`. When the env var is set,
the early-return registration block in `__init__` calls
`register_gate_0_probe_tool(self.mcp)` (in `openzim_mcp/tool_schemas.py`)
and skips the normal tool wiring. The probe uses **Pattern B (Tool.parameters
override)** because it produces the bare-`oneOf` shape — any wire-side
flattening, normalization, or schema rewriting shows up cleanly without the
distraction of `$defs`/`$ref` indirection.

Pattern C (Pydantic discriminated Union) is also exercised in-process for
comparison; the discriminator block emits `oneOf` natively, and we want to
record whether both patterns are viable for rc1.

The probe block in `server.py` is **reverted in Task Z2** of the Gate 0 PR —
verification artifacts (this markdown + the check scripts) remain committed.

## Summary

| Transport                                 | `oneOf` survives | Notes |
| ----------------------------------------- | ---------------- | ----- |
| in-memory (Pattern B override)            | YES              | `Tool.parameters` direct read confirms override is stored. |
| stdio JSON-RPC (Pattern B override)       | YES              | `tools/list` response carries `inputSchema.oneOf` verbatim. |
| streamable-http (Pattern B override)      | YES              | `tools/list` response (SSE-framed JSON-RPC over `POST /mcp`) carries `inputSchema.oneOf` verbatim. |
| in-memory (Pattern C — pydantic discriminator) | YES         | `oneOf` + `$defs` + `discriminator.mapping` all present in `Tool.parameters`. |

All five summary booleans (`in_memory_oneOf`, `stdio_oneOf`, `http_available`,
`http_oneOf`, `pattern_c_oneOf`) were `true` on this run.

## Probe results

### In-memory (Pattern B — Tool.parameters override)

```json
{
  "transport": "in-memory",
  "ok": true,
  "tool_names": ["probe_tool"],
  "parameters": {
    "type": "object",
    "oneOf": [
      {"title": "fulltext", "type": "object", "required": ["mode"],
       "properties": {"mode": {"const": "fulltext"},
                      "namespace": {"type": "string"},
                      "limit": {"type": "integer"}}},
      {"title": "title",   "type": "object", "required": ["mode"],
       "properties": {"mode": {"const": "title"}}},
      {"title": "suggest", "type": "object", "required": ["mode"],
       "properties": {"mode": {"const": "suggest"}}}
    ]
  },
  "contains_oneOf": true
}
```

### stdio JSON-RPC (Pattern B)

The probe sends `initialize` (protocol 2025-06-18), then
`notifications/initialized`, then `tools/list` over the subprocess's stdin
(`python -m openzim_mcp /tmp --transport stdio`), waits for `communicate()`,
and pulls the response with `id == 2`. Full `tools/list` response below;
note the `inputSchema.oneOf` block survives the wire trip with all three
branches intact.

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "probe_tool",
        "description": "Gate 0.2 probe — flat base, oneOf override applied at registration.",
        "inputSchema": {
          "type": "object",
          "oneOf": [
            {"title": "fulltext", "type": "object", "required": ["mode"],
             "properties": {"mode": {"const": "fulltext"},
                            "namespace": {"type": "string"},
                            "limit": {"type": "integer"}}},
            {"title": "title",   "type": "object", "required": ["mode"],
             "properties": {"mode": {"const": "title"}}},
            {"title": "suggest", "type": "object", "required": ["mode"],
             "properties": {"mode": {"const": "suggest"}}}
          ]
        },
        "outputSchema": {
          "properties": {"result": {"title": "Result", "type": "string"}},
          "required": ["result"],
          "title": "probe_toolOutput",
          "type": "object"
        }
      }
    ]
  }
}
```

### streamable-http (Pattern B)

The probe binds the server to `127.0.0.1:<random-free-port>` via `python -m
openzim_mcp /tmp --transport http --host 127.0.0.1 --port <port>`, waits for
the TCP socket to accept, then issues three `POST /mcp` calls:

  1. `initialize` — captures the `Mcp-Session-Id` response header.
  2. `notifications/initialized` — same session.
  3. `tools/list` — same session.

The server replies in `text/event-stream` frames; the probe parses the
`data:` line as JSON. Response body (HTTP 200, `Content-Type:
text/event-stream`):

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "tools": [
      {
        "name": "probe_tool",
        "description": "Gate 0.2 probe — flat base, oneOf override applied at registration.",
        "inputSchema": {
          "type": "object",
          "oneOf": [
            {"title": "fulltext", "type": "object", "required": ["mode"],
             "properties": {"mode": {"const": "fulltext"},
                            "namespace": {"type": "string"},
                            "limit": {"type": "integer"}}},
            {"title": "title",   "type": "object", "required": ["mode"],
             "properties": {"mode": {"const": "title"}}},
            {"title": "suggest", "type": "object", "required": ["mode"],
             "properties": {"mode": {"const": "suggest"}}}
          ]
        },
        "outputSchema": {
          "properties": {"result": {"title": "Result", "type": "string"}},
          "required": ["result"],
          "title": "probe_toolOutput",
          "type": "object"
        }
      }
    ]
  }
}
```

### In-memory (Pattern C — pydantic discriminator)

For comparison, a discriminated Union of three Pydantic models produces
the following `Tool.parameters` in-process (no subprocess round-trip
performed for Pattern C — the override path is what's wired through
`server.py`):

```json
{
  "$defs": {
    "_CFulltext": {"properties": {"mode": {"const": "fulltext", "title": "Mode", "type": "string"},
                                   "namespace": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Namespace"},
                                   "limit":     {"anyOf": [{"type": "integer"}, {"type": "null"}], "default": null, "title": "Limit"}},
                    "required": ["mode"], "title": "_CFulltext", "type": "object"},
    "_CTitle":    {"properties": {"mode": {"const": "title", "title": "Mode", "type": "string"}},
                    "required": ["mode"], "title": "_CTitle", "type": "object"},
    "_CSuggest":  {"properties": {"mode": {"const": "suggest", "title": "Mode", "type": "string"}},
                    "required": ["mode"], "title": "_CSuggest", "type": "object"}
  },
  "properties": {
    "args": {
      "discriminator": {"mapping": {"fulltext": "#/$defs/_CFulltext",
                                     "title":    "#/$defs/_CTitle",
                                     "suggest":  "#/$defs/_CSuggest"},
                         "propertyName": "mode"},
      "oneOf": [{"$ref": "#/$defs/_CFulltext"},
                {"$ref": "#/$defs/_CTitle"},
                {"$ref": "#/$defs/_CSuggest"}],
      "title": "Args"
    }
  },
  "required": ["args"],
  "title": "probe_cArguments",
  "type": "object"
}
```

## Notes / surprises

- Streamable-http returned the JSON-RPC envelope inside an SSE
  `data:` frame (`Content-Type: text/event-stream`), not as a flat
  `application/json` body. The probe handles both shapes. This is per the
  MCP streamable-http spec — clients are expected to handle SSE framing.
- The probe block in `__init__` must set `self.subscriber_registry = None`
  even when returning early; otherwise `http_app.serve_streamable_http`
  raises `AttributeError` on `server.subscriber_registry`.
- No schema flattening or normalization observed on either transport. The
  Pattern B override's bare-`oneOf` schema (no `$defs`, no `$ref`) is the
  shape we are forwarding into rc1 because the wire result is identical to
  what we author.

## Verdict

**PROCEED-AS-DESIGNED** — `oneOf` round-trips on both stdio and
streamable-http from the Gate 0.1 winning pattern. The plan's existing
`oneOf`-gated branches in Stages B and D remain in force; no spec
amendment is required.

**rc1 production pattern recommendation:** **Pattern B (Tool.parameters
override)** for `zim_search` and `zim_get`. Rationale:

  - It rides through both transports unchanged (verified).
  - It produces a bare `oneOf` (no `$defs` indirection) — cleaner
    self-documenting schema for clients walking the input shape.
  - It keeps the Python function signature flat (a single function with
    all named parameters), which preserves existing tool-handler
    refactoring patterns: handler reads parameters by name, dispatches on
    `mode`.
  - The override happens at registration time, immediately after the
    `@mcp.tool()` decorator — no Pydantic-model boilerplate needed for
    each mode branch.

Pattern C (Pydantic discriminator) remains a viable fallback if a downstream
client requires the `discriminator.propertyName` block (some JSON Schema
validators prefer it for error reporting). For the current Gate 0 PR we
align on Pattern B.

Gate 0.3 — which runs in Stage B against prototype skeletons for
`zim_search` and `zim_get` — will validate this choice end-to-end against
real handler dispatch.
