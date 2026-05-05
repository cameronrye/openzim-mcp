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

        # First call returns a structured hit; second raises
        def fake(path, q, lim, off):
            if "good" in path:
                return {
                    "query": q,
                    "total_results": 1,
                    "offset": 0,
                    "limit": lim,
                    "results": [
                        {"path": "A/Python", "title": "Python", "snippet": "..."}
                    ],
                    "pagination": {
                        "has_more": False,
                        "showing_start": 1,
                        "showing_end": 1,
                    },
                }
            raise RuntimeError("corrupt index")

        server.zim_operations.search_zim_file_data = MagicMock(side_effect=fake)

        result = server.zim_operations.search_all_data("python", limit_per_file=5)
        assert result["files_searched"] == 2
        assert result["files_with_hits"] == 1
        assert result["files_failed"] == 1
        assert any("error" in entry for entry in result["per_file"])

    def test_no_hits_anywhere(self, server: OpenZimMcpServer):
        """Test that result aggregates files_with_hits=0 when nothing matches."""
        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/a.zim", "name": "a.zim"}]
        )
        server.zim_operations.search_zim_file_data = MagicMock(
            return_value={
                "query": "xyzzy",
                "total_results": 0,
                "offset": 0,
                "limit": 5,
                "results": [],
                "pagination": {"has_more": False},
            }
        )

        result = server.zim_operations.search_all_data("xyzzy", limit_per_file=5)
        assert result["files_with_hits"] == 0
        assert result["per_file"][0]["has_hits"] is False

    def test_search_all_data_per_file_payload_is_dict(self, server: OpenZimMcpServer):
        """``search_all_data['per_file'][i]['result']`` is a dict, not a string.

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
                "total_results": 1,
                "offset": 0,
                "limit": 5,
                "results": [{"path": "C/Python", "title": "Python", "snippet": "..."}],
                "pagination": {
                    "has_more": False,
                    "showing_start": 1,
                    "showing_end": 1,
                },
            }
        )

        result = server.zim_operations.search_all_data("python", limit_per_file=5)
        assert isinstance(result, dict)
        per_file = result["per_file"][0]
        # The fix: ``result`` is a dict, not a stringified markdown blob.
        assert isinstance(per_file["result"], dict)
        assert per_file["result"]["query"] == "python"
        assert per_file["result"]["total_results"] == 1
        assert per_file["has_hits"] is True
