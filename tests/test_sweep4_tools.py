"""Sweep-4 fixes for the advanced tool surface.

Three independent contracts are pinned here:

* an archive-level rejection ("File does not exist") must render the
  "Archive Not Available" template, not the entry-level "Resource Not Found"
  one whose recovery steps hunt inside an archive that was never opened;
* replaying a ``next_cursor`` without repeating ``limit`` must keep the page
  size the cursor was issued under, instead of reverting to the wrapper
  default;
* a decodable cursor whose state carries no resume offset must be rejected
  the way the simple-mode decoder rejects it, not served as a fresh page 1.
"""

from __future__ import annotations

import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.error_messages import get_error_config
from openzim_mcp.exceptions import OpenZimMcpArchivePathError
from openzim_mcp.pagination import Cursor
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.tools._common import decode_cursor_state
from openzim_mcp.tools.zim_browse import register as register_zim_browse
from openzim_mcp.tools.zim_links import register as register_zim_links


@pytest.fixture
def server() -> MagicMock:
    """Stand-in server whose ``mcp.tool`` decorator stores the wrapped fn."""
    srv = MagicMock()
    tools_store: dict[str, Any] = {}

    def _tool(*, description: str = ""):
        def decorate(fn: Any) -> Any:
            tools_store[fn.__name__] = (fn, description)
            return fn

        return decorate

    srv.mcp.tool = _tool
    srv._tools_store = tools_store
    # The real formatter: it touches no instance state, so binding it to the
    # mock exercises the genuine template selection.
    srv._create_enhanced_error_message = types.MethodType(
        OpenZimMcpServer._create_enhanced_error_message, srv
    )
    return srv


def _patch_async_ops(
    monkeypatch: pytest.MonkeyPatch, **method_returns: Any
) -> MagicMock:
    """Patch AsyncZimOperations so each named data method is an AsyncMock."""
    mock_ops = MagicMock()
    for name, value in method_returns.items():
        setattr(mock_ops, name, AsyncMock(return_value=value))
    monkeypatch.setattr(
        "openzim_mcp.async_operations.AsyncZimOperations",
        lambda _zim_ops: mock_ops,
    )
    return mock_ops


# --------------------------------------------------------------------------
# Finding 1 — archive-level failures must not use the entry-level template
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        "File does not exist: /archives/ghost.zim",
        "Path is not a file: /archives/somedir",
        "File is not a ZIM file: /archives/notes.txt",
        "Failed to resolve file path: /archives/broken.zim",
    ],
)
def test_every_archive_path_rejection_uses_the_archive_template(
    message: str,
) -> None:
    """All four ``validate_zim_file`` rejections carry the same advice."""
    config = get_error_config(OpenZimMcpArchivePathError(message))

    assert config is not None, message
    assert config.title == "Archive Not Available", config.title
    assert any("list available ZIM files" in step for step in config.steps)


def test_generic_does_not_exist_still_resolves_not_found() -> None:
    """The message-pattern shortcut stays intact for untyped errors."""
    config = get_error_config(Exception("Entry does not exist"))

    assert config is not None
    assert config.title == "Resource Not Found"


@pytest.mark.asyncio
async def test_missing_archive_envelope_points_at_the_archive_list(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: a hallucinated ``zim_file_path`` must be told to list the
    real archives, not to browse/search for an entry inside a missing file."""
    ops = _patch_async_ops(monkeypatch, extract_article_links_data=None)
    ops.extract_article_links_data.side_effect = OpenZimMcpArchivePathError(
        "File does not exist: /archives/ghost.zim"
    )
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]

    result = await fn(zim_file_path="/archives/ghost.zim", entry_path="A/X")

    assert result["error"] is True
    assert "**Archive Not Available**" in result["message"], result["message"]
    assert "list available ZIM files" in result["message"]
    assert "**Resource Not Found**" not in result["message"]


# --------------------------------------------------------------------------
# Finding 2 — a replayed cursor keeps the page size it was issued under
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outbound_resume_keeps_the_cursor_page_size(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An opaque-cursor client that replays ``next_cursor`` without repeating
    ``limit`` must not silently jump from a 2-row page to a 100-row one."""
    ops = _patch_async_ops(monkeypatch, extract_article_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    cursor = Cursor.encode(
        tool="extract_article_links",
        state={"o": 2, "l": 2, "ep": "A/Cat", "k": "internal", "ai": "qq"},
    )

    await fn(zim_file_path="/x.zim", entry_path="A/Cat", cursor=cursor)

    ops.extract_article_links_data.assert_awaited_once_with(
        "/x.zim",
        "A/Cat",
        limit=2,
        offset=2,
        kind="internal",
        cursor_archive_identity="qq",
    )


@pytest.mark.asyncio
async def test_outbound_explicit_limit_overrides_the_cursor_page_size(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller may still deliberately change page size mid-run."""
    ops = _patch_async_ops(monkeypatch, extract_article_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    cursor = Cursor.encode(
        tool="extract_article_links",
        state={"o": 2, "l": 2, "ep": "A/Cat", "ai": "qq"},
    )

    await fn(zim_file_path="/x.zim", entry_path="A/Cat", cursor=cursor, limit=25)

    assert ops.extract_article_links_data.await_args.kwargs["limit"] == 25


@pytest.mark.asyncio
async def test_outbound_without_cursor_keeps_the_wrapper_default(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, extract_article_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]

    await fn(zim_file_path="/x.zim", entry_path="A/Cat")

    assert ops.extract_article_links_data.await_args.kwargs["limit"] == 100


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [0, -5, True, "50", None])
async def test_outbound_ignores_an_unusable_cursor_page_size(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch, bad: Any
) -> None:
    """A hand-built cursor can carry anything under ``l``; only a positive
    int is honoured, everything else falls back to the default."""
    ops = _patch_async_ops(monkeypatch, extract_article_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    cursor = Cursor.encode(
        tool="extract_article_links",
        state={"o": 2, "l": bad, "ep": "A/Cat"},  # type: ignore[typeddict-item]
    )

    await fn(zim_file_path="/x.zim", entry_path="A/Cat", cursor=cursor)

    assert ops.extract_article_links_data.await_args.kwargs["limit"] == 100


@pytest.mark.asyncio
async def test_inbound_resume_keeps_the_cursor_page_size(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same contract on the inbound branch, whose default is 10."""
    ops = _patch_async_ops(monkeypatch, get_inbound_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    cursor = Cursor.encode(
        tool="get_inbound_links", state={"o": 2, "l": 2, "ep": "A/Cat", "ai": "qq"}
    )

    await fn(
        zim_file_path="/x.zim", entry_path="A/Cat", direction="inbound", cursor=cursor
    )

    ops.get_inbound_links_data.assert_awaited_once_with(
        "/x.zim", "A/Cat", limit=2, offset=2, cursor_archive_identity="qq"
    )


@pytest.mark.asyncio
async def test_inbound_without_cursor_keeps_the_wrapper_default(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_inbound_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]

    await fn(zim_file_path="/x.zim", entry_path="A/Cat", direction="inbound")

    assert ops.get_inbound_links_data.await_args.kwargs["limit"] == 10


# --------------------------------------------------------------------------
# Finding 3 — a cursor with no resume offset is an error, not page 1
# --------------------------------------------------------------------------


def test_decode_cursor_state_rejects_a_stateless_cursor() -> None:
    """``s = {}`` decodes fine but carries no paging position."""
    token = Cursor.encode(tool="browse_namespace", state={})
    state, error = decode_cursor_state(token, expected_tool="browse_namespace")

    assert state is None
    assert error is not None
    assert error["operation"] == "cursor_decode"
    assert "`s.o`" in error["message"]


@pytest.mark.parametrize("offset", [-1, "5", None, True])
def test_decode_cursor_state_rejects_an_unusable_offset(offset: Any) -> None:
    token = Cursor.encode(
        tool="browse_namespace",
        state={"o": offset, "l": 50, "ns": "A"},  # type: ignore[typeddict-item]
    )
    state, error = decode_cursor_state(token, expected_tool="browse_namespace")

    assert state is None
    assert error is not None
    assert error["operation"] == "cursor_decode"


def test_decode_cursor_state_accepts_offset_zero() -> None:
    """Offset 0 is a legitimate resume position and must not be rejected."""
    token = Cursor.encode(tool="browse_namespace", state={"o": 0, "l": 50, "ns": "A"})
    state, error = decode_cursor_state(token, expected_tool="browse_namespace")

    assert error is None
    assert state == {"o": 0, "l": 50, "ns": "A"}


def test_decode_cursor_state_accepts_the_walk_scan_at_alias() -> None:
    """Walk cursors may name the resume position ``scan_at``."""
    token = Cursor.encode(
        tool="walk_namespace", state={"scan_at": 500, "l": 200, "ns": "A", "ai": "zz"}
    )
    state, error = decode_cursor_state(token, expected_tool="walk_namespace")

    assert error is None
    assert state == {"scan_at": 500, "l": 200, "ns": "A", "ai": "zz"}


@pytest.mark.asyncio
async def test_outbound_stateless_cursor_is_not_served_as_page_one(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, extract_article_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    cursor = Cursor.encode(tool="extract_article_links", state={})

    result = await fn(zim_file_path="/x.zim", entry_path="A/Cat", cursor=cursor)

    assert result["operation"] == "cursor_decode"
    ops.extract_article_links_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_inbound_stateless_cursor_is_not_served_as_page_one(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, get_inbound_links_data={"results": []})
    register_zim_links(server)
    fn, _ = server._tools_store["zim_links"]
    cursor = Cursor.encode(tool="get_inbound_links", state={})

    result = await fn(
        zim_file_path="/x.zim", entry_path="A/Cat", direction="inbound", cursor=cursor
    )

    assert result["operation"] == "cursor_decode"
    ops.get_inbound_links_data.assert_not_awaited()


# --------------------------------------------------------------------------
# Finding 2, browse half — the same drift on both zim_browse dispatches
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browse_page_resume_keeps_the_cursor_page_size(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 5-row browse page replayed by cursor must not become a 50-row one."""
    ops = _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(
        tool="browse_namespace",
        state={"o": 5, "l": 5, "ns": "C", "as": False, "ai": "qq"},
    )

    await fn(zim_file_path="/x.zim", namespace="C", cursor=cursor)

    assert ops.browse_namespace_data.await_args.kwargs["limit"] == 5


@pytest.mark.asyncio
async def test_browse_walk_resume_keeps_the_cursor_page_size(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Walk resumes carry their page size in the same ``l`` slot."""
    ops = _patch_async_ops(monkeypatch, walk_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(
        tool="walk_namespace",
        state={"o": 3, "l": 3, "ns": "C", "as": False, "ai": "qq"},
    )

    await fn(zim_file_path="/x.zim", namespace="C", mode="walk", cursor=cursor)

    assert ops.walk_namespace_data.await_args.kwargs["limit"] == 3
    assert ops.walk_namespace_data.await_args.kwargs["cursor_state"]["l"] == 3


@pytest.mark.asyncio
async def test_browse_explicit_limit_overrides_the_cursor_page_size(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]
    cursor = Cursor.encode(
        tool="browse_namespace",
        state={"o": 5, "l": 5, "ns": "C", "as": False, "ai": "qq"},
    )

    await fn(zim_file_path="/x.zim", namespace="C", cursor=cursor, limit=25)

    assert ops.browse_namespace_data.await_args.kwargs["limit"] == 25


@pytest.mark.asyncio
async def test_browse_without_cursor_keeps_the_wrapper_default(
    server: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = _patch_async_ops(monkeypatch, browse_namespace_data={"results": []})
    register_zim_browse(server)
    fn, _ = server._tools_store["zim_browse"]

    await fn(zim_file_path="/x.zim", namespace="C")

    assert ops.browse_namespace_data.await_args.kwargs["limit"] == 50
