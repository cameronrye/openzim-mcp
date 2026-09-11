""" "What links here?" must not answer with the site's navigation.

v3.3.1 field report, fid 86 (ranking half). Inbound linkers were ranked
``ORDER BY n.inbound_degree DESC`` — a signal site boilerplate maximises.
A page in the nav bar links to everything and is therefore linked FROM
everything, so it wins that ordering on every query, and the caller asking
what links to an article gets the alphabet index instead of the articles.

Measured on the shipped IEP sidecar: 366 of 371 article targets get a real
article at rank 1 under the fix, where before they got the index page.

The demote is by RANK, not by removal: rows are only reordered, so
``total``, the pagination arithmetic and the cursor contract are untouched.
A node whose inbound degree reaches half the archive's node count is
treated as site-wide furniture. Small archives are exempt — on a
twenty-page archive a genuinely central article can legitimately be linked
from half of it, and there is no boilerplate to separate it from.

The builder-scoping half of fid 86 was deliberately NOT taken: feeding the
builder ``select_main_content`` inherits the furniture strips, which on
MedlinePlus delete "Related Health Topics" — 165 of 174 strip-only removals
in a 250-page sample were genuine topic pages. That would trade a cosmetic
contradiction between the two directions for the loss of MedlinePlus's best
inbound signal.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from openzim_mcp.linkgraph.reader import LinkGraphReader, sidecar_path_for
from openzim_mcp.linkgraph.schema import SCHEMA_VERSION

_UUID = "11111111-2222-3333-4444-555555555555"


def _sidecar(tmp_path: Path, *, nodes, edges, node_count=None) -> Path:
    """Build a minimal sidecar. ``nodes`` is [(id, path, inbound_degree)]."""
    archive = tmp_path / "a.zim"
    archive.write_bytes(b"ZIM\x04" + b"\0" * 100)
    db = Path(sidecar_path_for(str(archive)))
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE nodes (id INTEGER PRIMARY KEY, path TEXT, inbound_degree INTEGER);
        CREATE TABLE edges (source_id INTEGER, target_id INTEGER, anchor_text TEXT);
        """)
    conn.executemany(
        "INSERT INTO meta VALUES (?, ?)",
        [
            ("schema_version", str(SCHEMA_VERSION)),
            ("archive_uuid", _UUID),
            ("node_count", str(node_count if node_count is not None else len(nodes))),
        ],
    )
    conn.executemany("INSERT INTO nodes VALUES (?, ?, ?)", nodes)
    conn.executemany("INSERT INTO edges VALUES (?, ?, ?)", edges)
    conn.commit()
    conn.close()
    return archive


def _open(archive: Path) -> LinkGraphReader:
    reader = LinkGraphReader.open_for(str(archive), live_archive_uuid=_UUID)
    assert reader is not None
    return reader


# A 100-node archive: node 1 is in the nav bar (linked from 90 of them), the
# rest are ordinary articles. All four link to the target, node 5.
def _nav_bar_archive(tmp_path: Path) -> Path:
    nodes = [
        (1, "a.org/index-of-everything/", 90),
        (2, "a.org/aristotle/", 12),
        (3, "a.org/plato/", 8),
        (5, "a.org/target/", 3),
    ]
    edges = [(1, 5, "Index"), (2, 5, "Aristotle"), (3, 5, "Plato")]
    return _sidecar(tmp_path, nodes=nodes, edges=edges, node_count=100)


def test_site_furniture_does_not_lead_the_answer(tmp_path):
    reader = _open(_nav_bar_archive(tmp_path))
    try:
        page = reader.query_inbound("a.org/target/", limit=10, offset=0)
    finally:
        reader.close()

    assert [r["path"] for r in page.rows] == [
        "a.org/aristotle/",
        "a.org/plato/",
        "a.org/index-of-everything/",
    ]


def test_the_furniture_row_is_still_returned(tmp_path):
    """A demote, not a filter. Paired with the test above so "the index is
    not first" cannot be satisfied by dropping it — it IS a real linker, and
    a caller enumerating linkers must still see it."""
    reader = _open(_nav_bar_archive(tmp_path))
    try:
        page = reader.query_inbound("a.org/target/", limit=10, offset=0)
    finally:
        reader.close()

    assert len(page.rows) == 3
    assert page.total == 3


def test_ordinary_linkers_keep_degree_ordering_among_themselves(tmp_path):
    """Below the furniture threshold, inbound degree is still the signal —
    the fix is about separating boilerplate from articles, not about
    abandoning the ranking."""
    reader = _open(_nav_bar_archive(tmp_path))
    try:
        rows = reader.query_inbound("a.org/target/", limit=10, offset=0).rows
    finally:
        reader.close()

    ordinary = [r for r in rows if "index-of-everything" not in r["path"]]
    assert [r["inbound_degree"] for r in ordinary] == [12, 8]


def test_a_small_archive_is_exempt(tmp_path):
    """On a tiny archive a genuinely central article can be linked from half
    of it, and there is no boilerplate to separate it from. Without this the
    fix would demote the single most useful linker on small archives."""
    nodes = [(1, "a.org/hub/", 9), (2, "a.org/x/", 2), (5, "a.org/target/", 1)]
    edges = [(1, 5, "Hub"), (2, 5, "X")]
    archive = _sidecar(tmp_path, nodes=nodes, edges=edges, node_count=12)

    reader = _open(archive)
    try:
        rows = reader.query_inbound("a.org/target/", limit=10, offset=0).rows
    finally:
        reader.close()

    assert rows[0]["path"] == "a.org/hub/"


def test_pagination_still_spans_every_linker(tmp_path):
    """The demote reorders within the full set, so paging must still reach
    every row exactly once — the cursor contract depends on it."""
    reader = _open(_nav_bar_archive(tmp_path))
    try:
        first = reader.query_inbound("a.org/target/", limit=2, offset=0)
        second = reader.query_inbound("a.org/target/", limit=2, offset=2)
    finally:
        reader.close()

    seen = [r["path"] for r in first.rows] + [r["path"] for r in second.rows]
    assert sorted(seen) == sorted(
        ["a.org/aristotle/", "a.org/plato/", "a.org/index-of-everything/"]
    )
    assert first.total == second.total == 3


def test_a_sidecar_without_node_count_still_answers(tmp_path):
    """Older sidecars of the same schema may lack the key. Degrading to the
    previous ordering is right; refusing to answer is not."""
    nodes = [(1, "a.org/hub/", 90), (2, "a.org/x/", 2), (5, "a.org/target/", 1)]
    edges = [(1, 5, "Hub"), (2, 5, "X")]
    archive = tmp_path / "b.zim"
    archive.write_bytes(b"ZIM\x04" + b"\0" * 100)
    db = Path(sidecar_path_for(str(archive)))
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE nodes (id INTEGER PRIMARY KEY, path TEXT, inbound_degree INTEGER);
        CREATE TABLE edges (source_id INTEGER, target_id INTEGER, anchor_text TEXT);
        """)
    conn.executemany(
        "INSERT INTO meta VALUES (?, ?)",
        [("schema_version", str(SCHEMA_VERSION)), ("archive_uuid", _UUID)],
    )
    conn.executemany("INSERT INTO nodes VALUES (?, ?, ?)", nodes)
    conn.executemany("INSERT INTO edges VALUES (?, ?, ?)", edges)
    conn.commit()
    conn.close()

    reader = _open(archive)
    try:
        rows = reader.query_inbound("a.org/target/", limit=10, offset=0).rows
    finally:
        reader.close()

    assert [r["path"] for r in rows] == ["a.org/hub/", "a.org/x/"]


@pytest.mark.live
def test_the_shipped_iep_sidecar_leads_with_an_article():
    """The measured case, on the real sidecar rather than a fixture."""
    import os

    iep = "/Users/cameron/Developer/zim/internet-encyclopedia-philosophy_en_all_2025-06.zim"
    if not os.path.exists(sidecar_path_for(iep)):
        pytest.skip("IEP sidecar not present")

    from openzim_mcp.zim.archive import zim_archive

    with zim_archive(Path(iep)) as archive:
        uuid = str(archive.uuid)
    reader = LinkGraphReader.open_for(iep, live_archive_uuid=uuid)
    if reader is None:
        pytest.skip("IEP sidecar is stale for this archive")
    try:
        rows = reader.query_inbound(
            "iep.utm.edu/hume-causation/", limit=5, offset=0
        ).rows
    finally:
        reader.close()

    assert rows, "no inbound linkers for a well-linked article"
    # The alphabet index (iep.utm.edu/a/ and friends) must not lead.
    assert len(rows[0]["path"].rstrip("/").rsplit("/", 1)[-1]) > 2, rows[0]


@pytest.mark.parametrize(
    "node_count,expected",
    [
        (0, 0),
        (49, 0),  # below the exemption floor
        (50, 25),
        (100, 50),
        (101, 51),  # ODD: "at least half" must round UP, not truncate
        (999, 500),
        (None, 0),
        ("not-a-number", 0),
        ("-5", 0),
    ],
)
def test_the_furniture_threshold_is_a_true_ceiling(node_count, expected):
    """The docstring says "at least half", and the first implementation did
    not do that: ``-(-int(x) // 1)`` truncates inside ``int()`` before the
    ceiling idiom runs, so it computed the FLOOR and was off by one on every
    odd node count. Nothing in the file pinned the arithmetic, so it passed.
    """
    from openzim_mcp.linkgraph.reader import _furniture_threshold

    assert _furniture_threshold(node_count) == expected
