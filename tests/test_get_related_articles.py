"""Tests for get_related_articles tool."""

import json
from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer


class TestGetRelatedArticles:
    """Test get_related_articles operation."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance."""
        return OpenZimMcpServer(test_config)

    def test_outbound_uses_extract_article_links(self, server: OpenZimMcpServer):
        """Outbound delegates to extract_article_links and dedupes."""
        # extract_article_links returns a JSON string like:
        #   {"internal_links": [{"path": "C/A", "title": "A"}, ...]}
        server.zim_operations.extract_article_links = MagicMock(
            return_value=json.dumps(
                {
                    "internal_links": [
                        {"path": "C/Linked_A", "title": "Linked A"},
                        {"path": "C/Linked_B", "title": "Linked B"},
                        {"path": "C/Linked_A", "title": "Linked A"},  # dup
                    ]
                }
            )
        )

        result_json = server.zim_operations.get_related_articles(
            "/zim/test.zim", "C/Source", limit=10, direction="outbound"
        )
        result = json.loads(result_json)
        assert result["direction"] == "outbound"
        assert len(result["outbound_results"]) == 2  # deduped
        assert {r["path"] for r in result["outbound_results"]} == {
            "C/Linked_A",
            "C/Linked_B",
        }

    def test_invalid_direction_returns_error(self, server: OpenZimMcpServer):
        """An unknown direction returns a parameter validation error."""
        result = server.zim_operations.get_related_articles(
            "/zim/test.zim", "C/Source", limit=10, direction="sideways"
        )
        assert "Parameter Validation Error" in result

    def test_inbound_bounded_scan_returns_cursor(
        self, server: OpenZimMcpServer, monkeypatch
    ):
        """Inbound scan respects scan_cap and returns a next_cursor."""
        # Build a mock archive whose entries each "link" to C/Source.
        mock_archive = MagicMock()
        mock_archive.entry_count = 100
        mock_archive.has_new_namespace_scheme = True

        def get_entry_by_id(entry_id):
            entry = MagicMock()
            entry.path = f"C/Article_{entry_id}"
            entry.title = f"Article {entry_id}"
            return entry

        mock_archive._get_entry_by_id.side_effect = get_entry_by_id

        # extract_article_links returns C/Source as one of the links from
        # every article — so every scanned entry counts as inbound.
        server.zim_operations.extract_article_links = MagicMock(
            return_value=json.dumps(
                {"internal_links": [{"path": "C/Source", "title": "Source"}]}
            )
        )

        monkeypatch.setattr(
            "openzim_mcp.zim_operations.zim_archive",
            lambda *a, **kw: _ctx(mock_archive),
        )
        server.zim_operations.path_validator = MagicMock()
        server.zim_operations.path_validator.validate_path.return_value = (
            "/zim/test.zim"
        )
        server.zim_operations.path_validator.validate_zim_file.return_value = (
            "/zim/test.zim"
        )

        # scan_cap=10 so we hit the cap before exhausting 100 entries.
        result_json = server.zim_operations.get_related_articles(
            "/zim/test.zim",
            "C/Source",
            limit=50,
            direction="inbound",
            inbound_scan_cap=10,
        )
        result = json.loads(result_json)
        assert result["direction"] == "inbound"
        assert result["inbound_done"] is False
        assert result["inbound_next_cursor"] is not None
        assert result["inbound_scanned"] == 10


def _ctx(value):
    """Build a context manager that yields the given value."""

    class _C:
        def __enter__(self):
            return value

        def __exit__(self, *a):
            return False

    return _C()
