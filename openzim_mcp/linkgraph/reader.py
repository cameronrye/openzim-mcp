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
from urllib.request import pathname2url

from .schema import SCHEMA_VERSION


class LinkGraphUnavailable(Exception):
    """Raised by the data layer when the inbound sidecar is absent or stale."""


def sidecar_path_for(archive_path: str | Path) -> str:
    """Return the sibling sidecar path: ``<archive>.zim.linkgraph.sqlite``."""
    return f"{archive_path}.linkgraph.sqlite"


@dataclass
class InboundPage:
    """One page of inbound linkers plus the unpaginated total."""

    rows: List[Dict[str, Any]]
    total: int


class LinkGraphReader:
    """Open and query a link-graph sidecar. Construct via ``open_for``."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Store the open read-only SQLite connection."""
        self._conn = conn

    @classmethod
    def open_for(
        cls, archive_path: str, *, live_archive_uuid: str
    ) -> Optional["LinkGraphReader"]:
        """Open the sidecar for ``archive_path`` if present and fingerprint-valid."""
        path = sidecar_path_for(archive_path)
        if not Path(path).is_file():
            return None
        # Percent-encode the path for the file: URI so archives whose path
        # contains a space or other URI-significant character still open
        # read-only (otherwise the URI is malformed and a valid sidecar would
        # silently look absent).
        uri = f"file:{pathname2url(str(Path(path).resolve()))}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        try:
            meta = dict(conn.execute("SELECT key, value FROM meta"))
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

    def query_inbound(
        self, target_path: str, *, limit: int, offset: int
    ) -> InboundPage:
        """Return the inbound linkers of ``target_path``, ranked + paginated."""
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
        """Close the underlying connection."""
        self._conn.close()
