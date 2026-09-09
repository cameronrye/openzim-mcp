"""Bad arguments get rejected in the tool surface's own vocabulary.

Two v3.3.1 field-report findings with one shape: the server knows exactly
what is wrong with the call, and says so somewhere a client's branch cannot
reach.

**fid 105** — an out-of-range ``limit`` gets a crisp ``invalid_limit``
envelope on ``zim_query`` / ``zim_search`` / ``zim_get`` and a 635-char
markdown troubleshooting blob on ``zim_browse`` and ``zim_links``, with the
actual cap buried under "Technical Details". The range check exists; it
just lives in the data layer, where it raises the generic validation type.
A client branching on ``operation == "invalid_limit"`` works on three tools
out of five.

**fid 32** — an *empty* ``zim_file_path`` reaches
``PathValidator.validate_path``, which raises parameter-agnostically
("Path must be a non-empty string"), and the wrapper labels the envelope
``Context: Path: iep.utm.edu/stoicism/`` — the one string in the whole
message is the argument that was fine. Omitting the same argument entirely
produces the clean ``invalid_argument`` / ``invalid_arguments:
["zim_file_path"]`` envelope, so the two ways of not supplying an archive
report themselves completely differently.

Every test drives the registered tool handler.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


@pytest.fixture
def server(tmp_path) -> OpenZimMcpServer:
    (tmp_path / "a.zim").write_bytes(b"ZIM\x04" + b"\0" * 100)
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(tmp_path)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
        )
    )


def _handler(server: OpenZimMcpServer, name: str) -> Any:
    return server.mcp._tool_manager._tools[name].fn


def _archive(server: OpenZimMcpServer) -> str:
    return str(server.config.allowed_directories[0]) + "/a.zim"


# ---------------------------------------------------------------------------
# fid 105 — one `invalid_limit` vocabulary across the whole surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,kwargs,cap",
    [
        ("zim_browse", {"namespace": "C", "limit": 201}, 200),
        ("zim_browse", {"namespace": "C", "mode": "walk", "limit": 501}, 500),
        ("zim_links", {"entry_path": "A/X", "limit": 501}, 500),
        ("zim_links", {"entry_path": "A/X", "direction": "inbound", "limit": 101}, 100),
        ("zim_links", {"entry_path": "A/X", "direction": "related", "limit": 101}, 100),
    ],
)
async def test_an_over_cap_limit_gets_the_structured_envelope(
    server, tool, kwargs, cap
):
    out = await _handler(server, tool)(zim_file_path=_archive(server), **kwargs)

    assert out.get("error") is True, out
    assert out["operation"] == "invalid_limit", out
    message = out["message"]
    assert str(cap) in message, message
    assert str(kwargs["limit"]) in message, message
    # Negative: the boilerplate blob the finding measured is gone.
    assert "Troubleshooting Steps" not in message, message
    assert "Technical Details" not in message, message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,kwargs",
    [
        ("zim_browse", {"namespace": "C", "limit": 0}),
        ("zim_browse", {"namespace": "C", "limit": -1}),
        ("zim_links", {"entry_path": "A/X", "limit": 0}),
    ],
)
async def test_a_non_positive_limit_is_rejected_the_same_way(server, tool, kwargs):
    """The data layer's range is ``1 <= limit <= cap``; both ends must land
    in the same envelope or a client still has to parse prose."""
    out = await _handler(server, tool)(zim_file_path=_archive(server), **kwargs)

    assert out.get("error") is True, out
    assert out["operation"] == "invalid_limit", out


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,kwargs",
    [
        ("zim_browse", {"namespace": "C", "limit": 200}),
        ("zim_browse", {"namespace": "C", "mode": "walk", "limit": 500}),
        ("zim_links", {"entry_path": "A/X", "limit": 500}),
        ("zim_links", {"entry_path": "A/X", "direction": "inbound", "limit": 100}),
    ],
)
async def test_a_limit_at_the_cap_is_not_rejected(server, tool, kwargs):
    """Control against an off-by-one that would refuse the documented
    maximum. The call still fails — ``a.zim`` is not a real archive — but it
    must fail for the archive, not for the limit."""
    out = await _handler(server, tool)(zim_file_path=_archive(server), **kwargs)

    assert out.get("operation") != "invalid_limit", out


@pytest.mark.asyncio
async def test_the_whole_surface_now_shares_one_limit_vocabulary(server):
    """fid 105's actual ask, stated as the property.

    ``zim_search`` has always emitted ``invalid_limit``; the point of the
    finding is that a client branching on it should not have to special-case
    two of the five tools that take a ``limit``.
    """
    archive = _archive(server)
    calls = [
        ("zim_search", {"query": "x", "limit": 10_000}),
        ("zim_browse", {"namespace": "C", "limit": 10_000}),
        ("zim_links", {"entry_path": "A/X", "limit": 10_000}),
    ]
    operations = set()
    for tool, kwargs in calls:
        out = await _handler(server, tool)(zim_file_path=archive, **kwargs)
        assert out.get("error") is True, (tool, out)
        operations.add(out["operation"])

    assert operations == {"invalid_limit"}, operations


# ---------------------------------------------------------------------------
# fid 32 — a blank argument names itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,kwargs",
    [
        ("zim_get", {"entry_path": "iep.utm.edu/stoicism/"}),
        ("zim_get_section", {"entry_path": "A/X", "section_id": "H1"}),
        ("zim_links", {"entry_path": "A/X"}),
        ("zim_browse", {"namespace": "C"}),
        ("zim_metadata", {}),
    ],
)
async def test_an_empty_archive_path_names_the_empty_argument(server, tool, kwargs):
    out = await _handler(server, tool)(zim_file_path="", **kwargs)

    assert out.get("error") is True, out
    assert out["operation"] == "invalid_argument", out
    assert out.get("invalid_arguments") == ["zim_file_path"], out
    assert "zim_file_path" in out["message"], out["message"]


@pytest.mark.asyncio
async def test_the_message_stops_blaming_the_argument_that_was_fine(server):
    """The finding's exact evidence: the only concrete string in the
    envelope, printed twice, was the entry path — which was correct."""
    out = await _handler(server, "zim_get")(
        zim_file_path="", entry_path="iep.utm.edu/stoicism/"
    )

    body = json.dumps(out)
    assert "iep.utm.edu/stoicism/" not in body, body
    assert "Path must be a non-empty string" not in body, body


@pytest.mark.asyncio
async def test_whitespace_is_as_empty_as_empty(server):
    """``" "`` reaches the same parameter-agnostic raise one layer down."""
    out = await _handler(server, "zim_get")(zim_file_path="   ", entry_path="A/X")

    assert out["operation"] == "invalid_argument", out
    assert out.get("invalid_arguments") == ["zim_file_path"], out


@pytest.mark.asyncio
async def test_omitting_and_blanking_now_report_the_same_way(server):
    """The two ways of not supplying an archive converge.

    The omitted case is answered by the envelope layer's pydantic mapping
    and already looked like this; the blank case is what fid 32 is about.
    """
    blanked = await _handler(server, "zim_get")(zim_file_path="", entry_path="A/X")
    omitted = await server.mcp.call_tool("zim_get", {"entry_path": "A/X"})
    omitted_body = json.loads(omitted.content[0].text)

    assert blanked["operation"] == omitted_body["operation"] == "invalid_argument"
    assert (
        blanked["invalid_arguments"]
        == omitted_body["invalid_arguments"]
        == ["zim_file_path"]
    )


@pytest.mark.asyncio
async def test_a_real_path_still_gets_through(server):
    """Control: the guard must not swallow a populated argument."""
    out = await _handler(server, "zim_metadata")(zim_file_path=_archive(server))

    assert out.get("operation") != "invalid_argument", out
