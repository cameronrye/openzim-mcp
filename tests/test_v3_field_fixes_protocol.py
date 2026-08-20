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
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import anyio
import pytest
from mcp import ClientSession
from mcp.shared.exceptions import MCPError
from mcp.shared.memory import create_client_server_memory_streams
from mcp_types import INTERNAL_ERROR, INVALID_PARAMS

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
