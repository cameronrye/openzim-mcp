"""Unknown tool arguments are rejected, not silently dropped.

A follow-up surfaced by the v3.0.0 field-defect sweep (#374). The SDK builds
one pydantic model per tool from the function signature and its base class sets
only ``arbitrary_types_allowed``, so pydantic's default ``extra="ignore"``
applied: ``zim_search(query=..., limitt=2)`` ran at the default page size and
returned ten hits while the caller believed it had asked for two. Nothing on
the wire contradicted them — the published ``inputSchema`` carries no
``additionalProperties: false`` either — and the shipped server instructions
already promise that "A rejected argument is flagged isError with a JSON body
carrying 'error', 'operation' and a 'message' describing how to correct the
call".

Every assertion here drives a real client session over the in-memory transport,
because the defect and its fix both live at the dispatch seam: calling a tool's
function directly, or ``server.mcp.call_tool`` with a dict, never carries the
stray key that far.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer
from tests.test_mcp_session import _connected_client, _text, advanced_session

# Minimal *correctly spelled* arguments for each advanced tool, so the
# parametrised rejection test differs from a valid call by the stray key alone.
_MINIMAL_ARGS: dict[str, dict[str, Any]] = {
    "zim_query": {"query": "climate"},
    "zim_search": {"query": "climate"},
    "zim_get": {"entry_path": "A/Anything"},
    "zim_get_section": {"entry_path": "A/Anything", "section_id": "intro"},
    "zim_browse": {"namespace": "M"},
    "zim_metadata": {},
    "zim_links": {"entry_path": "A/Anything"},
    "zim_health": {},
}


@asynccontextmanager
async def _session_over(directory: Path, tool_mode: str) -> AsyncIterator[Any]:
    """A connected client session whose allowed directory is ``directory``.

    ``tests.test_mcp_session.session_for`` always allows ``tmp_path``; the
    positive-control test needs a session that can actually open the bundled
    archive.
    """
    config = OpenZimMcpConfig(allowed_directories=[str(directory)], tool_mode=tool_mode)
    async with _connected_client(OpenZimMcpServer(config)) as session:
        yield session


def _payload(result: Any) -> dict[str, Any]:
    text = _text(result)
    # Pinned alongside every parse: ``extra="forbid"`` would also reject the
    # call, but as a pydantic ``ValidationError`` the SDK stringifies into a
    # bare text block. That leak is what D04 removed from ``zim_browse``.
    assert "pydantic" not in text, text
    assert "validation error for" not in text, text
    return json.loads(text)


@pytest.mark.asyncio
async def test_misspelled_argument_is_rejected_not_ignored(tmp_path: Path) -> None:
    """The headline regression: ``limitt=2`` used to run at the default page
    size and return ten hits with ``isError=false``."""
    (tmp_path / "a.zim").write_bytes(b"ZIM\x04")
    async with advanced_session(tmp_path) as session:
        result = await session.call_tool(
            "zim_search",
            {
                "query": "climate",
                "zim_file_path": str(tmp_path / "a.zim"),
                "limitt": 2,
            },
        )

    assert result.is_error is True
    payload = _payload(result)
    assert payload["error"] is True
    assert payload["operation"] == "unknown_argument"
    assert "limitt" in payload["message"]
    # The self-correction hint, mirroring the section-id repair in
    # zim/structure.py: a model that reads only ``message`` can still retry.
    assert "'limit'" in payload["message"]
    assert payload["unknown_arguments"] == ["limitt"]
    assert "limit" in payload["accepted_arguments"]
    assert payload["closest_matches"] == {"limitt": "limit"}


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", sorted(_MINIMAL_ARGS))
async def test_every_advanced_tool_rejects_an_undeclared_argument(
    tmp_path: Path, tool_name: str
) -> None:
    """The seam is generic, not ``zim_search``-specific — including
    ``zim_health``, whose only declared property is optional."""
    (tmp_path / "a.zim").write_bytes(b"ZIM\x04")
    arguments = dict(_MINIMAL_ARGS[tool_name])
    arguments["zim_file_path"] = str(tmp_path / "a.zim")
    arguments["nonsense_argument_xyz"] = 1

    async with advanced_session(tmp_path) as session:
        result = await session.call_tool(tool_name, arguments)

    assert result.is_error is True
    payload = _payload(result)
    assert payload["operation"] == "unknown_argument"
    assert payload["unknown_arguments"] == ["nonsense_argument_xyz"]


@pytest.mark.asyncio
async def test_simple_mode_rejects_an_undeclared_argument(tmp_path: Path) -> None:
    """Both tool surfaces share one dispatch seam, so simple mode is covered
    by the same check rather than by a second implementation."""
    (tmp_path / "a.zim").write_bytes(b"ZIM\x04")
    async with _session_over(tmp_path, "simple") as session:
        result = await session.call_tool(
            "zim_query",
            {
                "query": "climate",
                "zim_file_path": str(tmp_path / "a.zim"),
                "limitt": 2,
            },
        )

    assert result.is_error is True
    payload = _payload(result)
    assert payload["operation"] == "unknown_argument"


@pytest.mark.asyncio
async def test_did_you_mean_is_casefold_tolerant(tmp_path: Path) -> None:
    """``difflib`` is case-sensitive and a pure case variant scores under the
    0.6 cutoff, so the easiest typo to repair would otherwise get no
    suggestion. Mirrors the ``sh2d``/``SH2d`` section-id case."""
    (tmp_path / "a.zim").write_bytes(b"ZIM\x04")
    async with advanced_session(tmp_path) as session:
        result = await session.call_tool(
            "zim_get",
            {"zim_file_path": str(tmp_path / "a.zim"), "Entry_Path": "A/Anything"},
        )

    assert result.is_error is True
    payload = _payload(result)
    assert payload["closest_matches"] == {"Entry_Path": "entry_path"}
    assert "'entry_path'" in payload["message"]


@pytest.mark.asyncio
async def test_reserved_meta_key_in_arguments_is_tolerated(tmp_path: Path) -> None:
    """``_meta`` belongs on ``RequestParams`` (``mcp_types._types``), a sibling
    of ``arguments``, so a client nesting it inside ``arguments`` is lenient
    rather than wrong. Tolerating exactly that one key keeps a client's
    protocol metadata from reading as the caller's typo; nothing else is
    tolerated, including other underscore-prefixed keys."""
    (tmp_path / "a.zim").write_bytes(b"ZIM\x04")
    async with advanced_session(tmp_path) as session:
        tolerated = await session.call_tool(
            "zim_health",
            {
                "zim_file_path": str(tmp_path / "a.zim"),
                "_meta": {"progressToken": 1},
            },
        )
        rejected = await session.call_tool(
            "zim_health",
            {"zim_file_path": str(tmp_path / "a.zim"), "_limit": 2},
        )

    assert json.loads(_text(tolerated)).get("operation") != "unknown_argument"
    assert rejected.is_error is True
    assert _payload(rejected)["operation"] == "unknown_argument"


@pytest.mark.asyncio
async def test_correctly_spelled_argument_still_honoured(
    real_content_zim_files: dict[str, Optional[Path]],
) -> None:
    """Positive control against over-rejection: the same call with ``limit``
    spelled correctly still caps the result set."""
    archive = real_content_zim_files["wikipedia_climate"]
    if archive is None:  # pragma: no cover - fixture archive missing
        pytest.skip("wikipedia_en_climate_change_mini fixture not available")

    async with _session_over(archive.parent, "advanced") as session:
        result = await session.call_tool(
            "zim_search",
            {"query": "climate", "zim_file_path": str(archive), "limit": 2},
        )

    assert result.is_error is False
    assert len(_payload(result)["results"]) == 2


def test_rejection_is_runtime_only_and_costs_no_schema_bytes(tmp_path: Path) -> None:
    """Deliberately NOT published as ``additionalProperties: false``.

    The keyword would cost ~29 bytes per tool (~232 across the advanced
    surface) and force a prototype-schema re-snapshot and a Gate 0b re-run.
    The 25600-byte cap in ``tests/test_phase_f_schema_budget.py`` used to be
    the decisive half of that: the surface had ~159 bytes free, so the bytes
    simply were not there. The schema trim freed 1,621 and the argument now
    rests entirely on what the keyword buys, which is nothing — it is only a
    hint, and a client that does not validate still sends the stray key, so
    the runtime rejection below is required either way. Do not "helpfully" add
    the schema keyword on the grounds that the budget can now afford it.
    """
    config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)], tool_mode="advanced")
    server = OpenZimMcpServer(config)

    for tool in server.mcp._tool_manager.list_tools():
        assert "additionalProperties" not in tool.parameters, tool.name
