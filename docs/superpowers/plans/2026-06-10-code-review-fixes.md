# Code Review 2026-06-10 — Remediation Plan

> **For agentic workers:** Implement task-by-task with TDD. Each finding gets a failing test (where testable), a minimal fix, a green test, and a commit. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 56 confirmed findings plus the verified-new issues from `CODE_REVIEW_2026-06-10.md`, on a single branch (`fix/code-review-2026-06-10`) with grouped commits and one PR.

**Architecture:** Work is grouped into 12 phases by subsystem so overlapping-file edits stay coherent and the suite stays green throughout. Opportunities and the 50 unverified observations are out of scope.

**Tech Stack:** Python 3.9+, uv, pytest (coverage in addopts), flake8/isort/black, mypy, FastMCP/mcp 1.27.0, libzim, BeautifulSoup, Xapian.

**Commands:** test `uv run pytest -q --no-cov`; lint `uv run flake8 openzim_mcp tests && uv run isort --check-only openzim_mcp tests && uv run black --check openzim_mcp tests`; types `uv run mypy openzim_mcp`; format `uv run black openzim_mcp tests && uv run isort openzim_mcp tests`.

**Verification rule:** Keep the full suite green after every phase. Add a regression test for every behavioral fix. Run `make format` before each commit.

---

## Phase 1 — CI / packaging / security workflows

- [ ] **H1** `.github/workflows/test.yml:211` — bandit `|| echo '{}' > report` clobbers real findings. Fix: use `bandit -c pyproject.toml -r openzim_mcp --exit-zero -f json -o bandit-report.json` (and SARIF) so the real report is kept and the project config (B101 skip) applies; decide the gating step explicitly. Verify: `bandit -c pyproject.toml -r openzim_mcp -f json` produces a non-empty results array that survives.
- [ ] **M1** `.github/workflows/release.yml:314` — swallowed asset-upload failure then publishes. Fix: drop `|| echo`, track a failure flag, exit nonzero before the publish step; optionally verify asset count via `gh release view --json assets`.
- [ ] **M34** `scripts/download_test_data.py:140,234` — partial download treated as complete. Fix: download to `dest_path.with_suffix('.part')` then `os.replace()` on success; validate size. Test: simulate a mid-stream failure leaves no final file.
- [ ] **L1** `.github/workflows/deploy-website.yml:84,129` — update-benchmark-integration job pushes to gh-pages with `contents: read`. Fix: delete the job (benchmark gh-pages is not maintained; `performance.yml` sets `auto-push: false`).
- [ ] **NEW (med)** `.github/workflows/performance.yml` — structural no-op: zero pytest-benchmark tests exist; workflow fabricates placeholder results. Fix: delete the workflow (and the `benchmark`/`test-integration` Makefile targets are addressed in devx opportunities — out of scope here, but remove the dead workflow). Also remove the gh-pages benchmark-integration coupling.
- [ ] **NEW (low)** `sonar-project.properties:50-57` — stale blanket suppression of `githubactions:S7637` (SHA-pin rule) now that `2d23e20` completed SHA pinning. Fix: remove the suppression block so future unpinned actions are flagged.

## Phase 2 — HTTP transport / auth security

- [ ] **H4** `openzim_mcp/config.py:365`, `openzim_mcp/http_app.py:119,206` — empty `OPENZIM_MCP_AUTH_TOKEN` disables auth. Fix: add a `field_validator` on `auth_token` rejecting blank/whitespace secret values at config load. Test: `Config(auth_token="")` raises; `Config(auth_token="  ")` raises.
- [ ] **H10** `openzim_mcp/server.py:139,146` — non-loopback HTTP without `ALLOWED_HOSTS` ⇒ 421 on every request. Fix: always build `TransportSecuritySettings` for `transport=="http"`, including loopback entries plus `config.host` (+ `:*`) when non-loopback; warn at startup if effective allowlist is loopback-only on a non-loopback bind. Test: with host=0.0.0.0 and empty allowed_hosts, settings include the bind host.
- [ ] **M6** `openzim_mcp/http_app.py:151` — readyz does blocking `os.path.isdir`/`os.access` on the event loop. Fix: wrap dir checks in `await asyncio.to_thread(...)` (optionally `asyncio.wait_for`). Test: readyz handler offloads to a thread.
- [ ] **M12** `openzim_mcp/server.py:103`, `rate_limiter.py:280` — rate limiter constructed but never enforced. Fix: call `check_rate_limit(operation=...)` in a shared seam in `tools/_common.py` (or each handler), returning a structured rate-limit error on rejection. Test: exceeding the configured limit returns a rate-limit error.
- [ ] **NEW (low)** docs — `OPENZIM_MCP_INSECURE_DISABLE_AUTH` is an undocumented auth-disable flag. Fix: document it in SECURITY.md / security-best-practices with a strong warning. (Doc-only.)

## Phase 3 — intent_parser.py extraction / routing bugs

- [ ] **H5** `intent_parser.py:170` — `\s+(?:in|within)` with no `\b` truncates queries at any `in*` word. Fix: `...\s+(?:in|within)\b(?=\s+(?:namespace|type)\b)`. Test: `search for history of the internet in namespace A` ⇒ query `history of the internet`.
- [ ] **H6** `intent_parser.py:291-297` — last-keyword anchor truncates titles with of/for/in/from/to. Fix: prefer `article|entry|page` anchors; only anchor a preposition immediately after the intent verb. Test: `get article History of France` ⇒ entry_path `History of France`; `Lord of the Rings` preserved.
- [ ] **H7** `intent_parser.py:337` — `_extract_binary` captures connector `from` as path. Fix: require connector after anchor `(?:content|data|entry)\s+(?:from|of|for)\s+(['"]?)([A-Za-z0-9_/.-]+)\1`, and guard connector words from being returned. Test: `get binary content from I/image.png` ⇒ entry_path `I/image.png`.
- [ ] **H8** `intent_parser.py:738-739` — `info about X`/`details of X` always routes to metadata, shadowing tell_me_about. Fix: restrict metadata patterns to file-shaped targets (require `.zim` token or `this file/archive`). Test: `info about Python` ⇒ tell_me_about; `metadata for foo.zim` ⇒ metadata.
- [ ] **M7** `intent_parser.py:610` — `[A-Za-z]/[\w...]` captures `d/or` from `and/or`. Fix: `(?<![A-Za-z0-9])[A-Za-z]/[\w\-./%]+`. Test: `get entries A/Foo and/or B/Bar` ⇒ `['A/Foo','B/Bar']`.
- [ ] **M8** `intent_parser.py:64,270-271,650` — apostrophes treated as quote delimiters break possessive titles. Fix: use paired-quote backreference matching / exclude apostrophes from opening-quote class. Test: `section Earth's atmosphere of Earth` extracts section `Earth's atmosphere`; `links in Murphy's law` not parsed as quoted span.
- [ ] **M9** `intent_parser.py:803` — bare `complete` verb hijacks `complete X` into suggestions. Fix: drop `complete` from the alternation or require disambiguating object. Test: `get article complete works of Shakespeare` ⇒ get_article.
- [ ] **M10** `intent_parser.py:1199,1211,1216` — Rule-4 decompose runs before politeness/param strips, baking junk into entity hint. Fix: run `_strip_param_leaks` + `_strip_trailing_politeness` before `_apply_tier1_rewrites`. Test: `population of berlin please` ⇒ hint entity `berlin`; `population of berlin limit=5` ⇒ hint entity `berlin`.

## Phase 4 — chain detection + non-ASCII title matching

- [ ] **H2** `chain_detection.py:55,305` — middle-initial names (`Franklin D. Roosevelt`) falsely rejected as chains. Fix: before promoting on the period connector, skip when the last token of `left_bare` is a 1-2 char initial/abbreviation (D, F, St, Mt, Jr, Dr). Test: `tell me about Franklin D. Roosevelt`, `John F. Kennedy`, `Mount St. Helens`, `the St. Louis Cardinals` are NOT chain-rejected.
- [ ] **M24** `title_promotion.py:52,62` — `is_strong_title_match` ASCII-only tokenizer false-matches non-Latin topics. Fix: Unicode-aware tokenizer (`[^\W_]+`) and/or apply 3-char-sum guard before token equality. Test: `is_strong_title_match('Łódź','D','D')` is False; `('café','CAF','CAF')` is False.
- [ ] **M25** `title_promotion.py:965,1011` — non-ASCII possessor tokens never pass possessive gates. Fix: tokenize candidate path with a Unicode-aware tokenizer consistent with `extract_possessor_tokens`. Test: `accept_possessive_promotion({'path':"Ampère's_circuital_law",...},"Ampère's circuital law")` is True.

## Phase 5 — content_processor.py

- [ ] **H3** `content_processor.py:552-570` — `_build_sections` walks both div and p, duplicating/misattributing content. Fix: skip elements whose ancestor is also collected (`if element.find_parent(["p","div"]): continue`) so only outermost blocks count. Test: nested `<div><div><p>...</p></div></div>` yields correct word_count (7, not 21).
- [ ] **M2** `content_processor.py:862` — `extract_infobox` decomposes node even when no rows extracted, deleting content. Fix: `if rows: node.decompose()` else continue; restrict bare `.infobox`/`.vcard` to `table.infobox`/`table.vcard`. Test: a div-based/label-`td` infobox with zero KV rows is NOT removed.
- [ ] **M3** `content_processor.py:1063,1083` — snippet truncation splits markdown links, defeating highlight skip-protection. Fix: after truncation, detect an unterminated trailing link and back up to before `[` (mirror the `**` repair). Test: truncating mid-link yields no dangling `[text](url` and no bolding inside link.

## Phase 6 — synthesize.py / rerank.py

- [ ] **H9** `rerank.py:217,218` — `_maybe_rerank_search_all` redistributes BEFORE checking `rerank_score`, zeroing later archives on passthrough. Fix: check `reranked_tagged and 'rerank_score' in reranked_tagged[0]` before calling `_redistribute_reranked_hits`; on passthrough return `per_file` unmodified (mirror synthesize guard). Test: short query (<4 tokens) over 3 archives leaves all archives' hits intact.
- [ ] **M17** `synthesize.py:464,509` — affinity boost (`*1.5`) inverts for negative cross-encoder scores. Fix: make the boost monotonic regardless of sign (divide when score<0, or rank-bonus, or sigmoid-normalize rerank scores before propagating). Test: a matching passage with negative score is not demoted below non-matching.
- [ ] **M18** `synthesize.py:1199-1209` — possessive tail-rescue can prepend a duplicate already in top_hits. Fix: check `(archive_name, str(rescued['path'])) in existing_paths` and reorder to front instead of prepending a dup. Test: when canonical already present, no duplicate passage.
- [ ] **M19** `synthesize.py:1315` — `_drop_low_relevance_tail` filters on the `1/rank` proxy, unconditionally dropping rank-5. Fix: only apply when a distinct real relevance key exists; stop reading fabricated `score` as relevance. Test: rank-5 hit survives in default single-archive synthesize.

## Phase 7 — simple_tools.py dispatch / search / query

- [ ] **H11** `simple_tools.py:410,425-426` — search-tail overwrite reverts query-rewrite/param-strip/quote-strip. Fix: use the recomputed tail only for the empty-tail guard; otherwise keep extractor's `search_q`. Test: `search for photosythesis` ⇒ backend gets `photosynthesis`; `search for biology limit=10` ⇒ `biology`; quotes stripped.
- [ ] **H12** `simple_tools.py:2165-2247`, `cache.py:311`, `zim/search.py:615` — cached search payload mutated in place (cross-surface poisoning + race). Fix: `_splice_title_match_into_search` operates on a copied payload (`{**payload, "results":[...], "page_info":{...}}`). Test: after a compact zim_query splice, a subsequent cache hit returns the original BM25 payload unmutated.
- [ ] **M14** `tools/zim_query.py:99` — always injects `limit=3`, making per-intent defaults dead. Fix: only set `options["limit"]` when the caller passed one (mirror offset). Test: `links in X` returns the per-intent default (25), not 3, when limit unset. Update `zim_query_description.md` 'ignored' text.
- [ ] **M15** `simple_tools.py:3201-3218` — find_by_title upfront namespace redirect blocks all slash titles (Rule-1 lowercases everything). Fix: consult the index first; only redirect on zero hits (D7 branch becomes primary); restrict upfront to uppercase-first if kept. Test: `find article titled a/b testing` consults `find_entry_by_title_data`.

## Phase 8 — timeout_utils.py pool redesign

The four findings (M20/M21/M22/M23) are one cohesive redesign of `timeout_utils.py`.

- [ ] **M20/M23** `timeout_utils.py:36` — single 16-worker pool shared by 1s regex guards and 30s libzim opens ⇒ head-of-line blocking / spurious `RegexTimeoutError`. Fix: separate executors (a small dedicated pool for libzim archive opens vs. regex guards), or run pre-vetted bounded regexes inline. Test: saturating the archive pool does not raise RegexTimeoutError on independent regex calls.
- [ ] **M22** `timeout_utils.py:91-92` — timed-out futures never cancelled; queued work still executes. Fix: call `future.cancel()` in the TimeoutError handler before raising. Test: a still-pending submission is cancelled on timeout.
- [ ] **M21** `timeout_utils.py:54` — pool never shut down; hung libzim worker blocks interpreter exit. Fix: daemon worker threads (ThreadPoolExecutor with daemon threads) and/or `shutdown(wait=False, cancel_futures=True)` from a server shutdown hook. Test: workers are daemon threads.

## Phase 9 — tools API/UX + error messages

- [ ] **H13** `tools/zim_get.py:119` — batch branch silently ignores `view`. Fix: reject `entry_paths` + `view != "full"` in `_validate_branch_combination` with `invalid_path_combination`; fix description. Test: batch + `view="summary"` raises a structured error.
- [ ] **H14** `tools/zim_search.py:75` — `cursor` accepted/documented but never used. Fix: decode via `_common.decode_cursor_state` and project `o`/`ai`/`q` into the data call (as zim_browse/zim_links do); or remove the param + stop emitting `next_cursor`. Test: passing a `next_cursor` advances the page.
- [ ] **M4** `error_messages.py:38,50,60,94,120,127` — templates reference removed tools (`list_zim_files`, `get_server_health`, `get_server_configuration`). Fix: update to `zim_health(...)` / `zim_query("list available ZIM files")`. Test: rendered error text contains no removed tool name.
- [ ] **M5** `error_messages.py:204` — security violations misrouted to the Permission template. Fix: check the exception-type mapping for `OpenZimMcpSecurityError` before the `access denied` substring heuristic. Test: an `OpenZimMcpSecurityError("Access denied - Path is outside...")` renders the security template.
- [ ] **M26** `tools/zim_get.py:69` — `compact_budget` accepted/documented but never used in advanced mode. Fix: wire it into the compact rendering path (as zim_query does), or document inert. Test: `compact_budget="tiny"` caps output.
- [ ] **M27** `tools/zim_get_section_description.md:17-30` — doc says `compact` is a no-op but it is wired. Fix: correct the description to match wired behavior; keep no-op caveat only for `compact_budget`.
- [ ] **M28** `tools/zim_search.py:255,135-137,217-219` — `offset` silently dropped in title/suggest/cross-file modes. Fix: reject non-zero `offset` in modes that can't honor it (structured `invalid_combination`); update doc. Test: title mode + offset>0 raises.
- [ ] **M29** `tools/zim_search_description.md:49-53` — RESPONSE doc misstates cross_file/suggest shapes. Fix: document per-mode shapes (cross_file rows nest hits under `results[].result.results`; suggest items carry `text`/`path`/`type`).
- [ ] **L5** `tool_schemas.py:4-7` — structuredContent contract docstring is wrong (`-> Any` tools emit none; zim_query wraps in `{"result":...}`). Fix: at minimum correct the contract docstring; optionally annotate tools with precise return types.
- [ ] **L6** `tools/_common.py:45` — same tool returns two incompatible error shapes (dict vs markdown string). Fix: have `tool_error_response` wrap the enhanced message in a `ToolErrorPayload` envelope. Test: data-layer failure returns `error: true` dict.
- [ ] **NEW (med)** `tools/resource_tools.py:69-71,194-200,361` — resource notices direct clients to removed tools (`get_zim_entry`, `get_binary_entry`, `max_size_bytes`). Fix: update to `zim_get(content_offset=...)` / `zim_get(binary=True)`. Test: resource notice text references only registered tools.

## Phase 10 — performance hot path

- [ ] **H15** `zim/search.py:2913,3023` — `find_entry_by_title_data` uncached, re-opens archive per probe, triggers ~10k-lookup typo sweeps. Fix: memoize results per (archive stat token, title) in the response cache; restrict the typo sweep to single-token probes. Test: repeated identical probe hits cache; multi-word window skips typo sweep.
- [ ] **M30** `topic_preprocessing.py:162-181` — Pass 3 repeats Pass 1's identical backend lookups. Fix: probe each tail once at permissive 0.8, cache per-tail results, apply strict 1.0 gate over cached results, fall back to 0.8 without re-querying. Test: backend called once per tail.
- [ ] **M31** `zim/content.py:215-253` — snippet re-renders full article; synthesize re-parses same HTML twice. Fix: source snippets from cached `EntryBundle.rendered_markdown` or cache compact render per (path, entry_path, stat_token). Test: two snippet calls for same entry parse once.
- [ ] **M32** `zim/search.py:501` — archive-type preset re-derived from full metadata extraction per uncached search. Fix: cache resolved `(preset, applied_type)` keyed by validated_path + archive_stat_token. Test: preset resolution runs once per archive.
- [ ] **M33** `zim/search.py:1104-1111` — canonical-splice filtered search runs the Xapian scan + snippet render twice when canonical is top hit. Fix: render the already-computed structured payload via `_format_filtered_response` instead of delegating to `search_with_filters`. Test: only one scan when canonical is top hit.
- [ ] **L4** `simple_tools.py:241-289` — Tier-1 rewrite probes run twice per request, unmemoized. Fix: memoize probe results per token for the request (dict/lru_cache on the closure). Test: probe backend called once per token across the two rewrite passes.

## Phase 11 — test coverage gaps

- [ ] **M11** `security.py:76,87,197-198,206,250,418` — untested security branches. Add tests: `%2e%2e` and double-encoded paths raise; >4096-char path raises 'Path too long'; symlink-swap TOCTOU raises 'resolves outside'; `sanitize_input('\x00\x01')` raises empty-input; >1024-char context truncated with '...'.
- [ ] **M13** `server_state.py:45-296` — 18% covered. Add direct unit tests for `_build_health_report`/`_build_configuration_report` over a tmp_path config, including missing/permission-denied dir asserting redacted path + 'warning' status.
- [ ] **L2** `async_operations.py` — ~25 `_data` wrappers never executed. Add a parametrized forwarding test over the wrapper list against `MagicMock(spec=ZimOperations)`.
- [ ] **L3** `http_app.py:379,393-398` — subscription-watcher lifespan uncovered. Add an in-process test building the streamable-HTTP app with a stub watcher, running lifespan via Starlette TestClient, asserting start/stop called.
- [ ] **L7** `tests/test_metadata_tools.py:37` — vacuous mock-tests-the-mock tests. Rewrite to call the registered handlers with ops mocked one level down; delete pure-AsyncMock-roundtrip tests.

## Phase 12 — concurrency + misc docstrings

- [ ] **M16** `subscriptions.py:92` — `SubscriberRegistry` retains dead sessions indefinitely. Fix: hook session teardown to call `clear_session`, or periodically sweep against live sessions / weak refs. Test: a torn-down session is removed from `_by_uri`.
- [ ] **NEW (low)** `linkgraph/builder.py:196-198` — docstring claims "whole graph is never held in memory" but nodes are interned in memory. Fix: correct the docstring to state only edges stream; nodes are held. (Doc-only.)

---

## Self-review coverage map

Highs (15): H1·P1 H2·P4 H3·P5 H4·P2 H5·P3 H6·P3 H7·P3 H8·P3 H9·P6 H10·P2 H11·P7 H12·P7 H13·P9 H14·P9 H15·P10.
Mediums (34): M1·P1 M2·P5 M3·P5 M4·P9 M5·P9 M6·P2 M7·P3 M8·P3 M9·P3 M10·P3 M11·P11 M12·P2 M13·P11 M14·P7 M15·P7 M16·P12 M17·P6 M18·P6 M19·P6 M20·P8 M21·P8 M22·P8 M23·P8 M24·P4 M25·P4 M26·P9 M27·P9 M28·P9 M29·P9 M30·P10 M31·P10 M32·P10 M33·P10 M34·P1.
Lows (7): L1·P1 L2·P11 L3·P11 L4·P10 L5·P9 L6·P9 L7·P11.
Verified-new: resource_tools·P9, performance.yml·P1, sonar suppression·P1, INSECURE_DISABLE_AUTH docs·P2, linkgraph memory claim·P12.
