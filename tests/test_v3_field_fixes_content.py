"""v3.0.0 field-defect fixes — content cluster (zim_get bodies, lead extraction).

Each test pins one defect from the 2026-08-19 real-world sweep against the
MedlinePlus / IEP corpora. Fixtures are trimmed copies of the real archive
HTML so the shapes that broke in the field are the shapes under test.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations


@pytest.fixture
def ops(
    test_config: OpenZimMcpConfig,
    path_validator: PathValidator,
    openzim_mcp_cache: OpenZimMcpCache,
    content_processor: ContentProcessor,
) -> ZimOperations:
    return ZimOperations(
        test_config, path_validator, openzim_mcp_cache, content_processor
    )


@pytest.fixture
def zim_file(temp_dir: Path) -> Path:
    """A placeholder file inside the allowed directory; the archive is mocked."""
    path = temp_dir / "corpus.zim"
    path.write_text("x")
    return path


def _html_entry(path: str, title: str, html: str) -> MagicMock:
    entry = MagicMock()
    entry.is_redirect = False
    entry.path = path
    entry.title = title
    item = MagicMock()
    item.mimetype = "text/html"
    item.content = html.encode("utf-8")
    entry.get_item.return_value = item
    return entry


def _archive_with(entries: dict[str, MagicMock]) -> MagicMock:
    """A mock libzim Archive that resolves exactly the given path spellings."""
    inst = MagicMock()
    inst.has_new_namespace_scheme = True

    def _get(path: str) -> MagicMock:
        if path in entries:
            return entries[path]
        raise KeyError("Cannot find entry")

    inst.get_entry_by_path.side_effect = _get
    inst.has_entry_by_path.side_effect = lambda p: p in entries
    return inst


# ---------------------------------------------------------------------------
# D07 — percent-encoded paths served by the archive's own links must resolve
# ---------------------------------------------------------------------------

_IEP_RAW = "iep.utm.edu/gauḍapad/"
_IEP_ENCODED = "iep.utm.edu/gau%E1%B8%8Dapad/"


@patch("openzim_mcp.zim_operations.Archive")
def test_percent_encoded_path_resolves_before_search_fallback(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """D07: the IEP G-index links ``../gau%E1%B8%8Dapad/`` exactly as archived;
    libzim stores the raw UTF-8 spelling. Feeding the served link back into
    zim_get must resolve via percent-decoding, not dead-end in not-found."""
    mock_archive.return_value = _archive_with(
        {_IEP_RAW: _html_entry(_IEP_RAW, "Gaudapada", "<h1>Gaudapada</h1><p>x</p>")}
    )
    search = MagicMock(return_value=None)
    with patch.object(ops, "_find_entry_by_search", search):
        result = ops.get_zim_entry_data(str(zim_file), _IEP_ENCODED)

    assert not result.get("error"), result
    assert result["path"] == _IEP_RAW
    assert result["requested_path"] == _IEP_ENCODED
    assert "Gaudapada" in result["content"]
    # The decoded spelling is a cheap exact probe; it must win before the
    # search-based fallback is consulted at all.
    search.assert_not_called()


@patch("openzim_mcp.zim_operations.Archive")
def test_literal_percent_path_is_not_decoded_away(
    mock_archive: MagicMock, ops: ZimOperations, zim_file: Path
) -> None:
    """warc2zim stores some asset names with a literal ``%``; the raw spelling
    must still be tried first so those keep resolving."""
    literal = "I/Al_Gore%2C_2007.webp"
    mock_archive.return_value = _archive_with(
        {literal: _html_entry(literal, "Al Gore", "<p>photo</p>")}
    )
    result = ops.get_zim_entry_data(str(zim_file), literal)
    assert result["path"] == literal
    assert "requested_path" not in result
