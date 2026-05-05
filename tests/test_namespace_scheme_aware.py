"""Tests for scheme-aware namespace handling.

Real-archive tests using the testing-suite fixtures. Verify that namespaces
in new-scheme ZIM files are derived from libzim's API (every iterable entry
is in C; M comes from ``metadata_keys``) rather than parsed from the first
character of the entry path.

Background: in old-scheme ZIMs paths are prefixed with the namespace
(``A/Article``, ``M/Title``). In new-scheme ZIMs paths have no prefix and
``Archive.entry_count``/``_get_entry_by_id`` enumerate only the C namespace;
metadata is reached through ``Archive.metadata_keys``.
"""

import json
from pathlib import Path
from typing import Dict, Optional

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations


@pytest.fixture
def ops_for_zim_data(
    basic_test_zim_files: Dict[str, Optional[Path]],
) -> ZimOperations:
    """Build a real ZimOperations rooted at the testing-suite directory.

    Calls ``pytest.skip`` directly when no fixture archive is available so
    each test body can assume a non-None value (cleaner than threading
    ``Optional`` through every test and re-checking).
    """
    sample = basic_test_zim_files.get("withns") or basic_test_zim_files.get("nons")
    if sample is None:
        pytest.skip("ZIM testing-suite fixture not available")
    root = sample.parent.parent  # .../zim-testing-suite/
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(root)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=1000, snippet_length=100),
        logging=LoggingConfig(level="ERROR"),
    )
    return ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=100),
    )


def _require(path: Optional[Path]) -> Path:
    """Return ``path`` or skip the test if it's unavailable."""
    if path is None:
        pytest.skip("ZIM testing-suite fixture not available")
    return path


class TestListNamespacesNewScheme:
    """list_namespaces against a new-scheme archive."""

    def test_no_first_letter_buckets(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """Iterable entries in nons/small.zim must all bucket into C.

        Never into 'F' (favicon.png) or 'M' (main.html) by first letter.
        """
        zim = _require(basic_test_zim_files["nons"])
        result = json.loads(ops_for_zim_data.list_namespaces(str(zim)))
        # The two iterable entries (favicon.png, main.html) are both content.
        assert (
            "F" not in result["namespaces"]
        ), "first-letter bucket 'F' must not appear for new-scheme archives"
        # 'M' may legitimately exist via metadata_keys, but its source must be
        # metadata not first-letter parsing of main.html — count must be > 1
        # because metadata_keys yields several entries.
        if "M" in result["namespaces"]:
            assert (
                result["namespaces"]["M"]["count"] > 1
            ), "'M' must come from metadata_keys, not first-letter of main.html"

    def test_content_namespace_present(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """C must be present and equal to entry_count for the iterable entries."""
        zim = _require(basic_test_zim_files["nons"])
        result = json.loads(ops_for_zim_data.list_namespaces(str(zim)))
        assert "C" in result["namespaces"], "C namespace must exist for new-scheme"
        assert (
            result["namespaces"]["C"]["count"] >= 2
        ), "C must contain favicon.png and main.html"

    def test_metadata_namespace_from_metadata_keys(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """M should be populated from archive.metadata_keys.

        nons/small.zim has 10 metadata_keys (not derived from path parsing).
        """
        zim = _require(basic_test_zim_files["nons"])
        result = json.loads(ops_for_zim_data.list_namespaces(str(zim)))
        assert (
            "M" in result["namespaces"]
        ), "M must be discovered via metadata_keys for new-scheme"
        assert result["namespaces"]["M"]["count"] >= 10


class TestListNamespacesOldScheme:
    """list_namespaces against an old-scheme archive should remain correct."""

    def test_known_namespaces_present(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """Old-scheme withns/small.zim must surface its known namespaces."""
        zim = _require(basic_test_zim_files["withns"])
        result = json.loads(ops_for_zim_data.list_namespaces(str(zim)))
        assert {"-", "A", "I", "M", "X"} <= set(result["namespaces"].keys())
        assert result["namespaces"]["M"]["count"] == 12
        assert result["namespaces"]["A"]["count"] == 1


class TestBrowseNamespaceNewScheme:
    """browse_namespace must use scheme-aware enumeration."""

    def test_browse_C_returns_iterable_entries(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """browse_namespace('C') in new-scheme returns every iterable entry."""
        zim = _require(basic_test_zim_files["nons"])
        result = json.loads(ops_for_zim_data.browse_namespace(str(zim), "C", limit=50))
        paths = {e["path"] for e in result["entries"]}
        assert {"favicon.png", "main.html"} <= paths

    def test_browse_F_returns_empty(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """The bogus first-letter bucket 'F' must yield zero entries."""
        zim = _require(basic_test_zim_files["nons"])
        result = json.loads(ops_for_zim_data.browse_namespace(str(zim), "F", limit=50))
        assert result["entries"] == []

    def test_browse_M_returns_metadata_entries(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """browse_namespace('M') in new-scheme returns metadata entries."""
        zim = _require(basic_test_zim_files["nons"])
        result = json.loads(ops_for_zim_data.browse_namespace(str(zim), "M", limit=50))
        # Should include metadata keys like Title, Language, etc.
        titles = {e["title"] for e in result["entries"]}
        assert "Title" in titles or any(
            "Title" in t for t in titles
        ), f"expected metadata keys in M, got titles: {titles}"


class TestBrowseNamespaceOldScheme:
    """Old-scheme browse_namespace must keep working."""

    def test_browse_M_finds_metadata(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """Old-scheme browse_namespace('M') still finds M/* metadata entries."""
        zim = _require(basic_test_zim_files["withns"])
        result = json.loads(ops_for_zim_data.browse_namespace(str(zim), "M", limit=50))
        paths = {e["path"] for e in result["entries"]}
        # withns/small.zim has 12 M/* entries
        assert "M/Title" in paths
        assert "M/Language" in paths


class TestWalkNamespaceNewScheme:
    """walk_namespace must use scheme-aware iteration."""

    def test_walk_C_enumerates_all(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """walk_namespace('C') must surface every iterable entry."""
        zim = _require(basic_test_zim_files["nons"])
        result = json.loads(ops_for_zim_data.walk_namespace(str(zim), "C", limit=500))
        paths = {e["path"] for e in result["entries"]}
        assert {"favicon.png", "main.html"} <= paths

    def test_walk_F_empty(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """First-letter bucket 'F' must walk to zero results, done=True."""
        zim = _require(basic_test_zim_files["nons"])
        result = json.loads(ops_for_zim_data.walk_namespace(str(zim), "F", limit=500))
        assert result["entries"] == []
        assert result["done"] is True


class TestWalkNamespaceTotalInNamespace:
    """walk_namespace must report a namespace-specific count, not the file total.

    Beta-test feedback: walking an empty namespace returned ``total_entries``
    equal to the whole archive's entry count, which is misleading. The fix
    introduces ``total_in_namespace`` (matching browse_namespace) and renames
    the file-total field to the unambiguous ``archive_entry_count``. The old
    ``total_entries`` is kept as a deprecated alias of ``archive_entry_count``.
    """

    def test_new_scheme_C_total_matches_entry_count(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """New-scheme C: iterator emits only C, so total_in_namespace == entry_count.

        The count is authoritative because libzim tells us exactly.
        """
        zim = _require(basic_test_zim_files["nons"])
        result = ops_for_zim_data.walk_namespace_data(str(zim), "C", limit=500)
        # nons/small.zim has entry_count=2 (favicon.png, main.html)
        assert result["archive_entry_count"] == 2
        assert result["total_in_namespace"] == 2
        assert result["total_in_namespace_is_lower_bound"] is False
        # Deprecated alias kept for backward compatibility
        assert result["total_entries"] == 2

    def test_new_scheme_M_total_matches_metadata_keys(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """New-scheme M count is len(metadata_keys), not archive.entry_count."""
        zim = _require(basic_test_zim_files["nons"])
        result = ops_for_zim_data.walk_namespace_data(str(zim), "M", limit=500)
        # nons/small.zim has 10 metadata_keys, entry_count=2
        assert result["archive_entry_count"] == 2
        assert result["total_in_namespace"] == 10
        assert result["total_in_namespace_is_lower_bound"] is False
        # Deprecated alias mirrors archive_entry_count, NOT the namespace count
        assert result["total_entries"] == 2

    def test_new_scheme_empty_namespace_reports_zero(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """An empty namespace must report 0, not the file total.

        This was the headline beta-test issue: walking namespace ``Z``
        returned ``total_entries: 5175`` (the whole archive size).
        """
        zim = _require(basic_test_zim_files["nons"])
        result = ops_for_zim_data.walk_namespace_data(str(zim), "Z", limit=500)
        assert result["entries"] == []
        assert result["total_in_namespace"] == 0
        assert result["total_in_namespace_is_lower_bound"] is False
        # archive_entry_count is still the file total — make this explicit
        assert result["archive_entry_count"] == 2

    def test_old_scheme_total_in_namespace_is_unknown(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """Old-scheme: count is None because deriving it needs a full scan.

        Reporting an inaccurate number would be misleading; None signals
        "not derivable" so callers know to fall back to browse_namespace.
        ``is_lower_bound`` must also be None — saying ``False`` next to a
        null count would read as "this null is the exact count", which is
        nonsense.
        """
        zim = _require(basic_test_zim_files["withns"])
        result = ops_for_zim_data.walk_namespace_data(str(zim), "M", limit=10)
        # archive_entry_count is always populated
        assert result["archive_entry_count"] >= 1
        # Old-scheme: count not derivable without full scan
        assert result["total_in_namespace"] is None
        # When the count is unknown, the lower-bound flag is also unknown
        assert result["total_in_namespace_is_lower_bound"] is None


class TestSearchWithFiltersNewScheme:
    """search_with_filters namespace must be scheme-aware."""

    def test_filter_by_F_returns_no_matches(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """A real namespace=C filter should not silently match by first letter."""
        # Use the larger climate archive if available so we have content to search.
        # This test uses nons/small.zim's filter logic — even if the archive
        # has no full-text index for the query, the namespace filter must not
        # admit entries whose path simply starts with F.
        # Anchor the test to the new-scheme fixture being present so the
        # assertion is unambiguous about which scheme it covers.
        _require(basic_test_zim_files["nons"])
        # Direct unit-level assertion: cheap-namespace match against 'F' must
        # NOT match a new-scheme path 'favicon.png'.
        ops = ops_for_zim_data
        assert (
            ops._matches_cheap_namespace("favicon.png", "F", has_new_scheme=True)
            is False
        )
        assert (
            ops._matches_cheap_namespace("favicon.png", "C", has_new_scheme=True)
            is True
        )


class TestBrowseNamespaceTotalIsAuthoritative:
    """browse_namespace must report authoritative totals when libzim does."""

    def test_new_scheme_C_total_matches_entry_count(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """For new-scheme C, totals come straight from archive.entry_count.

        is_total_authoritative must be True (libzim tells us exactly).
        """
        zim = _require(basic_test_zim_files["nons"])
        result = json.loads(ops_for_zim_data.browse_namespace(str(zim), "C", limit=50))
        # nons/small.zim has entry_count=2 (favicon.png, main.html)
        assert result["total_in_namespace"] == 2
        assert result["is_total_authoritative"] is True

    def test_new_scheme_M_total_matches_metadata_keys(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ):
        """For new-scheme M, totals come from archive.metadata_keys."""
        zim = _require(basic_test_zim_files["nons"])
        result = json.loads(ops_for_zim_data.browse_namespace(str(zim), "M", limit=50))
        # nons/small.zim has 10 metadata_keys
        assert result["total_in_namespace"] == 10
        assert result["is_total_authoritative"] is True


class TestExtractNamespaceFromPathSchemeAware:
    """Unit-level tests for the scheme-aware extraction helper."""

    def test_new_scheme_returns_C_regardless_of_path(self, ops_for_zim_data):
        """Any new-scheme entry path must bucket as C, not by first letter."""
        ops = ops_for_zim_data
        for p in ["favicon.png", "main.html", "Evolution", "Bob_Dylan", "🐜"]:
            assert (
                ops._extract_namespace_from_path(p, has_new_scheme=True) == "C"
            ), f"new-scheme path {p!r} must bucket as C"

    def test_old_scheme_uses_path_prefix(self, ops_for_zim_data):
        """Old-scheme paths still bucket by their single-char prefix."""
        ops = ops_for_zim_data
        assert ops._extract_namespace_from_path("A/main.html") == "A"
        assert ops._extract_namespace_from_path("M/Title") == "M"
        assert ops._extract_namespace_from_path("-/favicon") == "-"

    def test_default_has_new_scheme_false_preserves_legacy_behaviour(
        self, ops_for_zim_data
    ):
        """Existing callers that don't pass the flag must see the old behaviour."""
        ops = ops_for_zim_data
        # No scheme flag → old-scheme parsing
        assert ops._extract_namespace_from_path("A/Article_Title") == "A"
        assert ops._extract_namespace_from_path("metadata/title") == "M"
        assert ops._extract_namespace_from_path("") == "Unknown"
