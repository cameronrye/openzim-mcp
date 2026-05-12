"""Contract-shape regression: every list-returning tool emits the five contract keys.

Phase B (#3) standardizes pagination across all list-returning tools. This
file is the single source of truth for "did we keep the contract?" Each
test calls a real tool against the bundled fixtures and asserts the shape.

Phase C note
------------
``get_section`` and ``synthesize`` are NOT list-paginated tools and are
therefore exempt from ``_assert_contract``.  They still carry ``_meta`` —
see ``TestPhaseCMetaEnvelope`` below.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openzim_mcp.config import OpenZimMcpConfig, SynthesizeConfig
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.synthesize import synthesize_query
from openzim_mcp.zim_operations import ZimOperations, zim_archive

CONTRACT_KEYS = ("results", "next_cursor", "total", "done", "page_info", "_meta")
PAGE_INFO_KEYS = ("offset", "limit", "returned_count")


def _assert_contract(payload: dict) -> None:
    """Assert payload carries the five contract keys + _meta + page_info subkeys."""
    for key in CONTRACT_KEYS:
        assert key in payload, f"contract key missing: {key}"
    assert isinstance(
        payload["results"], list
    ), f"results must be list, got {type(payload['results'])}"
    assert isinstance(payload["done"], bool)
    assert payload["next_cursor"] is None or isinstance(payload["next_cursor"], str)
    assert payload["total"] is None or isinstance(payload["total"], int)
    pi = payload["page_info"]
    for key in PAGE_INFO_KEYS:
        assert key in pi, f"page_info missing key: {key}"
    assert pi["returned_count"] == len(
        payload["results"]
    ), f"page_info.returned_count={pi['returned_count']} != len(results)={len(payload['results'])}"
    # done <-> next_cursor co-vary (redundant by design)
    if payload["done"]:
        assert payload["next_cursor"] is None, "done=True must imply next_cursor=None"
    else:
        assert (
            payload["next_cursor"] is not None
        ), "done=False must imply next_cursor!=None"


@pytest.fixture
def server(test_config_with_zim_data: OpenZimMcpConfig) -> OpenZimMcpServer:
    return OpenZimMcpServer(test_config_with_zim_data)


class TestContractShape:
    @pytest.mark.asyncio
    async def test_search_zim_file_contract(self, server, basic_test_zim_files):
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "search_zim_file",
            {"zim_file_path": str(zim_path), "query": "evolution", "limit": 5},
            convert_result=True,
        )
        _, structured = result
        payload = structured["result"] if "result" in structured else structured
        if payload.get("error") is True:
            pytest.skip(
                f"search_zim_file returned error envelope: {payload.get('details') or payload.get('operation')}"
            )
        _assert_contract(payload)

    @pytest.mark.asyncio
    async def test_search_all_contract_top_level(self, server):
        result = await server.mcp._tool_manager.call_tool(
            "search_all",
            {"query": "evolution"},
            convert_result=True,
        )
        _, structured = result
        payload = structured["result"] if "result" in structured else structured
        if payload.get("error") is True:
            pytest.skip(
                f"search_all returned error envelope: {payload.get('details') or payload.get('operation')}"
            )
        _assert_contract(payload)
        # search_all top-level is always done=True
        assert payload["done"] is True
        # And each per-archive result inside also conforms.
        for entry in payload["results"]:
            # H14: per-file row carries ``error`` as a sibling of ``result``;
            # ``result`` is None on failure, a SearchResponse on success.
            if entry.get("error") is True:
                continue  # inner ZIM lacked Xapian index — skip that entry
            inner = entry["result"]
            _assert_contract(inner)

    @pytest.mark.asyncio
    async def test_find_entry_by_title_contract(self, server, basic_test_zim_files):
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "find_entry_by_title",
            {"zim_file_path": str(zim_path), "title": "anything"},
            convert_result=True,
        )
        _, structured = result
        payload = structured["result"] if "result" in structured else structured
        _assert_contract(payload)
        assert payload["done"] is True  # non-paginated tool

    @pytest.mark.asyncio
    async def test_get_search_suggestions_contract(self, server, basic_test_zim_files):
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "get_search_suggestions",
            {"zim_file_path": str(zim_path), "partial_query": "ev"},
            convert_result=True,
        )
        _, structured = result
        payload = structured["result"] if "result" in structured else structured
        if payload.get("error") is True:
            pytest.skip(
                f"get_search_suggestions returned error envelope: {payload.get('details') or payload.get('operation')}"
            )
        _assert_contract(payload)
        assert payload["done"] is True

    @pytest.mark.asyncio
    async def test_browse_namespace_contract(self, server, basic_test_zim_files):
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "browse_namespace",
            {"zim_file_path": str(zim_path), "namespace": "C", "limit": 5},
            convert_result=True,
        )
        _, structured = result
        payload = structured["result"] if "result" in structured else structured
        _assert_contract(payload)

    @pytest.mark.asyncio
    async def test_walk_namespace_contract(self, server, basic_test_zim_files):
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "walk_namespace",
            {"zim_file_path": str(zim_path), "namespace": "C", "limit": 50},
            convert_result=True,
        )
        _, structured = result
        payload = structured["result"] if "result" in structured else structured
        _assert_contract(payload)
        assert payload["total"] is None  # walk doesn't know total

    @pytest.mark.asyncio
    async def test_extract_article_links_contract(self, server, basic_test_zim_files):
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        # Find any article and extract links from it.
        find = await server.mcp._tool_manager.call_tool(
            "find_entry_by_title",
            {"zim_file_path": str(zim_path), "title": "Berlin"},
            convert_result=True,
        )
        _, find_structured = find
        find_payload = (
            find_structured["result"]
            if "result" in find_structured
            else find_structured
        )
        if not find_payload["results"]:
            pytest.skip("No fixture article to test against")
        entry_path = find_payload["results"][0]["path"]
        result = await server.mcp._tool_manager.call_tool(
            "extract_article_links",
            {
                "zim_file_path": str(zim_path),
                "entry_path": entry_path,
                "kind": "internal",
            },
            convert_result=True,
        )
        _, structured = result
        payload = structured["result"] if "result" in structured else structured
        _assert_contract(payload)
        assert "category_totals" in payload
        for k in ("internal", "external", "media"):
            assert k in payload["category_totals"]

    @pytest.mark.asyncio
    async def test_list_zim_files_contract(self, server):
        result = await server.mcp._tool_manager.call_tool(
            "list_zim_files",
            {},
            convert_result=True,
        )
        _, structured = result
        payload = structured["result"] if "result" in structured else structured
        _assert_contract(payload)
        assert payload["done"] is True

    @pytest.mark.asyncio
    async def test_get_related_articles_contract(self, server, basic_test_zim_files):
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        find = await server.mcp._tool_manager.call_tool(
            "find_entry_by_title",
            {"zim_file_path": str(zim_path), "title": "Berlin"},
            convert_result=True,
        )
        _, find_structured = find
        find_payload = (
            find_structured["result"]
            if "result" in find_structured
            else find_structured
        )
        if not find_payload["results"]:
            pytest.skip("No fixture article to test against")
        entry_path = find_payload["results"][0]["path"]
        result = await server.mcp._tool_manager.call_tool(
            "get_related_articles",
            {"zim_file_path": str(zim_path), "entry_path": entry_path},
            convert_result=True,
        )
        _, structured = result
        payload = structured["result"] if "result" in structured else structured
        _assert_contract(payload)
        assert payload["done"] is True

    @pytest.mark.asyncio
    async def test_get_zim_entries_contract(self, server, basic_test_zim_files):
        zim_path = basic_test_zim_files.get("nons") or basic_test_zim_files.get(
            "withns"
        )
        if zim_path is None:
            pytest.skip("ZIM testing-suite small.zim not available")
        result = await server.mcp._tool_manager.call_tool(
            "get_zim_entries",
            {"zim_file_path": str(zim_path), "entries": ["C/Berlin", "C/Paris"]},
            convert_result=True,
        )
        _, structured = result
        payload = structured["result"] if "result" in structured else structured
        _assert_contract(payload)
        assert payload["done"] is True


# ---------------------------------------------------------------------------
# Phase C: non-paginated tools are exempt from _assert_contract but must
# still carry _meta.  Tests use the heading-rich v2_phase_c_zim fixture.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _phase_c_zim_ops(v2_phase_c_zim: Path) -> ZimOperations:
    from tests.conftest_v2_fixtures import make_zim_ops

    return make_zim_ops(str(v2_phase_c_zim.parent))


class TestPhaseCMetaEnvelope:
    """get_section and synthesize are exempt from the list-pagination contract
    but must still carry a _meta dict."""

    def test_get_section_response_carries_meta_envelope(
        self, _phase_c_zim_ops: ZimOperations, v2_phase_c_zim: Path
    ) -> None:
        response = _phase_c_zim_ops.get_section_data(
            str(v2_phase_c_zim), "A/Berlin", section_id="geography"
        )
        assert "_meta" in response, "get_section response missing _meta"
        assert isinstance(response["_meta"], dict)

    def test_synthesize_response_carries_meta_envelope(
        self, _phase_c_zim_ops: ZimOperations, v2_phase_c_zim: Path
    ) -> None:
        with zim_archive(v2_phase_c_zim) as archive:
            response = synthesize_query(
                "berlin geography",
                archives=[(archive, v2_phase_c_zim)],
                search_handler=_phase_c_zim_ops,
                cache=_phase_c_zim_ops.cache,
                content_processor=_phase_c_zim_ops.content_processor,
                config=SynthesizeConfig(),
            )
        assert "_meta" in response, "synthesize response missing _meta"
        assert isinstance(response["_meta"], dict)
