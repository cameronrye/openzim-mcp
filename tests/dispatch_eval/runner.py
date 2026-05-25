"""Gate 0b dispatch-eval runner.

Boots the openzim-mcp server with a chosen variant × mode × model cell,
drives the configured LLM with the system prompt + each probe query, and
records per-probe outcomes to a JSONL file.

USAGE (Cameron runs this — the present module builds the harness only):

    python tests/dispatch_eval/runner.py \\
      --variant {b13,phase-f,phase-f-fallback} \\
      --mode {simple,advanced} \\
      --model {qwen2.5-7b-instruct,haiku-4.5,llama-3.1-8b-instruct, \\
               phi-3.5-mini-instruct,qwen-2.5-3b-instruct} \\
      --reps 5 \\
      --probes tests/dispatch_eval/probes.jsonl \\
      --output tests/dispatch_eval/runs/<variant>__<mode>__<model>__<timestamp>.jsonl

Variant semantics:
  - ``b13``    — runs against whichever surface is active in the current
                 working tree (no env overrides). Operator invokes this from
                 a worktree at the ``v2.0.0b13`` tag.
  - ``phase-f`` — sets ``OZM_PHASE_F_PROTOTYPE=1`` and ``OZM_TOOL_MODE=<mode>``
                 in the spawned MCP server's env. Drives the prototype
                 skeleton.
  - ``phase-f-fallback`` — like ``phase-f`` but ALSO sets
                 ``OZM_CRITERION_C_PATH=fallback`` so ``zim_search`` swaps to
                 the legibility-fallback description.

Per-model adapter table:

  | --model prefix | endpoint                       | parser           |
  |----------------|--------------------------------|------------------|
  | ``qwen*``      | http://localhost:8000/v1       | hermes JSON      |
  | ``llama-3*``   | http://localhost:8001/v1       | llama3_json      |
  | ``phi-3.5*``   | http://localhost:8002/v1       | pythonic         |
  | ``haiku*`` /   | Anthropic SDK                  | tool_use block   |
  | ``claude*``    |                                | (parsed JSON)    |

  Override endpoints via ``OZM_VLLM_BASE_URL`` (qwen primary),
  ``OZM_LLAMA_BASE_URL``, ``OZM_PHI_BASE_URL``.

Per-probe loop. For each (probe, rep):
  1. Spawn (or reuse) an MCP server subprocess with the right env vars.
  2. Pull the tool list via ``tools/list`` JSON-RPC over stdio — this is what
     the model sees.
  3. Send the system prompt + probe ``query`` to the model.
  4. Parse the model's tool call (name, parameters).
  5. Resolve the entry path (best-effort — only set when the tool response
     surfaces a single path).
  6. Score: dispatch_correct, parameter_validity, spurious_route,
     spurious_route_kind.
  7. Append an outcome row to the output JSONL.

Robustness:
  - 30-second per-rep timeout (model call + tool call combined).
  - Model API errors retry up to 3 times; persistent failure records a
    ``tool_called=null, parameter_validity="fail"`` row and continues.
  - Subprocess hangs (rare; MCP server is event-driven) are killed by the
    same 30s wall clock.
  - One probe failure does NOT crash the run.

Output filename convention: ``<variant>__<mode>__<model>__<timestamp>.jsonl``
with ``timestamp`` an ISO 8601 UTC marker like ``2026-05-25T15-23-04Z``.

Dependencies:
  - Standard library only for the OpenAI-compatible endpoints (urllib).
  - ``anthropic`` Python SDK ONLY when ``--model haiku-*`` / ``claude-*`` is
    used. If the SDK is missing in that case, the runner fails fast with a
    clear pip-install hint.
"""

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

DEFAULT_QWEN_BASE_URL = os.environ.get("OZM_VLLM_BASE_URL", "http://localhost:8000/v1")
DEFAULT_LLAMA_BASE_URL = os.environ.get(
    "OZM_LLAMA_BASE_URL", "http://localhost:8001/v1"
)
DEFAULT_PHI_BASE_URL = os.environ.get("OZM_PHI_BASE_URL", "http://localhost:8002/v1")
DEFAULT_TEMPERATURE = float(os.environ.get("OZM_DISPATCH_TEMPERATURE", "0.2"))
PER_REP_TIMEOUT_S = float(os.environ.get("OZM_DISPATCH_TIMEOUT_S", "30"))
MAX_RETRIES = 3

VALID_VARIANTS = {"b13", "phase-f", "phase-f-fallback"}
VALID_MODES = {"simple", "advanced"}

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system_prompt.md"

# Vendor model IDs used when actually hitting the endpoint. Keyed by the
# short ``--model`` flag value (which is what gets recorded in outcome rows
# and the output filename).
_VENDOR_MODEL_IDS = {
    "qwen2.5-7b-instruct": "Qwen/Qwen2.5-7B-Instruct",
    "qwen-2.5-3b-instruct": "Qwen/Qwen2.5-3B-Instruct",
    "llama-3.1-8b-instruct": "meta-llama/Llama-3.1-8B-Instruct",
    "phi-3.5-mini-instruct": "microsoft/Phi-3.5-mini-instruct",
    "haiku-4.5": "claude-haiku-4-5-20251001",
}

# --------------------------------------------------------------------------
# Probe loading
# --------------------------------------------------------------------------


@dataclass
class Probe:
    probe_id: str
    query: str
    operation: str
    expected_tool: str
    expected_parameters: Dict[str, Any]
    tool_eligibility: str
    operational_classes: List[str]
    zim_archive_hint: Optional[str]
    expected_resolved_entry_path: Optional[str]

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Probe":
        return cls(
            probe_id=d["probe_id"],
            query=d["query"],
            operation=d["operation"],
            expected_tool=d["expected_tool"],
            expected_parameters=d.get("expected_parameters", {}),
            tool_eligibility=d.get("tool_eligibility", ""),
            operational_classes=list(d.get("operational_classes", [])),
            zim_archive_hint=d.get("zim_archive_hint"),
            expected_resolved_entry_path=d.get("expected_resolved_entry_path"),
        )


def load_probes(path: Path) -> List[Probe]:
    """Load a JSONL probe file into a list of ``Probe`` records."""
    probes: List[Probe] = []
    with path.open() as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            probes.append(Probe.from_dict(json.loads(raw)))
    return probes


# --------------------------------------------------------------------------
# Per-model adapter dispatch
# --------------------------------------------------------------------------


@dataclass
class ModelAdapter:
    """Per-model dispatch settings.

    ``family`` is one of {"qwen", "llama", "phi", "haiku"}. ``endpoint`` is
    the OpenAI-compatible base URL for vLLM-hosted families, or ``None`` for
    the Anthropic SDK.
    """

    family: str
    short_name: str
    vendor_id: str
    endpoint: Optional[str]


def _build_adapter(model_flag: str) -> ModelAdapter:
    """Resolve --model to (family, endpoint, vendor id) per the table above."""
    m = model_flag.lower()
    vendor_id = _VENDOR_MODEL_IDS.get(m, model_flag)

    if m.startswith("qwen"):
        return ModelAdapter(
            family="qwen",
            short_name=model_flag,
            vendor_id=vendor_id,
            endpoint=DEFAULT_QWEN_BASE_URL,
        )
    if m.startswith("llama-3"):
        return ModelAdapter(
            family="llama",
            short_name=model_flag,
            vendor_id=vendor_id,
            endpoint=DEFAULT_LLAMA_BASE_URL,
        )
    if m.startswith("phi-3.5"):
        return ModelAdapter(
            family="phi",
            short_name=model_flag,
            vendor_id=vendor_id,
            endpoint=DEFAULT_PHI_BASE_URL,
        )
    if m.startswith(("haiku", "claude")):
        return ModelAdapter(
            family="haiku",
            short_name=model_flag,
            vendor_id=vendor_id,
            endpoint=None,
        )
    raise SystemExit(
        f"Unknown --model {model_flag!r}. Expected prefix qwen*, llama-3*, "
        "phi-3.5*, haiku*, or claude*."
    )


# --------------------------------------------------------------------------
# Tool-call parsers (per family)
# --------------------------------------------------------------------------


def _parse_openai_compatible_tool_call(
    response: Dict[str, Any],
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Pull a (tool_name, parameters) pair out of an OpenAI Chat-Completions
    style response. Used for Qwen (hermes), Llama (llama3_json), and Phi
    (pythonic) — vLLM normalizes all three into the OpenAI tool_calls shape.
    """
    try:
        choices = response.get("choices", [])
        if not choices:
            return None, {}
        msg = choices[0].get("message", {})
        tool_calls = msg.get("tool_calls", []) or []
        if not tool_calls:
            return None, {}
        fn = tool_calls[0].get("function", {})
        name = fn.get("name")
        arg_str = fn.get("arguments", "{}")
        if isinstance(arg_str, str):
            # vLLM's pythonic parser sometimes leaks Python literal syntax
            # (single quotes, True/False/None) in older versions. Try JSON
            # first, fall back to ast.literal_eval, accept {} on persistent
            # failure.
            try:
                args = json.loads(arg_str)
            except json.JSONDecodeError:
                try:
                    args = ast.literal_eval(arg_str)
                    if not isinstance(args, dict):
                        args = {}
                except (ValueError, SyntaxError):
                    args = {}
        elif isinstance(arg_str, dict):
            args = dict(arg_str)
        else:
            args = {}
        return name, args
    except (KeyError, IndexError, TypeError):
        return None, {}


def _parse_anthropic_tool_call(
    response_content: List[Any],
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Pull a (tool_name, parameters) pair out of an Anthropic SDK message
    response. The SDK returns parsed content blocks; tool_use blocks carry
    already-parsed JSON in ``.input``.
    """
    for block in response_content or []:
        block_type = getattr(block, "type", None) or (
            block.get("type") if isinstance(block, dict) else None
        )
        if block_type == "tool_use":
            name = getattr(block, "name", None) or (
                block.get("name") if isinstance(block, dict) else None
            )
            args = getattr(block, "input", None) or (
                block.get("input") if isinstance(block, dict) else {}
            )
            if not isinstance(args, dict):
                args = {}
            return name, args
    return None, {}


# --------------------------------------------------------------------------
# MCP server subprocess + JSON-RPC stdio client
# --------------------------------------------------------------------------


class McpStdioClient:
    """Minimal JSON-RPC over stdio client for the openzim-mcp server.

    The MCP wire protocol is JSON-RPC 2.0 framed line-by-line. This client
    speaks just enough of it to (1) initialize, (2) call ``tools/list``,
    and (3) call ``tools/call`` for entry-path resolution.

    The client is intentionally minimal — full MCP framework features
    (notifications, resources, prompts) are out of scope for the dispatch
    eval runner.
    """

    def __init__(self, proc: subprocess.Popen):
        self._proc = proc
        self._next_id = 1

    def _send(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        msg = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            msg["params"] = params
        self._next_id += 1
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()

    def _send_notification(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> None:
        msg: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        assert self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(msg) + "\n")
        self._proc.stdin.flush()

    def _recv(self, timeout_s: float = PER_REP_TIMEOUT_S) -> Dict[str, Any]:
        """Read one JSON-RPC message from stdout. Skips notifications."""
        assert self._proc.stdout is not None
        # Best-effort timeout: subprocess.Popen has no per-line timeout, so
        # we rely on the caller's overall budget.
        deadline = time.monotonic() + timeout_s
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("MCP server response timed out")
            line = self._proc.stdout.readline()
            if not line:
                raise RuntimeError("MCP server stdout closed unexpectedly")
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Skip notifications (no "id")
            if "id" not in parsed:
                continue
            return parsed  # type: ignore[no-any-return]

    def initialize(self) -> None:
        """Run the MCP handshake: initialize + initialized notification."""
        self._send(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "dispatch-eval-runner", "version": "1.0"},
            },
        )
        self._recv()
        self._send_notification("notifications/initialized")

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return the server's tool list as a list of MCP tool spec dicts."""
        self._send("tools/list")
        resp = self._recv()
        return list(resp.get("result", {}).get("tools", []))

    def call_tool(
        self, name: str, arguments: Dict[str, Any], timeout_s: float = PER_REP_TIMEOUT_S
    ) -> Dict[str, Any]:
        """Invoke a tool by name. Returns the raw JSON-RPC result.

        Best-effort wrapper; callers must check for ``error`` keys themselves.
        """
        self._send("tools/call", {"name": name, "arguments": arguments})
        return self._recv(timeout_s=timeout_s)

    def close(self) -> None:
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=5)
        except Exception:
            pass


def _build_server_env(variant: str, mode: str) -> Dict[str, str]:
    """Return the env-var overlay for an MCP server subprocess.

    - b13: empty overlay; the working tree's surface is whatever's at HEAD.
    - phase-f: OZM_PHASE_F_PROTOTYPE=1, OZM_TOOL_MODE=<mode>.
    - phase-f-fallback: + OZM_CRITERION_C_PATH=fallback.
    """
    env = os.environ.copy()
    if variant == "phase-f":
        env["OZM_PHASE_F_PROTOTYPE"] = "1"
        env["OZM_TOOL_MODE"] = mode
    elif variant == "phase-f-fallback":
        env["OZM_PHASE_F_PROTOTYPE"] = "1"
        env["OZM_TOOL_MODE"] = mode
        env["OZM_CRITERION_C_PATH"] = "fallback"
    # b13: no overlay — operator must invoke from a v2.0.0b13 worktree, the
    # surface there is the default. We still pass the requested mode so the
    # b13 server boots in the right tool set.
    env["OPENZIM_MCP_TOOL_MODE"] = mode
    return env


def _resolve_zim_dir() -> str:
    """Return the ZIM directory used by the spawned MCP server.

    Honors ``OZM_DISPATCH_ZIM_DIR`` if set; otherwise falls back to a
    placeholder that lets the server boot — entry-path resolution requires
    a real archive, so the operator MUST set this var when running for
    Criterion C / D scoring.
    """
    explicit = os.environ.get("OZM_DISPATCH_ZIM_DIR")
    if explicit:
        return explicit
    # Boot-time-only fallback; tools that touch real archives will return
    # empty results.
    return os.environ.get("OZM_DISPATCH_ZIM_DIR_FALLBACK", "/tmp")


def _spawn_mcp_server(variant: str, mode: str) -> subprocess.Popen:
    """Spawn an openzim-mcp server subprocess in stdio transport mode."""
    env = _build_server_env(variant, mode)
    zim_dir = _resolve_zim_dir()
    cmd = [
        sys.executable,
        "-m",
        "openzim_mcp",
        "--mode",
        mode,
        "--transport",
        "stdio",
        zim_dir,
    ]
    return subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
        text=True,
        bufsize=1,
    )


# --------------------------------------------------------------------------
# Tool-list → OpenAI / Anthropic spec converters
# --------------------------------------------------------------------------


def _mcp_to_openai_tool_specs(
    mcp_tools: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Translate ``tools/list`` MCP tool dicts to OpenAI tool spec dicts."""
    out: List[Dict[str, Any]] = []
    for t in mcp_tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.get("name", ""),
                    "description": t.get("description", ""),
                    "parameters": t.get("inputSchema", {"type": "object"}),
                },
            }
        )
    return out


def _mcp_to_anthropic_tool_specs(
    mcp_tools: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Translate ``tools/list`` MCP tool dicts to Anthropic tool spec dicts."""
    out: List[Dict[str, Any]] = []
    for t in mcp_tools:
        out.append(
            {
                "name": t.get("name", ""),
                "description": t.get("description", ""),
                "input_schema": t.get("inputSchema", {"type": "object"}),
            }
        )
    return out


# --------------------------------------------------------------------------
# Model call wrappers
# --------------------------------------------------------------------------


def _http_post_json(
    url: str, payload: Dict[str, Any], timeout_s: float
) -> Dict[str, Any]:
    """POST JSON to ``url`` and return the parsed response. Stdlib only."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        result: Dict[str, Any] = json.loads(resp.read().decode("utf-8"))
        return result


def _probe_openai_compatible_endpoint(endpoint: str) -> None:
    """Fail-fast: hit /models on an OpenAI-compatible endpoint."""
    try:
        with urllib.request.urlopen(f"{endpoint}/models", timeout=5) as resp:
            json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        raise SystemExit(
            f"OpenAI-compatible endpoint at {endpoint} unreachable: {e}. "
            "Start the vLLM server with the right --tool-call-parser before "
            "running the dispatch eval."
        ) from e


def _call_openai_compatible(
    adapter: ModelAdapter,
    system_prompt: str,
    query: str,
    tools: List[Dict[str, Any]],
    timeout_s: float,
) -> Tuple[Optional[str], Dict[str, Any], Dict[str, Any]]:
    """One chat completion + tool call. Returns (name, args, raw_response)."""
    assert adapter.endpoint is not None
    payload = {
        "model": adapter.vendor_id,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ],
        "tools": tools,
        "tool_choice": "auto",
        "temperature": DEFAULT_TEMPERATURE,
    }
    response = _http_post_json(
        f"{adapter.endpoint}/chat/completions", payload, timeout_s
    )
    name, args = _parse_openai_compatible_tool_call(response)
    return name, args, response


def _call_anthropic(
    adapter: ModelAdapter,
    system_prompt: str,
    query: str,
    tools: List[Dict[str, Any]],
    timeout_s: float,
) -> Tuple[Optional[str], Dict[str, Any], Dict[str, Any]]:
    """One Anthropic message call. Returns (name, args, raw_response_dict)."""
    try:
        import anthropic  # type: ignore
    except ImportError as e:
        raise SystemExit(
            "The anthropic SDK is required for --model haiku-*/claude-*. "
            "Install it with: pip install anthropic"
        ) from e
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY env var must be set for --model haiku-*/claude-*."
        )
    client = anthropic.Anthropic(timeout=timeout_s)
    msg = client.messages.create(
        model=adapter.vendor_id,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": query}],
        tools=tools,
        temperature=DEFAULT_TEMPERATURE,
    )
    name, args = _parse_anthropic_tool_call(msg.content)
    # Flatten the message to a JSON-serializable dict for the outcome row.
    raw = {
        "id": getattr(msg, "id", None),
        "model": getattr(msg, "model", None),
        "stop_reason": getattr(msg, "stop_reason", None),
        "content": [
            (
                {"type": getattr(b, "type", None), "text": getattr(b, "text", None)}
                if getattr(b, "type", None) == "text"
                else {
                    "type": "tool_use",
                    "name": getattr(b, "name", None),
                    "input": getattr(b, "input", None),
                }
            )
            for b in (msg.content or [])
        ],
    }
    return name, args, raw


def _call_model(
    adapter: ModelAdapter,
    system_prompt: str,
    query: str,
    openai_tools: List[Dict[str, Any]],
    anthropic_tools: List[Dict[str, Any]],
    timeout_s: float,
) -> Tuple[Optional[str], Dict[str, Any], Dict[str, Any]]:
    """Dispatch to the right family adapter."""
    if adapter.family in ("qwen", "llama", "phi"):
        return _call_openai_compatible(
            adapter, system_prompt, query, openai_tools, timeout_s
        )
    if adapter.family == "haiku":
        return _call_anthropic(
            adapter, system_prompt, query, anthropic_tools, timeout_s
        )
    raise SystemExit(f"Unsupported model family: {adapter.family}")


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def _params_match_load_bearing(
    expected: Dict[str, Any], actual: Dict[str, Any]
) -> bool:
    """Lenient on extras, strict on the labeled load-bearing fields."""
    for k, want in expected.items():
        if k not in actual:
            return False
        got = actual[k]
        if isinstance(want, list):
            if not isinstance(got, list) or list(got) != list(want):
                return False
        elif got != want:
            return False
    return True


def _params_schema_only_valid(
    tool_name: str, args: Dict[str, Any], mcp_tools: List[Dict[str, Any]]
) -> bool:
    """Best-effort schema check.

    Lightweight: only verifies (a) the tool name exists in the server's
    listed tools, and (b) ``required`` fields are present and (c) declared
    fields whose type is ``string`` actually got a string. Full ``oneOf``
    branch validation would require a JSON Schema library; we use the
    same shallow check used by the oneof_parse benchmark.
    """
    spec = next((t for t in mcp_tools if t.get("name") == tool_name), None)
    if spec is None:
        return False
    schema = spec.get("inputSchema", {}) or {}
    required = schema.get("required", []) or []
    for r in required:
        if r not in args:
            return False
    properties = schema.get("properties", {}) or {}
    for k, v in args.items():
        if k not in properties:
            # Unknown extras are allowed.
            continue
        prop_type = properties[k].get("type")
        if isinstance(prop_type, str):
            if prop_type == "string" and not isinstance(v, str):
                return False
            if prop_type == "integer" and not isinstance(v, int):
                return False
            if prop_type == "boolean" and not isinstance(v, bool):
                return False
            if prop_type == "array" and not isinstance(v, list):
                return False
            if prop_type == "object" and not isinstance(v, dict):
                return False
    return True


def _score_parameter_validity(
    probe: Probe,
    tool_name: Optional[str],
    args: Dict[str, Any],
    mcp_tools: List[Dict[str, Any]],
) -> str:
    """Return one of {"fail", "schema_only", "load_bearing_match"}."""
    if tool_name is None:
        return "fail"
    if not _params_schema_only_valid(tool_name, args, mcp_tools):
        return "fail"
    if _params_match_load_bearing(probe.expected_parameters, args):
        return "load_bearing_match"
    return "schema_only"


def _detect_spurious_route(
    probe: Probe, tool_name: Optional[str], args: Dict[str, Any]
) -> bool:
    """Spurious route = zim_query_preferred probe answered with
    zim_search(mode='title').
    """
    if probe.tool_eligibility != "zim_query_preferred":
        return False
    if probe.expected_tool != "zim_query":
        return False
    if tool_name != "zim_search":
        return False
    return args.get("mode") == "title"


def _extract_resolved_path(call_result: Dict[str, Any]) -> Optional[str]:
    """Best-effort extraction of a single resolved entry path from a
    ``tools/call`` response.

    Many openzim-mcp responses are formatted text rather than structured
    JSON; we look for a few common shapes:
      - ``result.content[0].text`` containing a ``"path": "..."`` line
      - ``result.structuredContent.resolved_entry_path`` (explicit field)
      - ``result.content[0].text`` containing a heading like
        ``"Entry: <path>"`` or ``"Path: <path>"``

    Returns ``None`` if no path is found.
    """
    result = call_result.get("result") if isinstance(call_result, dict) else None
    if not isinstance(result, dict):
        return None
    # Structured form (some tools emit a JSON object alongside the text).
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        for key in ("resolved_entry_path", "entry_path", "path"):
            v = structured.get(key)
            if isinstance(v, str) and v:
                return v
    # Text form — scan the first text block.
    content = result.get("content") or []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if not isinstance(text, str):
            continue
        # Try a JSON parse first; many simple_tools responses are JSON-encoded
        # but transported as a text block.
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            for key in ("resolved_entry_path", "entry_path", "path"):
                v = parsed.get(key)
                if isinstance(v, str) and v:
                    return v
            entry = parsed.get("entry")
            if isinstance(entry, dict):
                for key in ("path", "entry_path"):
                    v = entry.get(key)
                    if isinstance(v, str) and v:
                        return v
        # Heuristic: look for "path": "..." or "Path: ..." or "Entry: ..."
        for needle in ('"resolved_entry_path":', '"entry_path":', '"path":'):
            i = text.find(needle)
            if i >= 0:
                tail = text[i + len(needle) :].lstrip()
                if tail.startswith('"'):
                    end = tail.find('"', 1)
                    if end > 1:
                        return tail[1:end]
    return None


def _classify_spurious_route_kind(
    probe: Probe,
    spurious_route: bool,
    resolved_entry_path: Optional[str],
) -> Optional[str]:
    """Return "answer_preserving", "answer_degrading", or None.

    Requires both ``spurious_route=True`` AND a known expected resolved path
    on the probe AND a model-reported resolved path. If any is missing,
    returns ``None`` and the caller leaves the field null.
    """
    if not spurious_route:
        return None
    if resolved_entry_path is None:
        return None
    if probe.expected_resolved_entry_path is None:
        return None
    if resolved_entry_path == probe.expected_resolved_entry_path:
        return "answer_preserving"
    return "answer_degrading"


# --------------------------------------------------------------------------
# Per-probe loop
# --------------------------------------------------------------------------


def _outcome_row(
    *,
    probe: Probe,
    rep: int,
    tool_called: Optional[str],
    parameters: Dict[str, Any],
    dispatch_correct: bool,
    parameter_validity: str,
    spurious_route: bool,
    spurious_route_kind: Optional[str],
    resolved_entry_path: Optional[str],
    raw_response: Any,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "probe_id": probe.probe_id,
        "rep": rep,
        "tool_called": tool_called,
        "parameters": parameters,
        "dispatch_correct": dispatch_correct,
        "parameter_validity": parameter_validity,
        "spurious_route": spurious_route,
        "spurious_route_kind": spurious_route_kind,
        "resolved_entry_path": resolved_entry_path,
        "raw_response": raw_response,
        "error": error,
    }


def _run_one_rep(
    *,
    probe: Probe,
    rep: int,
    adapter: ModelAdapter,
    system_prompt: str,
    client: McpStdioClient,
    mcp_tools: List[Dict[str, Any]],
    openai_tools: List[Dict[str, Any]],
    anthropic_tools: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Single probe × rep execution. Catches all errors; never raises."""
    started = time.monotonic()
    last_error: Optional[str] = None

    name: Optional[str] = None
    args: Dict[str, Any] = {}
    raw: Any = None

    for attempt in range(MAX_RETRIES):
        elapsed = time.monotonic() - started
        budget = PER_REP_TIMEOUT_S - elapsed
        if budget <= 0:
            last_error = "per-rep timeout exhausted"
            break
        try:
            name, args, raw = _call_model(
                adapter,
                system_prompt,
                probe.query,
                openai_tools,
                anthropic_tools,
                timeout_s=min(budget, PER_REP_TIMEOUT_S),
            )
            last_error = None
            break
        except SystemExit:
            raise  # operator-config issues (missing SDK / API key) propagate
        except Exception as e:  # noqa: BLE001 — defensive: many flaky paths
            last_error = f"{type(e).__name__}: {e}"
            time.sleep(0.5)

    if last_error is not None and name is None:
        return _outcome_row(
            probe=probe,
            rep=rep,
            tool_called=None,
            parameters={},
            dispatch_correct=False,
            parameter_validity="fail",
            spurious_route=False,
            spurious_route_kind=None,
            resolved_entry_path=None,
            raw_response=None,
            error=last_error,
        )

    dispatch_correct = name == probe.expected_tool
    parameter_validity = _score_parameter_validity(probe, name, args, mcp_tools)
    spurious_route = _detect_spurious_route(probe, name, args)

    # Resolution path — only attempted when the call was well-formed AND we
    # have enough budget remaining. ZIM-touching calls can be slow; we cap
    # the call timeout at the remaining per-rep budget.
    resolved_entry_path: Optional[str] = None
    if name is not None and parameter_validity != "fail":
        remaining = PER_REP_TIMEOUT_S - (time.monotonic() - started)
        if remaining > 1.0:
            try:
                call_result = client.call_tool(
                    name, args, timeout_s=min(remaining, PER_REP_TIMEOUT_S)
                )
                resolved_entry_path = _extract_resolved_path(call_result)
            except Exception:  # noqa: BLE001 — best-effort, never crash
                resolved_entry_path = None

    spurious_route_kind = _classify_spurious_route_kind(
        probe, spurious_route, resolved_entry_path
    )

    return _outcome_row(
        probe=probe,
        rep=rep,
        tool_called=name,
        parameters=args,
        dispatch_correct=dispatch_correct,
        parameter_validity=parameter_validity,
        spurious_route=spurious_route,
        spurious_route_kind=spurious_route_kind,
        resolved_entry_path=resolved_entry_path,
        raw_response=raw if raw is not None else None,
        error=last_error,
    )


# --------------------------------------------------------------------------
# Output filename
# --------------------------------------------------------------------------


def _default_output_path(variant: str, mode: str, model: str) -> Path:
    """Return the default output path under tests/dispatch_eval/runs/.

    Uses ISO 8601 UTC truncated to seconds with ':' replaced by '-' to be
    safe across filesystems.
    """
    ts = (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H-%M-%SZ")
    )
    runs_dir = Path(__file__).resolve().parent / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    return runs_dir / f"{variant}__{mode}__{model}__{ts}.jsonl"


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


@dataclass
class RunSummary:
    n_probes: int = 0
    n_reps: int = 0
    n_outcomes: int = 0
    n_dispatch_correct: int = 0
    n_load_bearing_match: int = 0
    n_spurious_route: int = 0
    n_errors: int = 0
    errors: List[str] = field(default_factory=list)


def _run(args: argparse.Namespace) -> int:
    """Execute one variant × mode × model cell. Returns shell exit code."""
    if args.variant not in VALID_VARIANTS:
        raise SystemExit(
            f"--variant must be one of {sorted(VALID_VARIANTS)}; got {args.variant!r}"
        )
    if args.mode not in VALID_MODES:
        raise SystemExit(
            f"--mode must be one of {sorted(VALID_MODES)}; got {args.mode!r}"
        )

    adapter = _build_adapter(args.model)
    if adapter.family in ("qwen", "llama", "phi"):
        _probe_openai_compatible_endpoint(adapter.endpoint or "")
    elif adapter.family == "haiku":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit(
                "ANTHROPIC_API_KEY env var must be set for --model haiku-*/claude-*."
            )

    probes_path = Path(args.probes).expanduser().resolve()
    if not probes_path.exists():
        raise SystemExit(f"Probes file not found: {probes_path}")
    probes = load_probes(probes_path)
    if not probes:
        raise SystemExit(f"No probes loaded from {probes_path}")

    if not SYSTEM_PROMPT_PATH.exists():
        raise SystemExit(f"System prompt missing at {SYSTEM_PROMPT_PATH}")
    system_prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else _default_output_path(args.variant, args.mode, args.model)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Spawn MCP server (subprocess approach — cleanest for the OZM_* env-var
    # injection per task spec). One subprocess per cell, not per probe — the
    # tool list is stable across the cell.
    print(
        f"[runner] Booting MCP server: variant={args.variant} mode={args.mode}",
        file=sys.stderr,
    )
    proc = _spawn_mcp_server(args.variant, args.mode)
    client = McpStdioClient(proc)

    summary = RunSummary(n_probes=len(probes), n_reps=args.reps)

    try:
        try:
            client.initialize()
            mcp_tools = client.list_tools()
        except Exception as e:  # noqa: BLE001
            raise SystemExit(f"MCP server initialization failed: {e}") from e
        if not mcp_tools:
            raise SystemExit("MCP server returned an empty tools list")
        openai_tools = _mcp_to_openai_tool_specs(mcp_tools)
        anthropic_tools = _mcp_to_anthropic_tool_specs(mcp_tools)

        print(
            f"[runner] Server exposes {len(mcp_tools)} tools: "
            f"{[t.get('name') for t in mcp_tools]}",
            file=sys.stderr,
        )

        with output_path.open("w", encoding="utf-8") as out:
            for probe in probes:
                for rep in range(args.reps):
                    row = _run_one_rep(
                        probe=probe,
                        rep=rep,
                        adapter=adapter,
                        system_prompt=system_prompt,
                        client=client,
                        mcp_tools=mcp_tools,
                        openai_tools=openai_tools,
                        anthropic_tools=anthropic_tools,
                    )
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    summary.n_outcomes += 1
                    if row["dispatch_correct"]:
                        summary.n_dispatch_correct += 1
                    if row["parameter_validity"] == "load_bearing_match":
                        summary.n_load_bearing_match += 1
                    if row["spurious_route"]:
                        summary.n_spurious_route += 1
                    if row["error"]:
                        summary.n_errors += 1
                        if len(summary.errors) < 10:
                            summary.errors.append(row["error"])
    finally:
        client.close()

    # Print a compact summary so operators see something at the terminal.
    print(
        json.dumps(
            {
                "output": str(output_path),
                "variant": args.variant,
                "mode": args.mode,
                "model": args.model,
                "summary": {
                    "n_probes": summary.n_probes,
                    "n_reps": summary.n_reps,
                    "n_outcomes": summary.n_outcomes,
                    "dispatch_accuracy": (
                        summary.n_dispatch_correct / summary.n_outcomes
                        if summary.n_outcomes
                        else 0.0
                    ),
                    "load_bearing_match_rate": (
                        summary.n_load_bearing_match / summary.n_outcomes
                        if summary.n_outcomes
                        else 0.0
                    ),
                    "spurious_route_count": summary.n_spurious_route,
                    "error_count": summary.n_errors,
                    "sample_errors": summary.errors,
                },
            },
            indent=2,
        )
    )
    return 0


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Gate 0b dispatch-eval runner — drives MCP server + LLM "
        "over a probe set and records per-probe outcomes.",
    )
    parser.add_argument(
        "--variant",
        required=True,
        choices=sorted(VALID_VARIANTS),
        help="Tool-surface variant under test.",
    )
    parser.add_argument(
        "--mode",
        required=True,
        choices=sorted(VALID_MODES),
        help="Tool mode (simple = zim_query only; advanced = all 8 tools).",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Model short name: qwen2.5-7b-instruct | haiku-4.5 | "
        "llama-3.1-8b-instruct | phi-3.5-mini-instruct | qwen-2.5-3b-instruct.",
    )
    parser.add_argument(
        "--reps",
        type=int,
        default=5,
        help="Repetitions per probe (default 5).",
    )
    parser.add_argument(
        "--probes",
        required=True,
        help="Path to the probes JSONL file.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output JSONL path. Default: tests/dispatch_eval/runs/"
        "<variant>__<mode>__<model>__<timestamp>.jsonl.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
