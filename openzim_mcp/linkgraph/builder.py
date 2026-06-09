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
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Tuple,
)

from openzim_mcp import __version__

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
    link_stream: Iterable[Tuple[str, List[Tuple[str, str]]]],
    force: bool = False,
    now_iso: Optional[str] = None,
    builder_version: Optional[str] = None,
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
        batch: List[Tuple[int, int, str]] = []
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
                ("builder_version", builder_version or __version__),
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


def _is_content_source(path: str, *, has_new_scheme: bool) -> bool:
    """Return whether ``path`` names a content (C-namespace) source entry.

    Scheme-aware, mirroring ``_extract_namespace_from_path`` in
    ``openzim_mcp/zim/namespace.py``:

    * **new-scheme:** libzim's iterable entry surface IS the C namespace and
      entry paths carry no prefix (``Evolution``, not ``C/Evolution``), so
      every iterated entry is a content source — accept all (a non-empty path).
    * **old-scheme:** paths are namespace-prefixed; the namespace is the first
      ``/``-delimited segment (or the first char if no ``/``). Keep only those
      whose namespace is ``C``.
    """
    if not path:
        return False
    if has_new_scheme:
        return True
    # Old-scheme: first segment before '/' (or first char) is the namespace.
    namespace = path.split("/", 1)[0] if "/" in path else path[0]
    return namespace.upper() == "C"


def iter_article_links(archive: Any) -> Iterator[Tuple[str, List[Tuple[str, str]]]]:
    """Yield ``(source_path, [(target, anchor_text), ...])`` per content entry.

    Walk the open archive once via ``_get_entry_by_id`` over ``entry_count``,
    keep only content sources (scheme-aware: see ``_is_content_source``), skip
    redirects-as-source, and reuse ``_parse_internal_link_edges`` for
    extraction + redirect canonicalization. The yielded ``source_path`` is the
    raw ``entry.path`` exactly as libzim returns it for that scheme
    (``"C/Evolution"`` old-scheme, ``"Evolution"`` new-scheme) so it stays
    consistent with what the runtime query layer looks up. Per-entry read
    failures are skipped so one bad entry never aborts the whole build.
    """
    # Imported here (not at module scope) so the pure ``build_from_link_stream``
    # core keeps no dependency on the ZIM/structure layer.
    from openzim_mcp.zim.structure import _StructureMixin

    has_new_scheme = bool(getattr(archive, "has_new_namespace_scheme", False))
    total = int(getattr(archive, "entry_count", 0) or 0)
    for entry_id in range(total):
        try:
            entry = archive._get_entry_by_id(entry_id)
        except Exception:  # nosec B112 - skip unreadable entry, keep walking
            continue
        path = getattr(entry, "path", "")
        if not _is_content_source(path, has_new_scheme=has_new_scheme):
            continue
        if getattr(entry, "is_redirect", False):
            continue
        try:
            html = bytes(entry.get_item().content).decode("utf-8", "replace")
        except Exception:  # nosec B112 - skip entry whose content won't read
            continue
        edges = _StructureMixin._parse_internal_link_edges(
            html, source_path=path, archive=archive
        )
        yield (path, edges)


def build_link_graph(
    archive_path: str,
    out_path: Optional[str] = None,
    *,
    force: bool = False,
    progress: Optional[Callable[[int, int], None]] = None,
) -> BuildStats:
    """Open ``archive_path`` once, walk it, and write the sidecar atomically.

    Streams ``iter_article_links`` straight into ``build_from_link_stream``
    so the whole graph is never held in memory. ``progress`` (if given) is
    invoked as ``progress(processed, total)`` every 10,000 source entries.
    """
    from openzim_mcp.linkgraph.reader import sidecar_path_for
    from openzim_mcp.zim_operations import zim_archive

    out = out_path or sidecar_path_for(archive_path)
    with zim_archive(Path(archive_path)) as archive:
        archive_uuid = str(archive.uuid)
        total = int(getattr(archive, "entry_count", 0) or 0)

        def _stream() -> Iterator[Tuple[str, List[Tuple[str, str]]]]:
            for i, pair in enumerate(iter_article_links(archive)):
                # ``i and`` guards against the spurious 0 % 10_000 == 0 call at
                # the very first entry; report every 10,000 thereafter.
                if progress and i and i % 10_000 == 0:
                    progress(i, total)
                yield pair

        return build_from_link_stream(
            out, archive_uuid=archive_uuid, link_stream=_stream(), force=force
        )
