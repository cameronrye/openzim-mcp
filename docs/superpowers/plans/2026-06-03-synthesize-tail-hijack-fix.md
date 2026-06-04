# Synthesize 2-token Tail-Hijack Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop `synthesize` promoting an off-topic generic article (`Refused`, `Theory`, `Cave`) to rank 1 for short queries, and surface the correct canonical instead.

**Architecture:** Two independent fixes in the synthesize path. Fix 1 closes the cross-archive leak gate against single-token-tail promotions from a non-primary archive (#253). Fix 2 threads the *original* (apostrophe-preserving) query into `_promote_title_match` and adds a "tail-rescue": before accepting a generic single-token tail promotion, probe the full original query for a more-specific multi-token canonical and promote that instead (#252 + `Plato's cave` class).

**Tech Stack:** Python 3.12, pytest, `unittest.mock`. Pure stdlib; no new deps.

**Reference spec:** `docs/superpowers/specs/2026-06-03-synthesize-tail-hijack-fix-design.md`

**Live oracle (deployed v2.1.6 server, dual-archive wiki + superuser) — pinned facts the mocks must encode:**
- `find_title_match("einstein's theory")` (apostrophe preserved) → `Theory_of_relativity` @ 1.00.
- `find_title_match("einstein theory")` (stripped) → `The_Einstein_Theory_of_Relativity` @ 0.95 (a film), `Theory_of_relativity` only @ 0.63.
- `find_title_match("plato's cave")` / `("plato cave")` → `Allegory_of_the_cave` @ ~0.95.
- `find_title_match("connection refused")` on wiki → `Refused` (single token); the relevant content is in superuser.
- `find_title_match("planet earth")` → `Earth` (single token — the carve-out: no more-specific canonical, must stay promoted).

---

## File Structure

- Modify: `openzim_mcp/title_promotion.py` — add `is_single_token_tail_match(promoted, topic)` (floor-free shape predicate) for Fix 1.
- Modify: `openzim_mcp/synthesize.py` — `_drop_cross_archive_leakage` (Fix 1); `_promote_title_match` signature + tail-rescue (Fix 2); `synthesize_query` signature to forward `original_query`.
- Modify: `openzim_mcp/simple_tools.py` — `_handle_synthesize_query` passes the raw user query as `original_query` into the synthesize call.
- Test: `tests/test_post_v2_1_4_beta_fixes.py` — new sweep regression file (sibling of `test_post_v2_1_3_beta_fixes.py`).
- Reuse: `tests/_promote_fixtures.py` patterns; `tests/test_synthesize.py` for `_promote_title_match` / `_drop_cross_archive_leakage` call shapes.

---

## Task 1: Fix 1 — leak gate drops non-primary single-token-tail promotions

**Files:**
- Modify: `openzim_mcp/title_promotion.py` (add predicate after `is_tail_hijack_shape`, ~line 480)
- Modify: `openzim_mcp/synthesize.py:1339-1342` (the kept-loop in `_drop_cross_archive_leakage`)
- Test: `tests/test_post_v2_1_4_beta_fixes.py`

- [ ] **Step 1: Write the failing predicate test**

In `tests/test_post_v2_1_4_beta_fixes.py`:

```python
from openzim_mcp.title_promotion import is_single_token_tail_match


def test_single_token_tail_match_fires_on_2token_query():
    # "connection refused" -> "Refused": the #253 shape the floored
    # is_tail_hijack_shape MISSES because the query has only 2 tokens.
    assert is_single_token_tail_match({"path": "Refused"}, "connection refused")


def test_single_token_tail_match_ignores_multitoken_canonical():
    # darwins evolution -> On_the_Origin_of_Species: multi-token canonical,
    # the legitimate lexically-disjoint promotion exemption.
    assert not is_single_token_tail_match(
        {"path": "On_the_Origin_of_Species"}, "darwins evolution"
    )


def test_single_token_tail_match_requires_tail_position():
    # head-position single token is not a tail hijack ("Berlin Germany"->Berlin)
    assert not is_single_token_tail_match({"path": "Berlin"}, "berlin germany")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_post_v2_1_4_beta_fixes.py -k single_token_tail_match -v`
Expected: FAIL with `ImportError: cannot import name 'is_single_token_tail_match'`.

- [ ] **Step 3: Implement the predicate**

In `openzim_mcp/title_promotion.py`, after `is_tail_hijack_shape` (~line 480):

```python
def is_single_token_tail_match(promoted: Dict[str, Any], topic: str) -> bool:
    """Floor-free sibling of :func:`is_tail_hijack_shape`: the promoted
    canonical is a single token equal to the topic's LAST token,
    regardless of topic length.

    ``is_tail_hijack_shape`` carries a ``< 3 token`` floor (the b4
    ``Berlin Germany`` carve-out) because, on the tell_me_about SOURCE
    gate, a 2-token tail can be legitimate. The cross-archive LEAK gate
    has an extra signal — provenance — so it can safely act on the
    2-token shape too (``connection refused`` -> ``Refused`` from a
    NON-PRIMARY archive). Used only by :func:`_drop_cross_archive_leakage`;
    the source gate keeps the floored predicate.
    """
    topic_tokens_seq = _TAIL_TOKEN_RE.findall(topic.lower())
    if not topic_tokens_seq:
        return False
    cand_tokens_seq = _TAIL_TOKEN_RE.findall(str(promoted.get("path", "")).lower())
    return len(cand_tokens_seq) == 1 and cand_tokens_seq == topic_tokens_seq[-1:]
```

- [ ] **Step 4: Run predicate test to verify pass**

Run: `uv run pytest tests/test_post_v2_1_4_beta_fixes.py -k single_token_tail_match -v`
Expected: 3 PASS.

- [ ] **Step 5: Write the failing leak-gate integration test**

Append to `tests/test_post_v2_1_4_beta_fixes.py`:

```python
from openzim_mcp.synthesize import _drop_cross_archive_leakage


def test_leak_gate_drops_nonprimary_promoted_tail_hijack():
    # superuser is primary (path overlap {connection, refused} = 2);
    # wiki/Refused is a tagged promoted hit but a single-token tail from
    # the non-primary archive -> must be dropped despite the `promoted` tag.
    top_hits = [
        ("wikipedia", {"path": "Refused", "promoted": True, "snippet": "", "score": 1.0}),
        ("superuser", {"path": "questions/1/ssh-connection-refused", "snippet": "", "score": 0.5}),
    ]
    kept = _drop_cross_archive_leakage(
        top_hits,
        query="connection refused",
        fallback_used="rrf_fusion",
        max_secondary_archive_hits=1,
        min_overlap=1,
    )
    paths = [h["path"] for _, h in kept]
    assert "Refused" not in paths
    assert "questions/1/ssh-connection-refused" in paths


def test_leak_gate_keeps_multitoken_promoted_exemption():
    # darwins evolution -> On_the_Origin_of_Species (promoted, lexically
    # disjoint, multi-token) must KEEP its exemption.
    top_hits = [
        ("wikipedia", {"path": "On_the_Origin_of_Species", "promoted": True, "snippet": "", "score": 1.0}),
        ("superuser", {"path": "questions/2/git-merge", "snippet": "", "score": 0.5}),
    ]
    kept = _drop_cross_archive_leakage(
        top_hits,
        query="darwins evolution",
        fallback_used="rrf_fusion",
        max_secondary_archive_hits=1,
        min_overlap=1,
    )
    assert "On_the_Origin_of_Species" in [h["path"] for _, h in kept]
```

- [ ] **Step 6: Run to verify the leak-gate test fails**

Run: `uv run pytest tests/test_post_v2_1_4_beta_fixes.py -k leak_gate -v`
Expected: `test_leak_gate_drops_nonprimary_promoted_tail_hijack` FAILS (Refused kept); the keep test PASSES (current behaviour already exempts it).

- [ ] **Step 7: Implement the leak-gate change**

In `openzim_mcp/synthesize.py`, add the import at the top with the other `title_promotion` imports:

```python
from .title_promotion import (
    ...
    is_single_token_tail_match,
    ...
)
```

Replace the kept-loop body at `_drop_cross_archive_leakage` (currently `synthesize.py:1339-1342`):

```python
    for archive_name, hit in top_hits:
        # A `promoted` hit normally bypasses the relevance floor (a
        # possessive/variant canonical can be lexically disjoint from the
        # query). EXCEPTION: a single-token-tail promotion from a
        # NON-PRIMARY archive is the cross-archive leak signature
        # (`connection refused` -> wiki `Refused` while the relevant hits
        # are in superuser). The path-overlap floor can't catch it — the
        # tail token IS a query token — so drop it outright here.
        if archive_name != primary_archive and hit.get("promoted") and (
            is_single_token_tail_match(hit, query)
        ):
            continue
        if hit.get("promoted") or archive_name == primary_archive:
            kept.append((archive_name, hit))
            continue
        if per_archive_kept[archive_name] >= max_secondary_archive_hits:
            continue
        if all_zero or _overlap(hit) >= min_overlap:
            kept.append((archive_name, hit))
            per_archive_kept[archive_name] += 1
    return kept or top_hits[:1]
```

- [ ] **Step 8: Run the full new file to verify pass**

Run: `uv run pytest tests/test_post_v2_1_4_beta_fixes.py -v`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add openzim_mcp/title_promotion.py openzim_mcp/synthesize.py tests/test_post_v2_1_4_beta_fixes.py
git commit -m "fix(synthesize): drop non-primary single-token-tail leaks (#253)"
```

---

## Task 2: Thread the original (apostrophe-preserving) query into `_promote_title_match`

The promotion path currently receives the *extracted topic* (apostrophe already stripped). Fix 2's rescue probe needs the raw query so `find_title_match` can resolve the specific canonical (`einstein's theory` -> `Theory_of_relativity`, which the stripped `einstein theory` cannot reach). This task is a pure signature/plumbing change with no behaviour change yet.

**Files:**
- Modify: `openzim_mcp/synthesize.py` — `synthesize_query(...)` (line 1654) and `_promote_title_match(...)` (line 958) gain an `original_query: str` keyword (default to `query` for backwards-compat).
- Modify: `openzim_mcp/simple_tools.py` — `_handle_synthesize_query` passes the raw user `query` as `original_query`.
- Test: `tests/test_post_v2_1_4_beta_fixes.py`

- [ ] **Step 1: Write a test asserting `original_query` defaults to `query` (no behaviour change)**

```python
def test_promote_title_match_accepts_original_query_kw():
    # Plumbing-only: passing original_query must not change a no-op promote.
    from openzim_mcp.synthesize import _promote_title_match
    top_hits = [("wikipedia", {"path": "Berlin", "snippet": "", "score": 1.0})]
    # Berlin is already a strong title match for "berlin" -> short-circuit,
    # returns input unchanged regardless of original_query.
    out = _promote_title_match(
        top_hits,
        query="berlin",
        original_query="berlin",
        archives=[],
        archives_searched=[],
        search_handler=object(),
    )
    assert out == top_hits
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_post_v2_1_4_beta_fixes.py -k original_query_kw -v`
Expected: FAIL — `_promote_title_match() got an unexpected keyword argument 'original_query'`.

- [ ] **Step 3: Add the keyword to both functions**

In `openzim_mcp/synthesize.py`, `_promote_title_match` signature (line 958):

```python
def _promote_title_match(
    top_hits: list[tuple[str, dict]],
    *,
    query: str,
    original_query: str | None = None,
    archives: list[tuple[Archive, Path]],
    archives_searched: list[str],
    search_handler: Any,
) -> list[tuple[str, dict]]:
```

At the top of the body, normalize: `rescue_query = original_query if original_query is not None else query`.

In `synthesize_query` (line 1654), add `original_query: str | None = None` to the signature and forward it to BOTH `_promote_title_match` calls (lines 1708 and 1752): `original_query=original_query`.

- [ ] **Step 4: Pass the raw query from the handler**

In `openzim_mcp/simple_tools.py`, find the `synthesize_query(...)` call inside the synthesize execution (search for `synthesize_query(`), and add `original_query=query` where `query` is the raw user query received by `_handle_synthesize_query`. (The BM25 `query`/topic argument stays as-is; only the new kwarg is added.)

- [ ] **Step 5: Run to verify pass + no regressions**

Run: `uv run pytest tests/test_post_v2_1_4_beta_fixes.py -k original_query_kw tests/test_synthesize.py -v`
Expected: PASS, no regressions in `test_synthesize.py`.

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/synthesize.py openzim_mcp/simple_tools.py tests/test_post_v2_1_4_beta_fixes.py
git commit -m "refactor(synthesize): thread original query into _promote_title_match"
```

---

## Task 3: Fix 2 — tail-rescue promotes the more-specific full-query canonical

**Files:**
- Modify: `openzim_mcp/synthesize.py` — `_promote_title_match` tail loop (around line 1136, where `accept_tail_promotion` gates a single-token tail).
- Test: `tests/test_post_v2_1_4_beta_fixes.py`

**Logic:** In the tail loop, when the candidate `promoted` is a single token equal to the tail (`is_single_token_tail_match(promoted, query)`), before accepting it, probe `find_title_match(search_handler, vp, rescue_query, min_score=0.95)` (the *original* query). If that returns a **multi-token** canonical whose tokens **include the tail token**, promote the rescued canonical instead (build its hit via `title_match_hit(archive, rescued_title)` like pass-0 does, tag `_mark_promoted`). Otherwise fall through to the existing `accept_tail_promotion` gate.

- [ ] **Step 1: Write the failing rescue tests**

```python
from unittest.mock import MagicMock
from openzim_mcp.synthesize import _promote_title_match


def _rescue_handler(title_index_by_query, hit_by_title):
    """Mock search_handler: find_entry_by_title_data keyed by query,
    title_match_hit keyed by resolved title."""
    m = MagicMock()

    def fake_fetbd(_vp, q, *, cross_file=False, limit=3):
        row = title_index_by_query.get(q.lower())
        return {"results": [row] if row else []}

    m.find_entry_by_title_data.side_effect = fake_fetbd
    m.title_match_hit.side_effect = lambda _archive, title: hit_by_title.get(title.lower())
    return m


def test_einsteins_theory_rescues_theory_of_relativity():
    # tail "theory" -> generic "Theory"; original "einstein's theory"
    # resolves to the more-specific multi-token canonical containing "theory".
    handler = _rescue_handler(
        title_index_by_query={
            "einstein's theory": {"path": "Theory_of_relativity", "title": "Theory of relativity", "score": 1.0},
            "theory": {"path": "Theory", "title": "Theory", "score": 1.0},
        },
        hit_by_title={
            "theory": {"path": "Theory", "snippet": "...", "score": 1.0},
            "theory of relativity": {"path": "Theory_of_relativity", "snippet": "...", "score": 1.0},
        },
    )
    archive = object()
    out = _promote_title_match(
        [("wikipedia", {"path": "Einstein", "snippet": "", "score": 0.5})],
        query="einstein theory",          # stripped topic (what synthesize gets today)
        original_query="einstein's theory",  # raw query (apostrophe preserved)
        archives=[(archive, "wiki.zim")],
        archives_searched=["wikipedia"],
        search_handler=handler,
    )
    assert out[0][1]["path"] == "Theory_of_relativity"
    assert out[0][1].get("promoted") is True


def test_planet_earth_keeps_bare_tail_no_rescue():
    # original "planet earth" resolves only to single-token "Earth" -> no
    # more-specific canonical -> keep the legitimate bare-tail promotion.
    handler = _rescue_handler(
        title_index_by_query={
            "planet earth": {"path": "Earth", "title": "Earth", "score": 1.0},
            "earth": {"path": "Earth", "title": "Earth", "score": 1.0},
        },
        hit_by_title={"earth": {"path": "Earth", "snippet": "...", "score": 1.0}},
    )
    archive = object()
    out = _promote_title_match(
        [("wikipedia", {"path": "Planet", "snippet": "", "score": 0.5})],
        query="planet earth",
        original_query="planet earth",
        archives=[(archive, "wiki.zim")],
        archives_searched=["wikipedia"],
        search_handler=handler,
    )
    assert out[0][1]["path"] == "Earth"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_post_v2_1_4_beta_fixes.py -k "rescues or keeps_bare_tail" -v`
Expected: `test_einsteins_theory_rescues_theory_of_relativity` FAILS (promotes `Theory`, not `Theory_of_relativity`); `test_planet_earth_keeps_bare_tail_no_rescue` PASSES.

- [ ] **Step 3: Implement the rescue in the tail loop**

In `_promote_title_match`, inside the tail loop, immediately BEFORE the `if not accept_tail_promotion(...)` gate (around `synthesize.py:1136`), insert:

```python
            # Fix 2 tail-rescue: if we're about to promote a generic
            # single-token tail, the apostrophe-stripped topic may have
            # buried the real canonical (e.g. "einstein's theory" ->
            # Theory_of_relativity @1.0, unreachable from "einstein
            # theory"). Probe the ORIGINAL query; if it resolves to a
            # more-specific MULTI-token canonical that contains the tail
            # token, promote THAT instead — bypassing the Z4/possessive
            # gates that wrongly reject correct-but-tangential canonicals.
            if is_single_token_tail_match(promoted, query):
                rescued = find_title_match(
                    search_handler, str(_vp), rescue_query, min_score=0.95
                )
                if isinstance(rescued, dict) and rescued.get("path"):
                    rescued_tokens = _TAIL_TOKEN_RE.findall(
                        str(rescued["path"]).lower()
                    )
                    tail_tok = _TAIL_TOKEN_RE.findall(promoted_path.lower())
                    if len(rescued_tokens) > 1 and tail_tok and tail_tok[0] in rescued_tokens:
                        rescued_hit = _build_pass0_promoted_hit(
                            rescued, archive, title_match_hit
                        )
                        return [(archive_name, _mark_promoted(rescued_hit)), *top_hits]
```

Add `_TAIL_TOKEN_RE` to the `title_promotion` imports in `synthesize.py` if not already imported (it is exported from `title_promotion`).

- [ ] **Step 4: Run to verify rescue tests pass**

Run: `uv run pytest tests/test_post_v2_1_4_beta_fixes.py -k "rescues or keeps_bare_tail" -v`
Expected: both PASS.

- [ ] **Step 5: Run the FULL existing synthesize + promotion suites for regressions**

Run: `uv run pytest tests/test_synthesize.py tests/test_synthesize_title_promotion_v2a9.py tests/test_post_b4_beta_fixes.py tests/test_post_b6_beta_fixes.py tests/test_post_b8_beta_fixes.py tests/test_post_b9_beta_fixes.py tests/test_post_b10_beta_fixes.py tests/test_post_b11_beta_fixes.py tests/test_post_v2_1_3_beta_fixes.py -v`
Expected: all PASS (no possessive/Z4/tail invariant regressions).

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/synthesize.py tests/test_post_v2_1_4_beta_fixes.py
git commit -m "fix(synthesize): rescue more-specific canonical over generic tail (#252)"
```

---

## Task 4: Full suite, lint, and live validation

**Files:** none (verification only)

- [ ] **Step 1: Full local gate (matches CI)**

Run: `make lint && make type-check && uv run pytest -q`
Expected: lint clean (flake8 + isort + black over `openzim_mcp tests`), mypy clean, all tests pass. Fix any Sonar-style regex (no new unbounded quantifiers — `is_single_token_tail_match` reuses the existing bounded `_TAIL_TOKEN_RE`) and CodeQL uninitialized-local issues.

- [ ] **Step 2: Live before/after reprobe against the deployed server**

After deploy, re-run the four defect probes + four invariants via the connected `zim_query` tool (synthesize=True where noted):
- `connection refused` (synth) → relevant superuser SSH at rank 1, no `Refused`. **[#253]**
- `Einstein's theory` (synth) → `Theory_of_relativity` at rank 1. **[#252]**
- `Plato's cave` (synth) → `Allegory_of_the_cave` at rank 1. **[#252 class]**
- `ssh connection refused` (synth) → superuser SSH (unchanged). **[invariant]**
- `planet earth` (synth) → `Earth` (unchanged). **[invariant]**
- `Berlin Germany` (synth) → `Berlin` (unchanged). **[invariant]**

Record the before/after in the PR body. NOTE: these are not reproducible from a checkout — the live reprobe is the only end-to-end proof.

- [ ] **Step 3: Open the PR** with the live before/after table; close #252 and #253 on merge.

---

## Self-Review (completed during plan authoring)

- **Spec coverage:** Fix 1 (Sub-case A / #253) → Task 1. Fix 2 (Sub-case B / #252 + Plato) → Tasks 2-3. Testing layers (mock unit + invariants + live) → Tasks 1-4. Carve-out (`planet earth → Earth`) → Task 3 Step 1 `test_planet_earth_keeps_bare_tail_no_rescue` + Task 1 multi-token keep test. No gaps.
- **Placeholder scan:** none — every step has concrete code/commands.
- **Type consistency:** `is_single_token_tail_match(promoted, topic)` signature identical across Task 1 definition and its uses; `original_query` kw consistent across Tasks 2-3; `rescue_query` derived once in Task 2 Step 3 and used in Task 3 Step 3.
- **Known follow-up:** if the live reprobe (Task 4 Step 2) shows `Einstein's theory` still not resolving (e.g. the apostrophe is stripped *before* `original_query` is captured), the rescue degrades to suppression (drop `Theory`, BM25 fallback) — never worse than today; capture the live `find_title_match` shape and adjust the rescue guard.
