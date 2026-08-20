"""v3.0.0 field-defect fixes — ``structure`` workstream (links / sections / TOC).

One test class per defect from the 2026-08-19 real-world sweep, in packet
order. Each docstring names the defect id and the behaviour it pins.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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

ARCHIVE_CTX = "openzim_mcp.zim_operations.zim_archive"


@pytest.fixture
def ops(tmp_path: Path) -> ZimOperations:
    """ZimOperations rooted in a temp dir holding one fake ``.zim`` path."""
    (tmp_path / "test.zim").touch()
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=100_000, snippet_length=200),
        logging=LoggingConfig(level="ERROR"),
    )
    return ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache, enable_background_cleanup=False),
        ContentProcessor(snippet_length=200),
    )


@pytest.fixture
def zim_path(tmp_path: Path) -> str:
    return str(tmp_path / "test.zim")


def _html_archive(
    html: str,
    *,
    title: str = "Test",
    entry_path: str = "Test",
    mime: str = "text/html",
) -> MagicMock:
    """Mock libzim archive serving ``html`` for any requested path."""
    item = MagicMock()
    item.content = html.encode("utf-8")
    item.mimetype = mime
    item.path = entry_path
    entry = MagicMock()
    entry.title = title
    entry.path = entry_path
    entry.is_redirect = False
    entry.get_item.return_value = item
    archive = MagicMock()
    archive.get_entry_by_path.return_value = entry
    archive.has_entry_by_path.return_value = True
    return archive


def _missing_entry_archive() -> MagicMock:
    """Mock archive whose every path lookup misses the way libzim does."""
    archive = MagicMock()
    archive.get_entry_by_path.side_effect = KeyError("Cannot find entry")
    archive.has_entry_by_path.return_value = False
    return archive


# ---------------------------------------------------------------------------
# D18 — zim_get_section on a nonexistent entry must return entry_not_found
# ---------------------------------------------------------------------------


class TestD18SectionMissingEntry:
    """D18: a missing entry_path is an ``entry_not_found`` envelope, not a
    raw ``KeyError`` that the wrapper renders as a transient server fault."""

    def test_missing_entry_returns_entry_not_found_payload(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _missing_entry_archive()
            result = ops.get_section_data(zim_path, "A/Nope", section_id="summary")

        assert result.get("error") is True
        assert result["operation"] == "entry_not_found"
        assert "A/Nope" in result["message"]
        assert "KeyError" not in result["message"]
        # The guidance must point at path correction, not retries.
        assert "spelling" in result["message"].lower()


# ---------------------------------------------------------------------------
# D19 — duplicate explicit anchors must yield unique, fetchable section ids
# ---------------------------------------------------------------------------

DUPLICATE_ANCHOR_HTML = """\
<html><body>
<h1>Thrasymachus</h1>
<p>Lead paragraph.</p>
<h2 id="SH4b">b. Secondary Sources</h2>
<p>Books about Thrasymachus.</p>
<h2 id="SH4b">Author Information</h2>
<p>Written by a scholar.</p>
</body></html>
"""


class TestD19DuplicateAnchorIds:
    """D19: when an archive reuses an anchor name, the second heading gets a
    disambiguated id so every TOC node is fetchable and no id silently
    resolves to the wrong section. The first occurrence keeps its anchor."""

    def test_toc_ids_are_unique_and_first_anchor_is_preserved(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _html_archive(
                DUPLICATE_ANCHOR_HTML
            )
            toc = ops.get_table_of_contents_data(zim_path, "Test")

        ids = [node["section_id"] for node in toc["toc"][0]["children"]]
        assert ids == ["SH4b", "SH4b_2"]
        assert len(set(ids)) == len(ids)

    def test_second_id_fetches_second_section(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _html_archive(
                DUPLICATE_ANCHOR_HTML
            )
            first = ops.get_section_data(zim_path, "Test", section_id="SH4b")
            second = ops.get_section_data(zim_path, "Test", section_id="SH4b_2")

        assert first["section_title"] == "b. Secondary Sources"
        assert "Books about" in first["content_markdown"]
        assert second["section_title"] == "Author Information"
        assert "Written by" in second["content_markdown"]


# ---------------------------------------------------------------------------
# D20 — compact=True section text must match zim_get's compact article text
# ---------------------------------------------------------------------------

LINKED_HTML = """\
<html><body>
<h1>Diabetes</h1>
<p>Lead paragraph.</p>
<h2 id="what-is-diabetes">What is diabetes?</h2>
<p>Diabetes raises your <a href="bloodglucose.html">blood glucose</a>,
also called <a href="sugar.html">blood sugar</a>, above normal.</p>
</body></html>
"""


class TestD20CompactLinkParity:
    """D20: both compact surfaces promise the same slice shape, so a
    compact section body must be link-stripped exactly like the compact
    article body — and therefore be a substring of it."""

    def test_compact_section_is_substring_of_compact_article(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _html_archive(LINKED_HTML)
            article = ops.get_zim_entry_data(zim_path, "Test", compact=True)
            section = ops.get_section_data(
                zim_path, "Test", section_id="what-is-diabetes", compact=True
            )

        body = section["content_markdown"]
        assert "](" not in body, body
        assert "blood glucose" in body
        assert body.strip() in article["content"]
        assert section["char_count"] == len(body)

    def test_raw_section_keeps_links(self, ops: ZimOperations, zim_path: str) -> None:
        with patch(ARCHIVE_CTX) as ctx:
            ctx.return_value.__enter__.return_value = _html_archive(LINKED_HTML)
            section = ops.get_section_data(
                zim_path, "Test", section_id="what-is-diabetes", compact=False
            )
        assert "](bloodglucose.html)" in section["content_markdown"]
