"""End-to-end: build a link-graph sidecar then query inbound through the reader.

Both tests work on a COPY of an archive. Building a sidecar writes a file
beside the archive it describes, and this test built with ``force=True``, so
pointed at a real library it overwrote the operator's own sidecar with
whatever the builder on the branch under test produced. The archives
themselves are only ever read.
"""

from __future__ import annotations

import math
import shutil
from pathlib import Path
from typing import Optional

import pytest

from tests.live.conftest import usable_zims, writable_copy

pytestmark = pytest.mark.live


def _build_first_linked_archive(zims, workdir: Path) -> Optional[tuple]:
    """Build a sidecar beside a copy of the first archive that yields edges.

    ``zims[0]`` alone was not enough: the fixture corpus leads with
    ``small.zim``, a two-entry archive whose articles link to nothing, so the
    roundtrip asserted importance ranking over an empty edge table. Walk the
    candidates and keep the first that actually has a link graph — the
    behavior under test only exists once there are edges to rank.

    Each candidate is copied into ``workdir`` first, so the sibling sidecar
    the reader expects lands next to the copy. A candidate without edges has
    its copy discarded before the next one is tried.

    Returns ``(archive, sidecar, stats)``, or None.
    """
    from openzim_mcp.linkgraph.builder import build_link_graph
    from openzim_mcp.linkgraph.reader import sidecar_path_for

    for candidate in zims:
        staged = workdir / candidate.stem
        archive = writable_copy(candidate, staged)
        sidecar = sidecar_path_for(str(archive))
        stats = build_link_graph(str(archive), sidecar, force=True)
        if stats.node_count > 0 and stats.edge_count > 0:
            return archive, sidecar, stats
        shutil.rmtree(staged, ignore_errors=True)
    return None


def test_build_then_inbound_roundtrip(zim_dir, tmp_path) -> None:
    """Building a sidecar then querying inbound returns importance-ranked
    linkers, with site furniture sunk below every other linker."""
    # Smallest first: every candidate is copied before it is built, and the
    # smallest archive that has edges is the cheapest way to get one.
    zims = sorted(usable_zims(zim_dir), key=lambda f: f.stat().st_size)
    if not zims:
        pytest.skip("no ZIM test data available")

    from openzim_mcp.linkgraph.reader import LinkGraphReader

    built = _build_first_linked_archive(zims, tmp_path / "staged")
    if built is None:
        pytest.skip("no archive in the corpus produces a non-empty link graph")
    archive, sidecar, stats = built

    assert stats.node_count > 0 and stats.edge_count > 0

    import sqlite3

    conn = sqlite3.connect(sidecar)
    target = conn.execute(
        "SELECT t.path FROM edges e JOIN nodes t ON t.id=e.target_id "
        "GROUP BY e.target_id ORDER BY COUNT(*) DESC LIMIT 1"
    ).fetchone()[0]
    node_count = int(
        conn.execute("SELECT value FROM meta WHERE key='node_count'").fetchone()[0]
    )
    conn.close()

    # Read it back through the public reader, fingerprint-checked.
    from openzim_mcp.zim_operations import zim_archive

    with zim_archive(Path(str(archive))) as a:
        uuid = str(a.uuid)
    reader = LinkGraphReader.open_for(str(archive), live_archive_uuid=uuid)
    assert reader is not None
    page = reader.query_inbound(target, limit=100_000, offset=0)
    reader.close()
    assert len(page.rows) == page.total >= 1

    # Ranked by importance, except that a linker whose degree reaches half
    # the archive is in the nav bar and sinks to the end. Checked over the
    # WHOLE list: the first version read five rows, which never reach the
    # sunk group, so it went on asserting pure degree order. The threshold
    # is recomputed here rather than imported, to cross-check the reader.
    threshold = math.ceil(node_count / 2) if node_count >= 50 else 0
    furniture = [threshold > 0 and r["inbound_degree"] >= threshold for r in page.rows]
    assert furniture == sorted(furniture), "a furniture linker outranks an article"
    for group in (False, True):
        degrees = [
            r["inbound_degree"]
            for r, is_furniture in zip(page.rows, furniture)
            if is_furniture is group
        ]
        assert degrees == sorted(degrees, reverse=True)


def test_inbound_absent_sidecar_is_graceful(disposable_corpus: Path) -> None:
    """With no sidecar present, open_for reports absence (None), not an error.

    On a fresh copy there never is one, so this no longer skips itself on a
    library whose archives have been indexed.
    """
    from openzim_mcp.linkgraph.reader import LinkGraphReader

    archive = sorted(disposable_corpus.glob("*.zim"))[0]
    from openzim_mcp.zim_operations import zim_archive

    with zim_archive(Path(str(archive))) as a:
        uuid = str(a.uuid)
    assert LinkGraphReader.open_for(str(archive), live_archive_uuid=uuid) is None
