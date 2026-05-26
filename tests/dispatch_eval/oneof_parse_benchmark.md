# Gate 0.3 — small-model `oneOf` parsing benchmark (against prototype skeletons)

**Date run:** `<TO FILL IN AT RUN TIME>`
**Model:** Qwen-2.5-7B-Instruct
**Probe count:** 100
**Reps per probe:** 5
**Source schemas:** prototype skeletons at `<PROTOTYPE_COMMIT_SHA>` on
  `v2-phase-f-prototype`

## What this measures

Two variants of the same target tools (`zim_get` + `zim_search`):

- **oneof_variant** — wired Pattern B `oneOf` schemas, imported byte-identical
  from `tests/dispatch_eval/prototype_schema_snapshot.json`. This is the
  surface rc1 would ship if Gate 0b passes.
- **flat_variant** — equivalent flat schemas where every parameter is
  `Optional[...]` and per-branch conditionals are described in prose only.
  Throwaway shape that exists ONLY for the A/B comparison.

Each variant runs all 100 probes × 5 reps against the same Qwen-2.5-7B-Instruct
endpoint at temperature=0.2 with `tool_choice="auto"`. Per-probe outcome
records:

- Did the model call the right tool?
- Did the model construct an argument shape whose branch discriminator
  (the `mode` value for `zim_search`, or the {`main_page`, `binary`,
  `entry_paths`, `entry_path`} combination for `zim_get`) matches the gold
  label?
- Do the load-bearing parameter fields match the gold label?

## Probe composition

- **30 zim_search probes** — 10 per branch (`fulltext`, `title`, `suggest`).
- **70 zim_get probes** — 30 single-entry-body across 4 views (`full`/
  `summary`/`toc`/`structure`), 10 single-entry-binary, 15 batch, 15 main-page.

See `oneof_parse_benchmark.jsonl` for the full set.

## Results

| Metric | oneof_variant | flat_variant | Delta (pp) | 1-sided z-test p-value (α=0.05) |
| --- | --- | --- | --- | --- |
| Branch-selection accuracy | `<TO FILL IN>` | `<TO FILL IN>` | `<TO FILL IN>` | `<TO FILL IN>` |
| Parameter-validity rate | `<TO FILL IN>` | `<TO FILL IN>` | `<TO FILL IN>` | `<TO FILL IN>` |

Per-branch breakdowns (from `out.json`):

```
<TO FILL IN — paste the per_branch sub-dicts from the script's stdout>
```

## Verdict

`<TO RUN>` — choose one of:

- **PROCEED-AS-DESIGNED-VALIDATED** — `oneof_variant` wins by ≥7pp absolute
  on either metric. The schema design is empirically supported on the target
  population.
- **PROCEED-AS-DESIGNED-UNVALIDATED** — the two variants are statistically
  indistinguishable (delta < 7pp absolute on both metrics). Surface design
  proceeds (transport works, byte cost is acceptable), but the small-model
  benefit is unmeasured. Gate 0b still runs against the wired variant.
- **STOP-AMEND-SPEC (ONEOF-DOWNGRADES-DISPATCH)** — `oneof_variant` loses by
  ≥7pp absolute on either metric. Open the spec amendment to flat schemas.
  Re-author Task B2 skeletons with flat parameter signatures, re-snapshot in
  Task B2 Step 6, and commit. Gate 0b's prototype is then the flat variant;
  the wired-`oneOf` path is dropped entirely.

## How to run

```bash
# Boot vLLM on the deployer's GPU. Single GPU is fine.
python -m vllm.entrypoints.openai.api_server \
  --model Qwen/Qwen2.5-7B-Instruct \
  --tool-call-parser hermes \
  --enable-auto-tool-choice &

# Wait for ready (curl http://localhost:8000/v1/models should succeed), then:
python tests/dispatch_eval/oneof_parse_benchmark.py | tee /tmp/oneof_parse.json
```

If the vLLM endpoint at `http://localhost:8000/v1` is unreachable, the script
exits with status 2 and prints a JSON envelope including a hint command to
start vLLM. Set `OZM_VLLM_BASE_URL` to override the endpoint.

Other override knobs (env vars):

- `OZM_VLLM_MODEL` — model name (default `Qwen/Qwen2.5-7B-Instruct`).
- `OZM_BENCHMARK_TEMPERATURE` — sampling temperature (default `0.2`).
- `OZM_BENCHMARK_REPS` — reps per probe (default `5`).
- `OZM_BENCHMARK_TIMEOUT_S` — per-request timeout (default `60`).

The script's stdout is a JSON document; pipe it to a file and paste the
relevant numbers into this template at run time.
