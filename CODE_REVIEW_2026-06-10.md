# End-to-End Codebase Review — openzim-mcp

**Date:** 2026-06-10 · **Scope:** full repository at commit `1b24125` (v2.4.0)

Conducted by a multi-agent review: 13 specialized reviewers (7 per-subsystem correctness, plus security, concurrency, performance, MCP API-design, test-suite, and CI/packaging auditors), every medium+ finding independently adversarially verified against the actual code (most reproduced by execution), 4 opportunity scouts, a repo health check, and a completeness critic. 76 agents, ~6M tokens.

## Health gates

- **Lint:** PASS. flake8: no findings; isort --check-only: clean; black --check: "259 files would be left unchanged."
- **Typecheck:** PASS. mypy openzim_mcp: "Success: no issues found in 74 source files."
- **Tests:** PASS. `uv run pytest -q`: 2966 passed, 217 skipped, 41 deselected (live-marked tests excluded by addopts) in 38.48s. Zero failures/errors. Full suite fit in a single run; no chunking required.
- **Coverage:** Fresh coverage produced this run (coverage.xml + htmlcov written): TOTAL 86% (9991 statements, 1381 missed). Five least-covered source modules: (1) openzim_mcp/server_state.py 18% (114 stmts, 94 missed), (2) openzim_mcp/zim/content.py 58% (504 stmts, 210 missed), (3) openzim_mcp/**main**.py 67% (trivial: 3 stmts, 1 missed), (4) openzim_mcp/zim/archive.py 71% (438 stmts, 126 missed), (5) openzim_mcp/zim/search.py 76% (1087 stmts, 263 missed). Next lowest substantive modules: zim/namespace.py 77% and async_operations.py / main.py at 78%.

## Confirmed findings

56 findings survived adversarial verification: 15 high, 34 medium, 7 low. 1 finding was refuted and removed. An additional 50 low-severity observations (not adversarially verified) are listed at the end.

### High severity

#### H1. CI bandit step discards real findings by overwriting the report with an empty one

`.github/workflows/test.yml:211` · security · found by ci-packaging

Lines 211 and 213 run `uv run bandit -r openzim_mcp -f json -o bandit-report.json || echo '{"results": [], "errors": []}' > bandit-report.json` (and the same pattern for SARIF). Bandit exits 1 whenever it finds ANY issue, and `-o` has already written the real report — so the `|| echo` fallback then clobbers the report containing findings with an empty one. Verified locally: bandit currently exits 1 with 6 findings (B110/B112/B101) on openzim_mcp, meaning every CI run today replaces both reports with fabricated empty ones. Consequences: the 'Generate security scan summary' step (line 243) always prints '[OK] No security issues found by Bandit', the SARIF uploaded to the GitHub Security tab (line 215) is always empty, and the uploaded security-reports artifact contains no data — the scan is silently neutered exactly when it has something to say. Note bandit is also invoked without `-c pyproject.toml`, so the [tool.bandit] config (B101 skip) never applies here.

**Suggested fix:** Use `bandit ... --exit-zero -f json -o bandit-report.json` (or capture the exit code and only write a placeholder when the report file is genuinely missing), and pass `-c pyproject.toml` so the project bandit config applies. Decide explicitly whether findings should fail the job instead of masking them.

**Verification:** Reproduced exactly: running the CI command verbatim, bandit exits 1 with 6 findings (B101 x2, B110, B112 x3) because no `-c pyproject.toml` is passed (bandit log shows `profile exclude tests: None`, so the B101 skip never applies), and the `|| echo '...' > bandit-report.json` fallback then overwrites the real report — the final file is literally `{"results": [], "errors": []}`. Consequently the summary step's jq count is 0 ("[OK] No security issues found"), the SARIF uploaded to GitHub Security is the fabricated empty one, and the artifact contains empty reports. The workflow's own comment (lines 223-231) admits this same `|| echo` fallback pattern previously neutered the safety step, yet it

#### H2. Chain detector falsely rejects names containing middle initials or abbreviations

`openzim_mcp/chain_detection.py:305` · correctness · found by title-chain

The sentence-period connector (line 55, `\s*\.\s+(?=[A-Z])`) plus the right-promote branch turns ordinary names with internal periods into hard 'Chained Operations Detected' rejections. The pass-2 guard `cls._is_substantive_topic(left_bare)` (line 305) was designed to block abbreviation splits like 'Dr. Strange' where left_bare is the 1-2 char abbreviation itself, but `_is_substantive_topic` returns True for ANY multi-token string (line 908-909), so any lead with words before the abbreviation passes. Verified live via the real dispatch path (simple_tools.py:592 passes the raw cased query): 'tell me about Franklin D. Roosevelt' -> rejected with ops `tell me about Franklin D` / `tell me about Roosevelt`; same for 'John F. Kennedy', 'Mount St. Helens', 'the St. Louis Cardinals'. The user gets a chain rejection instead of the article for completely normal single-topic input (middle initials are pervasive in biographical queries).

**Suggested fix:** Before promoting on the period connector, check the last token of `left_bare`: if it is a 1-2 character token (an initial/abbreviation immediately preceding the period, e.g. 'D', 'F', 'St', 'Mt', 'Jr', 'Dr'), skip the split. Alternatively require the period connector to be preceded by a token of >=3 chars that is not a known abbreviation.

**Verification:** Confirmed by executing the real entry point: handle_zim_query("tell me about Franklin D. Roosevelt") returns a hard "Chained Operations Detected" rejection with ops `tell me about Franklin D` / `tell me about Roosevelt`; same for "John F. Kennedy", "Mount St. Helens", and "the St. Louis Cardinals". The period connector (chain_detection.py:55) splits at the middle initial, and the line-305 guard_is_substantive_topic(left_bare) passes because lines 907-909 return True for any multi-token string ("Franklin D"), so the abbreviation guard only protects abbreviation-first titles like "Dr. Strange". The MCP tool (tools/zim_query.py:117) passes the raw cased query with no upstream normalization, an

#### H3. _build_sections duplicates and misattributes content by walking both div and p

`openzim_mcp/content_processor.py:552` · correctness · found by content

_build_sections iterates soup.find_all(["h1".."h6", "p", "div"]) and_append_section_content adds element.get_text() for every p AND every div. Because a div's get_text() includes all descendant text, nested containers count the same prose multiple times. Verified: '<h2>History</h2><div><div><p>Berlin was founded in the 13th century.</p></div></div>' yields content_preview 'Berlin was founded in the 13th century. Berlin was founded in the 13th century. Berlin was founded in the 13th century.' and word_count 21 instead of 7. Worse, find_all returns a wrapper div BEFORE the headings nested inside it, so a container div holding the whole article body dumps every later section's text (including heading text, e.g. 'Section Aalpha text') into the section preceding the wrapper. Nested divs / content wrappers are near-universal in mwoffliner and ZIMIT HTML, so the sections[] previews and word counts returned by get_article_structure (and the per-section summaries compact_structure_payload derives from content_preview) are wrong on realistic input.

**Suggested fix:** Skip elements whose ancestor is also collected, e.g. in the p/div branch do `if element.find_parent(["p", "div"]) is not None: continue` (count only outermost blocks), or collect text only from direct NavigableString/inline children of each div, and exclude text that belongs to a heading that appears later in document order.

**Verification:** Confirmed empirically by running the project's own _build_sections (content_processor.py:552-570): the nested-div example produces the exact claimed triple-duplicated preview and word_count 21 instead of 7, because _append_section_content adds get_text() for both each div and the p inside it. The wrapper-div misattribution also reproduces: a div preceding its nested headings dumps all later sections' text ('Section Aalpha text\nSection Bbeta text') into the prior section. The caller's only preprocessing strips script/style/footer/figure-type selectors (defaults.py:174), not content wrapper divs, and the corrupted sections[] flow into get_article_structure output and compact_renderers' per-se

#### H4. Empty OPENZIM_MCP_AUTH_TOKEN silently disables HTTP authentication

`openzim_mcp/http_app.py:119` · security · found by security

Authentication on the HTTP transport can be fully bypassed with a trivially-guessable credential when the operator sets an empty auth token. I verified empirically: `OPENZIM_MCP_AUTH_TOKEN=""` parses to `SecretStr('')` (not None) because `auth_token: Optional[SecretStr]` in config.py:365-371 has no min-length/non-empty validator. Two things then go wrong: (1) `check_safe_startup` computes `has_token = getattr(config, "auth_token", None) is not None` (http_app.py:119) which is True for SecretStr(''), so a non-loopback bind is permitted with no refusal and no warning (line 120 condition `not is_localhost and not has_token` is False). (2) In `BearerTokenAuthMiddleware.__init__`, `self._expected = token.get_secret_value()` becomes `""` (line 206). The `if self._expected is None` fast-path (line 233) is NOT taken for an empty string, so dispatch proceeds to `hmac.compare_digest(token, self._expected)` (line 251). I confirmed that a request with header `Authorization: Bearer` yields `scheme='Bearer'`, `token=''`, and `hmac.compare_digest('', '') == True` → the request authenticates. Net effect: the server appears auth-protected (passes safe-startup, advertises Bearer challenge), is exposed on a public interface, yet accepts anyone who sends an empty bearer token.

**Suggested fix:** Reject empty/whitespace auth tokens at config load (add a field_validator on auth_token that raises if the secret value is blank), and/or in check_safe_startup compute has_token from the stripped secret value, and in the middleware treat an empty expected token as misconfiguration (refuse to start rather than authenticate everyone).

**Verification:** Empirically confirmed all three links in the venv: OPENZIM_MCP_AUTH_TOKEN="" loads as SecretStr('') (not None) since config.py has no validator on auth_token and main.py never normalizes it; check_safe_startup at http_app.py:119-120 computes has_token=True (SecretStr('') is not None), so a non-loopback bind (host='0.0.0.0') passes with no refusal and no warning; BearerTokenAuthMiddleware sets _expected='' so the `is None` fast-path is skipped and a request with header `Authorization: Bearer` yields scheme='Bearer', token='', and hmac.compare_digest('','')==True, authenticating the request. The server thus appears auth-protected (issues 401 Bearer challenges) yet accepts an empty bearer toke

#### H5. Missing word boundary after (?:in|within) truncates filtered-search queries at any 'in'-prefixed word

`openzim_mcp/intent_parser.py:170` · correctness · found by intent

_extract_filtered_search's pattern ends with \s+(?:in|within) with no trailing \b, and the lazy ({_QUOTE_NOT}+?) capture stops at the earliest match. Any whitespace-preceded word starting with 'in' (internet, insulin, India, industry, information...) terminates the capture early. Verified by execution: 'search for history of the internet in namespace A' yields {'query': 'history of the', 'namespace': 'A'} and 'search for protein insulin in namespace A' yields {'query': 'protein'}. The corrupted query is then searched silently in the requested namespace, returning wrong results with no signal.

**Suggested fix:** Add a word boundary and require the filter keyword: r"...\s+(?:in|within)\b(?=\s+(?:namespace|type)\b)" so the capture only stops at the actual 'in namespace'/'in type' anchor.

**Verification:** Confirmed by execution against the real code: the pattern at openzim_mcp/intent_parser.py:169-170 ends with `\s+(?:in|within)` (no trailing `\b`), and the lazy `({_QUOTE_NOT}+?)` capture stops at the first whitespace-preceded 'in'-prefixed word — 'search for history of the internet in namespace A' yields query='history of the' and 'search for protein insulin in namespace A' yields query='protein', both via the full parse_intent pipeline. The handler (simple_tools.py:1833, `search_query = params.get("query", query)`) consumes the truncated query with no validation, silently returning wrong namespace-filtered results; even quoting the query ('search for "history of the internet" in namespace A

#### H6. Last-keyword anchor truncates entry titles containing of/for/in/from/to

`openzim_mcp/intent_parser.py:297` · correctness · found by intent

_extract_entry_path_keyworded takes the text after the LAST occurrence of article|entry|page|of|for|in|from|to (lines 291-297). These keywords are extremely common inside article titles, so the tail is silently truncated: verified by execution, _extract_entry_path_keyworded('get article Lord of the Rings', p) yields {'entry_path': 'the Rings'} (anchors on the title-internal 'of'); 'get article History of France' likewise yields 'France'. Downstream title resolution then fuzzy-matches the wrong article with no error — exactly the 'silent-fall-through failure mode' the function's docstring claims to have eliminated. This feeds get_article, structure, links, toc, and summary intents.

**Suggested fix:** Prefer the explicit object keywords (article|entry|page) over prepositions when both are present, or only anchor on a preposition that directly follows the intent verb (e.g. 'structure of', 'links in') instead of the last preposition anywhere in the query.

**Verification:** Reproduced by execution: intent_parser.py:291-297 anchors on the LAST of article|entry|page|of|for|in|from|to, so IntentParser.parse_intent('get article History of France') yields entry_path 'france' and 'get article Lord of the Rings' yields 'the rings'; no caller corrects it. Downstream_resolve_natural_language_path (simple_tools.py:1359) fuzzy-promotes the truncated tail at min_score=0.8, and is_strong_title_match accepts exact token equality, so 'france' silently resolves to the France article instead of History of France — wrong content with no error, feeding get_article/structure/links/toc/summary. The only test with an of-containing title (test_simple_tools.py:4504) passes solely bec

#### H7. Binary extractor captures keyword 'from' as entry path for its own documented phrasing

`openzim_mcp/intent_parser.py:337` · correctness · found by intent

The fallback pattern in _extract_binary puts anchor keywords (content|data|entry) and connector words (from|of|for) in the same alternation: r"(?:content|data|entry|from|of|for|pdf|image|video|audio|media)\s+['\"]?([A-Za-z0-9_/.-]+)". re.search matches at the leftmost position, so for the comment's own example 'get binary content from I/image.png' (line 335) the alternation matches 'content' first and the capture group grabs the next token 'from'. Verified by execution: _extract_binary('get binary content from I/image.png', p) yields {'entry_path': 'from'} instead of 'I/image.png'. Every 'get binary content from <path>' / 'binary content for <path>' query fetches a bogus entry.

**Suggested fix:** Either require the connector after the anchor (e.g. r"(?:content|data|entry)\s+(?:from|of|for)\s+(['\"]?)([A-Za-z0-9_/.-]+)\1") or make the capture reject further keyword tokens; at minimum add a guard like the suggestions extractor's bare-'for' check so connector words are never returned as the path.

**Verification:** Confirmed by execution: _extract_binary('get binary content from I/image.png', p) yields {'entry_path': 'from'} because re.search matches the leftmost alternative 'content' and the capture group grabs the connector word 'from' (also reproduced for 'binary content for X', 'raw data from X', and even 'get pdf from X' → 'from')._handle_binary in simple_tools.py only guards against a missing entry_path, so the truthy 'from' is passed straight to get_binary_entry, fetching a bogus entry; tests only assert intent classification for these phrasings (the sole unquoted entry_path test uses 'extract pdf I/document.pdf', which lacks a connector word), so nothing pins or rescues the behavior. Severity

#### H8. 'info about X' / 'details of X' always routes to archive metadata, making tell_me_about's info-branch dead code

`openzim_mcp/intent_parser.py:738` · correctness · found by intent

Patterns at lines 738-739 map (metadata|info|details?)\s+(for|about|of) and info\s+about to intent 'metadata' at confidence 0.9/specificity 9, which always beats the tell_me_about pattern (0.85/7, lines 873-881) that also lists info(rmation)?\s+(about|on). Verified by execution: parse_intent('info about Python'), parse_intent('info about the Apollo program') and parse_intent('details of the French Revolution') all return ('metadata', {}, 0.9). With no .zim filename in the query the dispatcher auto-selects an archive and returns ZIM-file metadata instead of topic content. This contradicts the module's own documentation:_extract_tell_me_about's docstring (line 453) lists 'info about the Apollo program' -> topic, and the_METADATA_FILENAME_RE comment (line 680) explicitly states 'info about Python' is a topic, not a file. Note 'information about X' and 'info on X' DO route to tell_me_about, so identical asks get opposite handling depending on word choice.

**Suggested fix:** Restrict the metadata patterns to file-shaped targets (e.g. require a .zim token or words like 'this file/archive' after the connector, leveraging _METADATA_FILENAME_RE), letting bare 'info about <topic>' / 'details of <topic>' fall through to tell_me_about.

**Verification:** Confirmed by execution: parse_intent('info about Python'), 'info about the Apollo program', and 'details of the French Revolution' all return ('metadata', {}, 0.9) because the metadata patterns (intent_parser.py:738-739, score 0.90) deterministically beat the tell_me_about pattern (lines 873-881, score 0.805) in _select_best_match, while 'information about X'/'info on X' route to tell_me_about. Nothing rescues it downstream: Tier-1 rewrites don't touch the phrasing, and the dispatcher (simple_tools.py:648-691) auto-selects an archive and _handle_metadata returns get_zim_metadata() — ZIM-file metadata instead of topic content. The code contradicts its own docs (_extract_tell_me_about docstrin

#### H9. search_all rerank passthrough silently truncates results and zeroes out later archives

`openzim_mcp/rerank.py:217` · correctness · found by synthesize

_maybe_rerank_search_all calls _redistribute_reranked_hits(per_file, reranked_tagged) unconditionally (rerank.py:217), BEFORE checking whether reranking actually happened (the 'rerank_score' check is at line 218, after mutation). BGEReranker.rerank's skip paths return candidates[:top_k] with NO rerank_score: the short-query gate (ml/reranker.py:140, fires for any query with fewer than min_query_tokens=4 words — i.e. most real queries like 'french revolution') and the inference-failure fallback_rerank_passthrough (ml/reranker.py:57). top_k here is final_top_k=10. _flatten_archive_hits orders candidates by archive index, so with 3+ archives at the default limit_per_file=5 (simple_tools.py:3038), a 1-3-word query slices the flattened list to the first 10 hits IN ARCHIVE ORDER — no relevance ordering — and _redistribute_reranked_hits then overwrites the third-and-later archives with results=[] and has_hits=False (rerank.py:180-182). The user is told those archives had no hits even though Xapian found hits, purely because the reranker was installed but skipped. Contrast with the synthesize path, which correctly guards: synthesize.py:1691 returns inputs unchanged when reranked_envelopes[0] lacks 'rerank_score'.

**Suggested fix:** Check `reranked_tagged and 'rerank_score' in reranked_tagged[0]` BEFORE calling _redistribute_reranked_hits; on passthrough, track_RERANKER_SKIPPED_PASSTHROUGH and return per_file unmodified (mirroring_maybe_rerank_synthesize_passages in synthesize.py).

**Verification:** Confirmed by reading the code and by empirical reproduction: rerank.py:217 calls _redistribute_reranked_hits before the rerank_score check, and BGEReranker.rerank's skip paths (short-query gate at ml/reranker.py:140 with default min_query_tokens=4, and _rerank_passthrough at reranker.py:57) return candidates[:top_k] in archive order without rerank_score. Running the real code with 3 archives x 5 hits and the 2-token query "french revolution" produced telemetry 'reranker_skipped.passthrough' while the third archive's 5 Xapian hits were silently zeroed out (results=[], has_hits=False) and omitted from the rendered output; the synthesize path (synthesize.py:1691) correctly guards against exactl

#### H10. HTTP transport rejects all MCP requests (421) on any non-loopback deployment without OPENZIM_MCP_ALLOWED_HOSTS

`openzim_mcp/server.py:139` · correctness · found by server

TransportSecuritySettings is only passed to FastMCP when `config.transport == "http" and config.allowed_hosts` (line 139). When allowed_hosts is empty, FastMCP is constructed at line 146 WITHOUT a `host` kwarg, so the SDK's auto-enable check (mcp/server/fastmcp/server.py:178, verified in installed SDK 1.27.0) sees its default host "127.0.0.1" — not config.host — and installs DNS-rebinding protection with allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"]. The real bind host is only mirrored into settings later (http_app.py:354), after the security settings are frozen. Consequence: a server bound to 0.0.0.0 with an auth token, or with OPENZIM_MCP_INSECURE_DISABLE_AUTH=1 (the documented Docker-bridge/isolated-LAN mode in config.py:375-381, where clients connect by IP), passes check_safe_startup but then 421-rejects every single MCP request because Host: <lan-ip>:8000 is not in the loopback allowlist. /healthz and /readyz are plain Starlette routes that bypass the session manager and still return 200, so the deployment looks healthy while being completely unusable. The allowed_hosts config description (config.py:391-402) frames the setting as reverse-proxy/Tailscale-only, so operators of direct-IP deployments have no documented reason to set it, and the wildcard rejection (config.py:480) prevents working around dynamic container IPs.

**Suggested fix:** Always construct TransportSecuritySettings when transport == "http": include loopback entries plus the configured bind host (and its :* variant) when config.host is non-loopback, or pass host=config.host to the FastMCP constructor so the SDK auto-enable decision is made against the real bind address. Add a startup error/warning when host is non-loopback and the effective Host allowlist is loopback-only.

**Verification:** Reproduced end-to-end: with transport=http, host=0.0.0.0, a valid auth token, and allowed_hosts empty (default), check_safe_startup passes but POST /mcp with Host: 192.168.1.50:8000 and a valid bearer token returns 421 "Invalid Host header", while /healthz and /readyz return 200 with the same Host — because server.py:146 constructs FastMCP without a host kwarg, so the SDK 1.27.0 auto-enable check (fastmcp/server.py:178) sees its default "127.0.0.1" and installs a loopback-only allowlist before http_app.py:354 mirrors the real bind host. The only inaccuracy in the claim is that the website deployment guide's troubleshooting section does document the 421-symptom-to-ALLOWED_HOSTS remedy (includ

#### H11. Search-tail overwrite reverts query-rewrite, param-leak strip, and quote strip for all verb-prefixed searches

`openzim_mcp/simple_tools.py:426` · correctness · found by simple-tools

In `_normalize_and_validate_query_params`, for intent=="search" the code recomputes the search tail from the ORIGINAL raw query (`tail = self._search_query_tail(query)` at line 410) and then unconditionally overwrites the parser's extracted value with it (`params["query"] = tail` at line 426). `parse_intent` runs the Tier-1 rewrites (Rule 1 lowercase, Rule 2 misspelling map, param-leak strip, politeness strip, quote strip) BEFORE extraction, so the overwrite silently undoes them. Verified end-to-end with a mocked backend: `search for photosythesis` calls `search_zim_file(..., 'photosythesis', ...)` even though parse_intent produced `{'query': 'photosynthesis'}`; `search for biology limit=10` searches the literal string 'biology limit=10' (re-introducing the leaked parameter the post-a23 P1-D3 strip removed); `search for "quantum mechanics"` searches with the surrounding quotes the extractor had stripped. The query-rewrite telemetry counter (`query_rewrite.misspelling`) still increments in `_run_query_rewrite_probes`, so operators see the rewrite as engaged while the backend actually searched the unrewritten term.

**Suggested fix:** Only use the recomputed tail for the empty-tail guard (the P1-D8 purpose). When the tail is non-empty, keep the extractor's `search_q` (which already went through the rewrite pipeline) instead of overwriting with the raw tail — i.e. delete lines 425-426 and always assign `params["query"] = search_q` unless `search_q` still contains the verb prefix.

**Verification:** Confirmed end-to-end with a mocked backend: _normalize_and_validate_query_params (simple_tools.py:410,425-426) recomputes the tail from the raw query via _search_query_tail and unconditionally overwrites the parser's cleaned params["query"], and_handle_search (line 2013) passes it to the backend uncleaned — 'search for photosythesis' searches 'photosythesis' (despite parse_intent producing 'photosynthesis'), 'search for biology limit=10' searches the literal 'biology limit=10', and 'search for "quantum mechanics"' searches with quotes intact. The query_rewrite.misspelling telemetry still increments via_run_query_rewrite_probes (line 606), which runs on the raw query before the overwrite. O

#### H12. Cached search payload mutated in place after cache read — cache poisoning across surfaces plus cross-thread race

`openzim_mcp/simple_tools.py:2240` · concurrency · found by concurrency

OpenZimMcpCache.get() returns the stored object by reference (cache.py:311, `return entry.value`) and search_zim_file_data caches the very dict it returns (zim/search.py:615). The compact zim_query path then mutates that shared dict in place: _splice_title_match_into_search (simple_tools.py:2165-2247) reassigns `payload["results"]` (lines 2191, 2218, 2240), prepends a synthetic row `{"snippet": "(canonical title match)"}` while truncating off a real BM25 hit, and mutates the nested cached `page_info` dict (line 2245, `page_info["returned_count"] = len(spliced)`). The docstring even says "Mutates and returns payload". Consequences: (1) every subsequent cache hit on `search_v2b:{path}:{query}:{limit}:{offset}` — including the advanced zim_search tool (tools/zim_search.py:242) and the legacy search_zim_file text path (zim/search.py:398), which the code explicitly promises keep "byte-identical output, including the original BM25 ranking" (simple_tools.py:2120-2124) — receives the spliced/demoted/truncated payload containing a fabricated result row the backend never produced, with one real hit permanently dropped from the cached entry for the TTL; (2) two concurrent zim_query requests for the same query run in separate asyncio.to_thread workers and mutate the same dict concurrently with no lock (one thread swaps results/page_info while another renders them via _format_search_text), producing torn responses. The cache's internal lock does not help because the mutation happens on the returned value outside the cache.

**Suggested fix:** Never hand the cached object out by reference when callers may mutate it: deep-copy on cache.get() (or copy.deepcopy in search_zim_file_data before returning a hit), or make_splice_title_match_into_search operate on a copied payload ({**payload, "results": [...], "page_info": {...}}) the way_maybe_rerank_compact already does.

**Verification:** Confirmed end-to-end: cache.py:311/360 store and return values by reference; zim/search.py:615 caches the exact dict returned (cold and warm paths); _splice_title_match_into_search (simple_tools.py:2191/2218/2240/2245) mutates that shared dict on the default zim_query path (compact=True, offset=0 per tools/zim_query.py:54), inserting a synthetic "(canonical title match)" row, dropping a real BM25 hit, and mutating nested page_info — poisoning the cached entry for the TTL. Same-key consumers (compact=False zim_query at simple_tools.py:2127, tell_me_about at 2583 with identical limit=3/offset=0, zim_search at tools/zim_search.py:242) then serve the spliced payload, violating the explicit byte-

#### H13. zim_get batch branch silently ignores `view` despite docs saying batch supports it

`openzim_mcp/tools/zim_get.py:119` · correctness · found by api-ux

zim_get_description.md line 13 says "Batch: pass `entry_paths` (list of strings) + optional `view`", and the module docstring (lines 16-17) repeats "Batch: requires `entry_paths`. Optional `view`...". But the batch branch calls `ops.get_entries_data(entries, max_content_length=..., compact=...)` (lines 119-123) and `get_entries_data` has no view parameter (async_operations.py:216-228). A call like `entry_paths=[...], view="summary"` is neither honored nor rejected by `_validate_branch_combination` — the model gets full article bodies while believing it requested summaries, at much higher token cost.

**Suggested fix:** Either thread `view` through to the batch data layer, or reject `entry_paths` + `view != "full"` in `_validate_branch_combination` with an `invalid_path_combination` error, and fix the description.

**Verification:** Confirmed: zim_get.py:119-123 calls ops.get_entries_data(entries, max_content_length=..., compact=...) without view; get_entries_data has no view parameter at either layer (async_operations.py:216-228, zim/content.py:666-672) and always fetches full bodies via _get_zim_entry_from_archive._validate_branch_combination (zim_get.py:152-216) locks view='full' only for binary (line 180) and main_page (line 204) — batch + view="summary"/"toc"/"structure" passes validation and is silently ignored, contradicting zim_get_description.md:13-14 and the module docstring (lines 15-16) which advertise optional view for batch. No test covers batch + non-full view (tests/test_zim_get.py only tests binary/mai

#### H14. zim_search accepts and documents `cursor` but never uses it in any mode

`openzim_mcp/tools/zim_search.py:75` · correctness · found by api-ux

The `cursor` parameter (line 75) is documented in zim_search_description.md line 46 as "Phase B cursor pagination handle; overrides `offset` when set", and the data layer really does emit `next_cursor` handles (zim/search.py:738 encodes tool="search_zim_file"; zim/search.py:1425 encodes tool="search_with_filters"). But the handler never decodes the cursor: fulltext mode does not pass it to `_handle_fulltext_mode` (lines 139-150), suggest mode ignores it, and `_handle_title_mode` receives it (line 256) but its body (lines 271-329) never references it. An LLM that follows the documented loop — take `next_cursor` from a SearchResponse, pass it back as `cursor` — silently gets page 1 again, an unbreakable pagination loop with no error.

**Suggested fix:** Decode the cursor via `_common.decode_cursor_state` (expected_tool "search_zim_file"/"search_with_filters") and project its `o`/`ai`/`q` into the data-layer call, as zim_browse and zim_links already do; or remove the parameter and the description text and stop emitting next_cursor for this tool.

**Verification:** Confirmed: zim_search accepts `cursor` (zim_search.py:75) and the description (zim_search_description.md:46) documents it as overriding `offset`, but no mode uses it — fulltext doesn't forward it (lines 139-150), suggest ignores it, and _handle_title_mode receives it (line 256) but its body (271-329) never references it; `decode_cursor_state` is only called from zim_browse.py and zim_links.py. The data layer really emits live `next_cursor` handles (zim/search.py:738 and 1425) directly in the returned payload, so a client following the documented loop silently gets page 1 again with the same next_cursor — an unbreakable pagination loop with no error, and no test pins cursor behavior for zim_s

#### H15. Title-promotion probe fan-out: find_entry_by_title_data is uncached, re-opens the archive per probe, and can trigger ~10k-lookup typo sweeps per failed probe

`openzim_mcp/zim/search.py:2913` · performance · found by performance

find_entry_by_title_data has no response cache and opens the archive fresh on every call (zim/search.py:2913 `with _zim_ops_mod.zim_archive(file_path)`), constructing a new SuggestionSearcher each time. A single zim_query fans out to it many times: the query-rewrite title_probe (simple_tools.py:222-237, per mapped token / per the-prefixed query / per X-of-Y shape), promote_topic_via_title_index passes 0-3 (topic_preprocessing.py:97,163,171,181 — up to 4 tails + ~4n sliding windows for an n-token topic via iter_query_windows), the Z3/Z4 discriminator probes (title_promotion.py:677 and 835, one probe per non-stop-word topic token per candidate), and the synthesize promotion path (synthesize.py:1050, 1074-1075, 1144-1145, 1176-1178), which re-opens archives via find_title_match even though open handles are already in scope in `archives`. Additionally, any probe string >=4 chars (FUZZY_TITLE_MIN_QUERY_LEN=4, defaults.py:145) that yields zero suggestions falls into the typo sweep (zim/search.py:3023, gated only on no score>=0.7 hit):_typo_variants generates ~26*(n+1) insertions + ~25*n substitutions (zim/search.py:2567-2592), each probed via_find_entry_fast_path's up-to-11 lookups (zim/search.py:2477-2503) — ~10k+ index probes for a single failed multi-word window. A prose-y tell_me_about/synthesize topic can thus cause dozens of archive opens plus several typo sweeps in one request.

**Suggested fix:** Memoize find_entry_by_title_data results per (archive stat token, title) in the existing response cache; pass already-open archive handles into the promotion/probe layers instead of re-opening by path; restrict the typo sweep to single-token probes (multi-word windows from iter_query_windows are never single-edit typos).

**Verification:** Confirmed by code trace and live measurement: find_entry_by_title_data (zim/search.py:2913) is uncached and opens a fresh Archive per call, and the typo sweep (gated only by zero suggestions + len>=4, search.py:3023) walks the full ~26*(n+1)+25*n variant set with up to 11 lookups each. Running promote_topic_via_title_index on a realistic prose topic against the repo's real mini ZIM produced 26 archive opens, 22,685 fast-path probe calls (~200k index lookups), and 3.0-3.5 s wall time for a single request's promotion step — including 4 byte-identical duplicate backend probes between pass 1 and pass 3. This fires on the default zim_query/tell_me_about path (query_rewrite enabled, promotion trig

### Medium severity

#### M1. Release asset upload failures are swallowed, then the release is published anyway

`.github/workflows/release.yml:314` · ci · found by ci-packaging

In 'Upload assets to existing release': `gh release upload "$TAG_NAME" "$file" --clobber || echo "Warning: Failed to upload $filename"` — any upload failure (transient API error, auth issue) is converted to a warning and the step stays green. The next step 'Publish draft release' (line 343+) then flips the draft to published. The workflow's own comments (lines 320-329, 350-353) explain that under immutable releases the asset list is LOCKED at publish time — so a swallowed upload failure produces a permanently asset-less published release with a fully green pipeline, the exact rc0/rc1 empty-Releases failure mode the comments describe guarding against.

**Suggested fix:** Let the upload step fail on error (drop the `|| echo`), or track a failure flag and exit nonzero before reaching the publish step; optionally verify the expected asset count with `gh release view --json assets` before publishing.

#### M2. extract_infobox decomposes the matched node even when no KV rows were extracted, silently deleting content

`openzim_mcp/content_processor.py:862` · correctness · found by content

After the row loop, node.decompose() runs unconditionally and the function returns rows — even when rows == []. The KV loop only emits rows that pair a <th> with a <td>, so any infobox whose labels are <td class="infobox-label"> (common on non-Wikipedia wikis exported via zimit, older MediaWiki skins), or any non-table element matched by the broad '.infobox' / '.vcard' selectors (e.g. a div-based infobox or an hCard-classed block), produces zero rows yet is removed from the soup. In _render_soup_to_text (line 933) compact mode then renders neither the infobox markdown (kv_rows is empty) nor the original element — the content vanishes with no placeholder and no signal to the caller.

**Suggested fix:** Only decompose when rows were actually extracted (`if rows: node.decompose(); return rows` / otherwise `continue` to the next selector), and/or restrict the bare '.infobox'/'.vcard' selectors to 'table.infobox'/'table.vcard' so non-table matches are never consumed.

#### M3. Snippet truncation splits markdown links and defeats the highlight skip-protection

`openzim_mcp/content_processor.py:1063` · correctness · found by content

create_snippet truncates with snippet_text[:cap] before calling _highlight_terms. A cut landing inside a `[text](url "title")` construct (link soup is pervasive in html2text output since ignore_links=False) leaves a dangling unterminated link — verified output: 'The city of Berlin is documented in [History of Berlin](A/History_of_Berlin "...'. Because the link is now incomplete,_HIGHLIGHT_SKIP_RE (which requires a complete [..](..) unit) no longer protects it, so _highlight_terms bolds query terms inside the link text and URL — verified output: 'The city of **Berlin** is documented in [**History** of **Berlin**](A/History...'. This is exactly the malformed-markdown shape the skip-regex was added to prevent (per its own comment, bolding inside the link target breaks the URL). The post-highlight repair at line 1083 only fixes dangling '**', never dangling links.

**Suggested fix:** After each truncation, detect an unterminated trailing link (e.g. a final '[' whose matching '](...)' was cut) and either back the cut up to before the '[' or strip the fragment, mirroring the existing '**' repair; alternatively run _highlight_terms before truncating and make the length re-check link-aware.

#### M4. Error templates instruct the model to call tools that no longer exist (list_zim_files, get_server_health, get_server_configuration)

`openzim_mcp/error_messages.py:38` · error-handling · found by api-ux

The troubleshooting steps emitted on every enhanced error reference legacy tool names removed by the Phase F consolidation: `list_zim_files()` (line 38), `get_server_health()` (lines 50, 94, 120), `get_server_configuration()` (lines 60, 127). The v2 surface only exposes zim_query/zim_search/zim_get/zim_get_section/zim_browse/zim_metadata/zim_links/zim_health (tools/**init**.py), and simple mode exposes only zim_query. These templates are the standard error path for all 8 tools via `_create_enhanced_error_message` (server.py:184-220), so a model following the recovery steps will issue calls to nonexistent tools and get protocol-level unknown-tool errors instead of recovering.

**Suggested fix:** Update the step text to the Phase F names: `zim_health()` for server state and archive listing, `zim_health(zim_file_path=...)` for archive validation; in simple-mode deployments reference `zim_query("list available ZIM files")` instead.

#### M5. Security violations misrouted to the Permission error template

`openzim_mcp/error_messages.py:204` · error-handling · found by infra-core

get_error_config() runs message-pattern checks before the exception-type mapping, and the pattern at line 204 matches "access denied". The codebase's two primary security rejections both start with that phrase: security.py:145 raises OpenZimMcpSecurityError("Access denied - Path is outside allowed directories: ...") and security.py:206 raises "Access denied - Path resolves outside allowed directories: ...". Both are therefore routed to PERMISSION_ERROR_CONFIG ("Insufficient permissions to access the resource", "Try running with appropriate permissions") instead of the OpenZimMcpSecurityError entry in ERROR_CONFIGS (line 53), which is the template that actually explains the block ("Check for path traversal attempts (../ sequences)", "Use get_server_configuration() to see allowed directories"). The security-specific config is unreachable for the two main raise sites that produce it, and the guidance shown for a blocked path traversal is actively wrong (it tells the caller to escalate filesystem permissions). Confirmed flow: server.py:208 calls get_error_config(error) on the raw excepti…

**Suggested fix:** Check the exception type mapping for OpenZimMcpSecurityError before the generic "permission"/"access denied" substring heuristics (or exclude OpenZimMcpSecurityError instances from the pattern shortcut), so security rejections always render the security template.

#### M6. readyz endpoint performs blocking filesystem syscalls on the event loop

`openzim_mcp/http_app.py:151` · performance · found by concurrency

The async readyz handler calls os.path.isdir(d) and os.access(d, os.R_OK) directly (line 151) for each allowed directory. These are blocking stat-family syscalls executed on the event loop thread. The codebase itself documents that stat calls on these same allowed directories block on network-mounted filesystems and explicitly offloads identical work to threads for that reason (subscriptions.py:149-152 and 195-198 offload MtimeWatcher._scan via asyncio.to_thread). readyz is the endpoint orchestrators poll automatically; if an allowed directory sits on a hung NFS/SMB mount, each probe freezes the entire event loop — stalling all in-flight MCP traffic — for the duration of the uninterruptible stat, exactly the condition a readiness probe is meant to detect.

**Suggested fix:** Wrap the directory checks in await asyncio.to_thread(...) (optionally with a short asyncio.wait_for so a hung mount yields a fast 503 instead of a hang).

#### M7. Entry-path batch extractor has no left boundary, capturing 'd/or' from 'and/or'

`openzim_mcp/intent_parser.py:610` · correctness · found by intent

safe_regex_findall(r"[A-Za-z]/[\w\-./%]+", query) matches a single letter before '/' with no preceding boundary, so the last letter of a longer word qualifies. Verified by execution: _extract_get_zim_entries('get entries A/Foo and/or B/Bar', p) yields {'entries': ['A/Foo', 'd/or', 'B/Bar']} — the bogus 'd/or' entry is sent to the batch fetch. 'either/or', 'km/h', 'he/she' and URLs ('https://...' yields 's//...'-adjacent matches) produce the same false captures in otherwise valid batch queries.

**Suggested fix:** Anchor the namespace letter: r"[?<![A-Za-z0-9]](A-Za-z)/[\w\-./%]+" (negative lookbehind) so only standalone single-letter namespaces match.

#### M8. Apostrophes treated as quote delimiters break possessive titles in get_section and keyworded extractors

`openzim_mcp/intent_parser.py:650` · correctness · found by intent

_QUOTE_CHARS (line 64) includes ASCII and curly apostrophes, and _QUOTE_NOT excludes them from captures. In _extract_get_section both forms use ({_QUOTE_NOT}+?) for the section name, so a single possessive apostrophe makes the whole extraction fail: verified by execution,_extract_get_section("section Earth's atmosphere of Earth", p) yields {} — the handler then raises a missing-arg error for a perfectly valid query (section names with apostrophes are common). In _extract_entry_path_keyworded (line 270-271) a query containing two apostrophes is parsed as a quoted span: _extract_entry_path_keyworded("links in Murphy's law and Sod's law", p) yields {'entry_path': 's law and Sod'}.

**Suggested fix:** Require matching quote pairs of the same character (backreference, e.g. (['\"‘“])(.+?)\1-style with paired closers), or exclude apostrophes from the opening-quote class when not at a token boundary.

#### M9. 'complete' in the suggestions alternation hijacks 'complete X' phrasings into autocomplete

`openzim_mcp/intent_parser.py:803` · correctness · found by intent

The suggestions intent pattern includes the bare verb 'complete' at confidence 0.85/specificity 7, which outweighs get_article (0.75/5, even with the param boost capped at 0.85 — score 0.805 vs 0.71). The adjective 'complete' is far more common than the verb in archive queries. Verified by execution: parse_intent('get article complete works of Shakespeare') returns ('suggestions', {'partial_query': 'works of shakespeare'}, 0.85) — the user asked for an article and gets title autocompletion for the wrong string. Any 'complete list/guide/history of X' query is similarly misrouted.

**Suggested fix:** Drop 'complete' from the alternation or require a disambiguating object (e.g. complete\s+(?:this|the\s+(?:term|query|prefix))), keeping 'autocomplete'/'suggestions'/'hints' as the reliable cues.

#### M10. Rule-4 decomposition runs before politeness/param-leak strips, baking junk into the entity hint

`openzim_mcp/intent_parser.py:1199` · correctness · found by intent

parse_intent applies_apply_tier1_rewrites (including Rule 4 _decompose_x_of_y) at line 1199, then _strip_param_leaks (1211) and_strip_trailing_politeness (1216). For '<attr> of <entity>' queries the politeness/param suffix is part of the entity capture, and the rewrite to '<entity> <attr>' moves it mid-string where the end-anchored strips can no longer remove it. Verified by execution: parse_intent('population of berlin please') returns topic 'berlin please population' with decomposition_hint {'entity': 'berlin please', ...}; parse_intent('population of berlin limit=5') returns the cleaned topic 'berlin population' but a stale hint entity 'berlin limit=5'. simple_tools._resolve_tell_me_about_topic (line 2426-2435) prefers the hint entity as the lookup topic, so the title lookup runs on 'berlin please' / 'berlin limit=5'. These exact suffix classes are documented as occurring in live traffic (the post-a20/a23 sweeps that motivated the strips).

**Suggested fix:** Run _strip_param_leaks and_strip_trailing_politeness BEFORE _apply_tier1_rewrites (Rule 4 is the last tier-1 rule, so ordering the strips first is safe), or re-run the strips on the entity capture before emitting the hint.

#### M11. PathValidator security branches untested: encoded-traversal decode loop, TOCTOU recheck, path-length cap

`openzim_mcp/security.py:87` · security · found by tests

Coverage from the full suite shows security.py at 86% with precisely the security-control branches missed: line 87 — the multi-pass URL-decode loop (lines 82-87) that exists to catch %2e%2e/double-encoded traversal in file paths never iterates, because no test feeds an encoded path to PathValidator (tests/test_path_traversal_d12_v2a9.py exercises %2e%2e only against the separate _looks_like_path_traversal entry-path check in zim/content.py); line 206 — the validate_zim_file TOCTOU re-resolve rejection ('Path resolves outside allowed directories', the symlink-swap defense documented at lines 191-194) is never triggered; line 76 — the MAX_PATH_LENGTH (4096) buffer-exhaustion guard is untested (grep for 'Path too long' in tests/ returns nothing); lines 197-198 — resolve(strict=True) failure; line 250 — sanitize_input's empty-after-sanitization rejection (no test references allow_empty or 'Input is empty'); line 418 — the _CONTEXT_MAX_LENGTH truncation in sanitize_context_for_error. These are the exact code paths whose regression would silently weaken the server's path-containment guaran…

**Suggested fix:** Add tests: validate_path('%2e%2e%2fetc/passwd') and a double-encoded variant must raise OpenZimMcpSecurityError; a >4096-char path must raise 'Path too long'; create a .zim symlink, validate_path it, retarget the symlink outside the allowed dir, and assert validate_zim_file raises 'resolves outside'; sanitize_input('\x00\x01') must raise the empty-input error; a >1024-char context must be truncated with '...'.

#### M12. Rate limiter is constructed but never enforced anywhere — configured limits are silently inert

`openzim_mcp/server.py:103` · security · found by server

`self.rate_limiter = RateLimiter(config.rate_limit)` is created in **init**, but a repo-wide search shows `check_rate_limit` (rate_limiter.py:280) is never called from any tool, handler, middleware, or operation module — the only references outside rate_limiter.py are this construction and docstrings. The supporting machinery actively claims otherwise: request_context.py:4-11 says the ContextVar is "read by tool call sites that hand off to check_rate_limit", and the HTTP auth middleware sets client ids on every request (http_app.py:234, 262) specifically "so the rate limiter can isolate buckets per-token". Operators who configure OPENZIM_MCP_RATE_LIMIT__* (config.py:331, surfaced in the config hash at config.py:537-539) believe an abuse/DoS control is active when nothing is enforced. This looks like a regression from the Phase F tool-registration refactor (the legacy per-tool registration methods that presumably called it were deleted, per the comment at server.py:240-244).

**Suggested fix:** Call server.rate_limiter.check_rate_limit(operation=...) at the top of each registered tool handler (or in a shared decorator in tools/_common.py), returning a structured rate-limit error on rejection. Alternatively remove the limiter and its config surface so operators are not misled.

#### M13. zim_health report builders in server_state.py are 18% covered; tool tests mock them away

`openzim_mcp/server_state.py:45` · tests · found by tests

Full-suite coverage for server_state.py is 18% with lines 60-83, 102-115, 126-139, 149-155, 165-170, 181-233, 247-296 missed — i.e._check_directory_health, _append_cache_recommendations,_finalize_health_status, _build_health_report, and_build_configuration_report are essentially untested. tests/test_zim_health.py stubs the whole pipeline (its _patch_async_ops helper replaces get_health_data with AsyncMock at lines 34-43), so only the thin tool registration is checked. Notably,_check_directory_health's documented security property — 'Sanitize the path before it ever lands in user-visible warning / recommendation strings ... must not leak host topology' (lines 57-63) — and the inaccessible-directory/PermissionError status-degradation branches are verified by no test.

**Suggested fix:** Add direct unit tests for _build_health_report/_build_configuration_report using a real OpenZimMcpServer over a tmp_path config, including a missing/permission-denied directory case asserting the warning strings contain the redacted (not raw) path and that status degrades to 'warning'.

#### M14. Per-intent default limits (links=25, browse=50, walk=200, find_by_title/related/suggestions=10) are unreachable — zim_query always injects limit=3

`openzim_mcp/simple_tools.py:1724` · correctness · found by simple-tools

The MCP tool layer (openzim_mcp/tools/zim_query.py:99) always materializes `options["limit"] = limit if limit is not None else 3`, so every handler's `options.get("limit", N)` / `options.get("limit") or 25` fallback is dead code via the MCP surface: `links in X` returns 3 links per category (not the intended 25 at line 1724), `browse namespace C` returns 3 entries (not 50, line 1299), `walk namespace C` walks 3 entries per page (not 200, line 3125), find_by_title/related/suggestions return 3 (not 10), search_all uses 3 per file (not 5). The P3-D6 comment at lines 1716-1723 documents the exact live symptom ('links in Berlin returned 3 of 2,749 internal — well below the limit set here, suggesting a downstream narrowing path') without identifying the cause, and the bump from 20 to 25 it shipped cannot take effect. The tool description (tools/zim_query_description.md:53-58) additionally claims limit is 'Ignored' for `links in <name>` ('Setting it there has no effect'), which contradicts the actual behavior.

**Suggested fix:** In tools/zim_query.py, only set `options["limit"]` when the caller explicitly passed one (mirroring how offset/content_offset are conditionally added), letting each handler's per-intent default apply; or explicitly thread per-intent defaults from the dispatcher. Update the description's 'ignored' list to match reality.

#### M15. find_by_title upfront namespace-path redirect blocks all slash-containing titles and makes the D7 zero-hits branch dead code

`openzim_mcp/simple_tools.py:3201` · correctness · found by simple-tools

The upfront redirect in `_handle_find_by_title` (lines 3201-3218) fires for ANY title matching letter + '/' + >=3-char suffix, regardless of case (`title[0].isalpha()` accepts lowercase). The A16 D7 comment (lines 3226-3237) explicitly states the design: lowercase-first-char shapes must consult the title index FIRST and only redirect on zero hits, 'because some real article titles ARE lowercase-first-char + /'. Since Sub-D-2 Rule 1 lowercases every query, ALL titles arrive lowercase, the upfront check returns before the index is ever consulted (verified: `find article titled a/b testing` returns 'Namespace Path, Not a Title' with `find_entry_by_title_data` never called), real titles like 'A/B testing' or 'I/O scheduling' can never be found through this intent, and the D7 zero-hits branch at lines 3239-3258 (whose title-shape condition is byte-identical to the upfront one) is unreachable dead code.

**Suggested fix:** Restrict the upfront redirect to uppercase-first-char titles (`title[0].isupper()`) — though note Rule 1 lowercases everything, so the post-lookup D7 branch should be the primary path: consult the index first and only emit the redirect on zero hits, as the D7 comment describes.

#### M16. SubscriberRegistry retains dead sessions indefinitely; cleanup only happens on a failed broadcast send

`openzim_mcp/subscriptions.py:92` · concurrency · found by concurrency

Sessions are stored as strong references in SubscriberRegistry._by_uri (line 63) and are removed only by an explicit unsubscribe or by _safe_clear_session when a later broadcast's send fails or times out (lines 283, 286). clear_session (line 92) has no caller tied to session teardown — there is no hook on HTTP session termination (DELETE / disconnect). On a long-running HTTP server where subscribed clients come and go but the watched .zim files rarely or never change (broadcasts fire only on mtime/size/listing changes per MtimeWatcher._tick), dead ServerSession objects — along with their streams and buffers — accumulate without bound. When a change finally does fire, the first broadcast also burns up to SEND_TIMEOUT_SECONDS (5s, defaults.py:112) per accumulated dead session; the sends are gathered concurrently per URI but the watcher tick still pays the full timeout window before the snapshot is updated.

**Suggested fix:** Bound the registry: track sessions in a WeakSet/weak-keyed structure where possible, or periodically sweep the registry against the session manager's live-session set (or probe with a cheap no-op send), or hook FastMCP's session lifecycle (e.g. wrap the lowlevel Server run loop) to call registry.clear_session on session exit.

#### M17. Section-affinity boost inverts for negative cross-encoder scores, demoting matching passages

`openzim_mcp/synthesize.py:464` · correctness · found by synthesize

_maybe_boost_passage applies the affinity boost as `new_p['score'] = float(passage['score']) * boost` with boost >= 1.0 (default 1.5, config.py:155-164). When the [reranker] extra is engaged,_maybe_rerank_synthesize_passages overwrites every passage's score with the raw cross-encoder output (synthesize.py:1710), and ml/reranker.py:106 stores raw model scores with no sigmoid — bge-reranker-base emits unbounded logits that are routinely NEGATIVE for moderately relevant passages. Multiplying a negative score by 1.5 makes it MORE negative, so a passage whose section heading matches the query gets DEMOTED below non-matching passages by the very mechanism documented to promote it (_boost_by_section_affinity sorts by score descending at line 509). When all candidates score negative (common for niche queries), the boost inverts the intended ordering entirely.

**Suggested fix:** Make the boost monotonic regardless of sign: e.g. divide by the boost when score < 0, add a rank-based bonus instead of multiplying, or sigmoid-normalize rerank scores before propagating them into passage['score'].

#### M18. Possessive tail-rescue promotion can duplicate an existing hit, rendering the same passage twice

`openzim_mcp/synthesize.py:1203` · correctness · found by synthesize

Every other promotion path in _promote_title_match dedupes against hits already in top_hits before prepending: pass-0 checks existing_paths_p0 (line 1081) and the normal tail path checks existing_paths (line 1209). The Fix-2 rescue path does not: lines 1199-1205 build rescued_hit and `return [(archive_name, _mark_promoted(rescued_hit)), *top_hits]` with no membership check. The module's own Z2 comment (lines 1033-1036) documents that the rescued canonical can already be in BM25 top_hits ('the live Einstein's theory synthesize case surfaced Theory_of_relativity at rank 6'). When that happens, top_hits contains the same (archive, path) twice, _extract_passages_for_top_hits creates two passages with identical cite_id, both survive rerank filtering (score_by_cite_id collapses to one key but both passages pass the `in` check at line 1700), both consume the char budget in_enforce_budget, and_render_answer emits the same snippet text twice in answer_markdown. The duplicate also appears twice in passages[].

**Suggested fix:** Before returning the rescued hit, check `(archive_name, str(rescued['path'])) in existing_paths` and reorder the existing entry to front (as the other two promotion paths do) instead of prepending a duplicate.

#### M19. _drop_low_relevance_tail filters on the 1/rank proxy, not Xapian relevance — unconditionally drops the 5th hit

`openzim_mcp/synthesize.py:1315` · correctness · found by synthesize

The docstring (lines 1288-1296) claims 'The original Xapian score is preserved on each hit ... use that as the relevance signal', but search_top_k fabricates score = 1.0/rank (zim/search.py:3441 — 'no raw BM25 in libzim Python API'), and _xapian_score at synthesize.py:1315 reads that fabricated 'score' key. The 'relevance' threshold therefore degenerates into a pure rank cutoff: with threshold_ratio=0.25 and top score 1.0, hits survive iff 1/rank >= 0.25, i.e. rank <= 4. In the default single-archive synthesize (fallback_used='xapian_score', top_n=5), the rank-5 hit (score 0.2) is dropped on EVERY query regardless of how relevant it actually is, silently shrinking each answer from the configured 5 passages to 4 — and the filter can never distinguish a strong rank-5 hit from a junk one, which was its entire stated purpose (A11 G2). The sibling function _drop_cross_archive_leakage even documents the fabrication (line 1348) yet this function trusts the same key as a relevance score.

**Suggested fix:** Either remove the threshold path until a real relevance signal exists, or only apply it when an explicit 'xapian_score' key (distinct from the 1/rank 'score') is present; at minimum stop reading the 'score' key as relevance.

#### M20. Per-regex timeout submissions share one 16-worker pool with un-cancellable 30s archive opens — head-of-line blocking can stall intent parsing server-wide

`openzim_mcp/timeout_utils.py:36` · performance · found by performance

run_with_timeout uses a single global ThreadPoolExecutor capped at 16 workers (timeout_utils.py:36-58). Every safe_regex_search/findall/sub goes through it (intent_parser.py:53-58, 102-107, 128-140), and parse_intent issues one submission per INTENT_PATTERN (~30 patterns, intent_parser.py:1222-1243) plus dozens more in the politeness/param-leak strip loops and extractors — 50+ executor round-trips per dispatched query. The same pool services archive opens with 30s timeouts (zim/archive.py:266-272), and timed-out libzim workers cannot be cancelled — they keep occupying slots ('the future keeps running', timeout_utils.py:93-99). With 16 slow or wedged archive operations in flight, every micro-regex queues behind them and hits the 1.0s REGEX_SECONDS timeout (defaults.py:104); parse_intent then silently skips patterns on RegexTimeoutError (intent_parser.py:1241-1243), degrading intent classification for all users, not just the slow request.

**Suggested fix:** Run bounded, pre-vetted regexes inline (they are already ReDoS-reviewed and pre-compiled in most cases) or give regex operations a dedicated executor, reserving the shared pool for genuinely long-running libzim work.

#### M21. Timeout worker pool is never shut down; hung libzim workers block interpreter exit indefinitely

`openzim_mcp/timeout_utils.py:54` · concurrency · found by server

The module-level ThreadPoolExecutor (created at line 54) is never shut down, and Python 3.9+ executor worker threads are non-daemon and joined at interpreter shutdown by concurrent.futures' registered atexit hook (_python_exit joins every worker after sending sentinels). A worker stuck inside a libzim call that never returns — the exact scenario this module exists to guard against, per its own docstring ("A timed-out worker can't be killed... the surviving thread keeps doing libzim work", lines 23-26) — never dequeues the shutdown sentinel, so the atexit join blocks forever. Net effect: after a timeout fires on a truly hung libzim operation (e.g. archive open via run_with_timeout at zim/archive.py:267 on a stalled network filesystem), Ctrl-C produces the "Server shutdown requested" / "server stopped" logs (server.py:315, 320) and then the process hangs and must be SIGKILLed. Even finite runaways delay every shutdown by their full remaining duration.

**Suggested fix:** Create worker threads as daemon threads (e.g. a ThreadPoolExecutor subclass or initializer-managed threads), or call _EXECUTOR.shutdown(wait=False, cancel_futures=True) plus a bounded join from a shutdown hook in OpenZimMcpServer.run()'s finally block, so abandoned workers cannot block process exit.

#### M22. Timed-out futures are never cancelled — abandoned queued work still executes, prolonging overload

`openzim_mcp/timeout_utils.py:91` · performance · found by server

On timeout (line 92) the future is simply dropped without calling future.cancel(). executor.submit() never blocks — when all _MAX_WORKERS slots are busy, new work items queue immediately and the caller's future.result(timeout) expires while the item is still PENDING. Because it is never cancelled, the executor later runs it to completion even though no caller will ever observe the result: a burst of N requests while workers are slow yields N queued items that each consume a worker slot after abandonment, so the pool keeps chewing through dead work and rejecting/starving fresh requests long after the burst ends. This also falsifies the module docstring's stated design (lines 5-8: "concurrent calls past the cap block instead of spawning, which makes the overload mode observable") — callers do not block at submission; they burn their full timeout and fail while invisible dead work accumulates.

**Suggested fix:** In the TimeoutError handler call future.cancel() before raising; a still-pending item is then discarded and never occupies a worker. Only items already running (truly unkillable) continue, which restores the intended bounded-orphan behavior.

#### M23. Single 16-worker timeout pool shared by 30s libzim opens and 1s regex guards — saturation causes spurious server-wide RegexTimeoutError

`openzim_mcp/timeout_utils.py:91` · concurrency · found by concurrency

run_with_timeout submits to one module-global ThreadPoolExecutor capped at 16 workers (_MAX_WORKERS, line 36) and `future.result(timeout=timeout_seconds)` (line 91) starts counting from submit time, so the timeout includes queue wait, not just execution. The same pool is used both by zim_archive opens (zim/archive.py:267, ARCHIVE_OPEN_TIMEOUT=30s) and by every safe_regex_search/findall/sub call (intent_parser.py:53/102/129/135, REGEX_TIMEOUT_SECONDS=1.0). The module's own comments (lines 23-34, 70-74) acknowledge that timed-out libzim workers cannot be killed and keep occupying slots. Therefore one hung filesystem (e.g. a dead NFS mount) plus ~16 open attempts permanently fills the pool with unkillable workers, after which every regex operation across the whole server — including intent parsing for queries against perfectly healthy archives — spuriously raises RegexTimeoutError after 1s of queue wait without the regex ever running. The designed 'observable backpressure' degrades into wrong errors on unrelated requests.

**Suggested fix:** Use separate executors for long-running libzim work and sub-second regex guards (regex CPU work could even run inline with a compiled-pattern step limit), or measure the timeout from task start rather than submit (e.g. have the worker record a start event and wait on that first), so pool saturation by orphaned archive opens cannot fail unrelated fast operations.

#### M24. is_strong_title_match still uses ASCII-only tokenizer, producing false canonical matches on non-Latin topics

`openzim_mcp/title_promotion.py:52` · correctness · found by title-chain

`is_strong_title_match` tokenizes with `_TOKEN_RE = [a-z0-9]+` (ASCII only), so non-ASCII letters are silently deleted from tokens. Verified: `is_strong_title_match('Łódź', 'D', 'D')` returns True ('łódź' tokenizes to ['d'], exact-matching the letter article D — the equality check at line 62 runs BEFORE the 3-char guard), and `is_strong_title_match('café', 'CAF', 'CAF')` returns True. The module's own post-a17 P1-D2 comment (lines 199-213) documents this exact ASCII-tokenizer failure class as having produced live 'confidently-wrong answer' results (München -> the letter M article) — but the fix only replaced the tokenizer in `_TAIL_TOKEN_RE`; `is_strong_title_match` (used by synthesize.py:1007 and disambiguation.py to stamp a search hit as THE canonical article for the topic) still uses the broken one. Any diacritic-bearing topic whose ASCII residue collapses to a short token can be confidently matched to an unrelated short-titled article.

**Suggested fix:** Use a Unicode-aware tokenizer (the same `[^\W_]+` approach as `_TAIL_TOKEN_RE`) in `is_strong_title_match`, or at minimum apply the 3-char-sum guard before the token-equality check so mutilated 1-char residues cannot exact-match.

#### M25. Non-ASCII possessor tokens can never pass the possessive promotion gates

`openzim_mcp/title_promotion.py:965` · correctness · found by title-chain

`extract_possessor_tokens` uses the Unicode-aware `_POSSESSIVE_TOKEN_RE` ([^\W_]) so it yields possessors like 'ampère' or 'gödel' intact, but `_accept_possessive_fuzzy_suggest` (line 965) and the `_accept_possessive_redirect` fallback (line 1011) tokenize the candidate path with the ASCII-only `_TOKEN_RE` ([a-z0-9]+), which shreds 'Ampère' into {'amp','re'}. The possessor-in-canonical intersection is therefore always empty for non-ASCII possessors. Verified: `accept_possessive_promotion({'path': "Ampère's_circuital_law", 'match_type': 'fuzzy_suggest'}, "Ampère's circuital law")` returns False even though the canonical path literally contains the possessor; same for Gödel. The ASCII control case ("Newton's gravity" -> Newton's_law_of_universal_gravitation) returns True. Result: the b8 OPP-1 carve-out and b9 redirect extension are silently disabled for any possessive topic with a diacritic possessor (Ampère's law, Gödel's theorems, Erdős's conjecture, Poincaré's conjecture), forcing those queries down the weaker BM25 fallback.

**Suggested fix:** Tokenize the candidate path (and pre-redirect path) with a Unicode-aware tokenizer consistent with `extract_possessor_tokens` — e.g. split `_TAIL_TOKEN_RE` matches on apostrophes, or use a Unicode equivalent of `_TOKEN_RE` — so possessor tokens compare against unmutilated path tokens.

#### M26. zim_get documents `compact_budget` as a real char cap but the parameter is never used

`openzim_mcp/tools/zim_get.py:69` · correctness · found by api-ux

`compact_budget` is accepted (line 69) and zim_get_description.md lines 44-46 describe it as "Named profile (\"tiny\"/\"small\"/\"medium\"/\"large\") or raw integer char cap when compact=True" — with no caveat. The handler never references the variable after binding: none of `get_zim_entry_data`, `get_entries_data`, `get_entry_summary_data`, `get_table_of_contents_data`, `get_article_structure_data` calls receives it (lines 106-141). The only wired consumer of compact_budget is the simple-mode path (simple_tools.py:899). A small-model caller setting `compact_budget="tiny"` to protect its context window gets an uncapped response.

**Suggested fix:** Wire `compact_budget` into the compact rendering path (as zim_query does via options), or document it as inert at v2.0 the way zim_get_section_description.md does.

#### M27. zim_get_section description says `compact` is a no-op, but it is wired and changes output

`openzim_mcp/tools/zim_get_section_description.md:19` · correctness · found by api-ux

The client-facing description (lines 17-23) states "At v2.0 the parameter is a no-op: section bodies always ship in the bundle's compact rendering" and the RESPONSE block (line 29-30) repeats "always compact-rendered at v2.0". The code disagrees: the handler forwards `compact=compact` to `get_section_data` (zim_get_section.py:60-66), which threads it into bundle construction (zim/structure.py:534-601), and the module docstring confirms "``compact`` is wired at the data layer (v2.5 #18): ... ``compact=False`` returns the unrendered section body with full pipe-delimited tables". A model reading the description will never pass compact=False to obtain full tables, and one that does gets a different shape than documented.

**Suggested fix:** Update the description to match the wired behavior: compact=True (default) collapses oversized tables to placeholders; compact=False returns the raw section body with full tables. Keep the no-op caveat only for compact_budget.

#### M28. zim_search silently drops `offset` in title, suggest, and cross-file fulltext modes

`openzim_mcp/tools/zim_search.py:255` · correctness · found by api-ux

The description (zim_search_description.md line 45) documents `offset` as a general "Pagination offset (default 0)" and the handler validates it (lines 99-103), but only single-archive fulltext actually honors it. `_handle_title_mode` receives `offset` (line 255) and never uses it — `find_entry_by_title_data` has no offset parameter (async_operations.py:648-654). Suggest mode calls `get_search_suggestions_data(path, query, limit)` with no offset (lines 135-137), and cross-file fulltext calls `search_all_data(query, limit_per_file=...)` with no offset (lines 217-219). A model paging title/suggest results with offset=10 silently receives the same first page forever.

**Suggested fix:** Reject non-zero `offset` in modes that cannot honor it (mirroring the existing `invalid_combination` errors), or implement offset slicing in those data calls; update the parameter doc to state which modes paginate.

#### M29. zim_search RESPONSE doc misstates result shape for cross_file and suggest modes

`openzim_mcp/tools/zim_search_description.md:50` · correctness · found by api-ux

Lines 49-53 claim "Search-shape dict with `results` array. Each result carries `path`, `title`, and (mode-dependent) `snippet`". With `cross_file=True` the tool returns SearchAllResponse, whose `results[]` rows are per-archive wrappers `{zim_file_path, name, has_hits, result, error, ...}` (tool_schemas.py:161-203) — the actual hits are nested one level down in `results[].result.results`. With mode="suggest" each item is `{text, path, type}` (SuggestionItem, tool_schemas.py:72-75) with no `title`. A model iterating `results` per the description will read absent keys and miss the nested hits in cross-archive responses.

**Suggested fix:** Document the per-mode shapes explicitly: cross_file=True returns per-archive rows with hits under `results[].result.results`; suggest items carry `text`/`path`/`type`.

#### M30. Pass 3 of promote_topic_via_title_index repeats Pass 1's identical backend lookups

`openzim_mcp/topic_preprocessing.py:180` · performance · found by performance

find_title_match's min_score parameter is applied client-side after the data fetch (title_promotion.py:143-155 — the backend call find_entry_by_title_data(zim_file_path, topic, cross_file, limit=3) is identical regardless of min_score). When no tail passes the strict 1.0 gate in Pass 1 (topic_preprocessing.py:162-163), Pass 3 (lines 180-181) iterates the exact same iter_query_tails set and re-executes the exact same backend calls (archive open + suggestion search + potential typo sweep per tail) just to re-filter the same results at min_score=0.8 — doubling the entire tail-probe cost on the common no-strict-match path.

**Suggested fix:** Probe each tail once (fetching at the permissive 0.8 threshold), cache the per-tail results, apply the strict 1.0 gate over the cached results first, then fall back to the 0.8 gate over the same data without re-querying.

#### M31. Search snippets re-render the full article per result; synthesize parses the same HTML twice, bypassing the bundle cache

`openzim_mcp/zim/content.py:234` · performance · found by performance

_get_entry_snippet (zim/content.py:215-253) decodes the entire entry, BeautifulSoup-parses the full HTML (line 234), and runs the full compact render (_render_soup_to_text at line 238: infobox extraction + oversized-table replacement + html2text over the whole document) to emit a <=2-paragraph, ~3000-char snippet. It runs once per search result:_perform_search calls it per hit (zim/search.py:700, default limit 10), and search_top_k calls it per hit with per_archive_k=10 (zim/search.py:3435). On Wikipedia-scale articles (100KB-1MB HTML) a cold search pays 10 full document parses+renders just for snippets. Worse, in a single synthesize request the SAME entries are then re-parsed and re-rendered a second time by get_or_build_bundle (bundle.py:327 BeautifulSoup parse, bundle.py:347 _render_soup_to_text) for section attribution — the docstring at zim/content.py:192-199 explicitly states the snippet render is byte-compatible with the bundle's rendered_markdown, yet the snippet path never consults the bundle cache (get_or_build_bundle, bundle.py:367-388). This is the dominant CPU cost of e…

**Suggested fix:** Source snippets from the cached EntryBundle's rendered_markdown (the renders are already identical by design), or cache the compact-rendered markdown per (validated_path, entry_path, stat_token) so search, snippets, and bundle-building share one render per article.

#### M32. Archive-type preset is re-derived from full metadata extraction on every uncached search

`openzim_mcp/zim/search.py:501` · performance · found by performance

search_zim_file_data calls_resolve_preset_for_open_archive on every search-cache miss (zim/search.py:501), which runs the full _extract_zim_metadata pass (zim/archive.py:700): it probes ~15 M-namespace keys, and on old-scheme archives each value read decodes the complete entry content (zim/archive.py:836) and BeautifulSoup-parses it in_extract_metadata_text (zim/archive.py:198) — the code's own comments document Wikipedia ZIMs storing ~1MB HTML documents per metadata field. The same uncached extraction also runs per entry-summary call (zim/content.py:1445). The preset depends only on the archive, yet the existing per-archive metadata cache (`metadata_data:v2c:` key, zim/archive.py:515) is bypassed because _resolve_preset_for_open_archive takes an open handle and calls_extract_zim_metadata directly. Every distinct query pays this archive-constant cost again.

**Suggested fix:** Cache the resolved (preset, applied_type) tuple keyed by validated_path + archive_stat_token (or route through the cached get_zim_metadata_data) so preset resolution is a one-time per-archive cost.

#### M33. Canonical-splice filtered search runs the entire Xapian scan and snippet rendering twice when the canonical is already the top hit

`openzim_mcp/zim/search.py:1104` · performance · found by performance

_splice_canonical_into_filtered first executes the full filtered search via search_with_filters_data (zim/search.py:1035 — Xapian scan, entry materialisation, per-result full-article snippet rendering). When the structured payload's top hit IS the canonical (top_path == canonical_path), instead of rendering the payload it already holds, it calls self.search_with_filters (zim/search.py:1104-1111), which re-runs_perform_filtered_search from scratch — a second complete scan plus per-result snippet renders — because the legacy markdown path uses a separate `search_filtered:` cache namespace that is cold on the first call. 'search for <canonical topic> in namespace C' is the common case for this code path, so the doubling hits realistic traffic.

**Suggested fix:** Render the already-computed structured payload through _format_filtered_response (as the non-short-circuit branch does) instead of delegating back to the legacy search_with_filters execution path.

#### M34. Partial/corrupt test-data downloads are treated as complete on subsequent runs

`scripts/download_test_data.py:234` · error-handling · found by ci-packaging

download_file() calls urlretrieve(url, dest_path) (line 140) writing directly to the final destination. If the transfer fails mid-stream, a truncated file is left at dest_path. On the next invocation, line 234 (`if dest_path.exists() and not force:`) skips any existing file as already downloaded, so the corrupt ZIM file persists indefinitely and create_manifest() (line 268) records the sha256 of the truncated file as if it were authoritative — there are no expected checksums to compare against. The result is confusing downstream libzim test failures with no indication the data is bad.

**Suggested fix:** Download to a temporary path (e.g., dest_path.with_suffix('.part')) and os.replace() into place only on success; ideally also validate downloaded size against the known size_mb or pin expected sha256 hashes in ESSENTIAL_FILES.

### Low (confirmed) severity

#### L1. deploy-website update-benchmark-integration job pushes to gh-pages with a read-only token

`.github/workflows/deploy-website.yml:129` · ci · found by ci-packaging

The update-benchmark-integration job declares `permissions: contents: read` (lines 84-85), but its 'Commit changes' step runs `git push` to the gh-pages branch (line 129) using the checkout's GITHUB_TOKEN. With contents: read the push is rejected with a 403, so whenever the sed edit at lines 105-108 actually modifies index.html, the step fails and the workflow goes red on a main push. The job can never accomplish its stated purpose; it only appears green today because the gh-pages checkout fails (continue-on-error, line 89) or no changes are produced.

**Suggested fix:** Either grant the job `contents: write`, or delete the job entirely — performance.yml sets `auto-push: false` on the benchmark action, so a benchmark gh-pages site is not being maintained anyway.

#### L2. ~25 structured async `_data` wrappers never executed; tool/ops seam mocked on both sides

`openzim_mcp/async_operations.py:135` · tests · found by tests

Full-suite coverage shows async_operations.py at 78% with the bodies of the structured wrappers never run: lines 99, 135, 210, 224, 243, 258, 275, 309, 364, 404, 435, 479, 518, 548, 586, 602, 614, 624, 630, 640, 656, 671, 685, 702, 722 (search_zim_file_data, browse_namespace_data, get_entries_data, get_section_data, get_inbound_links_data, etc.). tests/test_async_operations.py pins argument forwarding only for the legacy string-returning variants, while the Phase-F tool tests (tests/test_zim_get.py, test_zim_search.py, test_zim_browse.py, etc.) monkeypatch openzim_mcp.async_operations.AsyncZim…

**Suggested fix:** Extend tests/test_async_operations.py (or parametrize a single forwarding test over the wrapper list) to call each `_data` wrapper against a MagicMock(spec=ZimOperations) and assert_called_once_with the exact arguments, mirroring what is already done for the legacy variants.

#### L3. HTTP subscription-watcher lifespan wiring only covered by live tests that no CI workflow runs

`openzim_mcp/http_app.py:393` · ci · found by tests

serve_streamable_http's MtimeWatcher wiring (the _on_change broadcast at line 379 and the lifespan_with_watcher start/stop wrapper at lines 393-398) is uncovered in the default suite (coverage shows http_app.py missing 379, 393-398). The code's own comment (lines 369-373) explains this is exactly the silent-failure-prone spot: FastMCP supplies a custom lifespan, so a naive add_event_handler('startup') 'silently does nothing'. The only tests exercising it live in tests/live/test_live_subscriptions.py, but addopts deselects `-m live` and no .github/workflows/*.yml ever runs the live marker (grep…

**Suggested fix:** Add an in-process unit test that builds the streamable-HTTP app with a subscriber registry and a stub watcher, runs the app lifespan via Starlette TestClient (its context manager triggers lifespan), and asserts watcher.start/stop were called; alternatively add a CI job that runs `make test-live` on a small fixture directory.

#### L4. Tier-1 query-rewrite rules execute twice per request with unmemoized archive-probing title_probe

`openzim_mcp/simple_tools.py:241` · performance · found by performance

_run_query_rewrite_probes (simple_tools.py:241-289) runs the lowercase/misspelling/stopword/decompose rules solely to bump telemetry counters, calling title_probe (which performs a full find_entry_by_title_data: archive open + SuggestionSearcher per call, simple_tools.py:222-237) for any mapped token, any 'the/a/an/of'-prefixed query (rule 3 probes the FULL query), and any 'X of Y' shape. handle_zim_query then calls parse_intent (simple_tools.py:606-610), whose_apply_tier1_rewrites (intent_parser.py:1199-1203, 1126-1147) re-runs all four rules with the same probe — and the probe closure has n…

**Suggested fix:** Memoize probe results per token for the lifetime of the request (e.g. functools.lru_cache on the closure or a dict in the handler), or run the rewrite once in parse_intent and derive the per-rule telemetry from its returned intermediate stages.

#### L5. structuredContent contract broken: `-> Any` tools emit none; zim_query wraps payloads in {"result": ...}

`openzim_mcp/tool_schemas.py:7` · correctness · found by api-ux

The module docstring (lines 4-7) claims FastMCP "reads the function's return annotation to generate the output schema and emits the payload at the top level of structuredContent — no {\"result\": ...} wrapper". Verified against the pinned mcp 1.27.0 SDK: the 7 advanced tools are annotated `-> Any` (e.g. tools/zim_search.py:76), for which func_metadata produces output_schema=None — their dict payloads are serialized as JSON text inside a TextContent block with NO structuredContent at all. Meanwhile zim_query's `Union[str, SynthesizeResponse, ToolErrorPayload]` annotation (tools/zim_query.py:57)…

**Suggested fix:** Annotate each tool with its precise TypedDict union (or a discriminated wrapper model) so FastMCP emits top-level structuredContent uniformly; at minimum correct the tool_schemas.py contract docstring so integrators don't build against structuredContent that never arrives.

#### L6. Same tool returns two incompatible error shapes: ToolErrorPayload dict vs plain markdown string

`openzim_mcp/tools/_common.py:45` · error-handling · found by api-ux

Parameter/combination errors return structured `ToolErrorPayload` dicts (`{error: true, operation, message}`), but every wrapper's broad `except` routes through `tool_error_response`, which returns the plain markdown string from `_create_enhanced_error_message` (line 45-47) — so data-layer failures (entry not found, bad archive, rate limit) come back as a bare string. responses.py's docstring (lines 5-9) promises "every tool emits a recognisable envelope on failure", and zim_links_description.md tells callers errors arrive as structured envelopes. A client branching on `error: true` misses the…

**Suggested fix:** Have `tool_error_response` wrap the enhanced message in `tool_error(operation=..., message=enhanced_text, context=...)` so all failure paths share the ToolErrorPayload envelope.

#### L7. Vacuous mock-tests-the-mock tests across test_metadata_tools.py

`tests/test_metadata_tools.py:37` · tests · found by tests

TestGetZimMetadataTool, TestGetMainPageTool, and TestListNamespacesTool never invoke any server code under test. E.g. test_get_zim_metadata_success (lines 30-42) replaces server.async_zim_operations.get_zim_metadata with an AsyncMock, then awaits THE MOCK ITSELF (line 37) and asserts it returns its own canned value; test_get_zim_metadata_generic_exception (lines 56-64) and test_list_namespaces_generic_exception (lines 137-145) assert that an AsyncMock configured with side_effect=Exception raises that exception — testing unittest.mock, not exception handling. The 'rate limit' tests (lines 44-53…

**Suggested fix:** Rewrite these tests to call the registered MCP tool handlers (or OpenZimMcpServer methods) with the ops layer mocked one level down, asserting the handler's error-translation and rate-limit behavior; delete the tests that only assert AsyncMock round-trips.

### Refuted during verification

- openzim_mcp/content_processor.py — select_main_content serializes and re-parses the landmark subtree, doubling parse cost on ZIMIT/warc2zim pages: The serialize+re-parse at content_processor.py:417 exists but is a documented, intentional requirement: the docstring (lines 408-412) explains the return must be a full BeautifulSoup because downstream rendering calls new_tag (BeautifulSoup-only) during oversized-table replacement, so returning the bare Tag would break the compact path. The "tripling" cost claim is wrong: _render_soup_to_text always ends with handle(str(soup)) (line 943), so the baseline pipeline already serializes and html2text

## Completeness-critic results

A final agent audited what the review structure itself missed. Verified new issues and uncovered areas:

- [verified new issue, medium] MCP resources surface directs clients to tools that no longer exist — same defect class as the error_messages.py finding, but unflagged. /Users/cameron/Developer/openzim-mcp/openzim_mcp/tools/resource_tools.py:69-71 (truncation notice: 'Use the get_zim_entry tool with content_offset ... or get_binary_entry for raw bytes'), :194-200 (oversize-binary error: 'Use the get_binary_entry tool with max_size_bytes set'), :361 ('Use the get_zim_entry tool for processed/truncated text output'). Neither get_zim_entry nor get_binary_entry is registered on the v2 surface (tools/**init**.py registers only zim_query + 7 zim_* tools), and max_size_bytes is not a parameter anywhere; the v2 equivalents are zim_get(content_offset=...) and zim_get(binary=True). Every truncated resource read hands the model a dead-end instruction.

- [verified new issue, medium] The Performance Benchmarks workflow is a structural no-op end to end. Zero pytest-benchmark tests exist anywhere — verified: `uv run pytest tests/ -k benchmark --collect-only -q` reports 'no tests collected (3224 deselected)' (only tests/dispatch_eval/ mentions 'benchmark'; those are auto-skipped opt-in scripts, not pytest-benchmark tests). /Users/cameron/Developer/openzim-mcp/.github/workflows/performance.yml:49-56 swallows pytest's exit-5 in an if/else, :58-64 then fabricates a placeholder benchmark-results.json ('version': 'no-benchmark-tests'), and the PR comparison step (:102-113) runs against that empty placeholder with fail-on-alert:false. The workflow burns CI on every PR, every main push, and a weekly cron (including a full ZIM test-data download) while producing fictitious benchmark signal — and it feeds the same gh-pages benchmark integration that deploy-website.yml was already flagged for. Bonus: performance.yml:36 `uv run --isolated pip install pytest-benchmark` installs into a throwaway env (vestigial; the dep is already in dev extras). The review's CI audit covered test.yml/release.yml/deploy-website.yml but skipped this workflow entirely.

- [verified new issue, low] Link-graph builder memory claim is false for nodes: /Users/cameron/Developer/openzim-mcp/openzim_mcp/linkgraph/builder.py:196-198 docstring says 'the whole graph is never held in memory', but build_from_link_stream interns every node path in the in-memory `ids: Dict[str, int]` (builder.py:60-67) and materializes the full node list for insertion (:97-100). Only edges stream in batches. For the documented full-archive use case (`openzim-mcp build link-graph <wikipedia>`, millions of articles) this is GB-scale RSS in the CLI. The performance audit never touched the linkgraph subsystem.

- [verified new issue, low] Stale SonarCloud suppression now masks a regression class: /Users/cameron/Developer/openzim-mcp/sonar-project.properties:50-57 suppresses githubactions:S7637 (require full commit-SHA pins) across .github/workflows/** with the justification 'every workflow in this repo uses major-tag pins ... transition to SHA pinning is tracked as a follow-up' — but HEAD commit 2d23e20 ('ci: pin third-party GitHub Actions to commit SHAs') completed that transition. The blanket suppression is now both factually wrong and actively prevents SonarCloud (the gate Glama relies on) from flagging any future unpinned third-party action.

- [uncovered area] The MCP resources + prompts surface (591 lines: /Users/cameron/Developer/openzim-mcp/openzim_mcp/tools/resource_tools.py and tools/prompts.py) sat outside every review axis — the API/schema-consistency pass covered only the 8 tools, and no security finding touches the resource entry-path handling (unquote + sanitize_input at resource_tools.py:232-235, ZIM-name resolution at :85-102) or the prompt-injection sanitizer (prompts.py:20-49). I spot-checked both: prompts' hardcoded tool params (cross_file, main_page, mode='walk', view='summary') all match current signatures, and entry-path handling looks sound — but the verified stale-tool issue above shows nobody reviewed this surface.

- [uncovered area] The repo's newest, highest-churn subsystems have zero findings: /Users/cameron/Developer/openzim-mcp/openzim_mcp/linkgraph/ (builder/reader/schema — PRs #274/#279/#280, merged days before this review), openzim_mcp/ml/ (reranker.py singleton + load-timeout kill switch, fallback.py decorator, ml/cli/download.py model-download path), and openzim_mcp/cli/build.py. I spot-checked reader.py (fingerprint gating, percent-encoded read-only URI, per-call open/close — sound) and reranker.py (defensive, acknowledged thread leak) and found nothing beyond the builder memory claim, but ml/cli/download.py and cli/build.py got no systematic eyes from anyone.

- [uncovered area, low] OPENZIM_MCP_INSECURE_DISABLE_AUTH (/Users/cameron/Developer/openzim-mcp/openzim_mcp/http_app.py:116-136) is an explicit HTTP-auth-disable escape hatch that appears nowhere in README.md, SECURITY.md, or any website doc (verified by grep across website/src/content/docs and docs/). The security audit flagged the empty-AUTH_TOKEN silent bypass but never noted that a deliberate disable flag exists undocumented — security-best-practices.mdx cannot warn operators about a knob it doesn't mention, and the two auth-bypass paths interact.

- [checked clean — ruled out with evidence] (a) Dependency vulnerabilities: pip-audit 2.10.1 over the full uv.lock export with all extras → 'No known vulnerabilities found'; the CI pip-audit gate (test.yml:232-233) is real and blocking, unlike the bandit step. (b) Env-var docs drift: every OPENZIM_MCP_X__Y name in website docs resolves via pydantic env_prefix + '__' nested delimiter (config.py:427-429); no drift in either direction beyond the undocumented flags above. (c) Website v1 tool-name mentions (search_zim_file, get_zim_entry, list_zim_files in faq.mdx/api-reference.mdx) are intentional v1→v2 migration tables, not drift. (d) Dockerfile (read-only tree, non-root uid 10001, stdio default, pinned uv) and wheel packaging (setuptools package-data covers data/*.txt|toml + tools/*.md; every subpackage incl. ml/cli has **init**.py) are sound. (e) docker-publish.yml and codeql.yml are unremarkable (note: CodeQL analyzes python only — the Astro/TS website is unanalyzed, acceptable for a static site). (f) Subscriptions docs correctly state HTTP-only (server.py:150-155 matches resources-prompts-subscriptions.mdx:267). (g) git history shows no reverted-then-reintroduced patterns; the two reverts (6951e09, 1102a28) stayed reverted.

## Opportunities

### Architecture & refactoring

#### Unify the duplicated filtered-search implementations in zim/search.py (render-from-data)

*impact: high · effort: medium*

WHAT: /Users/cameron/Developer/openzim-mcp/openzim_mcp/zim/search.py keeps two parallel filtered-search stacks: `search_with_filters` (line 1161) + `_perform_filtered_search` (line 1587) + `_build_filtered_results` (line 1834) render markdown directly, while `search_with_filters_data` (line 1279) + `_perform_filtered_search_data` (line 1474, with an inline hit-projection loop duplicating `_build_filtered_results`) return structured dicts. Both duplicate the full orchestration: namespace canonicalisation, Query/Searcher setup, `_scan_filtered_search` call, validation, archive open, error wrapping, and even two separate caches (legacy markdown cache vs the v2b dict cache). Every other pair in the file already delegates correctly (`search_zim_file` -> `_format_search_text(search_zim_file_data(...))`; `browse_namespace`/`walk_namespace`/`find_entry_by_title`/`search_all`/`get_search_suggestions` are thin `_json(...)` wrappers). WHY: the duplication has already caused a shipped bug — the comment at `_perform_filtered_search_data` documents the `KeyError: 'namespace'` drift where the_data sibling dropped per-hit fields the renderer required. One cache also means no double-warm and no stale-divergence between the two surfaces. SCOPE: make `search_with_filters` call `search_with_filters_data` and add a `_format_filtered_text(payload, display_query=...)` renderer (the pieces — `_format_filter_text`, `_format_filtered_response` — already exist); delete `_perform_filtered_search` and `_build_filtered_results`. Tests pin the rendered strings, so the repo's existing parity-test pattern (tests/dispatch_eval/test_promotion_extraction_parity.py style) applies; ~250 lines deleted.

#### Single title-promotion orchestrator shared by tell_me_about and synthesize

*impact: high · effort: medium*

WHAT: the pass structure (pass-0 full-topic probe at min_score=0.95, possessive min_len tightening, strict tail iteration, sliding windows, 0.8 typo pass, Z4/tail-hijack gates) is implemented twice: `promote_topic_via_title_index` in /Users/cameron/Developer/openzim-mcp/openzim_mcp/topic_preprocessing.py (lines 52-190, used by simple_tools._promote_topic_via_title_index) and `_promote_title_match` in /Users/cameron/Developer/openzim-mcp/openzim_mcp/synthesize.py (lines 960-1225, 265 lines). The acceptance gates were already extracted to title_promotion.py precisely because of drift, but the orchestration — pass order, min_score conventions, possessive rescue, promoted-hit shaping — is still duplicated. WHY: the code's own comments document three drift incidents (post-b4 D3 "synthesize never got the treatment", post-v2.1.3 D1 `ssh connection refused` -> `Refused` inversion, post-b6 Z2 hit-shape bug). Every new gate currently has to be ported by hand to both sites and bugs surface only in live evals. SCOPE: extract one `run_promotion_passes(topic, probe, accept, *, min_score_pass0=0.95)` generator into title_promotion.py parameterized over the probe (single-archive path vs per-archive loop) and the hit-shaping callback (`_build_pass0_promoted_hit` / `_mark_promoted` stay synthesize-side); both call sites become ~40-line adapters. The synthesize-only apostrophe tail-rescue (#252) stays a synthesize-side hook. ~200 net lines removed and one place to add the next gate.

#### Extract the tell_me_about topic-resolution pipeline out of SimpleToolsHandler

*impact: high · effort: large*

WHAT: /Users/cameron/Developer/openzim-mcp/openzim_mcp/simple_tools.py (3831 lines, the hottest file in the repo: 46 of the last 200 commits) is dominated by one subdomain — tell_me_about. Lines 2298-3011 (~715 lines: `_handle_tell_me_about`, `_resolve_tell_me_about_topic`, `_tell_me_about_namespace_redirect`, `_try_explicit_disambig_page`, `_search_or_recover_tell_me_about`, `_collect_tell_me_about_strong_matches`, `_auto_pick_or_render_disambiguation`, `_render_tell_me_about_article`, `_fetch_topic_article_body`) plus the `_TellMeAboutSearch`/`_TellMeAboutPick` dataclasses, plus three mixins that exist only for this flow (article_body.py 310, disambiguation.py 253, subject_section.py 323) and the upstream helpers (topic_preprocessing.py, title_promotion.py 1191). That is a ~2,800-line topic-resolution subsystem spread across 6 modules glued together by mixin attribute conventions and TYPE_CHECKING forward declarations. WHY: this is the highest-churn logic in the project and currently mutates/reads handler state implicitly through mixins; the seam is real (the flow is a linear pipeline: resolve topic -> promote via title index -> search/recover -> disambiguate -> render article/section). A dedicated `topic_resolution/` package with an explicit pipeline object (holding zim_operations, telemetry callback, config) would make each stage independently testable and shrink simple_tools.py to the dispatcher plus thin handlers. SCOPE: move the 9 methods + 3 mixins into a package; replace mixin attribute access with a small context dataclass; `SimpleToolsHandler._handle_tell_me_about` becomes a ~20-line delegation. Mostly mechanical but large surface; the existing telemetry keys (`self._track`) and rendered-string tests constrain it.

#### Collapse async_operations.py to generic delegation

*impact: medium · effort: small*

WHAT: /Users/cameron/Developer/openzim-mcp/openzim_mcp/async_operations.py is 841 lines, and every one of its ~40 methods is the identical shape `return await asyncio.to_thread(self._ops.<name>, *args)` (verified across `search_zim_file`, `search_zim_file_data`, `get_table_of_contents`, `get_binary_entry`, `walk_namespace`, etc. — zero added logic anywhere). WHY: every new ZimOperations method currently requires four hand-written surfaces (sync str, sync _data, async str, async_data); the async pair is pure transcription debt and a place for signatures to silently drift from the sync source of truth (e.g. keyword-only params already require careful `partial` wrapping at line 125). SCOPE: replace with either (a) a ~30-line `__getattr__`-based proxy that wraps any callable attribute of `ZimOperations` in `asyncio.to_thread`, keeping a .pyi or `TYPE_CHECKING` block for typing, or (b) a tiny codegen/decorator that builds the wrappers from `ZimOperations`'s public methods. Net deletion of ~750 lines; tests that patch `AsyncZimOperations.<method>` need the proxy to remain patchable (define wrappers in `__init__` via `functools.partial` per method if needed).

#### Fix the utility-layering inversions: regex/quote/token helpers out of intent_parser and title_promotion

*impact: medium · effort: small*

WHAT: generic utilities live inside high-level feature modules, forcing private cross-module imports that invert the layering. Concretely: `safe_regex_search/findall/sub` and `_strip_quote_pair` live in /Users/cameron/Developer/openzim-mcp/openzim_mcp/intent_parser.py (lines 29-147) and are imported by compact_format.py (a rendering module importing from the NL parser), simple_tools.py, and indirectly others; the token regexes `_TOKEN_RE` (line 26) and `_TAIL_TOKEN_RE` (line 225) in title_promotion.py are imported as private names by subject_section.py, synthesize.py, and simple_tools.py, while synthesize.py separately redefines the identical regex as `_AFFINITY_TOKEN_RE` (line 380) and text_utils.py defines a third copy (line 12); `_is_list_article` lives in synthesize.py (line 1255) but is lazily imported by simple_tools.*stable_demote_list_articles (line 2158) — a higher layer reaching into a sibling pipeline for a ranking predicate; bundle.py imports private `_build_headings` from content_processor (line 304). WHY: these private imports are exactly where drift bugs breed (the codebase already grew text_utils.py for this purpose but only one helper moved); they also make the dependency graph cyclic-in-spirit (parser <- renderer, synthesize <- dispatcher) and block the bigger decompositions above. SCOPE: move safe_regex** into timeout_utils.py (or a new regex_utils.py), `_strip_quote_pair` + the token regexes into text_utils.py as public names, and `_is_list_article` + its three regex tables into a small ranking/list_articles module imported by both synthesize and simple_tools. Pure moves with re-export shims (the repo already has the zim_operations.py shim precedent); ~1 day including import churn.

#### Make simple-tool handlers data-first; retire the per-handler compact/legacy fork

*impact: medium · effort: medium*

WHAT: nearly every `_handle_*` in /Users/cameron/Developer/openzim-mcp/openzim_mcp/simple_tools.py repeats the same fork: `if options.get("compact"): data = zim_operations.<op>_data(...); return compact_renderers.render_<op>(data)` / `else: return zim_operations.<op>(...)` where the else-branch returns a raw JSON string into a natural-language surface (see `_handle_walk_namespace` lines 3148-3161, `_handle_find_by_title` lines 3219-3265, `_handle_search_all` lines 3036-3075, `_handle_list_namespaces` lines 1246-1256, `_handle_browse` line 1296). `_handle_find_by_title` even duplicates its 20-line namespace-path guidance block twice within the same method (lines 3209-3218 and 3248-3258) because of the fork. WHY: handlers should produce one structured payload; the compact-vs-full decision is a rendering concern that already has a central seam (`_finalize_compact_response`, line 823). Unifying removes ~15 duplicated forks, makes the legacy `_json(...)` string wrappers on ZimOperations deletable (zim/search.py, zim/namespace.py), and ends the situation where compact mode and legacy mode can disagree about recovery hints. SCOPE: per handler, always call the `_data` variant and pick `compact_renderers.render_*` vs a `_json` fallback at one dispatch point keyed by intent; then deprecate the string variants on ZimOperations. Mechanical, can be landed one intent at a time; the rendered-text tests for legacy mode are the main cost.

#### Split zim/search.py (3,486 lines) along its five embedded domains

*impact: medium · effort: medium*

WHAT: /Users/cameron/Developer/openzim-mcp/openzim_mcp/zim/search.py is now bigger than the pre-refactor zim_operations.py and `_SearchMixin` contains five separable domains: (1) basic search + rendering (`search_zim_file*`, `_perform_search`, `_format_search_text`, lines 365-911); (2) filtered search + canonical splice (`search_with_filters*`, `_splice_canonical_into_filtered`, `_scan_filtered_search`, lines 912-1877); (3) suggestions (`get_search_suggestions*`, `_generate_search_suggestions`, `_get_suggestions_from_search`, `_find_canonical_prefix_match`, lines 1878-2456); (4) title lookup (`_find_entry_fast_path`, `_typo_variants`, `_find_entry_typo_fallback_with_suggestions`, `find_entry_by_title*`, `_is_path_match`, lines 2457-3240); (5) cross-archive aggregation + synthesize primitives (`search_all*`, `search_top_k`, `title_match_hit`, lines 3241-3486). WHY: the file is the second-hottest in the repo (30 of last 200 commits); the title-lookup domain in particular is the backend for the whole title-promotion subsystem and deserves its own module and test seam, and domain (5) is the only part synthesize.py depends on — splitting it shrinks synthesize's import surface to a 250-line module instead of a 3.5k-line one. SCOPE: same recipe already used for the zim package itself (`_ContentMixin`/`_StructureMixin`/`_NamespaceMixin` + the zim_operations.py call-time re-export shim for test patches): four new modules (`search_filtered.py`, `suggestions.py`, `title_lookup.py`, `search_aggregate.py`), `_SearchMixin` becomes a composition of five mixins; zero behavior change, mostly `git mv`-style cuts.

#### Per-intent registry: co-locate pattern, extractor, handler, and guidance per intent

*impact: medium · effort: large*

WHAT: each of the ~20 intents is currently defined in four disconnected places: the ~870-line `INTENT_PATTERNS` table (/Users/cameron/Developer/openzim-mcp/openzim_mcp/intent_parser.py line 729), the per-intent `_extract_*` module functions (intent_parser.py lines 148-720), the `_INTENT_HANDLERS` dict + `_handle_*` methods (/Users/cameron/Developer/openzim-mcp/openzim_mcp/simple_tools.py line 3371), and the chain-detection verb tables in /Users/cameron/Developer/openzim-mcp/openzim_mcp/chain_detection.py which re-enumerate the intent verb vocabulary and reach into IntentParser private classmethods (`IntentParser._strip_param_leaks` at line 123, `_strip_trailing_politeness` at lines 215-216). Adding or tuning an intent means touching all four with nothing enforcing consistency. WHY: this is the core extension axis of the product (most CHANGELOG entries are intent-behavior fixes); a registry makes the per-intent unit reviewable in one diff and lets chain detection derive its verb list from the registry instead of a hand-maintained parallel table. SCOPE: an `IntentSpec` dataclass (name, patterns+confidence+specificity, extractor, handler ref, missing-param guidance, example queries) and a module-per-intent or single registry module; `parse_intent`'s scoring loop and the dispatcher iterate the registry. The dynamic parts (tier-1 rewrites, bare-topic fallback) stay where they are. Large because of the volume of moved code, but behavior-preserving and incrementally landable intent-by-intent.

### Features

#### Expose the already-parsed infobox as a structured facts view (zim_get view="infobox")

*impact: high · effort: small*

What: openzim_mcp/bundle.py already extracts every article's infobox into structured InfoboxData (label/value fields) during the single-parse bundle step — then decomposes it out of the rendered markdown and never surfaces it in any tool response (the only mention is a docstring note in tools/zim_get_section.py saying it isn't inlined). Adding a `view="infobox"` branch to zim_get (or attaching the fields to view="summary") gives LLMs the highest-density facts on a page (birth/death dates, population, chemical formula) for a few hundred tokens instead of a 4,000-char body fetch. Who benefits: small-model simple-mode callers most of all — fact-lookup queries become one cheap structured call — plus any agent doing comparative/tabular work across articles. Effort: small; the parsing, caching, and InfoboxData schema (tool_schemas.py) all exist, so this is a new view branch, a TypedDict response, a compact renderer, and a description.md update. Schema-additive, consistent with the v2.5 'no wire-format changes' rule.

#### Multi-archive auto-routing in zim_query

*impact: high · effort: medium*

What: simple mode is pitched as the zero-thought default, but with more than one archive loaded, zim_query only auto-selects when exactly one archive exists (simple_tools.py `_probe_archive_path`); otherwise the model must first call 'list available ZIM files' and pass an explicit zim_file_path — exactly the multi-step dispatch burden simple mode exists to remove, and the tool description spends ~15 lines warning models not to invent paths. A server-side router — cheap title-probe fan-out (the probe infrastructure already exists in `_build_title_probe` and search_all), plus archive-type priors from archive_types.py (route 'define X' to a wiktionary archive, 'how do I' to stackexchange) — would pick the best archive automatically and report the choice in _meta. Who benefits: the project's core persona (small models ≤13B in simple mode) running against realistic Kiwix libraries, which are almost never single-archive; also removes a whole class of hallucinated-path errors the code currently has to auto-correct. Effort: medium — probe fan-out with a latency budget, tie-breaking, and telemetry, no schema change.

#### Lean embeddings sidecar for hybrid semantic retrieval (rescoped sub-D-4)

*impact: high · effort: large*

What: the roadmap's own gap statement (docs/roadmap.md sub-D-4) is the biggest real-world quality ceiling: pure Xapian BM25 means concept-shaped queries ('the chemical that makes leaves green') never reach Chlorophyll because no lexical token overlaps; the cross-encoder reranker only reorders Xapian's top-50 so it can't recover them. The deferred design (32 GB FAISS sidecar, 3-4 h build) is heavy enough that it's scheduled to close-by-default on 2026-07-19. A rescoped version — title+lead-paragraph embeddings only, int8-quantized, behind the existing `pip install openzim-mcp[embeddings]` extra and the established sidecar pattern (`openzim-mcp build embeddings <archive>.zim`, mirroring the link-graph sidecar in openzim_mcp/linkgraph/ with UUID staleness refusal) — would cut the artifact to low single-digit GB and make hybrid Xapian+vector RRF fusion practical for ordinary operators. Who benefits: every end user asking definitional/conceptual questions, which is the canonical offline-Wikipedia use case; also makes zim_query's 'tell me about' path dramatically more forgiving. Effort: large (build CLI, sidecar format, query-time fusion, extras packaging, eval), but the RRF/rerank plumbing in rerank.py and synthesize.py already exists to fuse into.

#### Opt-in structured usage telemetry to unblock the roadmap's own decision gates

*impact: medium · effort: small*

What: three open roadmap decisions are explicitly blocked on evidence nobody can cheaply collect — sub-D-3 (intent-parser upgrade) and sub-D-4 (embeddings) close by default 2026-07-19 because 'telemetry is still not collected at the required granularity', and the zim_get compact-default flip is 'telemetry-driven' with no telemetry. Today operators must grep transcripts for the per-call `<!-- intent=… cert=… -->` HTML comment markers. An opt-in `OPENZIM_MCP_TELEMETRY_LOG=path` JSONL event stream (tool, intent class, confidence, compact flag, archive type, reranker hit, latency, zero-hit flag) — plus surfacing the aggregates in the existing zim_health simple_tools_telemetry block and optionally a /metrics endpoint on the HTTP transport (http_app.py) — turns those qualitative triggers into one-liner queries. Who benefits: operators running fleets, and the project itself (every deferred feature decision becomes evidence-based instead of close-by-default). Effort: small — the counter scaffolding (`_track` in simple_tools.py, reranker_* counters) already exists; this is a structured sink, config flag, and docs, with care to keep query text opt-in for privacy.

#### Source-URL provenance on citations and entries

*impact: medium · effort: small*

What: synthesize-mode citations (Citation in tool_schemas.py) and search hits identify content only by archive + entry_path — there is no way for an end user to verify a claim or share a link. ZIM archives carry Source/Name/Flavour metadata sufficient to derive the canonical online URL for most major scrapes (en.wikipedia.org/wiki/<path> for mwoffliner archives, the SE question URL for sotoki, ted.com talk URLs), and archive_types.py already classifies the four types. Adding a best-effort `source_url` field to Citation, SearchHit, and EntryResponse._meta (omitted when underivable) makes every answer verifiable. Who benefits: research-assistant deployments where the human needs clickable, checkable citations — the difference between 'the offline model said so' and an auditable answer; also helps RAG pipelines deduplicate against online sources. Effort: small — a per-archive-type URL-template function keyed off existing detection, NotRequired schema additions (wire-compatible), and tests against the four known scraper layouts.

#### Ship the deferred archive-type preset follow-ons: Wiktionary gloss and TED transcript styles

*impact: medium · effort: small*

What: the presets system (v2.2.0, openzim_mcp/data/presets.toml + archive_types.py) detects all four archive types but only Wikipedia and Stack Exchange have behavior presets; docs/roadmap.md explicitly defers the `wiktionary` (gloss) and `ted` (transcript) summary styles plus the Stack Exchange vote-score-prefix trim to 'a2 — pure data + minor refinement'. A Wiktionary 'tell me about serendipity' today returns a generic first-section summary instead of the part-of-speech + numbered-definitions gloss a dictionary lookup wants; TED summaries should lead with the transcript, not page chrome. Who benefits: users of two of the most-downloaded Kiwix archive families — dictionary lookups are a natural high-frequency LLM query class, and language-learning assistants get materially better answers. Effort: small by the project's own assessment — one new summary_style value plus selection logic per type, preset data entries, and the score-prefix trim; the detection, preset plumbing, and_meta.preset_applied reporting all shipped in v2.2.0.

#### MCP-native image content returns for multimodal clients

*impact: medium · effort: medium*

What: zim_get(binary=True) returns images as a base64 string inside a JSON `data` field (zim/content.py ~line 1311, BinaryEntryResponse.data) — a shape no LLM can actually see. MCP has a first-class ImageContent block, and the per-entry resources (tools/resource_tools.py) already detect native MIME types. Returning image entries as proper MCP image content (and/or emitting resource_link content pointing at the existing zim://{name}/entry/{path} resources from search/links results) would let multimodal clients — Claude, GPT-4o-class — actually look at maps, diagrams, chemical structures, and anatomical figures that are often the most information-dense part of a Wikipedia article. Who benefits: multimodal research assistants and education use cases; ZIM archives are full of curated images that are currently dead weight. Effort: medium — a content-block return path in the zim_get tool wrapper (FastMCP supports mixed content), size/MIME gating, and docs; the MIME detection and truncation logic already exists in resource_tools.py.

#### Kiwix catalog discovery and download CLI (openzim-mcp catalog / download)

*impact: medium · effort: medium*

What: the single biggest onboarding cliff is before the server ever starts — README step zero is 'go download ZIM files from library.kiwix.org yourself', which means picking among dozens of flavours (maxi/nodet/mini, language, date) of multi-GB files. An operator-side CLI verb pair — `openzim-mcp catalog search wikipedia --lang en` (query the Kiwix OPDS catalog) and `openzim-mcp download <name>` (resumable fetch with checksum verify into the allowed directory) — removes it. This fits the project's own precedent exactly: 'offline-first' bans network tools on the MCP surface (docs/roadmap.md out-of-scope), but build-time operator commands are established (`openzim-mcp build link-graph` in cli/build.py). Who benefits: every new operator and every agent-infra team scripting deployments; it also pairs naturally with the archive-type presets, since the catalog metadata tells you the type up front. Effort: medium — OPDS client, progress/resume handling, checksum verify, docs; no runtime-surface change at all.

### Performance

#### Cache per-archive preset/metadata resolution (currently re-probed on every cache-miss search and summary)

*impact: high · effort: small*

_resolve_preset_for_open_archive (zim/archive.py:690) calls_extract_zim_metadata, which probes ~15 M-namespace keys with redirect walks; on old-scheme Wikipedia ZIMs each value is a ~1MB full HTML document parsed with BeautifulSoup in _extract_metadata_text (zim/archive.py:168-220). This runs on EVERY cache-miss search_zim_file_data call (zim/search.py:501), every entry-summary fetch (zim/content.py:1445), and once per archive in every search_all fan-out — even though the result is a tiny (preset, applied_type) tuple that only changes when the file changes. load_presets is lru_cached but the metadata extraction feeding it is not. Fix: store (preset, applied_type) — or the metadata_entries dict — in OpenZimMcpCache keyed by validated_path + archive_stat_token (same pattern get_archive_validation_data already uses at zim/archive.py:590). Expected win: eliminates ~15 entry reads + multiple megabyte-scale bs4 parses from the search hot path; likely the single best ratio of effort to saved latency in the codebase.

#### Pool open Archive handles and Xapian Searchers instead of re-opening per request

*impact: high · effort: medium*

Every tool call opens the ZIM fresh via the zim_archive context manager (/Users/cameron/Developer/openzim-mcp/openzim_mcp/zim/archive.py:226-282) and discards it on exit, so libzim's per-archive dirent cache (default 512 entries, re-applied per open) and the embedded Xapian fulltext/title DB handles never survive between requests. Searcher(archive) is rebuilt per query (zim/search.py:653) and the 0-hit suggestion path opens the archive a second time in the same request (zim/search.py:549). On a 90GB Wikipedia ZIM the archive-open + Xapian-open fixed cost dominates warm-index query latency. Fix: an LRU pool of open Archive handles plus memoized Searcher/SuggestionSearcher per handle, keyed by (path, archive_stat_token) — the stat-token invalidation pattern already exists in bundle.py — with a per-handle lock for thread safety and the zim_operations shim patch points preserved for tests. This is exactly what kiwix-serve does. Expected win: removes tens-to-hundreds of ms of per-call setup and lets libzim's dirent/cluster caches actually accumulate; also a natural place to default-bump the 16 MiB process-global cluster cache (config knob libzim_cluster_cache_max_size_bytes already exists but defaults to None).

#### Stop full-document HTML parsing to produce 200-char search snippets (lazy parse / lxml / snippet cache)

*impact: high · effort: medium*

_get_entry_snippet (zim/content.py:182-242) decodes the entire article body and parses it with BeautifulSoup using the pinned pure-Python 'html.parser' (content_processor.py:116), then renders through html2text — per result, ~10 results per cold search. Wikipedia article HTML is routinely 100KB-1MB, so each search burns ~10 full-document parses to extract lead-paragraph snippets. Three stacking fixes: (a) small — make HTML_PARSER prefer lxml when importable (3-10x parse speedup, optional dependency extra); (b) small — for the snippet path only, truncate the HTML byte string to the first ~64KB before parsing (the lead paragraph is always there; fall back to a full parse when the main-content landmark isn't found in the prefix); (c) medium — cache rendered snippets per entry keyed bundle-style (path + stat token) so distinct queries hitting the same popular entries skip the parse. Expected win: cold-search latency drops by the dominant CPU term; on Wikipedia-scale archives this is most of the post-Xapian time.

#### Parallelize the search_all fan-out across archives

*impact: medium · effort: small*

search_all_data (zim/search.py:3298-3345) iterates the archive list strictly sequentially; each iteration pays archive open + preset probe + Xapian query + snippet parses, so total latency is the sum over N archives and the H22 wall-clock budget gets eaten by serial stragglers. The per-file searches are fully independent (separate payload rows, no shared state) and the underlying work is I/O-heavy C++ that releases the GIL. Fix: submit per-file search_zim_file_data calls to a small bounded ThreadPoolExecutor (4-8 workers) and collect futures with the remaining deadline budget, preserving the existing budget_exceeded semantics and per-row error isolation. Expected win: ~N/workers latency reduction for multi-archive libraries — e.g. a 10-ZIM library drops from ~10x single-search latency to ~2x.

#### Extend the link-graph sidecar into a general precomputed index: titles, lead snippets, degree-ranked results

*impact: medium · effort: large*

The existing sidecar build (linkgraph/builder.py: build_link_graph / iter_article_links) already does the most expensive pass possible — decoding and parsing every content entry's HTML — but persists only inverted link edges + inbound_degree (schema.py). While walking, it could additionally store per-node: entry title, the lead paragraph / pre-rendered snippet (which would make opportunity 3 a pure sqlite lookup on sidecar-bearing archives), and a title->path map. That map would replace the extra SuggestionSearcher round-trips per query in_find_canonical_prefix_match (zim/search.py:2261) and title_promotion.find_title_match, which today re-probe the title index on top of normal search. inbound_degree is already available for popularity-based re-ranking of search/suggestion results at zero runtime cost. Infrastructure is in place: atomic build, uuid fingerprint validation, and the LinkGraphUnavailable graceful-fallback contract in zim/structure.py:961-997. Expected win: snippet and canonical-title work move from per-query CPU to a one-time build; effort is large because it needs a schema version bump, build CLI changes, and fallback paths for archives without a sidecar.

#### Eliminate redundant JSON serialization in the response cache write path and persistence save

*impact: low · effort: small*

Each cache.set of a large payload (entry bundles, search pages — often 100KB-1MB) serializes the value up to three times: _approximate_size_bytes does json.dumps for the byte-budget estimate (cache.py:55-67), set() does a second json.dumps purely to validate JSON-serializability when persistence is enabled (cache.py:335-343), and_save_to_disk re-dumps the entire cache with indent=2 while holding the cache lock (cache.py:540-587), blocking all concurrent cache reads during the save. Fix: serialize once per set and reuse the encoded string for both the size estimate and the validation check; drop indent=2 (smaller file, faster dump); and in _save_to_disk snapshot entries under the lock but perform the json.dump + file write outside it. Expected win: measurable CPU savings on every large cached write and removal of a save-time stall — modest individually, but it sits under every cached operation on Wikipedia-scale payloads.

### Developer experience & docs

#### Move coverage flags out of pytest addopts — they double full-suite time and bury single-file test output

*impact: high · effort: small*

pyproject.toml line 127 hardwires `--cov=openzim_mcp --cov-report=html --cov-report=term-missing --cov-report=xml` into addopts, so every pytest invocation pays for coverage. Measured: full suite is 19.9s with --no-cov vs 36.2s with defaults (~80% overhead), and a 0.7s run of tests/test_cache.py dumps a 74-line term-missing table for the whole package plus rewrites htmlcov/ and coverage.xml. It also makes `make test` and `make test-cov` functionally identical despite CONTRIBUTING presenting them as fast vs. comprehensive. Fix: keep `-m 'not live'` in addopts, move the --cov flags into the `test-cov` target and the CI invocation (test.yml already calls `make test-cov`). While editing that line, add `--strict-markers` — markers are only registered dynamically in tests/conftest.py, so a typo'd marker currently passes silently. This is the single cheapest change for the edit-test inner loop.

#### PR CI never exercises the real-ZIM tests; downloading <15 MB of test data in the main test job closes the gap

*impact: high · effort: small*

The main job in .github/workflows/test.yml runs `make test-cov` without ever running `make download-test-data`, so every test backed by real ZIM files (tests/test_integration.py, test_find_entry_by_title_quality.py — both `pytest.skip('climate-change ZIM fixture not available')`) skips on every PR. The 'Comprehensive Testing' job that runs `make download-test-data-all` is gated `if: github.event_name == 'push' && github.ref == 'refs/heads/main'`, so real-content regressions only surface after merge. The entire zim-testing-suite download is ~14.5 MB (priority-1 files alone are 0.12 MB), and scripts/download_test_data.py already verifies via test_data/zim-testing-suite/manifest.json, making it trivial to wrap in actions/cache keyed on the manifest. Add `make download-test-data` (or -all + cache) to the PR test job so contributors' green PR checks mean what they appear to mean.

#### Delete or implement the three dead test selectors: make test-integration, make benchmark, and the weekly performance workflow all run zero tests

*impact: high · effort: medium*

Verified: `uv run pytest -m integration` collects 0 of 3224 tests, and `pytest -k benchmark --benchmark-only` also collects 0 (the only name matches are in tests/dispatch_eval/, which conftest auto-skips). So `make test-integration` and `make benchmark` (Makefile lines 34-46) silently do nothing. Worse, .github/workflows/performance.yml runs weekly on a cron, finds no benchmarks, then fabricates a placeholder `{"benchmarks": []}` JSON, validates it, uploads it, and 'compares' it on PRs — pure CI theater. test.yml's 'Run slow tests' step even contains the comment 'tolerate it until tests are marked @pytest.mark.slow' and masks exit code 5 on every main push. Fix: add `@pytest.mark.integration` to tests/test_integration.py (and friends) so the target works, then either write real pytest-benchmark tests or delete the benchmark target, the performance.yml workflow, and the slow-tests CI step. Right now these targets actively mislead contributors who run them and see green.

#### Repoint make test-with-zim-data — it is currently a byte-for-byte no-op alias of make test

*impact: medium · effort: small*

Makefile line 32 runs the suite with `ZIM_TEST_DATA_DIR=test_data/zim-testing-suite`, but the `zim_test_data_dir` fixture in tests/conftest.py (lines ~95-110) already falls back to exactly `test_data/zim-testing-suite` when the env var is unset. The target therefore changes nothing, yet CONTRIBUTING.md sells it as 'comprehensive testing' in two places, implying plain `make test` is a lesser run. Meanwhile the thing that actually unlocks more tests — having the priority-2/3 files (wikibooks, the 14 MB wikipedia climate mini) on disk — is a separate, undocumented step (`make download-test-data-all`; default `make setup-dev` only fetches priority 1). Fix: make `test-with-zim-data` depend on `download-test-data-all` so it genuinely mirrors CI's comprehensive job, or delete it and document `make download-test-data-all && make test` instead. Also surface in CONTRIBUTING that real-ZIM tests skip (with clear reasons) when files are absent, so 'N skipped' doesn't surprise newcomers.

#### Accuracy pass on CONTRIBUTING.md: phantom test markers, a changelog instruction that conflicts with release-please, and a Quick Start that bypasses make setup-dev

*impact: medium · effort: small*

Three verified inaccuracies in CONTRIBUTING.md. (1) The 'Test Markers' section documents `@pytest.mark.integration` and `@pytest.mark.slow` and recommends `pytest -m "not slow"` — zero tests in the repo use either marker; the markers that actually exist (`live`, `docker`, registered in tests/conftest.py pytest_configure, plus the `--dispatch-eval` opt-in flag and the `[reranker]`-extra skips that account for most of the 217 skips) are entirely undocumented. (2) 'Before Submitting' step 4 says 'Add changelog entry if user-facing change', but the Release Process section of the same file explains CHANGELOG.md is generated by release-please from conventional commits — a hand-edited entry will conflict with or be overwritten by the release PR. (3) Quick Start step 3 says `python scripts/setup_dev_env.py` while the canonical one-command path is `make setup-dev` (which the script's own output and the Makefile help advertise); the Environment Setup section then repeats the same steps manually. The onboarding flow itself is good — verified that one command produces a working env with test data and a passing 20s suite — the prose just doesn't match it.

#### Make docs/ and the website findable: link roadmap.md and docs/specs from CONTRIBUTING, and document the website dev loop

*impact: low · effort: small*

tests/test_docs_consistency.py calls docs/roadmap.md 'the project's stated source of truth for where are we' and pins its claims to code, yet neither README.md nor CONTRIBUTING.md links to it — CONTRIBUTING's Resources section lists only README/CHANGELOG/SECURITY/CODE_OF_CONDUCT. The six dated design docs in docs/specs/ (the project's design-history convention a new contributor should follow when proposing features) are similarly unreferenced. The website/ Astro app has a deploy workflow (deploy-website.yml) and a Node >=22.12 engines pin, but no docs anywhere on how to run it (`cd website && npm install && npm run dev`), no Makefile target, and no mention in CONTRIBUTING beyond one line in the structure tree — anyone touching the GitHub Pages site has to reverse-engineer package.json. A short 'Documentation map' subsection in CONTRIBUTING (roadmap, specs convention, website dev commands) plus an optional `make website-dev` target fixes all three.

## Low-severity observations (not adversarially verified)

Reported by reviewers but below the verification threshold — treat as leads, not confirmed defects.

**api-ux:**

- `openzim_mcp/tools/zim_get_section_description.md:2` — zim_get_section description advertises "optional subsection inclusion" that has no parameter
- `openzim_mcp/simple_tools.py:1755` — Binary-content guidance tells the model to use removed tool `extract_article_links`
- `openzim_mcp/tools/zim_query_description.md:100` — zim_query Returns doc omits the ToolErrorPayload dict returned on validation/cursor errors with synthesize=False
- `openzim_mcp/tools/zim_search.py:217` — Cross-file fulltext reinterprets `limit` as per-archive limit_per_file without documentation

**ci-packaging:**

- `Dockerfile:20` — Docker image never gets pre-compiled bytecode despite read-only /app and a comment claiming it does
- `.github/workflows/test.yml:11` — test.yml lacks workflow-level permission scoping; test jobs run with default token grant
- `.github/workflows/test.yml:53` — Duplicate Codecov upload steps in test job
- `.github/workflows/performance.yml:51` — Benchmark workflow can never fail: pytest errors swallowed and placeholder results fabricated
- `.github/workflows/docker-publish.yml:65` — docker-publish unconditionally repoints :latest, including for re-dispatched older tags
- `.github/workflows/release.yml:48` — workflow_dispatch tag input interpolated into shell before validation
- `sonar-project.properties:54` — Stale blanket suppression of SHA-pin rule across all workflows in SonarCloud config
- `pyproject.toml:127` — pytest addopts forces coverage instrumentation into benchmark runs
- `Makefile:63` — [tool.bandit] config is dead outside pre-commit; Makefile and CI bandit invocations ignore it

**concurrency:**

- `openzim_mcp/http_app.py:60` — DNS timeout guard in _is_loopback_host is ineffective and mutates process-global socket state
- `openzim_mcp/http_app.py:251` — Non-ASCII Bearer token crashes auth middleware with TypeError, returning 500 instead of 401
- `openzim_mcp/cache.py:573` — Cache persistence uses a fixed .tmp filename — concurrent saves from multiple processes can interleave and corrupt the snapshot

**content:**

- `openzim_mcp/content_processor.py:100` — _join_cell_text inserts block separator only at tag open, concatenating text that follows a closing block
- `openzim_mcp/compact_format.py:102` — Per-snippet cap bypassed when a snippet contains a markdown H2 paragraph
- `openzim_mcp/content_processor.py:1192` — Truncation hint advertises comma-formatted content_offset that the server silently coerces to 0
- `openzim_mcp/compact_renderers.py:457` — render_search_all header claims N hits but silently lists at most 5
- `openzim_mcp/article_body.py:234` — _lead_with_toc loses the TOC on soft-failure structure payloads (no exception raised)

**infra-core:**

- `openzim_mcp/cache.py:525` — _get_persistence_file silently rewrites dotted persistence paths, allowing distinct configs to collide on one file
- `openzim_mcp/cursor_decode.py:93` — Simple-mode cursor decode performs no version check, accepting v1/arbitrary-version cursors the v2 contract says must be rejected
- `openzim_mcp/pagination.py:116` — Cursor.decode lacks the token-length cap the simple-mode decoder applies as adversarial-input defense

**intent:**

- `openzim_mcp/intent_parser.py:397` — search_all extractor requires 'for' that the intent pattern does not, leaving the verb phrase in the query
- `openzim_mcp/intent_parser.py:1012` — Politeness token list strips legitimate trailing title words ('Cheers', 'Tack', 'Domo', 'Danke')
- `openzim_mcp/intent_parser.py:382` — 'query' verb matches the search intent but is never stripped by the extractor
- `openzim_mcp/intent_parser.py:1756` — Misspelling possessive retry only handles ASCII apostrophe, missing curly ’s

**performance:**

- `openzim_mcp/cache.py:337` — cache.set JSON-serializes every value twice when persistence is enabled

**security:**

- `openzim_mcp/simple_tools.py:521` — Synthesize error envelopes leak unsanitized absolute filesystem paths

**server:**

- `openzim_mcp/timeout_utils.py:92` — TimeoutError raised inside the worker function is misreported as an operation timeout
- `openzim_mcp/timeout_utils.py:36` — OPENZIM_MCP_TIMEOUT_MAX_WORKERS is parsed unvalidated at import time
- `openzim_mcp/server.py:61` — IPv6 literal hosts never receive the ':*' wildcard-port variant in the Host allowlist
- `openzim_mcp/tool_schemas.py:5` — tool_schemas contract does not match registered handlers: advanced tools expose no output schema; zim_query output is wrapped in {"result": ...}

**simple-tools:**

- `openzim_mcp/simple_tools.py:2499` — tell_me_about namespace-path redirect false-positives on real slash-containing topics (A/B testing, I/O scheduling)
- `openzim_mcp/simple_tools.py:2239` — Canonical-title splice inflates shown row count past the reported total when results are under the limit
- `openzim_mcp/simple_tools.py:632` — list_files responses bypass the intent-telemetry comment, compact size cap, and footer
- `openzim_mcp/simple_tools.py:1347` — Broad exception catches mislabel non-lookup failures as 'Article not found' and suggest recovery commands that will fail the same way

**synthesize:**

- `openzim_mcp/rerank.py:143` — Compact rerank passthrough truncates results to final_top_k without reranking
- `openzim_mcp/synthesize.py:936` — Pass-0 fallback hit's promised lead-text backfill does not exist — answer can lead with an empty passage
- `openzim_mcp/synthesize.py:266` — _locate_passage lockstep walk is off by one when the haystack starts with whitespace
- `openzim_mcp/synthesize.py:380` — ASCII-only affinity tokenizer disables section-affinity boost for non-Latin archives despite 'alphanumeric' claim

**tests:**

- `tests/test_async_operations.py:262` — test_operations_run_in_thread asserts nothing about the code under test
- `tests/test_zim_get.py:18` — Identical server()/_patch_async_ops fixtures copy-pasted across 10 tool test files
- `tests/ml/test_ml_config.py:27` — Broad pytest.raises(Exception) hides what pydantic validation tests actually check
- `tests/test_subscriptions.py:143` — Stale comment in watcher test asserts the opposite of current watcher behavior
- `tests/test_per_entry_resource.py:524` — Event-loop heartbeat test depends on wall-clock scheduling (>=8 ticks of 50ms in 0.5s)

**title-chain:**

- `openzim_mcp/chain_detection.py:154` — re.IGNORECASE nullifies the (?=[A-Z]) capital-letter guard on the sentence-period chain connector
- `openzim_mcp/chain_detection.py:727` — Conjunction-prefix strip on non-first halves mangles titles starting with Or/And and silently aborts multi-entity detection
- `openzim_mcp/chain_detection.py:671` — Slash-compound guard only protects bare compounds; embedded TCP/IP-style compounds get split in multi-entity decomposition
