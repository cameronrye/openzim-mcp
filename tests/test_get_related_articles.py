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
        """Outbound delegates to extract_article_links, resolves URLs, dedupes.

        ``extract_article_links`` returns links with ``url`` keys carrying
        href values relative to the source entry. ``get_related_articles``
        resolves each href against the source path and dedupes the result.
        """
        server.zim_operations.extract_article_links = MagicMock(
            return_value=json.dumps(
                {
                    "internal_links": [
                        # Bare relative href — resolves to "C/Linked_A".
                        {"url": "Linked_A", "text": "Linked A"},
                        {"url": "Linked_B", "text": "Linked B"},
                        {"url": "Linked_A", "text": "Linked A"},  # dup
                        # Anchor-only — should be ignored.
                        {"url": "#section", "text": "anchor"},
                    ]
                }
            )
        )

        result_json = server.zim_operations.get_related_articles(
            "/zim/test.zim", "C/Source", limit=10
        )
        result = json.loads(result_json)
        assert len(result["outbound_results"]) == 2  # deduped, anchor dropped
        assert {r["path"] for r in result["outbound_results"]} == {
            "C/Linked_A",
            "C/Linked_B",
        }

    def test_invalid_limit_returns_error(self, server: OpenZimMcpServer):
        """An out-of-range limit returns a parameter validation error."""
        result = server.zim_operations.get_related_articles(
            "/zim/test.zim", "C/Source", limit=0
        )
        assert "Parameter Validation Error" in result
