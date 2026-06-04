# Synthesize 2-token tail-hijack defect class — design

**Date:** 2026-06-03
**Issues:** #252 (`Einstein's theory → Theory`), #253 (`connection refused → Refused`)
**Scope:** `openzim_mcp/synthesize.py` + `openzim_mcp/title_promotion.py` internals only. No tool-surface or response-contract change.

## Problem

`synthesize` promotes an off-topic generic article to rank 1 for several short queries, burying the relevant content. Confirmed live against the deployed v2.1.6 server (dual-archive: `wikipedia_en_all_maxi_2026-02` + `superuser.com_en_all_2026-02`):

| Query | Promoted rank-1 (wrong) | Correct canonical (buried/absent) |
| --- | --- | --- |
| `connection refused` | `wikipedia/Refused` (punk band, score 1.0) | `superuser/.../ssh-channel-3-tunnel-connection-refused` (rank 2) |
| `Einstein's theory` | `wikipedia/Theory` (score 1.5) | `Theory_of_relativity` (absent from results) |
| `einstein theory` | `wikipedia/Theory` (score 1.5) | same as above — identical output |
| `Plato's cave` | `wikipedia/Cave` (score 1.0) | `Allegory_of_the_cave` (rank 3) |

The two filed issues are instances of one class: a **2-token tail-hijack** — the query's last token (`refused` / `theory` / `cave`) exact-title-matches a generic article, which is promoted at score 1.0 (title-match base) × up-to-1.5 (section-affinity boost).

Counter-evidence that bounds the fix: `ssh connection refused` (3-token) is already correct (returns the superuser SSH articles, no `Refused`) — the v2.1.4 tail-hijack guard works for ≥3 tokens. And the standalone `find article titled Einstein's theory` resolves correctly to `Theory_of_relativity` (score 1.00) — so the correct canonical IS retrievable; only the synthesize promotion path lands on the generic tail.

## Root cause

**Enabling cause:** the `< 3 token` floor in `title_promotion._accept_non_possessive` (`title_promotion.py:441`): `if len(topic_tokens_seq) < 3: return True`. The v2.1.4/#250 tail-hijack rejection only fires for 3+ token queries, so any 2-token query's generic-tail promotion is waved through. The floor exists to protect legitimate 2-token tails (`planet earth → Earth`, `Berlin Germany → Berlin`).

The class splits into two sub-cases with **different clean fix sites**:

- **Sub-case A — cross-archive** (#253). `connection refused → Refused` is a Wikipedia hit while the relevant content is in superuser. `_promote_title_match` tags the hit `promoted`, and `_drop_cross_archive_leakage` (`synthesize.py:1340`) **unconditionally exempts** `promoted` hits from the cross-archive path-overlap floor, so `Refused` survives at rank 1.

- **Sub-case B — same-archive** (#252 + `Plato's cave` + `einstein theory`). All hits are Wikipedia, so the cross-archive leak gate cannot see it. The promotion path lands on the generic single-token tail (`Theory`/`Cave`) instead of the more-specific full-query canonical (`Theory_of_relativity`/`Allegory_of_the_cave`). The filed-issue hypothesis (a possessive `match_type` fallback) is **disproven**: the standalone title lookup resolves correctly, so the divergence is between synthesize's promotion path and the working title-lookup, NOT in `find_title_match`'s backend. The exact normalization point (apostrophe handling in topic extraction vs `find_title_match` `min_score`/`match_type`) is pinned in implementation step 1.

## Decided strategy

- Sub-case B: **resolve to the correct canonical** (surface `Theory_of_relativity` / `Allegory_of_the_cave` at rank 1), not mere suppression.
- Carve-out: **cross-archive-aware / more-specific-canonical-aware only** — preserve legitimate same-archive 2-token tails (`planet earth → Earth`), where no more-specific canonical exists.

## Fix 1 — cross-archive leak gate (Sub-case A, #253)

In `_drop_cross_archive_leakage`, replace the unconditional `promoted` exemption at the loop body (`synthesize.py:1340`):

- A `promoted` hit from the **primary** archive keeps the exemption (unchanged).
- A `promoted` hit from a **non-primary** archive keeps the exemption **unless** it is a single-token tail-hijack shape (canonical is one token equal to the query's last token, via the existing `is_tail_hijack_shape` predicate). In that case it is **dropped outright** — it is neither exempted nor saved by the path-overlap floor.

The path-overlap floor cannot rescue this case and must be bypassed: `Refused`'s only query overlap is the tail token `refused` itself (`overlap == 1`, the same token that mis-promoted it), so an overlap floor of 1 would keep it (issue #253 notes this explicitly). The discriminator is therefore the **shape + provenance** (single-token-tail canonical from a non-primary archive = the leak signature), not lexical overlap. This preserves the lexically-disjoint multi-token promoted exemption (`darwins evolution → On_the_Origin_of_Species` — multi-token canonical, not tail-hijack shape) and every same-archive (primary) promotion. Low risk.

Edge case checked: a legitimate same-archive 2-token tail like `planet earth → Earth` keeps its promotion because that archive is **primary** (highest query/path overlap), so the non-primary condition never fires for it.

## Fix 2 — resolve correct canonical (Sub-case B, #252 class)

**Step 1 (pin the divergence).** Reproduce with a local mock of `zim_operations.find_entry_by_title_data` encoding the live-observed result shapes, plus 2-3 targeted live probes (`Newton's gravity`, `Marie Curie's discovery`, bare-tail lookups) to confirm whether pass-0 receives the specific canonical and rejects it (possessor-not-in-path gate) or receives the generic tail directly, and whether the apostrophe survives to `_promote_title_match`.

**Step 2 (fix).** Make the full-query canonical win over the generic single-token tail. When a candidate promotion's canonical is a single generic token equal to the query tail, first check whether the **full query** resolves (via the title index) to a more-specific multi-token canonical; if so, promote that canonical instead. When no more-specific canonical exists (`planet earth → Earth`), keep the bare tail — this is the cross-archive-aware/more-specific carve-out that protects the legitimate case.

The precise edit (a new shared `title_promotion` predicate vs an inline check in `_promote_title_match` pass-0) is settled in the implementation plan once Step 1 pins the path, so the change stays in one place shared by the tell_me_about and synthesize paths (the established anti-drift pattern: `accept_tail_promotion` / `passes_z4`).

## Testing

These defects are **not reproducible from a local checkout** (they depend on the live 118 GB title index) — the reason they were deferred. Validation is three-layered:

1. **Unit tests with a mock `zim_operations`** encoding the live-observed `find_entry_by_title_data` shapes for `einstein's theory`, `plato's cave`, `connection refused`. Assert: correct canonical at rank 1 (Sub-case B) / leak dropped (Sub-case A).
2. **Invariant regression tests (must stay green):** `planet earth → Earth`, `Berlin Germany → Berlin`, `ssh connection refused → superuser` (3-token guard), `darwins evolution → On_the_Origin_of_Species` (leak-gate multi-token exemption). Reuse/extend the existing `tests/` suites for `title_promotion` and `synthesize`.
3. **Live before/after reprobe** against the deployed server — the only true end-to-end validation, run before merge. Probe set: the four defect queries + the four invariants.

## Non-goals / risk

- No reranker, no semantic retrieval, no tool-surface change.
- If Step 1 shows the correct canonical genuinely isn't retrievable for a given query, that query degrades to **suppression** (drop the junk, fall back to BM25) — never a worse answer than today.
- CI gate awareness (per project memory): full `make lint` (package + tests), Sonar S5852/ReDoS on any new regex, CodeQL uninitialized-local, Windows cp1252.
