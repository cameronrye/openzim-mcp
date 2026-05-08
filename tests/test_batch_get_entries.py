"""Tests for the get_zim_entries MCP tool registration and async wrapper."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.async_operations import AsyncZimOperations
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


@pytest.mark.asyncio
async def test_async_get_entries_wraps_sync():
    """The async wrapper delegates to the sync ZimOperations.get_entries."""
    sync_ops = MagicMock()
    sync_ops.get_entries.return_value = '{"results": [], "succeeded": 0, "failed": 0}'
    async_ops = AsyncZimOperations(sync_ops)

    result = await async_ops.get_entries(
        [{"zim_file_path": "/x", "entry_path": "y"}], None
    )

    sync_ops.get_entries.assert_called_once()
    assert json.loads(result)["succeeded"] == 0


def test_get_zim_entries_tool_is_registered(test_config: OpenZimMcpConfig):
    """The get_zim_entries tool appears in the registered FastMCP tool set."""
    server = OpenZimMcpServer(test_config)
    # FastMCP exposes _tool_manager / list_tools across SDK versions; we look
    # via the public tool listing if available, else fall back to the manager.
    tools = (
        server.mcp._tool_manager._tools if hasattr(server.mcp, "_tool_manager") else {}
    )
    assert (
        "get_zim_entries" in tools
    ), f"expected get_zim_entries in registered tools, got {list(tools)}"


@pytest.mark.asyncio
async def test_get_zim_entries_tool_passes_through(
    test_config: OpenZimMcpConfig,
):
    """Calling the registered tool function delegates to async_zim_operations."""
    server = OpenZimMcpServer(test_config)
    server.async_zim_operations.get_entries_data = AsyncMock(
        return_value={"results": [], "succeeded": 0, "failed": 0}
    )
    server.rate_limiter.check_rate_limit = MagicMock()

    tool = server.mcp._tool_manager._tools["get_zim_entries"]
    # FastMCP wraps the registered function; ToolDefinition.fn / .func varies.
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None)
    assert fn is not None, f"could not find callable on tool object: {tool!r}"

    result = await fn(
        entries=[{"zim_file_path": "/x", "entry_path": "y"}],
    )
    assert isinstance(result, dict)
    assert result["succeeded"] == 0
    server.async_zim_operations.get_entries_data.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_zim_entries_tool_sanitizes_inputs(
    test_config: OpenZimMcpConfig,
):
    """Per-entry paths go through sanitize_input before delegation."""
    server = OpenZimMcpServer(test_config)
    server.async_zim_operations.get_entries_data = AsyncMock(
        return_value={"results": [], "succeeded": 0, "failed": 0}
    )
    server.rate_limiter.check_rate_limit = MagicMock()

    tool = server.mcp._tool_manager._tools["get_zim_entries"]
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None)

    bad_path = "  /zim/wiki.zim  "
    bad_entry = "  A/Article\x00\n"
    await fn(
        entries=[{"zim_file_path": bad_path, "entry_path": bad_entry}],
    )
    # The args passed to the async op are the *sanitized* values.
    call = server.async_zim_operations.get_entries_data.await_args
    sent_entries = call.args[0]
    assert sent_entries[0]["zim_file_path"].strip() == "/zim/wiki.zim"
    assert "\x00" not in sent_entries[0]["entry_path"]
    assert sent_entries[0]["entry_path"].strip() == "A/Article"


@pytest.mark.asyncio
async def test_get_zim_entries_tool_rate_limit_error(
    test_config: OpenZimMcpConfig,
):
    """Rate-limit errors are converted to enhanced error messages."""
    from openzim_mcp.exceptions import OpenZimMcpRateLimitError

    server = OpenZimMcpServer(test_config)
    server.rate_limiter.check_rate_limit = MagicMock(
        side_effect=OpenZimMcpRateLimitError("rate limit hit")
    )
    server.async_zim_operations.get_entries_data = AsyncMock()

    tool = server.mcp._tool_manager._tools["get_zim_entries"]
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None)

    result = await fn(entries=[{"zim_file_path": "/x", "entry_path": "y"}])
    # Rate-limit error → never delegates to async op
    server.async_zim_operations.get_entries_data.assert_not_awaited()
    # Structured error envelope: error=True, with batch-size context.
    assert isinstance(result, dict)
    assert result.get("error") is True
    assert "Batch size: 1" in result.get("context", "")


@pytest.mark.asyncio
async def test_get_zim_entries_tool_exception_returns_error_message(
    test_config: OpenZimMcpConfig,
):
    """Generic exceptions in the async op are wrapped in an error message."""
    server = OpenZimMcpServer(test_config)
    server.rate_limiter.check_rate_limit = MagicMock()
    server.async_zim_operations.get_entries_data = AsyncMock(
        side_effect=RuntimeError("unexpected failure")
    )

    tool = server.mcp._tool_manager._tools["get_zim_entries"]
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None)

    result = await fn(entries=[{"zim_file_path": "/x", "entry_path": "y"}])
    assert isinstance(result, dict)
    assert result.get("error") is True
    assert "Batch size: 1" in result.get("context", "")
    # The error message surfaces the underlying message somewhere.
    message = result.get("message", "")
    assert "unexpected failure" in message or "RuntimeError" in message


@pytest.mark.asyncio
async def test_get_zim_entries_tool_accepts_string_paths_with_default_archive(
    test_config: OpenZimMcpConfig,
):
    """Bare strings are valid entry paths, paired with the kwarg-level archive."""
    server = OpenZimMcpServer(test_config)
    server.rate_limiter.check_rate_limit = MagicMock()
    server.async_zim_operations.get_entries_data = AsyncMock(
        return_value={"results": [], "succeeded": 0, "failed": 0}
    )

    tool = server.mcp._tool_manager._tools["get_zim_entries"]
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None)

    # Mix a bare-string entry path with a fully-qualified dict.
    await fn(
        entries=[
            "A/Foo",  # paired with default zim_file_path
            {"zim_file_path": "/ok", "entry_path": "ok"},
        ],
        zim_file_path="/default.zim",
    )
    call = server.async_zim_operations.get_entries_data.await_args
    sent_entries = call.args[0]
    assert len(sent_entries) == 2
    assert sent_entries[0] == {"zim_file_path": "/default.zim", "entry_path": "A/Foo"}
    assert sent_entries[1]["zim_file_path"] == "/ok"


class TestGetEntriesDataMeta:
    """get_entries_data must attach a _meta envelope on the single return path."""

    @pytest.fixture
    def zim_ops(self, test_config, path_validator, openzim_mcp_cache, content_processor):
        from openzim_mcp.zim_operations import ZimOperations

        return ZimOperations(test_config, path_validator, openzim_mcp_cache, content_processor)

    def _zim_file(self, temp_dir):
        from pathlib import Path

        p = Path(temp_dir) / "test.zim"
        p.write_bytes(b"")
        return p

    def test_get_entries_data_attaches_meta(self, zim_ops, temp_dir, monkeypatch):
        """Batch entry fetch should attach _meta on the normal return path."""
        zim_file = self._zim_file(temp_dir)

        monkeypatch.setattr(
            zim_ops,
            "_get_zim_entry_from_archive",
            lambda *a, **kw: "article content",
        )

        from unittest.mock import MagicMock, patch

        with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
            mock_archive.return_value.__enter__.return_value = MagicMock()
            result = zim_ops.get_entries_data(
                entries=[{"zim_file_path": str(zim_file), "entry_path": "A/Foo"}]
            )

        assert "_meta" in result, "get_entries_data must attach _meta"
        assert result["_meta"]["tokens_est"] > 0
        assert result["_meta"]["chars"] > 0
        assert result["_meta"]["truncated"] is False

    def test_get_entries_data_attaches_meta_on_validation_failure(
        self, zim_ops, temp_dir
    ):
        """Validation-failure path (entries from bad paths) still returns _meta."""
        result = zim_ops.get_entries_data(
            entries=[{"zim_file_path": "/no/such/file.zim", "entry_path": "A/X"}]
        )
        assert "_meta" in result, "validation-failure path must attach _meta"


@pytest.mark.asyncio
async def test_get_zim_entries_tool_coerces_non_string_non_dict_entries(
    test_config: OpenZimMcpConfig,
):
    """Non-string non-dict entries (None, int, etc.) become empty pairs."""
    server = OpenZimMcpServer(test_config)
    server.rate_limiter.check_rate_limit = MagicMock()
    server.async_zim_operations.get_entries_data = AsyncMock(
        return_value={"results": [], "succeeded": 0, "failed": 0}
    )

    tool = server.mcp._tool_manager._tools["get_zim_entries"]
    fn = getattr(tool, "fn", None) or getattr(tool, "func", None)

    await fn(
        entries=[
            None,  # type: ignore[list-item]
            42,  # type: ignore[list-item]
            {"zim_file_path": "/ok", "entry_path": "ok"},
        ],
    )
    call = server.async_zim_operations.get_entries_data.await_args
    sent_entries = call.args[0]
    assert len(sent_entries) == 3
    assert sent_entries[0] == {"zim_file_path": "", "entry_path": ""}
    assert sent_entries[1] == {"zim_file_path": "", "entry_path": ""}
    assert sent_entries[2]["zim_file_path"] == "/ok"
