"""Tests for Phase F combined async wrappers (Task D2).

Verifies that the two combined wrappers in ``AsyncZimOperations``
assemble their composite responses from the right single-purpose
data calls without behavior drift from the legacy single-purpose
tools.

The wrappers are pure composition + reshape: source the legacy
``_data`` methods (or the existing per-tool ``_build_*`` helpers for
the server-state half) and stitch them into the new combined
TypedDict shape. Tests use ``unittest.mock`` to mock the underlying
data calls; we never touch a real ZIM archive here — the data-source
layer is exercised by the existing ``test_zim_operations`` suite.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.async_operations import AsyncZimOperations


@pytest.fixture
def mock_zim_ops() -> MagicMock:
    """A ``ZimOperations`` shaped well enough for the wrappers' calls."""
    ops = MagicMock()
    ops.get_zim_metadata_data.return_value = {
        "entry_count": 10,
        "all_entry_count": 12,
        "article_count": 8,
        "media_count": 2,
        "metadata_entries": {"Name": "wikipedia_en", "Title": "Wikipedia"},
        "_meta": {},
    }
    ops.list_namespaces_data.return_value = {
        "total_entries": 12,
        "sampled_entries": 12,
        "has_new_namespace_scheme": True,
        "is_total_authoritative": True,
        "discovery_method": "full",
        "namespaces": {
            "A": {
                "total": 8,
                "is_authoritative": True,
                "description": "articles",
            },
            "M": {
                "total": 2,
                "is_authoritative": True,
                "description": "metadata",
            },
        },
    }
    ops.list_zim_files_data.return_value = [
        {
            "name": "wiki.zim",
            "path": "/data/wiki.zim",
            "directory": "/data",
            "size": "1 GB",
            "size_bytes": 1_000_000_000,
            "modified": "2026-01-01T00:00:00Z",
        }
    ]
    return ops


@pytest.fixture
def async_ops(mock_zim_ops: MagicMock) -> AsyncZimOperations:
    return AsyncZimOperations(mock_zim_ops)


# ---------------------------------------------------------------------------
# get_archive_metadata_data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_metadata_combines_metadata_and_namespaces(
    async_ops: AsyncZimOperations, mock_zim_ops: MagicMock
) -> None:
    """Combined response carries the metadata dict + list-form namespaces."""
    result = await async_ops.get_archive_metadata_data("/data/wiki.zim")

    assert result["metadata"] == {"Name": "wikipedia_en", "Title": "Wikipedia"}
    # Namespaces dict → list with `letter` field added.
    letters = sorted(n["letter"] for n in result["namespaces"])
    assert letters == ["A", "M"]
    # Per-namespace fields from NamespaceSummary preserved verbatim.
    a_ns = next(n for n in result["namespaces"] if n["letter"] == "A")
    assert a_ns["total"] == 8
    assert a_ns["is_authoritative"] is True
    assert a_ns["description"] == "articles"
    assert "_meta" in result


@pytest.mark.asyncio
async def test_archive_metadata_handles_missing_metadata_entries(
    async_ops: AsyncZimOperations, mock_zim_ops: MagicMock
) -> None:
    """Legacy responses may omit metadata_entries; combined wrapper returns
    an empty dict in that case rather than crashing."""
    mock_zim_ops.get_zim_metadata_data.return_value = {
        "entry_count": 0,
        "all_entry_count": 0,
        "article_count": 0,
        "media_count": 0,
        "_meta": {},
    }
    result = await async_ops.get_archive_metadata_data("/data/empty.zim")
    assert result["metadata"] == {}
    assert result["namespaces"][0]["letter"] == "A"


@pytest.mark.asyncio
async def test_archive_metadata_coerces_metadata_values_to_string(
    async_ops: AsyncZimOperations, mock_zim_ops: MagicMock
) -> None:
    """Legacy dict[str, Any] tightens to dict[str, str] in the combined
    shape — non-string values stringify."""
    mock_zim_ops.get_zim_metadata_data.return_value = {
        "metadata_entries": {"Date": 20260101, "ArticleCount": 8},
        "_meta": {},
    }
    result = await async_ops.get_archive_metadata_data("/data/typed.zim")
    assert result["metadata"]["Date"] == "20260101"
    assert result["metadata"]["ArticleCount"] == "8"


@pytest.mark.asyncio
async def test_archive_metadata_calls_both_sources(
    async_ops: AsyncZimOperations, mock_zim_ops: MagicMock
) -> None:
    """Pure-composition guarantee: each underlying _data call fires once
    per combined invocation."""
    await async_ops.get_archive_metadata_data("/data/wiki.zim")
    mock_zim_ops.get_zim_metadata_data.assert_called_once_with("/data/wiki.zim")
    mock_zim_ops.list_namespaces_data.assert_called_once_with("/data/wiki.zim")


# ---------------------------------------------------------------------------
# get_health_data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_data_combines_all_three_sources(
    async_ops: AsyncZimOperations, mock_zim_ops: MagicMock
) -> None:
    """Combined response carries health + configuration + loaded_archives."""
    fake_health = {"timestamp": "now", "status": "healthy", "server_name": "test"}
    fake_config = {
        "configuration": {"server_name": "test", "allowed_directories": []},
        "diagnostics": {
            "validation_status": "ok",
            "warnings": [],
            "recommendations": [],
        },
        "timestamp": "now",
    }
    server = MagicMock()
    with (
        patch(
            "openzim_mcp.server_state._build_health_report",
            return_value=fake_health,
        ),
        patch(
            "openzim_mcp.server_state._build_configuration_report",
            return_value=fake_config,
        ),
    ):
        result = await async_ops.get_health_data(server)

    assert result["health"] == fake_health
    assert result["configuration"] == fake_config
    assert result["loaded_archives"][0]["name"] == "wiki.zim"
    assert "_meta" in result


@pytest.mark.asyncio
async def test_health_data_calls_list_zim_files_with_no_filter(
    async_ops: AsyncZimOperations, mock_zim_ops: MagicMock
) -> None:
    """The loaded_archives field uses an unfiltered enumeration so the
    health surface reports every archive the server can see, not a
    filtered subset."""
    server = MagicMock()
    with (
        patch("openzim_mcp.server_state._build_health_report", return_value={}),
        patch(
            "openzim_mcp.server_state._build_configuration_report",
            return_value={},
        ),
    ):
        await async_ops.get_health_data(server)
    mock_zim_ops.list_zim_files_data.assert_called_once_with(None)
