"""``zim_links`` must tell the truth about the entry and about itself.

Three v3.3.1 field-report findings against the links surface.

**fid 90** — asked for a redirect spelling, the response header reports the
*stub's* path where its ``title`` should be::

    zim_links("iep.utm.edu/aristotl/")  -> title "iep.utm.edu/aristotl/"
                                           path  "iep.utm.edu/aristotle/"
    zim_get  ("iep.utm.edu/aristotl/")  -> title "Aristotle | Internet …"

zimit gives a redirect stub its own path string as its title, so reading it
"succeeds with junk" — ``_resolve_outbound_titles`` says exactly that, and
already re-resolves it for the ROWS. The bundle header never got the same
treatment: it takes ``entry.title`` from the pre-redirect stub while
deriving ``resolved_path`` from the item, which does follow the redirect.
``direction="inbound"`` handles the same input correctly.

**fid 91** — nothing tells a client whether an archive has a link graph.
The only way to find out is to issue an inbound call and see it fail. The
sidecar's own meta table (``built_at``, ``node_count``, ``edge_count``,
``builder_version``, the archive fingerprint) is already opened and
discarded by the reader.

**fid 92** — the inbound-unavailable message is the one runtime string that
bypasses ``recovery_advice``: it offers an operator shell command and
nothing the client can issue, identically in simple mode where the client
has one tool.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

_MINI = "wikipedia_en_climate_change_mini_2024-06.zim"


def _server(tmp_path: Path, corpus: Optional[Path], mode: str = "advanced") -> Any:
    if corpus is None:
        pytest.skip("ZIM_TEST_DATA_DIR not set")
    source = corpus / "withns" / _MINI
    if not source.exists():
        pytest.skip(f"{_MINI} not in the corpus")
    solo = tmp_path / mode
    solo.mkdir()
    shutil.copy(source, solo / _MINI)
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(solo)],
            tool_mode=mode,
            cache=CacheConfig(enabled=False),
        )
    )


@pytest.fixture
def advanced(tmp_path, zim_test_data_dir):
    server = _server(tmp_path, zim_test_data_dir)
    return server, str(tmp_path / "advanced" / _MINI)


# ---------------------------------------------------------------------------
# fid 91 — say whether the archive has a link graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_says_whether_an_archive_has_a_link_graph(advanced):
    server, archive = advanced
    out = await server.mcp._tool_manager._tools["zim_health"].fn(zim_file_path=archive)

    assert "has_link_graph" in out, sorted(out)
    assert out["has_link_graph"] is False, out


@pytest.mark.asyncio
async def test_a_present_sidecar_is_described_not_just_flagged(advanced, monkeypatch):
    """When there IS one, report the meta the reader already opens.

    "Yes there is a sidecar" does not tell a planner whether it is usable;
    a stale one refuses every inbound call.
    """
    server, archive = advanced
    meta = {
        "schema_version": "3",
        "archive_uuid": "2a11f796-0000-0000-0000-000000000000",
        "built_at": "2026-09-04T16:05:54Z",
        "node_count": "15990",
        "edge_count": "422722",
        "builder_version": "3.3.1",
    }
    monkeypatch.setattr(
        "openzim_mcp.linkgraph.reader.read_sidecar_meta",
        lambda _path: meta,
        raising=False,
    )

    out = await server.mcp._tool_manager._tools["zim_health"].fn(zim_file_path=archive)

    assert out["has_link_graph"] is True, out
    graph = out["link_graph"]
    assert graph["node_count"] == 15990, graph
    assert graph["edge_count"] == 422722, graph
    assert graph["built_at"] == "2026-09-04T16:05:54Z", graph
    assert graph["builder_version"] == "3.3.1", graph


@pytest.mark.asyncio
async def test_a_sidecar_built_for_another_archive_is_reported_as_stale(
    advanced, monkeypatch
):
    """Presence is not usability. A sidecar whose fingerprint does not match
    the live archive refuses every inbound call, and a planner that only saw
    ``has_link_graph: true`` would keep issuing them."""
    server, archive = advanced
    monkeypatch.setattr(
        "openzim_mcp.linkgraph.reader.read_sidecar_meta",
        lambda _path: {
            "schema_version": "3",
            "archive_uuid": "ffffffff-dead-beef-dead-ffffffffffff",
            "built_at": "2025-01-01T00:00:00Z",
            "node_count": "1",
            "edge_count": "1",
            "builder_version": "2.4.0",
        },
        raising=False,
    )

    out = await server.mcp._tool_manager._tools["zim_health"].fn(zim_file_path=archive)

    assert out["has_link_graph"] is True, out
    assert out["link_graph"]["is_stale"] is True, out["link_graph"]


# ---------------------------------------------------------------------------
# fid 92 — the inbound refusal must name something the client can do
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_inbound_refusal_offers_an_in_protocol_fallback(advanced):
    server, archive = advanced
    out = await server.mcp._tool_manager._tools["zim_links"].fn(
        zim_file_path=archive,
        entry_path="A/Climate_change_in_the_Americas",
        direction="inbound",
    )

    assert out.get("error") is True, out
    message = out["message"]
    # The operator sentence stays — an operator may be reading the transcript.
    assert "openzim-mcp build link-graph" in message, message
    # ...and something the *client* can issue is now offered alongside it.
    assert "related" in message, message
    assert "zim_search" in message, message


@pytest.mark.asyncio
async def test_the_fallback_names_tools_a_simple_mode_client_has(
    tmp_path, zim_test_data_dir
):
    """The message is built in the data layer and was identical in both
    modes — naming two tools a simple-mode client cannot call is the exact
    regression v3.3.0 shipped mode-aware advice to prevent."""
    server = _server(tmp_path, zim_test_data_dir, mode="simple")
    archive = str(tmp_path / "simple" / _MINI)

    out = await server.mcp._tool_manager._tools["zim_query"].fn(
        query="what links to A/Climate_change_in_the_Americas",
        zim_file_path=archive,
    )
    text = out if isinstance(out, str) else str(out)

    assert "zim_search" not in text, text
    assert "zim_links" not in text, text


# ---------------------------------------------------------------------------
# fid 90 — the header must describe the entry it actually read
# ---------------------------------------------------------------------------

_REDIRECT = "A/10-year_flood"
_CANONICAL = "A/100-year_flood"


@pytest.mark.asyncio
async def test_a_redirect_header_reports_the_canonical_title(advanced):
    """`title` and `path` described two different articles.

    The bundle takes `entry.title` off the pre-redirect stub while deriving
    `resolved_path` from the item, which does follow the redirect — so the
    header read "10-year flood" beside "A/100-year_flood".
    """
    server, archive = advanced
    out = await server.mcp._tool_manager._tools["zim_links"].fn(
        zim_file_path=archive, entry_path=_REDIRECT, limit=2
    )

    assert out.get("error") is not True, out
    assert out["path"] == _CANONICAL, out
    assert out["title"] == "100-year flood", out


@pytest.mark.asyncio
async def test_the_two_tools_agree_about_the_same_redirect(advanced):
    """`zim_get` already resolved this correctly; the point is the disagreement."""
    server, archive = advanced
    tools = server.mcp._tool_manager._tools

    links = await tools["zim_links"].fn(
        zim_file_path=archive, entry_path=_REDIRECT, limit=2
    )
    got = await tools["zim_get"].fn(zim_file_path=archive, entry_path=_REDIRECT)

    assert links["title"] == got["title"], (links["title"], got["title"])
    assert links["path"] == got["path"]


@pytest.mark.asyncio
async def test_the_spelling_the_caller_used_is_echoed_back(advanced):
    """Outbound rewrote `path` silently. `zim_get` and `direction="inbound"`
    both say which spelling was asked for; a caller correlating a response
    with its request had no handle on this one."""
    server, archive = advanced
    out = await server.mcp._tool_manager._tools["zim_links"].fn(
        zim_file_path=archive, entry_path=_REDIRECT, limit=2
    )

    assert out.get("requested_path") == _REDIRECT, out


@pytest.mark.asyncio
async def test_a_direct_path_is_not_given_a_spurious_echo(advanced):
    """Control: `requested_path` marks a rewrite, so it must be absent when
    nothing was rewritten — otherwise it is noise on every response."""
    server, archive = advanced
    out = await server.mcp._tool_manager._tools["zim_links"].fn(
        zim_file_path=archive, entry_path=_CANONICAL, limit=2
    )

    assert "requested_path" not in out, out
    assert out["title"] == "100-year flood", out
