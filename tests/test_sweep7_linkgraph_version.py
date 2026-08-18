"""A link-graph sidecar built by the previous release must be rejected.

``_parse_internal_link_edges`` is what the sidecar builder walks, and pass 6
(18567e6) changed the spelling it stores: an edge target is now recorded under
the path the archive can actually serve (``A/El_Niño–Southern_Oscillation``)
rather than the raw percent-encoded href (``A/El_Ni%C3%B1o%E2%80%93Southern_
Oscillation``).

``query_inbound`` matches ``nodes.path`` as an exact string, and callers now
receive the decoded spelling everywhere. So a sidecar built by 2.7.0 answers
every non-ASCII lookup with an empty page — on the shipped corpus that is 36
inbound links silently becoming zero for one article alone — while
``LinkGraphReader.open_for`` still accepts the file, because its fingerprint
only covers ``schema_version`` and ``archive_uuid`` and neither changed.

Bumping ``SCHEMA_VERSION`` converts that silent wrong answer into the
actionable error the module already emits for a stale sidecar: "Run
`openzim-mcp build link-graph <path>` (rebuild it if the archive changed)".
That is the module's stated "strict staleness decision".
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from openzim_mcp.linkgraph.reader import LinkGraphReader, sidecar_path_for
from openzim_mcp.linkgraph.schema import SCHEMA_VERSION

# The version in use while edge targets were still stored percent-encoded.
_PRE_FIX_SCHEMA_VERSION = 2


def test_schema_version_advanced_past_the_encoded_edge_format() -> None:
    assert SCHEMA_VERSION > _PRE_FIX_SCHEMA_VERSION, (
        "pass 6 changed the spelling of stored edge targets but left "
        "SCHEMA_VERSION alone, so a 2.7.0 sidecar is still accepted and "
        "answers every non-ASCII inbound lookup with an empty page"
    )


def _write_sidecar(archive: Path, *, schema_version: str, uuid: str) -> Path:
    path = Path(sidecar_path_for(archive))
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.executemany(
        "INSERT INTO meta VALUES (?, ?)",
        [("schema_version", schema_version), ("archive_uuid", uuid)],
    )
    conn.commit()
    conn.close()
    return path


def test_pre_fix_sidecar_is_rejected(tmp_path: Path) -> None:
    """The old format must read as stale, not as valid-and-empty."""
    archive = tmp_path / "archive.zim"
    archive.write_bytes(b"not a real zim")
    _write_sidecar(archive, schema_version=str(_PRE_FIX_SCHEMA_VERSION), uuid="u1")

    assert LinkGraphReader.open_for(str(archive), live_archive_uuid="u1") is None, (
        "a sidecar whose edge targets are percent-encoded was accepted; "
        "inbound lookups on decoded paths would silently return nothing"
    )


def test_current_sidecar_is_accepted(tmp_path: Path) -> None:
    """Regression guard: the fingerprint must still accept a current file."""
    archive = tmp_path / "archive.zim"
    archive.write_bytes(b"not a real zim")
    _write_sidecar(archive, schema_version=str(SCHEMA_VERSION), uuid="u1")

    reader = LinkGraphReader.open_for(str(archive), live_archive_uuid="u1")
    assert reader is not None
    reader.close()
