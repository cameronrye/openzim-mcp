"""Tests for search_all tool."""

import json
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

        # First call returns a hit; second raises
        def fake_search(path, q, lim, off):
            if "good" in path:
                return "Found 1 matches for 'python':\n- /A/Python"
            raise RuntimeError("corrupt index")

        server.zim_operations.search_zim_file = MagicMock(side_effect=fake_search)

        result_json = server.zim_operations.search_all("python", limit_per_file=5)
        result = json.loads(result_json)
        assert result["files_searched"] == 2
        assert result["files_with_hits"] == 1
        assert result["files_failed"] == 1
        assert any("error" in entry for entry in result["per_file"])

    def test_no_hits_anywhere(self, server: OpenZimMcpServer):
        """Test that result aggregates files_with_hits=0 when nothing matches."""
        server.zim_operations.list_zim_files_data = MagicMock(
            return_value=[{"path": "/zim/a.zim", "name": "a.zim"}]
        )
        server.zim_operations.search_zim_file = MagicMock(
            return_value='No search results found for "xyzzy"'
        )

        result_json = server.zim_operations.search_all("xyzzy", limit_per_file=5)
        result = json.loads(result_json)
        assert result["files_with_hits"] == 0
        assert result["per_file"][0]["has_hits"] is False
