"""Tests for get_related_articles tool."""

import json
from pathlib import Path
from typing import Callable, List
from unittest.mock import MagicMock

import pytest

from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpValidationError
from openzim_mcp.server import OpenZimMcpServer


def _patch_zim_archive(
    monkeypatch: pytest.MonkeyPatch,
    mock_archive: MagicMock,
    on_open: Callable[[object], None] | None = None,
) -> None:
    """Patch ``openzim_mcp.zim_operations.zim_archive`` to return ``mock_archive``.

    The hook ``on_open`` (when provided) is called with each path the
    production code asks to open — useful for asserting the archive is
    opened with the expected (validated) path, not the raw caller input.
    """

    class _Ctx:
        def __enter__(self) -> MagicMock:
            return mock_archive

        def __exit__(self, *a: object) -> bool:
            return False

    def _factory(path: object, *_a: object, **_kw: object) -> _Ctx:
        if on_open is not None:
            on_open(path)
        return _Ctx()

    monkeypatch.setattr("openzim_mcp.zim_operations.zim_archive", _factory)


class TestGetRelatedArticles:
    """Test get_related_articles operation."""

    @pytest.fixture
    def server(self, test_config: OpenZimMcpConfig) -> OpenZimMcpServer:
        """Create a test server instance with a stub path validator.

        The stub passes the input through unchanged so unit tests can
        focus on outbound-link logic without registering paths in
        ``allowed_directories``. Tests that need to verify the validated
        path actually flows into the archive open replace this stub.
        """
        srv = OpenZimMcpServer(test_config)
        srv.zim_operations.path_validator = MagicMock()
        srv.zim_operations.path_validator.validate_path.side_effect = lambda p: p
        srv.zim_operations.path_validator.validate_zim_file.side_effect = lambda p: p
        return srv

    def test_outbound_uses_extract_article_links(self, server: OpenZimMcpServer):
        """Outbound delegates to extract_article_links_data, resolves URLs, dedupes.

        ``extract_article_links_data`` returns links with ``url`` keys
        carrying href values relative to the source entry.
        ``get_related_articles`` resolves each href against the source path
        and dedupes the result.
        """
        server.zim_operations.extract_article_links_data = MagicMock(
            return_value={
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

    def test_archive_error_swallowed_into_outbound_error(
        self, server: OpenZimMcpServer
    ):
        """Archive-level failures surface as outbound_error, not as a raise.

        Partial-success contract: callers get an empty outbound_results
        list plus an outbound_error string, so a successful entry header
        still ships even when link extraction fails.
        """
        from openzim_mcp.exceptions import OpenZimMcpArchiveError

        server.zim_operations.extract_article_links_data = MagicMock(
            side_effect=OpenZimMcpArchiveError("entry not found")
        )

        result = server.zim_operations.get_related_articles_data(
            "/zim/test.zim", "C/Missing", limit=10
        )
        assert result["outbound_results"] == []
        assert "entry not found" in result["outbound_error"]

    def test_unexpected_exception_propagates(self, server: OpenZimMcpServer):
        """Programming errors (e.g. TypeError) must NOT be swallowed.

        Previously this method caught bare ``Exception``, so a real bug
        in the link-extraction path would surface as a successful-looking
        response with the bug message embedded as a string. Narrowed to
        ``OpenZimMcpArchiveError`` so genuine programming errors bubble
        up to the tool layer's ``tool_error`` envelope instead.
        """
        server.zim_operations.extract_article_links_data = MagicMock(
            side_effect=TypeError("boom")
        )
        with pytest.raises(TypeError, match="boom"):
            server.zim_operations.get_related_articles_data(
                "/zim/test.zim", "C/Source", limit=10
            )

    def test_title_is_target_entry_title_not_anchor_text(
        self, server: OpenZimMcpServer, monkeypatch
    ):
        """Outbound ``title`` is the linked entry's title; ``link_text`` is the anchor.

        Beta-test feedback: prior shape conflated the two — the result said
        ``{path: "Animal", title: "Animalia"}`` (where "Animalia" is the
        inline anchor text in the source article, not the article title).
        """
        server.zim_operations.extract_article_links_data = MagicMock(
            return_value={
                "path": "C/Source",
                "internal_links": [
                    # Anchor text differs from the target's actual title.
                    {"url": "Animal", "text": "Animalia"},
                ],
            }
        )

        # Stub archive lookup so the target's "real" title is resolved.
        target_entry = MagicMock()
        target_entry.title = "Animal"
        target_entry.path = "C/Animal"
        mock_archive = MagicMock()
        mock_archive.get_entry_by_path.return_value = target_entry
        _patch_zim_archive(monkeypatch, mock_archive)

        result = server.zim_operations.get_related_articles_data(
            "/zim/test.zim", "C/Source", limit=10
        )
        outbound = result["outbound_results"]
        assert len(outbound) == 1
        assert outbound[0]["path"] == "C/Animal"
        assert outbound[0]["title"] == "Animal"
        assert outbound[0]["link_text"] == "Animalia"

    def test_title_resolution_uses_validated_path_not_raw_input(
        self, server: OpenZimMcpServer, monkeypatch, tmp_path
    ):
        """Title resolution must open the archive with the path validator's output.

        ``extract_article_links_data`` runs the input through ``validate_path``
        (which expands ``~`` and resolves symlinks) before opening libzim;
        ``_resolve_outbound_titles`` must use the same resolved path.
        Otherwise inputs like ``~/zims/wiki.zim`` open successfully for
        link extraction but silently fail to open for title resolution,
        leaving every outbound title at its placeholder.
        """
        # Use ``tmp_path`` so the "resolved" path is a real absolute path
        # in this OS's native form. Comparing string equality across
        # platforms breaks on Windows because ``Path()`` normalises
        # forward slashes to backslashes — assert via Path equality
        # instead, which is platform-correct.
        raw_input = "~/zims/wiki.zim"
        resolved = tmp_path / "zims" / "wiki.zim"
        resolved_str = str(resolved)

        # Path validator simulates ``~`` expansion: raw input → resolved abs path.
        server.zim_operations.path_validator = MagicMock()
        server.zim_operations.path_validator.validate_path.return_value = resolved_str
        server.zim_operations.path_validator.validate_zim_file.return_value = (
            resolved_str
        )

        server.zim_operations.extract_article_links_data = MagicMock(
            return_value={
                "path": "C/Source",
                "internal_links": [
                    {"url": "Animal", "text": "Animalia"},
                ],
            }
        )

        # Track every path we're asked to open so we can assert it's the
        # validated one, not the raw ``~/...`` input. Normalise via Path so
        # cross-platform comparisons work (Windows' ``Path('/foo/bar')`` is
        # ``\foo\bar``).
        opened_paths: List[Path] = []

        target_entry = MagicMock()
        target_entry.title = "Animal"
        mock_archive = MagicMock()
        mock_archive.get_entry_by_path.return_value = target_entry
        _patch_zim_archive(
            monkeypatch,
            mock_archive,
            on_open=lambda path: opened_paths.append(Path(path)),
        )

        server.zim_operations.get_related_articles_data(raw_input, "C/Source", limit=10)

        # The archive must be opened with the validator's output, not the raw
        # ``~/...`` string. Path("~/zims/wiki.zim") does NOT auto-expand on
        # Python 3, so the raw form would silently fail to find the file.
        assert resolved in opened_paths, (
            f"expected archive open to use validated path {resolved!r}; "
            f"actually opened: {opened_paths!r}"
        )
        assert Path(raw_input) not in opened_paths, (
            f"archive was opened with the raw, unresolved path {raw_input!r}; "
            f"this bypasses path expansion and silently fails on `~` paths"
        )

    def test_title_falls_back_to_path_when_archive_lookup_fails(
        self, server: OpenZimMcpServer, monkeypatch
    ):
        """When archive lookup fails, ``title`` falls back to the path.

        Possible failure modes: target lives in a different namespace,
        the entry is missing, or libzim raises. ``link_text`` still
        carries the original anchor text either way.
        """
        server.zim_operations.extract_article_links_data = MagicMock(
            return_value={
                "path": "C/Source",
                "internal_links": [
                    {"url": "Missing_Article", "text": "see Missing"},
                ],
            }
        )

        mock_archive = MagicMock()
        mock_archive.get_entry_by_path.side_effect = Exception("not found")
        _patch_zim_archive(monkeypatch, mock_archive)

        result = server.zim_operations.get_related_articles_data(
            "/zim/test.zim", "C/Source", limit=10
        )
        outbound = result["outbound_results"]
        assert len(outbound) == 1
        assert outbound[0]["path"] == "C/Missing_Article"
        # No title resolvable -> falls back to the target path
        assert outbound[0]["title"] == "C/Missing_Article"
        assert outbound[0]["link_text"] == "see Missing"


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
            assert (
                resolved is None
            ), f"expected None for url={url!r} source={source!r}, got {resolved!r}"

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
