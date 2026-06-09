# Finer `build link-graph` CLI errors (#16) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the coarse `except Exception` catch-all in `openzim-mcp build link-graph` with a pre-flight check + classified `except` blocks so each failure mode (missing file, not-a-ZIM, sidecar-exists, cannot-write) gets a distinct, actionable message and a documented exit code.

**Architecture:** All changes in `_link_graph` in `openzim_mcp/cli/build.py`. Compute the resolved output path up front, run a pre-flight existence/is-file check, then call `build_link_graph` inside an ordered `except` chain (`FileExistsError` → `OpenZimMcpArchiveError` → `(sqlite3.OperationalError, OSError)` → `Exception`). The builder, schema, and tools are untouched.

**Tech Stack:** Python 3.12, argparse, pytest (`capsys`, `tmp_path`).

**Spec:** [docs/specs/2026-06-08-v2.5-build-cli-finer-errors-design.md](../../specs/2026-06-08-v2.5-build-cli-finer-errors-design.md)

---

## Task 1: Add the failing CLI error tests

**Files:**

- Test: `tests/linkgraph/test_build_cli.py`

- [ ] **Step 1: Add the four new tests**

Append to `tests/linkgraph/test_build_cli.py` (the existing imports already cover `build_main` and `BuildStats`; add `import sqlite3` at the top):

```python
def test_build_missing_archive(tmp_path, capsys):
    """A non-existent archive path is reported as 'archive not found' (exit 1)."""
    missing = tmp_path / "nope.zim"
    with patch("openzim_mcp.cli.build.build_link_graph") as mock_build:
        rc = build_main(["link-graph", str(missing)])
    assert rc == 1
    assert "archive not found" in capsys.readouterr().err
    mock_build.assert_not_called()


def test_build_not_a_valid_zim(tmp_path, capsys):
    """A real file that is not a ZIM is reported as 'not a valid ZIM' (exit 1)."""
    bogus = tmp_path / "bogus.zim"
    bogus.write_bytes(b"not a zim file at all")
    rc = build_main(["link-graph", str(bogus)])
    assert rc == 1
    assert "not a valid ZIM archive" in capsys.readouterr().err


def test_build_sidecar_exists_message_mentions_force(tmp_path, capsys):
    """FileExistsError from the builder yields a --force hint (exit 1)."""
    archive = tmp_path / "wiki.zim"
    archive.write_bytes(b"")
    with patch(
        "openzim_mcp.cli.build.build_link_graph",
        side_effect=FileExistsError("exists"),
    ):
        rc = build_main(["link-graph", str(archive)])
    assert rc == 1
    assert "pass --force" in capsys.readouterr().err


def test_build_cannot_write_sidecar(tmp_path, capsys):
    """A SQLite/OS write failure is reported with output context (exit 1)."""
    archive = tmp_path / "wiki.zim"
    archive.write_bytes(b"")
    with patch(
        "openzim_mcp.cli.build.build_link_graph",
        side_effect=sqlite3.OperationalError("unable to open database file"),
    ):
        rc = build_main(["link-graph", str(archive)])
    assert rc == 1
    assert "cannot write sidecar" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/linkgraph/test_build_cli.py -k "missing_archive or not_a_valid or mentions_force or cannot_write" -v --no-cov`
Expected: FAIL — `test_build_missing_archive` calls the builder (no pre-flight yet); `not_a_valid` and `cannot_write` hit the generic catch-all (exit 2, wrong message); `mentions_force` prints the builder's `force=True` text, not `--force`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/linkgraph/test_build_cli.py
git commit -m "test(build-cli): pin finer error messages for link-graph build"
```

---

## Task 2: Rewrite `_link_graph` with pre-flight + classified errors

**Files:**

- Modify: `openzim_mcp/cli/build.py` (imports at top; `_link_graph` lines 16-39)

- [ ] **Step 1: Update imports**

Replace the import block (lines 9-13) with:

```python
import argparse
import os
import sqlite3
import sys
from typing import List, Optional

from openzim_mcp.exceptions import OpenZimMcpArchiveError
from openzim_mcp.linkgraph.builder import build_link_graph
from openzim_mcp.linkgraph.reader import sidecar_path_for
```

- [ ] **Step 2: Replace `_link_graph`**

Replace the whole `_link_graph` function (lines 16-39) with:

```python
def _link_graph(args: argparse.Namespace) -> int:
    """Run the link-graph build for one archive and print a summary.

    Exit codes: 0 success; 1 user-fixable precondition (archive not found /
    not a file / not a valid ZIM / sidecar exists without --force / cannot
    write the sidecar); 2 unexpected build failure.
    """

    def _progress(done: int, total: int) -> None:
        """Emit a one-line progress message to stderr."""
        if not args.quiet:
            print(f"  …walked {done}/{total} entries", file=sys.stderr)

    # Pre-flight separates "missing" from "exists-but-invalid" so each gets a
    # distinct, actionable message instead of surfacing from deep in the
    # libzim open path.
    if not os.path.exists(args.archive):
        print(f"error: archive not found: {args.archive}", file=sys.stderr)
        return 1
    if not os.path.isfile(args.archive):
        print(f"error: not a file: {args.archive}", file=sys.stderr)
        return 1

    out = args.output or sidecar_path_for(args.archive)
    try:
        stats = build_link_graph(
            args.archive, args.output, force=args.force, progress=_progress
        )
    except FileExistsError:
        # FileExistsError is an OSError subclass, so it MUST precede the
        # (sqlite3.OperationalError, OSError) clause below. The CLI builds its
        # own --force message rather than echoing the builder's force=True text.
        print(
            f"error: sidecar already exists: {out}; pass --force to overwrite.",
            file=sys.stderr,
        )
        return 1
    except OpenZimMcpArchiveError:
        # The pre-flight confirmed the file exists, so an open failure here
        # means the file is not a valid ZIM archive.
        print(f"error: not a valid ZIM archive: {args.archive}", file=sys.stderr)
        return 1
    except (sqlite3.OperationalError, OSError) as e:
        print(f"error: cannot write sidecar to {out}: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001 — operator CLI: report + nonzero exit
        print(f"error: link-graph build failed: {e}", file=sys.stderr)
        return 2
    print(
        f"built {out}: {stats.node_count} nodes, {stats.edge_count} edges, "
        f"{stats.bytes_written} bytes"
    )
    return 0
```

- [ ] **Step 3: Run the new tests to verify they pass**

Run: `uv run pytest tests/linkgraph/test_build_cli.py -v --no-cov`
Expected: PASS (all — the 4 new plus the 4 existing success/force/exists/unknown-artifact tests).

- [ ] **Step 4: Commit**

```bash
git add openzim_mcp/cli/build.py
git commit -m "feat(build-cli): finer-grained link-graph build errors (#16)"
```

---

## Task 3: Full verification

- [ ] **Step 1: Run the linkgraph + CLI suite**

Run: `uv run pytest tests/linkgraph/ -v --no-cov`
Expected: PASS (all).

- [ ] **Step 2: Lint + types**

Run: `uv run flake8 openzim_mcp/cli/build.py tests/linkgraph/test_build_cli.py && uv run mypy openzim_mcp/cli/build.py`
Expected: clean.

- [ ] **Step 3: Full suite (no regressions)**

Run: `uv run pytest -q --no-cov`
Expected: all pass, 0 failed.

- [ ] **Step 4: Smoke-test the real CLI messages**

Run: `uv run openzim-mcp build link-graph /does/not/exist.zim; echo "exit=$?"`
Expected: `error: archive not found: /does/not/exist.zim` on stderr, `exit=1`.
