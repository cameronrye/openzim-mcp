"""V2 golden-file fixture archive builders + shared helpers.

Centralises three things used by ``test_golden_v2_phase_*`` and ``test_response_contract``:

* ``_HtmlItem`` – the libzim Item subclass used to populate test ZIMs.
* ``strip_volatile`` / ``capture_or_compare`` – the snapshot-equality helpers.
* ``make_zim_ops`` – the canonical ``ZimOperations`` builder used by both
  golden modules and the contract-shape test.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from libzim.writer import Creator, Hint, Item, StringProvider

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

# ---------------------------------------------------------------------------
# Shared libzim Item used by every fixture archive in this module.
# ---------------------------------------------------------------------------


class _HtmlItem(Item):
    """A minimal HTML item suitable for the libzim ``Creator`` API."""

    def __init__(self, path: str, title: str, html: str) -> None:
        super().__init__()
        self._path = path
        self._title = title
        self._html = html

    def get_path(self) -> str:
        return self._path

    def get_title(self) -> str:
        return self._title

    def get_mimetype(self) -> str:
        return "text/html"

    def get_contentprovider(self) -> StringProvider:
        return StringProvider(self._html)

    def get_hints(self) -> dict[Hint, int]:
        return {Hint.FRONT_ARTICLE: 1}


# ---------------------------------------------------------------------------
# Snapshot helpers (used by test_golden_v2_phase_*).
# ---------------------------------------------------------------------------

# Keys to strip from snapshots — volatile or environment-specific.
_VOLATILE_KEYS = frozenset(
    {
        # token/char counts depend on rendered snippet text
        "tokens_est",
        "chars",
        # file-system metadata — environment-specific
        "directory",
        "size_bytes",
        "modified",
        "size",
        # opaque cursor encodes archive identity (tmp path digest)
        "next_cursor",
        # find_entry_by_title_data embeds the absolute zim file path in results
        "zim_file",
    }
)


def strip_volatile(d: Any) -> Any:
    """Recursively remove volatile keys from a nested dict/list structure."""
    if isinstance(d, dict):
        return {k: strip_volatile(v) for k, v in d.items() if k not in _VOLATILE_KEYS}
    if isinstance(d, list):
        return [strip_volatile(x) for x in d]
    return d


def capture_or_compare(
    name: str,
    payload: dict,
    *,
    capture_mode: bool,
    goldens_dir: Path,
) -> None:
    """Write golden snapshot or assert equality against saved snapshot.

    When ``capture_mode=True`` or the file is absent, the payload is
    serialised to JSON and written. Otherwise the saved golden is loaded
    and ``strip_volatile(payload)`` must equal ``strip_volatile(expected)``.
    """
    goldens_dir.mkdir(parents=True, exist_ok=True)
    path = goldens_dir / f"{name}.json"
    if capture_mode or not path.exists():
        path.write_text(
            json.dumps(
                strip_volatile(payload), indent=2, ensure_ascii=False, sort_keys=True
            ),
            newline="\n",
        )
        return
    expected = json.loads(path.read_text())
    assert strip_volatile(payload) == strip_volatile(expected), (
        f"Golden mismatch for {name}. "
        "Set OPENZIM_MCP_CAPTURE_GOLDENS=1 to refresh after intentional changes."
    )


def golden_capture_mode() -> bool:
    """Return True when the OPENZIM_MCP_CAPTURE_GOLDENS env var is set to '1'."""
    return os.environ.get("OPENZIM_MCP_CAPTURE_GOLDENS") == "1"


# ---------------------------------------------------------------------------
# Shared ZimOperations builder.
# ---------------------------------------------------------------------------


def make_zim_ops(zim_dir: str) -> ZimOperations:
    """Construct a ZimOperations instance pointing at ``zim_dir``.

    Used by golden tests and the contract-shape test to share a uniform
    construction recipe (cache size, content limits, snippet length, log level).
    """
    config = OpenZimMcpConfig(
        allowed_directories=[zim_dir],
        tool_mode="advanced",
        cache=CacheConfig(enabled=True, max_size=20, ttl_seconds=300),
        content=ContentConfig(max_content_length=10000, snippet_length=200),
        logging=LoggingConfig(level="WARNING"),
    )
    path_validator = PathValidator(config.allowed_directories)
    cache = OpenZimMcpCache(config.cache)
    content_processor = ContentProcessor(snippet_length=config.content.snippet_length)
    return ZimOperations(config, path_validator, cache, content_processor)


# ---------------------------------------------------------------------------
# Phase A archive — shipped with v2.0.0a1; used by Phase B goldens.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def v2_phase_a_zim(tmp_path_factory) -> Path:
    """Build a tiny ZIM with articles for Phase A snapshot tests.

    Articles:
      - A/Einstein: contains an infobox table + one large content table
      - A/PlainArticle: no infobox, no large table (control)
      - A/MultiTable: multiple oversized tables
      - A/LongArticle: longer than typical compact_budget (forces truncation)
    """
    out_dir = tmp_path_factory.mktemp("v2-golden")
    out_path = out_dir / "v2_phase_a.zim"

    fixtures = [
        (
            "A/Einstein",
            "Einstein",
            "<html><body>"
            "<table class='infobox'>"
            "<tr><th>Born</th><td>14 March 1879</td></tr>"
            "<tr><th>Died</th><td>18 April 1955</td></tr>"
            "<tr><th>Field</th><td>Theoretical physics</td></tr>"
            "</table>"
            "<p>Albert Einstein was a German-born theoretical physicist. "
            "He developed the theory of relativity, one of the two pillars "
            "of modern physics.</p>"
            "<table>"
            + "".join(
                f"<tr><td>Award {i}</td><td>Year {1900 + i}</td></tr>"
                for i in range(15)
            )
            + "</table>"
            "</body></html>",
        ),
        (
            "A/PlainArticle",
            "PlainArticle",
            "<html><body><p>This article has no infobox and no large tables. "
            "It is a control case for the snapshot suite.</p></body></html>",
        ),
        (
            "A/MultiTable",
            "MultiTable",
            "<html><body><p>Intro paragraph.</p>"
            "<table>" + "<tr><td>x</td></tr>" * 20 + "</table>"
            "<p>Middle paragraph.</p>"
            "<table>" + "<tr><td>y</td></tr>" * 20 + "</table>"
            "</body></html>",
        ),
        (
            "A/LongArticle",
            "LongArticle",
            "<html><body><p>" + ("Word " * 5000) + "</p></body></html>",
        ),
    ]

    with Creator(out_path).config_indexing(True, "eng") as creator:
        for path, title, html in fixtures:
            creator.add_item(_HtmlItem(path, title, html))
        creator.set_mainpath("A/Einstein")

    return out_path


# ---------------------------------------------------------------------------
# Phase C archive — heading-rich content for get_section + synthesize goldens.
# ---------------------------------------------------------------------------


_BERLIN_HTML = (
    "<html><body><h1>Berlin</h1>"
    + "<p>Berlin is the capital and largest city of Germany.</p>"
    + "<h2 id='geography'>Geography</h2>"
    + "<p>Berlin lies in northeastern Germany on the river Spree.</p>"
    + "<h2 id='climate'>Climate</h2>"
    + "<p>Berlin has a temperate seasonal climate.</p>"
    + "<h2 id='history'>History</h2>"
    + "<p>The history of Berlin begins in the 13th century.</p>"
    + "</body></html>"
)
_MUNICH_HTML = (
    "<html><body><h1>Munich</h1>"
    + "<p>Munich is the capital of Bavaria.</p>"
    + "<h2 id='history'>History</h2>"
    + "<p>Munich was founded in 1158.</p>"
    + "<h2 id='culture'>Culture</h2>"
    + "<p>Munich is famous for Oktoberfest.</p>"
    + "</body></html>"
)


@pytest.fixture(scope="module")
def v2_phase_c_zim(tmp_path_factory) -> Path:
    """Build a heading-rich ZIM for Phase C golden tests (get_section + synthesize).

    Articles:
      - A/Berlin: h2 sections geography, climate, history
      - A/Munich: h2 sections history, culture
    """
    out_dir = tmp_path_factory.mktemp("v2-phase-c-golden")
    out_path = out_dir / "v2_phase_c.zim"

    articles = [
        ("A/Berlin", "Berlin", _BERLIN_HTML),
        ("A/Munich", "Munich", _MUNICH_HTML),
    ]

    with Creator(out_path).config_indexing(True, "eng") as creator:
        for path, title, html in articles:
            creator.add_item(_HtmlItem(path, title, html))
        creator.set_mainpath("A/Berlin")

    return out_path
