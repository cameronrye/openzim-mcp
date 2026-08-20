"""Tests for the link-graph SQLite schema."""

from __future__ import annotations

import sqlite3

from openzim_mcp.linkgraph.schema import (
    SCHEMA_VERSION,
    apply_build_pragmas,
    create_schema,
)


def test_create_schema_makes_expected_tables_and_index() -> None:
    """Schema creation produces expected tables and edge index."""
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"meta", "nodes", "edges"} <= tables
    indexes = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    }
    assert "edges_by_target" in indexes


def test_schema_version_is_a_positive_int() -> None:
    """SCHEMA_VERSION is a positive integer."""
    assert isinstance(SCHEMA_VERSION, int) and SCHEMA_VERSION >= 1


def test_edges_has_anchor_text_column(tmp_path) -> None:
    """Edges table carries target_id, source_id, and anchor_text columns."""
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(edges)")}
    assert cols == {"target_id", "source_id", "anchor_text"}


def test_schema_version_is_3() -> None:
    """SCHEMA_VERSION equals 3.

    Bumped from 2 when edge targets started being stored in the spelling the
    archive can serve (decoded) rather than the raw percent-encoded href. The
    table shapes did not change, so a v2 file still loads — which is exactly
    why the version has to move: without it the reader accepts a sidecar whose
    non-ASCII targets no caller can look up any more.
    """
    assert SCHEMA_VERSION == 3


def test_apply_build_pragmas_runs_without_error() -> None:
    """Build pragmas apply cleanly on a fresh connection."""
    conn = sqlite3.connect(":memory:")
    apply_build_pragmas(conn)  # must not raise
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 0
