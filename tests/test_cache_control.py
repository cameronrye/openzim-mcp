"""Tests covering cache-control invariants for ZimOperations.

Regression coverage for finding C5 (review v1.0): error sentinels and
zero-result responses must not be cached, otherwise a single transient
failure (decompression hiccup, libzim index warm-up) gets locked in for
the full TTL.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.exceptions import OpenZimMcpArchiveError
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations


@pytest.fixture
def zim_operations(
    test_config: OpenZimMcpConfig,
    path_validator: PathValidator,
    openzim_mcp_cache: OpenZimMcpCache,
    content_processor: ContentProcessor,
) -> ZimOperations:
    """Construct a ZimOperations with a real cache so we can assert cache state."""
    return ZimOperations(
        test_config, path_validator, openzim_mcp_cache, content_processor
    )


def _zim_path(temp_dir: Path) -> Path:
    """Create a placeholder ZIM file the path validator will accept."""
    p = temp_dir / "test.zim"
    p.write_bytes(b"")
    return p


def test_get_zim_entry_does_not_cache_error_strings(
    zim_operations: ZimOperations, temp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If process_mime_content raises, the error sentinel must not land in the cache."""
    zim_file = _zim_path(temp_dir)

    calls = {"n": 0}

    def boom(*args, **kwargs):
        calls["n"] += 1
        raise OpenZimMcpArchiveError("simulated decompression failure")

    monkeypatch.setattr(zim_operations.content_processor, "process_mime_content", boom)

    with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
        mock_archive_instance = MagicMock()
        mock_entry = MagicMock()
        mock_entry.title = "Foo"
        mock_item = MagicMock()
        mock_item.mimetype = "text/html"
        mock_item.content = b"<html><body>broken</body></html>"
        mock_entry.get_item.return_value = mock_item
        mock_archive_instance.get_entry_by_path.return_value = mock_entry
        mock_archive.return_value.__enter__.return_value = mock_archive_instance

        out1 = zim_operations.get_zim_entry(str(zim_file), "A/Foo")
        out2 = zim_operations.get_zim_entry(str(zim_file), "A/Foo")

    # Both calls produced the error-sentinel content, but neither was served
    # from the cache: process_mime_content must have been re-invoked.
    assert "Error retrieving content" in out1
    assert calls["n"] == 2, "error result was cached and re-served"

    # Stronger assertion: the cache slot for this entry must not be populated.
    validated_path = zim_operations.path_validator.validate_path(str(zim_file))
    validated_path = zim_operations.path_validator.validate_zim_file(validated_path)
    cache_key = (
        f"entry:{validated_path}:A/Foo:"
        f"{zim_operations.config.content.max_content_length}:0"
    )
    assert (
        zim_operations.cache.get(cache_key) is None
    ), "error sentinel should not be cached"
    # And we still produced output for the caller.
    assert out2 != "" and "Foo" in out2


def test_search_does_not_cache_zero_result_response(
    zim_operations: ZimOperations, temp_dir: Path
) -> None:
    """Zero-result search responses must not be cached for the TTL.

    libzim's lazy index warm-up can return 0 transiently; caching the
    no-results sentinel locks the query out for the entire TTL.
    """
    zim_file = _zim_path(temp_dir)

    with patch("openzim_mcp.zim_operations.Archive") as mock_archive:
        mock_archive_instance = MagicMock()
        mock_archive.return_value = mock_archive_instance

        mock_searcher = MagicMock()
        mock_search = MagicMock()
        mock_search.getEstimatedMatches.return_value = 0
        mock_searcher.search.return_value = mock_search

        with (
            patch("openzim_mcp.zim_operations.Searcher", return_value=mock_searcher),
            patch("openzim_mcp.zim_operations.Query"),
        ):
            result = zim_operations.search_zim_file(
                str(zim_file), "warmup", limit=10, offset=0
            )

    assert "No search results found" in result

    # The cache slot for the zero-result query must remain empty.
    validated_path = zim_operations.path_validator.validate_path(str(zim_file))
    validated_path = zim_operations.path_validator.validate_zim_file(validated_path)
    cache_key = f"search:{validated_path}:warmup:10:0"
    assert (
        zim_operations.cache.get(cache_key) is None
    ), "zero-result response should not be cached"


def test_filtered_search_does_not_cache_zero_result_response(
    zim_operations: ZimOperations, temp_dir: Path
) -> None:
    """Filtered search must not cache the no-results / no-filtered-matches sentinels."""
    zim_file = _zim_path(temp_dir)

    with patch("openzim_mcp.zim_operations.Archive") as mock_archive:
        mock_archive_instance = MagicMock()
        mock_archive.return_value = mock_archive_instance

        mock_searcher = MagicMock()
        mock_search = MagicMock()
        mock_search.getEstimatedMatches.return_value = 0
        mock_searcher.search.return_value = mock_search

        with (
            patch("openzim_mcp.zim_operations.Searcher", return_value=mock_searcher),
            patch("openzim_mcp.zim_operations.Query"),
        ):
            result = zim_operations.search_with_filters(
                str(zim_file),
                "warmup",
                namespace="C",
                content_type=None,
                limit=10,
                offset=0,
            )

    assert "No search results found" in result

    validated_path = zim_operations.path_validator.validate_path(str(zim_file))
    validated_path = zim_operations.path_validator.validate_zim_file(validated_path)
    cache_key = f"search_filtered:{validated_path}:warmup:C:None:10:0"
    assert (
        zim_operations.cache.get(cache_key) is None
    ), "filtered zero-result response should not be cached"


def test_get_search_suggestions_does_not_cache_on_error(
    zim_operations: ZimOperations, temp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If suggestion generation raises, the error must not land in the cache.

    Drives a real failure through the production code path: stubs the
    inner search-based suggestions helper to raise so the error propagates
    through ``_generate_search_suggestions`` to the public method.
    """
    zim_file = _zim_path(temp_dir)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated libzim suggestion-iterator failure")

    monkeypatch.setattr(zim_operations, "_get_suggestions_from_search", boom)

    with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
        mock_archive_instance = MagicMock()
        mock_archive.return_value.__enter__.return_value = mock_archive_instance

        with pytest.raises(OpenZimMcpArchiveError):
            zim_operations.get_search_suggestions(str(zim_file), "warmup", limit=10)

    validated_path = zim_operations.path_validator.validate_path(str(zim_file))
    validated_path = zim_operations.path_validator.validate_zim_file(validated_path)
    cache_key = f"suggestions:{validated_path}:warmup:10"
    assert (
        zim_operations.cache.get(cache_key) is None
    ), "errored suggestion response should not be cached"


def test_get_entry_summary_does_not_cache_on_html_extract_error(
    zim_operations: ZimOperations, temp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If HTML summary extraction raises, the error must not land in the cache.

    Stubs ``BeautifulSoup`` (used inside ``_extract_html_summary``) to raise
    so the failure propagates through the real code path.
    """
    zim_file = _zim_path(temp_dir)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated BeautifulSoup parse failure")

    monkeypatch.setattr("bs4.BeautifulSoup", boom)

    with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
        mock_archive_instance = MagicMock()
        mock_entry = MagicMock()
        mock_entry.title = "Foo"
        mock_entry.path = "C/Foo"
        mock_item = MagicMock()
        mock_item.mimetype = "text/html"
        mock_item.content = b"<html><body><p>broken</p></body></html>"
        mock_entry.get_item.return_value = mock_item
        mock_archive_instance.get_entry_by_path.return_value = mock_entry
        mock_archive.return_value.__enter__.return_value = mock_archive_instance

        with pytest.raises(OpenZimMcpArchiveError):
            zim_operations.get_entry_summary(str(zim_file), "C/Foo", max_words=50)

    validated_path = zim_operations.path_validator.validate_path(str(zim_file))
    validated_path = zim_operations.path_validator.validate_zim_file(validated_path)
    cache_key = f"summary:{validated_path}:C/Foo:50"
    assert (
        zim_operations.cache.get(cache_key) is None
    ), "errored summary response should not be cached"


def test_get_table_of_contents_does_not_cache_on_toc_build_error(
    zim_operations: ZimOperations, temp_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If TOC building raises, the error must not land in the cache.

    Stubs ``BeautifulSoup`` (used inside ``_build_hierarchical_toc``) to
    raise so the failure propagates through the real code path.
    """
    zim_file = _zim_path(temp_dir)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated BeautifulSoup parse failure")

    monkeypatch.setattr("bs4.BeautifulSoup", boom)

    with patch("openzim_mcp.zim_operations.zim_archive") as mock_archive:
        mock_archive_instance = MagicMock()
        mock_entry = MagicMock()
        mock_entry.title = "Foo"
        mock_entry.path = "C/Foo"
        mock_item = MagicMock()
        mock_item.mimetype = "text/html"
        mock_item.content = b"<html><body><h1>Foo</h1></body></html>"
        mock_entry.get_item.return_value = mock_item
        mock_archive_instance.get_entry_by_path.return_value = mock_entry
        mock_archive.return_value.__enter__.return_value = mock_archive_instance

        with pytest.raises(OpenZimMcpArchiveError):
            zim_operations.get_table_of_contents(str(zim_file), "C/Foo")

    validated_path = zim_operations.path_validator.validate_path(str(zim_file))
    validated_path = zim_operations.path_validator.validate_zim_file(validated_path)
    cache_key = f"toc:{validated_path}:C/Foo"
    assert (
        zim_operations.cache.get(cache_key) is None
    ), "errored TOC response should not be cached"
