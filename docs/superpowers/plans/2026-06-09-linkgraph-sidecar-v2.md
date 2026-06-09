# Link-graph sidecar v2 (#16) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `builder_version` meta row and a per-edge `anchor_text` column to the link-graph sidecar, bumping `SCHEMA_VERSION` 1→2 (old sidecars refuse + rebuild). Surface the anchor text on inbound results.

**Architecture:** Schema v2 (`edges.anchor_text TEXT NOT NULL DEFAULT ''`, `SCHEMA_VERSION = 2`). The parser yields `(target, anchor)` pairs; the builder writes the 3-column edge + a `builder_version` meta row; the reader SELECTs the anchor; `get_inbound_links_data` surfaces it. Existing v1 sidecars hit the reader's existing strict `schema_version` check and rebuild.

**Tech Stack:** Python 3.12, SQLite (STRICT tables), pytest.

**Spec:** [docs/specs/2026-06-09-v2.5-linkgraph-sidecar-v2-design.md](../../specs/2026-06-09-v2.5-linkgraph-sidecar-v2-design.md)

---

## Task 1: Schema v2 — version bump + `anchor_text` column

**Files:**

- Modify: `openzim_mcp/linkgraph/schema.py` (`SCHEMA_VERSION` line 16; `edges` DDL in `_DDL`)
- Test: `tests/linkgraph/test_schema.py`

- [ ] **Step 1: Write/adjust the failing tests**

In `tests/linkgraph/test_schema.py`, update any assertion that `SCHEMA_VERSION == 1` to `== 2`, and add a column test:

```python
def test_edges_has_anchor_text_column(tmp_path):
    import sqlite3
    from openzim_mcp.linkgraph.schema import create_schema

    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(edges)")}
    assert cols == {"target_id", "source_id", "anchor_text"}


def test_schema_version_is_2():
    from openzim_mcp.linkgraph.schema import SCHEMA_VERSION

    assert SCHEMA_VERSION == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/linkgraph/test_schema.py -v --no-cov`
Expected: FAIL — `anchor_text` column absent; `SCHEMA_VERSION` is 1.

- [ ] **Step 3: Bump version + add the column**

In `openzim_mcp/linkgraph/schema.py`: change `SCHEMA_VERSION = 1` to `SCHEMA_VERSION = 2`, and change the `edges` line in `_DDL` to:

```sql
CREATE TABLE edges (target_id INTEGER NOT NULL, source_id INTEGER NOT NULL,
                    anchor_text TEXT NOT NULL DEFAULT '') STRICT;
```

(The `edges_by_target` index and the explanatory comment above the table are unchanged.)

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/linkgraph/test_schema.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/linkgraph/schema.py tests/linkgraph/test_schema.py
git commit -m "feat(linkgraph): schema v2 — edges.anchor_text + SCHEMA_VERSION=2"
```

---

## Task 2: Parser yields `(target, anchor)`; builder writes anchors + `builder_version`

This is the coupled core: the parser's output shape change and its only consumer (the builder) move together so the suite stays green.

**Files:**

- Modify: `openzim_mcp/zim/structure.py` (`_parse_internal_link_targets` lines 1137-1230)
- Modify: `openzim_mcp/linkgraph/builder.py` (imports; `build_from_link_stream` signature/loop/insert/meta lines 40-108; `iter_article_links` lines 142-177)
- Test: `tests/linkgraph/test_link_parser.py`, `tests/linkgraph/test_builder.py`

- [ ] **Step 1: Write the failing parser test**

In `tests/linkgraph/test_link_parser.py`, the existing tests call `_StructureMixin._parse_internal_link_targets(...)` and expect `List[str]`. Rename all references to `_parse_internal_link_edges` and update expectations to `(target, anchor)` pairs. Add a new test capturing anchor text and the no-text/dedup cases:

```python
def test_parse_edges_captures_anchor_text():
    html = (
        '<a href="A/Cat">the cat page</a>'
        '<a href="A/Dog"><img src="d.png"></a>'  # no visible text -> ''
        '<a href="A/Cat">cat again</a>'           # dup target -> first anchor kept
    )
    edges = _StructureMixin._parse_internal_link_edges(
        html, source_path="A/Index", archive=None
    )
    assert edges == [("A/Cat", "the cat page"), ("A/Dog", "")]
```

(Update the other parser tests in this file: each `_parse_internal_link_targets(...)` → `_parse_internal_link_edges(...)`, and each expected `["A/Foo", ...]` becomes `[("A/Foo", "<anchor>"), ...]`. For tests that only care about targets, assert on `[t for t, _ in edges]`.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/linkgraph/test_link_parser.py -v --no-cov`
Expected: FAIL — `_parse_internal_link_edges` does not exist.

- [ ] **Step 3: Rewrite the parser to return pairs**

In `openzim_mcp/zim/structure.py`, rename `_parse_internal_link_targets` to `_parse_internal_link_edges`, change the return annotation to `List[Tuple[str, str]]`, update the docstring's first line to "Return one source entry's deduped, canonical INTERNAL `(target, anchor_text)` edges.", and replace the dedup loop (lines 1202-1230) with:

```python
        seen: set = set()
        edges: List[Tuple[str, str]] = []
        for link in links_data["internal_links"]:
            target = _StructureMixin._resolve_link_to_entry_path(
                link.get("url", ""), source_path
            )
            if not target or target == source_path:
                continue
            if _StructureMixin._is_non_article_target(target):
                continue
            anchor = (link.get("text") or "").strip()
            if archive is not None:
                # Canonicalize through the redirect chain so the builder
                # inverts edges against the served (non-redirect) path.
                # Best-effort: a missing entry or malformed chain falls
                # back to the path-normalized target rather than dropping
                # an otherwise-valid edge.
                try:
                    entry = archive.get_entry_by_path(target)
                    resolved = best_effort_redirect_chain(entry)
                    resolved_path = getattr(resolved, "path", None)
                    if resolved_path:
                        target = resolved_path
                except Exception as e:
                    logger.debug(f"redirect canonicalization for {target} failed: {e}")
            if target in seen or target == source_path:
                continue
            seen.add(target)
            edges.append((target, anchor))
        return edges
```

Ensure `Tuple` is imported in `structure.py` (it uses `typing`; add `Tuple` to the import if absent).

- [ ] **Step 4: Run the parser tests to verify pass**

Run: `uv run pytest tests/linkgraph/test_link_parser.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Write the failing builder test**

In `tests/linkgraph/test_builder.py`, add (and update the synthetic-stream tests to pass `(target, anchor)` pairs instead of bare strings — e.g. a stream item `("A", ["B", "C"])` becomes `("A", [("B", ""), ("C", "")])`):

```python
def test_builder_writes_anchor_text_and_builder_version(tmp_path):
    import sqlite3
    import openzim_mcp
    from openzim_mcp.linkgraph.builder import build_from_link_stream

    out = str(tmp_path / "a.zim.linkgraph.sqlite")
    stream = [("A/Src", [("A/Tgt", "see Tgt")])]
    build_from_link_stream(out, archive_uuid="uuid-1", link_stream=stream)

    conn = sqlite3.connect(out)
    anchors = conn.execute("SELECT anchor_text FROM edges").fetchall()
    assert anchors == [("see Tgt",)]
    meta = dict(conn.execute("SELECT key, value FROM meta"))
    assert meta["builder_version"] == openzim_mcp.__version__
    assert meta["schema_version"] == "2"
```

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/linkgraph/test_builder.py::test_builder_writes_anchor_text_and_builder_version -v --no-cov`
Expected: FAIL — `build_from_link_stream` iterates `for target in targets` (unpacking a 2-tuple as a string) / no `builder_version` row.

- [ ] **Step 7: Update the builder**

In `openzim_mcp/linkgraph/builder.py`:

Add the version import after line 26:

```python
from openzim_mcp import __version__
```

Change `build_from_link_stream`'s signature (lines 40-47) to:

```python
def build_from_link_stream(
    out_path: str,
    *,
    archive_uuid: str,
    link_stream: Iterable[Tuple[str, List[Tuple[str, str]]]],
    force: bool = False,
    now_iso: Optional[str] = None,
    builder_version: Optional[str] = None,
) -> BuildStats:
```

Change the batch type (line 71) to `batch: List[Tuple[int, int, str]] = []`, and the inner loop (lines 72-90) to:

```python
        for source_path, targets in link_stream:
            source_id = _intern(source_path)
            seen: set[str] = set()
            for target, anchor in targets:
                if target == source_path or target in seen:
                    continue
                seen.add(target)
                target_id = _intern(target)
                batch.append((target_id, source_id, anchor))
                edge_count += 1
                if len(batch) >= _BATCH:
                    conn.executemany(
                        "INSERT INTO edges(target_id, source_id, anchor_text) "
                        "VALUES (?,?,?)",
                        batch,
                    )
                    batch.clear()
        if batch:
            conn.executemany(
                "INSERT INTO edges(target_id, source_id, anchor_text) VALUES (?,?,?)",
                batch,
            )
```

Add the `builder_version` row to the `meta` `executemany` (after the `edge_count` row, line 106):

```python
                ("edge_count", str(edge_count)),
                ("builder_version", builder_version or __version__),
```

Change `iter_article_links`'s return annotation (line 142) to `Iterator[Tuple[str, List[Tuple[str, str]]]]`, and its body (lines 174-177) to:

```python
        edges = _StructureMixin._parse_internal_link_edges(
            html, source_path=path, archive=archive
        )
        yield (path, edges)
```

- [ ] **Step 8: Run the builder tests to verify pass**

Run: `uv run pytest tests/linkgraph/test_builder.py -v --no-cov`
Expected: PASS (all — the new test plus the updated synthetic-stream tests).

- [ ] **Step 9: Commit**

```bash
git add openzim_mcp/zim/structure.py openzim_mcp/linkgraph/builder.py tests/linkgraph/test_link_parser.py tests/linkgraph/test_builder.py
git commit -m "feat(linkgraph): parse (target, anchor) edges; write anchor_text + builder_version"
```

---

## Task 3: Reader returns `anchor_text`

**Files:**

- Modify: `openzim_mcp/linkgraph/reader.py` (`query_inbound` lines 83-93)
- Test: `tests/linkgraph/test_reader.py`

- [ ] **Step 1: Write the failing test**

In `tests/linkgraph/test_reader.py`, add (modelled on the file's existing build-then-read pattern; pass `(target, anchor)` pairs to the builder):

```python
def test_query_inbound_includes_anchor_text(tmp_path):
    from openzim_mcp.linkgraph.builder import build_from_link_stream
    from openzim_mcp.linkgraph.reader import LinkGraphReader

    out = str(tmp_path / "a.zim.linkgraph.sqlite")
    stream = [("A/Src", [("A/Tgt", "anchor for tgt")])]
    build_from_link_stream(out, archive_uuid="u", link_stream=stream)
    # open_for fingerprints on the live archive uuid; read the sidecar directly
    import sqlite3

    reader = LinkGraphReader(sqlite3.connect(out))
    try:
        page = reader.query_inbound("A/Tgt", limit=10, offset=0)
    finally:
        reader.close()
    assert page.total == 1
    assert page.rows[0]["path"] == "A/Src"
    assert page.rows[0]["anchor_text"] == "anchor for tgt"
```

(If `LinkGraphReader.__init__` is not directly constructible in the existing tests, follow whatever helper `test_reader.py` already uses to obtain a reader over a built sidecar, and add the `anchor_text` assertion to it.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/linkgraph/test_reader.py::test_query_inbound_includes_anchor_text -v --no-cov`
Expected: FAIL — `KeyError: 'anchor_text'` (the row dict has only `path`, `inbound_degree`).

- [ ] **Step 3: Add `anchor_text` to the query + row dict**

In `openzim_mcp/linkgraph/reader.py`, change the `query_inbound` SELECT (lines 83-92) and row build (line 93):

```python
        cur = self._conn.execute(
            """
            SELECT n.path, n.inbound_degree, e.anchor_text
              FROM edges e JOIN nodes n ON n.id = e.source_id
             WHERE e.target_id = ?
             ORDER BY n.inbound_degree DESC, n.path ASC
             LIMIT ? OFFSET ?
            """,
            (target_id, limit, offset),
        )
        rows = [
            {"path": p, "inbound_degree": d, "anchor_text": a}
            for (p, d, a) in cur.fetchall()
        ]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/linkgraph/test_reader.py -v --no-cov`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/linkgraph/reader.py tests/linkgraph/test_reader.py
git commit -m "feat(linkgraph): reader surfaces per-edge anchor_text"
```

---

## Task 4: Data layer surfaces `anchor_text` on inbound results

**Files:**

- Modify: `openzim_mcp/zim/structure.py` (`get_inbound_links_data` results build, lines 1006-1013)
- Test: `tests/linkgraph/test_inbound_data.py`

- [ ] **Step 1: Write the failing test**

In `tests/linkgraph/test_inbound_data.py`, add an assertion (extend the file's existing inbound-data fixture/flow; if it builds a sidecar with a known anchor, assert it surfaces). Minimal addition modelled on the existing tests:

```python
def test_inbound_results_include_anchor_text(tmp_path, monkeypatch):
    # Reuse this file's existing helper that builds a sidecar + calls
    # get_inbound_links_data. Assert each result item carries 'anchor_text'.
    result = _run_inbound(tmp_path, monkeypatch)  # existing helper in this file
    assert all("anchor_text" in item for item in result["results"])
```

(If `test_inbound_data.py` has no reusable helper, model the test on its existing happy-path test: build a sidecar via `build_from_link_stream` with a `(target, anchor)` stream, point `get_inbound_links_data` at it, and assert `result["results"][0]["anchor_text"]` equals the seeded anchor.)

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/linkgraph/test_inbound_data.py -k anchor -v --no-cov`
Expected: FAIL — results lack `anchor_text`.

- [ ] **Step 3: Forward `anchor_text` into each result**

In `openzim_mcp/zim/structure.py`, change the `results` list comprehension (lines 1006-1013):

```python
        results: List[Dict[str, Any]] = [
            {
                "path": r["path"],
                "title": r["path"],
                "inbound_degree": r["inbound_degree"],
                "anchor_text": r["anchor_text"],
            }
            for r in page.rows
        ]
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/linkgraph/test_inbound_data.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/zim/structure.py tests/linkgraph/test_inbound_data.py
git commit -m "feat(linkgraph): surface anchor_text on inbound link results"
```

---

## Task 5: Full verification

- [ ] **Step 1: Run the linkgraph suite**

Run: `uv run pytest tests/linkgraph/ -v --no-cov`
Expected: PASS (all).

- [ ] **Step 2: Lint + types**

Run: `uv run flake8 openzim_mcp/linkgraph openzim_mcp/zim/structure.py tests/linkgraph && uv run mypy openzim_mcp/linkgraph openzim_mcp/zim/structure.py`
Expected: clean.

- [ ] **Step 3: Full suite (no regressions)**

Run: `uv run pytest -q --no-cov`
Expected: all pass, 0 failed.

- [ ] **Step 4: Check the live test references the new shape**

Inspect `tests/live/test_live_inbound_linkgraph.py`. If it asserts on inbound result item keys, add an `anchor_text` assertion; if it only checks the happy path, leave it. Do NOT remove or weaken existing live assertions. Run (gated; may skip without a live archive):
`uv run pytest tests/live/test_live_inbound_linkgraph.py -v --no-cov`
Expected: PASS or SKIP (skip is acceptable when no live archive is present).
