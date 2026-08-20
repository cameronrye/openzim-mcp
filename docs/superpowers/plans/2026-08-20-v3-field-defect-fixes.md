# v3.0.0 Field-Defect Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 65 verified defects from the 2026-08-19 v3.0.0 real-world test sweep (11 major / 38 minor / 16 cosmetic).

**Architecture:** Eight parallel workstreams partitioned by file ownership (no two workstreams own the same module), each executed TDD defect-by-defect on its own branch in an isolated worktree; branches merge sequentially into `fix/v3-field-defects`, then every original repro is re-run against the merged build before the PR opens.

**Tech Stack:** Python 3.12, MCP Python SDK v2 (pinned <2.1), libzim, pytest, uv, pre-commit.

**Spec:** per-workstream defect packets at `/private/tmp/claude-501/-Users-cameron-Developer-openzim-mcp/4bc0d93c-a872-4909-9521-c9907b9147b7/scratchpad/fixplan/<cluster>.json` — each entry carries defect_id, title, severity, observed, expected, verified root cause (file:line), and an exact repro command. The packet entry is the per-defect spec; treat `expected` as the acceptance criterion. Full sweep report: <https://claude.ai/code/artifact/51f04457-054e-4a98-8d27-499e66a2da6a>

## Global Constraints

- Branch from `fix/v3-field-defects` (HEAD of this plan's commit); name your branch exactly as your task states.
- TDD per defect: failing test first, watch it fail, minimal fix, watch it pass, commit. One commit per defect or per tightly-coupled defect group; conventional messages (`fix: ...`, `docs: ...`) written as the developer, no AI attribution, no Co-Authored-By.
- New tests go in a NEW file `tests/test_v3_field_fixes_<cluster>.py`. Modify existing test files only when a pinned test contradicts a fix; say so in the commit body.
- Pre-commit is stricter than CI (bundled flake8 plugins, full-severity bandit). Run `uv run pre-commit run --files <changed>` and read the REAL exit code — never pipe through `tail`/`echo $?` chains that mask it. Never `--no-verify`, never amend.
- The full suite excludes `-m live` by default; run `uv run pytest -x -q` before your final commit and leave it green. 3 live tests fail on main already — do not chase them.
- Real-corpus validation: spawn YOUR build via the harness — `echo '<ops>' | uv run --project <your-worktree> python /private/tmp/claude-501/-Users-cameron-Developer-openzim-mcp/4bc0d93c-a872-4909-9521-c9907b9147b7/scratchpad/harness.py --repo <your-worktree>` (ops format in the harness header). Corpus: /Users/cameron/Developer/zim (medlineplus 1.85GB, IEP 122MB).
- Schema budget is a hard 25,600-byte wire cap for the advanced tools array, currently at 24,835 — any schema/description growth must fit; check `tests/test_phase_f_schema_budget.py`.
- Tool descriptions live in `openzim_mcp/tools/*.md` + `tool_schemas.py`; behavior and description must land together.
- If a fix genuinely requires touching a file another workstream owns (ownership below), make the minimal edit and flag it in your final summary for merge attention.
- Do not bump versions, do not touch uv.lock/pyproject deps, do not modify `.github/`.

## Workstream ownership map

- **structure** -> `fix/v3-structure` — owns: openzim_mcp/zim/structure.py (links, sections, TOC, sidecar); may add error configs minimally
- **content** -> `fix/v3-content` — owns: openzim_mcp/zim/content.py, openzim_mcp/article_body.py, openzim_mcp/content_processor.py, openzim_mcp/tools/zim_get*.md descriptions
- **simple** -> `fix/v3-simple` — owns: openzim_mcp/simple_tools.py, intent_parser.py, chain_detection.py, cursor_decode.py, compact_renderers.py, synthesize.py
- **search** -> `fix/v3-search` — owns: openzim_mcp/zim/search.py, rerank.py, tools/zim_search description
- **errors** -> `fix/v3-errors` — owns: openzim_mcp/error_messages.py, security.py, exceptions.py, tools/* description .md files for browse/metadata, tool_schemas.py doc strings
- **protocol** -> `fix/v3-protocol` — owns: openzim_mcp/sdk_compat.py, server.py (prompt registration / error mapping), mcp_envelope.py
- **http** -> `fix/v3-http` — owns: openzim_mcp/http_app.py, docs/ deployment page
- **runtime** -> `fix/v3-runtime` — owns: openzim_mcp/zim/archive.py, server_state.py, cache.py, async_operations.py

---

### Task 1: workstream `structure` (17 defects)

**Files:**

- Modify: openzim_mcp/zim/structure.py (links, sections, TOC, sidecar); may add error configs minimally
- Test: `tests/test_v3_field_fixes_structure.py` (create)
- Packet: `/private/tmp/claude-501/-Users-cameron-Developer-openzim-mcp/4bc0d93c-a872-4909-9521-c9907b9147b7/scratchpad/fixplan/structure.json`

**Interfaces:**

- Produces: branch `fix/v3-structure` containing one commit per defect, full suite green, pre-commit clean.
- Consumes: nothing from other tasks (file ownership is disjoint by construction).

**Design guidance (decisions already made — follow them):**

Hard calls, decided here:

- D33 (outbound urls don't round-trip): add a resolved `path` field to outbound internal link rows using the existing `_resolve_link_to_entry_path` (structure.py:1243+), mirroring related/inbound. Keep `url` as the raw href for fidelity; document both in the LinkItem schema docs (tool_schemas.py:112-126) and zim_links_description.md. Watch the 25KB schema budget — check `tests/test_phase_f_schema_budget.py` allocations before growing schema text; prefer description-file wording over schema growth.
- D34 (inbound total=0 for redirect spellings): canonicalize entry_path through `best_effort_redirect_chain` before `reader.query_inbound`, and raise the entry-not-found error when the entry does not exist at all (outbound already errors; make directions consistent).
- D35 (related path-as-title junk): in `_resolve_outbound_titles` follow redirects via `best_effort_redirect_chain` (as the sidecar builder does at structure.py:1389-1394) and emit the canonical post-redirect path so related/inbound agree.
- D18 (get_section KeyError envelope): make the except clauses at structure.py:676-679 honor the docstring contract (structure.py:648-651) — return the entry_not_found ToolErrorPayload, matching zim_get's targeted envelope.
Smaller items (see packet): duplicate TOC anchor ids must be de-duplicated (suffix or ordinal) so every listed section is fetchable; compact=True link-stripping must agree between zim_get and zim_get_section; remove or implement the advertised 'optional subsection inclusion'; section_not_found on section-free entries should say why; non-HTML zim_links should emit the documented `message` field; media assets out of the internal bucket (anchor-wrapped images belong under media kind); nonexistent-entry outbound error should be not-found, not corruption-flavored; cursor archive-identity mismatch gets a cursor_* envelope; document per-direction caps/defaults and occurrence-level semantics; closest_match for case-variant section ids.

**Defects:**

- [ ] **D18** [major] Nonexistent entry_path returns raw KeyError 'Operation Failed' envelope instead of the promised entry_not_found error
  - Root cause: openzim_mcp/zim/structure.py:676-679
  - Acceptance: get_section_data's docstring (zim/structure.py:648-651) promises 'a ToolErrorPayload on file-not-found / entry-not-found / section-not-found'. zim_get on the same bad path returns a targeted 'Resource Not Found — double-check the spelling and path' envelope; zim_get_section should return operation='
- [ ] **D19** [minor] Duplicate explicit anchors yield duplicate TOC section_ids; second section is unfetchable and its id silently returns the wrong section
  - Root cause: openzim_mcp/content_processor.py:709-713
  - Acceptance: section_id is the tool's unique handle ('The TOC id ... of the section'); when the archive reuses an anchor name, the TOC/get_section surface should disambiguate (e.g. SH4b_2 like the slug path does) or otherwise make every listed section fetchable, rather than list two identical handles that resolv
- [ ] **D20** [minor] compact=True section text does not match zim_get compact=True article text: links are stripped in one but kept in the other
  - Root cause: openzim_mcp/zim/content.py:910-911
  - Acceptance: bundle.py:526-530 states compact=True is used 'so a section slice matches the article-fetch path', and tools/zim_get_section.py:7-11 says compact=True matches 'the get_zim_entry slice shape'. Either the bundle's compact rendering should also strip links, or the docs/comments should say the two compa
- [ ] **D21** [minor] Tool description advertises 'optional subsection inclusion' but no such parameter exists; passing include_subsections is silently ignored
  - Root cause: openzim_mcp/tools/zim_get_section.py:41-48
  - Acceptance: Either wire the data layer's fully-implemented include_subsections flag (zim/structure.py:639-651 documents and implements it, including the D5 narrow-widening logic) through the tool signature, or remove 'with optional subsection inclusion' from the description; an unknown argument silently ignored
- [ ] **D22** [minor] zim_get view=toc/structure on a nonexistent entry reports 'Archive Operation Error ... Verify the ZIM file is not corrupted' instead of entry-not-found
  - Root cause: openzim_mcp/zim/structure.py:542-544 (toc) and openzim_mcp/zim/structure.py:203-205 (structure)
  - Acceptance: The toc/structure views should produce the same not-found classification as the full view, since the underlying failure is the identical missing entry.
- [ ] **D23** [minor] section_not_found on entries that can have no sections (non-HTML or heading-free) never says why — empty id list with generic retry advice
  - Root cause: openzim_mcp/zim/structure.py:711-748
  - Acceptance: When the section list is empty, the error should say the entry has no sections (and why — non-HTML content_type or no headings), instead of implying the caller merely picked a wrong id; a model following the current message burns a round-trip on the TOC call just to learn there was never anything to
- [ ] **D24** [cosmetic] Case-variant section ids get no closest_match suggestion ('sh2d' vs 'SH2d')
  - Root cause: openzim_mcp/zim/structure.py:727-729 (difflib.get_close_matches, case-sensitive ratio 0.5 < cutoff 0.6)
  - Acceptance: A pure case mismatch is the easiest typo to repair; the Did-you-mean pass should try a case-insensitive comparison (or casefold both sides before difflib) so short mixed-case anchor ids like the IEP's H1/SH2d family are recoverable.
- [ ] **D25** [cosmetic] Rate-limit error tells the caller to 'Please wait 0.00 seconds before retrying'
  - Root cause: openzim_mcp/rate_limiter.py:350-358 and 361-374 (f'{wait_time:.2f}' with no floor); contributing race at rate_limiter.py:129-134 (get_wait_time re-refills after the failed acquire, so it can return values arbitrarily close to — or exactly — 0.0)
  - Acceptance: Round up to a minimum displayable wait (e.g. 'less than 0.01 seconds' or 0.01) so the guidance is actionable.
- [ ] **D33** [major] direction='related' returns path-as-title junk titles for zimit archives (redirect entries not followed)
  - Root cause: openzim_mcp/zim/structure.py:1213-1227 (_resolve_outbound_titles calls _resolve_entry_spelling at line 1220 and takes entry.title without checking entry.is_redirect or following best_effort_redirect_chain; item['path'] at line 1221 stays the pre-redirect spelling)
  - Acceptance: Docstring (structure.py:948-950) promises "the linked entry's actual archive title", with path fallback only when the entry is missing. _resolve_outbound_titles should follow redirect entries (the sidecar builder already does exactly this via best_effort_redirect_chain at structure.py:1389-1394) and
- [ ] **D34** [major] Outbound internal link urls are raw document-relative hrefs that do not round-trip into zim_get / other zim_links directions
  - Root cause: openzim_mcp/zim/structure.py:435-455 (payload passes bundle link items through verbatim; the server-owned resolver_resolve_link_to_entry_path at structure.py:1243+ is applied for related/inbound/sidecar-build but never to outbound rows); raw href stored at openzim_mcp/content_processor.py:775-778
  - Acceptance: Each internal row should carry (or the docs should explain how to derive) a fetchable ZIM entry path — e.g. an added resolved `path` field per row, as related/inbound already provide — so zim_links output composes with zim_get. At minimum the tool description should warn that `url` is the raw href r
- [ ] **D35** [major] direction='inbound' silently returns total=0 for redirect spellings and nonexistent entries
  - Root cause: openzim_mcp/zim/structure.py:1153 (reader.query_inbound(entry_path,...) — exact-string sidecar lookup with no redirect canonicalization and no entry-existence check; docstring at structure.py:1100-1105 only motivates the exact lookup by namespace-scheme handling, not redirects)
  - Acceptance: Redirect spellings should be canonicalized through the redirect chain before the sidecar lookup (the builder already stores canonical targets), or at least a nonexistent/redirect entry should produce a distinguishable message rather than an empty success identical to "genuinely zero inbound links".
- [ ] **D36** [minor] Nonexistent entry_path (outbound) yields misleading 'Archive Operation Error' suggesting corruption
  - Root cause: openzim_mcp/zim/structure.py:469-471
  - Acceptance: Entry-not-found should be detected (KeyError from archive.get_entry_by_path) and rendered as the not-found envelope zim_get uses, ideally with search suggestions; troubleshooting text about corruption should be reserved for actual archive failures.
- [ ] **D37** [minor] Non-HTML entry returns silent empty LinksResponse without the documented `message` field
  - Root cause: openzim_mcp/zim/structure.py:435-455
  - Acceptance: A `message` like "Link extraction requires HTML content, got: image/png" so callers can distinguish 'no links in this article' from 'this entry type has no extractable links'.
- [ ] **D38** [minor] Anchor-wrapped media assets pollute the outbound 'internal' bucket and category_totals.internal
  - Root cause: openzim_mcp/content_processor.py:802-803
  - Acceptance: Anchor-wrapped asset targets should be filtered from (or at least flagged in) the internal bucket — e.g. reclassified into media or given type="asset" — so category_totals.internal counts navigable articles consistently with related/inbound.
- [ ] **D39** [cosmetic] Outbound results are occurrence-level (duplicates repeated), and neither description nor schema documents this
  - Root cause: openzim_mcp/tools/zim_links_description.md (RESPONSE section) + openzim_mcp/content_processor.py:796-803
  - Acceptance: Document that outbound results preserve every occurrence in document order (duplicates included) so clients don't misread `total` as a unique-link count; or dedupe with an occurrence counter like related does.
- [ ] **D40** [cosmetic] Cursor archive-identity mismatch surfaces as generic 'zim_links' validation envelope instead of a cursor_* operation code
  - Root cause: openzim_mcp/zim/structure.py:372-379
  - Acceptance: Archive-identity mismatch should surface under a cursor_* operation code consistent with the other three cursor failure modes.
- [ ] **D41** [cosmetic] Per-direction limit caps (500 vs 100) and defaults (100 vs 10) are undocumented and absent from the input schema
  - Root cause: openzim_mcp/tools/zim_links_description.md:30 (limit documented only as 'Page size'); caps: openzim_mcp/zim/structure.py:344 (outbound 1-500) vs structure.py:953 (related 1-100) and structure.py:1107 (inbound 1-100); defaults: openzim_mcp/tools/zim_links.py:83 (outbound 100), zim_links.py:140 (inbound 10), zim_links.py:163 (related 10)
  - Acceptance: Document the per-direction ranges/defaults in the PARAMETERS section (and ideally add bounds to the schema or unify the caps).

**Per-defect cycle (repeat for every defect above, in packet order):**

- [ ] Step 1: Read the packet entry (observed/expected/cause/repro) and the cited source.
- [ ] Step 2: Write the failing test in `tests/test_v3_field_fixes_structure.py` asserting the `expected` behavior; run `uv run pytest tests/test_v3_field_fixes_structure.py -x -q` and confirm it FAILS for the defect's reason.
- [ ] Step 3: Implement the minimal fix at the root cause site.
- [ ] Step 4: Re-run the test file — PASS; run the module's existing tests (e.g. `uv run pytest tests/ -q -k <module>`) — no regressions.
- [ ] Step 5: Where the defect is corpus-visible, re-run the packet's repro via the harness against YOUR worktree and confirm the observed behavior is gone.
- [ ] Step 6: `uv run pre-commit run --files <changed>`; fix what it flags.
- [ ] Step 7: Commit (`fix: <what/why>` or `docs: ...`), message body cites the defect_id.

---

### Task 2: workstream `content` (12 defects)

**Files:**

- Modify: openzim_mcp/zim/content.py, openzim_mcp/article_body.py, openzim_mcp/content_processor.py, openzim_mcp/tools/zim_get*.md descriptions
- Test: `tests/test_v3_field_fixes_content.py` (create)
- Packet: `/private/tmp/claude-501/-Users-cameron-Developer-openzim-mcp/4bc0d93c-a872-4909-9521-c9907b9147b7/scratchpad/fixplan/content.json`

**Interfaces:**

- Produces: branch `fix/v3-content` containing one commit per defect, full suite green, pre-commit clean.
- Consumes: nothing from other tasks (file ownership is disjoint by construction).

**Design guidance (decisions already made — follow them):**

Hard calls, decided here:

- D07 (percent-encoded paths unfetchable): in `_smart_retrieve_entry` (content.py:679-806) try `urllib.parse.unquote` variants before falling through to search — reuse `_resolve_entry_spelling`-style raw-first/decoded-fallback (zim/structure.py:50-81). Round-trip test: the IEP `gau%E1%B8%8Dapad` case from the packet.
- D43 (MedlinePlus lead = nav junk): fix `_lead_with_toc` (article_body.py:207) + `_lead_density` (article_body.py:141-205) so nav-list blocks (link-dense low-prose lists like MedlinePlus 'On this page') don't count as substantive lead; the cut must advance to real prose. Embed a trimmed real MedlinePlus HTML snippet as a test fixture. This also fixes tell_me_about/summary/synthesize output (the simple cluster tests it end-to-end; you own the extraction fix).
- D14/D15 (main_page skips chrome scoping; max_content_length ignored on main_page): route the main_page branch through the same scoping + truncation as path fetches.
Smaller items: correct not-found advice naming real tools; binary oversize message must reference parameters that exist; batch truncation footer must not advise content_offset (batch rejects it) — point at single-entry retry instead; batch items get the clean body, not the legacy header block; view=summary quality on topic pages follows the D43 fix; strip the recurring noscript boilerplate ('To use the sharing features…') in the content pipeline (search snippets benefit too — coordinate note in commit); truncation footer off-by-one; leading-slash redacted context.

**Defects:**

- [ ] **D07** [major] Percent-encoded paths from the archive's own links are unfetchable (round-trip broken)
  - Root cause: openzim_mcp/zim/content.py:679-806 (_smart_retrieve_entry ladder never tries urllib.parse.unquote before raising Entry-not-found; the raw-first/decoded-fallback helper _resolve_entry_spelling already exists at openzim_mcp/zim/structure.py:50-81 but is only wired into the links/related surfaces)
  - Acceptance: The smart-retrieval ladder should try a percent-decoded variant before giving up (decode helpers already exist at zim/structure.py:74 and zim/search.py:3486/3536 but the entry-fetch ladder never uses them), so served links resolve. Affects any archive with non-ASCII entry paths.
- [ ] **D08** [minor] Not-found errors tell callers to use nonexistent tools search_zim_file()/browse_namespace()
  - Root cause: openzim_mcp/zim/content.py:788-789, 805, 1486-1487 (entry-level) and 520, 648 (file-level), plus openzim_mcp/zim/archive.py:1460; the existing leak sanitizer _BACKEND_API_LEAK_RE at openzim_mcp/simple_tools.py:1624-1626 only covers simple mode
  - Acceptance: Error guidance should name the tools the server actually exposes (zim_search / zim_browse, or zim_query in simple mode).
- [ ] **D09** [minor] Binary oversize message references parameters zim_get does not expose (include_data, max_size_bytes)
  - Root cause: openzim_mcp/zim/content.py:1594-1598 (message built with data-layer names), surfaced untranslated via openzim_mcp/tools/zim_get.py:192-194
  - Acceptance: The hint should name max_content_length (the parameter that actually maps to the byte cap in this tool), and not offer include_data, which is unreachable from zim_get.
- [ ] **D10** [minor] main_page=True skips site-chrome scoping — dirtier output than fetching the same entry by path
  - Root cause: openzim_mcp/zim/archive.py:1280-1282 (_build inside _get_main_page_result calls process_mime_content without scope_main_content=True)
  - Acceptance: Both branches should serve the same cleaned content: the entry branch passes scope_main_content=True to process_mime_content (zim/content.py:892) with the stated intent of matching cleaned output, but the main-page builder omits it.
- [ ] **D11** [minor] max_content_length silently ignored in the main_page branch
  - Root cause: openzim_mcp/tools/zim_get.py:184 (main_page branch never forwards max_content_length) + openzim_mcp/zim/archive.py:1172-1174, 1288-1290 (get_main_page_data has no cap parameter; always truncates at DEFAULT_MAIN_PAGE_TRUNCATION)
  - Acceptance: Either honor max_content_length for the main page body or reject it as an invalid combination like the other forbidden main_page parameters; silence contradicts the tool's own defense-in-depth pattern.
- [ ] **D12** [minor] Batch items' truncation footer instructs passing content_offset, which batch mode rejects
  - Root cause: openzim_mcp/zim/content.py:1082-1088 (batch loop calls the legacy text surface with offset 0) leaving paginatable at its True default (content_processor.py:1452), producing the tail at content_processor.py:1542
  - Acceptance: Batch rendering should use the non-paginatable footer variant that already exists (content_processor.py:1546-1550 points callers at re-fetching the path with content_offset via a single-entry call), not the paginatable hint.
- [ ] **D13** [minor] Batch item content embeds a legacy header block instead of the clean body the docs promise
  - Root cause: openzim_mcp/zim/content.py:1082 (batch loop) →_get_zim_entry_from_archive (content.py:523) → _render_entry_payload_text (content.py:141-159, invoked at content.py:1407) — the legacy text document, not the structured payload body
  - Acceptance: Batch item content should be the same clean body text as the single-entry structured payload (path/title/type already identifiable via the item's entry_path field), or the description should say each item is a pre-rendered document.
- [ ] **D14** [minor] view=summary on MedlinePlus topic pages is mostly in-page navigation, not the summary
  - Root cause: openzim_mcp/zim/content.py:213-214 (first-section fallback slices top of rendered markdown, which retains the #toc-section menu); word budget applied at zim/content.py:1772-1775
  - Acceptance: A 'short summary' view should skip list-only navigation blocks (or start at the page's own '## Summary' section) so the budget goes to prose.
- [ ] **D15** [minor] Recurring noscript junk 'To use the sharing features on this page, please enable JavaScript.' in article bodies
  - Root cause: openzim_mcp/defaults.py:196-244 (UNWANTED_HTML_SELECTORS lacks "noscript"), applied at content_processor.py:1254-1256; contrast zim/content.py:1861 where the summary fallback strips noscript
  - Acceptance: The main-content scoper should drop this known share-widget boilerplate (comparable chrome like 'Skip navigation' is already stripped for entry fetches).
- [ ] **D16** [cosmetic] Truncation footer claims 'showing first N' when N-1 chars were emitted (trailing-whitespace trim)
  - Root cause: openzim_mcp/content_processor.py:1567 (footer prints max_length) vs :1509-1510 (emitted slice is rstripped to paged_slice_length) and meta.py:135 (more_at_offset uses the trimmed length)
  - Acceptance: The human-readable count should match the emitted slice length / more_at_offset (say 'first 599'), or the whitespace should not be trimmed from the count.
- [ ] **D17** [cosmetic] Leading-slash path failure shows a redacted, confusing context ('Path: ...diabetes.html')
  - Root cause: openzim_mcp/security.py:518
  - Acceptance: ZIM entry paths are not filesystem paths; the redactor should not mangle them in entry-not-found contexts, and/or smart retrieval could try lstrip('/') as a trivial fallback.
- [ ] **D43** [major] tell_me_about / summary / synthesize return only navigation junk for MedlinePlus topic pages (lead section is the 'On this page' nav)
  - Root cause: openzim_mcp/article_body.py:207 (_lead_with_toc cuts at first non-wrapper H2) combined with article_body.py:141-205 (_EMPTY_LEAD_DENSITY_THRESHOLD=5 and _lead_density count nav-list text as substantive, so _advance_cut_to_second_h2 never fires); no warc2zim/zimit 'On this page' nav stripping exists in content_processor.py
  - Acceptance: The flagship 'tell me about <topic>' call on a health-encyclopedia topic page should surface the actual Summary prose (skip the on-page nav), the way get article does after the nav block.

**Per-defect cycle (repeat for every defect above, in packet order):**

- [ ] Step 1: Read the packet entry (observed/expected/cause/repro) and the cited source.
- [ ] Step 2: Write the failing test in `tests/test_v3_field_fixes_content.py` asserting the `expected` behavior; run `uv run pytest tests/test_v3_field_fixes_content.py -x -q` and confirm it FAILS for the defect's reason.
- [ ] Step 3: Implement the minimal fix at the root cause site.
- [ ] Step 4: Re-run the test file — PASS; run the module's existing tests (e.g. `uv run pytest tests/ -q -k <module>`) — no regressions.
- [ ] Step 5: Where the defect is corpus-visible, re-run the packet's repro via the harness against YOUR worktree and confirm the observed behavior is gone.
- [ ] Step 6: `uv run pre-commit run --files <changed>`; fix what it flags.
- [ ] Step 7: Commit (`fix: <what/why>` or `docs: ...`), message body cites the defect_id.

---

### Task 3: workstream `simple` (12 defects)

**Files:**

- Modify: openzim_mcp/simple_tools.py, intent_parser.py, chain_detection.py, cursor_decode.py, compact_renderers.py, synthesize.py
- Test: `tests/test_v3_field_fixes_simple.py` (create)
- Packet: `/private/tmp/claude-501/-Users-cameron-Developer-openzim-mcp/4bc0d93c-a872-4909-9521-c9907b9147b7/scratchpad/fixplan/simple.json`

**Interfaces:**

- Produces: branch `fix/v3-simple` containing one commit per defect, full suite green, pre-commit clean.
- Consumes: nothing from other tasks (file ownership is disjoint by construction).

**Design guidance (decisions already made — follow them):**

Hard calls, decided here:

- D58 (zim_query isError=False on failures): route zim_query's path-resolution/security failures through the structured error envelope with isError=True (simple_tools.py:890-941). mcp_envelope.py's docstring already declares this a protocol defect — align behavior. Keep the friendly markdown as the error content; the change is the error flag + envelope, not the prose.
- D42 (tell_me_about offset ignored): thread the caller's offset into all four `search_zim_file(_data)` calls in `_search_or_recover_tell_me_about` (simple_tools.py:3188-3214); the footer hint must reflect reality.
Smaller items (packet has repros): foreign-cursor guards for the unguarded intents; page-size stability when a cursor crosses intents; archive-name-in-query should select the archive and be stripped from terms; 'next page'/'more results' follow-ups should route to continuation guidance, not junk searches; document-or-honor offset in suggestions/find_by_title (done:false lie); strip command scaffolding ('get the article about') from search terms; 'Last, First' title matching for tell_me_about auto-fetch; get_zim_entries must parse this corpus's path shape and examples must teach real syntax; cursor-mismatch responses get one consistent intent marker and error envelope; binary not-found error must not leak internal API names; docstring compact-default claim fixed.

**Defects:**

- [ ] **D42** [major] tell_me_about advertises 'pass offset=N for the next page' but ignores offset entirely
  - Root cause: openzim_mcp/simple_tools.py:3188, 3194, 3201, 3214 — _search_or_recover_tell_me_about hardcodes offset 0 in all four search_zim_file(_data) calls while the shared search renderer appends the 'Showing 1-3 of ~151 — pass offset=3 for the next page' footer
  - Acceptance: offset should be threaded into the tell_me_about fallback search (or the footer hint should not be emitted), so the advertised continuation actually advances the page.
- [ ] **D44** [minor] Foreign cursors silently accepted by unguarded intents; browse cursor resizes find_by_title page from 10 to 5
  - Root cause: openzim_mcp/simple_tools.py:581 and 602-603 project the decoded cursor's offset/limit into options for EVERY intent, but the post-a18 P1-D4 guard _cursor_tool_mismatch (simple_tools.py:1380) is invoked only at 5 handler sites (1590, 2156, 2350, 2565, 3714); _handle_find_by_title reads the projected limit at simple_tools.py:3827 with no guard
  - Acceptance: Cross-tool cursor reuse should be rejected uniformly — cursor_decode's design notes and the 5 guarded handlers reject it with 'Cursor / Tool Mismatch'; the remaining cursor-consuming intents (find_by_title, related, suggestions, tell_me_about, get_article) should not silently apply a foreign cursor'
- [ ] **D45** [minor] Archive name in query neither selects the archive nor is stripped from search terms ('search medlineplus for diabetes')
  - Root cause: openzim_mcp/intent_parser.py:546-551 — _extract_search's unquoted branch captures everything after the verb (the optional 'for' strip only applies immediately after the verb, so 'medlineplus for diabetes' becomes the literal terms); no archive-hint resolution for search intents before the no-zim-file gate at openzim_mcp/simple_tools.py:772-815 (metadata-only precedent at 781-786)
  - Acceptance: The 'search <archive> for <terms>' surface form is extremely common; the metadata intent already resolves filename hints against loaded archives before the no-zim-file gate (simple_tools.py:781-786), so precedent exists to resolve (or at least strip) a named archive rather than searching it as liter
- [ ] **D46** [minor] 'next page' / 'more results' follow-ups run junk full-text searches instead of meta-query guidance
  - Root cause: openzim_mcp/intent_parser.py:1924 (_COMMON_FILLER_TOKENS lacks 'page'/'results'), enforced at openzim_mcp/simple_tools.py:1220-1227
  - Acceptance: These are the most common pagination follow-ups from small models and are exactly the 'no information content' class _is_meta_only_query exists for; they should return the guidance playbook (ideally pointing at the offset/cursor mechanism).
- [ ] **D47** [minor] Documented 'offset' arg is silently ignored by suggestions and find_by_title; suggestions reports done:false with no working continuation
  - Root cause: openzim_mcp/simple_tools.py:2300-2302 and :3791-3871 (offset never read); tools/zim_query_description.md:65 (undocumented exclusion)
  - Acceptance: Either honor offset for these list intents or document them in the 'setting it has no effect' list and stop emitting done:false without a continuation mechanism.
- [ ] **D48** [minor] 'get the article about X' phrasing leaks command scaffolding into search terms
  - Root cause: openzim_mcp/intent_parser.py:1135 (no optional determiner between verb and noun in the get_article pattern)
  - Acceptance: 'get the article about X' should route to get_article/tell_me_about with topic 'Immanuel Kant' (or at minimum the fallback search should strip the recognized scaffolding words the parser itself defines).
- [ ] **D49** [minor] tell_me_about never auto-fetches on 'Last, First'-titled corpora (natural-order name queries fall to plain search)
  - Root cause: openzim_mcp/title_promotion.py:61-86 (order-sensitive token-sequence/prefix comparison in is_strong_title_match), consumed at openzim_mcp/simple_tools.py:3209 and :3251
  - Acceptance: is_strong_title_match (or the title-index promotion) should treat token-SET equality (order-insensitive) or comma-inverted 'Last, First' titles as strong matches, so natural-order person queries at least reach the disambiguation/auto-fetch path.
- [ ] **D50** [minor] get_zim_entries cannot parse this corpus's own path shape; example teaches nonexistent 'C/...' syntax
  - Root cause: openzim_mcp/intent_parser.py:868
  - Acceptance: Accept the archive's real path shape (domain/... paths that the tool itself advertises), or at least render the example using paths that exist in the loaded archive.
- [ ] **D51** [cosmetic] Cursor mismatch responses are non-error markdown with two contradictory intent markers, while dispatcher cursor errors are structured isError JSON
  - Root cause: openzim_mcp/simple_tools.py:1408 (mismatch renderer embeds its own intent=cursor_decode marker) + simple_tools.py:997 (_finalize_compact_response unconditionally appends the parsed-intent marker to any str result)
  - Acceptance: One telemetry marker per response, and the same isError/ToolErrorPayload envelope for both rejection layers of the same argument.
- [ ] **D52** [cosmetic] Binary intent's not-found error leaks internal API names unusable from the simple surface
  - Root cause: openzim_mcp/simple_tools.py:2259-2283 (_handle_binary calls get_binary_entry with no try/except recovery, unlike siblings at 1857/1936/2257/2527 which route through _render_not_found_recovery)
  - Acceptance: Binary should use the same _render_not_found_recovery natural-language suggestions ('search for ...', 'browse namespace ...') as its sibling intents.
- [ ] **D53** [cosmetic] zim_query docstring says compact defaults True 'in simple mode' but the default is True in advanced mode too
  - Root cause: openzim_mcp/tools/zim_query_description.md:73 (wording) vs openzim_mcp/tools/zim_query.py:63 (compact: bool = True in the single registration shared by both modes via tools/**init**.py:35)
  - Acceptance: Docstring should say the default is True (both modes), or the advanced registration should default False to match the wording.
- [ ] **D58** [major] zim_query reports path-resolution and security-denial failures as isError=False (success), unlike all 7 sibling tools
  - Root cause: openzim_mcp/simple_tools.py:890-941
  - Acceptance: A security denial / path-resolution failure is a failure and should carry isError=True (or the structured error envelope). openzim_mcp/mcp_envelope.py's own docstring states this is 'a protocol defect, not a cosmetic one' because 'a security denial is indistinguishable from a successful search'. zim

**Per-defect cycle (repeat for every defect above, in packet order):**

- [ ] Step 1: Read the packet entry (observed/expected/cause/repro) and the cited source.
- [ ] Step 2: Write the failing test in `tests/test_v3_field_fixes_simple.py` asserting the `expected` behavior; run `uv run pytest tests/test_v3_field_fixes_simple.py -x -q` and confirm it FAILS for the defect's reason.
- [ ] Step 3: Implement the minimal fix at the root cause site.
- [ ] Step 4: Re-run the test file — PASS; run the module's existing tests (e.g. `uv run pytest tests/ -q -k <module>`) — no regressions.
- [ ] Step 5: Where the defect is corpus-visible, re-run the packet's repro via the harness against YOUR worktree and confirm the observed behavior is gone.
- [ ] Step 6: `uv run pre-commit run --files <changed>`; fix what it flags.
- [ ] Step 7: Commit (`fix: <what/why>` or `docs: ...`), message body cites the defect_id.

---

### Task 4: workstream `search` (7 defects)

**Files:**

- Modify: openzim_mcp/zim/search.py, rerank.py, tools/zim_search description
- Test: `tests/test_v3_field_fixes_search.py` (create)
- Packet: `/private/tmp/claude-501/-Users-cameron-Developer-openzim-mcp/4bc0d93c-a872-4909-9521-c9907b9147b7/scratchpad/fixplan/search.json`

**Interfaces:**

- Produces: branch `fix/v3-search` containing one commit per defect, full suite green, pre-commit clean.
- Consumes: nothing from other tasks (file ownership is disjoint by construction).

**Design guidance (decisions already made — follow them):**

Hard calls, decided here:

- D26 (typo tolerance never fires): `_find_entry_fast_path` (search.py:2699-2731) verifies typo candidates only via exact `has_entry_by_title` + `C/`/`A/` path probes — structurally unsatisfiable on scraped archives (suffixed titles, domain-prefixed paths). Re-verify candidates against the title index via suggestion search (prefix/contains match on the candidate) instead of exact-title equality, so Levenshtein-1 variants like 'Diabtes'→'Diabetes' produce _meta.suggestions and the promotion machinery can fire. Add `_meta.suggestions` on 0-hit title queries when candidates exist. Test with the repo's test_data ZIMs; validate by hand against the real corpus via the harness before finishing.
Smaller items: dedupe query-string variants of the same page in plain fulltext (the filter exists on another path — apply it); low_relevance false positives when the top hit is an exact/folded match of the query; boilerplate snippet suppression (coordinate with content cluster's noscript strip — snippet source should skip boilerplate blocks when choosing extract windows); document Boolean/Xapian operators as unsupported literals in the tool description (do NOT implement operator parsing); consistent empty-query envelope across the three modes; IEP snippet junk (empty image links, MathJax soup) — strip in snippet post-processing.

**Defects:**

- [ ] **D26** [major] Title-mode typo tolerance and filler-prose promotion never fire on either real archive — natural queries return empty with no recovery hints
  - Root cause: openzim_mcp/zim/search.py:2699-2731 (_find_entry_fast_path verifies typo variants only via exact has_entry_by_title + C//A/ path probes — structurally unsatisfiable on scraped archives with suffixed titles and domain-prefixed paths, so the sweep at search.py:2842 verifies nothing and _meta.suggestions stays empty); search.py:2791 (deletion edits gated to len>=6, so 'Kannt'->'Kant' is never generated); openzim_mcp/title_promotion.py:246 (min_score gate: suffixed titles cap at 0.95 fuzzy_suggest so the strict-1.0 passes at topic_preprocessing.py:159-173 can never fire) plus title_promotion.py:1147-1156 (passes_z4: the correctly-resolved 0.8-gate candidate is rejected as is_tangential_multi_token_shape because the ' | MedlinePlus' suffix inflates the title token set)
  - Acceptance: The tool description promises 'Exact / typo-tolerant title lookup ... case ladder + suggestion expansion + Levenshtein-1' and 'Single-archive applies Z3/Z4/OPP-1 promotion'; zim_search.py's own docstring says filler-prose queries that miss on the full phrase are rescued by tail/window probes and ser
- [ ] **D27** [minor] Plain fulltext search returns query-string variants of the same page as duplicate results (filtered path already dedupes them)
  - Root cause: openzim_mcp/zim/search.py:788-802 (_perform_search appends raw hits; canonical_result_path is applied only in the filtered scanner at zim/search.py:1893)
  - Acceptance: Each underlying page emitted once per result page, matching the intent stated in canonical_result_path's docstring ('a full-text search surfaces ...htm and ...htm?quiz=1 as two hits for the same page. Collapsing on the canonical path lets the scanner emit each page once') and reasonable client expec
- [ ] **D28** [minor] _meta.reason="low_relevance" false positives on wildcard and diacritic-folded queries whose hits are exactly on-topic
  - Root cause: openzim_mcp/text_utils.py:12,21 (_TOKEN_RE = [a-z0-9]+, exact lowercase token sets) used by _all_results_weakly_match at openzim_mcp/zim/search.py:243-249
  - Acceptance: No low_relevance flag when results token-match the query modulo the same stemming/diacritic folding Xapian itself applied to produce the hits.
- [ ] **D29** [minor] ~43% of MedlinePlus fulltext snippets are information-free boilerplate ('To use the sharing features on this page, please enable JavaScript.')
  - Root cause: openzim_mcp/content_processor.py:1344-1374 (create_snippet anchors on the first whole-word-matching paragraph — the H1 on this corpus — and max_paragraphs=2 appends the corpus-ubiquitous no-JS paragraph; no boilerplate filtering)
  - Acceptance: Snippets that carry article content (lead sentence or query-term context), skipping ubiquitous boilerplate/nav paragraphs — as the informative snippets on the same page ('An insulin in blood test measures...') show is achievable.
- [ ] **D30** [minor] Boolean/Xapian operator syntax treated as literal terms: OR-query totals lower than single terms, NOT ignored, operator words bold-highlighted in snippets
  - Root cause: openzim_mcp/zim/search.py:747 (query passed verbatim to libzim Query().set_query, no boolean parsing, no doc warning) + openzim_mcp/content_processor.py:344,1345 (_split_query_terms has no operator/stopword handling; the len>=3 filter keeps 'and'/'not' as snippet match/highlight terms)
  - Acceptance: Either operator/phrase support, or the description warning that operators/quotes are treated as literal terms; operator stopwords not counted as match terms for snippet selection/highlighting; union estimates not lower than their single-term components.
- [ ] **D31** [cosmetic] Empty-query handling is inconsistent across the three modes
  - Root cause: openzim_mcp/zim/search.py:537-553 (fulltext bad_query branch) vs openzim_mcp/zim/search.py:2104-2113 (suggest empty payload, no reason) vs openzim_mcp/zim/search.py:3133-3136 (title raises ValidationError, converted by broad except at openzim_mcp/tools/zim_search.py:256-262)
  - Acceptance: One consistent contract for an empty/whitespace query across modes — ideally the structured reason='bad_query' shape fulltext already uses, or a typed invalid_query error.
- [ ] **D32** [cosmetic] IEP snippets carry rendering junk: empty markdown links for images and escaped MathJax soup
  - Root cause: openzim_mcp/content_processor.py:899-900 and 948-949 (ignore_images=True + ignore_links=False leaves [](href) for zimit anchor-wrapped lead images); no math/MathJax handling anywhere in the render pipeline; snippet path openzim_mcp/zim/content.py:306_get_entry_snippet
  - Acceptance: Image remnants dropped entirely (no empty [](...) links) and MathJax either rendered to plain text or replaced with a placeholder, so snippets read cleanly.

**Per-defect cycle (repeat for every defect above, in packet order):**

- [ ] Step 1: Read the packet entry (observed/expected/cause/repro) and the cited source.
- [ ] Step 2: Write the failing test in `tests/test_v3_field_fixes_search.py` asserting the `expected` behavior; run `uv run pytest tests/test_v3_field_fixes_search.py -x -q` and confirm it FAILS for the defect's reason.
- [ ] Step 3: Implement the minimal fix at the root cause site.
- [ ] Step 4: Re-run the test file — PASS; run the module's existing tests (e.g. `uv run pytest tests/ -q -k <module>`) — no regressions.
- [ ] Step 5: Where the defect is corpus-visible, re-run the packet's repro via the harness against YOUR worktree and confirm the observed behavior is gone.
- [ ] Step 6: `uv run pre-commit run --files <changed>`; fix what it flags.
- [ ] Step 7: Commit (`fix: <what/why>` or `docs: ...`), message body cites the defect_id.

---

### Task 5: workstream `errors` (8 defects)

**Files:**

- Modify: openzim_mcp/error_messages.py, security.py, exceptions.py, tools/* description .md files for browse/metadata, tool_schemas.py doc strings
- Test: `tests/test_v3_field_fixes_errors.py` (create)
- Packet: `/private/tmp/claude-501/-Users-cameron-Developer-openzim-mcp/4bc0d93c-a872-4909-9521-c9907b9147b7/scratchpad/fixplan/errors.json`

**Interfaces:**

- Produces: branch `fix/v3-errors` containing one commit per defect, full suite green, pre-commit clean.
- Consumes: nothing from other tasks (file ownership is disjoint by construction).

**Design guidance (decisions already made — follow them):**

Hard calls, decided here:

- D04 (bare archive name → 'Security Validation Error'): the project already ruled this wording a regression for zim_query (tests/test_path_error_wording.py); extend the same contract to the advanced tools. In security.py:160-163, when a relative input resolves outside allowed dirs, distinguish 'no traversal, just doesn't match a loaded archive' and let error_messages.py render a did-not-match-any-loaded-archive envelope pointing at loaded_archives[].path — reserve the security framing for actual traversal/absolute-escape attempts. Better: before cwd-resolution, try matching the bare name against loaded archive basenames and resolve it (one loaded archive with that exact basename → use it); then the misleading error disappears for the common case.
- D02 (impossible 'omit zim_file_path' advice): parameterize the OpenZimMcpArchivePathError step list (error_messages.py:75) by tool capability — only tools whose schema allows omission advertise omission; also only claim auto-select when exactly one archive is loaded.
Smaller items: invalid `mode` should return the documented invalid_mode envelope (make the in-tool guard reachable or hoist the check); zim_search query-length cap mirroring zim_query's 4096 front door; bound the echoed entry_path length in zim_get error Technical Details; sanitize tab/newline in sanitize_context_for_error; browse description vs actual unknown-namespace envelope; document per-mode limit bounds (page 1-200, walk 1-500) consistently in error texts and description.

**Defects:**

- [ ] **D02** [minor] Error advice 'Omit `zim_file_path` entirely to auto-select the only archive' is impossible on zim_metadata/zim_browse (schema-required param)
  - Root cause: openzim_mcp/error_messages.py:75 (static OpenZimMcpArchivePathError step list shared by every tool)
  - Acceptance: Recovery steps should be valid for the tool that emitted them (only zim_health/zim_query-style tools accept omission), or the template should be parameterized per tool.
- [ ] **D03** [minor] Passing the bare archive name from loaded_archives[].name yields a misleading 'Security Validation Error / blocked for security reasons'
  - Root cause: openzim_mcp/security.py:161-163 (cwd-resolved relative input raised as security violation) routed via error_messages.py:224-225; the existing fix at simple_tools.py:506 (_path_failure_reason) covers only the zim_query path
  - Acceptance: Either resolve a bare name against loaded archives, or return a not-found/validation message saying relative names are unsupported and pointing at loaded_archives[].path — not a security-block message.
- [ ] **D04** [minor] Invalid `mode` returns a raw pydantic error, not the documented `invalid_mode` envelope (in-tool guard unreachable)
  - Root cause: openzim_mcp/tools/zim_browse.py:40 (Literal['page','walk'] schema pre-empts the invalid_mode guard at :53-60); promise at tools/zim_browse_description.md:33
  - Acceptance: Per the description: 'Invalid `mode` returns `invalid_mode`' — a structured envelope consistent with the server's other errors, without leaking pydantic internals.
- [ ] **D05** [cosmetic] zim_browse description says unknown namespace 'returns the underlying data-layer error envelope' but it returns a non-error empty success
  - Root cause: openzim_mcp/tools/zim_browse_description.md:32-34 (stale ERRORS text) vs the deliberate soft-reject at openzim_mcp/zim/namespace.py:705-729
  - Acceptance: Description and behavior should agree — document the soft-reject payload (or actually return the error envelope).
- [ ] **D06** [cosmetic] limit bounds differ by mode (page 1-200, walk 1-500) but are documented nowhere; error texts are inconsistently styled
  - Root cause: openzim_mcp/tools/zim_browse_description.md:21 omits bounds and openzim_mcp/tools/zim_browse.py:42 declares plain Optional[int] with no schema constraint; page bound at openzim_mcp/zim/namespace.py:692-693, walk bound at openzim_mcp/zim/namespace.py:1652
  - Acceptance: Document the per-mode limit ranges in the description/schema and use one error-message style for both modes.
- [ ] **D59** [minor] zim_search accepts an unbounded query and echoes it verbatim; zim_query's 4096-char front-door cap is missing on the sibling tool
  - Root cause: openzim_mcp/tools/zim_search.py:104-195
  - Acceptance: A free-text query field should have a front-door length bound consistent with zim_query, and/or the echoed query should be truncated. An unbounded input echoed 1:1 into the response is a needless amplification vector and an intra-family inconsistency (zim_query.py:85 documents the cap as an availabi
- [ ] **D60** [minor] zim_get error 'Technical Details' echoes an unbounded entry_path verbatim (exception message is path-redacted but never length-capped)
  - Root cause: openzim_mcp/server.py:417
  - Acceptance: The rendered error message should bound echoed user input the way the context field does. entry_path has no front-door length validation in zim_get, and the exception string embedded into `message` is only path-redacted, not length-capped, so an oversized entry_path produces an oversized error body.
- [ ] **D61** [minor] Tab and newline survive sanitize_context_for_error, injecting line breaks into returned error text (contradicts its docstring)
  - Root cause: openzim_mcp/security.py:478
  - Acceptance: sanitize_context_for_error's docstring promises raw user values 'cannot embed control characters ... in the response', but its_CONTEXT_CONTROL_CHARS_RE = [\x00-\x08\x0b\x0c\x0e-\x1f\x7f] deliberately excludes \x09 (tab) and \x0a (newline). Both are C0 control characters; letting an attacker-control

**Per-defect cycle (repeat for every defect above, in packet order):**

- [ ] Step 1: Read the packet entry (observed/expected/cause/repro) and the cited source.
- [ ] Step 2: Write the failing test in `tests/test_v3_field_fixes_errors.py` asserting the `expected` behavior; run `uv run pytest tests/test_v3_field_fixes_errors.py -x -q` and confirm it FAILS for the defect's reason.
- [ ] Step 3: Implement the minimal fix at the root cause site.
- [ ] Step 4: Re-run the test file — PASS; run the module's existing tests (e.g. `uv run pytest tests/ -q -k <module>`) — no regressions.
- [ ] Step 5: Where the defect is corpus-visible, re-run the packet's repro via the harness against YOUR worktree and confirm the observed behavior is gone.
- [ ] Step 6: `uv run pre-commit run --files <changed>`; fix what it flags.
- [ ] Step 7: Commit (`fix: <what/why>` or `docs: ...`), message body cites the defect_id.

---

### Task 6: workstream `protocol` (4 defects)

**Files:**

- Modify: openzim_mcp/sdk_compat.py, server.py (prompt registration / error mapping), mcp_envelope.py
- Test: `tests/test_v3_field_fixes_protocol.py` (create)
- Packet: `/private/tmp/claude-501/-Users-cameron-Developer-openzim-mcp/4bc0d93c-a872-4909-9521-c9907b9147b7/scratchpad/fixplan/protocol.json`

**Interfaces:**

- Produces: branch `fix/v3-protocol` containing one commit per defect, full suite green, pre-commit clean.
- Consumes: nothing from other tasks (file ownership is disjoint by construction).

**Design guidance (decisions already made — follow them):**

Constraint: the wire behavior largely lives in the SDK; fix server-side where the repo owns the surface, and where the SDK owns it use the established sdk_compat.py patch pattern (see the ping shim) with a canary test so the patch retires on SDK fix. Upstream-report notes go in the PR description, not code comments.

- D54 (modern-era prompts/get collapses to -32603): wrap prompt render/lookup failures so unknown-prompt and bad-argument cases return a structured invalid-params error naming the prompt/argument (server.py prompt registration; sdk_compat patch if the swallow happens inside SDK dispatch).
- D55 (legacy prompts/get error code 0): map to proper JSON-RPC codes (-32602 for client mistakes, -32603 for render faults).
- D56 (stdio silently drops malformed JSON/batch/invalid frames): emit -32700/-32600 responses where the spec requires them; if the drop happens in the SDK read loop, sdk_compat patch + canary. At minimum, log at warning level.
- D57 (pydantic internals leak in prompt errors): sanitize error text to name the prompt and argument, not register_prompts.<locals> paths or pydantic URLs.

**Defects:**

- [ ] **D54** [minor] Modern-era (2026-07-28) prompts/get collapses all client mistakes to -32603 "Internal server error" with no detail
  - Root cause: .venv/.../mcp/server/runner.py:544-548 (modern_error_data maps non-MCPError/non-ValidationError to bare INTERNAL_ERROR, discarding the message) fed by bare ValueErrors from the SDK prompt layer (.venv/.../mcp/server/mcpserver/prompts/manager.py:65 and server.py:1283 unknown name; prompts/base.py:160 missing required args; ValueError-wrapped pydantic error for unexpected kwargs); openzim_mcp/tools/prompts.py contains no MCPError(INVALID_PARAMS) conversion
  - Acceptance: -32602 Invalid params with a message naming the unknown prompt / missing argument, per the MCP spec's prompts error guidance (invalid prompt name and missing/invalid arguments are invalid-params conditions, not internal errors). This server targets 2026-07-28, so the modern path is the primary surfa
- [ ] **D55** [minor] Legacy-era prompts/get errors use JSON-RPC error code 0 (unknown prompt, missing args, render failures)
  - Root cause: .venv/lib/python3.12/site-packages/mcp/shared/jsonrpc_dispatcher.py:757 (fed by mcp/server/mcpserver/prompts/manager.py:53 and mcp/server/mcpserver/prompts/base.py:160)
  - Acceptance: -32602 Invalid params for unknown prompt / missing required arguments (JSON-RPC reserves error semantics; the SDK's own TODO admits JSON-RPC says INTERNAL_ERROR at minimum).
- [ ] **D56** [minor] stdio transport silently drops malformed JSON, batch arrays, and invalid request frames — no -32700/-32600 response ever sent
  - Root cause: .venv/lib/python3.12/site-packages/mcp/server/stdio.py:189-191 + .venv/lib/python3.12/site-packages/mcp/shared/jsonrpc_dispatcher.py:538-540
  - Acceptance: JSON-RPC 2.0: a parse failure MUST get a -32700 response with id null; an invalid Request object (missing jsonrpc, id:null) should get -32600. Batches were removed from MCP in 2025-06-18, so an array frame should be answered with an error, not silence.
- [ ] **D57** [cosmetic] Prompt error messages leak implementation internals: pydantic validation text, register_prompts.<locals> function paths, and Python set repr
  - Root cause: .venv/lib/python3.12/site-packages/mcp/server/mcpserver/prompts/base.py:200 (pydantic text + <locals> path) and base.py:160 (set repr), surfacing via jsonrpc_dispatcher.py:757
  - Acceptance: A clean, stable message naming the prompt and the offending argument(s), without internal function paths, pydantic doc URLs, or set reprs.

**Per-defect cycle (repeat for every defect above, in packet order):**

- [ ] Step 1: Read the packet entry (observed/expected/cause/repro) and the cited source.
- [ ] Step 2: Write the failing test in `tests/test_v3_field_fixes_protocol.py` asserting the `expected` behavior; run `uv run pytest tests/test_v3_field_fixes_protocol.py -x -q` and confirm it FAILS for the defect's reason.
- [ ] Step 3: Implement the minimal fix at the root cause site.
- [ ] Step 4: Re-run the test file — PASS; run the module's existing tests (e.g. `uv run pytest tests/ -q -k <module>`) — no regressions.
- [ ] Step 5: Where the defect is corpus-visible, re-run the packet's repro via the harness against YOUR worktree and confirm the observed behavior is gone.
- [ ] Step 6: `uv run pre-commit run --files <changed>`; fix what it flags.
- [ ] Step 7: Commit (`fix: <what/why>` or `docs: ...`), message body cites the defect_id.

---

### Task 7: workstream `http` (2 defects)

**Files:**

- Modify: openzim_mcp/http_app.py, docs/ deployment page
- Test: `tests/test_v3_field_fixes_http.py` (create)
- Packet: `/private/tmp/claude-501/-Users-cameron-Developer-openzim-mcp/4bc0d93c-a872-4909-9521-c9907b9147b7/scratchpad/fixplan/http.json`

**Interfaces:**

- Produces: branch `fix/v3-http` containing one commit per defect, full suite green, pre-commit clean.
- Consumes: nothing from other tasks (file ownership is disjoint by construction).

**Design guidance (decisions already made — follow them):**

- D62 (sessionless request leaks session+task): follow TransportSecurityGateMiddleware's precedent (http_app.py:483-503 names this exact harm) — gate sessionless non-initialize POSTs before the SDK session manager can mint a transport: reject with the same 400 -32600 body the SDK sends today, but with no session created. An initialize request (no session id yet) must still pass. Verify with the packet's repro: created=0 for 30 rejected requests, and DELETE/reuse flows still work. If a reliable body sniff is needed to detect initialize, read+replay the receive channel carefully (Starlette pattern) or gate on the documented header contract; state the choice in the commit.
- D63 (OPTIONS auth doc claim): fix the deployment doc to say CORS preflight is answered without a token by design (outer-CORS), matching verified behavior.

**Defects:**

- [ ] **D62** [major] Every sessionless request on streamable-HTTP leaks an unreaped session + live task (rejected 400s included)
  - Root cause: .venv/lib/python3.12/site-packages/mcp/server/streamable_http_manager.py:288-303 (SDK) + openzim_mcp/http_app.py:564
  - Acceptance: A request rejected before completing an initialize handshake should not permanently allocate a session and a task. The repo's own TransportSecurityGateMiddleware docstring (openzim_mcp/http_app.py:483-503) names exactly this harm ('every request is rejected and every request leaks a session, until t
- [ ] **D63** [cosmetic] Deployment doc claims OPTIONS /mcp always requires a Bearer token, but CORS preflight is answered 200 without one
  - Root cause: website/src/content/docs/http-and-docker-deployment.mdx:69 (inaccurate wording); behavior governed by openzim_mcp/http_app.py:581-582 (CORSMiddleware added last via Starlette LIFO, so it answers preflight before BearerTokenAuthMiddleware runs)
  - Acceptance: website/src/content/docs/http-and-docker-deployment.mdx line 69 states: 'OPTIONS /mcp is not exempt — the deliberately-closed preflight bypass means OPTIONS requests must also carry a valid Authorization: Bearer ...'. That is false whenever OPENZIM_MCP_CORS_ORIGINS is set (the documented browser dep

**Per-defect cycle (repeat for every defect above, in packet order):**

- [ ] Step 1: Read the packet entry (observed/expected/cause/repro) and the cited source.
- [ ] Step 2: Write the failing test in `tests/test_v3_field_fixes_http.py` asserting the `expected` behavior; run `uv run pytest tests/test_v3_field_fixes_http.py -x -q` and confirm it FAILS for the defect's reason.
- [ ] Step 3: Implement the minimal fix at the root cause site.
- [ ] Step 4: Re-run the test file — PASS; run the module's existing tests (e.g. `uv run pytest tests/ -q -k <module>`) — no regressions.
- [ ] Step 5: Where the defect is corpus-visible, re-run the packet's repro via the harness against YOUR worktree and confirm the observed behavior is gone.
- [ ] Step 6: `uv run pre-commit run --files <changed>`; fix what it flags.
- [ ] Step 7: Commit (`fix: <what/why>` or `docs: ...`), message body cites the defect_id.

---

### Task 8: workstream `runtime` (3 defects)

**Files:**

- Modify: openzim_mcp/zim/archive.py, server_state.py, cache.py, async_operations.py
- Test: `tests/test_v3_field_fixes_runtime.py` (create)
- Packet: `/private/tmp/claude-501/-Users-cameron-Developer-openzim-mcp/4bc0d93c-a872-4909-9521-c9907b9147b7/scratchpad/fixplan/runtime.json`

**Interfaces:**

- Produces: branch `fix/v3-runtime` containing one commit per defect, full suite green, pre-commit clean.
- Consumes: nothing from other tasks (file ownership is disjoint by construction).

**Design guidance (decisions already made — follow them):**

- D64 (Archive.check() freezes the event loop): libzim's check() holds the GIL, so to_thread cannot help. Run validation in a separate PROCESS: a small helper (module-level function taking the path, returning the validation dict) executed via concurrent.futures.ProcessPoolExecutor (spawn context, lazy singleton, max_workers=1) from get_archive_validation_data. Keep the sync API; async_operations wraps it as today. Handle child crashes as a validation error, not a server crash. Test: validation still correct on test_data ZIMs; assert the mechanism (the pool is used), plus a generous-threshold timing test only if the suite has a slow-test pattern.
- D01 (garbage .zim listed as loaded/healthy): _scan_zim_files (archive.py:445-478) globs by extension only. Cheap-validate each candidate at scan time (ZIM magic-bytes check, not a full open) and mark unreadable files with a warning entry + health warning; keep zim_files_found honest (server_state.py:66). Choose marking over silent exclusion so operators see the bad file.
- D65 (one limit=100 search evicts whole cache): the entry-count cap (100) is consumed by per-result snippets. Make the eviction unit the response (count responses, not per-result items) or size-based only; verify a limit=100 search no longer flushes unrelated entries (packet repro).

**Defects:**

- [ ] **D01** [minor] zim_health() lists unreadable garbage .zim files as loaded_archives ('the ZIM files the server can read') and stays 'healthy'
  - Root cause: openzim_mcp/zim/archive.py:445-478 (_scan_zim_files: glob+stat, never opens); count at openzim_mcp/server_state.py:66
  - Acceptance: loaded_archives should only contain openable archives, or unopenable *.zim files should be flagged (warning / unreadable marker) instead of being presented as loaded and healthy.
- [ ] **D64** [major] zim_health archive validation freezes the entire server event loop for the duration of Archive.check() (GIL held by libzim)
  - Root cause: openzim_mcp/zim/archive.py:722 (bool(archive.check()) in get_archive_validation_data) calling python-libzim 3.12.0's Archive.check() binding (.venv/lib/python3.12/site-packages/libzim/libzim.pyx:1247-1253), which invokes self.c_archive.check() WITHOUT 'with nogil' — unlike other methods in the same file (e.g. lines 516/539/564) that do release the GIL — so asyncio.to_thread (openzim_mcp/async_operations.py) cannot keep the loop responsive
  - Acceptance: async_operations.py states it 'wraps the synchronous operations with asyncio.to_thread() to prevent blocking the event loop'. A heavy validation running in a worker thread should leave the event loop responsive: concurrent pings and light tool calls should stay near their ~1ms baseline instead of st
- [ ] **D65** [minor] A single limit=100 search evicts the entire response cache (entry-count cap 100 is consumed by per-result snippet_render entries)
  - Root cause: openzim_mcp/defaults.py:30 (CacheDefaults.MAX_SIZE = 100) interacting with per-result snippet_render:v1 inserts at openzim_mcp/zim/content.py:349-365 (M31); count-cap eviction fires at openzim_mcp/cache.py:391 long before the 64MB byte budget
  - Acceptance: The 64MB max_bytes budget is documented as the memory bound ('64 MB keeps memory bounded... without measurably degrading hit rate for typical workloads', defaults.py), but the max_size=100 entry cap silently dominates: a single documented, supported call (limit up to 500 for plain fulltext) should n

**Per-defect cycle (repeat for every defect above, in packet order):**

- [ ] Step 1: Read the packet entry (observed/expected/cause/repro) and the cited source.
- [ ] Step 2: Write the failing test in `tests/test_v3_field_fixes_runtime.py` asserting the `expected` behavior; run `uv run pytest tests/test_v3_field_fixes_runtime.py -x -q` and confirm it FAILS for the defect's reason.
- [ ] Step 3: Implement the minimal fix at the root cause site.
- [ ] Step 4: Re-run the test file — PASS; run the module's existing tests (e.g. `uv run pytest tests/ -q -k <module>`) — no regressions.
- [ ] Step 5: Where the defect is corpus-visible, re-run the packet's repro via the harness against YOUR worktree and confirm the observed behavior is gone.
- [ ] Step 6: `uv run pre-commit run --files <changed>`; fix what it flags.
- [ ] Step 7: Commit (`fix: <what/why>` or `docs: ...`), message body cites the defect_id.

---

### Task 9: sequential merge into `fix/v3-field-defects`

**Steps:** merge each workstream branch in this order (most-central files first): structure, content, simple, search, errors, runtime, protocol, http. After each merge: resolve conflicts preserving BOTH fixes, run `uv run pytest -x -q`. Final: `uv run pre-commit run --all-files`.

### Task 10: full re-verification

**Steps:** with the main checkout on `fix/v3-field-defects`, re-run all 65 original repros (they reference the main checkout path verbatim) and confirm each defect's observed behavior is gone; re-run the full suite; diff live-test results against main's baseline (3 pre-existing failures). Any still-broken defect goes back to a fix round before the PR.

### Task 11: PR

**Steps:** push `fix/v3-field-defects`; open one PR titled `fix: resolve the v3.0.0 field-test defect sweep`; body maps defect_id -> commit, notes the SDK-owned upstream issues (session-mint on rejected sessionless HTTP requests; stdio silent drops if patched via sdk_compat), and links the field report artifact. Do not merge — required review is self-unsatisfiable; the owner merges with `--admin`.
