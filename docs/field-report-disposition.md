# Real-world field report — disposition

**Status: closed out.** This records what a real-world sweep of the preceding
release found, what was fixed, and — the part worth keeping — what was
deliberately *not* fixed and why. The sweep itself was a point-in-time run;
this file is the durable half. The release it swept, and the commits that
answered it, are pinned by [CHANGELOG.md](../CHANGELOG.md) and by the
`field report (fid N)` comments the fixes left in the source.

The sweep drove 5,012 live tool calls against two real archives (1.9 GB of
MedlinePlus and the Internet Encyclopedia of Philosophy) through a freshly
spawned binary over stdio, and produced 138 findings across 12 dimensions.
An adversarial panel then reproduced or refuted each one, and a second pass
audited the fixes themselves and raised 28 problems with them.

## The shape of it

One defect shape recurred often enough to be worth naming: **the server
computes the right answer and loses it on the way out.** It knew a result set
was weak and did not say so. It had a canonical-title index that answers
instantly and did not consult it from the search tool. It had an exact
inbound link graph and answered the inbound question with outbound data. A
namespace rejection was rendered as an empty page. A cache hit rate described
the caller's `limit` rather than the cache.

The second theme is **simple mode**. It is the documented default and a
one-tool surface, so every defect there is unrecoverable: there is no second
tool to fall back to, and the tool's own description block *is* the API.

## What shipped

Eighteen commits, `f19bfcb`..`26453df`. The first three closed 75 findings;
the remainder closed the audit's residues and the findings the first pass had
left blocked on file ownership.

Two of the fixes were defects in the fix work itself rather than in the
released server: a
furniture-heading strip that deleted the rest of an article when no peer
heading followed (invisible on the shipped corpus, where furniture always
sits last), and a snippet-emphasis fix whose own repro cases were unchanged
by it.

### The follow-up

A second branch took three of the six items the first left open.

**Crawl artefacts sink below articles (fid 71).** Paths matching
`/imagepages/` (image-caption stubs), `/languages/` (translation hubs) or
ending `.srt` (subtitle sidecars) now sink below real articles on four
surfaces: single-archive and cross-archive title mode, suggest mode, and the
`zim_query` chooser. Measured on the shipped MedlinePlus archive with 40
topic queries at `limit=5`, with the rate limiter and the cache off, before
and after the change:

| Surface | Artefact at #1 | Pages with an artefact above an article |
| --- | --- | --- |
| Title | 4 → 1 | 30 of 40 → 0 |
| Suggest | 6 → 1 | 29 of 40 → 0 |
| Chooser | 7 → 1 | 7 of 39 → 0 |

The remaining #1 on each surface is a page with nothing else on it:
`migraine headache` in title and suggest, whose only row is an image stub,
and `swollen glands` in the chooser, whose only strong match is an image
stub — which `zim_query` still fetches as the answer.
The artefact share of the rows (26.1% title, 26.6% suggest) does not move,
and must not: the demote reorders the page it is handed and never evicts
from it. On IEP, the `/category/` topic pages stay #1 for the four queries
they answer.

Getting there took three attempts at two placements. Demoting inside the title lookup
reordered the page the canonical-title promotion reads as
score-descending, so the probe blanked and a weaker hit was hoisted to #1
at a fabricated score of 1.0. Moving the demote to the response edge fixed
that call and broke the next one: the edge rewrote the *cached* page in
place, so a second identical `title 'swollen glands'` at `limit=3` — the
page size the promotion probe reads — brought the fabricated 1.0 back. The edge now demotes a copy. A "24.5% → 12.8%"
artefact figure recorded along the way was measured on the first
placement, and does not describe the shipped code.

**"What links here?" stops answering with the navigation (fid 86, ranking
half).** A linker whose inbound degree is at least half the sidecar's node
count — on sidecars of 50 or more nodes — is site furniture and sinks to
the end. Reader-only: no rebuild and no schema bump. On the IEP sidecar
(1,187 nodes, threshold 594) the 33 nodes over the line are the home page,
the 26 alphabet pages, five site pages and the RSS feed; the best-linked
article, `plato/`, sits at 106. Of the 919 article targets — targets not
themselves furniture — with at least one non-furniture linker, furniture led
654 before and leads none after; the 235 linked only by furniture still lead
with it, since a reorder cannot change them.

**The reranker docs stop claiming an improvement.** The only blind
evaluation — 50 queries, 44 rerank-eligible, 132 judgments on two warc2zim
archives — found no metric reaching significance (55 preference votes
against 52, p = 0.85; a relevant article at #1 in 64.4% against 62.9%),
while median latency roughly doubled and the model costs about 1.1 GB. The
reranking page now says that, with the numbers; the install page carries the
hedge and the latency cost, and links to them.

### The fulltext follow-up

A third branch took the first "Still open" item: crawl artefacts on the
surfaces the 64% figure was measured on.

**Crawl artefacts sink on fulltext too (fid 71, second half).** The same
three shapes now sink below real articles on every fulltext-shaped route:
`zim_search(mode="fulltext")` single-archive, filtered and cross-archive;
`zim_query` search, filtered search and "search all files", compact and
legacy; and `synthesize=True`. Measured on the shipped MedlinePlus archive
with the same 40 topic queries at `limit=5`, rate limiter, cache and
reranker off, `main` against the branch, every route driven through an MCP
client session:

| Surface | Artefact at #1 | Pages with an artefact above an article |
| --- | --- | --- |
| Fulltext page 1, each of seven routes | 4 → 0 | 14 of 40 → 0 |
| Fulltext page 2 (`offset=5`), each of two routes | 2 → 0 | 8 of 40 → 0 |
| `synthesize=True`, first five citations | 1 → 0 | 12 of 40 → 0 |

Every changed page is exactly the stable demote of `main`'s page on the
same route: the same rows, so the artefact share (12.0% of page-1 rows,
7.5% of page 2) does not move, and `total`, `done`, `next_offset` and
`source_consumed` match on every structured page. Synthesize cites the same
205 passages across the 40 answers; the 25 that are scraper output now come
after the articles in each answer, which is why the first-five share falls
from 12.5% to 11.5%. The four #1s were `/languages/` hubs for
`hepatitis b`, `covid-19`, `chickenpox` and `shingles`; each now leads with
the topic article. `tell me about`, which reads the same fulltext page,
returns byte-identical text on all 40 queries, and nothing moves on the
four IEP queries. The live suite gives 26 passed and 11 skipped on both trees. With
the in-memory cache on and every call made twice, 967 of 968 comparisons
match the cache-off run on both trees; the one that does not is a
cache-dependent title completion from the first pass, recorded under
"Still open".

The placement is the opposite of title mode's, for a reason worth keeping.
Title mode demotes at the response edge because its canonical promotion
probe reads the title page as score-descending. Fulltext rows carry no
score and no consumer reads their order as one, so the demote runs where
the page is assembled — `_perform_search`, and `_build_filtered_results`
for both filtered renderers — before the cache write, so a cached page can
never disagree with a cold one. It then runs again after each step that
reorders a page later: the two canonical-title splices (whose list-article
demote moves articles below the artefacts, and whose title-index hit can
itself be an image stub), the cross-encoder rerank on both `zim_query`
routes, and synthesize, once on the selected hits and once on the final
passages, after the rerank and section-affinity boost that re-sort them on
score. The fulltext search caches now hold a different order for the same
archive, so the render epoch moved r3 → r4, and a new pin on the order
those caches hold fails when the wiring changes without a bump.

**A translation the caller asks for is not demoted (found in review).** The
40-query measurement above asked only for topics, so it could not see what
the demote does to a caller who asks for the hub itself. Review measured it
on the same archive with 700 queries — 50 hub topics × Spanish, Chinese,
French, Korean, Vietnamese, Arabic and Russian × both "<topic> <language>"
and "<topic> in <language>" — cache warm, the real code of both trees. On
fulltext the requested hub was #1 on 332 of 700 on `main` and on 106 with
the demote: it lost #1 on 226, and on about 190 of those the new #1 was
unrelated ("asthma in children chinese" → Dong Quai, "breast cancer in
french" → Maritime Pine), because fulltext matches the language word inside
product names and citations. On `synthesize=True`, 147 "<topic> in
<language>" queries in Spanish, Chinese and French, the hub was the first
citation — the featured article — on 63 on `main` and on 7 with the demote,
and the requested language's section dropped out of the answer. Title,
suggest and `tell me about` never surfaced the hub for this phrasing on
`main`, so fulltext was the only surface that answered these queries at all.

The fix is an exemption, not a new ranking. A query asks for a translation
when, lowercased and stripped of surrounding whitespace and trailing
punctuation, it ends with one or more language words — MedlinePlus's
languages, multi-word names such as "cape verdean creole" included, plus
"simplified", "traditional", "mandarin", "cantonese", "persian" and
"filipino"; not "english" — optionally preceded by "in", with a topic left
before them. The topic's key is that text with every non-alphanumeric
character removed, and the one row exempt from the demote is
`/languages/<key>.html`, matched on the path because some stored hub titles
are cut at the apostrophe ("Alzheimer") while the slug never is. Exempt
means not demoted: the hub keeps the position the archive ranked it at and
is never promoted past an article above it. Every demote call site — the
fulltext ones above and the title, suggest and chooser ones from the first
pass — is handed the same query string its cache key is built from, so a
cached page cannot disagree with a cold one. The render epoch stays r4,
which has not shipped; the code pin was re-pinned, and the order pin gained
a translation query.

The limits are deliberate. Suffix only: "japanese encephalitis" and "german
measles" lead with the language word and ask about the disease, so they
exempt nothing, and neither do "chinese" or "in chinese", which name no
topic. Image stubs, `.srt` sidecars and other topics' hubs still sink for
every query, and so do the per-language portals and the index and help pages
beside them (`languages/french.html` for "health information in french"):
the accepted-cost row for portals under "Deliberately not fixed" stands.

TODO(owner): re-measure the 700 fulltext and 147 `synthesize=True`
translation queries on the fixed branch and record the numbers here.

## Deliberately not fixed

Each of these was reproduced and understood. They are decisions, not
omissions — reopen one only with evidence that changes its premise.

| Finding | Decision |
| --- | --- |
| `mode="title"` case-folding to collapse `/Sartre-ex/` and `/sartre-ex/` | Declined. Case-folding the dedup key applies to every archive, and on mwoffliner archives only the first letter of a title is case-insensitive: `A/Bus` and `A/BUS` are different articles. A correctness regression on the main archive class to fix a warc2zim scrape artifact rated low. |
| Aggregate byte ceiling on the advanced surface | Declined. The per-entry ceiling is `max_content_length`; adding an aggregate one changes the contract of every advanced tool at once, and the worst case needs a 50-path batch of an archive's largest articles. The two amplifiers underneath it (the missing binary ceiling, the unguarded tokenisation) were fixed. |
| `_meta.chars` matching the wire serializer | Declined. It measures the payload without `indent=2` and excludes `_meta` itself, so it under-reports the wire by ~6.5%. Matching it changes a contract seven test files pin, for an advisory field no tool description mentions, no `outputSchema` publishes, and which arrives inside the payload it measures — a client that cares can measure the text it already holds. |
| Widening the prompt-injection fence beyond its ten intents | Declined. The scope is published in `security-best-practices.mdx`, which states the fence is provenance labelling and not a filter, and a docs gate asserts documented == live. Widening it silently falsifies a published security claim. |
| Adding `what`/`how`/`work` to the meta-only filler tokens | Declined. `_is_meta_only_query` documents its bias — the cost of treating a real query as filler is much higher than the reverse — and `what` alone would swallow every "what is X". |
| Falling back to the whole document when the main-content landmark is small | Declined. Reverses a deliberate decision (PR #374 D10/D11) and re-opens chrome leakage on every archive to help one WordPress-themed front page. |
| Re-adding `title`/`content_type` to batch items | Declined. Removed deliberately in PR #374; the bodies are self-identifying and the caller supplied the paths. |
| Worker processes / single-flight coalescing for the HTTP transport | Declined. Horizontal scaling is the documented answer and the replica is the worker unit. Coalescing means per-key in-flight futures across a lock also touched from `atexit` and a cleanup thread — real deadlock risk, for a thundering-herd shape rare on a personal offline server, with no load-test harness in CI to defend it. |
| Stripping the site-name suffix from browse titles | Declined. `strip_site_suffix` splits only on `" \| "`, so it would clean the IEP rows and ~553 MedlinePlus rows but none of the ~10,678 `": MedlinePlus …"` ones — and the same suffix rides `zim_search` and `zim_links` rows, so stripping it in browse alone desynchronises the surfaces. |
| The builder-scoping half of fid 86 | Declined. Feeding the sidecar builder `select_main_content` would make outbound and inbound describe the same graph, but it inherits the furniture strips, which on MedlinePlus delete "Related Health Topics": 165 of 174 strip-only removals in a 250-page sample were genuine topic pages. That trades an inconsistency between the two directions — `c/`'s inbound list includes `hume-causation/`, whose outbound list omits `c/` — for the loss of MedlinePlus's best inbound signal, and would invalidate every sidecar in the field. |
| Dropping the reranker extra, or publishing an improvement figure | Declined. "No measured effect at n=44 on two warc2zim archives" is not "no effect" — the sample rules out a large effect, not a small one, and says nothing about Wikipedia-shaped corpora — and a published figure would be invented. The docs give the measured numbers and let a reader price the trade. |
| Demoting index pagination (`/page/N/`) as a crawl artefact | Declined on measurement. It matched nothing on MedlinePlus and two IEP entries, both false positives: `category/…/metaphysics/page/2/` continues the topic index `/category/` is kept for, 19 more articles with no overlap. |
| Over-fetching so a small title or suggest `limit` evicts artefacts | Declined. The demote reorders the page the data layer returns, so at `limit` 1 or 2 a page holding no real article still leads with an artefact, and a larger `limit` can change which row leads. Over-fetching means recomputing `total`, `done` and the paging arithmetic, in the same spot where the first placement broke promotion. Documented in the API reference. Fulltext is declined on the same grounds and one more: it pages, so pulling an article forward from page two would have to move `next_offset` and the cursor with it, and a walk would then see pages whose boundaries depend on what the demote found. |
| Exempting MedlinePlus's per-language portals from `/languages/` | Accepted cost. The shape also matches about 53 "Health Information in *Language*" portals, which now sink below other rows on their page — `title 'Italian'` leads with a recipe, and fulltext does the same. They are still returned. Telling a portal from a translation hub needs a language list or MedlinePlus-specific title matching. |
| Versioning the inbound cursor across the ranking change | Recorded. A cursor minted before the upgrade resumes at the same offset in the new order, so a paging walk that spans the upgrade can repeat or skip a row. Within one server version paging is exact. Rejecting every pre-upgrade cursor is a contract change for a one-time effect. |
| Malformed-frame classification on the `sse` transport | Not wired, recorded. `MCPServer.run(transport="sse")` builds its own ASGI app inside the SDK, so no middleware this server adds reaches it. Covering it means reimplementing `run_sse_async`'s uvicorn and transport-security setup for a transport already deprecated for removal in 4.0.0. The gap is named where the gate is wired, in the transport table, and in the deprecation warning an operator sees when they choose SSE — and asserted by tests, so it cannot be re-discovered as a surprise. |

## Still open

Recorded rather than closed, in rough order of value:

- **Ranking headroom beyond artefacts.** Both reranker configurations put a
  relevant article at #1 of `zim_query` search results only 63–64% of the
  time. That was measured before either artefact demote and has not been
  measured since. Scraper output no longer leads or outranks an article on
  any fulltext surface (see the fulltext follow-up), but the evaluation's
  other failure shape — real articles in the wrong order, such as a
  supplement monograph outranking "High blood pressure medications" — is
  untouched.
- **fid 70's title completion needs the cache.** A search row's truncated
  title ("Alzheimer" for "Alzheimer's Disease") is completed from the
  snippet render the row just cached, so with the cache disabled no title
  is completed, and `tell me about alzheimer's disease` fetches the
  encyclopedia article instead of offering the three-way chooser the default
  configuration offers. Found while comparing cache-on and cache-off runs
  for the fulltext follow-up; identical on the release before it.
- `zim_browse(mode='page')` renders a `preview` that is empty on 99.8% of
  IEP rows, making the default mode far slower than `mode='walk'` for
  identical rows.
- Cross-archive fan-out has no cross-archive ranking. Cross-archive title
  mode now sinks artefacts, but rows from different archives are still
  interleaved by per-archive rank scores that mean nothing across archives.
- Rate-limit pricing charges a wide search less than a batch fetch that does
  less work.
- `zim_query "find article titled X"` is a title surface the artefact demote
  does not reach, so the same title-index lookup comes back in a different
  order there than from `zim_search` title mode.

## Three things the process itself surfaced

**Tests keep shipping vacuous.** Every fix here was mutation-proven, and the
mutation pass repeatedly caught what the tests did not: a guard made
unreachable by an anchored regex, an assertion that passed because "202"
also occurs inside "2026-07-28", a drift guard that passed while both of the
call sites it existed for were unmarked, and a cross-transport test that
compared each transport only against itself. Writing the test first is not
enough; reintroducing the defect is the only evidence that the test works.

**The corpus hides shapes the fixtures do not have.** Several defects here
were invisible to a fixture-shaped suite and to a 390-page corpus sweep,
because the corpus is regular: MedlinePlus always puts furniture last, so a
strip that ate everything after it never had anything to eat. Both live
archives are `generic` zimit/warc2zim archives, so nothing here speaks to
Wikipedia- or Stack Exchange-shaped content.

**The cache is part of the surface.** The follow-up's artefact demote
rewrote a cached page in place, and every test of it passed, because every
test ran with the cache off and called once. It was found by re-measuring on
the real archive with the default in-memory cache on and asking the same
question twice. A fix that touches what a cached value holds needs a
two-call test with the cache enabled, and needs the render epoch bumped for
any cache that stores its output.
