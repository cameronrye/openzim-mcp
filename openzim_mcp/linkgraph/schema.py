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
