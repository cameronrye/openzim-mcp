"""Tests for search_all tool."""

from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpValidationError
from openzim_mcp.server import OpenZimMcpServer


class TestSearchAll:
    """Test search_all operation."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_empty_query_raises(self, server: OpenZimMcpServer):
        """Test that empty/whitespace query raises OpenZimMcpValidationError."""
        with pytest.raises(OpenZimMcpValidationError):
            server.zim_operations.search_all("", limit_per_file=5)
        with pytest.raises(OpenZimMcpValidationError):
            server.zim_operations.search_all("   \t  ", limit_per_file=5)

    def test_limit_per_file_validation_low(self, server: OpenZimMcpServer):
        """Test that limit_per_file < 1 raises OpenZimMcpValidationError."""
        with pytest.raises(OpenZimMcpValidationError, match="limit_per_file"):
            server.zim_operations.search_all("python", limit_per_file=0)

    def test_limit_per_file_validation_high(self, server: OpenZimMcpServer):
        """Test that limit_per_file > 50 raises OpenZimMcpValidationError."""
        with pytest.raises(OpenZimMcpValidationError, match="limit_per_file"):
            server.zim_operations.search_all("python", limit_per_file=51)

    def test_per_file_aggregation_mixed(self, server: OpenZimMcpServer):
        """Test that files failing to search are skipped without aborting the rest."""
        # Mock the file listing
        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[
                {"path": "/zim/good.zim", "name": "good.zim"},
                {"path": "/zim/bad.zim", "name": "bad.zim"},
            ]
        )

        # First call returns a Phase B SearchResponse; second raises
        def fake(path, q, lim, off):
            if "good" in path:
                return {
                    "query": q,
                    "results": [
                        {"path": "A/Python", "title": "Python", "snippet": "..."}
                    ],
                    "next_cursor": None,
                    "total": 1,
                    "done": True,
                    "page_info": {"offset": 0, "limit": lim, "returned_count": 1},
                }
            raise RuntimeError("corrupt index")

        server.zim_operations.search_zim_file_data = MagicMock(side_effect=fake)

        result = server.zim_operations.search_all_data("python", limit_per_file=5)
        assert result["files_searched"] == 2
        assert result["files_with_hits"] == 1
        assert result["files_failed"] == 1
        # H14: failure entries carry a sibling ``error: True`` flag plus
        # ``error_message`` / ``error_operation``. ``result`` is None for
        # failures so the shape of ``result`` stays single-typed (no more
        # Union with ToolErrorPayload).
        assert any(entry.get("error") is True for entry in result["results"])
        for entry in result["results"]:
            if entry.get("error"):
                assert entry["result"] is None
                assert "error_message" in entry
                assert entry.get("error_operation") == "search_zim_file"
        # Phase B contract-shape assertions
        assert result["done"] is True
        assert result["next_cursor"] is None
        assert result["total"] == result["files_searched"]
        assert result["page_info"] == {
            "offset": 0,
            "limit": result["files_searched"],
            "returned_count": len(result["results"]),
        }

    def test_no_hits_anywhere(self, server: OpenZimMcpServer):
        """Test that result aggregates files_with_hits=0 when nothing matches."""
        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/a.zim", "name": "a.zim"}]
        )
        server.zim_operations.search_zim_file_data = MagicMock(
            return_value={
                "query": "xyzzy",
                "results": [],
                "next_cursor": None,
                "total": 0,
                "done": True,
                "page_info": {"offset": 0, "limit": 5, "returned_count": 0},
            }
        )

        result = server.zim_operations.search_all_data("xyzzy", limit_per_file=5)
        assert result["files_with_hits"] == 0
        assert result["results"][0]["has_hits"] is False
        # Phase B contract-shape assertions
        assert result["done"] is True
        assert result["next_cursor"] is None
        assert result["total"] == result["files_searched"]
        assert result["page_info"] == {
            "offset": 0,
            "limit": result["files_searched"],
            "returned_count": len(result["results"]),
        }

    def test_search_all_data_per_file_payload_is_dict(self, server: OpenZimMcpServer):
        """``search_all_data['results'][i]['result']`` is a dict, not a string.

        Catches the triple-encoding regression: previously per_file.result
        was a markdown blob (string) and the outer json.dumps escaped its
        quotes. The fix routes per-file results through
        ``search_zim_file_data`` so the embedded payload stays structured.
        """
        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/good.zim", "name": "good.zim"}]
        )
        server.zim_operations.search_zim_file_data = MagicMock(
            return_value={
                "query": "python",
                "results": [{"path": "C/Python", "title": "Python", "snippet": "..."}],
                "next_cursor": None,
                "total": 1,
                "done": True,
                "page_info": {"offset": 0, "limit": 5, "returned_count": 1},
            }
        )

        result = server.zim_operations.search_all_data("python", limit_per_file=5)
        assert isinstance(result, dict)
        per_file = result["results"][0]
        # The fix: ``result`` is a dict, not a stringified markdown blob.
        assert isinstance(per_file["result"], dict)
        assert per_file["result"]["query"] == "python"
        # Phase B: per-file SearchResponse uses ``total`` (not legacy
        # ``total_results``).
        assert per_file["result"]["total"] == 1
        assert per_file["has_hits"] is True
        # Phase B contract-shape assertions on the top level
        assert result["done"] is True
        assert result["next_cursor"] is None
        assert result["total"] == result["files_searched"]
        assert result["page_info"] == {
            "offset": 0,
            "limit": result["files_searched"],
            "returned_count": len(result["results"]),
        }
