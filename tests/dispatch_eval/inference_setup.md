# Inference setup (Gate 0b)

This document covers booting the four inference targets that drive the Gate
0b dispatch evaluation: **Qwen-2.5-7B-Instruct** (primary), **Haiku-4.5**
(secondary), **Llama-3.1-8B-Instruct** (tertiary), and **Phi-3.5-mini-instruct**
(quaternary). Per the spec's §Gate 0b multi-model coverage rule, the primary
runs all four cells (b13 × {simple, advanced} and phase-f × {simple, advanced})
plus the optional fallback cell; the three secondaries each run two cells
(`phase-f × advanced` for the Criterion D load-bearing comparison, and
`b13 × advanced` for the cross-validation baseline) plus the optional
fallback cell if Criterion C fails.

A model that is unavailable in a given run gets recorded in
`gate_0b_decision.json` (e.g. `secondary_status: "unavailable"`); it is a
**documented decision**, not a silent skip.

## Per-model tool-call parser table

Different model families emit tool-call payloads in different formats. The
Task B4 runner (`tests/dispatch_eval/runner.py`) dispatches by `--model`
flag to the right parser. Missing the parser produces a wiring bug that
*looks* like a model regression (every probe reports parameter-validity
failure) but is in fact a runner-side fix.

| `--model` prefix | Tool-call format | vLLM `--tool-call-parser` | Notes |
| --- | --- | --- | --- |
| `qwen*` | Hermes JSON | `hermes` | Default for Qwen-2.5-7B primary AND for Qwen-2.5-3B if used as the quaternary substitute. |
| `llama-3*` | Llama 3 JSON | `llama3_json` | Required for the Llama-3.1-8B tertiary; missing this maps every Llama tool call to malformed-JSON and reports 100% parameter-validity failure that looks like a Llama regression but is a wiring bug. |
| `phi-3.5*` | Python-flavored | `pythonic` (vLLM >= 0.6.2) | Required for the Phi-3.5-mini quaternary. Same wiring-bug risk: missing parser -> reports as a Phi regression. If `pythonic` is broken in the deployer's vLLM, substitute Qwen-2.5-3B (covered by the `qwen*` row) and record the substitution in `gate_0b_decision.json`. |
| `haiku*`, `claude*` | Anthropic SDK `tool_use` block | n/a (Anthropic SDK) | Native parsed JSON from the SDK; no extra adapter needed. |

## Primary: Qwen-2.5-7B-Instruct (100% of cells)

Local inference via vLLM (preferred) or llama.cpp.

```bash
# vLLM single-GPU
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct \
  --tool-call-parser hermes \
  --enable-auto-tool-choice \
  --port 8000
```

Runner connects via OpenAI-compatible API at `http://localhost:8000/v1`.

**Cells run by Qwen:** all 4 defaults plus the conditional fallback.

- `b13 × simple` (baseline)
- `b13 × advanced` (baseline)
- `phase-f × simple` (variant)
- `phase-f × advanced` (variant — the cell Criterion D primarily compares)
- `phase-f-fallback × advanced` (conditional — only if Criterion C fails on the wired run)

## Secondary: Haiku-4.5 (50% of cells)

Anthropic-family cross-validation. Hosted (no local GPU needed):

```bash
export ANTHROPIC_API_KEY=<key>
# runner picks haiku-4.5 via --model claude-haiku-4-5-20251001
```

The runner uses the Anthropic SDK with model ID
`claude-haiku-4-5-20251001`. Tool-call payloads arrive as parsed
`tool_use` content blocks; no extra parser dispatch is required.

**Cells run by Haiku:**

- `b13 × advanced`
- `phase-f × advanced`
- `phase-f-fallback × advanced` (conditional)

Haiku is skipped on the `simple` cells — the simple mode is byte-identical
to b13 surface for the prototype, so adding another model on simple does
not add cross-validation signal.

**If Haiku is unavailable** (e.g. no Anthropic credential or rate-limited
out), set `secondary_status: "unavailable"` in `gate_0b_decision.json` with
a brief justification. Gate 0b does NOT block on Haiku availability — the
primary's 4-cell Qwen run is the load-bearing data path.

## Tertiary: Llama-3.1-8B-Instruct (50% of cells)

Architecturally-distinct ~8B-class open-weights model (Meta, not Alibaba).
Mitigates the "Qwen-family overfit" risk by adding a second open-weights
family at the same size class as the primary.

**Prerequisites — license + access.** Meta's Llama 3.1 weights are gated.
Before any inference run, the operator must:

1. Accept the Llama 3.1 Community License at
   <https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct> (logged-in
   HuggingFace account required).
2. Generate a HuggingFace access token with `read` scope at
   <https://huggingface.co/settings/tokens>.
3. `export HF_TOKEN=<token>` in the shell that boots vLLM.

If the license has not been accepted, vLLM's first download attempt 403s
with a HuggingFace error — fail-fast, not a silent skip. Operators who
cannot accept the license set `tertiary_status: "unavailable"` per the
disagreement rule.

**Tool-call format.** Llama 3.1 emits tool calls in a JSON format distinct
from Qwen's hermes parser. The runner MUST dispatch by `--model` flag to the
right parser (see the per-model table above) — `hermes` for `qwen*`,
`llama3_json` for `llama-3*`. The runner's per-model adapter is small
(~20 lines) but MUST exist.

Local inference via vLLM. **Cannot share a single GPU with the Qwen server**
— vLLM workers consume the full GPU. Two options:

```bash
# Option A: Sequential runs on a single GPU
# Run Qwen cells to completion, kill the Qwen server, boot Llama:
kill $(pgrep -f Qwen2.5-7B-Instruct)
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --tool-call-parser llama3_json \
  --enable-auto-tool-choice \
  --port 8001

# Option B: Two GPUs (preferred if available)
# Boot Llama on a second GPU concurrently with Qwen on the first:
CUDA_VISIBLE_DEVICES=1 python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --tool-call-parser llama3_json \
  --enable-auto-tool-choice \
  --port 8001 &
```

Runner connects to Llama via OpenAI-compatible API at
`http://localhost:8001/v1`.

**Cells run by Llama:**

- `b13 × advanced`
- `phase-f × advanced`
- `phase-f-fallback × advanced` (conditional)

**If Llama is unavailable** (no second-GPU capacity AND insufficient time
for sequential runs, OR the license has not been accepted), set
`tertiary_status: "unavailable"` in the gate decision artifact with a
brief justification per spec §Gate 0b disagreement rule. This is a
documented decision, not a silent skip — Llama coverage is the explicit
response to the "Qwen-family overfit" risk.

## Quaternary: Phi-3.5-mini-instruct (50% of cells)

Sub-7B size class. Llama-8B covers the architecture-diversity axis at the
same size as Qwen-7B, but the sub-7B size class — where schema-handling
quality is known to fall off sharply — is the actual deployment boundary
for the "small models" claim. Phi-3.5-mini at 3.8B is the strongest
tool-using sub-4B open-weights model and ships under MIT license (no
HuggingFace gating like Llama). It also doubles as a third architecturally
distinct family (Microsoft, != Qwen, != Meta).

**Prerequisites.** None for license — Phi-3.5 is MIT-licensed and freely
pullable from HuggingFace without an access token. (Contrast with
Llama-3.1 which requires accepting the Meta license + having an
`HF_TOKEN`.)

**Tool-call format.** Phi-3.5 emits tool calls in a Python-flavored
format. vLLM exposes this via `--tool-call-parser pythonic` (requires
vLLM >= 0.6.2). The runner's `_parse_tool_call(model, raw_response)`
dispatch (see Task B4) routes `--model phi-3.5*` to the pythonic parser.

**Substitution fallback if `pythonic` parser is broken.** vLLM tool-call
parsing for Phi has had rough edges in older versions. If the deployer's
vLLM version doesn't cleanly produce structured tool calls from Phi-3.5
(manifest: every probe returns 100% parameter-validity failure with
parser-error reasons), substitute **Qwen-2.5-3B-Instruct** instead:

```bash
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-3B-Instruct \
  --tool-call-parser hermes \
  --enable-auto-tool-choice \
  --port 8002
```

Qwen-3B uses the same `hermes` parser as the Qwen-7B primary, so the
runner adapter table doesn't need a new branch. The substitution costs
the architecture-diversity-at-small-size signal but preserves the size
signal. Record the substitution in `gate_0b_decision.json` under
`quaternary_model_substituted: "qwen-2.5-3b-instruct"`.

**Boot Phi (preferred):**

```bash
# Phi-3.5-mini is small enough to share a single GPU with Qwen-7B on
# >=24GB VRAM IF vLLM is configured with gpu_memory_utilization tuned.
# Easier path: sequential runs (kill Qwen first), or third GPU.
python -m vllm.entrypoints.openai.api_server \
  --model microsoft/Phi-3.5-mini-instruct \
  --tool-call-parser pythonic \
  --enable-auto-tool-choice \
  --port 8002
```

Runner connects to Phi via OpenAI-compatible API at
`http://localhost:8002/v1`.

**Cells run by Phi:**

- `b13 × advanced`
- `phase-f × advanced`
- `phase-f-fallback × advanced` (conditional). The sub-7B size class is
  part of the "small model" the spec claims to support, so Z4 C3/C2/C1
  re-checks include Phi.

**If Phi is unavailable** (no GPU capacity AND no time for sequential runs
AND substitution refused), set `quaternary_status: "unavailable"` per
spec §Gate 0b disagreement rule. Same documented-decision discipline as
Llama: this is the response to the sub-7B-size blind spot, and going
without it surfaces the limitation in the decision artifact rather than
burying it.

## Cell coverage matrix

| Model | b13 × simple | b13 × advanced | phase-f × simple | phase-f × advanced | phase-f-fallback × advanced (conditional) |
| --- | --- | --- | --- | --- | --- |
| Qwen-2.5-7B (primary) | YES | YES | YES | YES | YES (if Criterion C fails) |
| Haiku-4.5 (secondary) | no | YES | no | YES | YES (if Criterion C fails) |
| Llama-3.1-8B (tertiary) | no | YES | no | YES | YES (if Criterion C fails) |
| Phi-3.5-mini (quaternary) | no | YES | no | YES | YES (if Criterion C fails) |

- Qwen runs ALL 4 default cells + 1 conditional fallback = 5 cells.
- Haiku / Llama / Phi each run 2 of 4 default cells + 1 conditional
  fallback = 3 cells each.

Total maximum cell runs (all four models available, Criterion C fails):
5 + 3 + 3 + 3 = 14 cells.

Minimum cell runs (only Qwen available, Criterion C passes): 4 cells.

## Per-rep configuration

The runner defaults to `--reps 5`. At ~512 probes per cell, that yields
2560 effective observations per Qwen cell — enough for non-inferiority
tests at the 5pp margin per the spec's primary-margin sample-size
calculation. Haiku/Llama/Phi run the same `--reps 5` over their respective
cells.

## Quick boot sequence

For a clean two-GPU box (Qwen on GPU 0, Llama on GPU 1) running all four
models with Phi via substitute:

```bash
# Terminal 1 — Qwen primary
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct \
  --tool-call-parser hermes --enable-auto-tool-choice --port 8000

# Terminal 2 — Llama tertiary (separate GPU)
CUDA_VISIBLE_DEVICES=1 python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.1-8B-Instruct \
  --tool-call-parser llama3_json --enable-auto-tool-choice --port 8001

# Terminal 3 — Phi quaternary (sequential after Qwen if shared GPU,
# or third GPU if available)
python -m vllm.entrypoints.openai.api_server \
  --model microsoft/Phi-3.5-mini-instruct \
  --tool-call-parser pythonic --enable-auto-tool-choice --port 8002

# Haiku — no local server, just export ANTHROPIC_API_KEY in the runner's env

# Terminal 4 — runner (will dispatch to the right endpoint per --model)
python tests/dispatch_eval/runner.py --variant b13 --mode advanced \
  --model qwen2.5-7b-instruct --reps 5 \
  --probes tests/dispatch_eval/probes.jsonl \
  --output tests/dispatch_eval/runs/b13__advanced__qwen.jsonl
```
