"""Tests for the link-graph SQLite schema."""

from __future__ import annotations

import sqlite3

from openzim_mcp.linkgraph.schema import SCHEMA_VERSION, create_schema


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
