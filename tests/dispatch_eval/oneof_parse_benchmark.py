"""Gate 0.3 — small-model `oneOf`-parsing benchmark against prototype skeletons.

Imports the prototype `zim_get` and `zim_search` schemas via
``OZM_PHASE_F_PROTOTYPE=1`` (the **oneof_variant**), constructs an equivalent
**flat_variant** locally (no `oneOf`, conditionals as prose only), then drives
both against a vLLM-hosted Qwen-2.5-7B-Instruct OpenAI-compatible endpoint at
``http://localhost:8000/v1`` for 5 reps × 100 probes per variant.

Per-probe outcome: tool_called, branch_selected, parameter_validity.
Emits final JSON to stdout with branch-selection accuracy + parameter-validity
per variant and a one-sided two-proportion z-test verdict.

USAGE (Cameron runs this; this module only builds the harness):

    python -m vllm.entrypoints.openai.api_server \\
        --model Qwen/Qwen2.5-7B-Instruct \\
        --tool-call-parser hermes \\
        --enable-auto-tool-choice &
    # wait for ready (curl http://localhost:8000/v1/models)
    python tests/dispatch_eval/oneof_parse_benchmark.py | tee /tmp/oneof_parse.json

Fails fast with a clear "vLLM not running" message if the endpoint is
unreachable.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Module-level configuration knobs. Override via env vars for ad-hoc tweaking.
VLLM_BASE_URL = os.environ.get("OZM_VLLM_BASE_URL", "http://localhost:8000/v1")
MODEL_NAME = os.environ.get("OZM_VLLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
TEMPERATURE = float(os.environ.get("OZM_BENCHMARK_TEMPERATURE", "0.2"))
REPS_PER_PROBE = int(os.environ.get("OZM_BENCHMARK_REPS", "5"))
REQUEST_TIMEOUT_S = float(os.environ.get("OZM_BENCHMARK_TIMEOUT_S", "60"))

PROBE_FILE = Path(__file__).parent / "oneof_parse_benchmark.jsonl"
PROTOTYPE_SNAPSHOT = Path(__file__).parent / "prototype_schema_snapshot.json"


# ---------------------------------------------------------------------------
# Probe loading
# ---------------------------------------------------------------------------


@dataclass
class Probe:
    probe_id: str
    query: str
    expected_tool: str
    expected_branch: str  # discriminator value (e.g., "fulltext", "body_view")
    expected_params: Dict[str, Any]


def load_probes() -> List[Probe]:
    """Read the 100-probe NL probe set from oneof_parse_benchmark.jsonl."""
    probes: List[Probe] = []
    with PROBE_FILE.open() as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            d = json.loads(raw)
            probes.append(
                Probe(
                    probe_id=d["probe_id"],
                    query=d["query"],
                    expected_tool=d["expected_tool"],
                    expected_branch=d["expected_branch"],
                    expected_params=d.get("expected_params", {}),
                )
            )
    return probes


# ---------------------------------------------------------------------------
# Variant schemas
# ---------------------------------------------------------------------------


def load_oneof_variant_schemas() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Load the prototype's oneOf-wired schemas for zim_get + zim_search.

    Reads the snapshot committed in Task B2 Step 6 — so the script does not
    need to import the openzim_mcp package and can be vendored anywhere.
    """
    if not PROTOTYPE_SNAPSHOT.exists():
        raise SystemExit(
            f"Prototype schema snapshot not found at {PROTOTYPE_SNAPSHOT}. "
            "Re-run Task B2 Step 6 to regenerate it on the prototype branch."
        )
    snapshot = json.loads(PROTOTYPE_SNAPSHOT.read_text())
    return snapshot["zim_search"], snapshot["zim_get"]


def build_flat_variant_schemas() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Construct a flat-schema equivalent of zim_get + zim_search.

    `Optional[...]` parameters at the top level, mode/branch conditionals
    described in prose only. Not committed to production — throwaway shape
    that exists ONLY to A/B against the wired-oneOf variant.
    """
    zim_search_flat = {
        "description": (
            "Search a ZIM archive (full-text, title lookup, or prefix-suggest). "
            "Flat schema: every parameter is optional and conditionals are "
            "encoded in prose, not in the schema.\n\n"
            "Parameters:\n"
            "  query (str, required) — search query term.\n"
            "  mode (str: 'fulltext' | 'title' | 'suggest', default 'fulltext').\n"
            "  zim_file_path (str, optional) — path to a specific archive. "
            "Mutually exclusive with cross_file=True.\n"
            "  cross_file (bool, default False) — fan out across loaded archives. "
            "Allowed only when mode='fulltext' or mode='title'.\n"
            "  namespace (str, optional) — namespace filter. Allowed ONLY when "
            "mode='fulltext'.\n"
            "  content_type (str, optional) — content-type filter. Allowed ONLY "
            "when mode='fulltext'.\n"
            "  limit (int, optional), offset (int, default 0), cursor (str, "
            "optional).\n\n"
            "INVARIANTS (caller enforces; schema does not):\n"
            "  - namespace and content_type apply only to mode='fulltext'.\n"
            "  - cross_file=True is forbidden with mode='suggest'.\n"
            "  - cross_file=True is forbidden with non-null zim_file_path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["fulltext", "title", "suggest"],
                    "default": "fulltext",
                },
                "zim_file_path": {"type": ["string", "null"], "default": None},
                "cross_file": {"type": "boolean", "default": False},
                "namespace": {"type": ["string", "null"], "default": None},
                "content_type": {"type": ["string", "null"], "default": None},
                "limit": {"type": ["integer", "null"], "default": None},
                "offset": {"type": "integer", "default": 0},
                "cursor": {"type": ["string", "null"], "default": None},
            },
            "required": ["query"],
        },
    }
    zim_get_flat = {
        "description": (
            "Retrieve one or more entries from a ZIM archive. Flat schema: "
            "every parameter is optional and the four call shapes are encoded "
            "in prose, not in the schema.\n\n"
            "Call shapes (caller picks one):\n"
            "  1. Single-entry body view — set entry_path AND view ∈ "
            "{'full','summary','toc','structure'}. Do not set entry_paths, "
            "binary=True, or main_page=True.\n"
            "  2. Single-entry binary — set entry_path AND binary=True. view "
            "is ignored. Do not set entry_paths or main_page=True.\n"
            "  3. Batch — set entry_paths (up to 50) AND view. Do not set "
            "entry_path, binary=True, or main_page=True.\n"
            "  4. Main page — set main_page=True. Do not set entry_path, "
            "entry_paths, or binary=True.\n\n"
            "Parameters:\n"
            "  zim_file_path (str, required).\n"
            "  entry_path (str, optional).\n"
            "  entry_paths (list[str], optional).\n"
            "  view (str: 'full' | 'summary' | 'toc' | 'structure', default 'full').\n"
            "  binary (bool, default False).\n"
            "  main_page (bool, default False).\n"
            "  max_content_length (int, optional), content_offset (int, "
            "default 0), compact (bool, default False), compact_budget (str|int, "
            "optional)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "zim_file_path": {"type": "string"},
                "entry_path": {"type": ["string", "null"], "default": None},
                "entry_paths": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "default": None,
                },
                "view": {
                    "type": "string",
                    "enum": ["full", "summary", "toc", "structure"],
                    "default": "full",
                },
                "binary": {"type": "boolean", "default": False},
                "main_page": {"type": "boolean", "default": False},
                "max_content_length": {"type": ["integer", "null"], "default": None},
                "content_offset": {"type": "integer", "default": 0},
                "compact": {"type": "boolean", "default": False},
                "compact_budget": {
                    "type": ["string", "integer", "null"],
                    "default": None,
                },
            },
            "required": ["zim_file_path"],
        },
    }
    return zim_search_flat, zim_get_flat


def build_tool_specs(variant: str) -> List[Dict[str, Any]]:
    """Return the list of OpenAI-style tool specs for one variant.

    `variant` ∈ {"oneof", "flat"}.
    """
    if variant == "oneof":
        zim_search, zim_get = load_oneof_variant_schemas()
        return [
            {
                "type": "function",
                "function": {
                    "name": "zim_search",
                    "description": zim_search["description"],
                    "parameters": zim_search["inputSchema"],
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "zim_get",
                    "description": zim_get["description"],
                    "parameters": zim_get["inputSchema"],
                },
            },
        ]
    if variant == "flat":
        zim_search_flat, zim_get_flat = build_flat_variant_schemas()
        return [
            {
                "type": "function",
                "function": {
                    "name": "zim_search",
                    "description": zim_search_flat["description"],
                    "parameters": zim_search_flat["inputSchema"],
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "zim_get",
                    "description": zim_get_flat["description"],
                    "parameters": zim_get_flat["inputSchema"],
                },
            },
        ]
    raise ValueError(f"Unknown variant: {variant!r}")


# ---------------------------------------------------------------------------
# Branch detection — same logic across both variants
# ---------------------------------------------------------------------------


def classify_branch(tool_name: str, args: Dict[str, Any]) -> Optional[str]:
    """Map a tool-call's (name, args) to the same discriminator labels the
    probes use (`fulltext`, `title`, `suggest`, `body_view`, `binary`,
    `batch`, `main_page`). Returns None if the call is malformed.
    """
    if tool_name == "zim_search":
        mode = args.get("mode", "fulltext")
        if mode in ("fulltext", "title", "suggest"):
            return mode
        return None
    if tool_name == "zim_get":
        if args.get("main_page") is True:
            return "main_page"
        if args.get("binary") is True:
            return "binary"
        if args.get("entry_paths"):
            return "batch"
        if args.get("entry_path"):
            return "body_view"
        return None
    return None


def params_match(probe: Probe, args: Dict[str, Any]) -> bool:
    """Strict-match the probe's load-bearing parameter fields against args.

    Lenient on extras (the model may include extra parameters); strict on
    the expected values for the labeled fields.
    """
    for k, want in probe.expected_params.items():
        if k not in args:
            return False
        got = args[k]
        if isinstance(want, list):
            if not isinstance(got, list) or list(got) != list(want):
                return False
        elif got != want:
            return False
    return True


# ---------------------------------------------------------------------------
# vLLM client (OpenAI Chat Completions API)
# ---------------------------------------------------------------------------


def _http_post_json(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST JSON to ``url`` and return the parsed response.

    Uses only the standard library to keep the script dependency-free —
    Cameron's vLLM box may not have ``httpx`` available.
    """
    import urllib.error
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"vLLM endpoint at {VLLM_BASE_URL} unreachable: {e}") from e


def _probe_vllm_alive() -> None:
    """Fail-fast probe — verifies vLLM is up before launching 1000 inferences.

    Hits ``/models``; if anything fails, prints a clear "vLLM not running"
    message and exits with code 2. Cameron sees this and starts the server.
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{VLLM_BASE_URL}/models", timeout=5) as resp:
            json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(
            json.dumps(
                {
                    "status": "vllm_not_running",
                    "endpoint": VLLM_BASE_URL,
                    "error": str(e),
                    "hint": (
                        "Start vLLM with: python -m vllm.entrypoints.openai.api_server "
                        f"--model {MODEL_NAME} --tool-call-parser hermes "
                        "--enable-auto-tool-choice"
                    ),
                },
                indent=2,
            )
        )
        sys.exit(2)


def call_model(
    query: str, tools: List[Dict[str, Any]]
) -> Tuple[Optional[str], Dict[str, Any], Dict[str, Any]]:
    """Send one chat completion + tool-call request. Returns (tool_name,
    args, raw_response)."""
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a tool-using assistant. Pick the correct tool "
                    "and supply parameters that match the user's request "
                    "exactly. Prefer the most specific tool shape."
                ),
            },
            {"role": "user", "content": query},
        ],
        "tools": tools,
        "tool_choice": "auto",
        "temperature": TEMPERATURE,
    }
    response = _http_post_json(f"{VLLM_BASE_URL}/chat/completions", payload)
    try:
        choices = response.get("choices", [])
        if not choices:
            return None, {}, response
        msg = choices[0].get("message", {})
        tool_calls = msg.get("tool_calls", []) or []
        if not tool_calls:
            return None, {}, response
        fn = tool_calls[0].get("function", {})
        name = fn.get("name")
        arg_str = fn.get("arguments", "{}")
        try:
            args = json.loads(arg_str) if isinstance(arg_str, str) else dict(arg_str)
        except json.JSONDecodeError:
            args = {}
        return name, args, response
    except (KeyError, IndexError, TypeError):
        return None, {}, response


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------


@dataclass
class VariantResults:
    variant: str
    n_total: int = 0  # probe × rep events
    branch_correct: int = 0  # tool ✓ AND branch ✓
    params_valid: int = 0  # branch_correct AND param fields match
    per_branch: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def record(self, probe: Probe, ok_branch: bool, ok_params: bool) -> None:
        self.n_total += 1
        if ok_branch:
            self.branch_correct += 1
        if ok_params:
            self.params_valid += 1
        key = f"{probe.expected_tool}:{probe.expected_branch}"
        slot = self.per_branch.setdefault(
            key, {"n": 0, "branch_correct": 0, "params_valid": 0}
        )
        slot["n"] += 1
        if ok_branch:
            slot["branch_correct"] += 1
        if ok_params:
            slot["params_valid"] += 1


def run_variant(variant: str, probes: List[Probe]) -> VariantResults:
    """Run all probes × reps against one variant. Returns aggregated counters."""
    tools = build_tool_specs(variant)
    results = VariantResults(variant=variant)
    for probe in probes:
        for _rep in range(REPS_PER_PROBE):
            name, args, _raw = call_model(probe.query, tools)
            branch = classify_branch(name or "", args)
            ok_branch = name == probe.expected_tool and branch == probe.expected_branch
            ok_params = ok_branch and params_match(probe, args)
            results.record(probe, ok_branch, ok_params)
    return results


# ---------------------------------------------------------------------------
# Verdict — one-sided 2-proportion z-test at α=0.05
# ---------------------------------------------------------------------------


def z_test_one_sided(p1: float, p2: float, n1: int, n2: int) -> float:
    """Return one-sided p-value testing H0: p1 <= p2 vs H1: p1 > p2.

    Uses the pooled-proportion z-statistic with the standard-normal CDF.
    """
    if n1 == 0 or n2 == 0:
        return float("nan")
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    var = p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)
    if var <= 0:
        return float("nan") if p1 == p2 else 0.0
    z = (p1 - p2) / math.sqrt(var)
    # 1 - Phi(z), Phi = standard normal CDF
    return 0.5 * math.erfc(z / math.sqrt(2))


def render_verdict(oneof: VariantResults, flat: VariantResults) -> Dict[str, Any]:
    """Compose the final verdict dict (also printed as the script's stdout)."""
    p_oneof_branch = oneof.branch_correct / max(oneof.n_total, 1)
    p_flat_branch = flat.branch_correct / max(flat.n_total, 1)
    p_oneof_params = oneof.params_valid / max(oneof.n_total, 1)
    p_flat_params = flat.params_valid / max(flat.n_total, 1)

    delta_branch = p_oneof_branch - p_flat_branch
    delta_params = p_oneof_params - p_flat_params

    p_branch = z_test_one_sided(
        p_oneof_branch, p_flat_branch, oneof.n_total, flat.n_total
    )
    p_params = z_test_one_sided(
        p_oneof_params, p_flat_params, oneof.n_total, flat.n_total
    )

    # Threshold: 7pp absolute delta on either metric. Sign reads as
    # oneof_variant minus flat_variant.
    win_threshold = 0.07
    if delta_branch >= win_threshold or delta_params >= win_threshold:
        verdict = "PROCEED-AS-DESIGNED-VALIDATED"
    elif delta_branch <= -win_threshold or delta_params <= -win_threshold:
        verdict = "STOP-AMEND-SPEC (ONEOF-DOWNGRADES-DISPATCH)"
    else:
        verdict = "PROCEED-AS-DESIGNED-UNVALIDATED"

    return {
        "model": MODEL_NAME,
        "endpoint": VLLM_BASE_URL,
        "temperature": TEMPERATURE,
        "reps_per_probe": REPS_PER_PROBE,
        "probes_total": oneof.n_total // REPS_PER_PROBE,
        "oneof_variant": {
            "n_total": oneof.n_total,
            "branch_accuracy": p_oneof_branch,
            "params_validity": p_oneof_params,
            "per_branch": oneof.per_branch,
        },
        "flat_variant": {
            "n_total": flat.n_total,
            "branch_accuracy": p_flat_branch,
            "params_validity": p_flat_params,
            "per_branch": flat.per_branch,
        },
        "delta_branch_pp": delta_branch * 100,
        "delta_params_pp": delta_params * 100,
        "pvalue_branch_one_sided": p_branch,
        "pvalue_params_one_sided": p_params,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    _probe_vllm_alive()
    probes = load_probes()
    if not probes:
        print(json.dumps({"status": "no_probes", "probe_file": str(PROBE_FILE)}))
        return 2

    started = time.time()
    oneof_results = run_variant("oneof", probes)
    flat_results = run_variant("flat", probes)
    elapsed = time.time() - started

    out = render_verdict(oneof_results, flat_results)
    out["elapsed_s"] = round(elapsed, 1)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
