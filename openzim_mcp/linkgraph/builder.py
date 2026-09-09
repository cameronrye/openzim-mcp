"""Build a link-graph sidecar from a stream of (source, [targets]) edges.

``build_from_link_stream`` is the pure, ZIM-free core (testable with synthetic
streams). ``iter_article_links`` and ``build_link_graph`` (Task 5) supply the
real stream from an archive and orchestrate the two.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import suppress
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

logger = logging.getLogger(__name__)

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
    """Return whether ``path`` names a content-namespace source entry.

    Scheme-aware, mirroring ``_extract_namespace_from_path`` in
    ``openzim_mcp/zim/namespace.py``:

    * **new-scheme:** libzim's iterable entry surface IS the C namespace and
      entry paths carry no prefix (``Evolution``, not ``C/Evolution``), so
      every iterated entry is a content source — accept all (a non-empty path).
    * **old-scheme:** paths are namespace-prefixed; the namespace is the first
      ``/``-delimited segment (or the first char if no ``/``). Keep the
      article namespaces: ``A`` (the legacy content namespace real pre-2020
      archives use) and ``C``.
    """
    if not path:
        return False
    if has_new_scheme:
        return True
    # Old-scheme: first segment before '/' (or first char) is the namespace.
    namespace = path.split("/", 1)[0] if "/" in path else path[0]
    return namespace.upper() in {"A", "C"}


# Progress cadence for the walk. The stride is derived from the archive so a
# build reports about fifty times whatever its size — one line every second or
# two on a 30k-entry archive — while a Wikipedia-scale walk stays at one line
# per 10,000 entries instead of emitting hundreds of thousands.
_PROGRESS_MIN_STRIDE = 500
_PROGRESS_MAX_STRIDE = 10_000
_PROGRESS_TARGET_REPORTS = 50


def _progress_stride(total: int) -> int:
    """Entries between progress reports for an archive of ``total`` entries."""
    if total <= 0:
        return _PROGRESS_MAX_STRIDE
    return max(
        _PROGRESS_MIN_STRIDE,
        min(_PROGRESS_MAX_STRIDE, total // _PROGRESS_TARGET_REPORTS),
    )


def iter_article_links(
    archive: Any,
    *,
    progress: Optional[Callable[[int, int], None]] = None,
) -> Iterator[Tuple[str, List[Tuple[str, str]]]]:
    """Yield ``(source_path, [(target, anchor_text), ...])`` per content entry.

    Walk the open archive once via ``_get_entry_by_id`` over ``entry_count``,
    keep only content sources (scheme-aware: see ``_is_content_source``), skip
    redirects-as-source and entries whose item mimetype is not an article type
    (the path filter is namespace-only, so the images, fonts and styles ZIMIT
    stores in the content namespace would otherwise be decoded and parsed as
    HTML), and reuse ``_parse_internal_link_edges`` for
    extraction + redirect canonicalization. The yielded ``source_path`` is the
    raw ``entry.path`` exactly as libzim returns it for that scheme
    (``"C/Evolution"`` old-scheme, ``"Evolution"`` new-scheme) so it stays
    consistent with what the runtime query layer looks up. Per-entry read
    failures are skipped so one bad entry never aborts the whole build.

    ``progress`` (if given) is called ``progress(entries_walked, entry_count)``
    every ``_progress_stride`` entries, and once more on completion. It counts
    ENTRIES WALKED, skips included — the same population as the denominator.
    Counting yielded pairs instead made the numerator a strict subset of the
    denominator (articles are roughly half the entries of a ZIMIT archive), so
    the percentage stalled around half and never reached 100 %, which reads as
    a hung build on the one long-running command in the product.
    """
    # Imported here (not at module scope) so the pure ``build_from_link_stream``
    # core keeps no dependency on the ZIM/structure layer.
    from openzim_mcp.zim.structure import _HTML_MIME_PREFIX, _StructureMixin

    # Mimetypes that can carry link structure. ``_HTML_MIME_PREFIX`` is matched
    # as a prefix so charset parameters ride along ("text/html; charset=utf-8");
    # the XHTML spelling is included because ``_is_non_article_target`` counts
    # it as a real article too.
    article_mimes = (_HTML_MIME_PREFIX, "application/xhtml+xml")

    has_new_scheme = bool(getattr(archive, "has_new_namespace_scheme", False))
    total = int(getattr(archive, "entry_count", 0) or 0)
    stride = _progress_stride(total)
    reported = 0
    for entry_id in range(total):
        # Reported before the filters below, so an entry that is skipped
        # (redirect, image, unreadable) still counts toward the walk the
        # denominator describes.
        walked = entry_id + 1
        if progress is not None and walked % stride == 0:
            reported = walked
            progress(walked, total)
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
            item = entry.get_item()
            # ``_is_content_source`` is namespace-only and accepts EVERY entry
            # on a new-scheme archive, so the images, fonts, styles and PDFs
            # ZIMIT stores in the content namespace arrive here. Decoding those
            # as UTF-8 and handing them to BeautifulSoup interns each asset as a
            # source node with bogus edges and logs a parse failure.
            # ``item.mimetype`` is a dirent header read (no cluster
            # decompression) off the item already in hand, so this gate also
            # skips the asset's content read.
            mime = ""
            with suppress(Exception):
                # A corrupt mimetype code raises (zim-testing-suite ships
                # ``invalid.bad_mimetype_in_dirent.zim``) and mock archives hand
                # back a non-str. An unreadable mimetype fails OPEN: parse it
                # rather than silently drop a real article's outbound edges.
                # ``getattr(..., "")`` would not do — its default only catches
                # AttributeError, letting a RuntimeError skip the entry.
                mime = item.mimetype or ""
            if isinstance(mime, str) and mime and not mime.startswith(article_mimes):
                continue
            html = bytes(item.content).decode("utf-8", "replace")
        except Exception:  # nosec B112 - skip entry whose content won't read
            continue
        try:
            edges = _StructureMixin._parse_internal_link_edges(
                html, source_path=path, archive=archive
            )
        except Exception as exc:  # nosec B112 - one bad entry must not abort
            # ``_classify_anchor`` can still raise on pathological markup
            # (e.g. ``urlparse`` on an unbalanced '[' in the authority).
            # A multi-hour link-graph build must not die on one article.
            logger.warning("Skipping link extraction for %s: %s", path, exc)
            continue
        yield (path, edges)

    # Close the walk on its denominator: a progress line that stops short of
    # the total it reports against is indistinguishable from a stalled build.
    if progress is not None and total and reported != total:
        progress(total, total)


def build_link_graph(
    archive_path: str,
    out_path: Optional[str] = None,
    *,
    force: bool = False,
    progress: Optional[Callable[[int, int], None]] = None,
) -> BuildStats:
    """Open ``archive_path`` once, walk it, and write the sidecar atomically.

    Streams ``iter_article_links`` straight into ``build_from_link_stream`` so
    EDGES are written in batches rather than buffered whole. Note that NODES are
    still held in memory: ``build_from_link_stream`` interns every node path in
    an in-memory id map and materialises the full node list for insertion, so
    peak RSS scales with the article count (GB-scale on a full Wikipedia build),
    not with the edge count. ``progress`` (if given) is invoked as
    ``progress(entries_walked, entry_count)`` — both halves count the same
    population, so the report ends at 100 % (see ``iter_article_links``).
    """
    from openzim_mcp.linkgraph.reader import sidecar_path_for
    from openzim_mcp.zim_operations import zim_archive

    out = out_path or sidecar_path_for(archive_path)
    with zim_archive(Path(archive_path)) as archive:
        archive_uuid = str(archive.uuid)
        total = int(getattr(archive, "entry_count", 0) or 0)

        # The walk owns the reporting: it is the only place that knows how
        # many ENTRIES have been visited, and reporting yielded pairs against
        # ``entry_count`` counted one population against another. Hand it a
        # reporter only when the caller asked for one, so an unwatched build
        # keeps the plain walk.
        if progress is not None:
            walk = iter_article_links(archive, progress=progress)
        else:
            walk = iter_article_links(archive)

        stats = build_from_link_stream(
            out, archive_uuid=archive_uuid, link_stream=walk, force=force
        )
        if total and not stats.node_count:
            # A non-empty archive that yields no content sources means the
            # sidecar will answer every inbound query with a silent zero —
            # surface that instead of letting the empty build look successful.
            logger.warning(
                "link-graph build for %s produced 0 nodes despite %d archive "
                "entries; inbound queries against this sidecar will return "
                "empty results",
                archive_path,
                total,
            )
        return stats
