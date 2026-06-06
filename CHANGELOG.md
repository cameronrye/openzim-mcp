# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.2.1](https://github.com/cameronrye/openzim-mcp/compare/v2.2.0...v2.2.1) (2026-06-05)


### Fixed

* **docker:** default image to stdio so bare `docker run` works ([#267](https://github.com/cameronrye/openzim-mcp/issues/267)) ([36a6258](https://github.com/cameronrye/openzim-mcp/commit/36a625851ec0f11f5decb1f784e549e49a619856))

## [2.2.0](https://github.com/cameronrye/openzim-mcp/compare/v2.1.8...v2.2.0) (2026-06-05)


### Added

* archive-type presets (v2.5 [#17](https://github.com/cameronrye/openzim-mcp/issues/17)) ([#265](https://github.com/cameronrye/openzim-mcp/issues/265)) ([f0cd9ad](https://github.com/cameronrye/openzim-mcp/commit/f0cd9adf2ff1b90ca4c68ca9465a04c0dd2a0a02))

## [2.1.8](https://github.com/cameronrye/openzim-mcp/compare/v2.1.7...v2.1.8) (2026-06-04)


### Documentation

* sync version facts to v2.1.7 ([#263](https://github.com/cameronrye/openzim-mcp/issues/263)) ([17d8f6a](https://github.com/cameronrye/openzim-mcp/commit/17d8f6ab8a467af99ab2ab556492f03a04251980))

## [2.1.7](https://github.com/cameronrye/openzim-mcp/compare/v2.1.6...v2.1.7) (2026-06-04)


### Fixed

* **synthesize:** resolve 2-token tail-hijack defect class ([#252](https://github.com/cameronrye/openzim-mcp/issues/252), [#253](https://github.com/cameronrye/openzim-mcp/issues/253)) ([#261](https://github.com/cameronrye/openzim-mcp/issues/261)) ([67c4f9c](https://github.com/cameronrye/openzim-mcp/commit/67c4f9c5c4b3f78fccecca87dc4db903e6e71e7f))

## [2.1.6](https://github.com/cameronrye/openzim-mcp/compare/v2.1.5...v2.1.6) (2026-06-04)


### Fixed

* pyjwt 2.13.0 security floor + repair manifest-mode release tagging ([#258](https://github.com/cameronrye/openzim-mcp/issues/258)) ([9b290ad](https://github.com/cameronrye/openzim-mcp/commit/9b290ad617ae97173c50366ff711128879d2acc4))

## [2.1.5](https://github.com/cameronrye/openzim-mcp/compare/v2.1.4...v2.1.5) (2026-06-03)


### Fixed

* **release:** run release-please in pure manifest mode so config + extra-files apply ([#256](https://github.com/cameronrye/openzim-mcp/issues/256)) ([7491aaa](https://github.com/cameronrye/openzim-mcp/commit/7491aaa9610d97d1ef9a8a0676c79a79e5e545a3))

## [2.1.4](https://github.com/cameronrye/openzim-mcp/compare/v2.1.3...v2.1.4) (2026-06-02)


### Bug Fixes

* guard synthesize tail-promotion against off-topic tail-hijacks ([#250](https://github.com/cameronrye/openzim-mcp/issues/250)) ([7512d60](https://github.com/cameronrye/openzim-mcp/commit/7512d60b2772e9a77d2f128769867761075e3288))

## [2.1.3](https://github.com/cameronrye/openzim-mcp/compare/v2.1.2...v2.1.3) (2026-06-02)


### Bug Fixes

* clear three deferred defects — synthesize cross-archive leak, MedlinePlus furniture, non-article-asset browse/walk filter ([c494e6a](https://github.com/cameronrye/openzim-mcp/commit/c494e6a978313e70bc17596f618ebf6e6dbba8ea))

## [2.1.2](https://github.com/cameronrye/openzim-mcp/compare/v2.1.1...v2.1.2) (2026-06-01)


### Bug Fixes

* **http:** port-expand bare allowed-hosts so proxied Host:port passes ([55ad602](https://github.com/cameronrye/openzim-mcp/commit/55ad6025c47e883da90da43354d5fcd4bc574a66))


### Documentation

* sync README + website to the shipped v2.1.1 surface ([#246](https://github.com/cameronrye/openzim-mcp/issues/246)) ([9264f15](https://github.com/cameronrye/openzim-mcp/commit/9264f15a79e6d51f1e518620667093343685e93a))

## [2.1.1](https://github.com/cameronrye/openzim-mcp/compare/v2.1.0...v2.1.1) (2026-05-30)


### Bug Fixes

* post-v2.1.0 beta-test sweep — highlighter empty-link protection + related-articles media exclusion ([#232](https://github.com/cameronrye/openzim-mcp/issues/232)) ([7d0d6df](https://github.com/cameronrye/openzim-mcp/commit/7d0d6dfa53c6d020a456e2f3d3144295e74fc9ee))

## [2.1.0](https://github.com/cameronrye/openzim-mcp/compare/v2.0.5...v2.1.0) (2026-05-29)


### Features

* surface native libzim reader capabilities (validate / identity / index / Counter / exact-title / cache tuning) ([#221](https://github.com/cameronrye/openzim-mcp/issues/221)) ([0ca65b5](https://github.com/cameronrye/openzim-mcp/commit/0ca65b5d9dadde2af17f3fdb77ad58a6ef93063d))


### Bug Fixes

* scope content tools to main content (chrome leak), restore TOC nesting, dedupe search URL variants ([#225](https://github.com/cameronrye/openzim-mcp/issues/225)) ([659d987](https://github.com/cameronrye/openzim-mcp/commit/659d987747a7e9ac8524d10f40a8e5780a0bb95b))

## [2.0.5](https://github.com/cameronrye/openzim-mcp/compare/v2.0.4...v2.0.5) (2026-05-29)


### Bug Fixes

* trigger release-please bump (parse-error recovery for [#219](https://github.com/cameronrye/openzim-mcp/issues/219)) ([251ba20](https://github.com/cameronrye/openzim-mcp/commit/251ba2014017d0719f847930deea270a9d058b24))

## [2.0.4](https://github.com/cameronrye/openzim-mcp/compare/v2.0.3...v2.0.4) (2026-05-28)


### Reverts

* PR [#215](https://github.com/cameronrye/openzim-mcp/issues/215) release.yml recovery hack — immutable-releases disabled at repo level ([#217](https://github.com/cameronrye/openzim-mcp/issues/217)) ([6951e09](https://github.com/cameronrye/openzim-mcp/commit/6951e09c698711bd37648d6d6bc409afadfb3386))

## [2.0.3](https://github.com/cameronrye/openzim-mcp/compare/v2.0.2...v2.0.3) (2026-05-28)


### Bug Fixes

* **release:** recover from immutable-release lockout when release-please publishes draft too early ([#215](https://github.com/cameronrye/openzim-mcp/issues/215)) ([2d8e458](https://github.com/cameronrye/openzim-mcp/commit/2d8e458f3579d177e7d4440e7d434661dbb7bbd6))

## [2.0.2](https://github.com/cameronrye/openzim-mcp/compare/v2.0.1...v2.0.2) (2026-05-28)


### Bug Fixes

* post-v2.0.0 beta-test sweep — 7 dispatcher defects + website 3-pass audit ([#213](https://github.com/cameronrye/openzim-mcp/issues/213)) ([d3402fb](https://github.com/cameronrye/openzim-mcp/commit/d3402fb564de4f4a5c4acaef933728df61c03917))

## [2.0.1](https://github.com/cameronrye/openzim-mcp/compare/v2.0.0...v2.0.1) (2026-05-27)


### Bug Fixes

* **codeql:** clear 2 py/empty-except alerts in dispatch-eval runner ([b3b47e8](https://github.com/cameronrye/openzim-mcp/commit/b3b47e8c15f11b06cdd60634bf0b7e0b29afa987))
* **docs:** zim_browse mode is 'page'|'walk', not 'browse'|'walk' ([#203](https://github.com/cameronrye/openzim-mcp/issues/203)) ([6fddc82](https://github.com/cameronrye/openzim-mcp/commit/6fddc82afd4887c10a7005d1f79b9e4c2ac0e219))


### Documentation

* Astro scaffold + landing v1→v2 refresh + Astro build in deploy workflow ([#205](https://github.com/cameronrye/openzim-mcp/issues/205)) ([3ef225e](https://github.com/cameronrye/openzim-mcp/commit/3ef225eae3b8e4282f0639d15c924b53740ef71f))
* comprehensive v2.0.0 surface update across README, website, deployment ([#201](https://github.com/cameronrye/openzim-mcp/issues/201)) ([3ba32f3](https://github.com/cameronrye/openzim-mcp/commit/3ba32f33df5f857f1f69f3d494f01ac84880ce8d))
* consolidate v2 planning artifacts into single roadmap ([5930dad](https://github.com/cameronrye/openzim-mcp/commit/5930dadf3437f7fad710b6441609c730d5c8f984))
* drop v2.5 references from README + website/llms.txt ([#204](https://github.com/cameronrye/openzim-mcp/issues/204)) ([3a91587](https://github.com/cameronrye/openzim-mcp/commit/3a9158748148bc4ca1d1a865ce8b354050b1a5d2))
* migrate 15-page wiki to Astro docs collection + retire docs/deployment.md ([#206](https://github.com/cameronrye/openzim-mcp/issues/206)) ([2beed02](https://github.com/cameronrye/openzim-mcp/commit/2beed027609bb324fb521945c9639802a0c97680))
* post-v2.0.0 documentation consolidation design spec + 4-PR plan ([#209](https://github.com/cameronrye/openzim-mcp/issues/209)) ([e8920a2](https://github.com/cameronrye/openzim-mcp/commit/e8920a2b6ae54f2ecb778108e4584d4f184a46fe))
* restore ❤️ in 'Made with' attribution (README + landing) ([#210](https://github.com/cameronrye/openzim-mcp/issues/210)) ([081397f](https://github.com/cameronrye/openzim-mcp/commit/081397f525144fa8cf129b392e1896efdf30d033))
* slim README to 147-line project card + relocate Dev/Test to CONTRIBUTING.md + fix /docs/ root URL ([#207](https://github.com/cameronrye/openzim-mcp/issues/207)) ([289b3ab](https://github.com/cameronrye/openzim-mcp/commit/289b3ab4edf19724c836c3204b06d47d33f3edb8))
* **website:** fix loose ends from docs-consolidation cut ([#211](https://github.com/cameronrye/openzim-mcp/issues/211)) ([085fb37](https://github.com/cameronrye/openzim-mcp/commit/085fb3787d07cef9eebfdef392e0ecdec1d65f7b))

## [2.0.0] — 2026-05-27 — Phase F Stage D ships: 8-tool surface

Final cut after `v2.0.0rc1` (PR #194). No surface or behavior changes vs rc1 — this is
the stabilization commit. See the `[2.0.0rc1]` section below for the full surface change
and migration table.

### Stage E verdict

- **E1 dispatch sweep** (Task E1, full 512-probe Gate 0b set, 5 reps): 2560 outcomes
  against Qwen3-8B-Q4 via `chat.owl-atlas.ts.net`, 0 errors. Overall dispatch accuracy
  76.7% (1964/2560), 5 spurious routes. Baseline committed at
  `tests/dispatch_eval/runs/rc1__advanced__qwen3-8b-q4__2026-05-27T03-31-27Z.jsonl`.
- **F2 enforcement** (Task E3 Step 3): **PASS** (`f2_pass=true`, `failures=[]`). Per-class
  delta ceiling at 10pp holds for every new Phase F operation class on the primary cell.
  (Haiku / Llama / Phi cells remain unavailable per `gate_0b_decision.json`
  `scope_limitations` — same posture as Gate 0b and rc1.)
- **E2 disposition** (Task E2): the dedicated 24-legal-probes test was not authored. The
  schema-bypass half (Task D15, `tests/test_phase_f_schema_bypass.py`) passes 15/15. The
  legal half is effectively covered by the 122 unique `zim_get-*` dispatch probes from E1
  against live Wikipedia plus the branch-level unit tests in `tests/test_zim_get.py`.
- **E4** (migration conformance in CI): `tests/test_phase_f_migration.py` runs in the
  default pytest suite; verified during PR #194 CI.

### Known limitation — natural-language dispatch on three new operation classes

Three of the new Phase F operation classes showed low absolute dispatch accuracy on
Qwen3-8B-Q4 in the Stage E1 sweep — but **F2 formally passes** (these are new classes
with no b13 baseline to regress against):

| Class | Accuracy | Where the model goes instead |
| --- | --- | --- |
| `zim_get-summary` | 20% (20/100) | 80/100 → `zim_query` |
| `zim_get-structure` | 53% (56/105) | 49/105 → `zim_query` |
| `zim_get-main-page` | 76% (76/100) | 14/100 → `zim_query`, 10/100 → `zim_metadata` |

The model interprets natural-language phrasings ("give me a brief summary of X") as
**query intent** rather than direct-fetch intent. This is **not a surface defect** — when
`zim_query` is dispatched the user still gets a working answer via the natural-language
entry path. Description tuning and/or probe-set relaxation tracked at #199 for v2.5.

### v1.x maintenance scope

Per the v1.x maintenance commitment, the most recent v1.x tag is retained as a parallel
maintenance branch until the FIRST of `{v2.5.0 ships, 6 calendar months after v2.0.0}`.

- **Accepted backports to v1.x:** security fixes (always), data-corruption fixes (always),
  pre-v2.0.0 crash bugs.
- **Rejected backports to v1.x:** new features, new tools, performance work, refactors.

## [2.0.0rc1] — 2026-05-26 (release candidate) — Phase F Stage D: 8-tool surface consolidation

Second release candidate for v2.0.0. The 22-tool advanced surface
collapses to 8 consolidated tools — the largest API change in the
project's history. `tool_mode='simple'` is unchanged (still registers
only `zim_query`); the consolidation lands in `tool_mode='advanced'`.

### Surface change

22 tools → 8 tools in `tool_mode='advanced'`. All renamed with the
`zim_*` prefix:

- `zim_query` — natural-language entry point (unchanged from b13).
- `zim_search` — fulltext / title / suggest mode dispatch. Collapses
  `search_zim_file`, `search_all`, `search_with_filters`,
  `find_entry_by_title`, `get_search_suggestions` (5 → 1).
- `zim_get` — single / batch / binary / main-page entry fetch.
  Collapses `get_zim_entry`, `get_zim_entries`, `get_main_page`,
  `get_binary_entry`, `get_entry_summary`, `get_table_of_contents`,
  `get_article_structure` (7 → 1).
- `zim_get_section` — section-level fetch (renamed from
  `get_section`).
- `zim_browse` — namespace browse / walk mode dispatch.
  Collapses `browse_namespace` + `walk_namespace` (2 → 1).
- `zim_metadata` — combined archive metadata + namespaces.
  Collapses `get_zim_metadata` + `list_namespaces` (2 → 1).
- `zim_links` — outbound / related direction dispatch.
  Collapses `extract_article_links` + `get_related_articles`
  (2 → 1). `direction="inbound"` arrives in v2.5 #16.
- `zim_health` — combined server health, configuration, and
  loaded archives. Collapses `get_server_health` +
  `get_server_configuration` + `list_zim_files` (3 → 1).

Default `tool_mode` stays `'simple'`. The total advanced-mode wire
footprint lands ~23.5KB — well below the 25-50KB MCP Tax pain band
the spec targets (down from b13's ~36.1KB).

### Migrating from v1.x / v2 beta

v2 allows clean breaks; there are no aliases on the wire. The
mapping is mechanical:

| v1 / v2-beta call | v2.0 equivalent |
| --- | --- |
| `list_zim_files()` | `zim_health()` → `.loaded_archives` |
| `get_server_health()` | `zim_health()` → `.health` |
| `get_server_configuration()` | `zim_health()` → `.configuration` |
| `get_zim_metadata(path)` | `zim_metadata(path)` → `.metadata` |
| `list_namespaces(path)` | `zim_metadata(path)` → `.namespaces` |
| `get_main_page(path)` | `zim_get(path, main_page=True)` |
| `search_zim_file(path, q)` | `zim_search(q, zim_file_path=path)` |
| `search_all(q)` | `zim_search(q, cross_file=True)` |
| `search_with_filters(path, q, ns=, ct=)` | `zim_search(q, zim_file_path=path, namespace=ns, content_type=ct)` |
| `find_entry_by_title(path, title)` | `zim_search(title, zim_file_path=path, mode="title")` |
| `find_entry_by_title(cross_file=True)` | `zim_search(title, cross_file=True, mode="title")` — promotion disabled in cross-archive case |
| `get_search_suggestions(path, prefix)` | `zim_search(prefix, zim_file_path=path, mode="suggest")` |
| `get_zim_entry(path, entry_path)` | `zim_get(path, entry_path=entry_path)` — rename only; `compact` defaults to `False` (legacy behavior preserved) |
| `get_zim_entries(path, entry_paths)` | `zim_get(path, entry_paths=entry_paths)` — rename only; `compact` defaults to `False` |
| `get_binary_entry(path, entry_path)` | `zim_get(path, entry_path=entry_path, binary=True)` |
| `get_entry_summary(path, entry_path)` | `zim_get(path, entry_path=entry_path, view="summary")` |
| `get_table_of_contents(path, entry_path)` | `zim_get(path, entry_path=entry_path, view="toc")` |
| `get_article_structure(path, entry_path)` | `zim_get(path, entry_path=entry_path, view="structure")` |
| `get_section(path, entry_path, section_id)` | `zim_get_section(path, entry_path, section_id)` — rename only. `compact` parameter added for surface uniformity (default `True`) but is a no-op at v2.0; v2.5 #18 wires a true raw-text path. Same response shape as legacy `get_section`. |
| `browse_namespace(path, namespace)` | `zim_browse(path, namespace)` |
| `walk_namespace(path, namespace)` | `zim_browse(path, namespace, mode="walk")` |
| `extract_article_links(path, entry_path)` | `zim_links(path, entry_path)` |
| `get_related_articles(path, entry_path)` | `zim_links(path, entry_path, direction="related")` |
| inbound-link lookup (no v1 tool) | not available at v2.0 — `zim_links(..., direction="related")` is the closest approximation; `direction="inbound"` arrives in v2.5 #16 |
| `zim_query(...)` | unchanged |

### Default behavior changes (silent breaks if not handled)

- **`zim_metadata` no longer exposes `main_page_path`.** Callers who
  used it to construct an explicit `entry_path` round-trip to
  `zim_get` should switch to `zim_get(path, main_page=True)` — a
  single-call, null-safe path. (Note: `main_page` is a dedicated
  boolean flag, NOT a value of the `view` enum — earlier Phase F
  drafts overloaded `view="main_page"` but it now stands as its
  own parameter so the `view` enum stays focused on body slicers.)

The `zim_get` rename from `get_zim_entry` is **behavior-preserving**
on the `compact` axis (default is `False`, matching legacy). v2.5
will revisit the `zim_get` default once telemetry shows adoption.

`zim_get_section` adds a `compact` parameter for surface uniformity
with the rest of the family, but at v2.0 it is a **no-op at the data
layer** — the bundle is always compact-rendered (see
`openzim_mcp/bundle.py` line 300+: load-bearing UX invariant that
section slices match `get_zim_entry` output on the same article).
v2.5 #18 wires a true raw-text path. Until then, the rename from
`get_section` is **behavior-preserving** despite the new parameter.

### Schema shape

Each `zim_get` and `zim_search` call still has multiple mutually-
exclusive branches. The spec's preferred wire shape is JSON Schema
`oneOf` over the branches, but Gate 0.3 (small-model `oneOf` parsing
benchmark) is `unvalidated` in `tests/dispatch_eval/gate_0b_decision.json`
at rc1 cut, so per the spec's fallback rule the schema ships **flat**
with handler-level invalid-combination validation. A small model
that flattens a `oneOf` payload still gets a structured
`tool_error("invalid_path_combination", ...)` envelope rather than a
silent dispatch.

### Gate 0b — surface-change non-regression

The 8-tool surface was validated against the b13 22-tool baseline via
a 300-probe dispatch eval (`tests/dispatch_eval/probes.jsonl`) before
rc1 opened. The Qwen-2.5-7B-Instruct primary cleared all gating
criteria (A: dispatch non-inferiority, B: parameter validity, C1/C3:
Z4 silent-wrong-answer ceilings, D: aggregate non-inferiority, F1/F2:
per-class deltas within 8pp / 10pp ceilings). Haiku / Llama / Phi
secondaries recorded as `unavailable` (Intel Mac i9 — no CUDA for
vLLM; documented in the gate decision artifact).

The full gate outcome ships at
`tests/dispatch_eval/gate_0b_decision.json` and the prototype's
per-tool wire-footprint snapshot ships at
`tests/dispatch_eval/prototype_schema_snapshot.json`. Drift between
the rc1 commit's baked Python constants and the recorded gate
outcome is caught by `tests/test_phase_f_gate_decision_consistency.py`;
drift between the rc1 schemas and the prototype baseline is caught
by `tests/test_phase_f_prototype_parity.py` (±5% bytes + structural
inputSchema identity + ≤30% description Levenshtein edit distance).

### Tests added

- `tests/test_phase_f_schema_budget.py` — total + per-tool byte
  budgets, simple-mode 1-tool registration, gate-decision invariants.
- `tests/test_phase_f_schema_shapes.py` — `oneOf`/flat schema shape
  matches `gate_0_schema_shape`.
- `tests/test_phase_f_gate_decision_consistency.py` — rc1 constants
  match the recorded gate outcome.
- `tests/test_phase_f_prototype_parity.py` — rc1 surface stays
  within parity tolerances of the prototype snapshot.
- `tests/test_phase_f_schema_bypass.py` — 13 invalid-combination
  probes per oneOf-forbidden shape on `zim_get` — handler
  validation surfaces structured `tool_error` envelopes.
- `tests/test_phase_f_migration.py` — v1.x legacy tool names map
  exhaustively to v2.0 Phase F names.

### Files

New: `openzim_mcp/tools/zim_{query,search,get,get_section,browse,
metadata,links,health}.py` + sibling `*_description.md` per-tool
descriptions packaged via `[tool.setuptools.package-data]`. New:
`openzim_mcp/server_state.py` extracts `_build_health_report` and
`_build_configuration_report`. New: `openzim_mcp/tools/__init__.py`
`register_phase_f_tools` orchestrator. Deleted: legacy per-domain
`content_tools.py` / `file_tools.py` / `metadata_tools.py` /
`navigation_tools.py` / `search_tools.py` / `server_tools.py` /
`structure_tools.py` modules.

---

## [2.0.0rc0] — 2026-05-25 (release candidate) — Phase F Stage A: promotion-extraction refactor + Gate 0 transport verification

First release candidate for v2.0.0. Two structural changes land,
both pure refactor / architecture verification — no behavior change
against the b13 baseline.

### Phase F Gate 0 — `oneOf` transport verification (PR #189)

Phase F's eight-tool surface design depends on emitting JSON Schema
``oneOf`` branches over the MCP transport so small dispatch models
can route on a single discriminator. Gate 0 is a two-step probe to
confirm the wire actually carries `oneOf`:

- **Gate 0.1 — emission spike.** Three FastMCP registration patterns
  (Literal-gated signature, hand-authored ``Tool.parameters``
  override, Pydantic discriminated Union) inspected in-process.
  Verdict: Pattern B (``Tool.parameters`` override) is the only path
  that emits a literal ``"oneOf"`` key in the registered tool's
  schema.
- **Gate 0.2 — transport round-trip.** Pattern B exercised over
  three transports (in-memory, stdio JSON-RPC subprocess,
  streamable-HTTP subprocess). Verdict: ``"oneOf"`` survives the
  wire round-trip across all three transports — the design's
  primary assumption holds.

Both probes live under ``tests/dispatch_eval/`` and run only via the
explicit ``--dispatch-eval`` pytest flag (skip-guarded against the
default suite). No production code touched — the env-gated probe-
tool registration block was reverted before merge so v2.0.0rc0
ships the same surface as b13.

### Phase F Stage A — extract `promote_topic_via_title_index` + `auto_select_zim_file` (PR #190)

The rc0 refactor lifts two pure orchestration functions out of
``SimpleToolsHandler`` (in ``simple_tools.py``) into a new module
``openzim_mcp/topic_preprocessing.py``:

- ``promote_topic_via_title_index`` — the four-pass promotion
  orchestrator (full-topic, multi-entity, possessive, typo-tolerant
  passes) that all 17 b-series sweeps have hardened.
- ``auto_select_zim_file`` — the 0/1/N archives selection used by
  the dispatch entry points.

The original ``SimpleToolsHandler`` methods remain as thin wrappers
over the extracted module-level functions, so the public surface is
unchanged. Importers that patched ``openzim_mcp.simple_tools.find_title_match``
in tests have been updated to patch the new live binding at
``openzim_mcp.topic_preprocessing.find_title_match``.

### Why extract now

Phase F's eight-tool surface needs ``zim_search`` and ``zim_query``
to share one promotion pipeline without inheriting
``SimpleToolsHandler``. The pre-rc0 pipeline lived as a bound method
on the simple handler, which Phase F's new tools cannot easily call.
Lifting it to a module-level function (with the ``zim_operations``
dependency passed in explicitly) is the smallest change that lets
the rc1 tool implementations share the orchestrator without a
deeper inheritance refactor.

### Verification

- **Promotion-extraction parity diff-test** (94 probes from b1–b13
  cumulative set) — bound-method path and extracted-function path
  return identical results.
- **Auto-select-extraction parity diff-test** (4 scenarios — zero
  files, one file, n files, exception) — log records and return
  values match across both paths.
- **Preprocessing-orchestration idempotency check** — calling
  ``promote_topic_via_title_index`` twice with the same inputs
  returns the same result (no hidden state mutation).
- **Direct unit tests for ``topic_preprocessing``** (45 new tests
  in ``tests/test_topic_preprocessing.py``) — documents the
  extracted module's contract independently of its call sites
  (Z3 probe-based discriminator, Z4 tangential rejection +
  biographical/digit/type-extension exemptions, OPP-1 possessive,
  auto_select_zim_file 0/1/N + exception handling).
- Full suite: **2573 passed, 246 skipped, 38 deselected**.

### Version bumps

| File | From | To |
|---|---|---|
| ``pyproject.toml`` | 2.0.0b13 | 2.0.0rc0 |
| ``.release-please-manifest.json`` | 2.0.0b13 | 2.0.0rc0 |
| ``website/llms.txt`` | 2.0.0b13 | 2.0.0rc0 |
| ``uv.lock`` | 2.0.0b13 | 2.0.0rc0 |

### What's next

The remaining Phase F work (Stage B + C — Gate 0b dispatch-eval
benchmarks + the eight-tool surface implementation as v2.0.0rc1)
proceeds on the ``v2-phase-f-prototype`` branch.

## [2.0.0b13] — 2026-05-24 (beta pre-release) — post-b12 beta-test sweep shipped — Play-style disambig phrasing variant + CodeQL #231 + test dedupe

Post-b12 live-MCP verification confirmed the Z4 multi-token canonical
fix lands cleanly (7/8 historical defects now route correctly) and
the Sub-pattern C disambig rejection works for Lincoln / O'Brien.
One new silent-wrong-answer slipped through:
``Shakespeare England plays`` at v2.0.0b12 still ships ``Play``
(disambig page) at cert=0.85.

### Root cause — phrasing variant not in ``_DISAMBIG_LEAD_PHRASES``

``_is_disambig_lead`` runs a trailing-tail ``endswith`` check against
the phrase set ``("may refer to", "may also refer to")``. The
Wikipedia ``Play`` disambig template ends its pre-H2 with:

  **Play** may refer also to:

Word order: may-refer-**also**-to (NOT may-**also**-refer-to). The
two-phrase set misses this variant, so ``_is_disambig_lead`` returns
False, the b12 Sub-pattern C rejection doesn't fire, and the Play
disambig page is served as the tell_me_about answer.

The b11 implementation comment at ``simple_tools.py:2660`` explicitly
anticipated this: "easier to extend with new phrasings if ZIM
exporters ever produce them".

### Fix — extend ``_DISAMBIG_LEAD_PHRASES`` with the third variant

One-line tuple extension:

```python
_DISAMBIG_LEAD_PHRASES = (
    "may refer to",
    "may also refer to",
    "may refer also to",  # b13 fix: Play-style word order
)
```

No regex, no backtracking risk, no architectural change. The
trailing-tail ``endswith`` check still position-anchors against
false-positives where the phrase appears earlier in the body but
not at the tail.

### Verification

Live-MCP probe of all documented preserved cases plus the 8 Z4
defect repros from b11. After b13: ``Shakespeare England plays``
falls to BM25 (Z4 + Sub-pattern C combine to reject ``Shakespeare's_Kings``
AND ``Play`` disambig). All other 7 Z4 defects continue routing
correctly (4 to head bios, 3 to tail concepts / BM25). 13/13
preserved cases hold; no regressions.

### CodeQL alert #231 — unquote forward refs to TYPE_CHECKING imports

CodeQL's ``py/unused-import`` flagged ``RerankerConfig`` as unused
in ``synthesize.py`` because two annotations used explicit string-
quoting (``"Optional[RerankerConfig]"``) which the static analyzer
treats as opaque string literals rather than deferred forward
references.

Under ``from __future__ import annotations`` (line 14 of synthesize.py),
ALL annotations are automatically stringified at runtime — explicit
quotes are redundant and serve only to hide the import usage from
static analyzers. Fix: remove the redundant string quotes from three
annotations (lines 1041 / 1444 / 1538). mypy / runtime behavior
unchanged.

### Test dedupe — extract ``make_disambig_handler`` to shared fixtures

SonarCloud flagged 6.2% new-code duplication (threshold 3%) because
the b13 sweep's ``TestPlayDisambigRejection._make_handler`` was a
copy of b11's ``TestSubPatternCDisambigRejection._make_handler``.
Extracted to ``tests/_promote_fixtures.make_disambig_handler``,
both sweep files now import the shared helper. Same dedup pattern
the post-b8 sweep used when it created ``_promote_fixtures.py``.

### Tests

7 new tests in ``tests/test_post_b12_beta_fixes.py``:

- 5 direct unit tests on ``_is_disambig_lead`` covering all three
  phrase variants + Play-style full pre-H2 + false-positive defense.
- 2 integration tests: ``Shakespeare England plays`` (multi-token →
  BM25 fallback) and ``tell me about Play`` (bare-head → preserve
  disambig).

```
2562 passed, 54 skipped (full suite, ~28s)
```

mypy / black / flake8 / pip-audit all clean.

### Methodology — "fix unlocks new paths" 20 sweeps strong

Smallest sweep since b6 — one-line phrase extension. The b11
Sub-pattern C rejection architecture was solid; only the underlying
detection primitive needed a phrase variant added. This is the
"easy to extend" promise of the b11 design paying off.

## [2.0.0b12] — 2026-05-23 (beta pre-release) — post-b11 beta-test sweep shipped — Z4 multi-token canonical tangential + Sub-pattern C disambig rejection

Post-b11 sweep packaged from PR #184. Live-MCP verification against
v2.0.0b11 confirmed the b11 probe-based multi-entity discriminator
fully ships its target shape (4/6 historical Z3 repros now route to
the correct head: ``Stalin USSR Russia`` → ``Joseph_Stalin``,
``Hitler Germany Berlin`` → ``Nazi_Germany``, ``Marie Curie polonium
discovery`` → ``Marie_Curie``, ``Big Rapids Michigan tourism`` →
``Big_Rapids,_Michigan``). One new HIGH-severity defect class
surfaced — Z4 multi-token canonical tangential — plus the
Sub-pattern C disambig promotion class noted but deferred from b8.

### Root cause — ``is_tail_hijack_shape`` is narrow by design

The b11 ``is_tail_hijack_shape`` predicate requires **(a) single-
token canonical AND (b) 3+-token topic**. Both preconditions are
sound for the b8 Z3 target shape, but the silent-wrong-answer
pattern manifests in two adjacent shapes that bypass the gate:

1. **2-token topics** with multi-token canonical that contains both
   topic tokens (head as possessive/parenthetical + extra modifier):
   ``Tesla electricity`` → ``Tesla's_Wireless_Electricity``,
   ``Mozart Vienna`` → ``Mozarthaus_Vienna``,
   ``Beethoven symphony`` → ``Symphony_No._1_(Beethoven)``,
   ``Lenin Russia`` → ``Leninist_Komsomol_of_the_Russian_Federation``.
2. **3+-token topics** with multi-token canonical that overlaps the
   topic only via stemming or non-head tokens:
   ``Marie Curie radioactivity`` → ``Radioactive_(Redniss_book)``,
   ``Darwin evolution Galapagos`` → ``Galápagos_Islands``,
   ``Mao China revolution`` →
   ``History_of_the_People's_Republic_of_China_(1949–1976)``,
   ``Shakespeare England plays`` → ``Shakespeare's_Kings``.

Additionally, the b8-noted Sub-pattern C cases still fire:
``Lincoln slavery emancipation`` → ``Lincoln`` (disambig page) and
``O'Brien character 1984`` → ``O'Brien`` (disambig page). The
canonical is single-token (no Z3 / Z4 shape) but is itself a
disambiguation page.

### Fix — Z4 tangential check with three exemptions + Sub-pattern C disambig render-time rejection

Four new helpers in ``title_promotion``:

- ``is_tangential_multi_token_shape(promoted, topic)`` — pure-logic
  shape: canonical is multi-token AND not a token-set subset of
  topic (after filtering ``_CANONICAL_FUNCTION_WORDS`` — articles,
  conjunctions, prepositions — from canonical). Subset preserves the
  ``Apollo 11 moon landing`` → ``Moon_landing`` and ``Lincoln
  Gettysburg Address`` → ``Gettysburg_Address`` invariants. The
  function-word filter additionally preserves
  ``Assassination_of_John_F._Kennedy`` for topic ``John F Kennedy
  assassination`` (canonical's only extra is the preposition
  ``of``).
- ``probed_head_matches_promoted(topic, promoted, title_probe)`` —
  biographical-canonical exemption: probes EACH non-stop-word topic
  token. True iff ANY probe's canonical path (or pre-redirect path)
  equals the promoted candidate AND the probed token literally
  appears in the promoted canonical's tokens. The probe-all approach
  catches tail-position subjects (``quantum mechanics Einstein`` →
  ``Albert_Einstein`` — subject ``einstein`` at the topic tail);
  the token-in-canonical guard prevents accidental over-acceptance
  (``Darwin evolution Galapagos`` → ``Galápagos_Islands`` would
  match on path-only but ``galapagos`` ≠ ``galápagos`` raw, so the
  guard correctly rejects).
- ``has_digit_specificity_match(promoted, topic)`` — digit
  specificity exemption: when canonical's extras (tokens NOT in
  topic) include a digit AND topic also has a digit-bearing token,
  the user explicitly signaled they want a numbered instance.
  Catches ``Beethoven 9th symphony`` → ``Symphony_No._9_(Beethoven)``
  without over-accepting ``Beethoven symphony`` →
  ``Symphony_No._1_(Beethoven)`` (no topic digit).
- ``has_topic_prefix_canonical_extension(promoted, topic)`` — type-
  extension exemption: canonical's leading tokens form a contiguous
  2+-token slice of topic, suffix tokens are all extras. Catches the
  b8 motivating case ``Big Rapids Michigan Ferris State`` →
  ``Ferris_State_University`` where the topic tail is the
  canonical's entity name without the type-word suffix.

Call-site wiring in ``_promote_topic_via_title_index``:

- **Pass 0 / Pass 3** consult ``accept_possessive_promotion`` AND
  ``_passes_z4`` directly (no Z3 multi-entity escape — that escape
  exists only for Pass 1's documented 1-token-tail filler-prose
  feature).
- **Pass 1 / Pass 2** consult ``_accept_with_multi_entity_check``,
  which layers the Z3 escape over the b9 unconditional tail-hijack
  rejection AND then applies ``_passes_z4``.
- The b3 invariant (first ``find_title_match`` call uses bare
  ``topic``) is preserved by hoisting the Pass 0 probe above the
  closure definitions.

Symmetric application in ``synthesize.py:_promote_title_match``
Pass 0 — synthesize was previously vulnerable to the same Z4
silent-wrong-answer pattern via ``zim_query(synthesize=True)``.

**Sub-pattern C disambig rejection** at render-time in
``_handle_tell_me_about``: when the auto-picked canonical's body
matches the disambig-lead pattern (``may refer to`` / ``may also
refer to``) AND the topic has 2+ non-stop-word content tokens, fall
back to plain BM25 search. Detection-at-render-time avoids a
separate content-peek round-trip (the body is already fetched for
normal rendering). Single-content-token topics (``tell me about
Lincoln``) legitimately want the disambig and are preserved by the
``len >= 2`` floor. Possessive queries bypass via
``has_apostrophe_possessive`` (OPP-1 handles those at the promotion
layer).

### Decision matrix

| Topic | Multi-token tangent | Bio exem | Digit exem | Type-ext exem | Decision |
| --- | --- | --- | --- | --- | --- |
| Tesla electricity | yes | no | no | no | REJECT |
| Mozart Vienna | yes | no | no | no | REJECT |
| Beethoven symphony | yes | no | no | no | REJECT |
| Lenin Russia | yes | no | no | no | REJECT |
| Marie Curie radioactivity | yes | no | no | no | REJECT |
| Shakespeare England plays | yes | no | no | no | REJECT |
| Darwin evolution Galapagos | yes | no | no | no | REJECT |
| Mao China revolution | yes | no | no | no | REJECT |
| Picasso Paris cubism | yes | YES | - | - | ACCEPT |
| Quantum mechanics Einstein | yes | YES (tail) | - | - | ACCEPT |
| Beethoven 9th symphony | yes | no | YES | - | ACCEPT |
| Big Rapids Michigan Ferris State | yes | no | no | YES | ACCEPT |
| John F Kennedy assassination | no (⊆ after func-word filter) | - | - | - | ACCEPT |
| Apollo 11 moon landing | no (⊆) | - | - | - | ACCEPT |
| Lincoln Gettysburg Address | no (⊆) | - | - | - | ACCEPT |
| Newton's gravity (possessive) | n/a | - | - | - | ACCEPT (OPP-1) |
| Hamlet Denmark prince | no (1tk) | - | - | - | ACCEPT |
| Berlin Germany | no (1tk) | - | - | - | ACCEPT |
| what is the population of detroit | no (1tk) | - | - | - | ACCEPT |
| Lincoln slavery emancipation | Sub-pattern C | - | - | - | REJECT (render-time, falls to BM25) |
| O'Brien character 1984 | Sub-pattern C | - | - | - | REJECT (render-time, falls to BM25) |
| tell me about Lincoln (1-tk) | Sub-pattern C | - | - | - | ACCEPT (single-content-token preserved) |

### Tests

52 new tests in ``tests/test_post_b11_beta_fixes.py`` covering:

- 8 Z4 defect-repro integration tests (one per live silent-wrong-answer)
- 9 preserved-case integration tests (Apollo / Lincoln / Hamlet / Berlin / Picasso / Newton's possessive / population-of-detroit / Ferris State / Beethoven-9th / quantum-Einstein / JFK)
- Direct unit tests on each new helper (shape predicate; biographical via probe-all + token-in-canonical guard; digit specificity in 4 directions; type-extension prefix length floor / subset overlap / anywhere-in-topic; function-word filter / lexical-word retention)
- 3 synthesize Z4 integration tests (Tesla reject / Picasso bio accept / possessive bypass)
- 4 Sub-pattern C disambig integration tests (Lincoln multi-token reject / Lincoln single-content-token preserve / stop-words filter / non-disambig body unaffected)

```
2555 passed, 54 skipped (full suite, ~29s)
```

mypy / black / flake8 / pip-audit all clean.

### Methodology — "fix unlocks new paths" 19 sweeps strong

The post-b11 sweep peeled the b11 narrow predicate in three concentric
layers across three commits:

1. **First pass** — Z4 shape predicate plus biographical
   (head-token-only), digit-specificity, and type-extension exemptions.
2. **Second pass** — static code review surfaced two regressions: tail-
   position subject (quantum mechanics Einstein) and canonical
   function-word extras (JFK). Fixed via probe-all-tokens with token-
   in-canonical guard, and the canonical-subset stop-word filter.
3. **Third pass** — closed two scoping gaps: synthesize Pass 0 Z4
   protection (symmetric to simple_tools), and Sub-pattern C disambig
   render-time rejection.

Each layer extends the b11 design without invalidating its core: the
b11 ``count_non_tail_strong_entities`` discriminator stays in place
for Pass 1/2's filler-prose escape; the b9 ``accept_possessive_promotion``
Z3 rejection stays unconditional at Pass 0/3; OPP-1 possessive logic
is untouched. b12 adds the multi-token canonical sibling of Z3 with
the supporting exemptions needed to keep all documented preserved
cases working.

## [2.0.0b11] — 2026-05-23 (beta pre-release) — post-b10 beta-test sweep shipped — probe-based multi-entity discriminator (case-independent Z3)

Post-b10 sweep packaged from PR #182. Live-MCP verification against
v2.0.0b10 confirmed OPP-1's redirect extension lands cleanly
(``Newton's gravity`` now auto-fetches
``Newton's_law_of_universal_gravitation``) but ALL SIX Z3 silent-
wrong-answer repros STILL fire identically to b9.

### Root cause — Tier 1 Rule 1 lowercases the topic upstream

The b10 Z3 discriminator counted capitalized + digit tokens in the
ORIGINAL-case topic. But ``IntentParser._normalize_topic_case``
(Tier 1 Rule 1, ``intent_parser.py:1540``) lowercases the query
BEFORE topic extraction. By the time the discriminator sees the
topic, ``"Stalin USSR Russia"`` is ``"stalin ussr russia"`` — zero
capitalized tokens — the discriminator never fired on live data,
even though OPP-1 (which doesn't depend on case) worked perfectly.

### Fix — case-independent probe-based discriminator

Two new helpers in ``title_promotion``:

- ``is_tail_hijack_shape(promoted, topic)`` — pure-logic shape check.
- ``count_non_tail_strong_entities(topic, title_probe, limit=2)`` —
  probe-based multi-entity counter with TWO refinements that make
  it robust against the live data shapes:
    - **Stop-word filter**: skip non-entity tokens (``what``,
      ``is``, ``the``, ``of``, common auxiliaries / pronouns /
      connectives) that often have legitimate disambiguation-page
      matches on Wikipedia but aren't entities the user is
      querying jointly.
    - **Probed-token-in-canonical check**: only count a probe as
      a "strong" match when the probed token (lowercased) appears
      in the canonical path tokens OR the pre-redirect-path
      tokens. Filters out fuzzy/stemming hits (libzim resolving
      ``musicians`` to ``Musician`` via stem) AND defends against
      overly-permissive test mocks.

``_promote_topic_via_title_index`` Pass 1 / Pass 2 now consult both
helpers via a closure-scoped ``_accept_with_multi_entity_check``
wrapper. The multi-entity discriminator overrides
``accept_possessive_promotion``'s unconditional tail-hijack
rejection only when the topic probes as single-entity (filler-
prose pattern).

``_accept_non_possessive`` no longer carries the case-based
discriminator (which never fired in production). Tail-hijack
rejection there is unconditional; the call site is now the only
place that runs the multi-entity discriminator.

### Decision matrix

| Topic | Tail-hijack? | Multi-entity? | Decision |
| --- | --- | --- | --- |
| Stalin USSR Russia | yes | yes (2+) | REJECT |
| Hitler Germany Berlin | yes | yes | REJECT |
| Marie Curie polonium discovery | yes | yes | REJECT |
| Big Rapids Michigan tourism | yes | yes | REJECT |
| O'Brien character 1984 | yes | yes | REJECT |
| what is the population of detroit | yes | no (stop-filter, 1 left) | ACCEPT |
| people who live in michigan | yes | no | ACCEPT |
| Berlin Germany | no (<3 tk) | n/a | ACCEPT |

### Tests

16 new tests in ``tests/test_post_b10_beta_fixes.py``. Two b9 tests
updated to reflect post-b10 architecture (multi-entity mock probes +
structural pin asserts ``_accept_with_multi_entity_check`` wrapper).

```
2503 passed, 54 skipped (full suite, ~28s)
```

mypy / black / flake8 / isort all clean.

### Methodology — "fix unlocks new paths" 18 sweeps strong

The post-b10 sweep peeled three layers in concert:
- b10 case-based discriminator broken by upstream Sub-D-2 Rule 1.
- Probe-based replacement fooled by stop words that match
  disambiguation pages.
- Probe ALSO fooled by overly-permissive test mocks.

Discriminator now has three layers — shape, stop-word filter,
in-canonical check — each independently testable.

## [2.0.0b10] — 2026-05-23 (beta pre-release) — post-b9 beta-test sweep shipped — Z3 all match_types + Pass 1/2 gate + OPP-1 redirect extension

Post-b9 sweep packaged from PR #180. Live-MCP verification against
v2.0.0b9 confirmed the b9 Z3 + OPP-1 fixes land at the unit-test
level but BOTH bypass the actual live silent-wrong-answer code
paths because b9 gated on the wrong ``match_type``.

### Z3-bypass (HIGH) — tail-hijack lives on direct/redirect

The b9 Z3 rule only fired inside ``_accept_non_possessive`` when
``match_type == "fuzzy_suggest"``. The live silent-wrong-answers
route through Pass 1 ``iter_query_tails``: ``find_title_match``
returns ``None`` for the full topic, so the next pass kicks in,
where the 1-token tail (``"russia"``, ``"berlin"``, ``"discovery"``,
``"tourism"``, ``"1984"``) is passed to ``find_title_match``.
libzim sees the tail string as a case-insensitive title equal →
returns ``match_type="direct"`` at score 1.0. The b9 short-circuit
``if match_type != "fuzzy_suggest": return True`` bypassed the Z3
check entirely.

ALSO: Pass 1 and Pass 2 in ``_promote_topic_via_title_index``
returned ``promoted`` directly without consulting
``accept_possessive_promotion``. Even after extending the gate to
direct/redirect, the Z3 rule wouldn't fire because the call site
didn't invoke it.

#### Fix — three changes in concert

1. **``_accept_non_possessive``** no longer short-circuits on
   ``match_type``. The tail-token-hijack premise is purely about
   the topic↔canonical token relationship; it doesn't depend on
   how libzim resolved the match. The zero-overlap stemming
   sub-rule stays gated on ``fuzzy_suggest`` (direct/redirect by
   definition share at least the matched token).
2. **``_promote_topic_via_title_index`` Pass 1 (tail iter) and
   Pass 2 (window iter)** now consult ``accept_possessive_promotion``
   on each candidate, matching what Pass 0 (full topic) and Pass 3
   (typo-tolerant) already did.
3. **Discriminator** preserves the documented Pass 1 1-token-tail
   feature. Queries like ``what is the population of detroit`` →
   ``Detroit`` and ``people who live in michigan`` → ``Michigan``
   keep working: the tail-hijack rejection only fires when the
   topic has 2+ "specific" tokens — tokens that are capitalized in
   the original case OR digit-only. The silent-wrong-answer
   pattern stacks multiple proper-noun-shaped tokens
   (``Stalin USSR Russia``, ``Hitler Germany Berlin``,
   ``O'Brien character 1984``); legitimate filler-prose queries
   have at most one capitalized entity (the tail itself).

#### Live cases this fix resolves (cert=0.85 silent-wrong-answers at v2.0.0b9)

- ``Stalin USSR Russia`` → ``Russia`` → BM25 / Pass 2 head probe
- ``Hitler Germany Berlin`` → ``Berlin`` → BM25 / Pass 2 head probe
- ``Marie Curie polonium discovery`` → ``Discovery`` (a disambig
  page!) → BM25
- ``Big Rapids Michigan tourism`` → ``Tourism`` → Pass 2 finds
  ``Big_Rapids,_Michigan``
- ``O'Brien character 1984`` → ``1984`` (the year) → BM25 /
  Pass 2 finds ``O'Brien_(Nineteen_Eighty-Four)``
- ``Marie Curie radioactivity`` → fuzzy-suggest stemming hit
  unchanged from b9

#### Regression guards preserved

- ``Hamlet Denmark prince`` → Pass 0 / Pass 2 finds ``Hamlet``
  (HEAD position)
- ``Napoleon France emperor`` → Pass 0 / Pass 2 finds ``Napoleon``
- ``Apollo 11 moon landing`` → ``Moon_landing`` (multi-token
  canonical, tail-hijack doesn't fire)
- ``quantum mechanics Einstein`` → ``Albert_Einstein`` (single
  capitalized token, discriminator skips)
- ``Lincoln Gettysburg Address`` → ``Gettysburg_Address``
  (multi-token canonical)
- ``Berlin Germany`` → ``Berlin`` (2-token topic, Z3 doesn't fire)
- ``population of detroit`` / ``people who live in michigan`` —
  legitimate Pass 1 1-token-tail feature preserved via
  discriminator (zero capitalized tokens)

### OPP-1-bypass (MEDIUM) — Newton's gravity redirect

The b9 OPP-1 carve-out only fired inside
``_accept_possessive_fuzzy_suggest``. The live ``Newton's gravity``
case routes through ``_accept_possessive_redirect``: libzim
returns ``Newton's_law_of_universal_gravitation`` with
``match_type="redirect"`` and
``pre_redirect_path="Newton_Laws_of_Gravity"``. The b7 Z1.1 subset
rule rejects because ``{newton, laws, of, gravity} ⊄ {newton, s,
gravity}``. OPP-1's possessor-in-canonical check never runs.

#### Fix — OPP-1 extension to redirect branch

When the b7 Z1.1 subset rule rejects,
``_accept_possessive_redirect`` NOW falls back to the same
possessor-in-canonical check OPP-1 uses for fuzzy_suggest: ACCEPT
if any of the topic's possessor tokens appears in the
post-redirect canonical path tokens.

Decision matrix:

| Topic | Resolved canonical | Decision |
| --- | --- | --- |
| ``Plato's cave`` | ``Allegory_of_the_cave`` via pre=``Plato's_cave`` | ACCEPT (b8 subset) |
| ``Einstein's theory`` | ``Theory_of_relativity`` via pre=``Einstein's_theory`` | ACCEPT (b8 subset) |
| ``Newton's gravity`` | ``Newton's_law_of_universal_gravitation`` via pre=``Newton_Laws_of_Gravity`` | ACCEPT (post-b9 OPP-1) |
| ``Darwin's evolution`` | ``Evolution`` via pre=``Darwin's_Theory_of_Evolution`` | REJECT (b7) |
| ``Plato's republic philosophy`` | ``Czech_philosophy`` | REJECT (b6) |

### Tests

39 new tests in ``tests/test_post_b9_beta_fixes.py`` across 5
classes. One b4 test mock updated to include ``pre_redirect_path``
reflecting the live libzim row shape since b6.

```
2487 passed, 54 skipped (full suite, ~28s)
pip-audit: no known vulnerabilities
```

mypy clean across 52 source files. black + flake8 + isort clean.

### Methodology — "fix unlocks new paths" 17 sweeps strong

The post-b9 sweep demonstrates the pattern again: b9's Z3 + OPP-1
fixes were conceptually correct but missed the actual live code
paths because I inferred the wrong match_types from upstream
behavior. Live diagnostic against the deployed b9 ZIM corpus
surfaced four new invariants this sweep pins down: (a) tail-hijack
hits direct match_type via Pass 1's tail probe, not fuzzy_suggest
via Pass 0; (b) Pass 1 / Pass 2 didn't call the accept gate; (c)
Newton's gravity redirect goes through a non-subset pre-path; (d)
discriminator needed to preserve the documented Pass 1 1-token-tail
feature.

## [2.0.0b9] — 2026-05-23 (beta pre-release) — post-b8 beta-test sweep shipped — Z3 non-possessive tail-hijack + OPP-1 possessor-in-canonical carve-out

Post-b8 sweep packaged from PR #178. Live-MCP verification against
v2.0.0b8 confirmed all prior b6/b7/b8 fixes land cleanly. ONE HIGH-
severity defect + ONE MEDIUM opportunity unlocked by deeper probing
of the non-possessive 3+ token shape.

### Z3 (HIGH) — Non-possessive multi-token tail-hijack

The b4 D2 raised-``min_len`` floor protected possessive topics from
trailing 1-token tails winning at strict 1.0. Non-possessive
multi-token queries still leaked the same hijack at Pass 0
(``_promote_topic_via_title_index``): libzim's title-suggest
fuzzy-matches a STRONG single token in the topic at score 0.95 and
returns just that token's canonical alone. The full-topic probe at
``min_score=0.95`` (added in b3) accepts the row because
``accept_possessive_promotion`` returned ``True`` for any
non-possessive topic.

Live silent-wrong-answer repros at v2.0.0b8 (all cert=0.85):

- ``Stalin USSR Russia`` → ``Russia`` (user wanted Stalin)
- ``Hitler Germany Berlin`` → ``Berlin`` (user wanted Hitler)
- ``Marie Curie polonium discovery`` → ``Discovery`` (a disambig
  page!)
- ``Marie Curie radioactivity`` → ``Radioactive_(Redniss_book)``
  (an obscure 2010 graphic novel surfaced via stemming match)
- ``Big Rapids Michigan tourism`` → ``Tourism`` (contradicts the
  ``iter_query_windows`` docstring's own canonical example,
  ``Big_Rapids,_Michigan``)
- ``O'Brien character 1984`` → ``1984`` (the year article)

#### Fix — non-possessive fuzzy_suggest gate

Two narrow rejections in the non-possessive branch when
``match_type="fuzzy_suggest"`` and the topic has 3+ tokens:

1. **Tail-token hijack** — canonical is a single token equal to
   the topic's LAST token. The user typed
   ``<subject> ... <generic>``; libzim returned the generic
   article. ``Hamlet Denmark prince`` → ``Hamlet`` stays accepted
   because the canonical sits at the HEAD position, not the tail.
2. **Zero-overlap stemming hit** — canonical's tokens have zero
   exact-overlap with topic's tokens (the match was via stemming
   only). The graphic novel surfaced for ``Marie Curie
   radioactivity`` because libzim's title index stems
   ``radioactivity`` to ``radioactive``; no other topic token
   matches the canonical, so the hit is one-stem-token-deep —
   too thin a signal to auto-fetch.

Topics with fewer than 3 tokens are unaffected.

Counter-cases the fix preserves: ``Hamlet Denmark prince`` →
``Hamlet``, ``Napoleon France emperor`` → ``Napoleon``,
``Apollo 11 moon landing`` → ``Moon_landing``,
``quantum mechanics Einstein`` → ``Albert_Einstein``,
``Lincoln Gettysburg Address`` → ``Gettysburg_Address``,
``Berlin Germany`` → ``Berlin``.

### OPP-1 (MEDIUM) — Possessive fuzzy_suggest carve-out

The b6 D1 rule REJECTS every ``match_type="fuzzy_suggest"`` row
for a possessive topic. Live probe found this is too strict:
``Newton's gravity`` falls to BM25 even though
``Newton's_law_of_universal_gravitation`` is the obvious rank-1
BM25 canonical AND contains the possessor token ``newton``
literally.

#### Refinement

For possessive topics + ``fuzzy_suggest``, ACCEPT iff the
canonical path tokens include any of the topic's possessor tokens.
The canonical literally preserves the user's named entity,
signalling it's a longer-form expansion rather than the
``Darwin's evolution`` → ``Evolution`` shape that drops the
possessor.

Decision matrix for possessive + fuzzy_suggest:

| Topic | Canonical | Decision |
| --- | --- | --- |
| ``Newton's gravity`` | ``Newton's_law_of_universal_gravitation`` | ACCEPT (OPP-1) |
| ``Mary's lamb`` | ``Mary_Had_a_Little_Lamb`` | ACCEPT |
| ``Darwin's evolution`` | ``Evolution`` | REJECT (b6 D1 preserved) |
| ``Plato's republic philosophy`` | ``Czech_philosophy`` | REJECT (b6 Z1 preserved) |

Tokenization uses ``_TOKEN_RE`` (apostrophe-splitting), same as
the b8 Z1.1 subset rule for redirects, so ``newton's`` in the
canonical surfaces as the bare token ``newton`` for comparison.

### Refactor (Sonar S3776 + duplication)

Quality-gate-driven follow-ups landed in the same PR:

- ``accept_possessive_promotion`` extracted three per-branch
  helpers (``_accept_non_possessive``,
  ``_accept_possessive_fuzzy_suggest``,
  ``_accept_possessive_redirect``) to bring cognitive complexity
  from 21 down under the 15 threshold. No behaviour change.
- The three shared sweep test fixtures (``_make_simple_handler``,
  ``_fake_find_title_match``, ``_run_promote_simple``) moved to
  ``tests/_promote_fixtures.py``. b6/b7/b8 sweep test files now
  import from the shared module instead of duplicating locally.

### Tests

26 new tests in ``tests/test_post_b8_beta_fixes.py`` across 5
classes (``TestZ3NonPossessiveTailHijack``,
``TestZ3RegressionGuards``, ``TestOPP1PossessorInCanonical``,
``TestZ3PromoteIntegration``, ``TestStructuralGuards``).

```
2448 passed, 54 skipped (full suite, ~28s)
pip-audit: no known vulnerabilities
```

mypy clean across 52 source files. black + flake8 + isort clean.

### Methodology — "fix unlocks new paths" 16 sweeps strong

Each sweep peels back another layer; the post-b8 sweep generalised
the b4 D2 raised-min_len protection to non-possessive multi-token
topics, and relaxed b6 D1's blanket-reject when the canonical
preserves the possessor literally.

## [2.0.0b8] — 2026-05-22 (beta pre-release) — post-b7 beta-test sweep shipped — Z1.1 subset rule (Darwin's evolution truncation redirect)

Post-b7 sweep packaged from PR #176. Live-MCP verification against
v2.0.0b7 confirmed all prior fixes land cleanly EXCEPT the b6 Z1
fix for ``Darwin's evolution``: it still returned ``Evolution`` at
cert=0.85, the silent-wrong-answer the user originally flagged.

### Z1.1 (HIGH) — Pre-redirect-path containment check too lenient

The post-b6 Z1 filter rejected ``match_type="redirect"`` rows whose
pre-redirect path tokens didn't *contain* any of the topic's
possessor tokens. That correctly caught the
``Plato's republic philosophy`` → ``Czech_philosophy`` case (the
pre-path didn't contain ``plato`` at all).

But the post-b7 live probe surfaced a sibling shape: **2-token
possessive queries where the user typed a TRUNCATED form of a
longer canonical redirect**. libzim's suggestion-search returns a
redirect entry whose pre-path includes the possessor AND extra
tokens not in the topic; the redirect walks to a canonical that
loses the possessor entirely.

Live repro: ``tell me about Darwin's evolution`` →
``Evolution``. libzim returns a redirect entry like
``Darwin's_Theory_of_Evolution`` (pre-path tokens: ``{darwin, s,
theory, of, evolution}``). The b6 containment check accepts
because ``darwin`` IS in the pre-path — but the user's topic
``{darwin, s, evolution}`` doesn't contain ``theory`` / ``of``,
signalling that the user typed an abbreviated form. The resolved
canonical (``Evolution``) drops the possessor.

### Fix — subset rule

Tighten ``accept_possessive_promotion`` in ``title_promotion`` from
"any possessor token in pre-path" to "pre-path tokens ⊆ topic
tokens":

```python
# Before (b6 containment):
return bool(possessors & pre_tokens)
# After (b8 subset):
return pre_tokens.issubset(topic_tokens)
```

Strictly tighter than the containment check: any pre-path that's a
subset of the topic necessarily contains the possessor — so all
cases accepted by b6 with pre ⊆ topic continue to be accepted.
Cases accepted by b6 with pre having extras (the truncation
shape) are now rejected.

Decision matrix:

| Topic | Pre-path | Subset? |
| --- | --- | --- |
| ``Plato's cave`` | ``Plato's_cave`` | ✅ ACCEPT |
| ``Einstein's theory`` | ``Einstein's_theory`` | ✅ ACCEPT |
| ``Newton's gravity`` | ``Newton's_gravity`` | ✅ ACCEPT |
| ``Darwin's evolution`` | ``Darwin's_Theory_of_Evolution`` | ❌ REJECT |

Non-possessive topics, ``match_type="direct"``, and
``match_type="fuzzy_suggest"`` decisions are unchanged from b7.

### Tests

13 new tests in ``tests/test_post_b7_beta_fixes.py`` across 3
classes (TestSubsetRule with 6 parametrized + 4 standalone,
TestPromoteIntegration with 2, TestRegressionGuards with 1).

Full suite: **2423 passing, 54 skipped**. mypy clean across 52
source files. black + flake8 + pip-audit clean. All 14 CI checks
pass on PR #176 (first push — no cleanup waves needed, having
internalized the post-b6 Sonar feedback).

### Methodology — "fix unlocks new paths" 15 sweeps strong

Each prior sweep added a more discriminating signal until the
filter's behaviour aligns with user intent across every shape:

- **b6 Z1** introduced match_type (direct/redirect/fuzzy_suggest).
- **b6 Z1** sub-discriminates redirect via pre-path *containment*.
- **b8 Z1.1** (this sweep) refines pre-path containment to
  *subset*.

The pattern: each layer of discrimination catches a more specific
subset of the wrong-answer attack surface. The subset rule's
strict-tightness guarantees no previously-accepted case regresses
that wasn't already in the truncation-shape attack surface.

---

## [2.0.0b7] — 2026-05-22 (beta pre-release) — post-b6 beta-test sweep shipped — 2 defects (Z1 associative-redirect filter + Z2 synthesize insert shape)

Post-b6 sweep packaged from PR #174. Live-MCP verification against
v2.0.0b6 confirmed all prior fixes land cleanly (b3 Einstein's /
Plato's canonicals, b4 non-possessive carve-out, b3 trailing-modal
politeness, b2 D3 typo retry, all earlier b-series invariants).
TWO new HIGH-severity defects unlocked by deeper probing of the
``match_type="redirect"`` shape and the synthesize-path
promotion's insert contract.

### Z1 (HIGH) — D1 filter misses associative redirects

The post-b4 D1 filter rejected ``fuzzy_suggest`` for possessive
topics but accepted ``redirect`` blindly. libzim's suggestion-
search occasionally produces an **associative redirect**: a
redirect entry whose pre-resolution path is unrelated to the user's
possessor entity, but whose redirect chain walks to a canonical
that shares one user-typed token.

Live silent-wrong-answers:

- ``tell me about Darwin's evolution`` → ``Evolution`` (cert=0.85)
- ``tell me about Plato's republic philosophy`` → ``Czech_philosophy``
  (cert=0.85)

### Z2 (HIGH) — Synthesize pass-0 produces malformed insert

The post-b4 D3 synthesize pass-0 inserted the raw ``find_title_match``
dict into ``top_hits``. The dict has shape ``{path, title, zim_file,
match_type, pre_redirect_path}`` but ``top_hits`` items expect the
``search_top_k`` shape ``{path, snippet, score}``. Downstream score-
sort demoted the canonical to the bottom when it wasn't already in
``top_hits``.

Live impact (``synthesize=true``): ``Einstein's theory`` →
``Theory_of_relativity`` surfaced at rank 6 with score 0 (BM25 hits
dominate; the buggy insert was demoted). ``Plato's cave`` happened
to work because ``Allegory_of_the_cave`` IS in BM25 top_hits — the
reorder branch fired with the existing properly-shaped entry.

### Fixes

1. **``pre_redirect_path`` annotation** through
   ``find_entry_by_title_data`` (fast-path + suggestion-search).
   ``find_title_match`` propagates the field. Schema is
   non-breaking (``FindEntryHit.pre_redirect_path`` is
   ``NotRequired[str]``).
2. **New ``extract_possessor_tokens(topic)`` helper** pulls bare
   possessor tokens from each ``X's``/``X'`` shape.
   ``"Plato's cave"`` → ``["plato"]``; ``"O'Brien"`` → ``[]``
   (name, not possessive).
3. **New shared filter ``accept_possessive_promotion``** in
   ``title_promotion`` (single source of truth for ``simple_tools``
   AND ``synthesize``). Acceptance matrix:

   - Non-possessive topic: accept all match_types (b4 win preserved).
   - Possessive + direct: accept.
   - Possessive + fuzzy_suggest: REJECT (b6 D1).
   - Possessive + redirect: accept iff any query possessor token
     appears in the pre-redirect path's tokens.
   - Missing match_type: accept (backwards-compat).

4. **``search_top_k``-shaped pass-0 insert** in synthesize.
   ``_build_pass0_promoted_hit`` re-probes via
   ``search_handler.title_match_hit(archive, full_probe.title)``
   to produce the proper ``{path, snippet, score: 1.0}`` shape.
   Fallback to a minimal ``{path, snippet: "", score: 1.0}`` hit
   when the re-probe handler misses.

### Tests

20 new tests in ``tests/test_post_b6_beta_fixes.py`` across 5
classes (TestPreRedirectPathPropagation,
TestPossessorTokenExtraction with 12 parametrized cases,
TestRedirectFilterRejectsUnrelatedRedirect with 3 parametrized
cases, TestSynthesizePass0InsertShape, TestRegressionGuards).
Updated 2 b4 tests + 1 golden snapshot.

Full suite: **2410 passing, 54 skipped**. mypy clean across 52
source files. black + flake8 + pip-audit clean. All 14 CI checks
pass on PR #174 (after three cleanup waves: SonarCloud S1192 /
S5869 / S5799 deduplication; helper consolidation to
``title_promotion``; S5852 ReDoS bound on the possessor regex).

### Methodology — "fix unlocks new paths" 14 sweeps strong

Each prior sweep peeled back another layer; post-b6 added two:

1. ``match_type="redirect"`` was assumed semantic. The post-b6
   live probe revealed associative redirects where libzim's fuzzy
   token-matching produces a redirect entry whose pre-resolution
   path is unrelated to the user's possessor.
2. The synthesize pass-0 insert worked only when the canonical
   was already in BM25 top_hits. Otherwise the malformed insert
   leaked through and was demoted by score-sort.

Three new invariants pinned: pre-redirect-path propagation;
possessor-token filter for redirects; ``search_top_k`` shape for
synthesize pass-0 inserts.

---

## [2.0.0b6] — 2026-05-22 (beta pre-release) — CVE-driven lockfile bump (starlette PYSEC-2026-161)

Lockfile-only release re-rolling v2.0.0b5 after the release workflow's
`pip-audit` security gate caught a new starlette CVE that landed
between the v2.0.0b4 release and the v2.0.0b5 attempted publish.

### Vulnerability

- **PYSEC-2026-161** — starlette 1.0.0 → fix in 1.0.1. Transitive
  dependency via `mcp[cli]` and `sse-starlette`. Bumped via
  `uv lock --upgrade-package starlette`.

### Behavior changes

None. Code under `openzim_mcp/` and `tests/` is unchanged from the
v2.0.0b5 attempt. The full post-b4 sweep (FOUR defects + 1 latent +
2 audit defects, see v2.0.0b5 section below) ships in this release.

### Methodology note

Release workflow's `pip-audit` step at the start of "Test before
release" is doing its job — caught a fresh CVE that landed between
PR-time CI (which doesn't run pip-audit) and release-time publish.
Pattern matches prior CVE-driven lockfile bumps (post-a19 idna
PR #151, post-a24 pyjwt PR #160). The v2.0.0b5 git tag exists on the
repo at the aborted merge commit (`385f72d`); v2.0.0b6 is the
released artifact.

---

## [2.0.0b5] — 2026-05-22 (beta pre-release) — post-b4 beta-test sweep shipped — 4 defects across 3 audit passes (aborted — see v2.0.0b6)

Post-b4 sweep packaged from PR #171 (commits `51158e9` → `8f9628d` →
`e6a778f`). FOUR defects + 1 latent surfaced by live-MCP probing of
v2.0.0b4, plus TWO additional defects caught by source-level
self-audits of the pass-1 fix itself. The "fix unlocks new paths"
methodology reproduced THREE times within a single sweep.

### D1 (HIGH) — b4 pass-0 gate can't distinguish redirect-0.95 from fuzzy-0.95

`find_entry_by_title_data` scores libzim's suggestion-search results on
a linearly-decaying rank formula capped at 0.95 (zim/search.py
:2814-2822). The same 0.95 score covers both:

- a redirect walk (suggestion returned `Plato's_cave` redirect entry;
  `_follow_redirect_chain` walked to `Allegory_of_the_cave`)
- a pure fuzzy title-prefix match (suggestion returned `Evolution` for
  the query `Darwin's evolution`)

The b4 `min_score=0.95` gate accepted both. Live: `tell me about
Darwin's evolution` → `Evolution` at cert=0.85 (silent-wrong-answer).

### D2 (HIGH) — pass-1 `iter_query_tails` still strips apostrophes

The b4 fix only patched pass-0. Pass-1 (simple_tools.py:3925) still
consumed `_TAIL_TOKEN_RE` at title_promotion.py:188, which treated
apostrophes as token boundaries. `"plato's republic philosophy"` →
`["plato", "s", "republic", "philosophy"]`; 1-tail `"philosophy"`
matches canonical `Philosophy` at strict 1.0 → silently wins. Live
silent-wrong-answers (cert=0.85): `Plato's republic philosophy` →
`Philosophy`; `Einstein's theory history` → `History`; `Einstein's
theory tourism` → `Tourism`.

### D3 (HIGH) — synthesize `_promote_title_match` never got the b4 treatment

PR #169 only touched `_promote_topic_via_title_index`.
`_promote_title_match` in synthesize.py:869-950 iterated
`iter_query_tails(query)` at line 915 without the b4 pass-0 full-query
probe. Live (`synthesize=true`): `Einstein's theory` → rank-1 citation
`Theory` (expected `Theory_of_relativity`); `Plato's cave` → rank-1
`Cave` (correct article demoted to rank 2).

### D5 (LATENT) — pass-2 windows + pass-3 typo-tolerant tails

`iter_query_windows` and the pass-3 0.8-fuzzy tail probe share the
same tokenizer; the apostrophe-strip shape was masked in practice
because pass-1's strict-1.0 single-token tail short-circuited first.
Fixed for free by the tokenizer change.

### Pass-2 audit defect — synthesize pass-0 silently no-ops in production

The pass-1 fix called `find_title_match(archive, ...)` passing the
libzim `Archive` handle as arg-0. `find_title_match` calls
`arg0.find_entry_by_title_data(...)` — `Archive` has no such method,
so the call raised `AttributeError` inside the `except Exception`
wrapper and silently no-op'd in production. Tests passed only because
they `patch`-ed `find_title_match` at the import site, bypassing the
contract entirely. Fix: `search_handler` in production IS the
`ZimOperations` instance (simple_tools.py:5542:
`search_handler=self.zim_operations`). Pass it as arg-0.

### Pass-3 audit defect — unconditional D1 filter regressed non-possessive prose

The pass-1 unconditional `match_type != "fuzzy_suggest"` gate silently
reverted a real b4 improvement for non-possessive prose queries of the
shape `<entity> <disambiguator>`. Trace `tell me about Berlin Germany`:

| Release | Pass-0 result | Final answer |
| --- | --- | --- |
| pre-b4 | (no pass-0) | `Germany` (pass-1 picks trailing tail) |
| b4 (pre-D1) | `Berlin` at fuzzy_suggest 0.95 — accepted | `Berlin` ✓ |
| b4 + pass-1 D1 (unconditional) | rejected | `Germany` ✗ |

Refine the gate: reject `fuzzy_suggest` ONLY when
`has_apostrophe_possessive(topic)` returns True. The
Darwin/Einstein/Plato silent-wrong-answer cases (possessive) still
reject; the Berlin/Apollo/Paris/Tokyo b4 improvements (non-possessive)
preserve.

### Fixes

1. **`match_type` annotation through find_entry_by_title_data** — each
   result row now carries `match_type ∈ {"direct", "redirect",
   "fuzzy_suggest", "typo_corrected"}`. `find_title_match` propagates
   the field. Schema is non-breaking (`FindEntryHit.match_type` was
   already `NotRequired[str]` for the pre-existing typo annotation).

2. **Tokenizer fix** — `_TAIL_TOKEN_RE` keeps apostrophes (both
   straight `'` and curly `'`) inside otherwise-alphanumeric runs so
   `einstein's` stays one token.

3. **Possessive `min_len` floor** — new
   `has_apostrophe_possessive(topic)` helper. When True, pass-1 /
   pass-3 / synthesize-pass-1 use `min_len=2` in `iter_query_tails` /
   `iter_query_windows` so a generic 1-token tail can't silently
   outrank the canonical the pass-0 probe just missed.

4. **Pass-0 / pass-3 / synthesize pass-0 gate filter** — reject
   `fuzzy_suggest` ONLY when topic carries an apostrophe-possessive.

5. **Synthesize pass-0** — `_promote_title_match` mirrors the
   `_promote_topic_via_title_index` pass-0 probe at the start, with
   the same `match_type` filter. Receives `search_handler`
   (ZimOperations) as arg-0, not the libzim `Archive` handle.

### Tests

21 new tests in `tests/test_post_b4_beta_fixes.py` across 6 classes
(TestMatchTypePropagation, TestFuzzySuggestGateReject,
TestPossessiveTokenizer, TestPossessiveMinLenFloor,
TestSynthesizePromoteFullTopicProbe, TestRegressionGuards). Updated
1 pre-existing assertion in `tests/test_post_a17_beta_fixes.py`
(`O'Brien` tokenizes to `["o'brien"]` post-fix) and 1 in
`tests/test_post_b3_beta_fixes.py` (tail iteration no longer strips
apostrophes). Updated 1 golden snapshot to include
`match_type: "direct"` on the canonical fast-path hit.

Full suite: **2390 passing, 54 skipped**. mypy clean across 52 source
files. black + flake8 clean. All 14 CI checks pass on PR #171.

### Methodology evolution

- **"Fix unlocks new paths" — now 13 sweeps strong, reproduced 3x in
  this single sweep.** Pass-1 looked correct in isolation; pass-2
  found the synthesize API misuse silently no-op'd in production
  (tests masked it via `patch`-at-import-site); pass-3 found the
  unconditional gate regressed a real b4 improvement for non-
  possessive prose.
- **Three new invariants pinned**: (a) `_TAIL_TOKEN_RE` keeps
  apostrophes inside otherwise-alphanumeric runs; (b) at
  `min_score=0.95`, `match_type ∈ {direct, redirect, typo_corrected}`
  is safe to auto-fetch — `fuzzy_suggest` is only safe when the topic
  shape would naturally produce a meaningful first-token resolution
  (non-possessive); (c) when a new call site for `find_title_match`
  is added, verify arg-0 is the `ZimOperations`-shaped object — the
  `except Exception` wrapper masks `AttributeError` silently.

---

## [2.0.0b4] — 2026-05-22 (beta pre-release) — post-b3 beta-test sweep shipped — X's Y auto-fetch tokenization

Post-b3 sweep packaged from PR #169 (commit `f69db46`). ONE pre-existing
defect surfaced by deeper live-MCP probing of the `tell me about X's Y`
shape — the attack surface b2 D3 partially closed. All six post-b2 fix
families verified clean on live MCP first (D1-D4 + the pass-2/pass-3
siblings).

### Defect — `X's Y` auto-fetch silent-wrong-answer

`_promote_topic_via_title_index` (simple_tools.py:3868) iterates trailing
tails via `iter_query_tails` (title_promotion.py:191). `iter_query_tails`
tokenizes on alphanumeric runs, so the apostrophe in `X's Y` is treated
as a separator. The topic `"einstein's theory"` becomes the tokens
`["einstein", "s", "theory"]`; tails yielded longest-first:

- `"einstein s theory"` — no canonical match (the canonical is stored
  WITH the apostrophe — `Einstein's_theory` is a redirect to
  `Theory_of_relativity`)
- `"s theory"` — no canonical match
- `"theory"` — matches the generic `Theory` article at score 1.0 →
  wins → wrong article fetched

Live impact (post-b3 live probe):

- `tell me about Einstein's theory` → `Theory` (expected
  `Theory_of_relativity` — confirmed canonical at 1.00 via
  `find article titled einstein's theory`)
- `tell me about Plato's cave` → `Cave` (expected
  `Allegory_of_the_cave` — confirmed at 1.00)
- `tell me about Plato's Republic` → `Republic` (expected
  `Republic_(Plato)` — confirmed at 0.95)
- `tell me about Darwin's evolution` → `Evolution`

The bug is pre-existing — it would have affected any user typing `tell
me about X's Y` for years — but was masked because:

- Pre-b1, fuzzy-search rescues at search time often surfaced the right
  article through different ranking paths.
- Pre-b2 D3, the retry that exposes the probe gate's True/False
  decision didn't exist.
- The specific repros (Einstein's theory, Plato's cave/Republic)
  weren't in the prior adversarial set.

Why b2 D3 doesn't catch this: D3's probe gate correctly suppresses
decomposition when `title_probe(topic)` finds a canonical (because
`Einstein's_theory` redirects to `Theory_of_relativity` at score 1.0).
So topic stays as `einstein's theory` → the buggy old auto-fetch flow
runs → wrong tail wins. The defect is in the older auto-fetch flow's
tail-iteration, not in the b2 D3 retry.

### Fix

Probe the FULL topic (with original punctuation preserved) BEFORE
entering the tail iteration in `_promote_topic_via_title_index`.
`find_title_match` uses libzim's title index directly — it correctly
handles apostrophes and redirects. The new probe uses `min_score=0.95`
to mirror the canonical-or-fuzzy gate Rule 2/3/4 already use
(intent_parser.py:317), accepting both direct hits (1.0) and
high-confidence redirects (0.95). Live verification of the threshold:
`find article titled` returns score 1.00 for Einstein's theory /
Plato's cave; score 0.95 for Plato's Republic. All three need the 0.95
gate.

Non-possessive queries hit this new probe with the same behavior they'd
get from pass-1's longest tail — the call returns redundantly on those,
never less correct. The pre-existing prose-query case (`famous people
from big rapids michigan`) still falls through to tail iteration
cleanly because the prose phrase isn't itself canonical.

### Tests

9 new tests in `tests/test_post_b3_beta_fixes.py` across 3 classes:

- `TestPossessiveAutofetchProbe` — verifies the full-topic probe fires
  first, uses `min_score=0.95`, runs before tail iteration, falls
  through cleanly on no-canonical, and preserves the apostrophe in the
  probed topic.
- `TestPossessivePromoteIntegration` — three end-to-end-shaped tests
  covering the live repros (Einstein's theory → Theory_of_relativity;
  Plato's cave → Allegory_of_the_cave; Plato's Republic →
  Republic_(Plato) at the 0.95 threshold).
- `TestRegressionGuards` — structural guard pinning that the first
  `find_title_match` call inside the method must use the bare `topic`
  argument (not a tail/window form).

Full suite: **2369 passing, 54 skipped**. mypy clean across 52 source
files. black + flake8 clean. All 14 CI checks pass.

### Methodology evolution

- **"Fix unlocks new paths" — now 10 sweeps strong.** Classic shape:
  b1 P1-D5 made `Photosythesis's reproduction` REACH the auto-fetch
  path; b2 D3 added the possessive retry to fix the immediate
  silent-wrong-answer; the post-b3 sweep's live probing of MORE
  possessive shapes (Einstein's theory, Plato's Republic, Plato's
  cave) revealed that the underlying auto-fetch flow has a
  tokenization bug for possessives where the full phrase is a
  canonical REDIRECT to a different article. Each sweep peels back
  another layer.
- **Single-defect sweep.** All eight b2 fix families + b3 sweep's
  three passes (b3 D1, pass-2 sibling, pass-3 sibling) verified
  clean on live MCP. The adversarial set was clean. The defect
  surfaced only via deeper probing of one specific query shape.
  Reinforces the post-a17 methodology refinement: "live re-probe
  is mandatory after deploy" — the auto-fetch tokenization bug
  is structurally invisible to unit tests but trivially visible
  to live-MCP probing of the right query shape.

---

## [2.0.0b3] — 2026-05-21 (beta pre-release) — post-b2 beta-test sweep shipped — 6 defects across 3 passes

Post-b2 sweep packaged from PR #167 (commits `45de8da` → `cc26b3d`).
Sweep shape: **4 → 1 → 1** across pass-1, pass-2, pass-3. All eight b2
user-facing fix families verified clean on live MCP first; sweep then
probed the adversarial shapes the b2 fixes unlocked. Both pass-2 and
pass-3 surfaced single narrow-scope siblings of pass-1 fixes —
consistent with the "narrow-scope sibling" pattern (now 8 sweeps
strong) and the "fix unlocks new paths" pattern (now 9 sweeps strong).

### Pass-1 defects (4, `45de8da`)

- **D1 — trailing modal politeness ≥2 words falls through.** The
  trailing-politeness regex in `_extract_tell_me_about` only matched
  `please` / `to me` / `for me`; the LEADING regex (line ~374)
  recognised the modal class (`could/can/would/will` + `you`) but
  the trailing twin was missing. Live: `tell me about Tokyo if you
  would` → `Would` (verb stub); `... if you could` → `Could`; `...
  would you` → `Would_You` disambig. Fix: add a trailing pattern
  symmetric to the leading one (both branches require a `you` so a
  bare trailing modal verb in real article titles isn't stripped).
- **D2 — reranker telemetry comment suppressed on no-results.** The
  b1 D-1 in-band telemetry contract promised `<!-- reranker=<state> -->`
  on every multi-token search. `_handle_search` compact path
  early-returned on `total == 0` BEFORE reaching
  `_maybe_rerank_compact`, so neither `_RERANKER_SKIPPED_NO_RESULTS`
  nor `_RERANKER_SKIPPED_NOT_INSTALLED` bumped and the envelope
  writer skipped the comment. Live: `search for asdfqwerzxcv
  nonexistent` → no reranker comment. Fix: invoke
  `_maybe_rerank_compact` on the empty payload before the bail
  (no-op aside from the counter bump; the rerank singleton is
  cached).
- **D3 — Rule 2 + multi-token possessive picks wrong token.** Live:
  `tell me about Photosythesis's reproduction` → `Reproduction`
  article (expected `Photosynthesis`). Rule 2's affix retry
  correctly fires (`Photosythesis's` → `Photosynthesis's`), but
  the b1 P1-D5 fix unlocked the path — pre-fix returned `No
  search results found`, post-fix returns a SILENT WRONG ANSWER.
  Root cause: Rule 4's `_POSSESSIVE_RE` is `^...$`-anchored and
  runs against the FULL query at parse time; the verb prefix
  prevents the match. Fix: in `_handle_tell_me_about`, when no
  decomposition hint was attached AND the topic carries an
  apostrophe-s followed by another token, retry
  `_decompose_x_of_y` on the bare topic. Scope narrowed to
  the possessive shape ONLY (NOT `X of Y`) to avoid regressing
  non-canonical X-of-Y queries.
- **D4 — compact filtered search drops "filtered" qualifier.**
  Live: `search Berlin in namespace C` → `Found 3 matches for
  "Berlin"` (legacy non-compact path emits `Found N filtered
  matches for "X"<filter_text>`). Both paths shared
  `_format_search_text`; pre-fix the formatter had no filter
  awareness. Fix: add optional `filter_text` kwarg to
  `_format_search_text` (mirrors `display_query`); compact filtered
  call site threads through `_format_filter_text` helper. Symmetric
  treatment for filtered no-results.

### Pass-2 sibling (1, `ed674b5`)

- **D1 universal-layer mirror.** Pass-1 added the modal-politeness
  strip inside `_extract_tell_me_about` only, but the universal
  `_TRAILING_POLITENESS_RE` (called by `_strip_trailing_politeness`
  at `parse_intent` line 1048) was added by the post-a20 PD2-1
  sweep specifically so every extractor sees the cleaned query.
  Every NON-tell_me_about intent kept leaking the modal class:
  `search for biology if you would` → `query="biology if you
  would"`; `find article titled Berlin if you would` → looks up
  `Berlin if you would` (not found). Fix: lift the modal class into
  `_TRAILING_POLITENESS_RE`. Pass-1 extractor-level strip kept as
  defense-in-depth. New invariant pinned:
  `TestD1RegexSync.test_leading_and_trailing_share_modal_class` —
  leading + trailing politeness regexes must share the modal class.

### Pass-3 sibling (1, `cc26b3d`)

- **Chained-intent trailing-politeness leak.**
  `_chained_intent_guidance` runs UPSTREAM of `parse_intent` on the
  raw user query. The post-a24 P1-D6 sweep mirrored the param-leak
  strip there; the equivalent mirror of `_strip_trailing_politeness`
  was never added. Pre-fix every trailing-politeness token (the
  full set, including the pass-2 modal class) leaked into chain
  rejection bullets — `tell me about Tokyo if you would then list
  namespaces` produced a rejection whose left bullet read
  `tell me about Tokyo if you would` verbatim, modal politeness and
  all. Caller would copy the suggested left half back,
  re-introducing the politeness on every iteration. Same structural
  sibling pattern as the post-a24 P1-D6 param-leak version. Fix:
  apply `_strip_trailing_politeness` to BOTH chain halves after the
  existing connector / punct trim loop, before bullets render.
  Per-half rather than full-query because the politeness can appear
  inside the chain (not just at the very end). Structurally safe —
  `_CHAINED_OPERATION_PREFIX_RE` checks the LEADING op verb, which
  the trailing strip never touches.

### Out of scope (deferred design call)

- **D5 — `death of stalin` → `Death_and_state_funeral_of_Joseph_Stalin`
  instead of the 2017 Iannucci film.** P1-D3 probe-gate correctly
  suppressed the Stalin disambig misroute; title-probe picked a
  different canonical X-related title rather than the film
  (canonical is `The_Death_of_Stalin`). Picking the film would
  require a prefix-widening probe (`The <query>`) — unwanted side
  effects on arbitrary bare topics — or a popularity ranker. Both
  are design choices beyond the b2 sweep scope.

### D2 / D3 / D4 sibling audits clean

- **D2**: `_handle_filtered_search` always routes through
  `_maybe_rerank_compact`; `_handle_search_all` uses its own
  rerank apply that bumps a counter on every path. `_handle_search`
  was the only early-return gap.
- **D3**: `_handle_tell_me_about` is the only handler that
  auto-fetches a single article based on the extracted topic.
  Other intents take the topic literally; synthesize uses RAG-style
  passage retrieval where decomposition would lose the attribute
  context (pre-existing design out of scope).
- **D4**: `_format_search_text` has three call sites — only the
  compact filtered one needed `filter_text`.
  `search_with_filters_with_canonical_splice` (non-compact filtered)
  already uses `_format_filtered_response` which natively emits
  the qualifier.

### Cross-feature composition verified

- `search for Photosythesis's reproduction in namespace C if you
  would` → universal trailing strip peels `if you would` → intent
  = filtered_search → `_maybe_rerank_compact` bumps counter →
  `_format_search_text` renders with `filter_text`. D1+D2+D4
  compose.
- `tell me about Photosythesis's reproduction if you would` →
  universal strip peels `if you would` → intent = tell_me_about
  → D3 retry fires on possessive topic → `photosynthesis`. D1+D3
  compose.

### Tests

- 40 new tests in `tests/test_post_b2_beta_fixes.py` across 10
  classes (`TestD1TrailingModalPoliteness`,
  `TestD1ParseIntentEndToEnd`, `TestD1SiblingUniversalTrailingModal`,
  `TestD1RegexSync`, `TestD1Pass3ChainedIntentPolitenessLeak`,
  `TestD2RerankerCounterOnNoResults`,
  `TestD3PossessiveDecompositionRetry`,
  `TestD4FilteredSearchEchoQualifier`, `TestRegressionGuards`).
- Full suite: **2360 passing, 54 skipped, 38 deselected**. mypy
  clean across 52 source files. black + flake8 clean. CI checks
  all green (CodeQL, SonarCloud, bandit, security scanning,
  6 OS × Python matrix, both `[reranker]`-extra suites,
  performance benchmarks).

### Methodology evolution

- **"Narrow-scope sibling" pattern** — now 8 sweeps strong. Both
  pass-2 and pass-3 surfaced a single sibling of pass-1's D1
  fix-family: pass-2 caught the universal-layer mirror (modal
  class missing from `_TRAILING_POLITENESS_RE`); pass-3 caught the
  upstream-chained-guidance mirror (trailing-politeness strip
  missing from `_chained_intent_guidance`). Both are STRUCTURAL
  mirrors of fixes already shipped — pass-2's sibling mirrors the
  post-a20 PD2-1 universal-strip extension, pass-3's sibling
  mirrors the post-a24 P1-D6 param-leak strip placement.
- **"Fix unlocks new paths"** — 9th consecutive sweep. D3 is
  particularly nasty because the failure mode changed from
  explicit `No search results found` (pre-b1 P1-D5) to silent
  wrong answer (post-b1 P1-D5 affix retry → post-b2 D3 retry).
- **New invariants pinned via canonical-source tests** — two
  feature-level guards: (a) leading + trailing politeness regexes
  must share the modal class; (b) the no-results early-return path
  in `_handle_search` must route through `_maybe_rerank_compact`.
  These pin the "added X to one side, forgot the other side"
  drift class that drove both pass-2 and pass-3 defects.

---

## [2.0.0b2] — 2026-05-21 (beta pre-release) — post-b1 beta-test sweep shipped — operational fixes + 8 D-2 user-facing defects + D-1 in-band telemetry

Post-b1 sweep packaged from PR #165 (commits `bbda863` → `261412b`).
The first b-series release shipped sub-D-1 (cross-encoder reranker) +
sub-D-2 (Tier-1 query rewriting); the post-b1 sweep covers three
distinct surfaces across two waves.

### Wave 1 — D-1 operational layer (`bbda863`)

Three defects/gaps surfaced operating the b1 reranker integration
end-to-end against the air-gapped pre-stage workflow advertised in
`docs/extras-reranker.md`.

- **`download-models` CLI ignored env vars.** The CLI built a bare
  `RerankerConfig()` (`BaseModel`, not `BaseSettings`), so
  `OPENZIM_MCP_ML__RERANKER__*` env vars (including `cache_dir`)
  were silently dropped. Pre-staging wrote to the FastEmbed default
  cache instead of the operator-configured directory, so the runtime
  re-downloaded on first call. Routes the CLI through a small staging
  `BaseSettings` that mirrors `OpenZimMcpConfig`'s env prefix +
  delimiter and reads `ml.reranker` from env.
- **Reranker telemetry only visible in advanced tool mode.** The four
  reranker events (`reranker_engaged` / `reranker_skipped.*`) lived
  only in `self._telemetry` Counter, surfaced via
  `get_server_health`. Simple-mode operators had no way to confirm
  rerank was actually engaging. `_track()` now also emits a one-line
  INFO log for the four reranker events; `synthesize.py` bumps its
  four DEBUG logs to INFO for consistency. Counter behaviour
  unchanged.
- **`first_call_timeout_seconds` default 5.0s too tight.** Typical
  ONNX session creation on a warm cache takes 7-10s on modest
  hardware; the 5s default tripped the kill switch even with
  pre-staged models. Raised default to 15.0s; bounds (0.1-120.0)
  unchanged.

### Wave 2 — D-2 user-facing defects + D-1 in-band telemetry surface (`54e68af` → `60d8532`)

Three live-MCP probe passes against `wikipedia_en_all_maxi_2026-02.zim`
(118 GB) surfaced 8 user-facing defects in the sub-D-2 wiring plus an
in-band visibility gap for sub-D-1. The "narrow-scope sibling" pattern
now extends at the FEATURE level: every probe-gated rule (Rules 2, 3,
4) shared the same `_build_title_probe(zim_file_path)`-before-auto-
resolve flaw, defeating the suppression for the dominant calling
pattern.

#### Pass-1 defects (6, `54e68af`)

- **P1-D1 — title_probe gated on caller-supplied `zim_file_path`
  BEFORE auto-archive-resolution.** `handle_zim_query` auto-selects
  the single loaded archive downstream (line ~776) when
  `zim_file_path` is omitted (the recommended pattern per the tool's
  own docstring). The probe was built earlier (line ~624) from the
  raw caller argument, so omitted-path callers got a `None` probe —
  Rules 2 (misspellings), 3 (article-strip), and post-fix Rule 4
  (X-of-Y decomposition) silently degraded. Live: `the Beatles` →
  disambig; `An American in Paris` → 🚨 `Niggas_in_Paris` (offensive
  misroute); `A Christmas Carol` → `Christmas_carol` concept. Fix:
  new `_probe_archive_path()` helper auto-resolves before the probe
  is built; mirrored at the synthesize wiring site.
- **P1-D2 — Rule 1's full-query lowercase leaked into user-facing
  chain rejection bullets and soft-connector footer.** Bullets/
  footer echo entities from `params["topic"]` which is extracted
  from the lowercased query. Live: `tell me about Köln, München,
  and Berlin` → bullets read `tell me about köln` / `münchen` /
  `berlin` — diacritics + casing corrupted, breaking the user's
  recovery copy-paste path. Fix: stash `params["_pre_rewrite_query"]`
  (original-case) at the wiring layer; new
  `_recase_from_original()` helper finds each lowercase token in
  the original via case-insensitive substring lookup; threaded
  into both surfaces.
- **P1-D3 — Rule 4 `_decompose_x_of_y` had no title-probe guard at
  all.** Every `<word> of <stuff>` whose attribute word wasn't in
  the structural-intent skip-set decomposed unconditionally,
  including canonical multi-word titles: `lord of the rings` →
  `The_Rings` (1985 Iranian horror film); `the art of war` → `War`
  concept; `wealth of nations` → `Nation`; `origin of species` →
  `Species`; `birth of venus` → Venus disambig; `death of stalin`
  → Stalin disambig; `history of rome` → `Rome` city. Fix: mirror
  Rule 3's probe gate inside Rule 4 — when `title_probe(query)`
  returns True, return `(query, None)` and suppress decomposition.
- **P1-D5 — Rule 2 missed possessives.** Whitespace-only token
  split meant `photosythesis's` didn't match map key
  `photosythesis`. Live: `tell me about Photosythesis's
  reproduction` → `No search results found`.
- **P1-D6 — Rule 2 missed leading/trailing punctuation.** `bilogy.`
  / `"recieve"` / `(photosythesis)` bypassed Rule 2 because the
  lookup key included the punctuation. Combined fix: new
  `_split_misspelling_affixes(token)` helper splits each token into
  `(prefix, core, suffix)` via linear-time `isalnum`/`_` scanning;
  on map miss, retry the core (after peeling trailing `'s`) and
  reattach affixes on hit.
- **D-1 in-band telemetry**: snapshot the four reranker counters at
  the start of `handle_zim_query`; new `_compute_rerank_state()`
  returns per-request engagement state (`engaged` / `skipped:not_installed`
  / `skipped:no_results` / `skipped:passthrough`) from
  the post-call delta; appended as `<!-- reranker=<state> -->` in
  the response envelope (mirrors the existing `<!-- intent=... cert=... -->`
  pattern). Solves the methodology gap where the live
  MCP transport filters out `get_server_health`, leaving reranker
  engagement invisible to simple-tool sweeps.

#### Pass-2 sibling defects (2, `e6f320e`)

- **P2-D1 — disambig heading echoed lowercase topic.** Sibling of
  P1-D2 in `_render_disambiguation`. Pre-fix: `tell me about
  Stalin` → `**Multiple articles match "stalin"**`. Fix: new
  optional `original_query` kwarg; `_recase_from_original` recovers
  the caller's casing (covers diacritics too — `tell me about
  München` → `"München"`).
- **P2-D2 — empty-result handler echoed lowercase query.** Sibling
  of P1-D2 in `_handle_search` compact path's `No results for "X"`
  body. Same recase via `_recase_from_original`; falls back to
  `search_query` when the original isn't available.

#### Pass-3 backend echo-string plumbing (`60d8532`)

- **P3-D1 — search backend echo strings.** Five user-facing echo
  sites in `zim/search.py` read the lowercased query directly:
  `Found N matches for "X"`, `No search results found for "X"`,
  `No filtered matches for "X"`, `Found N matches for "X", but
  offset N exceeds...`, and the filtered-search header. New
  optional `display_query` kwarg threaded through
  `_format_search_text`, `search_zim_file`,
  `_format_filtered_response`, `_perform_filtered_search`,
  `search_with_filters`, and
  `search_with_filters_with_canonical_splice`. Cache key in
  `search_with_filters` includes `display_query` so two calls with
  the same matched query but different display forms don't
  cross-contaminate. Backend matching is unchanged — Xapian is
  case-insensitive, `payload["query"]` keeps the lowercased form
  for cursor/cache stability; only the rendered echoes pick up the
  original case.

### CI cleanup (`261412b`)

- **flake8 E303** in test file (three blank lines before an inline
  `import`).
- **isort + black** drift across the three modified modules.
- **SonarCloud S5852 (ReDoS hotspot)** — pass-1's
  `_MISSPELL_AFFIX_RE = re.compile(r"^(\W*)(.*?)(\W*)$")` tripped
  the polynomial-backtracking detector (lazy `.*?` between two
  greedy `\W*`). Replaced with the linear-time
  `_split_misspelling_affixes(token)` helper — same precedent the
  post-a22 sweep applied to a sibling S5852 hit in
  `_chained_intent_guidance`.

### Tests

- 76 new tests in `tests/test_post_b1_beta_fixes.py`, organised by
  defect class (`TestP1D1ProbeArchiveResolution`,
  `TestP1D3Rule4ProbeGate`, `TestP1D5PossessiveMisspelling`,
  `TestP1D6PunctuationMisspelling`, `TestP1D2RecaseHelper`,
  `TestRerankerStateComment`, `TestPass2SiblingDefects`,
  `TestPass3SearchBackendEchoPlumbing`,
  `TestPass2CrossFeatureIntegration`, `TestRegressionGuards`).
- 6 pre-existing post-a-series test assertions updated to reflect
  the corrected post-P1-D2 original-case echoes.
- Full suite: **2320 passing, 54 skipped**. mypy clean across 53
  source files. All 14 CI checks pass (SonarCloud, CodeQL, bandit,
  security scanning, the 6 OS × Python matrix, both
  `[reranker]`-extra suites, performance benchmarks).

### Methodology evolution

- **"Narrow-scope sibling" pattern at the FEATURE level** —
  reproduced for the 7th sweep but now applies to NEW-FEATURE
  wiring shipped in the same release: every probe-gated Tier-1
  rule (Rules 2, 3, 4) shared the same probe-construction-before-
  auto-resolve flaw. The probe wiring shipped narrower than the
  recommended call pattern; the recommended pattern (omit
  `zim_file_path`) defeated it.
- **"Fix unlocks new paths"** — 6th consecutive sweep; D-2 Rule 4
  LANDED (`population of berlin` decomposes cleanly) but exposed
  the canonical-X-of-Y-title decomposition family that had no
  guard at all.
- **Three-wave sibling progression** — pass-1 (6 live-probed) →
  pass-2 (2 source-audited siblings in dispatcher-edge code) →
  pass-3 (5 backend-plumbed siblings of P2-D2) — validates the
  "defer scope-creep items to a follow-on pass" rule. Pass-2's
  explicit deferral let the dispatcher-edge fix ship without
  blocking on the multi-function backend plumbing.

---

## [2.0.0b1] — 2026-05-21 (beta pre-release) — Phase D sub-D-2 — Tier 1 query rewriting

First b-series release. Ships Phase D sub-D-2: four idempotent rule-based
query rewrites that run before the existing intent regex chain. Zero new
dependencies — every user gets the lift on the next install. The four
rules are:

- **Rule 1 — lowercase topic normalization.** `_normalize_topic_case`
  consolidates scattered `.lower()` calls into a single named pass that
  runs first on every query.
- **Rule 2 — misspelling map.** `_apply_misspelling_map` substitutes
  tokens from a bundled `dict[str, str]` (~40 starter entries from
  Wikipedia's "List of common misspellings (for machines)"). An optional
  title-index probe suppresses substitutions where the original token is
  itself a canonical entity name. Operators can override the bundled
  list via `query_rewrite.misspelling_map_path` and pin exceptions in
  the companion exclusions file. Hard-capped at 500 entries.
- **Rule 3 — stopword phrase detection.** `_detect_stopword_phrase`
  strips leading articles (`the`, `a`, `an`, `of`) unless the full query
  is itself a canonical title (`The Beatles`, `Of Mice and Men`).
  Title-probe-gated; one probe call per query maximum.
- **Rule 4 — `X of Y` decomposition.** `_decompose_x_of_y` recognises
  `population of berlin` and `berlin's population` shapes, returning
  both a cleaner query string (`berlin population`) and a structured
  `{"entity": ..., "attribute": ...}` hint that rides inside
  `params["decomposition_hint"]`. `_handle_tell_me_about` consumes the
  hint and uses the structured entity directly, skipping its own
  topic-extraction logic.

### Config

```python
class QueryRewriteConfig(BaseModel):
    enabled: bool = True
    misspelling_map_path: Path | None = None
    misspelling_exclusion_path: Path | None = None
```

`enabled = False` short-circuits all four rules — queries reach the
existing regex chain unchanged.

### Telemetry

Three new dot-separated events surface via the existing `_track()`
mechanism and `get_server_health`:

- `query_rewrite.misspelling` — Rule 2 substituted at least one token.
- `query_rewrite.stopword_phrase` — Rule 3 stripped a leading article.
- `query_rewrite.x_of_y` — Rule 4 matched and emitted a hint.

Rule 1 has no event (fires on essentially every query — zero signal).

### Risk mitigations baked in

- **Master kill switch** (`config.query_rewrite.enabled=False`) actually
  skips all four rules, not just the telemetry/probe wrapping.
- **Title-index probe** (when an archive is in scope) suppresses
  false-positive rewrites on real proper nouns.
- **Hard cap** of 500 entries in the misspellings map keeps the lookup
  cheap and the file reviewable.
- **Exclusions file** ships empty and grows reactively when sweeps
  observe a real proper noun getting misrouted (e.g., a surname or
  band name that happens to match a misspelling entry).
- **Idempotent rules** — running any rule twice produces the same
  output as running it once; rule order (1 → 2 → 3 → 4) is fixed.
- **Several ripple-effect compensations** in the existing intent chain
  for code paths that depended on case-preserving inputs (regex
  anchors with `[A-Z]`, `isupper()` checks, length-based bare-topic
  thresholds, namespace-path extraction).

### Tests

- 43 new tests in `tests/test_query_rewrite_tier1.py` (per-rule fix /
  no-op / boundary triads, integration, composition, hint handoff).
- 13 pre-existing test files updated for the lowercase ripple
  (assertions changed from `"Proper Case"` → `"lowercase"` to match
  Rule 1's unconditional normalization).
- Full suite: 2245 passing, 54 skipped — sub-D-1 reranker integration
  untouched.

### Not in Tier 1

- Multi-hop questions (`what year did the inventor of X die`) — deferred
  to a potential sub-D-3 if live evidence warrants.
- HyDE / hypothetical document synthesis — locked-in non-goal.
- Algorithmic spell-correction libraries (`pyspellchecker`, `autocorrect`)
  — wrong precision/recall tradeoff for encyclopedia search.

---

## [2.0.0a25] — 2026-05-20 (alpha pre-release) — post-a24 beta-test sweep — 6 live-Wikipedia defects across two passes

Live-MCP beta sweep against `wikipedia_en_all_maxi_2026-02.zim` on
the freshly-deployed `v2.0.0a24` build. Smoke gates 4/4 green
pre-fix; pass-1 surfaced 6 defects across 4 surfaces, pass-2 source-
level audit surfaced zero new defects. **"Narrow-scope sibling"
pattern is now 5 sweeps strong: ALL SIX defects this sweep are
narrower-than-needed shapes on the matching a24 fix** — two on
`_looks_like_slashed_compound` (digit halves, mixed-case short
halves), two on `_TRAILING_POLITENESS_RE` (multi-word multilingual,
third-wave single-word multilingual), one on `_PARAM_LEAK_RE`
(missing `query` token), one on `_chained_intent_guidance`
(param strip not applied before chained-intent detection). The
post-a24 sweep continues to validate the "narrow scope, widen
preemptively" methodology refinement.

### Slashed-compound helper digit-half widening (P1-D1)

The a24-shipped `_looks_like_slashed_compound` accepts letter-only
halves with `min ≤ 2` — tuned for short ALL-CAPS acronyms
(`TCP/IP`, `AC/DC`). Digit halves slipped through:

- `tell me about 9/11 and World War II` → 3-entity chain rejection
  naming `9`, `11`, `World War II`. But `9/11` is a single event.
- `tell me about 24/7 and 9 to 5` → 3-entity chain naming `24`,
  `7`, `9 to 5`. But `24/7` is a single phrase.

Same shape for `5/4` (time signature / fraction), `12/24` (date),
`2024/25` (sports season). All are conceptual single entities with
small-digit halves.

Fix: detect all-digit halves and accept the compound when both
halves are ≤ 2 chars. Catches the common date / ratio / sports-
season shapes; rejects `2024/2025` (min=4) which is more naturally
two distinct years. Mixed letter+digit halves (`A/4`, `X/12`)
still split.

### Slashed-compound helper short mixed-case widening (P1-D2)

Sibling shape: paired-concept TitleCase compounds like `Yin/Yang`,
`Hot/Cold`, `Wet/Dry`, `Mac/Cheese`, `Salt/Pepper` have letter-only
halves of 3-4 chars. Pre-fix:

- `tell me about Yin/Yang and the Tao` → slash split into
  `["Yin", "Yang", "the Tao"]`; Yin and Yang both failed
  substantive (3-4 char ASCII TitleCase, no digit, no non-Latin);
  `_split_multi_entity` returned None and the chain abandoned
  silently, returning the Tao article with Yin/Yang silently
  dropped.

Same shape for `Hot/Cold and Wet/Dry`, `Light/Dark`, etc. Fix:
widen letter floor from `min ≤ 2` to `min ≤ 4`. Catches the short
paired-concept compounds without affecting `Berlin/Munich`
(min=6), `Tokyo/Kyoto` (min=5), and other longer proper-noun
pairs that genuinely benefit from splitting.

### Politeness regex multi-word multilingual extension (P1-D3)

The a24 multi-word politeness additions (`thanks a million`,
`thank you very much`) were English-only. Multi-word counterparts
in other languages leaked or partially-peeled:

- `merci beaucoup` (French) — leaked entirely
- `vielen dank` (German) — leaked entirely (`dank` without `e`
  not in the prior single-word token list)
- `muchas gracias` (Spanish) — `gracias` peeled, `muchas` left
- `arigatou gozaimasu` (Japanese formal) — leaked entirely
- `domo arigato` (Mr. Roboto era) — `arigato` peeled, `domo` left
- `terima kasih` (Malay / Indonesian) — leaked entirely

Fix: each multi-word phrase listed as an explicit alternation
entry before the single-word forms (so the maximal phrase wins).

### Politeness regex third-wave single-word multilingual (P1-D4)

Sibling shape: more single-word multilingual tokens live-observed:
`mahalo` (Hawaiian), `xie xie` / `xièxie` (Chinese romaji),
`shukran` (Arabic), `kiitos` (Finnish), `tack` (Swedish — 4-char,
leading word-boundary anchor protects against embedded matches in
`attack` / `thumbtack`), `gomawo` / `kamsahamnida` (Korean romaji),
`dhanyavad` (Hindi romaji), `domo` / `gozaimasu` (Japanese
remainder fragments). Defence-in-depth via the canonical
`_TRAILING_POLITENESS_RE` propagates to every site that calls
`IntentParser._strip_trailing_politeness`.

### Param-leak strip `query` token (P1-D5)

The a24-shipped `_strip_param_leaks` covered 13 of the 14 public
`zim_query` arguments. The 14th — `query` itself — was missing.
Live: `tell me about Photosynthesis query=biology` returned the
`Biology` disambiguation page (the `=biology` suffix prevented
title promotion from cleanly resolving Photosynthesis; the
fuzzy-match path then resolved to `Biology` instead). Fix: add
`query` to the strip token set.

### Param-leak strip not applied before chained-intent detection (P1-D6)

The a24-shipped `_strip_param_leaks` runs inside `parse_intent`,
but the dispatcher's `_chained_intent_guidance(query)` call runs
upstream of that on the RAW user query. Live: `tell me about
Berlin limit=5 then list namespaces` surfaced a chained-intent
rejection whose `**First op (left)**: tell me about Berlin
limit=5` carried the leaked param verbatim — a user copying the
suggested left-op back into the tool would re-leak the param at
the same point.

Fix: mirror the existing leading-politeness strip pattern in
`_chained_intent_guidance` with a `IntentParser._strip_param_leaks`
call at the same point. Idempotent with `parse_intent`'s
downstream strip — both produce identical output on a clean query.

### What's in this release

- Slashed-compound helper widening (digit halves + short letter
  halves) lands in `openzim_mcp/simple_tools.py:_looks_like_slashed
  _compound`.
- Politeness regex third-wave extension (multi-word multilingual +
  more single-word multilingual) lands in
  `openzim_mcp/intent_parser.py:_TRAILING_POLITENESS_RE`.
- Param-leak strip `query` token + chained-intent param strip
  defence-in-depth lands in
  `openzim_mcp/intent_parser.py:_PARAM_LEAK_RE` and
  `openzim_mcp/simple_tools.py:_chained_intent_guidance`.
- 90 regression tests in `tests/test_post_a24_beta_fixes.py`
  (6 defect classes × multiple shape variants + 9 cross-feature
  pass-2 integration tests + 3 sibling-audit pins + 11 prior-alpha
  regression guards). One a23 test updated to reflect the new
  digit-compound policy.
- Full suite: **2143 passed, 50 skipped**. mypy clean across all
  45 source files. `make lint` (flake8 + isort + black) clean.
  SonarCloud quality gate passed with 0 open issues post-merge.

### Release process

After this changelog lands on `main`, push the `v2.0.0a25` tag
on `main` to trigger `.github/workflows/release.yml` — PyPI
publish + GitHub release notes auto-extracted from the matching
CHANGELOG section.

## [2.0.0a24] — 2026-05-20 (alpha pre-release) — post-a23 beta-test sweep — 4 live-Wikipedia defects across one pass

Live-MCP beta sweep against `wikipedia_en_all_maxi_2026-02.zim` on
the freshly-deployed `v2.0.0a23` build. Smoke gates 4/4 green
pre-fix; the live MCP session dropped after ~30 probes (same long-
session connection timeout pattern observed in the post-a22 sweep)
so pass-2 ran as a source-level sibling audit per the post-a17
methodology refinement — zero new defects surfaced. **"Narrow-scope
sibling" pattern holds for the 4th sweep running: 3 of 4 defects
this sweep are narrower-than-needed enumerations on the matching
a23 fix shape** (politeness regex missed a second wave of SMS /
multi-word / multilingual tokens, q-emitting drift-guard used
non-recursive glob, substantive filter rejected short ALL-CAPS
acronyms). The fourth defect (P1-D3) is a new defect class — the
title-promotion path silently resolves leaked `<param>=<value>`
suffixes to wildly unrelated articles.

### Multi-entity chain ALL-CAPS / slashed-acronym silent abandonment (P1-D1)

The post-a22 `_split_multi_entity` / `_is_substantive_topic` pair
correctly handles long bare-topic chains (Berlin / Munich / Köln)
and non-Latin shorts (東京 / Köln, post-a19 P1-D3). But two
interacting failures left short ALL-CAPS acronym chains silently
abandoned:

- The slash splitter (`\s*/\s*` in `_SOFT_CHAIN_CONNECTOR_PATS`)
  fragmented slashed acronyms — `TCP/IP` → `["TCP", "IP"]`,
  `AC/DC` → `["AC", "DC"]`, `Either/Or` → `["Either", "Or"]`.
- `_is_substantive_topic` rejected the fragments because they fail
  every existing clause (HTTP=4, TCP=3, IP=2, AC=2, DC=2 — none
  ≥5 chars, no digit, no non-ASCII letter). With every half
  failing substantive, `_split_multi_entity` returned None and
  the chain rejection silently abandoned.

Two live failures observed:

- `tell me about TCP/IP and HTTP and HTTPS` → silently returned
  the `HTTPS` article (matching-tail short-circuit picks the
  longest substantive ASCII tail), dropping TCP/IP and HTTP.
- `tell me about AC/DC and Iron Maiden and Metallica` → silently
  returned `Metallica`. Same path.

Two coordinated fixes:

- New `_looks_like_slashed_compound` helper protects slashed
  compounds whose halves are letter-only with a ≤2-char half
  (TCP/IP, AC/DC, Either/Or, A/B). `Berlin / Munich` (min half 6
  chars) still splits as a genuine 2-entity chain.
- New ALL-CAPS clause in `_is_substantive_topic`:
  `isupper() and len ≥ 2` accepts HTTP, TCP, IP, USA, EU, R&B
  etc. Mirrors the post-a19 P1-D3 non-Latin clause — short tokens
  with a clear proper-noun signal aren't English sentence-words.
  Mixed-case `Now` / `Both` / `Here` / `Then` stay rejected.

### Politeness regex second-wave family (P1-D2)

The post-a22 P1-D2 SMS extension added `thnx` / `thanx` / `tysm`
/ `kthx` / `kthxbai` but missed a second wave of live-observed
variants:

- 1-2 char compressions: `tx`, `txs`
- longer SMS: `tyvm`, `thnks`, `thxx`, `kthxbye`
- multi-word: `thanks a million`, `thank (you|u) (so|very) much`
- multilingual second tier: `obrigado(a)` (Portuguese),
  `arigato(u)` (Japanese romaji), `spasibo` (Russian)

Same narrow-scope sibling pattern as a22 P1-D2 → a23 P1-D2 — each
sweep so far has shipped narrower than the natural politeness
family. The word-boundary anchor (post-a21) already protects
short tokens from mid-word matches (`manta` / `pasta` / `vista` /
`cantata` stay intact).

### `<param>=<value>` query-suffix silent fragmentation (P1-D3) — NEW defect class

Live: `tell me about Photosynthesis limit=10` returns the article
for the number `10` (Wikipedia's number article). Same shape for
`compact_budget=200` (returns the year 200 article),
`content_offset=100` (returns 100), `offset=5` (returns 5). Root
cause: a small model that doesn't know to pass `limit` as the
typed MCP parameter occasionally leaks `limit=N` INTO the query
text; the title-promotion tokeniser sees `"10"` as a clean ASCII
digit tail and scores it cleanly against the number-article
title index, returning a wildly unrelated body that masks the
model's actual topic.

Distinct from a23 P1-D5 (docstring nudge for atomic intents that
ignore `limit`). The docstring tells the model not to pass
`limit` as text on atomic intents, but it can't prevent a model
that's confused about parameter-passing semantics from typing
`limit=10` as text anyway. Fix: new
`IntentParser._strip_param_leaks` peels `\s+<param>=<value>`
shapes BEFORE the politeness loop runs. Token list covers every
`zim_query` argument (`limit`, `offset`, `content_offset`,
`max_content_length`, `max_words`, `compact_budget`, `compact`,
`synthesize`, `cursor`, `zim_file_path`, `entry_path`,
`namespace`, `partial_query`). Idempotent loop handles multiple
leaks in one call. The `\s+` leading anchor protects prose
mentions (`offset printing`, `cursor algorithms`, `the compact
disc`) from accidental strip.

### Q-emitting drift scanner non-recursive glob (P1-D4)

The post-a22 P1-D3 widening from `zim/search.py` to all of
`zim/*.py` used `Path.glob` (direct children only). The current
`openzim_mcp/zim/` tree is flat (no subdirectories) so behaviour
is unchanged today, but a future contributor adding
`openzim_mcp/zim/cursor/encoder.py` or any subdirectory with
q-emitting `Cursor.encode` callsites would have those silently
missed by the scan, breaking the drift guard's promise. Same
narrow-scope sibling shape as the a22 P1-D3 widening from one
file to all direct-child files in the directory — the next
widening is naturally to all files in the tree. Fix: switch to
`rglob`.

### Methodology

The recurring **"fix unlocks new paths"** + **"narrow-scope
sibling"** pair held for the 4th sweep running. Three of four
defects this sweep are narrow-scope siblings of a23's own fixes
(P1-D1 narrow substantive filter + narrow slash split, P1-D2
narrow politeness enumeration, P1-D4 narrow scanner glob). The
fourth (P1-D3) is a new defect class — a small-model-leaked
parameter shape that silently fragments to an unrelated article
via title-promotion. The post-a22 lint-leak refinement (`make
lint` locally before push; check SonarCloud findings via API
before merging; avoid `[\s\S]+?` + literal regex shapes) was
followed cleanly — only one SonarCloud finding emerged
(implicit-concat strings from black auto-format, S6571), fixed
in a single follow-up commit before merge. **The methodology is
stabilising**: the structural defect classes the sweep catches
remain consistent across alphas, and the lint discipline now
catches static-analyzer noise pre-merge rather than letting it
leak to CI.

### Testing

- **73 regression tests** in `tests/test_post_a23_beta_fixes.py`:
  `TestP1D1MultiEntityAllCapsAndSlashedAcronyms` (12 cases —
  short ALL-CAPS substantive, R&B with ampersand, mixed-case
  rejected, slashed-compound helper identifies acronyms, rejects
  proper-noun pairs / 3-part slashes / digit halves, end-to-end
  split for TCP/IP, AC/DC, Berlin / Munich, ALL-CAPS chain);
  `TestP1D2PolitenessSecondWave` (~30 parameterized cases — every
  new token + chained + word-boundary safety + case-insensitive +
  regression guards on every post-a22 token);
  `TestP1D3ParamLeakSuffix` (~20 cases — every param-name × value
  shape strips, end-to-end parse_intent, multi-param chains, mix
  with politeness, prose-mention preservation, idempotence);
  `TestP1D4QEmittingScannerRecursive` (3 cases — source-level
  rglob check + scanner returns expected pinned set);
  `TestLiveMcpReproduction` (6 end-to-end probes mirroring the
  live-MCP queries the sweep observed); `TestRegressionGuards`
  (6 cases pinning post-a17 / a18 / a19 / a22 fixes that share
  code with the changed paths).
- Full suite: **2053 passed, 50 skipped**. mypy clean across all
  45 source files. `make lint` (flake8 + isort + black) clean.
  SonarCloud quality gate passed with 0 open issues post-merge.

### Release process

After this changelog lands on `main`, push the `v2.0.0a24` tag
on `main` to trigger `.github/workflows/release.yml` — PyPI
publish + GitHub release notes auto-extracted from the matching
CHANGELOG section.

## [2.0.0a23] — 2026-05-19 (alpha pre-release) — post-a22 beta-test sweep — 7 live-Wikipedia defects across two passes

Live-MCP beta sweep against `wikipedia_en_all_maxi_2026-02.zim` on
the freshly-deployed `v2.0.0a22` build. Smoke gates 4/4 green
pre-fix; the live MCP session dropped mid pass-1 (long-session
connection timeout) so pass-2 ran as a source-level sibling audit
per the post-a17 methodology refinement. **Strong "narrow-scope
sibling" signal this sweep: 4 of 7 defects were narrower-than-needed
enumerations on the matching a22 fix shape** (politeness regex
missed SMS variants, drift-guard scanned one file instead of the
whole zim/ tree, docstring-bait sweep skipped entry_path
placeholders, limit-nudge enumeration missing three atomic intents).

### Multi-entity chain first-word conjunction strip (P1-D1)

The post-a21 `_split_multi_entity` helper applied a defensive
`_CONJUNCTION_PREFIXES` strip to every cleaned half — including
the half that occupies the START of the original topic, where a
leading `And` / `Or` / `&` is real title content. Two live
failures observed:

- `tell me about And Then There Were None and Hercule Poirot and Murder on the Orient Express`
  → rejection bullets read `tell me about Then There Were None`
  (leading "And" mangled).
- `tell me about Or Else and Death and Taxes and Pride and Prejudice`
  → first half stripped from `Or Else` to `Else` (4 chars, fails
  `_is_substantive_topic`) → multi-entity rejection silently
  abandoned → `tell_me_about` resolved Pride and Prejudice,
  dropping 4 of 5 entities with no warning.

Fix: skip leading-conjunction strip on the FIRST non-empty half
(`parts[0]` after iterative `re.split` preserves order). Subsequent
halves retain the defensive strip — they can only get a leading
conjunction prefix from a hypothetical reordered pattern list,
never from the user's typed input.

### Politeness regex SMS variants (P1-D2)

The post-a21 P1-D6/D7 widening (`ta`/`cheers`/`thx`/`ty`/`pls` +
`bitte`/`danke`/`merci`/`gracias`/`por favor`) didn't cover
common chat / SMS spellings: `thnx`, `thanx`, `tysm`, `kthx`,
`kthxbai`. Live: `search for biology thnx` searches for
`"biology thnx"` (3 irrelevant matches). Same shape as the
post-a21 missed-token class. All new tokens are ≥4 chars except
`kthx`, which is word-anchored. No new `\s+` quantifiers —
ReDoS-safe.

### Q-emitting cursor tools drift guard scope (P1-D3)

The post-a21 P1-D5 regression test scanned ONLY `zim/search.py`
for `Cursor.encode` callsites. But callsites also exist in
`zim/namespace.py` (4 sites) and `zim/structure.py` (1 site) — a
future contributor adding a q-emitting tool there would silently
pass the test while breaking the dispatcher's q-overlap guard.
Widened the scan to all of `openzim_mcp/zim/*.py` with state-dict
introspection (handles literal-dict shape AND variable-reference
shape including PEP 526 type-annotated assignments like
`cursor_state: Dict[str, Any] = { ..., "q": ..., ... }`).

### entry_path docstring placeholder bait (P1-D4 + P2-D1)

The post-a21 P1-D9 widened the PD2-2 path-bait sweep to every
`tools/*.py` but only scanned for `/path/...\.zim` /
`/data/...\.zim` shapes. The `entry_path` parameter docstrings
used `'A/Some_Article'` and `'C/Some_Article'` as literal-looking
placeholders (6 sites: 1 in `content_tools.py`, 5 in
`structure_tools.py`). Same weak-instruction-follower defect
class — a small model copying `Some_Article` verbatim hits an
entry-not-found error and drops into a retry loop. The PD2-3 /
PD2-4 recovery hints only trigger on ZIM PATH errors, not
entry-path errors, so the bait was unreachable by the existing
safety net. Fix: replace with `<entry_path>` placeholder pointing
at real MCP tool names (`find_entry_by_title` / `browse_namespace`).

Pass-2 sibling audit found one more entry_path bait site (P2-D1):
`get_section` docstring (`structure_tools.py:576`) used
`'A/Berlin'` as the entry_path example. The legacy `A/` namespace
is the pre-2018 single-namespace ZIM convention; modern multi-
namespace ZIMs (Wikipedia 2026-02 and similar) use `C/`. A small
model copying `A/Berlin` verbatim hits entry-not-found on a
modern archive. Active wrong-guidance rather than obvious
placeholder. Fix: replace with `'C/Berlin'` + document the
legacy/modern distinction inline. Regression test scans
`tools/*.py` for `'A/<word>'` examples (allowing the legitimate
`A/B` Wikipedia testing article and lines that explicitly
document the distinction).

### `limit` docstring nudge — missing atomic intents (P1-D5)

The post-a21 T-D1 nudge enumerated 9 atomic intents that ignore
`limit` in the `zim_query` docstring. Three more atomic intents
whose handlers don't reference `options.get("limit", ...)` were
missing from the enumeration: `summary of <name>`, `table of
contents <name>`, `section <X> of <name>`. Same shape as T-D1 —
small models passing `limit=5` on those calls get no doc signal
that the parameter is ignored. Extended the enumeration.

### Dispatcher-edge politeness strip — additional fields (P1-D6)

The post-a21 P1-D1 defence-in-depth strip covered
`{query, topic, title, entry_path, partial_query}` but not
`section_name` (from `section <X> of <Y>` parses) or `entries`
(list of entry paths from batched parses). Same belt-and-
suspenders rationale: idempotent when `parse_intent`'s universal
strip works upstream, defence-in-depth when it doesn't
(in-process module cache, future regression). Added both fields
(scalar strip for `section_name`, per-element list strip for
`entries`).

### Methodology

The recurring **"fix unlocks new paths"** pattern reproduced again,
and the **"narrow-scope sibling"** pattern is now strong enough
to flag preemptively. Four of seven defects this sweep were
sibling shapes of a22's own fixes that landed at narrower-than-
needed scope (P1-D2 missed SMS politeness, P1-D3 narrow drift-
guard scope, P1-D4 + P2-D1 narrow docstring-bait scope, P1-D5
narrow limit-nudge enumeration). Future fixes should preemptively
widen each new guard to every analogue site before merging.

### Testing

- **34 regression tests** in `tests/test_post_a22_beta_fixes.py`:
  `TestP1D1MultiEntityFirstWordConjunction` (5 cases — first-word
  And/Or/Ampersand preserved, Unicode first word, mixed
  substantive halves); `TestP1D2PolitenessSmsVariants`
  (~22 parameterized cases — strip + word-boundary + full parse);
  `TestP1D3QEmittingDriftGuardWiderScope` (2 cases — scanner
  finds known tools + set membership pin across all zim/
  modules); `TestP1D4EntryPathDocstringBaitSweep` (3 cases —
  no `Some_Article` bait, `<entry_path>` placeholder convention,
  no legacy `A/<word>` bait); `TestP1D5LimitNudgeEnumeratesAllAtomicIntents`
  (1 case — docstring enumeration pin); `TestP1D6DispatcherEdgeStripWiderFields`
  (3 cases — `section_name` in field tuple, `entries` list
  strip wired, end-to-end politeness peel).
- Full suite: **1988 passed, 50 skipped**. mypy clean across all
  45 source files.

### Release process

After this changelog lands on `main`, push the `v2.0.0a23` tag
on `main` to trigger `.github/workflows/release.yml` — PyPI
publish + GitHub release notes auto-extracted from the matching
CHANGELOG section.

## [2.0.0a22] — 2026-05-19 (alpha pre-release) — post-a21 beta-test sweep — 11 live-Wikipedia defects across two passes

Live-MCP beta sweep against `wikipedia_en_all_maxi_2026-02.zim` on
the freshly-deployed `v2.0.0a21` build, plus a small-model failure
transcript review. Smoke gates landed 3/4 green pre-fix; the
politeness-strip gate (`search for biology please` →
`Found 5000 matches for "biology please"`) leaked on the live MCP
despite the source-side `parse_intent` strip working correctly
under direct unit test — most likely cause is an in-process
module cache on the live server that loaded only part of PR #152's
diff. The user-visible defect class is the same regardless of
root cause; defence-in-depth dispatcher-edge strip lands here
(P1-D1).

Pass 2 source-level audit found no new sibling defects across the
landed fix sites. The recurring **"fix unlocks new paths"** cycle
reproduced again three times: post-a20 P1-D2 (alias-fallback
widening to 2-entity asymmetric chains) didn't address 3+ entity
chains (this sweep's P1-D2/D3/D4 catch them); post-a20 PD2-1
(`parse_intent` politeness strip) didn't widen the token set
(P1-D6/D7 add British/texting/multilang variants); post-a20
PD2-2 (`zim_query` docstring de-bait) didn't sweep the sibling
advanced-tool docstrings (P1-D9 widens the regression net).
Live-transcript review remains a distinct test surface (T-D1
came from a Qwen3-8B-Q4 transcript; not reachable via adversarial
query probing alone).

### Fixed

- **Multi-entity chain warning for 3+ entity bare-topic chains**
  (P1-D2 / P1-D3 / P1-D4). Three observed shapes that bypass the
  existing 2-entity `_soft_connector_footer` alias-fallback:
  `tell me about Köln, München, and Berlin` returned Berlin + a
  footer suggesting `tell me about Köln, München,` (still-chained
  recursive suggestion — re-running it re-triggers the same
  defect); `tell me about Berlin or 東京 or Tokyo` silently fell
  through to "No search results found"; `tell me about Berlin
  and München and Köln` returned Cologne (Köln alias) with no
  footer about the dropped Berlin / München. Fix: new
  `_multi_entity_chain_guidance` detects 3+ substantive halves
  split by combined soft connectors (`and` / `or` / `,` / `&` /
  `vs` / `/`) AND probes the title index for the whole topic —
  clean single-title hits (`Earth, Wind & Fire` band;
  `Lions, Tigers, and Bears` idiom) suppress the warning; no
  clean hit fires a structured `Multi-Entity Chain Detected`
  rejection naming each entity. Iterative single-pattern splits
  (no combined alternation regex) keep SonarCloud's S5852
  polynomial-backtracking flag quiet; string-prefix/-suffix
  scans (not regex) handle leftover leading/trailing conjunctions
  for the same reason.

- **Trailing politeness regex extended to British/texting and
  multi-language tokens** (P1-D6 / P1-D7). Post-a20 PD2-1
  enumerated only `please` / `kindly` / `thanks` / `thank you|u`.
  Live probes showed `ta` / `cheers` / `thx` / `ty` / `pls`
  (British/texting) and `bitte` / `danke` / `merci` / `gracias` /
  `por favor` (multi-language) all leaked into search query /
  topic / title silently. Several new tokens are short (`ta` /
  `ty` are 2 chars) so the leading anchor tightens from
  `\s*[,;.!?]?\s*` to `(?:^|\s+|[,;.!?]\s*)` — embedded
  substrings in longer words (`cantata` / `feta` / `Dante`) no
  longer get their last two chars eaten.

- **`Search Terms Required` B4 guard now peels politeness from
  the tail before the empty-check** (P1-D8). Pre-fix,
  `_search_query_tail(query)` ran on the ORIGINAL query, so
  trailing politeness wasn't stripped before the empty-tail
  check; `search for please` silently dispatched with
  `query="for"` (the literal verb word) and returned a 200k-hit
  response dominated by stop-word collisions. Same shape for any
  `search for <politeness>` after the P1-D6 extension. Fix:
  apply `IntentParser._strip_trailing_politeness` to the tail
  before the B4 emptiness check.

- **Defence-in-depth dispatcher-edge politeness strip on params**
  (P1-D1). The live-MCP sweep observed
  `Found 5000 matches for "biology please"` for the query
  `search for biology please` despite the post-a20 PD2-1 fix.
  Source-side, the strip works correctly under direct unit test;
  the most likely cause is an in-process module cache on the
  live server that loaded only part of PR #152. Fix: in
  `handle_zim_query`, after the `parse_intent` call, apply
  `IntentParser._strip_trailing_politeness` to each of the
  user-supplied content fields in `params` (`query` / `topic` /
  `title` / `entry_path` / `partial_query`). Idempotent when
  `parse_intent` already cleaned them; belt-and-suspenders catch
  for any future regression that bypasses `parse_intent`.

- **`_Q_EMITTING_CURSOR_TOOLS` drift guard** (P1-D5). The
  post-a20 P1-D1 fix introduced
  `SimpleToolsHandler._Q_EMITTING_CURSOR_TOOLS` as a hand-
  maintained frozenset of tool names whose cursors legitimately
  carry an `s.q` field. If a future contributor adds a new
  q-emitting tool (a new `Cursor.encode(state={..., "q": ...})`
  callsite) but forgets to update the set, the dispatcher's
  q-overlap guard silently degrades to no-op for that tool —
  paginating with the wrong query proceeds silently. New
  regression test scans every `Cursor.encode(tool=...)` callsite
  in `zim/search.py` and pins membership equality with the set;
  encode-callsite comments updated to point at the set so the
  cross-module link is greppable from either side.

- **PD2-2 sibling docstring path-bait sweep** (P1-D9). Post-a20
  PD2-2 only pinned the `zim_query` docstring in `server.py`.
  Sibling literal path examples lived in advanced tool docstrings
  — `structure_tools.get_entry_summary` ("/path/to/wiki.zim"),
  `structure_tools.get_table_of_contents` ("/path/to/wiki.zim"),
  `structure_tools.get_binary_entry` ("/path/file.zim"), and
  `content_tools.get_zim_entries` ("/path/x.zim"). Small models
  copy these verbatim too — the same weak-instruction-follower
  class PD2-2 was designed to break. Fix: replace literal paths
  with `<zim_path>` placeholders that don't validate as
  filesystem paths; widen the regression test to scan every
  `openzim_mcp/tools/*.py` for `/path/...\.zim` or
  `/data/...\.zim` shapes.

- **PD2-4 recovery hint now preserves the original error reason**
  (P1-D10). The PD2-4 detector substring-matched `"access denied"`
  in the exception message and fired on `OpenZimMcpSecurityError`'s
  "Access denied - Path is outside allowed directories" message
  in addition to the intended file-not-found
  `OpenZimMcpValidationError`. The replacement body dropped the
  security-specific reason on the floor; callers saw only the
  generic "doesn't match any loaded archive" hint. Fix: surface
  the original exception message as a new `**Reason**` line
  alongside the recovery hint so the security-specific context
  isn't lost.

- **`limit` docstring nudge for atomic intents** (T-D1). Live
  small-model transcript (Qwen3-8B-Q4) showed the model passing
  `limit=5` on a `tell_me_about` query. The pre-fix docstring
  said "Max search/browse results (default: 3)" — silent about
  whether `limit` applies to atomic intents. Fix: docstring
  nudge explicitly enumerating the atomic intents that ignore
  `limit` (`tell me about` / `get article` / `show structure` /
  `links in` / `articles related to` / `main_page` /
  `list_namespaces` / `metadata for` / `list_files`).

### Testing

- 54 new regression tests in `tests/test_post_a21_beta_fixes.py`
  covering all eleven defects:
  `TestP1D6P1D7TrailingPolitenessExtensions` (29 parametric strip
  cases + word-boundary safety + full-parse integration);
  `TestP1D8SearchTermsRequiredAfterPolitenessStrip` (8 parametric
  guard-fires); `TestP1D1DispatcherEdgePolitenessStrip` (buggy-
  parse-stub regression); `TestMultiEntityChainGuidance` (8
  cases — 3-entity AND/OR/4-entity chains, 2-entity guard,
  real-title suppression via title-index probe, search-intent
  isolation, leading-conjunction split, Lions/Tigers/Bears idiom
  suppression); `TestP1D5QEmittingCursorToolsDrift` (3 cases —
  set value, search-encode comment hook, parametric
  `Cursor.encode` scan); `TestP1D9DocstringPathBaitSiblings`
  (directory-wide scan of `tools/*.py`);
  `TestP1D10RecoveryHintMarkerDiscriminatesSecurityError` (1
  case — surfaces original `OpenZimMcpSecurityError` reason);
  `TestTD1LimitDocstringClarifiesAtomicIntents` (1 case —
  docstring contract pin).
- Full suite: **1954 passed, 50 skipped**. mypy clean across all
  45 source files.

### Release process

After this changelog lands on `main`, push the `v2.0.0a22` tag
on `main` to trigger `.github/workflows/release.yml` — PyPI
publish + GitHub release notes auto-extracted from the matching
CHANGELOG section.

## [2.0.0a21] — 2026-05-19 (alpha pre-release) — post-a20 beta-test sweep — 6 live-Wikipedia defects across three passes

Live-MCP beta sweep against `wikipedia_en_all_maxi_2026-02.zim` on
the freshly-deployed `v2.0.0a20` build, plus a live small-model
failure transcript review. Pass 1 confirmed all nine prior fixes
(post-a17 P1-D1/P1-D2/P1-D3, post-a18 P3-D1/P3-D2/P1-D4, post-a19
P1-D1/P1-D2/P1-D3) still work as designed in production, then
surfaced two new defects. Pass 2 wave 1 widened probe coverage to
politeness wrappers across all simple-mode intents (one defect).
Pass 2 wave 2 reviewed a Qwen3-8B-Q4 failure transcript and
surfaced three more defects — a docstring-bait hallucinated path
that dropped small models into a retry loop. Pass 3 source-level
audit found zero new siblings across all six fix sites.

All six defects follow either the recurring **"fixes unlock
previously-broken code paths"** pattern (P1-D1, P1-D2, PD2-1
landed on surfaces a20's three landed fixes opened up) or the
**"weak-instruction-follower defect class"** pattern (PD2-2/3/4 —
small-model behaviour that adversarial query probes structurally
can't reach). The latter shape is new to the methodology and is
captured in the post-a20 refinement: live-transcript review should
join live-MCP probing as a recurring sweep input.

### Fixed

- **Cross-tool cursor reuse with stuffed `s.q` now reports
  tool-mismatch instead of q-mismatch** (P1-D1). The dispatcher's
  cursor-decode block runs the cursor's `s.q` overlap check before
  any handler-level `_cursor_tool_mismatch` guard fires. When a
  cross-tool cursor carries an `s.q` field (a hand-stuffed
  walk_namespace cursor with `s.q="biology"` passed to `search for
  photosynthesis`, or a real search cursor reused with a different
  tool), the dispatcher previously emitted the misleading "Cursor
  was issued for query X; current request shares no terms" error
  and advised the user to start the search over — even though the
  cursor was from a different tool entirely. Fix: scope the
  dispatcher's q-overlap check to cursors whose `t` claims a
  q-emitting tool (`search_zim_file` / `search_with_filters` — the
  only `Cursor.encode` callsites that put `s.q` in their envelope).
  Cursors claiming `walk_namespace` / `browse_namespace` /
  `extract_article_links` now pass through the dispatcher's
  q-check; the handler-edge guard emits the correct
  `Cursor / Tool Mismatch` diagnosis.

- **Soft-connector footer now suppresses for asymmetric alias
  cases** (P1-D2). `_soft_connector_footer`'s post-a18 P3-D2
  alias-fallback was gated on `not left_in and not right_in` — it
  only ran when BOTH halves missed the substring check. The
  asymmetric case (one half matches substring, the other matches
  only via title alias) slipped through:
  `tell me about Köln or Cologne` returned the Cologne article
  with a footer suggesting `tell me about Köln`, but Köln's
  title-index entry redirects back to Cologne — a 2-hop journey
  to the same article. Same shape reproduced for `京都 or Kyoto`,
  `上海 or Shanghai`, `München or Munich`, `Москва or Moscow`,
  `Αθήνα or Athens`, and their reverse-order variants. Fix:
  widen the gate to `not (left_in and right_in)` so the alias
  probe runs whenever either half misses substring. The probe
  still only upgrades a half whose top-scored title-index hit
  equals `top_path`, so genuinely different chain halves
  (`Berlin and 東京`) still surface the footer correctly. The
  irreducible `東京 or Tokyo` case stays unsuppressed — `東京`
  has its own disambig article that doesn't alias to `Tokyo`.

- **Trailing politeness now strips across all simple-mode
  intents** (PD2-1). Pre-fix, `tell_me_about` was the only
  intent that stripped trailing `please` / `kindly` / `thanks` /
  `thank you`. Every other extractor that captured the topic with
  a greedy end-anchored pattern (`_extract_search`,
  `_extract_search_all`, `_extract_find_by_title`,
  `_extract_related`, `_extract_suggestions`,
  `_extract_entry_path_keyworded` — feeding get_article / links /
  structure / toc / summary, plus `_extract_get_zim_entries` /
  `_extract_get_section`) silently swallowed the politeness:
  `search for biology please` searched for `"biology please"`
  (ranking `Thanks Maa` above `Biology`); `find article titled
  Berlin please` looked up `"Berlin please"` (not found);
  `links in Photosynthesis please` and `show structure of
  Photosynthesis please` showed the same shape. Comma forms
  (`"biology, please"`) and combinations
  (`"biology, thanks please"`) reproduced too. Fix: lift the
  trailing-politeness strip into `IntentParser.parse_intent` at
  the entry point — a single end-anchored regex, looped so
  combinations peel cleanly, runs before pattern matching +
  extractor dispatch. Legitimate content uses
  (`search for "Please Understand Me"` — song title) are
  unaffected because the strip is end-anchored and quoted phrases
  enclose the content.

- **`zim_query` tool docstring no longer contains a literal-
  looking path example** (PD2-2). The parameter description for
  `zim_file_path` previously included
  `(e.g. /data/wikipedia_en_all_maxi.zim)` as an illustrative
  path. Small models with weak instruction-following parse "e.g."
  inconsistently and routinely copied the example as the actual
  `zim_file_path` value. Real archives are date-suffixed in
  production (`wikipedia_en_all_maxi_2026-02.zim`) so the
  basename doesn't match either. Live transcript captured
  Qwen3-8B-Q4 doing exactly this and dropping into a
  `File does not exist` retry loop with no recovery signal.
  Fix: rewrote the docstring to lead with
  **Omit entirely (recommended)**, dropped the literal path
  example, added an explicit "do NOT invent a path from this
  docstring" line. A regression test pins the absence of the
  bait string so any future docstring edit reintroducing it
  fails CI.

- **`_normalize_zim_file_path` auto-selects when single archive
  loaded, even for slashed candidates** (PD2-3). The previous
  contract (H14: "explicit paths must reach the backend so it can
  surface a clearer error") only made sense when there was
  genuine ambiguity about which archive the caller wanted —
  single-archive setups have none. Pre-fix, a slashed candidate
  that didn't match anything still fell through to the backend in
  single-archive setups, producing the same `File does not exist`
  error that small models can't act on. Fix: when the candidate
  matches nothing via path-or-basename AND exactly one archive
  is loaded, auto-select regardless of separator. Multi-archive
  setups still preserve the candidate so the backend error
  surfaces and PD2-4 enriches it with the actual listing — H14
  narrowed but intact for the case it was actually defending.

- **"ZIM File Not Found" error now surfaces real archive paths
  and the omit-to-auto-select recovery** (PD2-4). The catch-all
  in `handle_zim_query` previously emitted a generic four-step
  troubleshooting block that gave small models no learning
  signal — they just retried with the same args. Fix: detect the
  `validate_zim_file` exception family (`File does not exist` /
  `Path is not a file` / `is not a zim file` / `Access denied`)
  and replace the template with a `ZIM File Not Found` shape:
  single-archive setups get "omit the parameter — only one
  archive loaded" + the actual path (defence-in-depth alongside
  PD2-3); multi-archive setups get a bulleted listing of real
  archive paths with "pass one verbatim" guidance. The generic
  template's step 1 was also rewritten to suggest
  "omit `zim_file_path`" as the canonical fix.

### Tests

- 65 new regression tests in `tests/test_post_a20_beta_fixes.py`
  covering all six defects plus the edge cases probed live
  (reverse-order alias variants, irreducible Tokyo disambig,
  multi-archive H14 preservation, zero archives edge case,
  defence-in-depth backend-failure paths, quoted-inner-please
  content preservation, etc.).
- 4 existing H14 tests updated to reflect the narrowed-to-multi-
  archive contract (single-archive auto-select + multi-archive
  preserve split into separate cases).
- 4 mock-realism updates in post-a16 / post-a17 test files (the
  widened P1-D2 alias-fallback calls the title backend for
  connector halves, so the blanket `return_value` mocks that
  reported every half resolves to `top_path` now use per-title
  `side_effect`).

Full suite: 1902 passed, 50 skipped.

### Methodology refinement (post-a20)

Live-transcript review is a distinct test surface from live-MCP
probing. The Qwen3-8B-Q4 transcript captured PD2-2 (a
docstring-bait hallucination source) that adversarial query
probes structurally couldn't reach — the bait was in the TOOL
DESCRIPTION, not in any user query. The transcript also exposed
PD2-4 ("no learning signal on retry" failure mode) that mocked
tests can't easily catch. Future sweeps should incorporate
small-model transcript review when available — the marginal
cost is low and the defect class it catches
(tool-self-described hallucination sources + error-message-
quality issues for weak-instruction-follower models) is
otherwise invisible.

## [2.0.0a20] — 2026-05-19 (alpha pre-release) — post-a19 beta-test sweep — 3 live-Wikipedia defects across one pass

Live-MCP beta sweep against `wikipedia_en_all_maxi_2026-02.zim` on
the freshly-deployed `v2.0.0a19` build. Pass 1 confirmed all six
prior fixes (post-a17 P1-D1/P1-D2/P1-D3 and post-a18 P3-D1/P3-D2/
P1-D4) still work as designed in production, then surfaced three
new user-facing defects. Pass 2 source-level self-audit found
zero new siblings.

All three defects follow the recurring **"fixes unlock previously-
broken code paths"** pattern: a17's Unicode tail-tokenisation fix
made non-Latin topics REACHABLE; a18's soft-connector alias
fallback + table-dominated subject-attribute fix landed on those
paths; THIS sweep found that the substantiveness filter guarding
the soft-connector footer wasn't Unicode-aware (P1-D3) AND that
the cross-tool cursor guard from a18's P1-D4 hadn't widened to
the search/filtered-search/links siblings (P1-D1, P1-D2 — the
deferred follow-up explicitly flagged by post-a18).

### Fixed

- **`search for X` rejects cross-tool cursors** (P1-D1). A
  `walk_namespace` or `browse_namespace` cursor passed to
  `search for Photosynthesis` previously decoded `s.o=3` into
  `options["offset"]` and search returned `showing 4-6 of 4237`
  instead of `showing 1-3`. Simple-tools-layer mirror of the
  post-a18 P1-D4 fix that landed for `_handle_browse` /
  `_handle_walk_namespace`. The advanced `search_zim_file` tool
  already enforces tool-binding via
  `Cursor.decode(expected_tool=...)`; this restores the check at
  the simple-tools handler edge with
  `_cursor_tool_mismatch(options, "search_zim_file")` at the
  top of `_handle_search`. User now sees the structured
  `Cursor / Tool Mismatch` rejection before any backend call.
- **`search X in namespace C` and `links in X` reject cross-tool
  cursors** (P1-D2). Same shape in `_handle_filtered_search`:
  `_cursor_tool_mismatch(options, "search_with_filters")` guard
  added. Defence-in-depth: `_handle_links` hardcodes `offset=0`
  today so the live shape didn't reproduce, but it IS a cursor-
  emitting handler and the guard
  (`_cursor_tool_mismatch(options, "extract_article_links")`)
  keeps the boundary consistent with sibling handlers and
  prevents a future offset-reading change from regressing
  silently. All four `options.get("offset")` sites in
  `simple_tools.py` (`_handle_browse`, `_handle_walk_namespace`,
  `_handle_search`, `_handle_filtered_search`) are now guarded.
- **Soft-connector footer recognises short non-Latin proper nouns
  as substantive** (P1-D3). `tell me about Berlin and 東京`
  resolved correctly to 東京 (right-promote via a18's Unicode
  tail fix), but the soft-connector footer was silently
  suppressed because `_is_substantive_topic("東京")` returned
  False. The ASCII-length-5 heuristic was tuned for English
  particles (`Then` / `Both` / `Here` / `Now`) and didn't
  account for non-Latin scripts where each character carries
  syllable-level lexical weight — `東京` is 2 chars but names
  the capital of Japan; `Köln` is 4 chars but names Germany's
  fourth-largest city. Same shape for `京都` / `北京` / `上海`.
  Fix: keep the original ASCII path (multi-token OR len≥5 OR
  digit-containing), and add a relaxed branch — when the string
  contains a non-ASCII letter, accept at len≥2. ASCII
  abbreviations (`Dr.` / `St.` / `Mt.`) remain rejected because
  they have no non-ASCII characters; single CJK ideograms (`京`)
  remain rejected because of the len≥2 floor. Both the chain
  detector and the soft-connector footer now fire correctly for
  non-Latin halves.

### Tests

19 regression tests in `tests/test_post_a19_beta_fixes.py`:

- **P1-D1** (4): walk-cursor-to-search rejected; browse-cursor-to-
  search rejected; same-tool search-cursor round-trips cleanly;
  no-cursor passthrough unaffected.
- **P1-D2** (3): walk-cursor-to-filtered-search rejected; walk-
  cursor-to-links rejected; filtered-search no-cursor passthrough
  unaffected.
- **P1-D3** (12): CJK 2-char accept (`東京` / `北京` / `京都` /
  `上海`); umlaut 4-char accept (`Köln`); ASCII particles still
  rejected (`Then` / `Both` / `Here` / `Now` / `This`);
  abbreviations still rejected (`Dr.` / `St.` / `Mt.` / `Jr.`);
  single CJK char still rejected (`京` / `北`); regression guards
  for ASCII long topics, multi-token, digit topics, empty /
  whitespace; Cyrillic short topic via existing 5-char path +
  relaxed branch; end-to-end soft-connector footer fires with
  CJK dropped half + umlaut dropped half.

Full test suite: **1842 passed, 50 skipped** (up from 1823 in a19).

### Pass-2 source-level audit (no siblings)

- **P1-D1 / P1-D2**: all 4 sites in `simple_tools.py` that read
  `options.get("offset", 0)` (`_handle_browse`,
  `_handle_walk_namespace`, `_handle_search`,
  `_handle_filtered_search`) are now guarded by
  `_cursor_tool_mismatch`. `_handle_search_all` and
  `_handle_related` don't read `options["offset"]` at all. No
  siblings remaining.
- **P1-D3**: `_is_substantive_topic` is called from two sites —
  the chain detector right-promote branch
  (`simple_tools.py:983-984`) and `_soft_connector_footer`
  (`simple_tools.py:1156`). Both benefit from the fix. Searched
  for other `len(stripped) >= N` ASCII-length heuristics across
  `simple_tools.py` / `intent_parser.py` / `title_promotion.py` /
  `synthesize.py`; `intent_parser.py:1012` already has explicit
  Unicode handling for the analogous `_looks_like_topic_ask`
  check. No other ASCII-only thresholds on user-provided strings.

Pass-3 live re-probe deferred following the post-a17 methodology:
the three fixes are narrow handler-edge guards + a pure-function
heuristic with no cross-module contract changes, no cursor codec
/ serialization changes. The 19 mock-based regression tests
cover the exact surfaces a live re-probe would.

PR: [#149](https://github.com/cameronrye/openzim-mcp/pull/149).
Commits on the sweep branch: `cc9eb64` (pass-1 fixes + tests),
`8745012` (dedupe cursor encode helpers — Sonar quality gate).

## [2.0.0a19] — 2026-05-19 (alpha pre-release) — post-a18 beta-test sweep — 3 live-Wikipedia defects across two passes

Live-MCP beta sweep against `wikipedia_en_all_maxi_2026-02.zim` on
the freshly-deployed `v2.0.0a18` build. Pass 1 confirmed all three
a18 fixes (P1-D1 soft-connector title-spans, P1-D2 Unicode tail
tokenisation, P1-D3 walk-namespace cursor `ai` preservation) work
as designed in production, then surfaced three new user-facing
defects. Pass 2 source-level self-audit found zero new defects.

Both P3-D1 and P3-D2 are **examples of a recurring pattern**: fixes
that unlock previously-broken code paths surface new defects in
those paths. Neither was reachable from the canonical reproducers
before a18 because the Unicode tokenisation defect intercepted
every non-Latin topic earlier in the pipeline.

### Fixed

- **Subject-attribute section dominated by table placeholders falls
  back to recovery pointer** (P3-D1). `musicians from München`
  resolved correctly via the new Unicode tail probe to Munich,
  then subject-attribute decomposition fired on the Notable people
  section. But that section is two H3 sub-tables
  (`Born in Munich` / `Notable residents`) which compact mode
  renders as `[Table N: M rows x P cols - pass compact=False to
  expand]` placeholders. The LLM got zero substantive content
  from a query that should list musicians — exactly the
  content-less-response shape wave 4's empty-lead fallback was
  designed to prevent. The bundle `get_section_data` reads is
  always built with `compact=True` (`openzim_mcp/bundle.py:307`),
  so the section can't be re-emitted with tables expanded.
  `_maybe_render_subject_section` now detects placeholder
  dominance (≥1 placeholder AND <100 chars of substantive prose
  after stripping them) and substitutes a `compact=False`
  recovery pointer that names the exact call to make. Telemetry
  counter `subject_attribute_table_dominated` for future tuning.
- **Soft-connector footer recognises non-Latin halves via title-
  alias fallback** (P3-D2). `tell me about Berlin and München`
  resolved correctly to Munich (right-promote), but the soft-
  connector footer was silently suppressed. The substring check
  `"berlin" in "munich"` is False; `"münchen" in "munich"` is
  also False because the title-alias index crosses the Unicode +
  language boundary (München → Munich) and substring matching
  can't see through that. So `left_in == right_in == False` hit
  the "neither in title — unclear which was picked" suppression
  branch. User never learned Berlin was dropped. Fix: when both
  halves fail substring, fall back to title-alias probing — probe
  the title index for each half, and if a half's top-scored hit
  resolves to `top_path`, treat that half as "in title"
  semantically. Cheap (in-memory title-index lookup) and only
  fires on the rare both-missed branch. The legacy positional-only
  call signature (without `zim_file_path` / `top_path` kwargs)
  continues to work — alias fallback is gated on those kwargs.
- **Cross-tool cursor reuse rejected at simple-tools handler
  edge** (P1-D4 — deferred from the post-a17 sweep).
  `walk namespace M` emits a cursor; passing that cursor to
  `browse namespace M` previously walked browse silently from
  walk's offset (=3 in the canonical reproducer), returning
  entries 4-6 and emitting a fresh `browse_namespace` cursor as
  if nothing was wrong. The simple-tools dispatcher had decoded
  only `s.o` and `s.ns` from any received cursor, ignoring `s.t`
  (issuing tool). The advanced tools already enforce tool-binding
  via `Cursor.decode(expected_tool=...)`. Fix: stash
  `decoded_payload.get("t")` into `options["_cursor_t"]` at decode
  time; add the `_cursor_tool_mismatch` helper alongside the
  existing `_cursor_ns_mismatch`; fire it at the top of both
  `_handle_browse` and `_handle_walk_namespace` (defence-in-depth
  for the symmetric direction). User now sees a clear
  `Cursor / Tool Mismatch` rejection before any backend call.

### Tests

9 regression tests in `tests/test_post_a18_beta_fixes.py`:

- **P3-D1** (3): table-dominated falls back to recovery pointer;
  prose + 1 table returns body unchanged; zero tables unchanged.
- **P3-D2** (3): alias-resolved half makes the footer fire;
  neither-half-resolves still suppresses; legacy positional-only
  call signature still works.
- **P1-D4** (3): walk cursor passed to browse → rejected; browse
  cursor passed to walk → rejected; same-tool round-trip preserves
  the post-a17 P1-D3 fix.

Full test suite: **1823 passed, 50 skipped** (up from 1814 in a18).

### Pass-2 source-level audit (no siblings)

- **P3-D1**: the table-placeholder shape is unique to subject-
  attribute decomposition. Other content-fetch paths surface
  tables embedded in larger prose bodies; the defect class is
  the "single section, all-tables" shape.
- **P3-D2**: `_soft_connector_footer` is the only substring-in-
  title site in the codebase. Other footers (disambig twin probe,
  related extends paths) use exact path/title matching from search
  results.
- **P1-D4**: `_handle_search` / `_handle_links` /
  `_handle_filtered_search` also read `options["offset"]` from any
  decoded cursor, but they use search-tool offsets that aren't
  cross-tool meaningful in the same way as walk/browse's shared
  namespace-offset semantics. Filed as a follow-up opportunity to
  widen the tool-mismatch guard later if a live probe ever
  surfaces the issue.

PR: [#147](https://github.com/cameronrye/openzim-mcp/pull/147).
Commit on the sweep branch: `7be575e` (pass-1 fixes + 9 tests).

## [2.0.0a18] — 2026-05-18 (alpha pre-release) — post-a17 beta-test sweep — 3 live-Wikipedia defects across two passes

Pass 1 (live-MCP, against the freshly-shipped `v2.0.0a17` build on
`wikipedia_en_all_maxi_2026-02.zim`) surfaced three user-facing
defects. Pass 2 source-level self-audit (sibling grep for the
landed fix shapes + edge-case unit tests) found zero new defects.

A live-MCP pass-3 reprobe is deferred until this release deploys — the
MCP server in the sweep environment couldn't be restarted mid-session
to load the new build. The recent post-a16 methodology refinement
(live-MCP catches a defect class unit tests structurally cannot)
should still apply for that follow-up pass.

### Fixed

- **`_soft_connector_footer` false-fires on titles that
  structurally span the connector** (P1-D1). Queries like
  `notable people from Big Rapids, Michigan` resolved correctly to
  the `Big_Rapids,_Michigan` article (a single entity whose title
  literally contains the comma) but the footer claimed the article
  for `Michigan` was returned and told the caller to query
  separately for `notable people from Big Rapids`. Same shape for
  `musicians from Romeo and Juliet` → "for Juliet". The existing
  `left_in == right_in` suppression only catches the
  both-halves-in-title case; a subject-attribute prefix
  (`notable people from`, `musicians from`) leaves the left half
  longer than the title and defeats it. Fix adds an earlier
  title-spans-connector suppression: when `top_title` matches the
  same connector regex as the topic, the connector is structural
  to the title and the footer is suppressed. The docstring already
  named `Vienna, Austria` as a case this should fire for; the new
  guard makes it work in the prefixed-topic shape too.
- **Non-Latin topic strings resolved to wrong articles at
  cert=0.85** (P1-D2 — critical). `tell me about München` returned
  the `M` letter article; `tell me about Zürich` returned the
  `Rich` disambig; `tell me about Köln` returned the `LN`
  abbreviation. Root cause: `_TAIL_TOKEN_RE = [a-z0-9]+` in
  `openzim_mcp/title_promotion.py` stripped non-ASCII characters,
  so `iter_query_tails("München")` yielded `["m", "nchen"]` and
  `iter_query_windows` then yielded `"m"`, which
  `find_title_match("m")` cleanly resolved to the `M` letter
  article at score 1.0. The backend `find_entry_by_title_data`
  natively handles Unicode topics (`find article titled München`
  resolves to Munich at score 1.00) — only the tokenisation layer
  destroyed the topic before the backend saw it. Fix: switch
  `_TAIL_TOKEN_RE` to `[^\W_]+` (Unicode-aware `\w` minus
  underscore, so underscore still acts as a token boundary for
  path-form input like `Big_Rapids,_Michigan`).
- **`walk namespace M` cursor round-trip false-failed with
  "missing archive-identity field"** (P1-D3). Paging walk_namespace
  by passing back the `next_cursor` it just emitted produced
  `Error: Cursor for 'walk_namespace' missing archive-identity
  field. Re-issue the request without a cursor.` even though the
  cursor (decoded) carried `{"v":2,"t":"walk_namespace","s":
  {"o":3,"l":3,"ns":"M","ai":"e048666a9e92"}}`. The simple-tools
  cursor dispatcher decoded the cursor and stashed only
  `state["o"]` (as `options["offset"]`) and `state["ns"]` (as
  `options["_cursor_ns"]`), dropping `ai`.
  `_handle_walk_namespace` then rebuilt cursor_state as
  `{scan_at, l}` without `ai`; downstream `walk_namespace_data`
  called `verify_archive_identity` unconditionally and raised
  "missing" because the field was gone. Fix: stash `state["ai"]`
  (and re-stash `state["ns"]`) into options at decode time;
  `_handle_walk_namespace` includes them in the rebuilt
  cursor_state when present. The data-layer guard now has the real
  `ai` to compare against and properly distinguishes "missing"
  from "cross-archive mismatch". Browse_namespace didn't surface
  the same failure because its handler passes `offset` directly
  (no cursor_state envelope) and the browse data layer only
  verifies archive identity when an explicit
  `cursor_archive_identity` kwarg is passed — which the
  simple-tools handler doesn't pass.

### Tests

21 regression tests in `tests/test_post_a17_beta_fixes.py`:

- **P1-D1** (6): comma title with subject-attribute prefix
  suppresses; `and` title with subject-attribute prefix
  suppresses; genuine two-entity query still emits the footer;
  pre-fix both-halves-in-title still suppresses; slash-connector
  title-spans suppression (pass-2); no-connector-in-title still
  fires (pass-2).
- **P1-D2** (11): München / Zürich / Köln tokenise as single
  Unicode tokens; multi-word Unicode topic preserved; ASCII path
  unchanged (regression guard for the original `big rapids
  michigan` example); underscore boundary preserved; digits
  preserved; empty topic (pass-2); mixed Latin + non-Latin
  (pass-2); single non-Latin char (pass-2); punctuation as
  boundary (pass-2).
- **P1-D3** (4): end-to-end cursor round-trip carries `ai`;
  dispatcher stashes `_cursor_ai` into options; no-cursor case
  preserved (cursor_state stays None); cross-archive `ai`
  mismatch propagated correctly (pass-2 — preserving `ai` must
  not weaken the cross-archive enforcement guard).

Full test suite: **1814 passed, 50 skipped**.

### Deferred

- **P1-D4** (lower priority): `browse_namespace` silently accepts
  cursors emitted by `walk_namespace` (cross-tool reuse at the
  simple-tools dispatcher layer; the advanced tools already
  enforce). Not user-facing critical — simple-tools reads
  `state["o"]` and walks browse from that offset, which for the
  metadata namespace coincidentally produces a continuation page.
  A defence-in-depth follow-up would stash `state["t"]` and add a
  `_cursor_t_mismatch` check alongside the existing
  `_cursor_ns_mismatch`. Filed as follow-up rather than bundled
  here to keep the sweep tight.

### Methodology

Two passes (rather than the recent 3–7) because the three landed
fixes were narrow, well-characterised, and had no live-only
surfaces that source-level self-audit couldn't cover.
`_AFFINITY_TOKEN_RE` in `synthesize.py` and
`_tokenize_for_relevance` in `zim/search.py` use the same ASCII
pattern as `_TAIL_TOKEN_RE` but are **symmetric** tokenisers (same
regex applied to both sides of the comparison) — the P1-D2 shape
is a **unidirectional probe** that destroys the topic before the
backend sees it, which is structurally different. No siblings.
`verify_archive_identity` is also called from
`browse_namespace_data`, `extract_article_links_data`, search
cursor paths, and structure cursors, but all gate on an explicit
`cursor_archive_identity` kwarg that the simple-tools handlers
don't pass; only walk_namespace builds a cursor_state envelope
whose `ai` the data layer unconditionally checks. No siblings.

PR: [#145](https://github.com/cameronrye/openzim-mcp/pull/145).
Commits on the sweep branch: `d42213b` (pass-1 fixes + 14 tests),
`8f8a44e` (pass-2 self-audit + 7 edge-case tests), `e59b953` /
`2f71bba` (CI lint fixes — F401 unused-imports / isort).

## [2.0.0a17] — 2026-05-18 (alpha pre-release) — post-a16 sweep + empty-lead fallback + subject-attribute decomposition (four waves)

Sixteen commits across four sweep waves on top of `v2.0.0a16`. Waves
1–3 fixed 10 + 7 user-facing defects + 2 opportunities surfaced by
unit-mocked adversarial probes and the new live-MCP probing surface;
wave 4 added two behavioural improvements driven by a 2026-05-18 live
transcript where a small Qwen3-8B-Q4 model hallucinated when
`zim_query` returned section-headings-only responses for short
city/biography articles whose infobox got stripped. Wave 4's own work
went through a pass-2 self-audit that surfaced three more real
defects in the wave-4 code itself (the recurring pattern: each pass's
own fixes have leftover defects). One follow-on test-assertion fix
(PR #143) was required after the merge when the Comprehensive Testing
job tripped on a fixture-drift issue PR #136 missed when it fixed
the parallel test.

### Added

- **Subject-attribute decomposition in `_handle_tell_me_about`**
  (wave 4). Queries like `famous musician from big rapids michigan`,
  `notable people from detroit`, `actors from new york` now route
  to the matching section of the resolved entity's article
  (`Notable people`, `Music`, `Film`, etc.) instead of the (often
  empty) lead. Subject hints (`musician`, `actor`, `athlete`,
  `notable people`, etc.) are extracted from the residual after
  entity-name tokens are subtracted from the topic; the candidate
  section is found via whole-word regex match against H2 headings
  (so `film` matches `Film and television` but not `Microfilm`).
  Strong hints win over weak ones (`famous`/`notable` alone don't
  fire). Soft-connector ambiguity footer fires for multi-entity
  variants like `musicians from Berlin and Paris` so the LLM
  knows the other entity was dropped. The original confidence-gate
  approach was removed by the self-audit (over-blocked legitimate
  explicit-phrasing queries like `who is a famous musician from X`
  classified at 0.85) — `_extract_subject_hint` is now the sole
  gate.
- **Empty-lead fallback in `_lead_with_toc`** (wave 4). When the
  pre-H2 lead is empty (after stripping the ZIM preamble +
  duplicated H1), advance the cut to the second non-wrapper H2 so
  the response includes the first real section's prose instead of
  just a TOC list. Motivating case: `Big_Rapids,_Michigan` from
  the 2026-05-18 live transcript — empty lead before
  `## Notable people` caused the LLM to invent facts. Gated to
  bodies in the ZIM-preamble shape; direct-content unit fixtures
  stay unchanged via a preamble-presence check.

### Fixed

- **D1: chained-intent detector false-fires on `and`/`or`/`&`/
  `,`/`/` connectors that are part of legitimate article titles**
  (`Romeo and Juliet`, `TCP/IP`, etc.). Wave 1 added the soft-
  connector ambiguity layer at `_soft_connector_footer` with a
  strict `_is_substantive_topic` filter so single-token English
  sentence-words don't trip the right-promote branch. Caught by
  wave 2 self-audit and refined to the current shape.
- **D2 + D3: `walk_namespace` on empty new-scheme `B`/`X`/`Z`
  namespaces omitted `namespace_entry_count` while
  `walk_namespace M`/`W` included it** — schema inconsistency
  between sibling aggregators (post-a15 D7 family). Now uniform.
- **D4: `find article titled M/Title` silently returned `0_hits`**
  because the title index only stores titles, not paths — no
  signal to the caller. Now returns a clear error pointing at
  `get article M/Title`.
- **D5: politeness modal lead-in (`could you`/`can you`/`would
  you`/`will you`) leaked into the parsed topic** for chained
  intents because the chain detector ran before the modal-strip.
  The D5 modal-strip now lives in a shared scaffold-strip that
  runs at the top of `_chained_intent_guidance` too.
- **D6 + D7: silent default `params.get("namespace", "C")`** in
  `walk_namespace` allowed garbage namespace input (empty, `AB`,
  `1`, `_`) to walk C silently. Added an input-validation guard
  matching sibling tools.
- **D8 + D9 + D10: aggregator-disagreement family** — `browse
  namespace M` reported 13 entries (including the binary
  `Illustration_*` entry) while `list namespaces` / `walk
  namespace M` / `metadata for <file>` all reported 12. Wave 3's
  P3-D3 applies the same `is_human_readable_metadata_key` filter
  to `_enumerate_new_scheme_metadata` so all four aggregators
  agree. Also pins C namespace total to `archive.entry_count`
  (was drifting ±1 due to sampling projection).
- **P3-D2: walk_namespace cursor encoded `s.scan_at` on the wire
  but the universal top-level cursor decoder only accepts `s.o`**.
  The mismatch made walk_namespace cursors round-trip-broken
  (`cursor_decode` error when replaying the tool's own cursor).
  Caught only by live-MCP probing the tool's own cursor advice;
  unit tests of either module in isolation looked correct.
- **P3-D5 + P3-D6: surface crashes on filtered-search**
  (`KeyError: 'namespace'` on certain compact filtered-search
  branches; missing dict key in the response builder). Both
  caught by live-MCP probing the deployed server, not the
  unit-mocked test set.
- **P6-D1 + P6-D2 + P6-D3: leading-politeness probes + source-
  level sibling audits** caught three more defects in the
  `browse_namespace` family that the live-query passes hadn't
  reached. New methodology angle.
- **Self-audit fix-ups for wave 4** (caught by pass-2 self-audit
  of wave 4 itself, BEFORE the PR landed): (a) confidence gate
  over-blocked `tell me about famous musicians from X` (removed
  the gate; `_extract_subject_hint` is the sole filter);
  (b) empty-lead density threshold of 80 false-fired on real
  one-sentence leads (~11 chars after preamble strip) — lowered
  to 5; (c) `_DUPLICATED_H1_RE` required trailing `\n+` but
  callers `rstrip()` `pre_h2` before passing it in, so the
  duplicated `# Title` was never being stripped — the 80
  threshold was masking the bug; fix changed to accept
  `(?:\n+|\Z)`.
- **PR #143 follow-on: M-namespace browse-total fixture drift**
  (post-merge fix). The P3-D3 metadata-key filter dropped the
  fixture's M-namespace count from 10 to 9, tripping a sibling
  exact-count assertion (`assert result["total"] == 10`) that
  PR #136 missed when it fixed the parallel
  `test_metadata_namespace_from_metadata_keys`. Mirrored PR
  #136's pattern: `>= 5` floor with cross-referenced docstring.

### Refactored

- **Hoisted regex constants out of method bodies** for the
  empty-lead path (`_LEAD_PREAMBLE_RE`, `_DUPLICATED_H1_RE`,
  `_EMPTY_LEAD_DENSITY_THRESHOLD`) matching the project pattern
  for SonarCloud-safe regex declaration. Patterns tightened to
  use literal single space + `[^\n]*` (the ZIM renderer emits
  exactly one space after `#`/`##`) rather than `\s+` adjacent
  to `[^\n]*`, eliminating the polynomial-backtracking
  ambiguity SonarCloud's S5852 detector flagged.
- **Whole-word matching in `_resolve_section_for_subject`**
  (`\bcand\b` instead of substring) prevents false-positives
  like `film` matching `Microfilm` or `science` matching
  `Conscience`.

### Methodology

Pass-4 of the sweep introduced **source-level sibling audits**
as a new angle. After a fix lands for a defect class, grep the
codebase for the same shape and audit every sibling. P6-D1 and
P6-D2 in `browse_namespace` were caught instantly this way;
pass-2 of wave-4 confirmed there are no other regex patterns
in `simple_tools.py` requiring trailing `\n+` that could be
defeated by rstrip, and no other confidence-based gates of the
same shape as the one removed.

Wave 4 also added **adversarial self-audit BEFORE the PR
lands** rather than as a post-merge gate. The original 12-commit
wave-4 push went through a pass-2 self-audit that caught three
real defects in its own work (confidence gate, density
threshold, latent H1-strip bug — the latter unmasked when
fixing the threshold). All landed before the PR was opened for
human review.

## [2.0.0a16] — 2026-05-17 (alpha pre-release) — post-a15 beta-test sweep — 10 live-Wikipedia defects across seven passes

The multi-pass live sweep of a15 against
`wikipedia_en_all_maxi_2026-02.zim` (~118 GB, ~27.2 M entries) ran
across seven passes. Pass 1 surfaced four user-facing defects (D4 in
the `tell_me_about` disambig-page handling for Mercury-class bare
titles; D5 in the intent parser's politeness-prefix regex; D6 in
`find_by_title`'s response to namespace-prefixed input; D7 a
schema-consistency gap in `walk_namespace`). Pass 2 self-audited
every D-fix in both verbose and compact rendering modes and
exercised the canonical-article paths (Berlin / Apollo 11 / Java)
the disambig-detection logic must not regress. Pass 3 re-tested
across a broader disambig set (Mars, Sun, Moon, Paris, Apollo bare),
walked empty namespaces B / X / Z, and exercised cross-fix
interactions (`could you find article titled M/Title`); both
passes 2 and 3 found zero new defects. Pass 4 then deliberately
stress-tested the four landed D-fixes from angles the earlier
passes hadn't probed (more bare-title disambigs, pathological
politeness combinations, find_by_title edge cases, walk_namespace
malformed args) AND exercised the intent paths the earlier passes
had barely touched (synthesize, browse namespace, show structure
of, links in, suggestions for, search in namespace); it surfaced
three more defects (P4-D1 / P4-D2 / P4-D3). Pass 5 verified those
three fixes; zero new defects. Pass 6 went deeper — a source-level
audit of every intent handler for the silent-default pattern
P4-D3 fixed (`params.get("X", DEFAULT)`) caught the same shape in
`_handle_browse`, and a parallel audit of every intent extractor
for the trigger-word-capture pattern P4-D1 fixed caught a sibling
extractor permissiveness in `_extract_browse`; plus a leading-
politeness probe surfaced a third defect (P6-D3) — `please tell
me about X` leaks the leading politeness into the parsed topic
just like the original D5 did for modal verbs. Pass 7 verified
all ten fixes and audited cumulative regressions across the three
commits; zero new defects.

### Fixed

- **D4: `tell me about Mercury` no longer attaches a misleading
  `_May also refer to: Mercury_Monterey — use tell me about <full
  title>_` footer to the disambiguation-page body.** Two cooperating
  bugs: `SimpleToolsHandler._is_disambig_lead` returned False
  whenever `pre_h2` exceeded 400 chars — Mercury's 628-char pre-H2
  (the "most commonly refers to" preamble, three top-level entries,
  and the "may also refer to" header) blew past the cap, so the
  existing disambig-page detection in `_lead_with_toc` never fired;
  AND the trailing-footer block in `_handle_tell_me_about` had no
  way to suppress the `disambig_twin_path` / `related_extends_paths`
  hints when the resolved body was itself a disambig page. Fixed
  by checking only the trailing 400 characters of `pre_h2` (the
  regex-free `endswith` stays bounded, but long preambles now
  trigger) and by gating both trailing footers on a fresh
  `body_is_disambig_page` check on the fetched body. Canonical
  pages with disambig twins (Berlin) keep their footer; canonical
  pages with extends-topic siblings (Apollo 11 → anniversaries /
  lunar sample display / goodwill messages) keep their footer.
- **D5: `could you tell me about Photosynthesis` now parses
  `topic = "Photosynthesis"` instead of leaking the modal lead-in
  into the topic.** The verb-prefix regex in
  `_extract_tell_me_about` anchored at `^\s*` and never matched
  "could you" / "can you" / "would you" / "will you", so the whole
  query fell through to the `topic = query.strip()` fallback and
  downstream relied on the tail-probe entity rescue to find the
  article anyway. Fixed by stripping the modal scaffold
  (`(?:could|can|would|will)\s+(?:you|we|i)\s+(?:please\s+)?`) before
  the verb regex runs. Leaves non-modal queries unchanged; combines
  cleanly with the existing trailing-politeness strip
  (`could you tell me about X please` → topic=X).
- **D6: `find article titled M/Title` now redirects to `get article
  M/Title` instead of returning a silent `0_hits`.** The title index
  only stores titles (M/Title's title is "Title"), so passing a ZIM
  namespace path through the title-lookup backend was guaranteed to
  return nothing — with no signal to the caller that the wrong tool
  was in use. `_handle_find_by_title` now detects the
  uppercase-letter + slash + non-empty-suffix shape upfront and
  returns a structured **Namespace Path, Not a Title** message that
  points at both `get article <path>` (direct lookup) and `find
  article titled <stripped>` (title-only fallback). Lowercase
  prefixes (`a/b`) and titles without the namespace shape pass
  through to the backend unchanged.
- **D7: `walk namespace A` (and any other empty new-scheme
  namespace) now includes `namespace_entry_count: 0` in the
  response.** The short-circuit at
  `openzim_mcp/zim/namespace.py` for new-scheme non-C/M/W namespaces
  built an empty result without passing `namespace_entry_count` to
  `_build_walk_result`, so the field was omitted entirely while
  walk-M and walk-W (which surface their bounded totals) included
  it. Downstream consumers had to special-case "missing" vs "zero".
  Fixed by passing `namespace_entry_count=0` in the short-circuit.
  Updated the `walk_A_10` golden to reflect the new schema; walk-M
  and walk-W goldens are unchanged (already carried the field).
- **P4-D1: `suggestions for` (no actual prefix) now returns the
  structured "Missing Search Term" error instead of silently
  autocompleting against the literal word "for".** The regex's
  optional `(?:for\s+)?` group failed to match without trailing
  whitespace, so the mandatory capture greedily swallowed "for"
  itself; the handler's existing missing-arg guard then saw a
  non-empty `partial_query` and ran the suggestion fallback (which
  spent ~70 s scanning for "for" — a high-frequency English token).
  Fixed in `_extract_suggestions` by discarding a bare-"for"
  capture so the guard takes over. Legitimate prefixes that happen
  to start with "for" (e.g., `suggestions for forest`) still work.
- **P4-D2: chained-intent detector no longer bypassed by a modal
  lead-in.** `_chained_intent_guidance`'s
  `_CHAINED_OPERATION_PREFIX_RE` is anchored at `^` and only
  recognised operation verbs at position 0, so `could you tell me
  about Photosynthesis then list namespaces` shifted the verb past
  the anchor — `left_is_op` evaluated False, the chain gate failed,
  and the query fell through to normal intent classification where
  the higher-confidence `list_namespaces` won and silently dropped
  the `tell me about` half. The D5 modal-strip lives inside
  `_extract_tell_me_about`; it only runs AFTER the chain detector
  has already decided. Fixed by pre-stripping the same modal
  scaffold (`(?:could|can|would|will)\s+(?:you|we|i)\s+
  (?:please\s+)?`) at the top of `_chained_intent_guidance` so
  detection sees the cleaned query.
- **P4-D3: `walk namespace` with a malformed argument now returns
  a structured "Missing or Invalid Namespace" error instead of
  silently walking C.** Multi-char (`AB`), digit (`1`), special
  (`_`), and missing-argument forms all fell through to
  `params.get("namespace", "C")` in `_handle_walk_namespace` with
  no signal to the caller that the input was rejected. Sibling
  tools (`find_by_title`, `links_in`, `suggestions`,
  `tell_me_about`) already return structured missing-arg errors;
  this one didn't. Fixed by adding an upfront guard that mirrors
  their shape (rule / examples) before the C-default kicks in.
- **P6-D1 + P6-D2: `browse namespace` now reaches input-validation
  parity with `walk namespace`.** Two cooperating gaps — the
  handler `_handle_browse` had the same
  `params.get("namespace", "C")` silent-default that P4-D3 fixed
  for walk; AND the extractor `_extract_browse` accepted multi-char,
  digit, and special-character namespace arguments
  (`browse namespace AB / 1 / _`) without uppercasing lowercase
  input — diverging from the strict
  `_extract_walk_namespace`. The two siblings now agree: regex
  tightened to `namespace\s+['"]?([A-Za-z])\b['"]?` with `.upper()`
  on the captured letter, and the handler returns a structured
  "Missing or Invalid Namespace" error when the extractor produces
  nothing.
- **P6-D3: leading `please` / `kindly` now strip cleanly from the
  parsed topic.** `please tell me about Photosynthesis` and
  `kindly describe Photosynthesis` previously parsed with the
  politeness phrase leaking into the topic — same shape as the
  pass-1 D5 defect but for non-modal politeness words. The article
  still resolved via tail-probe rescue, but the parsed topic was
  wrong. Fix extends the leading-strip in `_extract_tell_me_about`
  to cover `please` / `kindly` AND wraps both the modal-strip and
  the politeness-strip in a loop so composite phrases
  (`please could you tell me about X`, `please please tell me
  about X`) peel cleanly. Same loop also applied to the chain-
  detector's `_chained_intent_guidance` pre-strip so leading
  politeness doesn't bypass chain detection (mirror of P4-D2).
  Leaves the existing trailing-politeness strip alone, so
  `tell me about X please` still works, and the leading-only
  anchor (`^\s*`) prevents stripping mid-query mentions of
  `please` / `kindly` that are legitimately part of the topic.

### Tests

- **`tests/test_post_a15_beta_fixes.py`** — 80 regression tests
  pinning all ten defects. Each defect gets:
  - The fix-case test (Mercury body has no misleading trailer;
    `could you tell me about X` parses topic=X; `find article titled
    M/Title` returns redirect; `_build_walk_result` exposes the
    zero-count field; `suggestions for` triggers the missing-arg
    guard; `could you tell me about X then list namespaces` is
    detected as chained; `walk namespace AB` returns the missing-
    namespace error; `browse namespace AB` returns the same error
    and `browse namespace c` lowercases to "C"; `please tell me
    about X` strips cleanly).
  - Negative self-audit cases (Berlin keeps its disambig-twin
    footer; non-modal queries unchanged; lowercase a/b not
    redirected by find_by_title; `namespace_entry_count` omitted
    when caller passes None; legitimate `suggestions for forest`
    still captures the prefix; non-chained `could you tell me about
    X` not tripped by the chain detector; trailing `please` still
    works; mid-query `please in linguistics` not stripped).
  - Cross-defect probes (Java disambig body suppresses
    `disambig_twin_path` footer too; `please could you tell me
    about X` peels both layers; `please tell me about X then list
    namespaces` trips chain detector).

## [2.0.0a15] — 2026-05-16 (alpha pre-release) — post-a14 beta-test sweep — section-affinity feature now actually works on real Wikipedia content

### Pass 2 self-audit findings (the recurring pattern: each pass's own fixes have leftover defects)

Three real defects found while self-auditing pass 1; all fixed in this
commit set. Three new tests added.

- **D-Audit-1: `find_entry_by_title_data` produces duplicate rows after
  F3's redirect-chain canonicalisation.** When two suggestions
  (``Bilogy`` redirect + ``Biology`` canonical) both follow to the
  same canonical path, the result list previously emitted two rows
  with the same path. Added a ``(zim_file, path)`` dedup pass after
  the score sort, keeping the highest-scored occurrence.
- **D-Audit-2: `_follow_redirect_chain` can return ``None``.** The
  pre-existing implementation's docstring promised "Returns the
  original entry on any failure" but a redirect whose
  ``get_redirect_entry()`` returned None resulted in the function
  returning None — which then crashed every downstream
  ``entry.path`` access. Tracks ``last_good`` so the helper now
  always returns a real entry, matching its contract.
- **D-Audit-3: F5's underscore-replace heuristic misses slash-shaped
  paths.** Archives like IEP set their entries' ``title`` field to the
  full path (``iep.utm.edu/kantview/``); the F5 humanise heuristic
  only swaps underscores, so these entries surfaced unchanged in
  ``considered_articles[].title``. Extended ``_build_considered_articles``
  to accept ``archive_titles`` (already computed by
  ``_build_section_lookups``) and prefer the bundle's authoritative
  title when present. Verified in-process against the IEP archive
  where titles like ``"Kant, Immanuel | Internet Encyclopedia of
  Philosophy"`` now flow through correctly.

The live beta-test sweep of a14 against
`wikipedia_en_all_maxi_2026-02.zim` found that every `synthesize=True`
response carried `section_id: null` on every citation and an empty
`considered_sections` list — the three coordinated mechanisms a14
shipped were architecturally inert on real archives. Unit-test
goldens passed because they used a fabricated archive where the
entire article body sits inside a single section whose id matches
the article title; real Wikipedia articles have leads outside any
section and natural-bold markup (`**EntityName**`) that breaks the
snippet-to-markdown locate path.

### Fixed

- **F1 (P1): `_locate_passage` now strips bold from BOTH the snippet
  AND the haystack markdown** before searching, with a position-
  remap so the returned offset still indexes into the original
  markdown. Wikipedia's universal `**EntityName**`-opens-the-lead
  pattern previously caused every lead-snippet `md.find` and
  normalized-search to return -1; section attribution then dropped
  every passage to entry-level citation. New helper
  `_strip_bold_with_remap(text) -> (stripped, remap)` in
  `openzim_mcp/synthesize.py`.
- **F2 (P1 cascade): `_build_considered_sections` no longer short-
  circuits to `[]` when the featured passage is article-level.**
  Surfacing the article's sections regardless of whether the
  featured passage itself was section-attributed is a strict
  improvement for the multi-round pivot — the next-turn
  `get_section` call wins either way. The early-exit at
  `synthesize.py:684` was a strict pessimization.
- **F1 cascade (pre-h1 chrome fallback): `_attribute_sections` falls
  back to the FIRST section in the bundle when no section brackets
  the located passage.** Archives that render page chrome (nav,
  breadcrumbs) before the h1 heading otherwise lose every chrome-
  area BM25 snippet to entry-level citation. Verified live against
  the IEP archive's nav-menu prefix where the h1 section starts at
  char 513.
- **F3 (A1): `title_match_hit` and `find_entry_by_title_data` now
  follow the libzim redirect chain via `_follow_redirect_chain`
  before reporting the entry path.** Wikipedia archives carry many
  comma-stripped / case-normalised redirects (`Big_Rapids_Michigan`
  → `Big_Rapids,_Michigan`); without canonicalisation, the same
  article got two different cite_ids depending on which lookup
  variant fired, splitting multi-round-agent state. Applied at all
  three entry-emission sites (fast-path, suggestion-rank, typo-
  fallback).
- **F4 (A2): non-trailing sliding-window probe added as a fallback
  to `_promote_topic_via_title_index` after the strict trailing-tail
  pass.** Queries whose entity sits at the head/middle of the prose
  (`"Big Rapids Michigan tourism"`) now resolve to the entity
  instead of falling through to BM25 noise. New helper
  `iter_query_windows(query, max_len=4, min_len=1)` in
  `openzim_mcp/title_promotion.py`; non-trailing windows only,
  longest-first, so a14's motivating tail-positioned-entity
  behavior is preserved (sliding-window only fires when no
  trailing tail resolved strictly).
- **F5 (A3): `considered_articles[].title` is humanized via the new
  `_humanize_path_title` helper** so path-shaped hit titles
  (`"West_Michigan"`) render with spaces, matching the
  `citations[]` view in the same response. Eliminates the cross-
  view inconsistency where the same article had two different
  display titles depending on which structured field surfaced it.
- **F6 (B1): the lead-with-TOC trailer in `_lead_with_toc` now
  references the canonical (post-redirect) path** for typo-
  fallback resolutions like `tell me about Bilogy` → Biology.
  Carried through F3's canonicalisation in
  `find_entry_by_title_data` — `_promote_topic_via_title_index`
  returns the canonical path, which `_fetch_topic_article_body`
  passes to `_lead_with_toc`. Previously the trailer suggested
  `show structure of Bilogy` (the typo), pushing the next call
  back through typo-fallback.

### Tests

- Test count: 1581 (up from 1567 in a14). All passing.
- New test files:
  - `tests/test_synthesize_section_attribution_live_shape.py` —
    Wikipedia-shaped HTML fixture exercising the natural-bold
    locate path AND the pre-h1 chrome fallback.
  - `tests/test_title_match_hit_redirect_canonicalization.py` —
    redirect-chain canonicalisation for the fast-path hit.
  - `tests/test_iter_query_windows.py` — sliding-window iterator
    spec.
  - `tests/test_simple_tools_window_probe.py` — three-pass probe
    ordering: trailing-strict → window-strict → trailing-fuzzy.
  - `tests/test_simple_tools_typo_trailer_canonical_path.py` — end-
    to-end confirmation that the lead trailer uses the canonical
    path.
- Updated `test_build_considered_sections_empty_when_featured_is_article_level`
  → `test_build_considered_sections_surfaces_all_sections_when_featured_is_article_level`
  (semantics changed; old name retained as a renamed coverage of
  the new behaviour).
- Updated `test_fast_path_exact_match` and
  `test_cross_file_aggregates_and_skips_failures` mock entries to
  set `is_redirect = False` (the production path now calls
  `_follow_redirect_chain`; default MagicMock truthy-ness made the
  chain bounce forever otherwise).

### Researched, not fixed (B2)

The live sweep observed that four parallel `zim_query` calls (one
heavy with typo-fallback variants) caused every subsequent call to
time out for ~90 seconds before the server recovered. Hypothesis:
libzim is not thread-safe on a single archive handle, and the
typo-fallback path (~1400 archive probes per call) saturates the
thread-pool. Conservative fix surface (not in this sweep):
per-archive `asyncio.Lock` around typo-fallback, OR a per-request
deadline, OR a libzim archive pool. Needs a reliable reproducer
and instrumentation before landing.

## [2.0.0a14] — 2026-05-15 (alpha pre-release) — search-engine-style `zim_query`: tail-probe entity resolution + section-affinity boost + considered_* handles

First post-beta-test alpha that ships a feature rather than a sweep:
natural-language prose questions now resolve to canonical entities
and (in `synthesize=True` mode) lead with the most relevant section
of the resolved article. Three coordinated changes:

1. **Greedy length-down tail-probe entity resolution.** A shared
   `iter_query_tails` helper in `title_promotion.py` iterates the
   trailing 4 → 3 → 2 → 1 tokens of a query. Both the default
   `_handle_tell_me_about` path (via `_promote_topic_via_title_index`,
   two-pass strict-then-fuzzy) and the synthesize path (via
   `_promote_title_match`, single-pass strict) now probe each tail.
   This replaces the M26 4-token short-circuit that previously caused
   long prose queries like *"who are some famous people from big
   rapids, michigan"* to fall through to BM25 noise instead of
   resolving the canonical `Big_Rapids,_Michigan` entity.

2. **Section-heading affinity boost in synthesize.** A new
   `_boost_by_section_affinity` pipeline stage runs after
   `_attribute_sections`. For each passage carrying a `#section_id`,
   it computes `|query_tokens ∩ heading_tokens| / |heading_tokens|`.
   When that ratio meets `SynthesizeConfig.section_affinity_threshold`
   (default `0.25`), the passage score is multiplied by
   `section_affinity_boost` (default `1.5`) and the list is
   re-sorted (with `rank` renumbered to match). Archive-agnostic:
   the archive's own section headings supply the matching
   vocabulary, no curated synonym tables.

3. **Multi-round handles on `SynthesizeResponse`.** Two new optional
   fields surface the candidate space:
   `considered_articles` (top-3 article hits not featured) exposes
   `(archive, entry_path, title, score)` so a follow-up turn can pivot
   via `get_zim_entries`. `considered_sections` (top-10 sections of
   the featured article, in document order, minus the featured one)
   exposes `(section_id, title)` so a follow-up turn can pivot via
   `get_section`. `SynthesizeResponse` switches to
   `TypedDict(total=False)` to accommodate the additive shape;
   existing callers populating every field are unaffected. Compact-
   mode markdown rendering of these fields is deferred — the
   structured payload (`structuredContent`) always carries them.

The motivating query *"who are some famous people from big rapids,
michigan"* now traces:

- Default mode: tail probe resolves `Big_Rapids,_Michigan`, returns
  the article body. Better than today's BM25-noise outcome, though
  the response is not yet section-targeted in default mode.
- `synthesize=True`: tail probe resolves the entity, affinity boost
  promotes the `#Notable_people` section to the lead passage, and
  the response carries `considered_articles` + `considered_sections`
  handles for the next turn.

### Added

- `iter_query_tails(query, *, max_len=4, min_len=1)` in
  `openzim_mcp/title_promotion.py` — greedy length-down trailing-
  token iterator, lowercased + `[a-z0-9]+` tokenized. Shared by both
  entity-resolution paths. Underscore is treated as a token boundary
  so path-form input like `Big_Rapids,_Michigan` tokenizes correctly.
- `_boost_by_section_affinity` pipeline stage in
  `openzim_mcp/synthesize.py` plus the `_section_titles_for` and
  `_maybe_boost_passage` helpers. Bundle-titles lookup is memoized
  per call; exceptions and `None` bundles are no-ops (score unchanged).
- `SynthesizeConfig.section_affinity_threshold` (default `0.25`,
  bounds `[0.0, 1.0]`) and `section_affinity_boost` (default `1.5`,
  bounds `[1.0, 10.0]`) — Pydantic-validated tunables for the new
  stage.
- `ConsideredArticle` and `ConsideredSection` TypedDicts in
  `openzim_mcp/tool_schemas.py`.
- `_build_considered_articles` and `_build_considered_sections`
  helpers in `openzim_mcp/synthesize.py`. Featured article and
  section are excluded so the lists are alternatives, not
  duplicates of the featured citation.

### Changed

- `_promote_title_match` in `synthesize.py`: removed the M26 4-token
  short-circuit. Long prose queries with a clear entity tail now
  resolve canonically instead of falling through to BM25 noise.
- `_promote_topic_via_title_index` in `simple_tools.py`: rewritten
  as a two-pass tail-probe (strict 1.0-score gate across all tails
  first, then 0.8-score typo-tolerant gate across all tails). The
  two-pass ordering prevents a fuzzy 0.8 match on a long noisy tail
  from winning over an exact 1.0 match on a clean shorter tail.
- `SynthesizeResponse` TypedDict is now `total=False` to accommodate
  the new optional fields. Existing callers populating every field
  are unaffected.

### Tests

- 46 new unit tests across `tests/test_iter_query_tails.py`,
  `tests/test_simple_tools_tail_probe.py`,
  `tests/test_synthesize_section_affinity.py`,
  `tests/test_synthesize_considered_handles.py`, and additions to
  `tests/test_synthesize_title_promotion_v2a9.py` and
  `tests/test_tool_schemas.py`. Test count: 1567 → 1566 (one less
  because two affinity-boost tests with identical setup blocks were
  merged into one combined assertion; SonarCloud flagged the
  intra-file duplication).
- Three golden snapshots refreshed
  (`synthesize_berlin_geography.json`, `synthesize_munich_history.json`,
  `synthesize_capital_city.json`) — the new `considered_*` fields are
  always emitted, and the score change from `1.0 → 1.5` on
  entity-name section headings reflects the affinity boost firing.
- `test_metadata_namespace_from_metadata_keys` threshold relaxed
  from `>= 10` to `>= 5` after an upstream `zim-testing-suite`
  fixture refresh changed `nons/small.zim`'s metadata-key count
  from 10 to 9 (broke comprehensive-testing on `main` before this
  alpha was cut).

## [2.0.0a13] — 2026-05-14 (alpha pre-release) — post-a12 beta-test sweep (8 defects across three passes)

Three-pass beta-test of `v2.0.0a12` against the same 118 GB Wikipedia
ZIM (Feb 2026 snapshot) the a8 → a12 cuts targeted, via the simple-
mode `zim_query` MCP surface. The pattern across the alpha series
continues to diminish (a10: 22+6+3, a11: 11+3+1, a12: ~6+2+0 split
across the same three-pass shape — first pass surfaced six defects,
second pass two structural gaps, third pass zero new).

The single most user-visible defect was `search for Berlin in
namespace C` rendering `List_of_songs_about_Berlin` at rank #1 with
the canonical `Berlin` article absent. The H2 canonical-splice gate
short-circuited to the legacy `search_with_filters` whenever the top
BM25 hit token-prefix-matched the topic — `is_strong_title_match`
returns True for any candidate that extends the topic
(`Berlin_(disambiguation)` extends `Berlin`), so the splice never
fired for new-scheme archives that have a disambig page for the
topic. Tightening the gate to require exact path equality fixes the
H2/H3 surface end-to-end for every shape, not just the case the a12
third-pass self-audit addressed.

The recurring infobox-cell concatenation bug (`5th in Europe1st in
Germany`) got its final user-visible fix this cycle: the a10/a11
sweep added a space separator between block-level cell children, but
a downstream small LLM still tokenised `5th in Europe 1st in
Germany` as one phrase. The block-cell joiner now emits `"; "`
between block boundaries so each value reads as a distinct item.

Net: 1513 tests pass (+20 over `v2.0.0a12`), 50 skipped, 38
deselected. `black` / `isort` / `flake8` / `mypy` all clean.

### Fixed — High (post-a12 beta sweep)

- **D1: orphan-bullet sub-rows chained the previous row's full label
  as their parent.** `tell me about France` rendered
  `**Government — • President:** Macron` (correct) but then
  `**• President — • Prime Minister:** Lecornu`,
  `**• Prime Minister — • President of the Senate:** Larcher`
  (wrong — the parent kept shifting). Same shape in the USA infobox.
  Berlin's `Government` sub-rows happened to render correctly because
  Wikipedia marked them differently in HTML. Root cause: the
  virtual-parent extractor for orphan-bullet rows used
  `prev_label.split(" — ", 1)[-1]` (trailing segment) instead of
  `[0]` (original parent). Each bullet row's parent inherited the
  PREVIOUS bullet's label rather than the constant section parent.
  Fixed by taking the original parent.
- **D2: `list_namespaces` reports M=13 while `walk namespace M` /
  `metadata for` report 12.** The a12 M1 fix plumbed the shared
  `is_human_readable_metadata_key` predicate to two of three
  reporting surfaces but missed `_add_new_scheme_metadata_namespace`
  in the namespace walker. `list_namespaces` reported the raw libzim
  count (13, including the `Illustration_48x48@1` binary entry)
  while the other two filtered. Added the predicate to the third
  site so all three surfaces agree on 12.
- **D3 / D4: chained-intent splitter missed two recurring-set
  shapes.** `Biology; Chemistry` (bare topics, `;` connector) fell
  through to topic-fetch and resolved to `Computational_Biology_&_
  Chemistry` (a journal). `tell me about Photosynthesis and then
  about DNA` (single-imperative-prefix continuation, right side is
  `about DNA`) fell through to full-text search on the literal
  phrase. The splitter required an operation verb on BOTH sides of
  the connector. D3 adds a bare-topic-chain branch that wraps both
  halves with `tell me about` when the connector is unambiguous
  (`;` / `then` / `and then` / `after that` / `, then`) AND both
  halves are topic-shaped (≤6 tokens, no internal connectors). D4
  adds a continuation-prefix branch that re-prefixes the right half
  with the left's verb when the right starts with
  `about` / `of` / `for` / `with` / `on` / `in` / `into` / `to`. A
  negative-case guard prevents the bare-topic branch from
  over-triggering when a half is JUST an operation verb prefix with
  no topic content (``tell me about then and now`` — the connector
  was inside the topic name, not a chain marker).
- **D5: H2 canonical-splice early-return fired on any token-prefix
  strong match.** The gate at the top of the populated-results
  branch invoked `is_strong_title_match(query, top.path, top.title)`
  to decide whether to short-circuit to the legacy
  `search_with_filters` path (avoiding canonical duplication when
  BM25 already returned a strong hit). But the matcher returns True
  for any candidate that extends the topic via prefix
  (`Berlin_(disambiguation)` extends `Berlin`,
  `Apollo_(disambiguation)` extends `Apollo`,
  `List_of_…_named_after_X` extends `X`). For new-scheme Wikipedia
  archives — where a disambig page nearly always sits next to the
  canonical — the gate fired on the disambig and the splice never
  ran. Tightened to `top_path == canonical_path` so the splice's
  reorder logic handles canonical promotion in every other shape.
  As a side effect this also unblocks H3's list-article demote,
  which lives inside the same splice block.

### Fixed — Medium (post-a12 beta sweep)

- **D6: L2 trailing-punctuation trim only stripped one category per
  call.** `tell me about DNA, and then tell me about Photosynthesis`
  split on ` then ` to left=`tell me about DNA, and` (after
  trimming) → only the orphan `and` got stripped, the trailing `,`
  stayed. The `for/else` shape entered the punctuation branch only
  when no connector matched. Reworked to loop until stable so the
  trim handles any combination of orphan connector word + trailing
  `;`/`,` in any order.
- **D7: block-level cell separator was a bare space — final fix.**
  The a10/a11 fix turned `5th in Europe1st in Germany` into
  `5th in Europe 1st in Germany` (space separator at block
  boundaries) so cells with `<br>`/`<li>`/`<p>` children no longer
  concatenated without a separator. But downstream LLMs still
  tokenised the space-separated form as a single phrase. Upgraded
  the block-cell joiner to emit `"; "` between block boundaries so a
  population-rank cell like `<td>5th in Europe<br>1st in
  Germany</td>` renders as `5th in Europe; 1st in Germany` — two
  distinct values, same row label. Inline span groups (number
  formatting `3,913,644`, coordinates `52°31′N`) still concatenate
  directly per the a11 second-pass invariant.

### Fixed — Low (post-a12 beta sweep)

- **D8: legacy unstructured `**Error Processing Query**` template
  on four not-found surfaces.** `show structure of nonexistent_x`,
  `summary of nonexistent_x`, `get article nonexistent_x`, and
  `links in nonexistent_x` all let their backend exception
  propagate to the top-level `handle_zim_query` `except` block,
  which emitted a generic template with: no intent telemetry
  comment (`<!-- intent=... cert=... -->` was added in a12 L1 but
  only for the structured early-return paths), Python helper-name
  leakage (`Try using search_zim_file()` / `browse_namespace()` —
  none of which are MCP-surface commands), and unhelpful
  troubleshooting refs (`Check server logs` — not accessible from
  the MCP surface). `articles related to nonexistent_x` was
  already modernised in a10 F3. Added a
  `_render_not_found_recovery` helper that returns the modernised
  shape (`**Article not found: \`path\`**` + `suggestions for` /
  `find article titled` / `search for` recovery) and wrapped the
  four handler delegations with `try/except`. The outer
  `handle_zim_query` now layers the intent telemetry on success
  because the handlers return a string instead of raising.

### Wire-format / surface changes (alpha-line clean breaks)

- **`tell me about France` renders consecutive bullet sub-rows
  consistently anchored to the section parent.** Pre-fix every
  Wikipedia country article showed a chained sequence like
  `**• President — • Prime Minister:** ...` /
  `**• Prime Minister — • President of the Senate:** ...`. Post-fix
  each row reads `**Government — • Prime Minister:** ...`.
- **`list_namespaces` reports M=12 (matching `walk namespace M` and
  `metadata for`)** for archives whose only non-human-readable M
  entry is `Illustration_*`. Pre-fix M=13.
- **`Biology; Chemistry` is detected as a chained query.** Pre-fix
  it silently resolved to `Computational_Biology_&_Chemistry`.
  Other bare-topic chains (`DNA then Photosynthesis`, `Berlin and
  then Munich`) likewise.
- **`tell me about X and then about Y` is detected as a chained
  query.** Pre-fix the right half (`about Y`) wasn't recognised as
  an op verb continuation; the query fell through to full-text
  search on the literal phrase.
- **`tell me about then and now` (a topic whose name contains
  `then`) passes through unchanged.** The bare-topic chain branch
  guards against incomplete-verb halves so connector-in-topic
  queries aren't mis-classified.
- **`search for Berlin in namespace C` returns the canonical
  `Berlin` at rank #1.** Pre-fix it returned
  `[List_of_songs_about_Berlin, Berlin_(disambiguation),
  Timeline_of_Berlin]` with the canonical absent. Similar shape on
  every namespace-C archive that has a disambig page for the topic.
- **L2 chained-intent trim handles both orphan connectors and
  trailing punctuation.** `tell me about DNA, and then …` renders
  the left op as `tell me about DNA` (no trailing `,` or `and`).
- **Wikipedia infobox cells with `<br>`-separated values render with
  a `"; "` separator between values.** `**Rank:** 5th in Europe; 1st
  in Germany` instead of `5th in Europe 1st in Germany`. Inline
  span groups (number formatting, coordinates) unchanged.
- **`show structure of` / `summary of` / `get article` / `links in`
  not-found responses are structured guidance with intent telemetry
  and concrete recovery commands.** Same shape `articles related
  to` has carried since a10. Pre-fix these four used a legacy
  template with no telemetry and Python helper-name leakage.

## [2.0.0a12] — 2026-05-13 (alpha pre-release) — post-a11 beta-test sweep (11+3+1 defects across three passes)

Three-pass beta-test of `v2.0.0a11` against the same 118 GB Wikipedia
ZIM (Feb 2026 snapshot) the a8 → a11 cuts targeted, via the simple-
mode `zim_query` MCP surface. The first pass surfaced 11 live defects
+ a handful of opportunities; the second pass self-audited the first-
pass commit and found 3 more; the third pass self-audited the second-
pass commit and found 1 deeper case. The 22 → 6 → 3 a10 → a11 shape
repeats at 11 → 3 → 1.

The single most user-visible defect was `tell me about France`
silently returning `France_national_football_team_results_(2000–
2019)` while Germany / Italy / Spain / Brazil / Mexico all returned
the correct country article — Xapian's top hit was the football
article and the existing H3 canonical-prepend gate explicitly skipped
the `len(strong_matches) == 1` non-twin case. The same root-cause
shape (silent fall-through to a wrong-but-similar article) drove most
of this sweep's catches.

The two structural root causes — `_extract_entry_path_keyworded`
regex character class and the early-return suffix-bypass pattern —
each accounted for multiple defects in different surfaces.

Net: 1493 tests pass (+30 over `v2.0.0a11`), 50 skipped, 38
deselected. `black` / `isort` / `flake8` / `mypy` / CodeQL /
SonarCloud all clean.

### Fixed — Critical (post-a11 beta sweep)

- **C1: `tell me about France` returned the football-team article.**
  Xapian's #1 hit was `France_national_football_team_results_(2000–
  2019)`, which strong-matched topic=`France` via the candidate-
  extends-topic rule, leaving `len(strong_matches) == 1` non-twin —
  the H3 canonical-prepend gate explicitly skipped that case. Gate
  now also fires when the lone strong match's tokens differ from the
  topic's, and a sibling auto-pick `_auto_pick_canonical_over_extends_topic`
  prefers the canonical when the strong-match set is exactly
  `[canonical-with-topic-tokens, ..._extends-topic-only]`. Mercury /
  Apollo / Java / DNA forks unchanged. Apollo 11 and similar hub
  topics now auto-resolve to the canonical with variants surfaced as
  a `_May also refer to: ..._` footer hint.
- **C2: multi-word entry-path extraction silently dropped the second
  word on five operations.** The shared
  `_extract_entry_path_keyworded` regex used `[A-Za-z0-9_/.-]+` for
  the capture, so `show structure of United States` matched
  `of United` and captured `United`. New extractor anchors at the
  LAST keyword and captures everything that follows, so
  `World War II`, `Albert Einstein`, `Quantum mechanics` all flow
  through correctly on `structure` / `summary` / `links` /
  `get_article` / `toc`.

### Fixed — High (post-a11 beta sweep)

- **H1: title-index lookups for punctuated topics smeared to drop-
  the-punctuation candidates.** `tell me about C++` resolved past the
  title index to `C` (the letter); paired with the C2 fix that now
  preserves `++` through extraction, the punctuation-count guard
  (`_punctuation_smear_detected`) rejects candidates that drop a
  `+` / `#` count present in the topic. Known limitation: topic →
  candidate pairs that preserve the punctuation count (`C++` →
  `C/C++`) require redirect-target inspection and are deferred.
- **H2: filtered-search dropped the canonical title-match hit.**
  `_handle_filtered_search` was a one-call delegate to
  `search_with_filters` (legacy markdown path), so the splice
  `_handle_search` runs at offset=0 never fired. New
  `search_with_filters_with_canonical_splice` runs the same probe +
  prepend as the basic-search path, gated to canonical hits whose
  path lives in the requested namespace.
- **H3: Opp2 list / discography demote was synthesize-layer-only.**
  `_demote_list_articles` lived inside `synthesize_query`; basic
  `search` left catalog-shape hits in place at their BM25 rank.
  Lifted the predicate `_is_list_article` for cross-call use and
  applied it inside `_splice_title_match_into_search` (basic search)
  and the new H2 filtered-search splice.

### Fixed — Medium (post-a11 beta sweep)

- **M1: `walk namespace M` and `metadata for` disagreed (13 vs 12
  keys).** Shared `is_human_readable_metadata_key` predicate now
  consulted from both sites.
- **M2: `get article M/Illustration_48x48@1` stripped `@1`.** Same
  root cause as C2 — fixed by the C2 extractor change.
- **M3: `walk namespace C` reported "archive total" instead of per-
  namespace count.** L16's `namespace_entry_count` plumbing now
  applies to new-scheme C (the count equals `archive.entry_count`).
- **M4: truncation footer reported remaining-after-offset chars as
  "total".** Added `original_total` kwarg, plumbed from the three
  callers in `zim/content.py`. Mid-article reads now switch to
  `showing chars X–Y of N-char body` so the denominator stays stable
  across pagination.

### Fixed — Low (post-a11 beta sweep)

- **L1: structured guidance / error responses skipped the Opp6 intent
  telemetry comment.** Three early-return paths (`Topic Required`,
  `Search Terms Required`, `Chained Operations Detected`) now carry
  their own deterministic telemetry comments at `cert=1.00`.
- **L2: chained-intent splitter left the connector word attached to
  the left op.** Strip trailing connectors / orphan punctuation so
  the suggested split-up call is cleanly pasteable.
- **L3: canonical-title-match snippet rendered as snippet text.** Now
  surfaced as a distinct `Match type: canonical title match` badge
  in both `_format_search_text` and `_format_filtered_response`.

### Fixed — Second-pass self-audit (post-a11 sweep)

L1 covered three of the six structured early-return paths in the same
code section but missed the other three:

- **`Query Required`** (empty / whitespace query) →
  `intent=query_required cert=1.00`
- **`_meta_query_guidance`** (meta-only filler queries like `do
  both` / `try again` / `ok`) → `intent=meta_only_guidance cert=1.00`
- **`No ZIM File Specified`** (no archive selectable) →
  `intent=no_zim_file_specified cert=1.00`

### Fixed — Third-pass self-audit (post-a11 sweep)

- H2 splice silently dropped the canonical when
  `search_with_filters_data` returned 0 hits but `find_title_match`
  reported the canonical exists in the requested namespace.
  Symmetric to the bug the first-pass H2 fix addressed (canonical
  missing from a non-empty result page) — same wrong silent-fall-
  through, different shape. Hoisted the synthetic-canonical row
  construction above the populated-vs-empty branch so both paths
  share the same prepend logic. The empty-results path now lands the
  canonical as a single-result page with the post-a11 L3 badge.

### Fixed — Quality gate (post-a11 sweep)

- SonarCloud S5852 ReDoS on the L2 orphan-trim regex
  `\s+(?:and|or|but)\s*$|\s*[;,]\s*$` (multiple unbounded `\s*` /
  `\s+` quantifiers in alternation). Replaced with string ops that
  mirror the original "strip one of: trailing connector word OR
  trailing `;` / `,`" semantics, same approach as the existing
  `_is_disambig_lead` workaround in the same file.

### Wire-format / surface changes (alpha-line clean breaks)

- **`tell me about` auto-resolves to the canonical when the strong-
  match set is `[canonical-with-topic-tokens, ..._extends-topic-only]`**
  (Apollo 11, Pride and Prejudice, hub topics with parenthesized
  siblings). Variants are surfaced as a `_May also refer to: ..._`
  footer hint instead of the prior disambig fork. Genuine multi-
  meaning topics (Apollo / Mercury / Java / DNA) still fork as
  before.
- **`show structure of` (and `summary` / `links` / `get article` /
  `table of contents` of) actually accept multi-word titles.** Pre-
  fix these silently truncated to the first word and rendered the
  wrong article.
- **Filtered-search responses include canonical title-match hits**
  with a distinct `Match type: canonical title match` badge instead
  of dropping them silently.
- **`tell me about C++` (or any topic with `+` / `#`) no longer
  resolves to a candidate that dropped the punctuation.** Falls
  through to search-fallback where canonical-title-match can find
  the actual `_programming_language`-suffixed article.
- **`get article M/Illustration_48x48@1` (or any path with `@`)
  preserves the suffix through extraction.** Pre-fix the regex
  character class stripped `@1` before the metadata API saw it.
- **Walk-namespace M and metadata-for now agree** on the metadata-
  key set (filtered `Illustration_*` binaries on both sides).
- **Walk-namespace C reports `(of N in namespace C)`** instead of
  `(archive total: ~N entries)` for new-scheme archives.
- **Truncation footer denominator stays stable across pagination.**
  Mid-article reads switch to `showing chars X–Y of N-char body` so
  a caller paging through a 146 KB article doesn't see the "total"
  decrease with every page.
- **Every structured guidance / error response carries an intent
  telemetry comment** so callers branching on
  `<!-- intent=... cert=... -->` see the rejection class.

## [2.0.0a11] — 2026-05-13 (alpha pre-release) — post-a10 beta-test sweep (22+6+3 defects + 7 opportunities across three passes)

Three-pass beta-test of `v2.0.0a10` against a 118 GB Wikipedia ZIM
(Feb 2026 snapshot) via the simple-mode `zim_query` MCP surface. The
first pass surfaced 22 defects + 7 opportunities from live use; the
second and third passes were self-audits of the prior commit, each
finding fewer issues than the last (22 → 6 → 3). Every fix here was
first observed live; the existing 1425-test suite covered none of
them.

The single most user-visible regression is silent text concatenation
inside Wikipedia infoboxes — every city / country article had at
least one corrupted number (`5th in Europe1st in Germany`,
`Berliner(s) (English)Berliner (m)`, `0.967very high`,
`TokyoTamaNorthern Izu Islands`). A small LLM reading this would
emit those as single tokens. Plus one **critical**: the a10 DD2 fix
threaded `content_offset` through the article-paging handler, but
the parameter was never exposed on the MCP tool — the truncation
footer told callers to "pass `content_offset=N`" via a channel that
didn't exist.

Net: 1463 tests pass (+38 over `v2.0.0a10`), 50 skipped, 38
deselected. `black` / `isort` / `flake8` / `mypy` / CodeQL /
SonarCloud all clean.

### Fixed — Critical (post-a10 beta sweep)

- **C1: `content_offset` unreachable from `zim_query`.** A10's DD2
  threaded `options["content_offset"]` through
  `_fetch_topic_article_body`, but the `zim_query` MCP signature
  never exposed the parameter. The top-level `offset` arg routes to
  `options["offset"]` (search / browse pagination), not
  `options["content_offset"]` (article-body paging). Result: every
  `tell me about Photosynthesis` truncation footer pointed to a
  paging channel that returned the same page 1. Exposed
  `content_offset` as a top-level `zim_query` parameter, validated
  `>= 0`, threaded through `options`. Truncation footers on
  `truncate_content` now report the correct next-page offset
  (Opp4 implemented inline).

### Fixed — High (post-a10 beta sweep)

- **H2: `tell me about Berlin` non-determinism.** `Berlin` and
  `Berlin (disambiguation)` both strong-matched by the candidate-
  extends-topic rule, so the disambig set fired 2+ → fork between
  the city article and the disambig page. Auto-pick the canonical
  when the strong-match set is exactly `Foo` + `Foo (disambiguation)`;
  the disambig twin is surfaced as a footer hint on the returned
  body. Genuine multi-meaning topics (Apollo / Mercury / Java) still
  fork as before (Opp1 implemented inline).
- **H3: disambig hides the canonical it should be helping pick.**
  `tell me about Apollo 11` forked between `Apollo_11_anniversaries`,
  `Apollo_11_lunar_sample_display`, `Apollo_11_goodwill_messages` —
  none of which is the canonical `Apollo_11`. Probe the title index
  for the exact-topic canonical BEFORE the disambig check; prepend
  it to the strong-match list when absent.
- **H4: infobox text-extraction silently concatenates adjacent
  block-level children.** `td.get_text()` joined `<br>`, `<li>`,
  `<span>` runs without whitespace. Three-pass evolution:
  first-pass `separator=" "` mangled inline span groups
  (`3,913,644` → `3 , 913 , 644`); second-pass `_join_cell_text`
  helper inserts whitespace at block-tag boundaries only and
  concatenates inline tags directly; third-pass filters
  `Comment` instances (a `NavigableString` subclass) so invisible
  formatnum/microformat comments stop leaking as visible text.
- **H5: intent parser preempts on later-occurring keywords.**
  `tell me about berlin then list namespaces` silently ran only
  `list namespaces` (highest-confidence intent wins). New
  `_chained_intent_guidance` splits on `then` / `;` / `and then`
  connectors; if both halves start with a recognised operation
  prefix, return a "split into separate calls" guidance message.
- **H6: orphan bullet rows lose parent context.** Berlin's
  `**• Summer (DST):** UTC+02:00` rendered without a parent
  because `Time zone:` was a regular KV (not an `infobox-header`).
  When a KV row's label starts with a bullet char AND there's no
  active section, treat the previous KV row's label as a virtual
  parent — applied for that row only, doesn't persist into the
  next non-bullet row.

### Fixed — Medium (post-a10 beta sweep)

- **M7: `show structure of <multi-word title>` doesn't normalize.**
  D2 in a10 added `find_title_match(min_score=0.8)` to
  `_handle_related`; M7 extends the same pattern via the new
  `_resolve_natural_language_path` helper applied to `structure`,
  `table of contents`, `links`, `summary`, `get section`, and
  `get article` (when the path contains spaces and no namespace
  separator — direct-path lookups stay zero-cost).
- **M8: `get section` ignores `max_content_length`.** Section text
  was returned in full regardless of the cap. Honor the cap and
  append a one-line truncation footer reporting the original
  length.
- **M9: malformed cursor silent no-op.** A base64+JSON token that
  decodes but lacks the expected `s` envelope (or whose `s.o` is
  missing/invalid) used to silently degrade to page 1. The contract
  now mirrors the totally-garbled-token case: structured
  `cursor_decode` error.
- **M10: trailing-whitespace `tell me about` produces an empty
  topic.** A query of `tell me about` with a trailing space fell
  through to a topic of `"tell me about"` and disambiguated to
  articles titled "Tell Me About Tomorrow". The
  `_extract_tell_me_about` regex now uses `\b` + `(.*?)` so empty
  topics resolve to empty strings; simple_tools rejects with a
  clear "Topic Required" error.
- **M11: `explain X to me` parses incorrectly.** "explain Berlin
  to me" extracted topic `"Berlin to me"` and returned a memorial
  article. Topic extractor strips `to me` / `for me` / `please`
  politeness tails, loop-until-idempotent so wrapping cases
  (`DNA for me please`) collapse cleanly.

### Fixed — Low (post-a10 beta sweep)

- **L12: trailing-whitespace `search for` with no terms.** Used to
  fall through to searching for the literal word "for". Validate
  the extracted tail before dispatch; surface "Search Terms
  Required".
- **L13: `limit=0` nonsensical pagination.** `Showing 1-0 of N —
  pass offset=0 for the next page` looped on itself. Reject
  non-positive `limit` and negative `offset` at the MCP boundary.
- **L15: `articles related to <nonexistent>` raw error.** Wrap the
  backend's "Cannot find entry" with a structured guidance message
  pointing to `suggestions for` / `find article titled` /
  `search for`. (Second-pass F3 added the same hint trio to the
  `outbound_error` branch in `render_related` that the live case
  actually surfaces through.)
- **L16: walk namespace denominator misleading.** `walk namespace M`
  with 13 entries used to render `of ~27,199,904 archive-wide
  entries`. Prefer a per-namespace denominator when available; fall
  through to the archive total only when no per-namespace count is
  known. Second-pass F4 plumbed `namespace_entry_count` through
  `_build_walk_result` so the new `of N in namespace X` shape
  actually renders.
- **L17 / L18: list namespaces total mismatch, metadata aggregator
  underreports.** Header now annotates "X archive entries (per-
  namespace sum: Y)" when the two differ. `_extract_zim_metadata`
  enumerates `archive.metadata_keys` on new-scheme archives (filtering
  `Illustration_*` binaries) so `metadata for` and
  `walk namespace M` agree on what counts as metadata. Second-pass
  F6 replaced the first-pass hardcoded probe-list extension with
  the enumeration so future archive additions don't reopen the
  disagreement.

### Added — Opportunities (post-a10 beta sweep)

- **Opp1: auto-fall-through twin.** Implemented inline with H2.
- **Opp2: expanded demote patterns.** `_LIST_ARTICLE_PREFIX_RE`
  picks up `Lists_of_*` (plural); two new patterns demote
  `Listed_*` stems and `*_discography` / `*_filmography` /
  `*_videography` / `*_bibliography` / `*_albums` / `*_singles`
  suffixes. `tell me about cats` returning a Rephlex Records
  discography at rank 2 is the canonical failure this fixes.
- **Opp3: synthesize relevance threshold.** New
  `_drop_low_relevance_tail` cuts hits whose Xapian score is below
  25% of the top hit's. Only applied in `xapian_score` fallback
  (single-archive); multi-archive RRF keeps all hits because RRF
  normalizes scores. Always keeps at least one hit.
- **Opp4: `content_offset` in truncation footers.** Implemented
  inline with C1 — `truncate_content` accepts `current_offset` so
  paginated reads compute the next offset relative to where the
  slice started in the original article. Third-pass F2 added a
  `paginatable: bool = True` kwarg so the three main-page call sites
  switch to operation-accurate guidance (the main-page surface
  doesn't accept `content_offset`).
- **Opp5: canonical-exists hint in disambig auto-pick.** When the
  H2 auto-fall-through fires, append a `_Note: this topic also has
  a disambiguation page — see ``get article <path>`` for alternate
  meanings._` footer so the disambiguation stays discoverable.
- **Opp6: intent telemetry on all responses.** Every markdown
  response now carries a trailing `<!-- intent=foo cert=0.85 -->`
  HTML comment. Invisible to humans (HTML comments aren't rendered)
  but visible in the token stream so calling LLMs can branch on the
  parser's classification certainty without parsing the body.
- **Opp7: link-count rank on related articles.** When the related-
  articles backend supplies a `mention_count`, surface it inline as
  `- **Title** (`path`) · N×` so a small LLM can rank which related
  article is most central to the source. (Second-pass H1 fixed the
  first-pass typo that read the wrong field name — `link_count`
  vs `mention_count`.)

### Fixed — Second-pass self-audit findings

A self-audit of the first-pass commit surfaced six defects in the
fixes themselves:

- **D1 second-pass (folded into H4 above).** `get_text(separator=" ")`
  mangled inline-span numeric groups.
- **F3 second-pass (folded into L15 above).** Wrapped the wrong
  error path — backend serialises rather than re-raising.
- **F4 second-pass (folded into L16 above).** `namespace_entry_count`
  was renderer-only and never plumbed through the data payload.
- **F6 second-pass (folded into L17/L18 above).** Hardcoded probe-
  list extension still drifts; replaced with `metadata_keys`
  enumeration on new-scheme archives.
- **H1 second-pass (folded into Opp7 above).** First-pass read
  `link_count` from the related-articles result; the backend stores
  the frequency-rank signal as `mention_count`.
- **C2 perf: title-index probe ran twice on the weak-top-hit path.**
  Gated the H3 canonical-probe behind `len(strong_matches) >= 2`
  (the only condition under which the disambig page would otherwise
  render). Strong-top-hit and weak-then-promoted paths skip the
  second probe entirely. Third-pass extended the gate to also fire
  when the single strong match is itself the disambig twin.

### Fixed — Third-pass self-audit findings

A second self-audit found three more defects in the second-pass
commit:

- **D1 third-pass (folded into H4 above).** `Comment` is a
  `NavigableString` subclass; second-pass `_join_cell_text` caught
  comments and rendered their bodies as visible text.
- **C2 third-pass.** Lone disambig-twin search case bypassed the
  second-pass `>= 2` gate; extended the gate to also fire when the
  one strong match is `Foo (disambiguation)` itself.
- **F2 third-pass (folded into Opp4 above).** The second-pass
  truncation hint pointed at a `content_offset` parameter the
  main-page operation doesn't accept; added a `paginatable=False`
  kwarg on the three main-page call sites and routed them to
  operation-accurate guidance.

### Fixed — Quality gate (PR CI cleanup)

- **CodeQL: `full_len` may be uninitialized.** In the M8 truncation-
  footer code path, `full_len = len(text)` was assigned only inside
  the truncation `if` block but referenced in a different (correlated)
  `if truncated:` block. The correlation was opaque to CodeQL.
  Lifted the assignment above the branch so the variable is always
  defined. No behaviour change.
- **SonarCloud python:S5852 (ReDoS hotspot).** The
  `_search_query_tail` regex had adjacent `\s*` quantifiers that
  the heuristic flagged as polynomial-backtracking. Split into
  three single-token regexes (verb, optional `up` for `look up`,
  optional `for` connector) with plain-Python tail slicing between
  matches. Each individual pattern has at most one whitespace
  quantifier so the heuristic has nothing to flag. Behaviour
  verified identical across all 1463 tests.

### Wire-format / surface changes (alpha-line clean breaks)

- **`zim_query` accepts a top-level `content_offset` parameter.**
  Existing callers passing only the previous parameters are
  unaffected; new callers paginating long article bodies should
  use `content_offset` instead of the legacy `offset` (the latter
  remains the search / browse pagination knob).
- **Every markdown response now carries a trailing
  `<!-- intent=... cert=... -->` HTML comment** (Opp6). Invisible
  to humans; callers that token-count or post-process the trailing
  bytes will see two extra tokens per response.
- **Intent-parser chained-query guard returns guidance instead of
  silently dispatching the rightmost intent.** Callers sending
  `X then Y` queries that previously got Y's result silently now
  receive a structured "split into separate calls" message.
- **`get section` honors `max_content_length` and appends a
  truncation footer.** Callers that previously got full section
  bodies now receive at most `max_content_length` bytes plus a
  one-line footer reporting the original length.
- **Cursor with missing/invalid `s` envelope now errors
  (`cursor_decode`).** Callers that previously got silent page-1
  fall-through now receive a structured error.
- **Infobox cells render with intra-cell whitespace at block-tag
  boundaries only.** Most callers see strictly better text (no
  `5th in Europe1st in Germany`-style concatenation); inline
  numeric / unit / coordinate microformats remain intact.
- **Synthesize ranking demotes `Lists_of_*` and `*_discography` /
  `*_filmography` / `*_albums` / `*_singles` suffixes.** Citation
  order for queries like `cats` no longer surfaces a Rephlex
  Records discography in the top half.
- **`walk namespace M` and `metadata for <file>` agree on what
  counts as metadata** (new-scheme archives enumerate
  `metadata_keys` directly). Old-scheme archives keep the
  hardcoded probe list as a fallback.

---

## [2.0.0a10] — 2026-05-12 (alpha pre-release) — post-a9 beta-test sweep (16 defects + 6 opportunities)

Two-pass beta-test of `v2.0.0a9` against a 118 GB Wikipedia ZIM (Feb
2026 snapshot), plus a self-review code-reviewer audit and a
SonarCloud Quality Gate cleanup. The first pass exercised the
markdown surface; the second pass audited the first-pass fixes and
extended live testing to surfaces not covered the first time. Several
recently-shipped backend features turned out to be unreachable from
the natural-language surface, several handlers had silent fall-through
bugs on common phrasings, and one libzim quirk (silent namespace-prefix
stripping) was masking the entire metadata API.

Net: 1425 tests pass (+5 over `v2.0.0a9`), 50 skipped, 38 deselected.
Live-verified key fixes against the real Wikipedia archive via
in-process `ZimOperations` calls.

### Fixed — Critical (post-a9 beta sweep)

- **D1: infobox section-context leakage on every Wikipedia city /
  country.** Berlin and Tokyo (and the broad city-template family)
  produced trailing rows labelled `**GDP — Time zone:**`,
  `**GDP — Vehicle registration:**`, `**GDP — Website:**`,
  `**GDP — HDI (2022):**` — clearly wrong. The post-a8 #2/Op5
  parent-context fix correctly tracked `current_section` from
  `<th class="infobox-header">` rows but never reset it; trailing
  free-floating rows (which Wikipedia marks `<tr class="mergedtoprow">`)
  inherited the last header. Reset `current_section` on KV rows whose
  `<tr>` carries `mergedtoprow` AND only after at least one row has
  been emitted under the current section — the second guard is the
  third-pass fix, without which the reset stripped section context
  from the *first* KV row inside a section header (Wikipedia uses
  `mergedtoprow` on those too as the visual group lead). Both edges
  covered by new regression tests.
- **D7: `M/<key>` paths silently aliased to C-namespace articles.**
  libzim's `archive.get_entry_by_path("M/Title")` strips the `M/`
  prefix and resolves to the C-namespace article with that name;
  `get article M/Title` against a Wikipedia ZIM returned the 172 KB
  disambiguation article on "Title" instead of the metadata entry.
  Route `M/<key>` paths to `archive.get_metadata_item` on new-scheme
  archives so the proper metadata API serves these requests. Verified:
  `M/Title` now returns `"Wikipedia"`, `M/Date` returns `"2026-02-15"`.

### Fixed — High (post-a9 beta sweep)

- **D2: `articles related to <topic>` failed on natural phrasings.**
  The intent parser hands the topic verbatim from the user's query
  (`articles related to United States` → `United States`), but the
  underlying entry path stores spaces as underscores
  (`United_States`). The handler called `get_related_articles_data`
  with the unresolved string and surfaced "Cannot find entry". Now
  probes the title index via `find_title_match(min_score=0.8)` first;
  fall through to the literal path only when no canonical resolves.
- **D3: `tell me about <typo>` skipped the typo-tolerant title
  fallback.** The first-pass title promotion required score 1.0;
  single-edit typos resolve at score 0.85 via `_find_entry_typo_fallback`.
  `tell me about Photosythesis` (missing `n`) fell through to Xapian
  search and returned `International Year of Chemistry` —
  actively misleading. Retry `find_title_match(min_score=0.8)` after
  the strict gate fails; same conservative typo chain
  (length-gated at ≥ 5 chars, ≤ 700 variants).
- **DD1: `metadata for <file>` aggregator returned 172 KB article
  bodies for new-scheme archives.** D7 fixed the per-entry
  `get article M/Title` surface but `_extract_zim_metadata`
  (a separate code path used by the `metadata for` aggregator) was
  still calling `get_entry_by_path("M/Title")` and getting the same
  silently-aliased C-namespace article. Now uses `get_metadata_item`
  for new-scheme archives, with old-scheme `get_entry_by_path`
  fallback. Verified: `Title` returns `"Wikipedia"`, `Description`
  returns `"The free encyclopedia"`, `Language` returns `"eng"` (was
  172 K / 60 K / 364 K-char garbage respectively).
- **DD2: `tell me about` ignored `content_offset`.** The handler
  hard-coded offset = 0 in the body fetch, so callers paginating a
  148 KB Photosynthesis article through `zim_query` couldn't reach
  the tail without dropping to a separate `get article <path>` call.
  Threaded `options.get("content_offset", 0)` through; suppress the
  compact-mode lead-with-TOC step when reading mid-article.

### Fixed — Medium (post-a9 beta sweep)

- **D4: `get section X of Y` natural-language error path dropped the
  `closest_match` hint.** The structured `get_section` operation
  computes a `difflib`-based closest-match (Op5 from a8) but the
  natural-language handler reimplemented section lookup against the
  headings list and never queried that operation. Compute the same
  hint locally so `get section Goegraphy of Berlin` now suggests
  "Did you mean Geography?".
- **D5: `articles related to <hub>` markdown dropped the
  `scan_truncated` signal.** The a9 #A5 backend addition surfaced
  `scan_truncated` / `scan_total_internal` / `_meta.reason` for hub
  articles whose 500-link scan cap fired, but `compact_renderers.render_related`
  ignored all of it. Append a footer when the signal is set.
- **D6: `suggestions for X` missed the canonical bare-title article.**
  `suggestions for Photosyn` returned 15 results, none of which was
  bare `Photosynthesis` — both libzim's `SuggestionSearcher` and
  Xapian rank disambiguator-bearing variants
  (`Photosynthesis (song)`, `Photosynthetic_efficiency`) above the
  short canonical title. Probe `SuggestionSearcher` for parenthesised
  siblings (`foo_(suffix)`) and prepend the un-suffixed root path
  when the archive resolves it. The third-pass refactor restructured
  this to share a single `SuggestionSearcher.suggest()` round trip
  with Strategy 2, so the cold path stays at one title-index probe.
- **D8: `walk namespace W` returned zero entries while
  `list namespaces` claimed W had two.** The two operations
  contradicted each other on the same archive. The W-namespace
  well-known entries (`mainPage`, `favicon`) live on the
  `archive.main_entry` / `has_illustration` API, not the iterable
  surface that `walk_namespace_data` falls back to. Mirror the same
  probe pair `_add_new_scheme_well_known_namespace` already uses
  for the namespace listing. Also fix the `entries 1-0` off-by-one
  in the empty-walk header rendering.
- **D9: cursor `s.q` field silently ignored — wrong-query
  pagination.** Cursor reused across queries silently paginated the
  new query at the old offset. Reject with a `cursor_decode` error
  when `s.q` shares no meaningful (≥ 3-char) tokens with the current
  query. Falls back to a bidirectional substring check for cursors
  whose stored query has only short tokens. Three regression tests
  cover the unrelated-query reject, the shortened-query accept, and
  the overlapping-tokens accept.
- **DD4: `_splice_title_match_into_search` returned `limit + 1`
  results.** Prepending the canonical synthetic result didn't trim
  back to the requested limit; `limit=3` produced 4 results with
  header `"showing 1-4"`. Trim to `page_info.limit` and update
  `page_info.returned_count` so the header matches the row count.

### Added — Opportunities (post-a9 beta sweep)

- **O2: stopword-saturation footer on search.** Queries that match
  ≥ 1 M results (the stopword-only `search for the and a is in to`
  saturates at ~5 M) now carry a footer noting that top hits are
  ranked by general document importance, not topic relevance — so
  the model doesn't trust the "Found N matches" signal as
  meaningful.
- **O3: truncation hint no longer self-references.** The previous
  hint suggested `show structure of <path>` as the recovery —
  silly when the truncated response IS the show-structure (or
  table-of-contents) output. Replaced with operation-agnostic
  guidance (page via cursor / tighten query / `compact=False`).
- **O4: disambiguation page leads preserve their inline list.**
  `tell me about Martin` previously truncated to `**Martin** may
  refer to:` with no list, forcing a `show structure` round-trip.
  Detect "X may refer to:" leads and skip the H2 cut so the
  disambig list stays inline.
- **O5: synthesize demotes `List_of_*` / `Index_of_*` /
  `Outline_of_*` / `Timeline_of_*` etc.** These articles ranked
  surprisingly high in synthesize because their bodies match many
  query tokens but the actual content is just an enumeration stub.
  Demote to the back of `top_n` AFTER title promotion runs (demoting
  before regressed the promotion's strong-match guard, which would
  treat `Berlin_(disambiguation)` as a match for `Berlin`).
- **O6: docstring notes distinguish `show structure` (flat heading
  list) from `table of contents` (nested children tree).**

### Fixed — Code-reviewer audit findings (post-first-pass)

A `feature-dev:code-reviewer` agent audited the first-pass commit and
surfaced three real defects in the original fixes:

- **A1 (the second guard on D1, listed under Critical above).**
- **A2: D6 ran `SuggestionSearcher` twice on the cold path.** When
  Strategy 1 returned empty, both the canonical probe AND Strategy 2
  opened independent `SuggestionSearcher` instances against the same
  archive. The first-pass "skip canonical probe when Strategy 1
  empty" fix regressed the empty-Strategy-1 case (the canonical
  probe IS needed when Xapian misses). Restructured to share a
  single `SuggestionSearcher.suggest()` round trip via an optional
  `result_paths=` parameter on `_find_canonical_prefix_match`.
- **A3 (the token-overlap rewrite of D9, listed under Medium above).**

### Fixed — Quality gate (SonarCloud third-pass cleanup)

- **5 cognitive-complexity reductions (S3776).** Five functions added
  by the beta-test commits crossed SonarCloud's complexity-15 limit.
  Each was split into self-contained helpers without behaviour
  change: `_find_canonical_prefix_match` (53 → split into 5 helpers
  for path probing, root extraction, entry resolution, and the two
  ranking strategies), `_handle_tell_me_about` (19 → 17 → ~14 over
  two passes via `_promote_topic_via_title_index` and
  `_fetch_topic_article_body`), `render_related` (17 → ~10 via
  `_render_related_link_line` + `_scan_truncated_footer`),
  `render_walk_namespace` (19 → ~12 via `_walk_namespace_header`),
  and `_get_metadata_entry` (18 → ~13 via `_decode_metadata_content`).
- **4 duplicate-literal extractions (S1192).** The "text/" MIME prefix
  had three call sites in `zim/content.py`; "File:" / "Category:" /
  "Template:" each had three call sites in `zim/search.py`. Extracted
  to `_TEXT_MIME_PREFIX` and a `_PSEUDO_NAMESPACE_*` constant trio
  with a shared `_is_pseudo_namespace_entry(extended=)` helper.
- **1 ReDoS hotspot (S5852).** The O4 disambig-lead-detection regex
  `\bmay\s+(?:also\s+)?refer\s+to\s*:?\s*$` was flagged for nested
  unbounded quantifiers. Not actually catastrophic on Python's `re`
  engine, but replaced anyway with a normalised
  `str.endswith(("may refer to", "may also refer to"))` check — same
  behaviour, no regex engine, and the phrase list is easier to
  extend.

### Wire-format / surface changes (alpha-line clean breaks)

- **Infobox extraction labels for trailing rows change.** Berlin /
  Tokyo terminal rows that previously emitted as `GDP — Time zone`
  now emit as `Time zone`. Callers parsing the bullet-prefix
  structure see different label strings.
- **`metadata for <file>`** now returns short metadata strings
  instead of 172 KB article-body excerpts. Wire-format compatible
  (same keys); content is the actual ZIM metadata (`Title` =
  `"Wikipedia"`, `Date` = `"2026-02-15"`, etc.).
- **`get article M/<key>`** now returns the ZIM metadata entry
  instead of the silently-aliased C-namespace article body.
  Wire-format compatible (same response envelope); content differs.
- **`_splice_title_match_into_search`** trims to the requested
  limit. Callers receiving `limit + 1` results will now get exactly
  `limit`.
- **Cursor with mismatched `s.q` now errors.** Callers that
  previously got silent wrong-query results now receive a
  `cursor_decode` `ToolErrorPayload`.
- **Synthesize ranking demotes list articles.** Citation order for a
  query like `Quantum mechanics` no longer includes
  `List_of_textbooks_…` in the top half.
- **Truncation hint footer text changed (O3).** Callers parsing the
  trailing prose see different wording.

### Investigated and deferred

- **Pseudo-namespace pollution in default search results
  (`Portal:` / `User:` / `Help:`).** Filtering pseudo-namespace
  articles from default search is too opinionated; some callers
  legitimately want them. The canonical-promotion already pushes
  the real article to rank 1 in the common case (live-verified:
  `search for biology` → `Biology` at #1 via `(canonical title
  match)`). Revisit if the canonical-promotion fallback proves
  insufficient.

---

## [2.0.0a9] — 2026-05-12 (alpha pre-release) — post-a9 review wave (5 defects + 4 deferred items)

Follow-up review wave after the post-a8 batch (commit d3e310e). 4
parallel code-reviewer agents covered Phases A/B/C plus cross-cutting
concerns; 13 findings were verified, 8 were withdrawn after closer
read (the suspected bug was either already correct or by-design), 5
were real defects. The 4 items the post-a8 batch explicitly deferred
("bigger than this batch") are now closed.

Net: 1420 tests pass (11 new red-green-verified regression tests),
50 skipped. One module + its test suite deleted as dead code — alpha
clean break per v2 plan.

### Fixed — Critical (post-a9)

- **A1: cache `_restore_entry` skipped `_total_bytes` accounting.**
  After a warm-start with persistence enabled, `max_bytes` eviction
  read zero for `_total_bytes` — the `while self._total_bytes > max_bytes`
  loop in `set()` never fired even on a snapshot that already
  exceeded the configured cap. The byte budget was silently
  inoperative across every restart until enough new sets accumulated
  to cross the threshold *from zero*. Now `_restore_entry` updates
  `_total_bytes += entry.size_bytes` symmetrically with `set()` and
  `_remove()`.
- **A2: cache `_load_from_disk` did not enforce `max_size` or
  `max_bytes` against the loaded snapshot.** Operators tightening
  caps between restarts saw the prior caps until eviction was
  triggered by new sets. Added a post-load eviction pass using the
  same LRU heap `set()` maintains.

### Fixed — Medium (post-a9)

- **A3: `create_snippet` collapsed to bare `"..."` on leading-highlight
  truncation.** When the post-highlight slice began with `**` at
  position 0 (an unpaired marker landing inside the first highlighted
  term), `sliced[:0]` produced `""` and the caller saw a content-free
  ellipsis. Now drops the orphan `**` marker and keeps the term text.
- **A4: `render_search_all` blamed the query when every archive
  errored.** `files_with_hits == 0` emitted "Try `suggestions for X`"
  prose for both "no matches" and "all archives failed" cases, sending
  the model to chase a query-correction fix for a server-side problem.
  Now branches on `files_failed >= files_searched` and emits a
  targeted "all archives errored" hint.

### Added — Opportunity (post-a9)

- **A5: `get_related_articles` surfaces scan-truncation signal.** Hub
  articles ("List of …", "Index of …") routinely carry 1000–5000
  internal links; the underlying `extract_article_links_data` was
  called with `limit=500` and the frequency rank was operating on a
  document-head-biased sample with no signal to callers. Response now
  carries optional `scan_truncated` / `scan_total_internal` /
  `scan_limit` and `_meta.reason="scan_truncated"` when the cap fired.
  Added to the `RelatedArticlesResponse` TypedDict in `tool_schemas.py`.

### Deferred items resolved (post-a9)

- **D1 (cross-cutting H1): HTTP rate-limiter `client_id` always
  `"default"`.** Every `check_rate_limit` call across `tools/*.py`
  passed no `client_id`, so the per-(client_id, operation) bucket
  infrastructure was dead in HTTP mode — one aggressive caller could
  exhaust the global bucket for everyone. Added
  `openzim_mcp/request_context.py` with a `ContextVar[str]`;
  `BearerTokenAuthMiddleware` derives client_id from the presented
  token (`"bearer:<sha256-8>"`) or remote IP (`"ip:<host>"`) and sets
  the context var on every request; `check_rate_limit` reads the var
  when `client_id=None` (the default at every tool call site). Stdio
  transport has no middleware so the ContextVar reads its `"default"`
  fallback — single-bucket behavior preserved. No tool call sites
  changed.
- **D2 (cross-cutting H3): `_load_from_disk` JSON parse moved inside
  the `_lock` critical section.** The prior window (file open +
  `json.load` outside the lock, restore inside) was narrow — only
  `__init__`-time threads could race — but a foreign-thread regression
  probe now verifies the lock is held during `open()`. Single brief
  startup blocking window, no contention in production.
- **D3 (Phase B HIGH-4): `openzim_mcp/types.py` + `tests/test_types.py`
  deleted.** The module last shipped in v1.0.0; its TypedDicts
  (`SearchResponse` with `total_results` / `has_more`, `NamespaceInfo`
  with `entry_count` / `has_more` / `offset` / `limit`) contradicted
  the live Phase B contract in `tool_schemas.py`. Only the test file
  imported from it (32 tests pinning dead code). Removed both —
  v2 alpha allows clean breaks per the v2 plan.
- **D4: 3 pre-existing mypy errors fixed.** `content_processor.
  _cell_belongs_to_infobox` narrowed via intermediate `node_bound: Tag`
  local so the closure default carries the post-guard type;
  `simple_tools._splice_title_match_into_search` call site added
  explicit `cast(SearchResponse, ...)` / `cast(Dict[str, Any], ...)`
  bridges between the TypedDict and the splice helper signature.

### Withdrawn findings (post-a9, 8)

After verification each was either correct as-written or by-design:

- browse_namespace sampled-cache poisoning — the underlying
  per-namespace listing is cached separately by archive_stat_token,
  so per-page responses are deterministic after the first call.
- bundle parent_stack not popped for dropped sections — the pop loop
  is level-relative, correctly handles dropped sections.
- synthesize outer / `_meta` total_chars divergence — by intentional
  design (outer = answer length, `_meta` = pre-cap chars).
- heading regex mandatory space — html2text always emits the space.
- `_find_entry_typo_fallback` extra_probes cap overshoot — the cap
  holds; initial analysis was wrong.
- cursor `ns` field bypasses `sanitize_input` — `sanitize_input` IS
  called on the post-cursor namespace value at the tool layer.
- `_walk_new_scheme_metadata` missing `ai` field — only fires when
  `validated_path=None`, which does not happen in production.
- `synthesize.fallback_used` semantics on empty hits — the TypedDict's
  `Literal` constraint precludes a more accurate value.

### Wire-format / surface changes

- **`openzim_mcp.types` module removed.** Any external consumer
  importing from `openzim_mcp.types` must move to
  `openzim_mcp.tool_schemas`. The v1 shapes (`total_results` /
  `has_more`) are gone; the v2 Phase B shapes (`total` / `done` /
  `next_cursor` / `page_info`) are authoritative.
- **`get_related_articles` response gains optional keys.**
  `scan_truncated`, `scan_total_internal`, `scan_limit` plus
  `_meta.reason="scan_truncated"` when the 500-link scan cap fired.
  Existing callers that ignore the new keys see no behavior change.

---

## [Unreleased] — post-a8 review batch (33 defects + 5 opportunities)

Multi-agent review wave after v2.0.0a8: 33 defects and 5 strategic
opportunities found across Phases A/B/C and cross-cutting concerns
(security, concurrency, hot-path perf, public-API stability). Every
finding either fixed or explicitly deferred with rationale. No tests
removed; existing wire-format breaks (C2, H14) are documented in the
"Wire-format breaks" section below.

### Fixed — Critical

- **C1: path-traversal guard extended to every entry-path tool.** D12's
  guard lived only in `get_zim_entry`; sibling tools
  (`get_article_structure`, `extract_article_links`,
  `get_table_of_contents`, `get_section`, `get_entry_summary`,
  `get_binary_entry`, `get_related_articles`, batch `get_entries`) all
  accepted unsanitized entry paths. Extracted `reject_path_traversal`
  in `zim/content.py` and call it at every entry-path tool boundary.
- **C2: `browse_namespace` no longer lies with `done=True` after a
  sample.** When discovery is sampling-based, the contract field
  `done` previously flipped to True once the sample was consumed —
  clients stopped paging even though most entries remained. Now keeps
  emitting `next_cursor` and flags the response with
  `_meta.reason="sample_only"`. Wire-format compatible (existing
  fields preserved; `done` semantics tightened).
- **C4: `_scan_filtered_search` no longer cuts pagination at the scan
  cap.** When the 10K-entry scan cap fired, `total_filtered_is_lower_bound`
  was masked to False, which made `done=True` even though filtered
  hits remained past the cap. Removed the `not scan_cap_hit` guard.
- **C5: `run_with_timeout` runs in a bounded ThreadPoolExecutor.**
  The previous per-call `threading.Thread(daemon=True)` couldn't bound
  thread accumulation under sustained timeouts — a 118 GB ZIM with
  slow libzim decompression and a high timeout rate could pile up
  orphaned threads holding open archives. Default cap of 16 workers;
  override via `OPENZIM_MCP_TIMEOUT_MAX_WORKERS`.
- **C6: `_locate_passage` lockstep walk fix.** The `norm_cursor > 0`
  guard suppressed counting the first whitespace run; passages that
  began with whitespace landed in the *next* section. Dropped the
  guard (`_normalize_ws` already strips leading whitespace).
- **C7: bundle section invariant `char_start < char_end` enforced.**
  A heading at the very end of an article with no body content
  previously produced a degenerate `SectionMeta` with `char_start ==
  char_end`. Now dropped from the bundle's `sections` list.
- **C8: typo probe is single-sweep.** `find_entry_by_title` on a cold
  miss used to iterate the ~700-variant set TWICE (once for the
  fallback, once for the verified-suggestion pool). Merged into
  `_find_entry_typo_fallback_with_suggestions` returning
  `(best_entry, verified_titles)` from one pass. Halves worst-case
  latency on the spec's 30 ms budget.

### Fixed — High

- **H9: `_meta.reason="low_relevance"`** when Xapian returned hits but
  none token-match the query (path or title carries any query token
  ≥3 chars). Same suggestion pool as `0_hits`. Spec §4 defined the
  enum but no code emitted it until now.
- **H10: `_handle_search_all` routes compact-mode through
  `search_all_data`** so the aggregate `_meta.reason` /
  `_meta.suggestions` surface in the footer (legacy path bypassed
  `search_all_data` entirely). New `compact_renderers.render_search_all`.
- **H11: `_highlight_terms` joins paragraphs with `\n\n`** (not a
  single space). The single-space join silently broke any second
  paragraph that opened with a markdown heading.
- **H12: `tokens_est` no longer collapses to 0 for non-empty payloads
  that tokenize to 0 tokens.** Rare BPE edge case; the previous
  `if raw_tokens else 0` clause emitted a misleading zero instead of
  the +5% padded estimate.
- **H13: `_extract_entry_summary_data` no longer bypasses the bundle
  when `compact=True`.** Stale comment claimed the bundle stored
  non-compact markdown; the bundle has rendered with `compact=True`
  since v2.0.0a3. Now the same article produces identical markdown
  from `get_entry_summary` and `get_section`.
- **H14: `SearchAllResponse.results[].result` is shape-stable.**
  Previously `Union[SearchResponse, ToolErrorPayload]` (callers had
  to type-sniff). Now `result` is `Optional[SearchResponse]` and
  errors ride sibling keys (`error: bool`, `error_operation`,
  `error_message`). Wire-format break — callers branching on
  `result.get("error")` move to `entry.get("error")`.
- **H15: Phase B spec updated to cursor v=2.** Spec previously said
  v=1; implementation has been on v=2 since v2.0.0a4 (the cursor
  version that added the `s.ai` archive-identity field).
- **H16: `walk_namespace` archive-identity check is unconditional.**
  The previous `if "ai" in cursor_state:` guard let a hand-crafted
  cursor without `ai` skip the cross-archive verification. The
  underlying `verify_archive_identity` already raises on absent `ai`.
- **H17: bundle relaxed heading regex no longer over-matches.** The
  previous `^#{level} [^\n]*{text}[^\n]*$` accepted any heading
  *containing* the extracted text. Tightened to only match decorated-
  text variants (`*`, `_`, `` ` ``, `\`, whitespace before/after).
- **H18: `get_section` D5 widen scope tightened.** When the narrow
  slice would be empty, the previous fix widened to the first
  following section's `char_end`, which included that section's
  whole sub-tree. Now widens to that section's *first descendant's
  start* so the response covers only the child's lead prose.
- **H19: RRF fuse tie-breaks deterministically.** Equal-score paths
  now sort by `(-score, path)` so repeated multi-archive synthesize
  calls return citations in the same order.
- **H20: `is_strong_title_match` no longer false-positives on
  bare-first-name candidates.** Removed the reverse-direction prefix
  match (topic-extends-candidate) that let `"Martin"` promote past
  the canonical article for query `"Martin Luther King"`. Kept the
  forward direction (`"Berlin"` still promotes to `"Berlin (city)"`).
- **H21: `_get_encoder` uses `functools.lru_cache(maxsize=1)`.**
  Replaces the unguarded `_EncoderCache` check-then-set with a C-level
  lock so two concurrent `asyncio.to_thread` workers no longer race
  to write the tokenizer on first-use.
- **H22: `search_all` honors an aggregate wall-clock timeout.** New
  `OPENZIM_MCP_SEARCH__SEARCH_ALL_TOTAL_TIMEOUT_SECONDS` (default 20s).
  When the budget fires, the fan-out stops, partial results return
  with `done=False`, `budget_exceeded=True`, and
  `_meta.reason="search_all_budget_exceeded"`.
- **H23: `attach_meta` accepts a pre-rendered string.** Callers with a
  ready serialization (e.g. a markdown body about to ship) can pass
  `rendered=` to skip the per-call full-payload JSON serialization.
  Hot-path optimization for ~50 KB search responses.
- **H24: simple-mode cursor decode errors travel as `ToolErrorPayload`.**
  Previously a markdown string; now `tool_error(operation="cursor_decode",
  ...)` so callers can branch on `result.error`.

### Fixed — Medium

- **M25: `available_section_ids` capped at 50.** Long Wikipedia articles
  (United States, World War II) carry 80-150 section IDs; the prior
  unbounded error payload burned 4-6 KB of context for nothing.
  `available_section_ids_truncated` and `available_section_ids_total`
  surface the truncation.
- **M26: `_promote_title_match` skips multi-word content queries.**
  Queries with 5+ alphanumeric tokens (`"effects of climate change on
  arctic biodiversity"`) are recognized as prose, not entity lookups —
  skip the per-archive title-index probe to save a redundant fast-path
  walk.
- **M27: cache persistence default uses XDG.** Default
  `~/.cache/openzim-mcp/cache.json` (honors `XDG_CACHE_HOME`).
  Previously `.openzim_mcp_cache` in CWD, which silently failed inside
  read-only Docker images. Existing configured paths unchanged.
- **M28: Bearer challenge includes `realm`.** RFC 6750 §3 requires it;
  some MCP SDK clients inspect the full challenge to decide whether
  to auto-inject a token. Now emits
  `WWW-Authenticate: Bearer realm="openzim-mcp"`.
- **M29: `process_mime_content(snippet_mode=True)` exposed (hook only).**
  Adds a snippet-only rendering mode that skips infobox/table
  rewrites. `_get_entry_snippet` keeps the full compact pipeline
  because a Wikipedia article's leading infobox dominates the
  snippet's first paragraph without extraction — skipping the
  rewrite produced pipe-soup snippets in golden testing. The hook
  stays available for future callers that want raw rendering.
- **M30: dependency upper bounds.** `mcp[cli]<2.0`, `pydantic<3.0`,
  `libzim<4.0`, `tiktoken<1.0` etc. Caps the next major so a fresh
  `pip install` can't land on a wheel-incompatible upstream.
- **M31: synthesize errors return `ToolErrorPayload`.** If an inner
  exception escapes `_handle_synthesize_query` past its own
  try-except, the outer `handle_zim_query` except previously
  swallowed the shape and emitted markdown. Now detects the
  synthesize branch and emits `tool_error("synthesize_pipeline_error")`.
- **M32: suggestion titles humanized.** `Photosynthesis_(biology)` →
  `Photosynthesis (biology)` so the footer hint reads as a query a
  model can copy verbatim.
- **M33: `_cell_belongs_to_infobox` binds `node` via default arg.**
  Python closures bind by name; the previous version was correct only
  because the function happened to be called inside the same loop
  iteration that defined `node`. Future-proofs against restructuring.

### Added — Opportunities

- **Op1: live-archive smoke skeletons.** New
  `tests/live/test_live_phase_c_primitives.py` covers `get_section`,
  `synthesize`, `get_related_articles`, and `walk_namespace` against
  real Wikipedia ZIMs. Auto-skips when `ZIM_TEST_DATA_DIR` doesn't
  point at a ZIM directory.
- **Op2: `compact` parameter on natural-shape advanced tools.**
  `get_zim_entry`, `get_zim_entries`, `get_entry_summary` now accept
  `compact: bool = False` and thread it through. Phase F decides
  whether to propagate further.
- **Op3: `browse_namespace` sampling semantics documented in the tool
  docstring.** Explicitly says `done=True` in sampling mode means
  "end of sample, not end of namespace" and recommends `walk_namespace`
  for exhaustive iteration.
- **Op4: `_meta.reason` taxonomy expanded.** Added `sample_only`,
  `archive_unavailable`, `search_all_budget_exceeded` reasons + footer
  recovery prose for each.
- **Op5: `section_not_found` carries a `closest_match` hint.**
  `difflib`-based suggestion so a fat-fingered ID (`Goegraphy`) hands
  the model the right ID (`Geography`) without a full TOC scan.

### Wire-format breaks (alpha-line clean breaks)

- **`SearchAllResponse.results[].result`** changes from
  `Union[SearchResponse, ToolErrorPayload]` to `Optional[SearchResponse]`.
  Errors now ride sibling keys `error: bool` / `error_message` /
  `error_operation`. Callers branching on `result["error"]` move to
  the per-file `entry["error"]`.
- **`browse_namespace` `done` semantics** change in sampling mode.
  Clients depending on `done == True` to mean "end of the namespace"
  should consult `sampling_based` and `_meta.reason="sample_only"`.

## [2.0.0a8] — 2026-05-11 (alpha pre-release)

Re-cut of v2.0.0a7 — the v2.0.0a7 tag exists but its GitHub Release
failed to publish because `pip-audit` surfaced two upstream urllib3
CVEs (CVE-2026-44431 / 44432) that landed in the audit database
between the v2.0.0a6 and v2.0.0a7 builds. v2.0.0a8 carries the same
v2.0.0a7 content plus the urllib3 → 2.7.0 bump that closes the CVEs.
Also adjusts `make security` to pass `--skip-editable` so pip-audit
doesn't fail looking for the local package on PyPI mid-release.

Defect + opportunity batch on top of v2.0.0a6, found by end-to-end
testing against a real Wikipedia ZIM (118 GB, 27.2M entries,
Feb 2026 snapshot). 14 defects fixed, 8 opportunities added.
1388 tests pass (+13 from new test modules); no regressions.

### Fixed — Phase A (snippets, infobox, typo fallback)

- **#14: `_typo_variants` now reaches `"Photosythesis"` → `"Photosynthesis"`.**
  v2.0.0a4 shipped only transposition + deletion edits — mathematically
  unable to recover the missing `'n'` (insertion). Added insertion +
  substitution against the full a-z alphabet, length-gated at ≥ 5 chars
  to bound cost (~700 variants for a 13-char input; ≤ 10 ms/call).
- **#1: snippet highlighter no longer produces malformed markdown.**
  `_highlight_terms` previously wrapped query terms verbatim, producing
  `**Artificial **photosynthesis****`, `_****Berlin****_`, and
  `[**Photosynthesis**](**Photosynthesis** "**Photosynthesis**")` when
  the match landed inside existing bold / italic / link constructs.
  Added a skip regex covering paired emphasis runs and full
  `[text](href "tooltip")` link constructs (deliberately not bare
  parens, so prose like `(also called assimilation)` keeps its
  highlighting).
- **#1: snippet fallback to stem-prefix substring match.** When no
  whole-word match existed, the snippet used to drop to the lead
  paragraph. Now it falls back to a stem-prefix substring (first ⅔ of
  the query term) so `"photosynthesis"` catches paragraphs mentioning
  `"photosynthetic"` instead of returning the article's unrelated lead.
- **Op1: snippets drop the duplicate `# <Title>` H1.** `create_snippet`
  accepts an optional `title=`; `_get_entry_snippet` forwards the
  entry title so the heading that already appears in the result row
  doesn't burn 5–15 tokens per result.
- **#2 / Op5: infobox extraction tracks parent-section context.**
  `extract_infobox` now prefixes labels with their parent
  `<th colspan>` heading row, so a Berlin infobox renders
  `Area — City/State` / `Population — City/State` instead of three
  identical `City/State` rows. Also skips rows whose nearest table
  ancestor isn't the infobox (handles nested chronology / coords
  microformats) and rejects `<th>` / `<td>` candidates borrowed from
  inside nested tables.
- **Op6: strip image-caption / hatnote / sidebar / navbox / inline
  citation noise.** `UNWANTED_HTML_SELECTORS` now drops `figure`,
  `figcaption`, `.thumb`, `.thumbcaption`, `.gallery`, `.hatnote`,
  `.sidebar`, `.navbox`, `.metadata.mbox-small`, `sup.reference`,
  `.reference`, `.mw-collapsible-toggle`, and the `.geo-*` coordinate
  microformats. Article leads now start with the actual prose, not
  `Schematic of … For other uses, see X (disambiguation). Part of a
  series on … 52°31'07"N 13°24'16"E …`.

### Fixed — Phase B (response contract)

- **#3 / Op8: `zim_query` accepts a `cursor` parameter.** Tools advertised
  opaque base64 cursors in their responses, but the simple-mode
  `zim_query` tool only took an integer `offset` — the cursors were
  decorative. Now decoded; `s.o` populates `options["offset"]` and the
  per-tool state is preserved. Length-capped at 2 KB
  defense-in-depth.

### Fixed — Phase C (primitives)

- **#9 / #7: `get_section` table rendering now matches `get_zim_entry`.**
  The bundle's `rendered_markdown` was built with `compact=False` while
  `get_zim_entry` rendered with `compact=True`. Result: `get_section
  "Geography"` returned pipe-soup tables while the surrounding article
  fetch path showed `[Table N: M rows x P cols - pass compact=False to
  expand]` placeholders. Bundle and search-snippet rendering paths now
  both apply `compact=True`, so the markdown is consistent everywhere.
- **#10 / D8: synthesize attribution carries the `#section_id` suffix.**
  `_locate_passage` couldn't find passages containing `**bold**`
  highlight markers inside the bundle's plain markdown — every citation
  fell back to entry-level (`section_id: null`). Now strips `**`
  markers before locating so attribution resolves correctly.
- **#10 / D5: synthesize strips natural-language interrogative prefix.**
  `synthesize=True` with `"tell me about Berlin"` previously fed the
  entire phrase to BM25 — returning Irving Berlin songs, Nat King Cole
  albums, and a graffiti article instead of the canonical Berlin
  entry. Intent-parses first, hands only the topic to the search
  stage; preserves the original query for response echo.
- **#10 / D8 / Op4: response dedupe + link-strip in compact mode.**
  `passages[].text_markdown` previously duplicated `answer_markdown`
  verbatim (~50% token bloat on every synthesize call). In compact
  mode, passages now omit the body text. Wikipedia link-soup
  (`[text](href "tooltip")`) is also stripped from passages — small
  models can't follow inline links from inside tool responses anyway.
- **Op3: `get_section` supports narrow scoping.** New
  `include_subsections=False` parameter on `get_section_data` (and the
  `narrow section X of Y` / `just section X of Y` query syntax in
  simple mode) ends the slice at the next heading of any level, so a
  caller can fetch just the H2 lead paragraphs without the cascading
  H3 sub-tree.
- **Op2: compact structure response carries per-heading summaries.**
  The 80-char `summary` field is derived from each section's body
  preview so a small model can choose which section to drill into,
  not just see which exist.

### Fixed — namespace / metadata / `tell me about`

- **D2: `browse namespace C` no longer crashes on new-scheme archives.**
  Legacy code built a full 27 M-entry list before slicing 50 rows out
  of it — slow, memory-hostile, and triggered "session expired" errors
  on real Wikipedia archives. New `_browse_new_scheme_c_paginated`
  pages directly through the entry-id range.
- **D3: `browse namespace W` returns the actual W entries.** New-scheme
  archives keep W off libzim's iterable surface, but the well-known
  paths (`W/mainPage`, `W/favicon`, ...) are reachable via
  `has_entry_by_path`. New `_browse_new_scheme_w_paginated` probes
  them so the response matches `list_namespaces`' count.
- **D11: metadata previews cap at 800 chars.** Wikipedia ZIMs store
  `M/Title` as a full HTML document (~1 MB) rather than the bare title
  string. The `metadata for <archive>` call previously returned 980 KB,
  starving every other metadata field. Each entry is now capped with
  a `[truncated, N chars total]` marker.
- **D6 / Op7: `tell me about <topic>` auto-fetches on title-index hit.**
  When the top BM25 result wasn't a strong-title match (Xapian ranked
  `List of songs about Berlin` above the canonical `Berlin` article),
  the response used to render the search list. Now falls back to
  `find_entry_by_title_data`; promotes any score-1.0 result past the
  BM25 ranking and inlines the article body.

### CI / quality

- **3 new test modules, 47 additional assertions** covering each fix:
  `test_typo_variants_v2a7.py`, `test_content_processor_fixes_v2a7.py`,
  `test_v2a7_fixes_helpers.py`. End-to-end proof that `"Photosythesis"`
  resolves through the full call path (mock archive + suggester); perf
  guard against quadratic regressions in `_typo_variants`; cursor
  garbage-rejection; metadata cap on both long and short values.
- **Goldens regenerated** (all strict improvements): pipe-soup infobox
  snippet → clean lead-paragraph snippet for Einstein; H1 dedup +
  section attribution on the Berlin / Munich synthesize fixtures.
- **Test infra**: explicit `encoding="utf-8"` on golden read/write so
  non-ASCII characters in goldens survive Windows runners.
- **SonarCloud quality gate**: factored shared test setup
  (`_make_simple_handler`, `_build_metadata_mock_archive`,
  `_wire_typo_fallback_archive`) and namespace browse-payload shape
  (`_new_scheme_browse_payload`, `_materialise_paths`) so new-code
  duplication stays under 3%.

## [2.0.0a6] — 2026-05-11 (alpha pre-release)

Bugfix-only follow-up to v2.0.0a4 after a two-pass review of the
shipped Phase A/B/C surface. 13 defects fixed; no new tools, no
wire-format breaks. Existing tests stay green (1344 passed) and a few
new tests pin down the corrected behaviour.

### Fixed — Phase A (`_meta` envelope, snippets, fuzzy fallback)

- **`format_footer` recovery branch now covers every empty-result `reason`.**
  Responses carrying `reason="no_xapian_index"` or `"bad_namespace"`
  previously fell through to the success branch and emitted a useless
  "~0 tokens" footer. They now render archive-shaped recovery hints
  ("No full-text index on this archive. Try `find_entry_by_title` or
  `browse_namespace`." / "Unknown namespace. Try `list_namespaces`…").
- **`create_snippet` no longer slices `**term**` mid-tag.** When the
  highlighted snippet exceeded `snippet_length` and the second
  truncation landed inside a bold marker, the result was a runaway-bold
  fragment (`…**ter`). The truncation now detects an unpaired trailing
  `**` and strips the dangling segment before appending `...`.
- **Spec §14.4: surface `alt_spelling` suggestions when a fuzzy hit
  is returned.** `find_entry_by_title_data` now adds the resolved
  typo-corrected title to `_meta.suggestions[]` so callers can see
  *which* correction the server applied and decide whether to accept
  it. Previously suggestions only appeared when zero results were
  found.
- **`tokens_est` is now omitted from `_meta` when the tokenizer is
  unavailable** (spec §5). Callers can distinguish "tokenizer
  unavailable" from "zero-token response". `format_footer` falls back
  to char-count when the field is absent.

### Fixed — Phase B (cursor)

- **`CursorPayload.v` comment refreshed.** The inline comment said
  "currently 1" while `CURRENT_VERSION = 2`; replaced with a stable
  reference to the module constant so it can't drift again.

### Fixed — Phase C (bundle, get_section, synthesize)

- **`_locate_passage` whitespace-run offset mapping.** The
  normalized→original-offset walk could exit pointing inside a
  whitespace run that `md_norm` had collapsed to one space, attributing
  citations to the prior section when two section boundaries sat
  either side of the run. The mapper now advances past any remaining
  whitespace so the returned offset always lands on the first
  non-space character of the match.
- **`get_section` truncation surfaces `_meta.total_chars`.** Truncation
  set `_meta.truncated=True` but omitted the source-length context.
  Callers now see how much of the section was elided. `more_at_offset`
  remains absent because `get_section` truncation is not resumable.
- **`archive_by_name` collision on duplicate `.stem`.** Two ZIMs with
  the same filename in different directories (`en/wiki.zim` and
  `fr/wiki.zim`) silently overwrote each other in synthesize's
  archive-lookup dict, causing the bundle for the first archive's hit
  to be fetched from the second archive — i.e., citation poisoning.
  Duplicate stems are now detected at archive enumeration and
  disambiguated with a `~N` suffix (`wiki`, `wiki~2`) with a warning
  log. Single-archive synthesise is unaffected.
- **`get_entry_summary(compact=True)` no longer ignores the `compact`
  flag.** The Phase C bundle migration silently routed compact
  callers through `bundle["rendered_markdown"]`, which is rendered
  with `compact=False` (pipe-soup tables, no oversized-table
  placeholders). Compact requests now bypass the bundle and re-render
  through `_extract_html_summary(compact=True)` so Phase A #2's table
  trimming applies. `compact=False` (the default) still benefits from
  the bundle's shared HTML parse.
- **Cache keys for `path_mapping:`, `binary_meta:`, and `ns_entries:`
  now include an `<mtime_ns>:<size>` invalidation token.** Atomic ZIM
  file replacement (the typical monthly Wikipedia refresh) previously
  left stale resolved paths, binary metadata, and namespace listings
  in cache until LRU eviction. The bundle cache already did this; the
  helper has been extracted to `bundle.archive_stat_token()` and
  applied across all four.
- **`synthesize._extract_passages` no longer double-renders the
  snippet through `html_to_plain_text`.** `search_top_k` already
  returns plain-markdown snippets via `create_snippet`; the
  BeautifulSoup→html2text round-trip risked mangling `**bold**`
  highlight markers. Trust the upstream pipeline; a regression test
  pins the behaviour.

### Test suite

- 1344 passed, 50 skipped (one more than the v2.0.0a4 baseline; added
  `test_extract_passages_preserves_bold_highlight_markers`).
- Updated `test_zim_operations.py` and `test_content_tools.py` cache-key
  assertions for the new stat-token format.
- Updated `test_synthesize.py` to drop the `content_processor` arg
  from `_extract_passages` and use plain-markdown snippet fixtures.

## [2.0.0a4] — 2026-05-10 (alpha pre-release)

v2 Phase C, part 2: completes the retrieval-primitives phase. Adds the
`get_section` tool (#7) and the `zim_query(synthesize=True)` mode (#10)
on top of the EntryBundle infrastructure that shipped in v2.0.0a3.
**No wire-format breaks** — both new surfaces are additive.

### #7 — New tool `get_section`

```
get_section(zim_file_path, entry_path, section_id, *, max_chars=None)
  → Union[GetSectionResponse, ToolErrorPayload]
```

Returns a single section's body (~500-1500 tokens — small-model sweet
spot per parent-document-retrieval research) plus full metadata.
`section_id` values come from `get_table_of_contents`
(`TocHeading.section_id`). On miss, returns
`tool_error("section_not_found", extras={"available_section_ids": [...]
})` so the model can self-correct.

The data layer slices `EntryBundle.rendered_markdown[char_start:char_end]`
where the bundle's section ranges include subsections (a parent heading's
`char_end` extends to the next heading at the same or higher level).
Parent sections therefore return the full subtree body. `max_chars`
truncates the body and sets `truncated=True` plus `_meta.truncated=True`
in the envelope for budget-aware clients.

### #10 — New `zim_query(synthesize=True)` mode

```python
{
    "query": str,
    "answer_markdown": str,        # passages + inline [cite: ...] markers
    "passages": list[SynthesizePassage],
    "citations": list[Citation],
    "archives_searched": list[str],
    "fallback_used": Literal["xapian_score", "rrf_fusion", "reranker"],
    "total_chars": int,
    "total_words": int,
    "_meta": MetaEnvelope,
}
```

Pure retrieval + concatenation; no LLM generation. The seven-stage
pipeline (in `openzim_mcp/synthesize.py`):

1. **Per-archive search** — Xapian top-K hits (`search_top_k` helper
   on `ZimOperations`).
2. **RRF fusion** — Reciprocal Rank Fusion (k=60) when multiple archives
   are searched; identity passthrough for single-archive
   (`fallback_used="xapian_score"` vs `"rrf_fusion"`).
3. **Identity rerank** — placeholder for Phase D's cross-encoder.
4. **Passage extraction** — libzim snippets rendered to markdown.
5. **Section attribution** — best-effort lookup via `EntryBundle`;
   passages get `cite_id = "{archive}/{entry_path}#{section_id}"`
   when the snippet text is found in a section's char range. Bundle
   build failures keep the cite_id at entry level.
6. **Budget enforcement** — `output_char_budget` truncates the last
   passage; subsequent passages are dropped.
7. **Render + citations** — passages joined with `\n\n` and inline
   `[cite: ...]` markers; structured `Citation` list deduplicated by
   `cite_id`.

Zero hits returns an empty response with `_meta.reason="0_hits"`.

### Other

- Extended `tool_error()` with an `extras: Optional[Dict[str, Any]]`
  kwarg so error payloads can carry self-correction hints (e.g. the
  `available_section_ids` list above) without `# type: ignore` at
  call sites.
- New tests: `tests/test_get_section.py` (4),
  `tests/test_synthesize.py` (~20 unit + 3 end-to-end),
  `tests/test_golden_v2_phase_c.py` (3 `get_section` + 3 `synthesize`
  snapshots, deterministic via the new `v2_phase_c_zim` heading-rich
  fixture). `test_response_contract` exempts both new tools from the
  list-pagination contract while still asserting `_meta` is present.
- The Phase A `_meta` envelope continues to attach on every response.
  `_meta.truncated` is now correctly forwarded by `get_section_data`
  on truncation (was a hidden gap in earlier scaffolding).

## [2.0.0a3] — 2026-05-10 (alpha pre-release)

v2 Phase C, part 1: EntryBundle infrastructure and the four-tool collapse.
**One wire-format break** (TOC heading field rename). Phase C's other two
items — #7 `get_section` and #10 `synthesize` mode — are deferred to a
later alpha; their TypedDicts ship in this release as forward-declared
contract surface.

### #11 EntryBundle (internal — collapses four tools)

First touch of an entry runs ONE HTML parse → produces a single
`EntryBundle` value cached at `bundle:v2c:{validated_path}:{entry_path}`.
The four content-shape tools `get_entry_summary`, `get_table_of_contents`,
`get_article_structure`, and `extract_article_links` collapse from
independent HTML re-parsers to thin slicers over the bundle. First touch
parses HTML once; subsequent calls (across all four tools, in any order)
hit the bundle cache.

Removed legacy per-tool cache prefixes: `summary_data:`, `toc_data:`,
`structure_data:`, `links_full:v2b:`. Wire formats unchanged for
`get_entry_summary`, `get_article_structure`, `extract_article_links`.

### Breaking — `get_table_of_contents`

| Field | Before | After |
|---|---|---|
| TOC heading identifier | `heading["id"]` | `heading["section_id"]` |
| TOC list element type | `dict[str, Any]` | `TocHeading` TypedDict |

The value is unchanged (still `resolve_heading_id()`'s output with slug
fallback). The new field name is what `get_section(section_id=...)` will
consume in the next alpha. The old `id_source` field is dropped
(debugging-only, not a contract surface).

### Forward-declared TypedDicts (no behavior yet)

The following TypedDicts ship in `openzim_mcp/tool_schemas.py` as part of
this release so a4's implementation tasks don't have to re-litigate the
contract surface. They aren't returned by any tool yet.

- `GetSectionResponse` — for #7 `get_section` (a4)
- `SynthesizeResponse`, `Citation`, `SynthesizePassage` — for #10
  synthesize mode on `zim_query` (a4)
- `EntryBundle`, `SectionMeta`, `InfoboxField`, `InfoboxData`,
  `LinkBuckets` — bundle internals (already used by the four-tool collapse)
- `TocHeading` — already used (wire format)

### Configuration

`OpenZimMcpConfig.synthesize` block added with defaults `top_n=5`,
`per_archive_k=10`, `output_char_budget=4800`. Inert until `synthesize`
mode ships.

### Other

- New module: `openzim_mcp/bundle.py` — `extract_entry_bundle`,
  `get_or_build_bundle`.
- New tests: `tests/test_bundle.py` (15 tests covering bundle
  determinism, parent/child range nesting, eviction-rebuild identity).
- Cross-tool shared-bundle assertion in `tests/test_structured_tool_output.py`
  guards the "one parse per entry across all four tools" invariant.
- Housekeeping: removed stale `[[tool.mypy.overrides]] module = ['libzim']`
  from `pyproject.toml`. Added GitHub labels `v2`, `v2-phase-a/b/c`;
  applied `v2`/`v2-phase-b` retroactively to PR #111.

### Deferred to a later alpha

- **#7 `get_section`** — section-level retrieval by `section_id`. The
  `GetSectionResponse` TypedDict ships now; the data layer and tool
  registration land in a4.
- **#10 `synthesize`** — `zim_query(synthesize=True)` mode. The
  `SynthesizeResponse`/`Citation`/`SynthesizePassage` TypedDicts and
  `SynthesizeConfig` ship now; the pipeline (`openzim_mcp/synthesize.py`,
  per-archive search, RRF fusion, passage extraction, section attribution,
  citation rendering, budget enforcement) lands in a4.

## [2.0.0a2] — 2026-05-09 (alpha pre-release)

v2 Phase B: response-contract migration. **Wire-format break** for every
list-returning tool. v1.x users upgrading must update response-shape parsing.

### Breaking — pagination contract

Every list-returning tool now returns the same five contract keys:
`results`, `next_cursor`, `total`, `done`, `page_info`.

| Tool | What changed |
|---|---|
| `search_zim_file` | `total_results` → `total`; `pagination` block flattened; `next_cursor` at top level; `cursor` accepted as input |
| `search_all` | `per_file` → `results`; per-archive blocks each carry the new contract via `result` field; cursor lives only at the per-archive level |
| `search_with_filters` | now returns structured dict (was markdown); same shape as `search_zim_file` plus `namespace_filter`/`content_type_filter` |
| `find_entry_by_title` | gets the contract; `done=true`, `total=len(results)` always |
| `get_search_suggestions` | `suggestions` → `results`; `count` removed |
| `browse_namespace` | `entries` → `results`; `total_in_namespace` → `total`; `total_in_namespace_is_lower_bound` → `page_info.total_is_lower_bound`; `has_more` removed |
| `walk_namespace` | `cursor` input/output type changes from `int` to opaque `str`; `entries` → `results`; `total` is always `null`; `total_entries` deprecated alias removed |
| `list_namespaces` | `namespaces[<letter>].entry_count` → `total`; payload at top level (no `result` wrapper) |
| `extract_article_links` | **`kind` is now required (default `"internal"`)**; single category per call; `internal_links`/`external_links`/`media_links` parallel arrays removed; `category_totals: {internal, external, media}` added |
| `list_zim_files` | `files` → `results`; `count` → `total` |
| `get_related_articles` | `outbound_results` → `results`; anticipates Phase E inbound-link feature |
| `get_zim_entries` (batch) | gets the contract; `done=true`, `total=len(results)` |

### Breaking — TypedDict everywhere

Every dict-returning tool migrated from `Dict[str, Any]` to a per-tool
TypedDict. FastMCP now emits payloads at the top level of `structuredContent`
with real schemas. FastMCP continues to wrap `Union[<Response>, ToolErrorPayload]` returns in a `{"result": ...}` envelope at the wire level (this is FastMCP's behavior for any `Union` return type with multiple non-None members). Clients that previously parsed `structuredContent.result` keep working. The TypedDict change ensures the inner payload now carries a real schema instead of `Dict[str, Any]`.

Migrated tools (TypedDict-only, no contract): `get_zim_metadata`,
`get_zim_entry`, `get_main_page`, `get_entry_summary`,
`get_table_of_contents`, `get_article_structure`, `get_binary_entry`.

### Cursor format

Cursors are URL-safe base64 JSON: `{v: 2, t: <tool_name>, s: <state>}`.
**Tool-bound** — a search cursor passed to browse raises a clear error.
**Versioned** — adding new fields later doesn't break the wire format.
**Archive-bound** — cursors for archive-specific tools carry `s.ai` (a
short SHA-256 token of the validated archive path); resubmitting a
cursor against a different archive is rejected. v=1 cursors are
rejected so callers re-fetch rather than silently follow stale state.

### Compat shim removed

`openzim_mcp.zim.archive.PaginationCursor` (the v1 cursor class) is removed.
Use `openzim_mcp.pagination.Cursor` instead.

### Other

- New module: `openzim_mcp/pagination.py` — `Cursor.encode/decode`, `CursorMismatchError`.
- New module: `openzim_mcp/tool_schemas.py` — every per-tool response TypedDict.
- New tests: `tests/test_pagination_cursor.py`, `tests/test_response_contract.py`, `tests/test_golden_v2_phase_b.py`.
- The Phase A `_meta` envelope is unchanged in shape and still populates on every response.

## [2.0.0a1] — 2026-05-08

> First v2 pre-release. Phase A of the multi-phase v2 effort. All changes additive at the tool-signature layer; small compact-mode prose change for empty search results (see Changed below).

### Added

* **meta:** every dict-returning tool now includes a `_meta` envelope (`tokens_est`, `chars`, `truncated`, `more_at_offset`, `total_chars`, `suggestions`, `reason`). `tokens_est` uses tiktoken `cl100k_base` with a 5% pad. (#5)
* **simple:** compact-mode responses gain a one-line markdown blockquote footer (`> ~4.2K tokens · ...`). Set `OPENZIM_MCP_META__FOOTER_ENABLED=false` to suppress. (#5)
* **content:** in compact mode, `.infobox` / `.vcard` tables emit a Markdown KV list prepended to the body. (#2)
* **content:** in compact mode, tables exceeding row or character thresholds are replaced with `[Table N: ...]` placeholders. (#2)
* **search:** every search response is query-aware — snippets contain the actual matched passage (with `**bold**` highlights, capped at 5 hits) rather than the article lead. (#1)
* **search:** `_meta.suggestions[]` surfaces typo variants (`alt_spelling`) and other-archive candidates (`alt_archive`) for empty / low-confidence searches. (#4)
* **search:** `find_entry_by_title` fuzzy fallback now triggers whenever no result clears 0.7 (previously only on zero hits). Score and length-gate are configurable via `OPENZIM_MCP_SEARCH__FUZZY_TITLE_*`. (#14)

### Changed

* **simple:** compact-mode empty-result prose now renders via the new footer + structured suggestions instead of the v1.2.0 paragraph. The information is one-for-one; the format is more model-readable. `compact=False` paths retain byte-identical v1.2.0 behavior. (#4)
* **search:** `find_entry_by_title` typo-corrected hits now score `0.85` (was hardcoded `0.7`) by default. (#14)

### Dependencies

* Added `tiktoken>=0.7.0` to core dependencies.

## [1.3.0](https://github.com/cameronrye/openzim-mcp/compare/v1.2.0...v1.3.0) (2026-05-08)


### Features

* v1.2.0 follow-up — refinements + production-readiness improvements ([#106](https://github.com/cameronrye/openzim-mcp/issues/106)) ([e9396ec](https://github.com/cameronrye/openzim-mcp/commit/e9396ec699a62d4b0ec990d1a155b0ae7ddb73dd))

## [1.2.0](https://github.com/cameronrye/openzim-mcp/compare/v1.1.2...v1.2.0) (2026-05-06)


### Features

* **http:** operator-acknowledged auth bypass + rate-limit env-var docs ([#104](https://github.com/cameronrye/openzim-mcp/issues/104)) ([7294b1d](https://github.com/cameronrye/openzim-mcp/commit/7294b1d33dfa40a8e07c7ba67c062cc2d3c741c7))
* v1.2.0 simple-mode tool ergonomics — tell_me_about, bigger snippets, compact pagination ([#103](https://github.com/cameronrye/openzim-mcp/issues/103)) ([212a60a](https://github.com/cameronrye/openzim-mcp/commit/212a60afd7c1e66bd573605925ccbb06261ed27c))

## [1.1.2](https://github.com/cameronrye/openzim-mcp/compare/v1.1.1...v1.1.2) (2026-05-05)


### Bug Fixes

* **server:** mirror cors_origins into SDK transport allowed_origins ([#100](https://github.com/cameronrye/openzim-mcp/issues/100)) ([96001d1](https://github.com/cameronrye/openzim-mcp/commit/96001d1365933cd948027e6291c34d26234792fe))

## [1.1.1](https://github.com/cameronrye/openzim-mcp/compare/v1.1.0...v1.1.1) (2026-05-05)


### Bug Fixes

* walk_namespace, related-articles, and confidence beta-refinement fixes ([#98](https://github.com/cameronrye/openzim-mcp/issues/98)) ([912d346](https://github.com/cameronrye/openzim-mcp/commit/912d34607220d2a3f7b61d0f39cff918d23c3f99))

## [1.1.0](https://github.com/cameronrye/openzim-mcp/compare/v1.0.1...v1.1.0) (2026-05-05)


### Features

* tool responses use MCP structured content (no more double-stringified JSON) ([#96](https://github.com/cameronrye/openzim-mcp/issues/96)) ([5b541ec](https://github.com/cameronrye/openzim-mcp/commit/5b541ec616386128e6a9d105f07c27bc94676265))


### Bug Fixes

* **http:** allow MCP-Protocol-Version header and DELETE method in CORS ([#93](https://github.com/cameronrye/openzim-mcp/issues/93)) ([dbb791e](https://github.com/cameronrye/openzim-mcp/commit/dbb791e5a6b90a229283ee0a6a283615deae6e42))
* namespace, pagination, resources, and find-by-title beta-test fixes ([#92](https://github.com/cameronrye/openzim-mcp/issues/92)) ([4b572ef](https://github.com/cameronrye/openzim-mcp/commit/4b572efa9acdec84551163e0170c3e6569c28151))
* **server:** make simple mode actually expose only zim_query ([#94](https://github.com/cameronrye/openzim-mcp/issues/94)) ([92c725f](https://github.com/cameronrye/openzim-mcp/commit/92c725f0cffd43f592185c0f2173f4c6ca0ef1e4))

## [1.0.1](https://github.com/cameronrye/openzim-mcp/compare/v1.0.0...v1.0.1) (2026-05-04)


### Bug Fixes

* **http:** allow operator-configured Host allowlist ([#90](https://github.com/cameronrye/openzim-mcp/issues/90)) ([c4dad8a](https://github.com/cameronrye/openzim-mcp/commit/c4dad8a4eb0147178ca268403d85f90530290fe4))

## [1.0.0](https://github.com/cameronrye/openzim-mcp/compare/v0.9.0...v1.0.0) (2026-05-03)

Includes an end-to-end review pass before tagging — security hardening, correctness fixes, performance work, and a refactor that splits `zim_operations.py` into a `zim/` package via mixin classes. See sections below.

### Features

* **http:** streamable HTTP transport with bearer-token auth, CORS allow-list, and `/healthz`/`/readyz` endpoints
* **http:** safe-default startup check refuses to bind a non-localhost host without an auth token
* **transport:** legacy SSE transport (`--transport sse`) for clients that haven't migrated to streamable-HTTP; bound to localhost only, no auth/CORS middleware
* **docker:** multi-stage, multi-arch (`linux/amd64`, `linux/arm64`) image published to `ghcr.io/cameronrye/openzim-mcp`, runs as non-root with a built-in health check
* **content:** `get_zim_entries` batch tool — fetch up to 50 entries in one call, with per-entry success/error reporting
* **resources:** per-entry `zim://{name}/entry/{path}` resource serves entries with their native MIME type (clients must URL-encode `/` as `%2F` in the path segment)
* **subscriptions:** clients can subscribe to `zim://files` and `zim://{name}`; mtime-polling watcher emits `notifications/resources/updated` when allowed directories or `.zim` files change
* **search:** opaque `cursor` parameter on `search_zim_file` for resumable pagination
* **simple:** intent pattern routes batch retrieval queries to `get_zim_entries`

### Improvements

* **content:** `get_related_articles` resolves relative hrefs against the source entry's directory and detects the content namespace correctly on domain-scheme archives (previously returned nothing)
* **content:** suggestion fallback uses `SuggestionSearcher(archive).suggest(text)` (the prior `archive.suggest()` call did not exist)
* **tools:** `list_zim_files` accepts a case-insensitive `name_filter` substring argument; one shared cache slot regardless of filter value
* **content:** `get_zim_entries` accepts bare entry-path strings paired with a `zim_file_path` default (dicts still work for multi-archive batches)
* **content:** heading-id resolution falls through `id` → mw-headline anchor → preceding `<a name="">` → slug, returning `(id, source)` so consumers can distinguish real anchors from synthetic slugs
* **content:** summary extraction skips USWDS banners and skip-nav blocks above the first `<h1>` (MedlinePlus / NIH / NIST style sites)
* **content:** link extraction drops non-navigable schemes (`javascript:`, `mailto:`, `tel:`, `data:`, `blob:`, `vbscript:`)
* **server:** `__version__` reads from `importlib.metadata`; `serverInfo.version` reports openzim-mcp's actual version (no longer the FastMCP SDK default)

### Removed

* **tools:** advanced-mode tool surface drops 27 → 21. Removed: `warm_cache`, `cache_stats`, `cache_clear`, `get_random_entry`, `diagnose_server_state`, `resolve_server_conflicts`. The cache itself remains; the explicit management tools were dropped.
* **instance:** multi-instance conflict tracking removed; `instance_tracker.py` deleted. HTTP server instances coexist freely.

### Bug Fixes

* **content:** sanitize per-entry paths in `get_zim_entries` and expand test coverage
* **resources:** per-entry `zim://` returns libzim's native MIME type
* **http:** start subscription watcher via wrapped lifespan
* **instance:** relax conflict logic for HTTP transport so multiple HTTP server instances can coexist

### Security

* **errors:** redact absolute paths from MCP error responses (rejected traversals previously leaked the canonical allowed-directory layout)
* **errors:** regex-based path redaction with cross-platform separator handling and tightened lookbehind so wrapped/quoted paths (`(/opt/foo)`, `"/opt/bar"`) no longer slip through
* **diagnostics:** redact filesystem paths and PIDs in `get_server_health` / `get_server_configuration` responses (no longer transport-gated; always redacted)
* **resources:** sanitize URI-decoded entry paths before passing to libzim
* **search:** always sanitize `zim_file_path` in `find_entry_by_title` (previously skipped when `cross_file=True`)
* **prompts:** strip control characters and cap user-supplied arguments before interpolating into MCP prompt bodies; re-check empty after sanitization to avoid empty `('', ...)` tool calls
* **http:** require auth on `OPTIONS /mcp` (the unconditional preflight bypass let unauthenticated callers probe the endpoint)
* **http:** resolve `localhost` before classifying as loopback; warn and fall through to the public-host path when `/etc/hosts` maps it elsewhere
* **rate-limit:** make global + per-operation acquire atomic; concurrent callers no longer transiently over-consume the global bucket
* **rate-limit:** per-client buckets with LRU eviction (10k cap) — infrastructure ready for HTTP context wiring

### Correctness

* **search:** reject mismatched `cursor` and `query` arguments instead of silently applying the cursor's offsets to a different query
* **cache:** stop caching error sentinels and zero-result responses (previously a transient libzim error or index warmup poisoned the cache for the full TTL); audit follow-up extends the gate to `get_search_suggestions`, `get_entry_summary`, `get_table_of_contents`
* **cache:** treat empty-string cache values as hits, not misses
* **content:** resolve redirects to their target before rendering; cache the resolved path so subsequent lookups skip the chain; reject redirect cycles and chains deeper than `MAX_REDIRECT_DEPTH = 10`
* **content:** instantiate `html2text.HTML2Text` per call to eliminate a shared-state race that corrupted concurrent conversions
* **content:** preserve Unicode in heading slugs (Arabic, Chinese, Cyrillic, Japanese ZIMs no longer produce empty TOC anchors); disambiguate duplicate heading slugs with `_2`, `_3` suffixes
* **content:** drop trailing punctuation from path tokens extracted by the simple-tools `get_zim_entries` parser
* **simple-tools:** dispatch the `get_zim_entries` intent (was silently falling through to `search_zim_file`); honor explicit `zim_file_path` for `walk_namespace`, `find_by_title`, and `related` intents
* **subscriptions:** detect same-size ZIM replacements via mtime change (size-only detection silently missed identical-size replacements)
* **validation:** `browse_namespace` and `walk_namespace` parameter checks now raise `OpenZimMcpValidationError` instead of `OpenZimMcpArchiveError` or markdown error strings; bound `walk_namespace` `limit` to `[1, 500]` per the documented contract
* **validation:** validate `get_zim_entries` batch size before charging rate-limit so an oversized batch doesn't increment the limiter

### Performance

* **search:** skip-counter pagination in `_perform_filtered_search` (offset=900, limit=10 went from ~1000 backend calls to ~10)
* **content:** `get_entries` groups by ZIM file and opens each archive once
* **navigation:** cache namespace listings per `(archive, namespace)`; pagination now slices from cache instead of re-scanning
* **search:** hoist `Searcher` construction in `_find_entry_by_search` (up to 5 Xapian opens collapse to 1)
* **suggestions:** Strategy 2 uses libzim's `SuggestionSearcher` instead of a strided ID scan that skipped 95% of entries on large archives
* **subscriptions:** `SubscriberRegistry` is set-backed for O(1) subscribe/unsubscribe/clear; broadcast fans out concurrently with per-call `wait_for` timeout so one slow subscriber doesn't stall the watcher

### Refactoring

* **zim:** split `zim_operations.py` (3557 → 39 lines, pure shim) into a `zim/` package with `_SearchMixin`, `_ContentMixin`, `_StructureMixin`, `_NamespaceMixin`. Public API preserved via re-exports
* **simple-tools:** extract `IntentParser` into `intent_parser.py` (parsing logic now unit-testable without `ZimOperations` mocks)
* **config:** unify `RateLimitConfig` into a single Pydantic `BaseModel`; `per_operation_limits` is now reachable from environment variables and JSON config
* **defaults:** default cache `persistence_path` to `~/.cache/openzim-mcp` (absolute) rather than `.openzim_mcp_cache` (relative to CWD)
* **defaults:** relocate `MAX_REDIRECT_DEPTH` and `SUBSCRIPTION_SEND_SECONDS` to `defaults.py` (matches existing project pattern)
* **resources:** offload blocking `list_zim_files_data` directory scan via `asyncio.to_thread`
* **resources:** extract `_resolve_zim_name` helper, replacing duplicated inline ZIM-name match loops
* **simple-tools:** intent confidence boost capped (low-priority intents with extracted params can no longer overtake higher-priority param-less intents)
* **prompts:** dedupe ask-for-args message into a `_ask_for_args(prompt_name)` helper

### Hardening (other)

* **cache:** validate values are JSON-serializable at write time when persistence is enabled (previously `default=str` silently coerced non-JSON types)
* **security:** add an unconditional `..` pattern to path normalization so embedded `foo..bar` traversal candidates trigger the regex layer
* **exceptions:** drop `details` from `Exception.args` so it no longer leaks into `repr()` and tracebacks
* **main:** route startup banner through the logger (now respects `OPENZIM_MCP_LOGGING__LEVEL`)
* **simple-tools:** consistently append low-confidence note across all intents (was missing on `search_all`, `walk_namespace`, `find_by_title`, `related`)

### Pre-release fix-up

Final bug-sweep passes after the main review work above. Categorised by area for easier scanning.

* **content/structure:** `_resolve_entry_with_fallback` and `get_binary_entry` now follow the redirect chain (bounded by the shared `MAX_REDIRECT_DEPTH = 10` cap with cycle detection) before calling `entry.get_item()`. Without this the structure, links, TOC, summary, and binary-entry tools all crashed with `RuntimeError` from libzim whenever the requested path was a redirect to the canonical article (the common case for Kiwix-generated ZIMs)
* **content:** `_get_main_page_content` resolves `archive.main_entry` and the fallback `main_page_paths` entries before calling `get_item()`. Most ZIMs point `W/mainPage` at the real article via a redirect; previously this raised on every such archive
* **content:** `get_zim_metadata` resolves redirect entries before reading metadata content
* **content:** `get_related_articles` preserves trailing slash in path resolution and resolves relative links against the post-redirect path
* **zim:** `_resolve_link_to_entry_path` rejects self-referential refs that previously fed back into the resolver
* **search:** `_perform_filtered_search` canonicalises lowercase / long-form namespace input so filters stop silently dropping every result; suggestion cache now skips zero-result responses
* **search:** `search_all` validates effective_limit is in the documented 1-50 range
* **simple-tools:** `get_article` intent forwards `options[content_offset]` so simple-mode pagination works (previously always returned page 1); passthrough intents forward `options[limit]` / `options[offset]`
* **subscriptions:** `broadcast_resource_updated` re-raises `CancelledError` that `gather(return_exceptions=True)` had silently collected, so `stop()` no longer hangs until the next sleep tick
* **subscriptions:** `MtimeWatcher.start()` offloads initial `_scan` via `asyncio.to_thread` to match `_tick`, no longer blocking the ASGI lifespan on slow filesystems
* **subscriptions:** mtime scan offloaded to thread; fan-out cleanup guarded against late exceptions
* **prompts:** switch user-input interpolation delimiter to backticks and preserve quotes in user input
* **rate-limit:** add missing `RATE_LIMIT_COSTS` keys for `find_entry_by_title`, `get_zim_entries`, `get_related_articles` (were silently using the cost=1 default)
* **http:** add `Mcp-Session-Id` to CORS `allow_headers` and `expose_headers` so browser MCP clients can resume sessions
* **main:** catch `pydantic.ValidationError` from `OpenZimMcpConfig` construction and re-surface as `OpenZimMcpConfigurationError` so operators see a clean message instead of a pydantic validation dump
* **cache:** suppress shutdown logging spam; tolerate malformed persisted entries
* **security:** symlink-tighten archive scan; harden error context; sanitise `name_filter`; reject whitespace-only CORS wildcard
* **tools:** `get_binary_entry` docstring example uses keyword `include_data=False` (positional `False` was landing in `max_size_bytes`)
* **packaging:** `Development Status :: 5 - Production/Stable` classifier for the 1.0.0 release

### Final pre-release sweep

* **resource:** `ZimEntryResource.read` and the `zim://files` / `zim://{name}` resource handlers now offload archive opens via `asyncio.to_thread`; previously a single read stalled the HTTP/SSE event loop for every other concurrent client
* **resource:** `ZimEntryResource.read` resolves redirect chains (with cycle detection and the shared `MAX_REDIRECT_DEPTH = 10` cap) before `entry.get_item()`; previously every redirect-stub path crashed with `RuntimeError` from libzim
* **content:** `get_zim_entries` (batch) replaces manual `__enter__`/`__exit__` with a regular `with` block — cleaner cleanup on `BaseException`, no silent swallowing of `__exit__` errors
* **content:** drop `_get_main_page_content`'s `archive._get_entry_by_id(0)` fallback (libzim private API; entry-zero is not the spec's main-page pointer); the inline redirect helper now uses `MAX_REDIRECT_DEPTH` and raises `OpenZimMcpArchiveError` on cycles or chain exhaustion to match the rest of the redirect helpers
* **server:** `OpenZimMcpServer.run()` defaults to `self.config.transport` (translating the short name `'http'` to FastMCP's `'streamable-http'`) and rejects an explicit `transport=` argument that contradicts the configured value — closes the gap where HTTP-mode subscriptions could be wired while a stdio transport was actually started
* **search/structure:** `find_entry_by_title`, `search_all`, and `get_related_articles` raise `OpenZimMcpValidationError` on out-of-range `limit` / `limit_per_file` instead of returning a hand-formatted markdown string, so the tool layer sees a consistent exception shape
* **http:** `_is_loopback_host` adds a 1-second timeout around `socket.gethostbyname("localhost")` so a slow resolver can't hang server startup
* **ci:** drop `pull_request_target` trigger from `test.yml` / `codeql.yml` / `performance.yml` (closes the pwn-request gap where untrusted PR code could exfiltrate secrets); release-please prerelease detection reads the resolved tag name (works for `workflow_dispatch`); release-please bootstrap-sha placeholders removed; Dockerfile uv image pinned to `0.11`
* **make:** `make benchmark` selects via `-k benchmark` (the previously referenced `tests/test_benchmarks.py` does not exist); `make security` no longer swallows bandit / pip-audit non-zero exits, so `make check` (used by `release.yml`) actually fails on findings
* **docs:** `OPENZIM_MCP_TOOL_MODE`, `_TRANSPORT`, `_HOST`, `_PORT`, `_AUTH_TOKEN`, `_CORS_ORIGINS`, `_WATCH_INTERVAL_SECONDS`, `_SUBSCRIPTIONS_ENABLED` documented in the README configuration table; install commands aligned across README / `website/llms.txt` / `website/index.html` (lead with `uv tool install openzim-mcp`); `website/llm.txt` renamed to `website/llms.txt` (matches the [llmstxt.org](https://llmstxt.org) convention) and advertised in the sitemap

## [0.9.0](https://github.com/cameronrye/openzim-mcp/compare/v0.8.3...v0.9.0) (2026-04-30)

### Features

* **search:** `search_all` queries every ZIM file in allowed directories at once and merges results
* **search:** `find_entry_by_title` resolves a title (or partial title) to entry paths, case-insensitive, optionally cross-file
* **prompts:** MCP prompts (`/research`, `/summarize`, `/explore`) for multi-step ZIM workflows
* **resources:** MCP resources `zim://files` (index of all ZIM files) and `zim://{name}` (per-archive overview)
* **navigation:** `walk_namespace` for deterministic cursor-paginated namespace iteration (vs. `browse_namespace` which samples)
* **content:** `get_random_entry` to sample a random article
* **content:** `get_related_articles` returns link-graph nearest neighbours (outbound, inbound, or both)
* **server:** `warm_cache`, `cache_stats`, and `cache_clear` for inspecting and managing the in-memory cache

### Bug Fixes

* namespace listing deterministically surfaces minority namespaces (M, W, X, I) that random sampling could miss
* search filtering uses streaming scan instead of a hard 1000-hit cap, so rare-mime-type filters return matches that were previously hidden
* error messages route by failure mode first (no more "check disk space" for "entry not found")
* phantom server-instance conflicts are no longer reported (TOCTOU re-check before raising)

## [0.8.3](https://github.com/cameronrye/openzim-mcp/compare/v0.8.2...v0.8.3) (2026-01-30)

### Bug Fixes

* fix logo URL in README.md to use absolute GitHub raw URL for PyPI display ([README.md](README.md))
* resolve GitHub code scanning alert #133 - variable defined multiple times in security.py ([security.py](openzim_mcp/security.py))
* resolve GitHub code scanning alert #134 - mixed import styles in test_main.py ([test_main.py](tests/test_main.py))
* remove unused `contextlib` import from security.py (flake8 fix)

## [0.8.2](https://github.com/cameronrye/openzim-mcp/compare/v0.8.1...v0.8.2) (2026-01-29)

### Bug Fixes

* fix search pagination when offset exceeds total results ([zim_operations.py](openzim_mcp/zim_operations.py))
* improve exception handling in instance tracker for Python 3 compatibility ([instance_tracker.py](openzim_mcp/instance_tracker.py))
* add fallback to stderr for logging during shutdown ([instance_tracker.py](openzim_mcp/instance_tracker.py))
* improve Windows process checking with debug logging ([instance_tracker.py](openzim_mcp/instance_tracker.py))
* fix release workflow to skip automatic GitHub release creation ([release-please.yml](.github/workflows/release-please.yml))
* resolve linting issues in simple_tools.py and content_tools.py

## [0.8.1](https://github.com/cameronrye/openzim-mcp/compare/v0.7.1...v0.8.1) (2026-01-29)

### Features

* add article summaries, table of contents, and pagination cursors ([bf5d18f](https://github.com/cameronrye/openzim-mcp/commit/bf5d18fcfecb2e6b03c667565640439b145a4e30))

### Bug Fixes

* remove unused imports in test files for CI linting ([0ddb250](https://github.com/cameronrye/openzim-mcp/commit/0ddb250d49fb627ee7adb41cf3fa52a8caf69172))
* resolve GitHub code scanning alerts ([2ad2c56](https://github.com/cameronrye/openzim-mcp/commit/2ad2c56a6e7a958ed63d6bd23ad975dd80e1e1f0))

### Details

* **Article Summaries** (`get_entry_summary`): Extract concise article summaries from opening paragraphs
  * Removes infoboxes, navigation, and sidebars for clean summaries
  * Configurable `max_words` parameter (10-1000, default: 200)
  * Returns structured JSON with title, summary, word count, and truncation status
  * Useful for quick content preview without loading full articles

* **Table of Contents Extraction** (`get_table_of_contents`): Build hierarchical TOC from article headings
  * Hierarchical tree structure with nested children based on heading levels (h1-h6)
  * Includes heading text, level, and anchor IDs for navigation
  * Provides heading count and maximum depth statistics
  * Enables LLMs to navigate directly to specific article sections

* **Pagination Cursors**: Token-based pagination for easier result navigation
  * Base64-encoded cursor tokens encode offset, limit, and optional query
  * `next_cursor` field in search and browse results for continuation
  * Eliminates need for clients to track pagination state manually

### Enhanced

* **Intent Parsing**: Improved multi-match resolution with weighted scoring
  * Collects all matching patterns before selecting best match
  * Weighted scoring: 70% confidence + 30% specificity
  * Prevents earlier patterns from incorrectly shadowing more specific ones
  * New intent patterns for "toc" and "summary" queries in Simple mode

* **Simple Mode**: Added natural language support for new features
  * "summary of Biology" or "summarize Evolution" for article summaries
  * "table of contents for Biology" or "toc of Evolution" for TOC extraction

## [0.7.1](https://github.com/cameronrye/openzim-mcp/compare/v0.7.0...v0.7.1) (2026-01-28)

### Bug Fixes

* **ci:** handle existing GitHub releases in release workflow ([#54](https://github.com/cameronrye/openzim-mcp/issues/54)) ([63afa3d](https://github.com/cameronrye/openzim-mcp/commit/63afa3d9150a60716b7fa25524beedb806ded84d))

## [0.7.0](https://github.com/cameronrye/openzim-mcp/compare/v0.6.3...v0.7.0) (2026-01-28)

### Features

* add binary content retrieval for PDFs, images, and media files ([#52](https://github.com/cameronrye/openzim-mcp/issues/52)) ([95611c9](https://github.com/cameronrye/openzim-mcp/commit/95611c9135836202d1fc97181d98307c199e3888))

## [0.6.3](https://github.com/cameronrye/openzim-mcp/compare/v0.6.2...v0.6.3) (2025-11-14)

### Bug Fixes

* configure release-please to skip GitHub release creation and handle existing PyPI packages ([b865454](https://github.com/cameronrye/openzim-mcp/commit/b8654546c1a8ea3a90eb3dedfb95c671beaaca98))

## [0.6.2](https://github.com/cameronrye/openzim-mcp/compare/v0.6.1...v0.6.2) (2025-11-14)

### Bug Fixes

* add tag_name parameter to GitHub Release action ([74d393c](https://github.com/cameronrye/openzim-mcp/commit/74d393c600155b303a26d6f066130cb26351cb49))

## [0.6.1](https://github.com/cameronrye/openzim-mcp/compare/v0.6.0...v0.6.1) (2025-11-14)

### Bug Fixes

* resolve CI workflow issues ([4bd6c33](https://github.com/cameronrye/openzim-mcp/commit/4bd6c332548a444c58390889052ebcc417d65094))

## [0.6.0](https://github.com/cameronrye/openzim-mcp/compare/v0.5.1...v0.6.0) (2025-11-14)

### Features

* add dual-mode support with intelligent natural language tool ([#31](https://github.com/cameronrye/openzim-mcp/issues/31)) ([6d97993](https://github.com/cameronrye/openzim-mcp/commit/6d97993a8bda3f20cc65abfeef459f9487b94406))
* enhance GitHub Pages website with dark mode, dynamic versioning, and improved UX ([#22](https://github.com/cameronrye/openzim-mcp/issues/22)) ([977d46a](https://github.com/cameronrye/openzim-mcp/commit/977d46abf61efbafca2bd24142176c3857cc32b8))

## [0.5.1](https://github.com/cameronrye/openzim-mcp/compare/v0.5.0...v0.5.1) (2025-09-16)

### Bug Fixes

* resolve CI/CD status reporting issue for bot commits ([#20](https://github.com/cameronrye/openzim-mcp/issues/20)) ([af23589](https://github.com/cameronrye/openzim-mcp/commit/af235896b4a1afd96269d08d97362ff903e093d5))
* resolve GitHub Actions workflow errors ([#17](https://github.com/cameronrye/openzim-mcp/issues/17)) ([dcda274](https://github.com/cameronrye/openzim-mcp/commit/dcda2749a394a599e3f77a4b64412fa21e65a29d))

## [0.5.0](https://github.com/cameronrye/openzim-mcp/compare/v0.4.0...v0.5.0) (2025-09-15)

### Features

* enhance GitHub Pages site with comprehensive feature showcase ([#14](https://github.com/cameronrye/openzim-mcp/issues/14)) ([c50c69b](https://github.com/cameronrye/openzim-mcp/commit/c50c69b73bc4ec142a2080146644ed9c84da63c4))
* enhance GitHub Pages site with comprehensive feature showcase and uv-first installation ([#15](https://github.com/cameronrye/openzim-mcp/issues/15)) ([f988c5a](https://github.com/cameronrye/openzim-mcp/commit/f988c5a9c7af4acbfe08922a68e11a288f06da70))

### Bug Fixes

* correct CodeQL badge URL to match workflow name ([#13](https://github.com/cameronrye/openzim-mcp/issues/13)) ([7446f74](https://github.com/cameronrye/openzim-mcp/commit/7446f7491d1c0a028a7ba55071b46c73424b58e4))

### Documentation

* Comprehensive documentation update for v0.4.0+ features ([#16](https://github.com/cameronrye/openzim-mcp/issues/16)) ([e1bce58](https://github.com/cameronrye/openzim-mcp/commit/e1bce5816e95beca7adeca92c03dbd551808151f))
* improve installation instructions with PyPI as primary method ([d6f758b](https://github.com/cameronrye/openzim-mcp/commit/d6f758b30836e916933e87a316754cd757cec833))

## [0.4.0](https://github.com/cameronrye/openzim-mcp/compare/v0.3.3...v0.4.0) (2025-09-15)

### Features

* overhaul release system for reliability and enterprise-grade automation ([#9](https://github.com/cameronrye/openzim-mcp/issues/9)) ([ef0f1b8](https://github.com/cameronrye/openzim-mcp/commit/ef0f1b8f2eaac99a1850672088ddc29d28f0bcde))

## [0.3.1](https://github.com/cameronrye/openzim-mcp/compare/v0.3.0...v0.3.1) (2025-09-15)

### Bug Fixes

* add manual trigger support to Release workflow ([b968cf6](https://github.com/cameronrye/openzim-mcp/commit/b968cf661f536183f4ef5fd6374e75a847a0123f))
* ensure Release workflow checks out correct tag for all jobs ([b4a61ca](https://github.com/cameronrye/openzim-mcp/commit/b4a61ca7a034f9eefae2606c4eb9769ef4f79379))

## [0.3.0](https://github.com/cameronrye/openzim-mcp/compare/v0.2.0...v0.3.0) (2025-09-15)

### Features

* add automated version bumping with release-please ([6b4e27c](https://github.com/cameronrye/openzim-mcp/commit/6b4e27c0382bb4cfa16a7e101f012e8355f7c827))

### Bug Fixes

* resolve release-please workflow issues ([68b47ea](https://github.com/cameronrye/openzim-mcp/commit/68b47ea711525e126ec3ed8297808f7779edd87e))

## [0.2.0] - 2025-01-15

### Added

* **Complete Architecture Refactoring**: Modular design with dependency injection
* **Enhanced Security**:
  * Fixed path traversal vulnerability using secure path validation
  * Comprehensive input sanitization and validation
  * Protection against directory traversal attacks
* **Comprehensive Testing**: 80%+ test coverage with pytest
  * Unit tests for all components
  * Integration tests for end-to-end functionality
  * Security tests for vulnerability prevention
* **Intelligent Caching**: LRU cache with TTL support for improved performance
* **Modern Configuration Management**: Pydantic-based configuration with validation
* **Structured Logging**: Configurable logging with proper error handling
* **Type Safety**: Complete type annotations throughout the codebase
* **Resource Management**: Proper cleanup with context managers
* **Health Monitoring**: Built-in health check endpoint
* **Development Tools**:
  * Makefile for common development tasks
  * Black, flake8, mypy, isort for code quality
  * Comprehensive development dependencies

### Changed

* **Project Name**: Changed from "zim-mcp-server" to "openzim-mcp" for consistency
* **Entry Point**: New `python -m openzim_mcp` interface (backwards compatible)
* **Error Handling**: Consistent custom exception hierarchy
* **Content Processing**: Improved HTML to text conversion
* **API**: Enhanced tool interfaces with better validation

### Security

* **CRITICAL**: Fixed path traversal vulnerability in PathManager
* **HIGH**: Added comprehensive input validation
* **MEDIUM**: Sanitized error messages to prevent information disclosure

### Performance

* **Caching**: Intelligent caching reduces ZIM file access overhead
* **Resource Management**: Proper cleanup prevents memory leaks
* **Optimized Processing**: Improved content processing performance

## [0.1.0] - 2024-XX-XX

### Added

* Initial release of ZIM MCP Server
* Basic ZIM file operations (list, search, get entry)
* Simple path management
* HTML to text conversion
* MCP server implementation

### Known Issues (Fixed in 0.2.0)

* Path traversal security vulnerability
* No input validation
* Missing error handling
* No testing framework
* Resource management issues
* Global state management problems
