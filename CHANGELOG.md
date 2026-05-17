# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — post-a15 beta-test sweep — 7 live-Wikipedia defects (D4 / D5 / D6 / D7 + P4-D1 / P4-D2 / P4-D3)

The multi-pass live sweep of a15 against
`wikipedia_en_all_maxi_2026-02.zim` (~118 GB, ~27.2 M entries) ran
across five passes. Pass 1 surfaced four user-facing defects (D4 in
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
three more defects (P4-D1 / P4-D2 / P4-D3) — each one fixed in
this commit. Pass 5 re-tested every fix and audited the regression
shape; zero new defects.

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

### Tests

- **`tests/test_post_a15_beta_fixes.py`** — 55 regression tests
  pinning all seven defects. Each defect gets:
  - The fix-case test (Mercury body has no misleading trailer;
    "could you tell me about X" parses topic=X; "find article titled
    M/Title" returns redirect; `_build_walk_result` exposes the
    zero-count field; `suggestions for` triggers the missing-arg
    guard; `could you tell me about X then list namespaces` is
    detected as chained; `walk namespace AB` returns the missing-
    namespace error).
  - Negative self-audit cases (Berlin keeps its disambig-twin
    footer; non-modal queries unchanged; lowercase a/b not
    redirected; `namespace_entry_count` omitted when caller passes
    None; legitimate `suggestions for forest` still captures the
    prefix; non-chained `could you tell me about X` not tripped by
    the chain detector; `walk namespace c` lowercase still works).
  - Cross-defect probes (Java disambig body suppresses
    `disambig_twin_path` footer too).

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
  `compact: bool = False` and thread it through. Documented decision
  in `docs/v2/adr-001-compact-plumbing.md`; Phase F decides whether
  to propagate further.
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
See [docs/superpowers/specs/2026-05-08-v2-phase-b-response-contract-design.md](docs/superpowers/specs/2026-05-08-v2-phase-b-response-contract-design.md)
for the full design.

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
