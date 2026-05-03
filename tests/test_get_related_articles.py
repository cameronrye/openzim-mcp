"""Tests for get_related_articles tool."""

import json
from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpValidationError
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

    def test_invalid_limit_raises(self, server: OpenZimMcpServer):
        """An out-of-range limit raises OpenZimMcpValidationError."""
        with pytest.raises(OpenZimMcpValidationError, match="limit must be"):
            server.zim_operations.get_related_articles(
                "/zim/test.zim", "C/Source", limit=0
            )


class TestResolveLinkToEntryPath:
    """Test ``_resolve_link_to_entry_path`` static helper.

    Trailing-slash handling matters: in domain-scheme ZIMs, "directory"
    entries are stored with a trailing slash (e.g. ``iep.utm.edu/a/``),
    so URL resolution must preserve it for paths to remain fetchable.
    """

    def test_relative_dir_href_preserves_trailing_slash(self):
        """``../a/`` against ``iep.utm.edu/aristotle/`` → ``iep.utm.edu/a/``."""
        from openzim_mcp.zim.structure import _StructureMixin

        resolved = _StructureMixin._resolve_link_to_entry_path(
            "../a/", "iep.utm.edu/aristotle/"
        )
        assert resolved == "iep.utm.edu/a/"

    def test_relative_file_href_no_trailing_slash(self):
        """``../a`` (no slash) against same source stays without slash."""
        from openzim_mcp.zim.structure import _StructureMixin

        resolved = _StructureMixin._resolve_link_to_entry_path(
            "../a", "iep.utm.edu/aristotle/"
        )
        assert resolved == "iep.utm.edu/a"

    def test_dir_href_with_fragment_preserves_slash(self):
        """``../a/#section`` resolves to ``iep.utm.edu/a/`` (slash kept)."""
        from openzim_mcp.zim.structure import _StructureMixin

        resolved = _StructureMixin._resolve_link_to_entry_path(
            "../a/#section", "iep.utm.edu/aristotle/"
        )
        assert resolved == "iep.utm.edu/a/"

    def test_dir_href_with_query_preserves_slash(self):
        """``../a/?ref=foo`` resolves to ``iep.utm.edu/a/`` (slash kept)."""
        from openzim_mcp.zim.structure import _StructureMixin

        resolved = _StructureMixin._resolve_link_to_entry_path(
            "../a/?ref=foo", "iep.utm.edu/aristotle/"
        )
        assert resolved == "iep.utm.edu/a/"

    def test_anchor_only_returns_none(self):
        """Anchor-only refs (``#section``) are non-navigable."""
        from openzim_mcp.zim.structure import _StructureMixin

        assert (
            _StructureMixin._resolve_link_to_entry_path(
                "#section", "iep.utm.edu/aristotle/"
            )
            is None
        )

    def test_external_url_returns_none(self):
        """Schemes like ``http://`` are external."""
        from openzim_mcp.zim.structure import _StructureMixin

        assert (
            _StructureMixin._resolve_link_to_entry_path(
                "https://example.com/", "iep.utm.edu/aristotle/"
            )
            is None
        )

    def test_legacy_namespace_no_trailing_slash(self):
        """``Linked_A`` against ``C/Source`` → ``C/Linked_A`` (no slash)."""
        from openzim_mcp.zim.structure import _StructureMixin

        resolved = _StructureMixin._resolve_link_to_entry_path("Linked_A", "C/Source")
        assert resolved == "C/Linked_A"

    @pytest.mark.parametrize("url", [".", "./", "/", "//"])
    def test_self_referential_navigation_returns_none(self, url: str):
        """Refs that resolve to "stay here" return None.

        ``.``, ``./``, ``/`` and ``//`` don't point at navigable targets:
        - ``./`` from ``"C/Source"`` would otherwise produce ``"C/"``,
          which is a namespace prefix, not a fetchable entry.
        - ``/`` is an absolute web path with no meaningful ZIM analogue.
        - ``//`` is protocol-relative.
        """
        from openzim_mcp.zim.structure import _StructureMixin

        for source in ("C/Source", "C/Sub/Article", "iep.utm.edu/aristotle/"):
            resolved = _StructureMixin._resolve_link_to_entry_path(url, source)
            assert resolved is None, (
                f"expected None for url={url!r} source={source!r}, " f"got {resolved!r}"
            )

    def test_parent_dir_to_archive_root_is_kept(self):
        """``../`` from ``iep.utm.edu/aristotle/`` resolves to the archive index.

        This is the legitimate "parent directory" case in domain-scheme
        archives where ``iep.utm.edu/`` IS a real entry (the index page).
        Unlike pure-navigation tokens, ``..``/``../`` from a path with
        depth resolves to a different (parent) location and may map to
        a real entry.
        """
        from openzim_mcp.zim.structure import _StructureMixin

        # Two-level descent — parent is the domain root, a real entry.
        resolved = _StructureMixin._resolve_link_to_entry_path(
            "../", "iep.utm.edu/aristotle/"
        )
        assert resolved == "iep.utm.edu/"
        # Without trailing slash too.
        resolved = _StructureMixin._resolve_link_to_entry_path(
            "..", "iep.utm.edu/aristotle/"
        )
        assert resolved == "iep.utm.edu"
