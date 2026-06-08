# Inbound Link-Graph Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `openzim-mcp build link-graph <archive>.zim` command that materializes a reverse-edge graph into a `<archive>.zim.linkgraph.sqlite` sidecar, and wire `zim_links(direction="inbound")` to read it — ranked by linker importance, paginated, with strict staleness refusal and graceful absence.

**Architecture:** A new `openzim_mcp/linkgraph/` package (schema + reader + builder), a new `openzim_mcp/cli/build.py` sub-CLI dispatched from `main.py`, a `get_inbound_links_data` data method mirroring `get_related_articles_data`, and an `"inbound"` branch in `zim_links`. Build = one entry walk → extract internal outbound links → resolve to canonical targets → invert → SQLite. Read = indexed `edges_by_target` lookup joined to a precomputed `nodes.inbound_degree`.

**Tech Stack:** Python 3.12, stdlib `sqlite3`, `libzim` (via the existing `openzim_mcp.zim` layer), `argparse`, `pytest`.

**Spec:** [docs/specs/2026-06-08-v2.5-link-graph-design.md](../../specs/2026-06-08-v2.5-link-graph-design.md)

---

## File Structure

- **Create** `openzim_mcp/linkgraph/__init__.py` — package marker + public exports.
- **Create** `openzim_mcp/linkgraph/schema.py` — DDL, `SCHEMA_VERSION`, `create_schema`, `apply_build_pragmas`.
- **Create** `openzim_mcp/linkgraph/reader.py` — `LinkGraphReader` (locate, fingerprint-check, paginated inbound query).
- **Create** `openzim_mcp/linkgraph/builder.py` — `build_from_link_stream` (pure core), `iter_article_links` (archive walk), `build_link_graph` (orchestrator), `BuildStats`.
- **Create** `openzim_mcp/cli/__init__.py` + `openzim_mcp/cli/build.py` — `build_main(argv)`.
- **Modify** `openzim_mcp/main.py:107-117` — dispatch `build` subcommand.
- **Modify** `openzim_mcp/zim/structure.py` — extract a shared internal-link parser; add `get_inbound_links_data`.
- **Modify** `openzim_mcp/async_operations.py` — add `get_inbound_links_data` async wrapper.
- **Modify** `openzim_mcp/tools/zim_links.py` + `openzim_mcp/tools/zim_links_description.md` — `"inbound"` enum + branch + docs.
- **Tests:** `tests/linkgraph/test_schema.py`, `test_reader.py`, `test_builder.py`, `test_build_cli.py`; `tests/test_zim_links_inbound.py`; `tests/live/test_live_inbound_linkgraph.py`.

A note on a sentinel used throughout: the data method raises a dedicated `LinkGraphUnavailable` exception (defined in Task 2) when the sidecar is absent or stale; the tool layer catches it and returns a structured `tool_error`. This keeps "no sidecar" out of the generic archive-error path.

---

### Task 1: Link-graph schema module

**Files:**

- Create: `openzim_mcp/linkgraph/__init__.py`
- Create: `openzim_mcp/linkgraph/schema.py`
- Test: `tests/linkgraph/__init__.py`, `tests/linkgraph/test_schema.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/linkgraph/test_schema.py
"""Tests for the link-graph SQLite schema."""

from __future__ import annotations

import sqlite3

from openzim_mcp.linkgraph.schema import SCHEMA_VERSION, create_schema


def test_create_schema_makes_expected_tables_and_index() -> None:
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"meta", "nodes", "edges"} <= tables
    indexes = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }
    assert "edges_by_target" in indexes


def test_schema_version_is_a_positive_int() -> None:
    assert isinstance(SCHEMA_VERSION, int) and SCHEMA_VERSION >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/linkgraph/test_schema.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'openzim_mcp.linkgraph'`.

- [ ] **Step 3: Write minimal implementation**

```python
# openzim_mcp/linkgraph/__init__.py
"""Offline inbound link-graph sidecar: builder, reader, and schema."""
```

```python
# openzim_mcp/linkgraph/schema.py
"""SQLite schema for the inbound link-graph sidecar.

Layout is integer-keyed: ``nodes`` interns each entry path to a small id and
carries the precomputed ``inbound_degree`` used to rank linkers by importance;
``edges`` stores ``(target_id, source_id)`` pairs indexed by target for the
inbound lookup. ``meta`` holds the archive UUID + schema version the reader
fingerprints against (strict staleness check).
"""

from __future__ import annotations

import sqlite3

# Bump on any incompatible layout change; the reader rejects mismatches and
# forces an operator rebuild.
SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE meta  (key TEXT PRIMARY KEY, value TEXT) STRICT;
CREATE TABLE nodes (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,
                    inbound_degree INTEGER NOT NULL DEFAULT 0) STRICT;
CREATE TABLE edges (target_id INTEGER NOT NULL, source_id INTEGER NOT NULL) STRICT;
CREATE INDEX edges_by_target ON edges(target_id);
"""


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables + indexes on a fresh connection."""
    conn.executescript(_DDL)


def apply_build_pragmas(conn: sqlite3.Connection) -> None:
    """Speed pragmas for the one-shot build (safe: a crash discards the temp file)."""
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/linkgraph/test_schema.py -v --no-cov`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/linkgraph/__init__.py openzim_mcp/linkgraph/schema.py tests/linkgraph/
git commit -m "feat(linkgraph): SQLite schema for the inbound link-graph sidecar"
```

---

### Task 2: Reader — locate, fingerprint, query

**Files:**

- Create: `openzim_mcp/linkgraph/reader.py`
- Test: `tests/linkgraph/test_reader.py`

The reader is fully testable against a hand-built SQLite file — no ZIM needed.

- [ ] **Step 1: Write the failing test**

```python
# tests/linkgraph/test_reader.py
"""Tests for LinkGraphReader (built against a hand-made sidecar)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openzim_mcp.linkgraph.reader import LinkGraphReader, sidecar_path_for
from openzim_mcp.linkgraph.schema import SCHEMA_VERSION, create_schema


def _make_sidecar(archive: Path, *, uuid: str, schema_version: int = SCHEMA_VERSION):
    """Build a minimal sidecar: target T has linkers A(deg2), B(deg1)."""
    conn = sqlite3.connect(sidecar_path_for(archive))
    create_schema(conn)
    conn.executemany(
        "INSERT INTO nodes(id, path, inbound_degree) VALUES (?,?,?)",
        [(1, "C/T", 0), (2, "C/A", 2), (3, "C/B", 1)],
    )
    conn.executemany(
        "INSERT INTO edges(target_id, source_id) VALUES (?,?)",
        [(1, 2), (1, 3)],  # A->T, B->T
    )
    conn.executemany(
        "INSERT INTO meta(key, value) VALUES (?,?)",
        [("schema_version", str(schema_version)), ("archive_uuid", uuid)],
    )
    conn.commit()
    conn.close()


def test_sidecar_path_is_sibling(tmp_path: Path) -> None:
    archive = tmp_path / "wikipedia.zim"
    assert sidecar_path_for(archive) == str(tmp_path / "wikipedia.zim.linkgraph.sqlite")


def test_open_for_returns_none_when_absent(tmp_path: Path) -> None:
    archive = tmp_path / "x.zim"
    assert LinkGraphReader.open_for(str(archive), live_archive_uuid="u1") is None


def test_open_for_returns_none_on_uuid_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "x.zim"
    archive.write_bytes(b"")
    _make_sidecar(archive, uuid="built-uuid")
    assert LinkGraphReader.open_for(str(archive), live_archive_uuid="other") is None


def test_open_for_returns_none_on_schema_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "x.zim"
    archive.write_bytes(b"")
    _make_sidecar(archive, uuid="u1", schema_version=SCHEMA_VERSION + 99)
    assert LinkGraphReader.open_for(str(archive), live_archive_uuid="u1") is None


def test_query_inbound_ranks_by_degree_then_path(tmp_path: Path) -> None:
    archive = tmp_path / "x.zim"
    archive.write_bytes(b"")
    _make_sidecar(archive, uuid="u1")
    reader = LinkGraphReader.open_for(str(archive), live_archive_uuid="u1")
    assert reader is not None
    page = reader.query_inbound("C/T", limit=10, offset=0)
    assert [r["path"] for r in page.rows] == ["C/A", "C/B"]  # A(deg2) before B(deg1)
    assert page.rows[0]["inbound_degree"] == 2
    assert page.total == 2
    reader.close()


def test_query_inbound_paginates(tmp_path: Path) -> None:
    archive = tmp_path / "x.zim"
    archive.write_bytes(b"")
    _make_sidecar(archive, uuid="u1")
    reader = LinkGraphReader.open_for(str(archive), live_archive_uuid="u1")
    assert reader is not None
    page = reader.query_inbound("C/T", limit=1, offset=1)
    assert [r["path"] for r in page.rows] == ["C/B"]
    assert page.total == 2
    reader.close()


def test_query_inbound_unknown_target_is_empty_not_error(tmp_path: Path) -> None:
    archive = tmp_path / "x.zim"
    archive.write_bytes(b"")
    _make_sidecar(archive, uuid="u1")
    reader = LinkGraphReader.open_for(str(archive), live_archive_uuid="u1")
    assert reader is not None
    page = reader.query_inbound("C/Nonexistent", limit=10, offset=0)
    assert page.rows == [] and page.total == 0
    reader.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/linkgraph/test_reader.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'LinkGraphReader'`.

- [ ] **Step 3: Write minimal implementation**

```python
# openzim_mcp/linkgraph/reader.py
"""Read-only access to a `<archive>.zim.linkgraph.sqlite` sidecar.

``open_for`` returns ``None`` for an absent file OR a fingerprint mismatch
(schema version / archive UUID) — the caller treats both identically (the
strict staleness decision). ``query_inbound`` is a ranked, paginated lookup.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema import SCHEMA_VERSION


class LinkGraphUnavailable(Exception):
    """Raised by the data layer when the inbound sidecar is absent or stale."""


def sidecar_path_for(archive_path: str | Path) -> str:
    """Sibling sidecar path: ``<archive>.zim.linkgraph.sqlite``."""
    return f"{archive_path}.linkgraph.sqlite"


@dataclass
class InboundPage:
    """One page of inbound linkers + the unpaginated total."""

    rows: List[Dict[str, Any]]
    total: int


class LinkGraphReader:
    """Open + query a link-graph sidecar. Construct via ``open_for``."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    def open_for(
        cls, archive_path: str, *, live_archive_uuid: str
    ) -> Optional["LinkGraphReader"]:
        path = sidecar_path_for(archive_path)
        if not Path(path).is_file():
            return None
        # Read-only URI open so a reader never creates/writes the file.
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            meta = {
                k: v for k, v in conn.execute("SELECT key, value FROM meta")
            }
        except sqlite3.DatabaseError:
            conn.close()
            return None
        if meta.get("schema_version") != str(SCHEMA_VERSION):
            conn.close()
            return None
        if meta.get("archive_uuid") != live_archive_uuid:
            conn.close()
            return None
        return cls(conn)

    def query_inbound(self, target_path: str, *, limit: int, offset: int) -> InboundPage:
        row = self._conn.execute(
            "SELECT id FROM nodes WHERE path = ?", (target_path,)
        ).fetchone()
        if row is None:
            return InboundPage(rows=[], total=0)
        target_id = row[0]
        total = self._conn.execute(
            "SELECT COUNT(*) FROM edges WHERE target_id = ?", (target_id,)
        ).fetchone()[0]
        cur = self._conn.execute(
            """
            SELECT n.path, n.inbound_degree
              FROM edges e JOIN nodes n ON n.id = e.source_id
             WHERE e.target_id = ?
             ORDER BY n.inbound_degree DESC, n.path ASC
             LIMIT ? OFFSET ?
            """,
            (target_id, limit, offset),
        )
        rows = [{"path": p, "inbound_degree": d} for (p, d) in cur.fetchall()]
        return InboundPage(rows=rows, total=int(total))

    def close(self) -> None:
        self._conn.close()
```

Note: `query_inbound` takes `limit`/`offset` as keyword-only in the impl; the test calls them as keywords — keep them keyword-only.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/linkgraph/test_reader.py -v --no-cov`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/linkgraph/reader.py tests/linkgraph/test_reader.py
git commit -m "feat(linkgraph): sidecar reader with strict fingerprint + ranked inbound query"
```

---

### Task 3: Builder core — invert a link stream into a sidecar

**Files:**

- Create: `openzim_mcp/linkgraph/builder.py`
- Test: `tests/linkgraph/test_builder.py`

The core takes an iterator of `(source_path, [target_paths])` and writes the sidecar — fully testable with a synthetic stream (no ZIM).

- [ ] **Step 1: Write the failing test**

```python
# tests/linkgraph/test_builder.py
"""Tests for the link-graph builder core (synthetic link streams)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openzim_mcp.linkgraph.builder import build_from_link_stream
from openzim_mcp.linkgraph.reader import sidecar_path_for


def _stream():
    # A->T, B->T, A->B  =>  T linked by {A,B}; B linked by {A}
    yield ("C/A", ["C/T", "C/B"])
    yield ("C/B", ["C/T"])
    yield ("C/T", [])


def test_build_inverts_and_computes_degree(tmp_path: Path) -> None:
    archive = tmp_path / "x.zim"
    out = sidecar_path_for(archive)
    stats = build_from_link_stream(out, archive_uuid="u1", link_stream=_stream())
    assert stats.edge_count == 3
    conn = sqlite3.connect(out)
    # T's linkers, ranked by their own inbound_degree:
    rows = conn.execute(
        """SELECT n.path, n.inbound_degree FROM edges e
           JOIN nodes n ON n.id=e.source_id
           JOIN nodes t ON t.id=e.target_id
           WHERE t.path='C/T'
           ORDER BY n.inbound_degree DESC, n.path""",
    ).fetchall()
    # A is linked by nobody (deg 0); B is linked by A (deg 1) -> B ranks first.
    assert rows == [("C/B", 1), ("C/A", 0)]
    assert conn.execute(
        "SELECT value FROM meta WHERE key='archive_uuid'"
    ).fetchone()[0] == "u1"
    conn.close()


def test_build_rejects_self_links_and_dedups(tmp_path: Path) -> None:
    out = sidecar_path_for(tmp_path / "x.zim")

    def stream():
        yield ("C/A", ["C/A", "C/T", "C/T"])  # self-link + duplicate

    stats = build_from_link_stream(out, archive_uuid="u1", link_stream=stream())
    assert stats.edge_count == 1  # only A->T survives


def test_build_refuses_existing_without_force(tmp_path: Path) -> None:
    out = sidecar_path_for(tmp_path / "x.zim")
    Path(out).write_text("existing")
    with pytest.raises(FileExistsError):
        build_from_link_stream(out, archive_uuid="u1", link_stream=iter([]))


def test_build_force_overwrites_atomically(tmp_path: Path) -> None:
    out = sidecar_path_for(tmp_path / "x.zim")
    Path(out).write_text("existing")
    build_from_link_stream(out, archive_uuid="u1", link_stream=iter([]), force=True)
    # No leftover temp file beside the sidecar:
    assert not Path(out + ".tmp").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/linkgraph/test_builder.py -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'build_from_link_stream'`.

- [ ] **Step 3: Write minimal implementation**

```python
# openzim_mcp/linkgraph/builder.py
"""Build a link-graph sidecar from a stream of (source, [targets]) edges.

``build_from_link_stream`` is the pure, ZIM-free core (testable with synthetic
streams). ``iter_article_links`` (Task 5) supplies the real stream from an
archive, and ``build_link_graph`` (Task 5) orchestrates the two.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .schema import SCHEMA_VERSION, apply_build_pragmas, create_schema

_BATCH = 50_000


@dataclass
class BuildStats:
    """Summary of a completed build."""

    node_count: int
    edge_count: int
    bytes_written: int


def build_from_link_stream(
    out_path: str,
    *,
    archive_uuid: str,
    link_stream: Iterable[Tuple[str, List[str]]],
    force: bool = False,
    now_iso: Optional[str] = None,
) -> BuildStats:
    """Invert ``link_stream`` into the sidecar at ``out_path`` (atomic write)."""
    if Path(out_path).exists() and not force:
        raise FileExistsError(
            f"{out_path} already exists; pass force=True to overwrite."
        )
    tmp_path = out_path + ".tmp"
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    ids: Dict[str, int] = {}

    def _intern(path: str) -> int:
        node_id = ids.get(path)
        if node_id is None:
            node_id = len(ids) + 1
            ids[path] = node_id
        return node_id

    conn = sqlite3.connect(tmp_path)
    try:
        apply_build_pragmas(conn)
        create_schema(conn)
        edge_count = 0
        batch: List[Tuple[int, int]] = []
        for source_path, targets in link_stream:
            source_id = _intern(source_path)
            seen: set[str] = set()
            for target in targets:
                if target == source_path or target in seen:
                    continue
                seen.add(target)
                target_id = _intern(target)
                batch.append((target_id, source_id))
                edge_count += 1
                if len(batch) >= _BATCH:
                    conn.executemany(
                        "INSERT INTO edges(target_id, source_id) VALUES (?,?)", batch
                    )
                    batch.clear()
        if batch:
            conn.executemany(
                "INSERT INTO edges(target_id, source_id) VALUES (?,?)", batch
            )
        conn.executemany(
            "INSERT INTO nodes(id, path) VALUES (?,?)",
            [(node_id, path) for path, node_id in ids.items()],
        )
        # Degree pass: how many edges point AT each node (its importance).
        conn.execute(
            """UPDATE nodes SET inbound_degree =
                 COALESCE((SELECT COUNT(*) FROM edges WHERE target_id = nodes.id), 0)"""
        )
        conn.executemany(
            "INSERT INTO meta(key, value) VALUES (?,?)",
            [
                ("schema_version", str(SCHEMA_VERSION)),
                ("archive_uuid", archive_uuid),
                ("built_at", now_iso or datetime.now(timezone.utc).isoformat()),
                ("node_count", str(len(ids))),
                ("edge_count", str(edge_count)),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    os.replace(tmp_path, out_path)
    return BuildStats(
        node_count=len(ids),
        edge_count=edge_count,
        bytes_written=Path(out_path).stat().st_size,
    )
```

(`datetime.now(timezone.utc)` is the only clock use; it runs in the operator CLI, never in the server request path, so it's fine here.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/linkgraph/test_builder.py -v --no-cov`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/linkgraph/builder.py tests/linkgraph/test_builder.py
git commit -m "feat(linkgraph): builder core inverts a link stream into the sidecar"
```

---

### Task 4: Extract a shared internal-link parser from `extract_article_links_data`

**Files:**

- Modify: `openzim_mcp/zim/structure.py` (factor out the internal-link extraction)
- Test: `tests/test_extract_links_cache_sharing.py` (existing — must stay green) + a new unit test

**Why:** the builder must extract each source entry's internal-link target paths from an *already-open* archive (one open for the whole walk), so it cannot call `extract_article_links_data` per entry (that re-validates the path and re-opens the archive each call). Factor the HTML→internal-canonical-targets logic into a reusable helper that both the existing tool path and the builder call.

- [ ] **Step 1: Locate the internal-link extraction block**

Read `openzim_mcp/zim/structure.py` `extract_article_links_data` (lines ~228-378) and find where it produces the **internal** bucket: the code that reads the entry HTML, parses anchors, classifies internal vs external vs media, and resolves each internal href to a canonical target entry path (following redirects via `resolve_redirect_chain` / `best_effort_redirect_chain` from `openzim_mcp/zim/redirects.py`). Note the exact function/closure that does this.

- [ ] **Step 2: Write the failing test for the extracted helper**

```python
# tests/linkgraph/test_link_parser.py
"""The shared internal-link parser returns canonical target paths."""

from __future__ import annotations

from openzim_mcp.zim.structure import _StructureMixin


def test_parse_internal_targets_from_html_resolves_and_dedups() -> None:
    html = (
        '<a href="C/Foo">Foo</a>'
        '<a href="C/Foo">Foo again</a>'
        '<a href="https://example.com">external</a>'
        '<a href="I/img.png">image</a>'
    )
    # Helper takes raw HTML + source path; archive=None means "no redirect
    # resolution available" -> return hrefs as-is (canonicalization is a no-op
    # without an archive handle). Internal-only, deduped.
    targets = _StructureMixin._parse_internal_link_targets(
        html, source_path="C/Bar", archive=None
    )
    assert targets == ["C/Foo"]
```

Adjust the assertion to match the real internal-link classification rules you found in Step 1 (namespace handling, scheme drops). The invariants the test MUST encode: internal-only, deduped, external/media excluded, and (when `archive` is provided) redirect-resolved to canonical paths.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/linkgraph/test_link_parser.py -v --no-cov`
Expected: FAIL with `AttributeError: ... has no attribute '_parse_internal_link_targets'`.

- [ ] **Step 4: Extract the helper and call it from both sites**

Move the internal-link extraction into a `@staticmethod _parse_internal_link_targets(html, *, source_path, archive)` on `_StructureMixin`, returning a deduped `list[str]` of canonical internal target paths. Have `extract_article_links_data` call it for its internal bucket (preserving its existing external/media handling). Keep the signature exactly as the test uses it.

- [ ] **Step 5: Run the new test AND the existing link tests**

Run: `uv run pytest tests/linkgraph/test_link_parser.py tests/test_extract_links_cache_sharing.py tests/test_extract_article_links_pagination.py tests/test_zim_links.py -v --no-cov`
Expected: all PASS (the refactor is behavior-preserving for the tool path).

- [ ] **Step 6: Commit**

```bash
git add openzim_mcp/zim/structure.py tests/linkgraph/test_link_parser.py
git commit -m "refactor(structure): extract reusable internal-link parser for the builder"
```

---

### Task 5: Archive walk + build orchestrator

**Files:**

- Modify: `openzim_mcp/linkgraph/builder.py` (add `iter_article_links`, `build_link_graph`)
- Test: `tests/linkgraph/test_builder.py` (add a walk test with a fake archive)

- [ ] **Step 1: Write the failing test (fake archive, no real ZIM)**

```python
# append to tests/linkgraph/test_builder.py
from unittest.mock import MagicMock

from openzim_mcp.linkgraph.builder import iter_article_links


class _FakeEntry:
    def __init__(self, path, html, is_redirect=False):
        self.path = path
        self._html = html
        self.is_redirect = is_redirect

    def get_item(self):
        item = MagicMock()
        item.content = MagicMock()
        item.content.tobytes.return_value = self._html.encode()
        return item


def test_iter_article_links_walks_content_entries(monkeypatch):
    entries = [
        _FakeEntry("C/A", '<a href="C/T">t</a>'),
        _FakeEntry("M/Counter", "metadata"),          # non-content: skipped
        _FakeEntry("C/Redir", "", is_redirect=True),   # redirect: skipped as source
    ]
    archive = MagicMock()
    archive.entry_count = len(entries)
    archive._get_entry_by_id.side_effect = lambda i: entries[i]

    pairs = list(iter_article_links(archive))
    assert ("C/A", ["C/T"]) in pairs
    assert all(src.startswith("C/") for src, _ in pairs)
    assert not any(src == "C/Redir" for src, _ in pairs)
```

Match `get_item().content.tobytes()` to however the existing code reads entry HTML (check `extract_article_links_data` / `zim/content.py` for the exact content-access idiom and mirror it; adjust `_FakeEntry` accordingly).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/linkgraph/test_builder.py::test_iter_article_links_walks_content_entries -v --no-cov`
Expected: FAIL with `ImportError: cannot import name 'iter_article_links'`.

- [ ] **Step 3: Implement `iter_article_links` + `build_link_graph`**

```python
# add to openzim_mcp/linkgraph/builder.py
from openzim_mcp.zim.structure import _StructureMixin


def iter_article_links(archive):
    """Yield (source_path, [canonical internal target paths]) for content entries.

    Walks the open archive once via ``_get_entry_by_id`` (the same primitive
    the namespace walk uses), skips non-``C`` entries and redirects-as-source,
    and reuses ``_parse_internal_link_targets`` for extraction + canonicalization.
    """
    total = archive.entry_count
    for entry_id in range(total):
        try:
            entry = archive._get_entry_by_id(entry_id)
        except Exception:
            continue
        path = getattr(entry, "path", "")
        if not path.startswith("C/"):
            continue
        if getattr(entry, "is_redirect", False):
            continue
        try:
            html = entry.get_item().content.tobytes().decode("utf-8", "replace")
        except Exception:
            continue
        targets = _StructureMixin._parse_internal_link_targets(
            html, source_path=path, archive=archive
        )
        yield (path, targets)


def build_link_graph(
    archive_path: str,
    out_path: Optional[str] = None,
    *,
    force: bool = False,
    progress: Optional[Callable[[int, int], None]] = None,
) -> BuildStats:
    """Open ``archive_path``, walk it, and write the sidecar (atomic)."""
    from openzim_mcp.linkgraph.reader import sidecar_path_for
    from openzim_mcp.zim import zim_archive  # the existing context-managed open

    out = out_path or sidecar_path_for(archive_path)
    with zim_archive(Path(archive_path)) as archive:
        archive_uuid = str(archive.uuid)

        def _stream():
            for i, pair in enumerate(iter_article_links(archive)):
                if progress and i % 10_000 == 0:
                    progress(i, archive.entry_count)
                yield pair

        return build_from_link_stream(
            out, archive_uuid=archive_uuid, link_stream=_stream(), force=force
        )
```

Confirm the archive-open helper name/location: the title resolver uses `_zim_ops_mod.zim_archive(Path(...))` (`structure.py:962`). Import the same context manager (adjust the `from openzim_mcp.zim import zim_archive` line to the real module path you find).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/linkgraph/test_builder.py -v --no-cov`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/linkgraph/builder.py tests/linkgraph/test_builder.py
git commit -m "feat(linkgraph): archive walk + build orchestrator"
```

---

### Task 6: Build sub-CLI

**Files:**

- Create: `openzim_mcp/cli/__init__.py`, `openzim_mcp/cli/build.py`
- Test: `tests/linkgraph/test_build_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/linkgraph/test_build_cli.py
"""Tests for `openzim-mcp build link-graph` argument handling."""

from __future__ import annotations

from unittest.mock import patch

from openzim_mcp.cli.build import build_main
from openzim_mcp.linkgraph.builder import BuildStats


def test_build_link_graph_invokes_builder(tmp_path):
    archive = tmp_path / "wiki.zim"
    archive.write_bytes(b"")
    fake = BuildStats(node_count=3, edge_count=2, bytes_written=4096)
    with patch(
        "openzim_mcp.cli.build.build_link_graph", return_value=fake
    ) as mock_build:
        rc = build_main(["link-graph", str(archive)])
    assert rc == 0
    mock_build.assert_called_once()
    assert mock_build.call_args.kwargs["force"] is False


def test_build_force_flag_forwarded(tmp_path):
    archive = tmp_path / "wiki.zim"
    archive.write_bytes(b"")
    with patch(
        "openzim_mcp.cli.build.build_link_graph",
        return_value=BuildStats(0, 0, 0),
    ) as mock_build:
        rc = build_main(["link-graph", str(archive), "--force"])
    assert rc == 0
    assert mock_build.call_args.kwargs["force"] is True


def test_build_existing_without_force_returns_nonzero(tmp_path):
    archive = tmp_path / "wiki.zim"
    archive.write_bytes(b"")
    with patch(
        "openzim_mcp.cli.build.build_link_graph", side_effect=FileExistsError("exists")
    ):
        rc = build_main(["link-graph", str(archive)])
    assert rc != 0


def test_unknown_artifact_returns_nonzero():
    assert build_main(["embeddings", "/x.zim"]) != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/linkgraph/test_build_cli.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'openzim_mcp.cli'`.

- [ ] **Step 3: Write minimal implementation**

```python
# openzim_mcp/cli/__init__.py
"""Operator-facing offline subcommands (`openzim-mcp build ...`)."""
```

```python
# openzim_mcp/cli/build.py
"""`openzim-mcp build <artifact> ...` — offline build artifacts.

``build`` is a namespace so future artifacts (e.g. `build embeddings` under
sub-D-4) slot in beside `link-graph`.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from openzim_mcp.linkgraph.builder import build_link_graph


def _link_graph(args: argparse.Namespace) -> int:
    def _progress(done: int, total: int) -> None:
        if not args.quiet:
            print(f"  …walked {done}/{total} entries", file=sys.stderr)

    try:
        stats = build_link_graph(
            args.archive, args.output, force=args.force, progress=_progress
        )
    except FileExistsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — operator CLI: report + nonzero exit
        print(f"error: link-graph build failed: {e}", file=sys.stderr)
        return 2
    out = args.output or f"{args.archive}.linkgraph.sqlite"
    print(
        f"built {out}: {stats.node_count} nodes, {stats.edge_count} edges, "
        f"{stats.bytes_written} bytes"
    )
    return 0


def build_main(argv: Optional[List[str]] = None) -> int:
    """Entry point for `openzim-mcp build ...`. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="openzim-mcp build")
    sub = parser.add_subparsers(dest="artifact", required=True)
    lg = sub.add_parser("link-graph", help="Build the inbound link-graph sidecar.")
    lg.add_argument("archive", help="Path to the .zim archive.")
    lg.add_argument("--output", default=None, help="Sidecar output path.")
    lg.add_argument("--force", action="store_true", help="Overwrite an existing sidecar.")
    lg.add_argument("--quiet", action="store_true", help="Suppress progress output.")
    lg.set_defaults(func=_link_graph)
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:  # unknown artifact / bad args -> nonzero, no traceback
        return int(e.code or 2)
    return int(args.func(args))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/linkgraph/test_build_cli.py -v --no-cov`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/cli/ tests/linkgraph/test_build_cli.py
git commit -m "feat(cli): openzim-mcp build link-graph subcommand"
```

---

### Task 7: Wire `build` dispatch into `main.py`

**Files:**

- Modify: `openzim_mcp/main.py:107-117`
- Test: `tests/test_main.py` (add a dispatch test)

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_main.py
from unittest.mock import patch

import openzim_mcp.main as main_mod


def test_build_subcommand_dispatches(monkeypatch):
    monkeypatch.setattr(main_mod.sys, "argv", ["openzim-mcp", "build", "link-graph", "/x.zim"])
    with patch("openzim_mcp.cli.build.build_main", return_value=0) as mock_build:
        with pytest.raises(SystemExit) as exc:
            main_mod.main()
    assert exc.value.code == 0
    mock_build.assert_called_once_with(argv=["link-graph", "/x.zim"])
```

Add `import pytest` to `tests/test_main.py` if not present.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_main.py::test_build_subcommand_dispatches -v --no-cov`
Expected: FAIL (`main()` runs the server / argparse path instead of dispatching).

- [ ] **Step 3: Add the dispatch (mirror the `download-models` block at `main.py:113-116`)**

```python
# in main(), immediately after the download-models block:
    if len(sys.argv) >= 2 and sys.argv[1] == "build":
        from openzim_mcp.cli.build import build_main

        sys.exit(build_main(argv=sys.argv[2:]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_main.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/main.py tests/test_main.py
git commit -m "feat(cli): dispatch the build subcommand from main()"
```

---

### Task 8: `get_inbound_links_data` data method + async wrapper

**Files:**

- Modify: `openzim_mcp/zim/structure.py` (add `get_inbound_links_data`)
- Modify: `openzim_mcp/async_operations.py` (async wrapper)
- Test: `tests/linkgraph/test_inbound_data.py`

- [ ] **Step 1: Write the failing test (build a real sidecar, mock the archive UUID)**

```python
# tests/linkgraph/test_inbound_data.py
"""get_inbound_links_data reads the sidecar and shapes the Phase-B response."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openzim_mcp.linkgraph.builder import build_from_link_stream
from openzim_mcp.linkgraph.reader import LinkGraphUnavailable, sidecar_path_for


def _ops_with_archive(monkeypatch, tmp_path, uuid):
    """Build a ZimOperations whose path validation + archive UUID are stubbed."""
    from openzim_mcp.zim_operations import ZimOperations  # adjust to real ctor path

    ops = MagicMock(spec=ZimOperations)
    archive_path = tmp_path / "x.zim"
    archive_path.write_bytes(b"")
    ops._validate_zim_path = lambda p: archive_path
    # stub the live-uuid lookup the method uses (see Step 3)
    monkeypatch.setattr(
        "openzim_mcp.zim.structure._live_archive_uuid", lambda p: uuid, raising=False
    )
    return ops, archive_path


def test_inbound_returns_ranked_results(monkeypatch, tmp_path):
    from openzim_mcp.zim.structure import _StructureMixin

    ops, archive = _ops_with_archive(monkeypatch, tmp_path, "u1")
    build_from_link_stream(
        sidecar_path_for(archive),
        archive_uuid="u1",
        link_stream=iter([("C/A", ["C/T"]), ("C/B", ["C/T"]), ("C/X", ["C/A"])]),
    )
    resp = _StructureMixin.get_inbound_links_data(ops, str(archive), "C/T", limit=10)
    paths = [r["path"] for r in resp["results"]]
    assert paths == ["C/A", "C/B"]  # A has inbound_degree 1, ranks first
    assert resp["total"] == 2 and resp["done"] is True
    assert resp["entry_path"] == "C/T"


def test_inbound_missing_sidecar_raises_unavailable(monkeypatch, tmp_path):
    from openzim_mcp.zim.structure import _StructureMixin

    ops, archive = _ops_with_archive(monkeypatch, tmp_path, "u1")
    with pytest.raises(LinkGraphUnavailable):
        _StructureMixin.get_inbound_links_data(ops, str(archive), "C/T", limit=10)
```

The exact stubbing seam (`_validate_zim_path`, live-uuid lookup) depends on how `_StructureMixin` resolves these — align the test with the helper you add in Step 3. Title resolution (`_resolve_outbound_titles`) opens the (empty) stub archive and leaves placeholders, which is fine for the assertion (it checks `path`, not `title`).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/linkgraph/test_inbound_data.py -v --no-cov`
Expected: FAIL with `AttributeError: ... 'get_inbound_links_data'`.

- [ ] **Step 3: Implement `get_inbound_links_data`**

Mirror `get_related_articles_data` (`structure.py:789-946`). Key differences: read from the sidecar instead of computing outbound; emit a real `next_cursor`; raise `LinkGraphUnavailable` when the reader is `None`.

```python
# in _StructureMixin, beside get_related_articles_data
def get_inbound_links_data(
    self,
    zim_file_path: str,
    entry_path: str,
    limit: int = 10,
    offset: int = 0,
    *,
    cursor_archive_identity: Optional[str] = None,
) -> "RelatedArticlesResponse":
    """Inbound linkers for ``entry_path`` from the link-graph sidecar.

    Ranked by each linker's own inbound-degree. Raises ``LinkGraphUnavailable``
    when the sidecar is absent or stale (the tool layer turns that into a
    structured error). Phase-B five-key contract; paginated.
    """
    if limit < 1 or limit > 100:
        raise OpenZimMcpValidationError(
            f"limit must be between 1 and 100 (provided: {limit})"
        )
    if offset < 0:
        raise OpenZimMcpValidationError(
            f"offset must be non-negative (provided: {offset})"
        )
    reject_path_traversal(entry_path)
    validated_path = self._validate_zim_path(zim_file_path)
    validated_str = str(validated_path)

    from openzim_mcp.linkgraph.reader import LinkGraphReader, LinkGraphUnavailable
    from openzim_mcp.pagination import Cursor, archive_identity

    with _zim_ops_mod.zim_archive(Path(validated_str)) as archive:
        live_uuid = str(archive.uuid)
    reader = LinkGraphReader.open_for(validated_str, live_archive_uuid=live_uuid)
    if reader is None:
        raise LinkGraphUnavailable(
            "Inbound links require a link-graph sidecar for this archive. "
            f"Run `openzim-mcp build link-graph {validated_str}` "
            "(rebuild if the archive changed)."
        )
    try:
        page = reader.query_inbound(entry_path, limit=limit, offset=offset)
    finally:
        reader.close()

    results: List[Dict[str, Any]] = [
        {"path": r["path"], "title": r["path"], "inbound_degree": r["inbound_degree"]}
        for r in page.rows
    ]
    self._resolve_outbound_titles(validated_str, results)

    returned = len(results)
    has_more = offset + returned < page.total
    next_cursor = None
    if has_more:
        next_cursor = Cursor.encode(
            tool="get_inbound_links",
            state={
                "o": offset + returned,
                "l": limit,
                "ep": entry_path,
                "ai": archive_identity(validated_path),
            },
        )
    payload: Dict[str, Any] = {
        "entry_path": entry_path,
        "results": results,
        "next_cursor": next_cursor,
        "total": page.total,
        "done": not has_more,
        "page_info": {"offset": offset, "limit": limit, "returned_count": returned},
    }
    return cast("RelatedArticlesResponse", attach_meta(payload, reason=None))
```

Then add the async wrapper in `async_operations.py` beside `get_related_articles_data` (`async_operations.py:678`):

```python
async def get_inbound_links_data(
    self,
    zim_file_path: str,
    entry_path: str,
    limit: int = 10,
    offset: int = 0,
    *,
    cursor_archive_identity: Optional[str] = None,
) -> "RelatedArticlesResponse":
    """Structured variant of inbound link lookup (async)."""
    return await asyncio.to_thread(
        self._ops.get_inbound_links_data,
        zim_file_path,
        entry_path,
        limit,
        offset,
        cursor_archive_identity=cursor_archive_identity,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/linkgraph/test_inbound_data.py -v --no-cov`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/zim/structure.py openzim_mcp/async_operations.py tests/linkgraph/test_inbound_data.py
git commit -m "feat(linkgraph): get_inbound_links_data reads the sidecar (ranked, paginated)"
```

---

### Task 9: Promote `"inbound"` in the `zim_links` tool

**Files:**

- Modify: `openzim_mcp/tools/zim_links.py`
- Test: `tests/test_zim_links_inbound.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_zim_links_inbound.py
"""zim_links direction='inbound' wiring."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.linkgraph.reader import LinkGraphUnavailable
from openzim_mcp.tools.zim_links import register as register_zim_links


@pytest.fixture
def server() -> MagicMock:
    """Return a stand-in server whose mcp.tool decorator stores the fn."""
    srv = MagicMock()
    store: dict[str, Any] = {}
    srv.mcp.tool = lambda *, description="": (lambda fn: store.setdefault(fn.__name__, fn) or fn)
    srv._store = store
    return srv


def _patch_ops(monkeypatch, **methods):
    ops = MagicMock()
    for name, val in methods.items():
        setattr(ops, name, val)
    monkeypatch.setattr(
        "openzim_mcp.async_operations.AsyncZimOperations", lambda _z: ops
    )
    return ops


@pytest.mark.asyncio
async def test_inbound_dispatches_to_data_method(server, monkeypatch):
    ops = _patch_ops(
        monkeypatch,
        get_inbound_links_data=AsyncMock(return_value={"results": [], "total": 0}),
    )
    register_zim_links(server)
    fn = server._store["zim_links"]
    await fn(zim_file_path="/x.zim", entry_path="C/T", direction="inbound", limit=10)
    ops.get_inbound_links_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_inbound_missing_sidecar_is_structured_error(server, monkeypatch):
    _patch_ops(
        monkeypatch,
        get_inbound_links_data=AsyncMock(side_effect=LinkGraphUnavailable("build it")),
    )
    register_zim_links(server)
    fn = server._store["zim_links"]
    result = await fn(zim_file_path="/x.zim", entry_path="C/T", direction="inbound")
    assert result["operation"] == "inbound_sidecar_unavailable"
    assert "build link-graph" in result["message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_zim_links_inbound.py -v --no-cov`
Expected: FAIL — `direction="inbound"` is rejected as `invalid_direction`.

- [ ] **Step 3: Implement the inbound branch**

In `openzim_mcp/tools/zim_links.py`: add `"inbound"` to `_VALID_DIRECTIONS` (line 25) and the `Literal` (line 33). Before the `outbound`/`related` branches, add:

```python
            if direction == "inbound":
                state, cursor_error = decode_cursor_state(
                    cursor, expected_tool="get_inbound_links"
                )
                if cursor_error is not None:
                    return cursor_error
                eff_offset = offset
                if state is not None:
                    ep_error = cursor_context_mismatch(
                        state, field="ep", expected=entry_path, label="entry"
                    )
                    if ep_error is not None:
                        return ep_error
                    eff_offset = int(state.get("o", 0) or 0)
                try:
                    return await ops.get_inbound_links_data(
                        zim_file_path,
                        entry_path,
                        limit=limit if limit is not None else 10,
                        offset=eff_offset,
                        cursor_archive_identity=state.get("ai") if state else None,
                    )
                except LinkGraphUnavailable as e:
                    return tool_error(operation="inbound_sidecar_unavailable", message=str(e))
```

Add the import: `from ..linkgraph.reader import LinkGraphUnavailable`. The error message from the data method already contains "build link-graph", satisfying the test.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_zim_links_inbound.py tests/test_zim_links.py tests/test_zim_pagination_cursor.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/tools/zim_links.py tests/test_zim_links_inbound.py
git commit -m "feat(zim_links): promote 'inbound' direction backed by the link-graph sidecar"
```

---

### Task 10: Update the `zim_links` description + hold the schema-byte budget

**Files:**

- Modify: `openzim_mcp/tools/zim_links_description.md`
- (Maybe) Modify: `tests/test_phase_f_schema_budget.py` (`ALLOCATION` only), `tests/test_phase_f_prototype_parity.py` (snapshot)

- [ ] **Step 1: Run the budget gates to get the current headroom**

Run: `uv run pytest tests/test_phase_f_schema_budget.py tests/test_phase_f_prototype_parity.py -v --no-cov`
Expected: currently PASS. Note the `zim_links` measured bytes vs its `ALLOCATION` (2450) and the total vs cap (24500).

- [ ] **Step 2: Edit the description to document inbound, lean**

In `zim_links_description.md`: change the direction list so `"inbound"` is a real option (drop/replace the "inbound lands in v2.5" NOTE), and note inbound requires a built sidecar. Keep wording tight — every byte counts against the cap. Example replacement for the direction table rows + note:

```
| `"inbound"`  | Pages that link TO this entry, ranked by linker importance. Requires a built link-graph sidecar (`openzim-mcp build link-graph`); absent/stale → structured error. |
```

Remove the now-obsolete `direction="inbound" is reserved for v2.5` line.

- [ ] **Step 3: Run the budget gates again**

Run: `uv run pytest tests/test_phase_f_schema_budget.py tests/test_phase_f_prototype_parity.py -v --no-cov`

- If **PASS**: done — proceed to Step 5.
- If **`test_advanced_total_under_cap` FAILS** (over 24500): trim the description wording further; if still over, raise `zim_links`'s `ALLOCATION` and lower an under-using tool's allocation by the same amount (the total cap is fixed — the test docstring at `tests/test_phase_f_schema_budget.py:76-82` explains this is allowed).
- If **`test_prototype_parity_byte_budget` FAILS** (>5% drift for `zim_links`): the rewritten surface legitimately changed size — update the prototype snapshot for `zim_links` per the failure message's instruction ("re-run Gate 0b ... and re-commit the snapshot").

- [ ] **Step 4: Re-run to confirm green**

Run: `uv run pytest tests/test_phase_f_schema_budget.py tests/test_phase_f_prototype_parity.py -v --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add openzim_mcp/tools/zim_links_description.md tests/test_phase_f_schema_budget.py tests/test_phase_f_prototype_parity.py
git commit -m "feat(zim_links): document inbound direction within the schema-byte budget"
```

---

### Task 11: End-to-end integration on a real fixture archive

**Files:**

- Test: `tests/live/test_live_inbound_linkgraph.py`

This is the only test that needs a real ZIM. Gate it on the existing test-data fixture (`zim_dir` / `ZIM_TEST_DATA_DIR`) so it skips when data is absent, matching the other `tests/live/` and `tests/zim/` integration tests. Check `tests/conftest.py` / `tests/live/conftest.py` for the exact fixture name and reuse it.

- [ ] **Step 1: Write the integration test**

```python
# tests/live/test_live_inbound_linkgraph.py
"""End-to-end: build a link-graph sidecar then query inbound through the data layer."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.live


def test_build_then_inbound_roundtrip(zim_dir: Path, tmp_path: Path) -> None:
    zims = sorted(zim_dir.glob("*.zim"))
    if not zims:
        pytest.skip("no ZIM test data available")
    archive = zims[0]

    from openzim_mcp.linkgraph.builder import build_link_graph
    from openzim_mcp.linkgraph.reader import LinkGraphReader, sidecar_path_for

    out = str(tmp_path / (archive.name + ".linkgraph.sqlite"))
    stats = build_link_graph(str(archive), out, force=True)
    assert stats.edge_count > 0 and stats.node_count > 0

    # Pick a well-linked target: the source with the most outbound links is a
    # safe bet to BE an inbound target for something. Simpler: assert the graph
    # is queryable and ordering holds for any target that has linkers.
    import sqlite3

    conn = sqlite3.connect(out)
    target = conn.execute(
        "SELECT t.path FROM edges e JOIN nodes t ON t.id=e.target_id "
        "GROUP BY e.target_id ORDER BY COUNT(*) DESC LIMIT 1"
    ).fetchone()[0]
    conn.close()

    # Read via the reader using the same fingerprint the builder wrote.
    from openzim_mcp.zim import zim_archive

    with zim_archive(archive) as a:
        uuid = str(a.uuid)
    # Move sidecar next to a stand-in path the reader expects, or point the
    # reader at `out` directly by symlinking; simplest: reader.open_for needs
    # the sibling name, so build to the sibling path instead:
    sibling = sidecar_path_for(str(archive))
    Path(sibling).write_bytes(Path(out).read_bytes())
    try:
        reader = LinkGraphReader.open_for(str(archive), live_archive_uuid=uuid)
        assert reader is not None
        page = reader.query_inbound(target, limit=5, offset=0)
        assert len(page.rows) >= 1
        degs = [r["inbound_degree"] for r in page.rows]
        assert degs == sorted(degs, reverse=True)  # ranked by importance
        reader.close()
    finally:
        Path(sibling).unlink(missing_ok=True)


def test_inbound_absent_sidecar_is_graceful(zim_dir: Path) -> None:
    zims = sorted(zim_dir.glob("*.zim"))
    if not zims:
        pytest.skip("no ZIM test data available")
    from openzim_mcp.linkgraph.reader import LinkGraphReader, sidecar_path_for

    archive = zims[0]
    if Path(sidecar_path_for(str(archive))).exists():
        pytest.skip("a sidecar exists next to the fixture archive")
    from openzim_mcp.zim import zim_archive

    with zim_archive(archive) as a:
        uuid = str(a.uuid)
    assert LinkGraphReader.open_for(str(archive), live_archive_uuid=uuid) is None
```

- [ ] **Step 2: Run it (skips cleanly without data)**

Run: `uv run pytest tests/live/test_live_inbound_linkgraph.py -v --no-cov -m live`
Expected: PASS or SKIP (if no ZIM data locally). In CI's comprehensive job (which downloads priority-1 data) it runs for real.

- [ ] **Step 3: Commit**

```bash
git add tests/live/test_live_inbound_linkgraph.py
git commit -m "test(linkgraph): end-to-end build + inbound roundtrip (live-gated)"
```

---

### Task 12: User-facing docs + roadmap status

**Files:**

- Modify: `website/src/content/docs/api-reference.mdx` (zim_links inbound row)
- Modify: `README.md` (link-graph feature mention, if appropriate)
- Modify: `docs/roadmap.md` (#16 / v2.5.0a2 → implemented)

- [ ] **Step 1: Update the api-reference `zim_links` direction table**

In `website/src/content/docs/api-reference.mdx` (the `zim_links` section, ~line 252): add an `"inbound"` row — "Pages that link to this entry, ranked by linker importance; requires a built `link-graph` sidecar" — and update the "`inbound` is reserved for v2.5" line to describe it as available with the sidecar. Add a short "Building the link-graph sidecar" note documenting `openzim-mcp build link-graph <archive>`.

- [ ] **Step 2: Update the roadmap**

In `docs/roadmap.md`: change the `#16` section + the v2.5.0a2 milestones row from "design spec written / not started" to "implemented" (keep the spec link). Update the conditional-close note only if relevant.

- [ ] **Step 3: Verify markdownlint + the roadmap-sync test**

Run: `uv run pre-commit run markdownlint --files docs/roadmap.md website/src/content/docs/api-reference.mdx README.md`
Run: `uv run pytest tests/test_docs_consistency.py -v --no-cov`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add website/src/content/docs/api-reference.mdx README.md docs/roadmap.md
git commit -m "docs: document the inbound link-graph sidecar + mark v2.5.0a2 implemented"
```

---

### Task 13: Full-suite + gate verification

- [ ] **Step 1: Run the full non-live suite**

Run: `uv run pytest -q --no-cov -p no:cacheprovider`
Expected: all PASS (new tests included), no regressions.

- [ ] **Step 2: Run the quality gates**

Run: `uv run black --check openzim_mcp tests && uv run isort --check-only openzim_mcp tests && uv run mypy openzim_mcp && uv run make security`
Also run the docstring-strict gate the pre-commit hook uses on new/modified files:
`uv run --with flake8-docstrings --with flake8-bugbear --with flake8-comprehensions --with flake8-simplify flake8 --config=.flake8 openzim_mcp/linkgraph openzim_mcp/cli`
Expected: all clean (fix any new docstring D-codes inline — single-line summaries ending in a period, imperative mood for D401).

- [ ] **Step 3: Final commit if any gate fixes were needed**

```bash
git add -A
git commit -m "chore(linkgraph): satisfy lint/type/docstring gates"
```

---

## Self-Review

**Spec coverage:** build CLI (Tasks 6-7) ✓; integer-keyed SQLite sidecar w/ precomputed degree (Tasks 1, 3) ✓; single entry walk + internal-link extraction + redirect canonicalization (Tasks 4-5) ✓; runtime ranked inbound read (Tasks 2, 8) ✓; pagination via offset + `next_cursor` tool-bound to `get_inbound_links` (Tasks 8-9) ✓; `"inbound"` enum promotion + description (Tasks 9-10) ✓; strict staleness refuse (Task 2 fingerprint, Task 8 `LinkGraphUnavailable`) ✓; graceful absence (Tasks 8-9, 11) ✓; atomic temp→rename + force (Task 3) ✓; schema-byte budget gate (Task 10) ✓; build-memory note (interning dict, Task 3) ✓; testing across unit/integration (all tasks + 11) ✓; docs (Task 12) ✓.

**Type consistency:** `sidecar_path_for`, `LinkGraphReader.open_for`/`query_inbound`/`close`, `InboundPage(rows,total)`, `LinkGraphUnavailable`, `build_from_link_stream(out_path, *, archive_uuid, link_stream, force, now_iso)`, `BuildStats(node_count, edge_count, bytes_written)`, `iter_article_links(archive)`, `build_link_graph(archive_path, out_path, *, force, progress)`, `_StructureMixin._parse_internal_link_targets(html, *, source_path, archive)`, `get_inbound_links_data(...)`, cursor tool tag `"get_inbound_links"` — names are used consistently across tasks.

**Known seams to confirm during execution (not placeholders — verified-by-reading-first):** the exact archive-open context manager import (`zim_archive`, used at `structure.py:962`), the entry HTML-content access idiom (mirror `extract_article_links_data`), and the `_StructureMixin` live-UUID/`_validate_zim_path` seam for Task 8's stub. Each task's Step 1 says to align the test with the real seam found while implementing — the signatures above are fixed; only the internal wiring is confirmed in-flight.
