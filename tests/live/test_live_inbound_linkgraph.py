"""End-to-end: build a link-graph sidecar then query inbound through the reader."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.live


def test_build_then_inbound_roundtrip(zim_dir, tmp_path) -> None:
    """Building a sidecar then querying inbound returns importance-ranked linkers."""
    zims = sorted(zim_dir.glob("*.zim"))
    if not zims:
        pytest.skip("no ZIM test data available")
    archive = zims[0]

    from openzim_mcp.linkgraph.builder import build_link_graph
    from openzim_mcp.linkgraph.reader import LinkGraphReader, sidecar_path_for

    # Build directly to the sibling path the reader expects.
    sidecar = sidecar_path_for(str(archive))
    created_here = not Path(sidecar).exists()
    stats = build_link_graph(str(archive), sidecar, force=True)
    try:
        assert stats.node_count > 0 and stats.edge_count > 0

        import sqlite3

        conn = sqlite3.connect(sidecar)
        target = conn.execute(
            "SELECT t.path FROM edges e JOIN nodes t ON t.id=e.target_id "
            "GROUP BY e.target_id ORDER BY COUNT(*) DESC LIMIT 1"
        ).fetchone()[0]
        conn.close()

        # Read it back through the public reader, fingerprint-checked.
        from openzim_mcp.zim_operations import zim_archive

        with zim_archive(Path(str(archive))) as a:
            uuid = str(a.uuid)
        reader = LinkGraphReader.open_for(str(archive), live_archive_uuid=uuid)
        assert reader is not None
        page = reader.query_inbound(target, limit=5, offset=0)
        assert len(page.rows) >= 1
        degrees = [r["inbound_degree"] for r in page.rows]
        assert degrees == sorted(degrees, reverse=True)  # ranked by importance
        reader.close()
    finally:
        if created_here:
            Path(sidecar).unlink(missing_ok=True)


def test_inbound_absent_sidecar_is_graceful(zim_dir) -> None:
    """With no sidecar present, open_for reports absence (None), not an error."""
    zims = sorted(zim_dir.glob("*.zim"))
    if not zims:
        pytest.skip("no ZIM test data available")
    from openzim_mcp.linkgraph.reader import LinkGraphReader, sidecar_path_for

    archive = zims[0]
    if Path(sidecar_path_for(str(archive))).exists():
        pytest.skip("a sidecar already exists next to the fixture archive")
    from openzim_mcp.zim_operations import zim_archive

    with zim_archive(Path(str(archive))) as a:
        uuid = str(a.uuid)
    assert LinkGraphReader.open_for(str(archive), live_archive_uuid=uuid) is None
