"""Wire-level regression tests for the v3.0.0 field-sweep protocol defects.

Each test drives a real client session over in-memory streams (the pattern
``test_mcp_session.py`` established) so the assertions are on the JSON-RPC
error a client actually receives — the code, the message, and what the
message leaks — rather than on a handler's return value.

Defect ids refer to the 2026-08-19 field report:

- D54: modern-era (2026-07-28) ``prompts/get`` collapsed every client
  mistake to ``-32603 Internal server error`` with no detail.
- D55: legacy-era ``prompts/get`` errors rode the SDK's ``code=0`` catch-all.
- D57: prompt error text leaked pydantic boilerplate,
  ``register_prompts.<locals>`` paths and Python ``set`` reprs.
- D56: the stdio transport silently dropped malformed JSON, batch arrays and
  invalid request frames — no ``-32700`` / ``-32600`` was ever written.
"""

import io
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import anyio
import pytest
from mcp import ClientSession
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import MCPError
from mcp.shared.memory import create_client_server_memory_streams
from mcp_types import INTERNAL_ERROR, INVALID_PARAMS, INVALID_REQUEST, PARSE_ERROR

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

# Fragments that must never appear in a prompt error message: SDK function
# paths, pydantic's rendered validation report, and Python collection reprs.
_LEAK_MARKERS = (
    "<locals>",
    "pydantic",
    "validation error",
    "input_value",
    "{'",
    "Error rendering prompt",
)


@asynccontextmanager
async def _client(
    tmp_path: Path, *, modern: bool, server: OpenZimMcpServer | None = None
) -> AsyncIterator[Any]:
    """A connected client on the legacy (``initialize``) or modern (``discover``) era.

    ``raise_exceptions`` is left False so the server answers a handler fault
    on the wire exactly as it does in production — with it True the SDK would
    re-raise an unclassified exception and tear the session down, hiding the
    very response these tests assert on.
    """
    if server is None:
        config = OpenZimMcpConfig(
            allowed_directories=[str(tmp_path)], tool_mode="advanced"
        )
        server = OpenZimMcpServer(config)
    low = server.mcp._lowlevel_server
    async with create_client_server_memory_streams() as (
        client_streams,
        server_streams,
    ):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(
                low.run,
                server_read,
                server_write,
                low.create_initialization_options(),
            )
            async with ClientSession(client_read, client_write) as session:
                if modern:
                    await session.discover()
                else:
                    await session.initialize()
                yield session
            task_group.cancel_scope.cancel()


async def _prompt_error(
    tmp_path: Path,
    *,
    modern: bool,
    name: str,
    arguments: dict[str, str] | None,
    server: OpenZimMcpServer | None = None,
) -> MCPError:
    """The JSON-RPC error a ``prompts/get`` call produces on the given era."""
    async with _client(tmp_path, modern=modern, server=server) as session:
        with anyio.fail_after(10):
            with pytest.raises(MCPError) as excinfo:
                await session.get_prompt(name, arguments)
    return excinfo.value


def _assert_clean(message: str) -> None:
    """D57: the message names things for a human, not for a Python debugger."""
    lowered = message.lower()
    for marker in _LEAK_MARKERS:
        assert marker.lower() not in lowered, f"{marker!r} leaked in {message!r}"


# --------------------------------------------------------------------------
# D54 — modern era: client mistakes are invalid params, not internal errors
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_modern_unknown_prompt_is_invalid_params(tmp_path: Path) -> None:
    """D54: an unknown prompt name is the caller's mistake and says which name."""
    error = await _prompt_error(tmp_path, modern=True, name="nope", arguments={})

    assert error.code == INVALID_PARAMS
    assert "nope" in error.message
    _assert_clean(error.message)


@pytest.mark.asyncio
async def test_modern_missing_arguments_are_invalid_params(tmp_path: Path) -> None:
    """D54: missing required arguments name the prompt and every missing arg."""
    error = await _prompt_error(tmp_path, modern=True, name="summarize", arguments={})

    assert error.code == INVALID_PARAMS
    assert "summarize" in error.message
    assert "zim_file_path" in error.message
    assert "entry_path" in error.message
    _assert_clean(error.message)


@pytest.mark.asyncio
async def test_modern_unexpected_argument_is_invalid_params(tmp_path: Path) -> None:
    """D54: an argument the prompt does not declare is named, not swallowed."""
    error = await _prompt_error(
        tmp_path,
        modern=True,
        name="research",
        arguments={"topic": "x", "bogus": "y"},
    )

    assert error.code == INVALID_PARAMS
    assert "research" in error.message
    assert "bogus" in error.message
    _assert_clean(error.message)


# --------------------------------------------------------------------------
# D55 — legacy era: real JSON-RPC codes instead of the SDK's code 0
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_unknown_prompt_is_invalid_params(tmp_path: Path) -> None:
    """D55: the legacy path must not answer with the meaningless code 0."""
    error = await _prompt_error(tmp_path, modern=False, name="nope", arguments={})

    assert error.code == INVALID_PARAMS
    assert "nope" in error.message
    _assert_clean(error.message)


@pytest.mark.asyncio
async def test_legacy_missing_arguments_are_invalid_params(tmp_path: Path) -> None:
    """D55: missing required arguments are -32602 on the legacy path too."""
    error = await _prompt_error(tmp_path, modern=False, name="summarize", arguments={})

    assert error.code == INVALID_PARAMS
    assert "zim_file_path" in error.message
    assert "entry_path" in error.message
    _assert_clean(error.message)


@pytest.mark.asyncio
async def test_legacy_render_fault_is_internal_error(tmp_path: Path) -> None:
    """D55: a fault inside a prompt body is -32603 and names only the prompt.

    The SDK's catch-all would put the raw exception text on the wire with
    code 0; a client must get a real code, and the exception's internals
    (here a fake absolute path) stay server-side.
    """
    config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)], tool_mode="advanced")
    server = OpenZimMcpServer(config)

    @server.mcp.prompt("faulty")
    def faulty(topic: str) -> str:
        raise RuntimeError("boom at /srv/secret/location")

    error = await _prompt_error(
        tmp_path, modern=False, name="faulty", arguments={"topic": "x"}, server=server
    )

    assert error.code == INTERNAL_ERROR
    assert "faulty" in error.message
    assert "/srv/secret" not in error.message
    assert "boom" not in error.message


# --------------------------------------------------------------------------
# D57 — message quality: stable wording, no internals, deterministic order
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unexpected_argument_message_has_no_pydantic_text(
    tmp_path: Path,
) -> None:
    """D57: the offending argument is named; pydantic's report is not echoed."""
    error = await _prompt_error(
        tmp_path,
        modern=False,
        name="research",
        arguments={"topic": "x", "bogus": "y"},
    )

    assert "bogus" in error.message
    assert "register_prompts" not in error.message
    assert "errors.pydantic.dev" not in error.message
    assert "unexpected_keyword_argument" not in error.message
    _assert_clean(error.message)


@pytest.mark.asyncio
async def test_missing_arguments_are_listed_in_stable_order(tmp_path: Path) -> None:
    """D57: no ``set`` repr — the list is sorted so the text is deterministic."""
    error = await _prompt_error(tmp_path, modern=False, name="summarize", arguments={})

    assert "{'" not in error.message and "'}" not in error.message
    assert error.message.index("entry_path") < error.message.index("zim_file_path")


# --------------------------------------------------------------------------
# D56 — stdio: malformed frames get a JSON-RPC error, not silence
# --------------------------------------------------------------------------

_LEGACY_OPENING = [
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "0"},
            },
        }
    ),
    json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
]

_MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}
_MODERN_OPENING = [
    json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "ping",
            "params": {"_meta": _MODERN_META},
        }
    ),
]

_NOT_JSON = "{ this is not json"
_BATCH = json.dumps(
    [
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        {"jsonrpc": "2.0", "id": 3, "method": "ping"},
    ]
)
_NO_JSONRPC_MEMBER = json.dumps({"id": 4, "method": "ping"})
_BARE_STRING = json.dumps("just a string")


def _ping(request_id: int, *, modern: bool) -> str:
    frame: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": "ping"}
    if modern:
        frame["params"] = {"_meta": _MODERN_META}
    return json.dumps(frame)


def _plug_std_streams(monkeypatch: pytest.MonkeyPatch, frames: list[str]) -> io.BytesIO:
    """Point ``sys.stdin``/``sys.stdout`` at in-memory bytes and return stdout.

    ``stdio_server()`` probes ``sys.stdin.buffer.fileno()`` to decide whether
    to claim fd 0/1; a ``BytesIO`` raises ``UnsupportedOperation`` there, so
    the SDK serves the wire from the in-memory buffers in place — the exact
    production code path, minus the descriptor surgery.
    """
    stdin_bytes = io.BytesIO("".join(f + "\n" for f in frames).encode())
    stdout_bytes = io.BytesIO()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(stdin_bytes, encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(stdout_bytes, encoding="utf-8"))
    return stdout_bytes


def _responses(stdout_bytes: io.BytesIO) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in stdout_bytes.getvalue().decode().splitlines()
        if line.strip()
    ]


async def _serve_stdio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, frames: list[str]
) -> list[dict[str, Any]]:
    """Everything the server writes to stdout for ``frames`` then EOF."""
    config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)], tool_mode="advanced")
    server = OpenZimMcpServer(config)
    stdout_bytes = _plug_std_streams(monkeypatch, frames)
    with anyio.fail_after(20):
        await server.mcp.run_stdio_async()
    return _responses(stdout_bytes)


def _by_id(responses: list[dict[str, Any]], request_id: Any) -> list[dict[str, Any]]:
    return [r for r in responses if "id" in r and r["id"] == request_id]


@pytest.mark.asyncio
@pytest.mark.parametrize("modern", [False, True], ids=["legacy", "modern"])
async def test_stdio_answers_malformed_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, modern: bool
) -> None:
    """D56: parse failures are -32700 with id null, bad requests -32600.

    A hand-rolled client waiting on ids 2-4 used to hang until its own
    timeout: the SDK's stdio reader forwards an undecodable line as a bare
    ``Exception`` item and the dispatcher drops it at debug level. The
    following well-formed ping must still be answered.
    """
    opening = _MODERN_OPENING if modern else _LEGACY_OPENING
    responses = await _serve_stdio(
        monkeypatch,
        tmp_path,
        [
            *opening,
            _NOT_JSON,
            _BATCH,
            _NO_JSONRPC_MEMBER,
            _BARE_STRING,
            _ping(5, modern=modern),
        ],
    )

    errors = [r["error"] for r in responses if "error" in r]
    null_id_errors = [r["error"] for r in _by_id(responses, None)]

    assert [e["code"] for e in null_id_errors].count(PARSE_ERROR) == 1
    # The batch and the bare string: -32600, id null (no id can be recovered).
    assert [e["code"] for e in null_id_errors].count(INVALID_REQUEST) == 2
    # The object that carried a usable id gets it echoed back.
    (no_jsonrpc,) = _by_id(responses, 4)
    assert no_jsonrpc["error"]["code"] == INVALID_REQUEST
    # Nothing else went wrong, and good traffic is unaffected.
    assert len(errors) == 4
    (ping,) = _by_id(responses, 5)
    assert "result" in ping


@pytest.mark.asyncio
async def test_stdio_batch_rejection_says_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """D56: batches were removed in MCP 2025-06-18; the error should say so."""
    responses = await _serve_stdio(
        monkeypatch, tmp_path, [*_LEGACY_OPENING, _BATCH, _ping(5, modern=False)]
    )

    (batch_error,) = [r["error"] for r in _by_id(responses, None)]
    assert batch_error["code"] == INVALID_REQUEST
    assert "batch" in batch_error["message"].lower()


@pytest.mark.asyncio
async def test_stdio_ignores_blank_lines(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A blank line carries no request anyone waits on; answering it would
    turn a client's keepalive newlines into a stream of -32700s."""
    responses = await _serve_stdio(
        monkeypatch, tmp_path, [*_LEGACY_OPENING, "", "   ", _ping(5, modern=False)]
    )

    assert [r for r in responses if "error" in r] == []
    (ping,) = _by_id(responses, 5)
    assert "result" in ping


@pytest.mark.asyncio
async def test_canary_sdk_stdio_still_drops_malformed_frames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Fails the day the locked SDK answers malformed stdio frames itself.

    This runs the SDK's own ``stdio_server`` under the lowlevel server —
    ``MCPServer.run_stdio_async`` minus the repo's relay — and pins the
    silence the relay exists to fill. When this fails: delete
    ``stdio_server_answering_malformed_frames`` from ``sdk_compat.py``, the
    ``run_stdio_async`` override in ``mcp_envelope.py``, and this test. Keep
    the wire tests above — they assert the behavior either way.
    """
    config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)], tool_mode="advanced")
    low = OpenZimMcpServer(config).mcp._lowlevel_server
    stdout_bytes = _plug_std_streams(
        monkeypatch, [*_LEGACY_OPENING, _NOT_JSON, _BATCH, _ping(5, modern=False)]
    )

    with anyio.fail_after(20):
        async with stdio_server() as (read_stream, write_stream):
            await low.run(
                read_stream, write_stream, low.create_initialization_options()
            )

    responses = _responses(stdout_bytes)
    assert [r for r in responses if "error" in r] == []
    assert len(_by_id(responses, 5)) == 1
