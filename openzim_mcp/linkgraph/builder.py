"""Build a link-graph sidecar from a stream of (source, [targets]) edges.

``build_from_link_stream`` is the pure, ZIM-free core (testable with synthetic
streams). ``iter_article_links`` and ``build_link_graph`` (Task 5) supply the
real stream from an archive and orchestrate the two.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

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
