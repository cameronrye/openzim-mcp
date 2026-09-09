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
| Malformed-frame classification on the `sse` transport | Not wired, recorded. `MCPServer.run(transport="sse")` builds its own ASGI app inside the SDK, so no middleware this server adds reaches it. Covering it means reimplementing `run_sse_async`'s uvicorn and transport-security setup for a transport already deprecated for removal in 4.0.0. The gap is named where the gate is wired, in the transport table, and in the deprecation warning an operator sees when they choose SSE — and asserted by tests, so it cannot be re-discovered as a surprise. |

## Still open

Recorded rather than closed, in rough order of value:

- **Ranking headroom.** Both reranker configurations put a relevant article
  at #1 only about 64% of the time and carry ~2 off-topic entries in every
  top-5 — a supplement monograph outranking "High blood pressure
  medications", a raw `.srt` caption file in a top-5. Demoting crawl
  artefacts (`/category/`, `/page/N/`, `/imagepages/`) has to land on the
  title-suggest pool *and* the `zim_query` disambiguation chooser together,
  or the two surfaces disagree about what an artefact is; and it moves
  `results[0]`, which the canonical-splice promotion reads under a hard
  score gate. Needs corpus validation paired across both halves.
- **The optional reranker is unmeasured.** 50 queries, 44 eligible, 132
  blind judgments: not one metric approaches significance, while the extra
  costs ~1.1 GB of model and doubles query latency. Publish a measured
  number, say in the docs that the improvement is unmeasured, or drop the
  extra. (44 queries on two archives rules out a large effect, not a small
  one, and says nothing about Wikipedia-shaped corpora.)
- `zim_browse(mode='page')` renders a `preview` that is empty on 99.8% of
  IEP rows, making the default mode far slower than `mode='walk'` for
  identical rows.
- The sidecar builder parses raw entry bytes while the bundle scopes to the
  main-content landmark, so outbound and inbound describe slightly different
  graphs; inbound ranks on raw `inbound_degree`, a signal boilerplate
  maximises.
- Cross-archive fan-out has no cross-archive ranking.
- Rate-limit pricing charges a wide search less than a batch fetch that does
  less work.

## Two things the process itself surfaced

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
