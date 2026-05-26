"""Migration conformance — every v1.x / v2-beta tool name maps to a Phase F
tool, the CHANGELOG documents every rename, and the default-behavior changes
called out in the migration story actually hold in the rc1 code.

This is a static-rename-map test (not a runtime tool-invocation suite); a
real-archive conformance test belongs in Stage E (Task E4). The static
guarantee here is:
  - the v1.x legacy surface is fully accounted for (every name maps),
  - the v2.0 surface is the 8 Phase F tools (nothing else),
  - the CHANGELOG documents every legacy name (no silent drops),
  - default-behavior changes in the migration story hold in code.
"""

from __future__ import annotations

import pathlib
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

REPO = pathlib.Path(__file__).parent.parent
_ALLOWED_DIR = tempfile.mkdtemp(prefix="openzim_mcp_migration_")

# Every legacy tool name that existed on the v1.x / v2-beta surface, paired
# with its Phase F destination tool. Inbound-link lookup never existed in v1
# (only proposed for v2.5 #16) — recorded here only as a CHANGELOG-coverage
# anchor so the "not available at v2.0" note doesn't silently disappear.
LEGACY_TO_PHASE_F = {
    "list_zim_files": "zim_health",
    "get_server_health": "zim_health",
    "get_server_configuration": "zim_health",
    "get_zim_metadata": "zim_metadata",
    "list_namespaces": "zim_metadata",
    "get_main_page": "zim_get",
    "search_zim_file": "zim_search",
    "search_all": "zim_search",
    "search_with_filters": "zim_search",
    "find_entry_by_title": "zim_search",
    "get_search_suggestions": "zim_search",
    "get_zim_entry": "zim_get",
    "get_zim_entries": "zim_get",
    "get_binary_entry": "zim_get",
    "get_entry_summary": "zim_get",
    "get_table_of_contents": "zim_get",
    "get_article_structure": "zim_get",
    "get_section": "zim_get_section",
    "browse_namespace": "zim_browse",
    "walk_namespace": "zim_browse",
    "extract_article_links": "zim_links",
    "get_related_articles": "zim_links",
}

PHASE_F_TOOLS = {
    "zim_query",
    "zim_search",
    "zim_get",
    "zim_get_section",
    "zim_browse",
    "zim_metadata",
    "zim_links",
    "zim_health",
}


@pytest.fixture(scope="module")
def phase_f_advanced_server() -> OpenZimMcpServer:
    cfg = OpenZimMcpConfig(allowed_directories=[_ALLOWED_DIR], tool_mode="advanced")
    return OpenZimMcpServer(cfg)


def test_v1_legacy_names_map_to_phase_f_tools(
    phase_f_advanced_server: OpenZimMcpServer,
) -> None:
    """Every legacy tool name maps to one of the 8 registered Phase F tools."""
    registered = set(phase_f_advanced_server.mcp._tool_manager._tools)
    assert registered == PHASE_F_TOOLS, (
        f"Phase F advanced surface mismatch. Expected {PHASE_F_TOOLS}, "
        f"got {registered}."
    )
    for legacy, target in LEGACY_TO_PHASE_F.items():
        assert target in registered, (
            f"Migration row {legacy!r} -> {target!r} but {target!r} is not "
            f"registered in advanced mode."
        )


@pytest.mark.parametrize("legacy_name", sorted(LEGACY_TO_PHASE_F))
def test_changelog_documents_every_legacy_name(legacy_name: str) -> None:
    """The rc1 CHANGELOG entry must reference every legacy tool name so a
    migrating user can grep for their current call and find the mapping.
    """
    changelog = (REPO / "CHANGELOG.md").read_text()
    # Find the rc1 section bounds.
    rc1_start = changelog.find("## [2.0.0rc1]")
    assert rc1_start >= 0, "v2.0.0rc1 section not found in CHANGELOG.md"
    rc0_start = changelog.find("## [2.0.0rc0]", rc1_start)
    rc1_section = changelog[rc1_start:rc0_start]
    assert legacy_name in rc1_section, (
        f"Legacy tool {legacy_name!r} not referenced in the rc1 CHANGELOG "
        f"section. The migration table must cover every legacy name."
    )


def test_simple_mode_registers_only_zim_query() -> None:
    """The migration story leaves `tool_mode='simple'` unchanged: the only
    registered tool is zim_query.
    """
    cfg = OpenZimMcpConfig(allowed_directories=[_ALLOWED_DIR], tool_mode="simple")
    srv = OpenZimMcpServer(cfg)
    assert set(srv.mcp._tool_manager._tools) == {"zim_query"}


def _patch_async_ops(
    monkeypatch: pytest.MonkeyPatch, **method_returns: object
) -> MagicMock:
    mock = MagicMock()
    for name, value in method_returns.items():
        setattr(mock, name, AsyncMock(return_value=value))
    monkeypatch.setattr(
        "openzim_mcp.async_operations.AsyncZimOperations",
        lambda _zim_ops: mock,
    )
    return mock


@pytest.mark.asyncio
async def test_zim_get_compact_default_preserves_legacy_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """zim_get(entry_path=...) without compact= must dispatch with
    compact=False — preserves legacy get_zim_entry raw-markdown shape per
    spec §Default behavior changes.
    """
    from openzim_mcp.tools.zim_get import register as register_zim_get

    server = MagicMock()
    tools: dict[str, object] = {}

    def _tool(*, description: str = "") -> object:
        def decorate(fn: object) -> object:
            tools[fn.__name__] = fn  # type: ignore[attr-defined]
            return fn

        return decorate

    server.mcp.tool = _tool
    ops = _patch_async_ops(monkeypatch, get_zim_entry_data={"content": "body"})
    register_zim_get(server)
    await tools["zim_get"](zim_file_path="/x.zim", entry_path="A/Cat")  # type: ignore[operator]
    _, kwargs = ops.get_zim_entry_data.call_args
    assert kwargs["compact"] is False, (
        "zim_get(entry_path=...) without compact= must default to compact=False "
        "to preserve legacy get_zim_entry behavior — see spec §Default "
        "behavior changes."
    )


def test_zim_get_section_compact_signature_default_is_true(
    phase_f_advanced_server: OpenZimMcpServer,
) -> None:
    """zim_get_section's `compact` parameter must default to True at the
    function signature — the v2.0 surface contract called out in the
    migration story as a silent break. (Whether the data layer threads the
    flag through to a compactor is a separate behavior contract; the
    migration conformance test pins only the surface default.)
    """
    import inspect

    tool = phase_f_advanced_server.mcp._tool_manager._tools["zim_get_section"]
    sig = inspect.signature(tool.fn)
    compact_param = sig.parameters.get("compact")
    assert compact_param is not None, "zim_get_section must accept `compact`"
    assert compact_param.default is True, (
        f"zim_get_section.compact default must be True (v2.0 migration "
        f"contract); got {compact_param.default!r}"
    )


def test_zim_get_compact_signature_default_is_false(
    phase_f_advanced_server: OpenZimMcpServer,
) -> None:
    """zim_get's `compact` parameter must default to False at the signature
    — preserves the legacy get_zim_entry raw-markdown contract per the
    migration story.
    """
    import inspect

    tool = phase_f_advanced_server.mcp._tool_manager._tools["zim_get"]
    sig = inspect.signature(tool.fn)
    compact_param = sig.parameters.get("compact")
    assert compact_param is not None, "zim_get must accept `compact`"
    assert compact_param.default is False, (
        f"zim_get.compact default must be False (preserves legacy "
        f"get_zim_entry raw-markdown shape); got {compact_param.default!r}"
    )


def test_zim_query_compact_signature_default_is_true(
    phase_f_advanced_server: OpenZimMcpServer,
) -> None:
    """zim_query's `compact` parameter must default to True at the signature
    — unchanged from b13.
    """
    import inspect

    tool = phase_f_advanced_server.mcp._tool_manager._tools["zim_query"]
    sig = inspect.signature(tool.fn)
    compact_param = sig.parameters.get("compact")
    assert compact_param is not None, "zim_query must accept `compact`"
    assert (
        compact_param.default is True
    ), f"zim_query.compact default must be True; got {compact_param.default!r}"
