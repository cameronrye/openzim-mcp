"""Phase C golden-file regression tests for get_section and synthesize.

Anchors the response-contract shape for get_section_data and synthesize_query
so future changes that unintentionally alter the wire format show up as diffs.

Usage
-----
Capture (or refresh) goldens::

    OPENZIM_MCP_CAPTURE_GOLDENS=1 uv run pytest tests/test_golden_v2_phase_c.py -v

Compare against saved goldens (default)::

    uv run pytest tests/test_golden_v2_phase_c.py -v

Notes
-----
* Uses ``capture_or_compare`` / ``strip_volatile`` from ``conftest_v2_fixtures``.
* ``v2_phase_c_zim`` is a purpose-built heading-rich fixture (A/Berlin, A/Munich)
  because Phase A's articles have no h2/h3 headings and therefore no section IDs
  for ``get_section`` to slice on.
* ``synthesize_query`` is called directly (bypassing ``handle_zim_query`` dispatch)
  to keep the golden independent of simple-tools wiring.
* ``score`` values in passages use rank-inverse (1/rank) — fully deterministic for
  a fixed ZIM, so they are kept in the snapshot.
* ``total_chars`` / ``total_words`` in SynthesizeResponse depend on rendered text
  length, which is deterministic for fixed content, and are also retained.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openzim_mcp.config import SynthesizeConfig
from openzim_mcp.synthesize import synthesize_query
from openzim_mcp.zim_operations import ZimOperations, zim_archive
from tests.conftest_v2_fixtures import (
    capture_or_compare,
    golden_capture_mode,
    make_zim_ops,
)

GOLDENS_DIR = Path(__file__).parent / "data" / "goldens" / "v2_phase_c"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def zim_ops_c(v2_phase_c_zim: Path) -> ZimOperations:
    """Construct a ZimOperations instance pointing at the Phase C fixture archive."""
    return make_zim_ops(str(v2_phase_c_zim.parent))


@pytest.fixture(scope="module")
def zim_path_c(v2_phase_c_zim: Path) -> str:
    """Return the string path to the Phase C fixture ZIM file."""
    return str(v2_phase_c_zim)


@pytest.fixture(scope="session")
def capture_mode() -> bool:
    """Return True when the OPENZIM_MCP_CAPTURE_GOLDENS env var is set to '1'."""
    return golden_capture_mode()


# ---------------------------------------------------------------------------
# get_section golden snapshots
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entry_path,section_id,golden_name",
    [
        ("A/Berlin", "geography", "get_section_berlin_geography"),
        ("A/Berlin", "climate", "get_section_berlin_climate"),
        ("A/Munich", "history", "get_section_munich_history"),
    ],
)
def test_golden_get_section(
    zim_ops_c: ZimOperations,
    zim_path_c: str,
    entry_path: str,
    section_id: str,
    golden_name: str,
    capture_mode: bool,
) -> None:
    """get_section_data — snapshot of a named section from the heading-rich fixture."""
    payload = zim_ops_c.get_section_data(zim_path_c, entry_path, section_id=section_id)
    assert (
        "error" not in payload
    ), f"get_section_data returned an error for {entry_path}#{section_id}: {payload}"
    capture_or_compare(
        golden_name, dict(payload), capture_mode=capture_mode, goldens_dir=GOLDENS_DIR
    )


# ---------------------------------------------------------------------------
# synthesize golden snapshots
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query,golden_name",
    [
        ("berlin geography", "synthesize_berlin_geography"),
        ("munich history", "synthesize_munich_history"),
        ("capital city", "synthesize_capital_city"),
    ],
)
def test_golden_synthesize(
    zim_ops_c: ZimOperations,
    v2_phase_c_zim: Path,
    query: str,
    golden_name: str,
    capture_mode: bool,
) -> None:
    """synthesize_query — end-to-end snapshot for deterministic queries."""
    with zim_archive(v2_phase_c_zim) as archive:
        response = synthesize_query(
            query,
            archives=[(archive, v2_phase_c_zim)],
            search_handler=zim_ops_c,
            cache=zim_ops_c.cache,
            content_processor=zim_ops_c.content_processor,
            config=SynthesizeConfig(),
        )
    capture_or_compare(
        golden_name, dict(response), capture_mode=capture_mode, goldens_dir=GOLDENS_DIR
    )
