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


# A node linked from at least half the archive is site furniture, not a topic:
# it is in the nav bar. Below ``_MIN_ARCHIVE_FOR_FURNITURE`` nodes there is no
# boilerplate to separate an article from — on a twenty-page archive a
# genuinely central article can legitimately be linked from half of it — so the
# demotion is switched off rather than applied to a population too small to
# have the pattern. Returns 0 when it should not apply, including for an older
# sidecar of this schema that never stored ``node_count``.
_FURNITURE_DEGREE_FRACTION = 0.5
_MIN_ARCHIVE_FOR_FURNITURE = 50


def _furniture_threshold(node_count: Optional[str]) -> int:
    """Inbound degree at or above which a node counts as site furniture."""
    try:
        total = int(node_count or 0)
    except (TypeError, ValueError):
        return 0
    if total < _MIN_ARCHIVE_FOR_FURNITURE:
        return 0
    return -(-int(total * _FURNITURE_DEGREE_FRACTION) // 1)


class LinkGraphReader:
    """Open and query a link-graph sidecar. Construct via ``open_for``."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Store the open read-only SQLite connection."""
        self._conn = conn
        self._furniture_threshold: Optional[int] = None

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
        reader = cls(conn)
        reader._furniture_threshold = _furniture_threshold(meta.get("node_count"))
        return reader

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
        # v3.3.1 field report (fid 86): ranking purely on inbound_degree
        # answered "what links here?" with the site's navigation. A page in
        # the nav bar links to everything and is therefore linked FROM
        # everything, so it won this ordering on every single query — on the
        # shipped IEP sidecar the alphabet index led 366 of 371 article
        # targets. Nodes at or above the threshold sink as a group; below it,
        # inbound degree is still the signal.
        #
        # A demote by RANK only: no row is dropped, so ``total``, the
        # pagination arithmetic and the cursor contract are untouched.
        # ``threshold`` of 0 disables the clause (small or unlabelled
        # archives), leaving exactly the previous ordering.
        threshold = self._furniture_threshold or 0
        cur = self._conn.execute(
            """
            SELECT n.path, n.inbound_degree, e.anchor_text
              FROM edges e JOIN nodes n ON n.id = e.source_id
             WHERE e.target_id = :target_id
             ORDER BY (:threshold > 0 AND n.inbound_degree >= :threshold) ASC,
                      n.inbound_degree DESC,
                      n.path ASC
             LIMIT :limit OFFSET :offset
            """,
            {
                "target_id": target_id,
                "threshold": threshold,
                "limit": limit,
                "offset": offset,
            },
        )
        rows = [
            {"path": p, "inbound_degree": d, "anchor_text": a}
            for (p, d, a) in cur.fetchall()
        ]
        return InboundPage(rows=rows, total=int(total))

    def close(self) -> None:
        """Close the underlying connection."""
        self._conn.close()


def read_sidecar_meta(archive_path: str) -> Optional[Dict[str, str]]:
    """The sidecar's ``meta`` table for ``archive_path``, or ``None``.

    Deliberately does NOT apply ``open_for``'s fingerprint gate. That gate
    exists so a stale sidecar cannot answer a query with another archive's
    edges; this function exists to *describe* what is on disk, and "there is
    a sidecar and it is stale" is precisely the answer a planner needs and
    could not previously get. v3.3.1 field report (fid 91): the only way to
    learn whether an archive had a link graph was to issue an inbound call
    and see it fail.

    Returns ``None`` when there is no sidecar file, or when the file is
    present but not a readable SQLite database carrying a meta table — both
    of which mean "no link graph you can use" from the caller's side.
    """
    path = sidecar_path_for(archive_path)
    if not Path(path).is_file():
        return None
    uri = f"file:{pathname2url(str(Path(path).resolve()))}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return None
    try:
        return {str(k): str(v) for k, v in conn.execute("SELECT key, value FROM meta")}
    except sqlite3.DatabaseError:
        return None
    finally:
        conn.close()
