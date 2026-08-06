"""Correctness-sweep regression tests.

Each test class pins one defect found in the 2026-08 full-codebase sweep;
the docstrings name the failure the fix closes.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock, patch

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import CacheConfig, ContentConfig, OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.zim_operations import ZimOperations


def _ops(tmp_path: Path) -> ZimOperations:
    config = OpenZimMcpConfig(
        allowed_directories=[str(tmp_path)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=10000, snippet_length=200),
    )
    return ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(snippet_length=200),
    )


def _entry_for(eid: str) -> MagicMock:
    e = MagicMock()
    e.path = eid
    e.title = eid.rsplit("/", 1)[-1]
    e.is_redirect = False
    item = MagicMock()
    item.mimetype = "text/html"
    item.content = b"<p>body text</p>"
    e.get_item.return_value = item
    return e


def _search_stub(entry_ids: List[str], estimated: Optional[int] = None) -> MagicMock:
    search = MagicMock()
    search.getEstimatedMatches.return_value = (
        len(entry_ids) if estimated is None else estimated
    )
    search.getResults.side_effect = lambda start, count: entry_ids[
        start : start + count
    ]
    return search


def _archive_stub(get_entry=_entry_for) -> MagicMock:
    archive = MagicMock()
    archive.has_new_namespace_scheme = False
    archive.has_fulltext_index = True
    archive.get_entry_by_path.side_effect = get_entry
    return archive


# --------------------------------------------------------------------------
# _perform_search: Xapian estimate exceeding the real hit count must not
# produce a stuck cursor (empty page + done=False + same offset forever).
# --------------------------------------------------------------------------


class TestSearchCursorTerminatesOnEstimateOvershoot:
    def _perform(self, tmp_path, entry_ids, estimated, limit, offset):
        ops = _ops(tmp_path)
        zim_file = tmp_path / "test.zim"
        zim_file.write_bytes(b"zim")
        archive = _archive_stub()
        with patch("openzim_mcp.zim_operations.Searcher") as mock_searcher:
            mock_searcher.return_value.search.return_value = _search_stub(
                entry_ids, estimated=estimated
            )
            payload, _total = ops._perform_search(
                archive, "q", limit, offset, validated_path=zim_file
            )
        return payload

    def test_empty_page_past_real_hits_is_done(self, tmp_path) -> None:
        """Estimate 250, 180 real hits: the page at offset=180 is empty and
        must terminate pagination instead of re-minting the same cursor."""
        entry_ids = [f"C/A_{i}" for i in range(180)]
        payload = self._perform(tmp_path, entry_ids, 250, limit=10, offset=180)
        assert payload["results"] == []
        assert payload["done"] is True
        assert payload["next_cursor"] is None

    def test_short_page_at_exhaustion_is_done(self, tmp_path) -> None:
        """A page that comes back shorter than requested means the real
        result stream is exhausted — done must be True."""
        entry_ids = [f"C/A_{i}" for i in range(180)]
        payload = self._perform(tmp_path, entry_ids, 250, limit=20, offset=170)
        assert len(payload["results"]) == 10
        assert payload["done"] is True
        assert payload["next_cursor"] is None

    def test_full_page_mid_stream_still_pages(self, tmp_path) -> None:
        entry_ids = [f"C/A_{i}" for i in range(180)]
        payload = self._perform(tmp_path, entry_ids, 250, limit=10, offset=0)
        assert len(payload["results"]) == 10
        assert payload["done"] is False
        assert payload["next_cursor"] is not None


# --------------------------------------------------------------------------
# browse_namespace: the resume offset must count scanned candidate rows,
# not surviving materialised rows — otherwise dropped rows cause duplicate
# pages, and a fully-failing window never advances (livelock).
# --------------------------------------------------------------------------


def _decode_cursor(token: str) -> dict:
    import base64
    import json

    padded = token + "=" * (-len(token) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))


class TestBrowseNamespaceResumeCountsScannedRows:
    def _browse(self, tmp_path, listing, dropped, limit, offset):
        ops = _ops(tmp_path)
        zim_file = tmp_path / "test.zim"
        zim_file.write_bytes(b"zim")
        archive = _archive_stub()
        archive.has_new_namespace_scheme = False

        def materialise(_archive, entry_path, _scheme):
            if entry_path in dropped:
                return None
            return {"path": entry_path, "title": entry_path.rsplit("/", 1)[-1]}

        with (
            patch("openzim_mcp.zim_operations.zim_archive") as mock_zim_archive,
            patch.object(
                ops, "_find_entries_in_namespace", return_value=(listing, True)
            ),
            patch.object(ops, "_materialise_browse_entry", side_effect=materialise),
        ):
            mock_zim_archive.return_value.__enter__.return_value = archive
            return ops.browse_namespace_data(
                str(zim_file), "A", limit=limit, offset=offset
            )

    def test_dropped_row_does_not_rewind_cursor(self, tmp_path) -> None:
        """One drop inside the window: the cursor must resume at the end of
        the scanned window (5), not at survivors-count (4), which would
        duplicate the last surviving row on the next page."""
        listing = [f"A/e{i}" for i in range(10)]
        data = self._browse(tmp_path, listing, dropped={"A/e2"}, limit=5, offset=0)
        assert [r["path"] for r in data["results"]] == ["A/e0", "A/e1", "A/e3", "A/e4"]
        assert data["done"] is False
        cursor = _decode_cursor(data["next_cursor"])
        assert cursor["s"]["o"] == 5

    def test_fully_failing_window_still_advances(self, tmp_path) -> None:
        """A window whose rows all fail to materialise must still advance the
        cursor instead of re-minting the same offset forever."""
        listing = [f"A/e{i}" for i in range(10)]
        data = self._browse(
            tmp_path, listing, dropped={f"A/e{i}" for i in range(5)}, limit=5, offset=0
        )
        assert data["results"] == []
        assert data["done"] is False
        cursor = _decode_cursor(data["next_cursor"])
        assert cursor["s"]["o"] == 5

    def test_final_window_is_done(self, tmp_path) -> None:
        listing = [f"A/e{i}" for i in range(10)]
        data = self._browse(tmp_path, listing, dropped=set(), limit=5, offset=5)
        assert data["done"] is True
        assert data["next_cursor"] is None


# --------------------------------------------------------------------------
# walk_namespace M/W: a resume offset past the end must clamp scanned_count
# to zero, not report a negative count.
# --------------------------------------------------------------------------


class TestWalkNamespaceScannedCountClamped:
    def test_metadata_walk_past_end_reports_zero_scanned(self) -> None:
        from openzim_mcp.zim.namespace import _NamespaceMixin

        archive = MagicMock()
        archive.metadata_keys = ["Title", "Description"]
        result = _NamespaceMixin._walk_new_scheme_metadata(
            archive, scan_at=50, limit=10, archive_entry_count=100
        )
        assert result["scanned_count"] == 0
        assert result["results"] == []
        assert result["done"] is True

    def test_well_known_walk_past_end_reports_zero_scanned(self) -> None:
        from openzim_mcp.zim.namespace import _NamespaceMixin

        archive = MagicMock()
        archive.has_main_entry = True
        archive.has_illustration.return_value = True
        result = _NamespaceMixin._walk_new_scheme_well_known(
            archive, scan_at=50, limit=10, archive_entry_count=100
        )
        assert result["scanned_count"] == 0
        assert result["results"] == []
        assert result["done"] is True


# --------------------------------------------------------------------------
# Simple-mode links pagination: the non-compact path must honour the
# decoded cursor offset/limit/kind instead of returning page 1 forever,
# and the cursor's kind bucket must scope which category the offset
# applies to in compact mode.
# --------------------------------------------------------------------------


def _links_handler():
    from openzim_mcp.simple_tools import SimpleToolsHandler

    ops = MagicMock()
    handler = SimpleToolsHandler(ops)
    return handler, ops


class TestLinksPaginationHonoursCursor:
    def test_cursor_kind_is_projected_from_cursor(self) -> None:
        import base64
        import json

        from openzim_mcp.cursor_decode import decode_offset_cursor

        token = (
            base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "t": "extract_article_links",
                        "s": {"o": 100, "l": 25, "ep": "C/Berlin", "k": "external"},
                    }
                ).encode()
            )
            .decode()
            .rstrip("=")
        )
        result = decode_offset_cursor(
            token, query="links in Berlin", q_emitting_tools=frozenset()
        )
        assert not isinstance(result, dict)
        assert result.offset == 100
        assert result.k == "external"

    def test_non_compact_path_passes_offset_limit_and_kind(self, tmp_path) -> None:
        handler, ops = _links_handler()
        ops.extract_article_links.return_value = "{}"
        with patch.object(
            handler, "_resolve_natural_language_path", side_effect=lambda _z, p: p
        ):
            handler._handle_links(
                "links in C/Berlin",
                str(tmp_path / "t.zim"),
                {"entry_path": "C/Berlin"},
                {
                    "compact": False,
                    "offset": 100,
                    "limit": 50,
                    "_cursor_t": "extract_article_links",
                    "_cursor_ep": "C/Berlin",
                    "_cursor_k": "internal",
                },
            )
        assert ops.extract_article_links.call_count == 1
        _args, kwargs = ops.extract_article_links.call_args
        assert kwargs.get("offset") == 100
        assert kwargs.get("limit") == 50
        assert kwargs.get("kind") == "internal"

    def test_compact_path_scopes_cursor_offset_to_its_bucket(self, tmp_path) -> None:
        """A cursor minted for the external bucket must not skip rows in the
        internal bucket too."""
        handler, ops = _links_handler()
        ops.extract_article_links_data.return_value = {
            "results": [],
            "done": True,
            "page_info": {"offset": 0, "limit": 25},
            "category_totals": {},
        }
        with patch.object(
            handler, "_resolve_natural_language_path", side_effect=lambda _z, p: p
        ):
            handler._handle_links(
                "links in C/Berlin",
                str(tmp_path / "t.zim"),
                {"entry_path": "C/Berlin"},
                {
                    "compact": True,
                    "offset": 100,
                    "_cursor_t": "extract_article_links",
                    "_cursor_ep": "C/Berlin",
                    "_cursor_k": "external",
                },
            )
        offsets = {
            kwargs.get("kind"): kwargs.get("offset")
            for _args, kwargs in ops.extract_article_links_data.call_args_list
        }
        assert offsets.get("external") == 100
        assert offsets.get("internal") == 0

    def test_compact_plain_offset_still_applies_to_both(self, tmp_path) -> None:
        """Documented offset= pagination (no cursor kind) keeps advancing
        both buckets together."""
        handler, ops = _links_handler()
        ops.extract_article_links_data.return_value = {
            "results": [],
            "done": True,
            "page_info": {"offset": 25, "limit": 25},
            "category_totals": {},
        }
        with patch.object(
            handler, "_resolve_natural_language_path", side_effect=lambda _z, p: p
        ):
            handler._handle_links(
                "links in C/Berlin",
                str(tmp_path / "t.zim"),
                {"entry_path": "C/Berlin"},
                {"compact": True, "offset": 25},
            )
        offsets = {
            kwargs.get("kind"): kwargs.get("offset")
            for _args, kwargs in ops.extract_article_links_data.call_args_list
        }
        assert offsets.get("external") == 25
        assert offsets.get("internal") == 25


# --------------------------------------------------------------------------
# Bundle sections: headings whose soup text disagrees with the rendered
# markdown (stripped [edit]/reference spans, inline links) must still be
# located — previously they were silently dropped and the preceding
# section's slice absorbed them.
# --------------------------------------------------------------------------


class TestBundleHeadingsSurviveRenderDivergence:
    @staticmethod
    def _sections(html: str):
        from bs4 import BeautifulSoup

        from openzim_mcp.bundle import _compute_section_offsets
        from openzim_mcp.content_processor import (
            _build_headings,
            select_main_content,
        )

        cp = ContentProcessor()
        soup = BeautifulSoup(html, "html.parser")
        root = select_main_content(soup)
        headings = _build_headings(root)
        rendered = cp._render_soup_to_text(root, compact=True)
        return headings, rendered, _compute_section_offsets(rendered, headings)

    def test_sup_reference_heading_is_located(self) -> None:
        html = (
            "<html><body><h1>T</h1><p>intro</p>"
            '<h2>Etymology<sup class="reference">[1]</sup></h2><p>ety body</p>'
            "<h2>Plain</h2><p>plain body</p></body></html>"
        )
        headings, _rendered, sections = self._sections(html)
        assert [h["text"] for h in headings] == ["T", "Etymology", "Plain"]
        assert [s["title"] for s in sections] == ["T", "Etymology", "Plain"]

    def test_editsection_span_heading_is_located(self) -> None:
        html = (
            "<html><body><h1>T</h1><p>intro</p>"
            '<h2>History<span class="mw-editsection">[edit]</span></h2>'
            "<p>history body</p><h2>Plain</h2><p>plain body</p></body></html>"
        )
        headings, _rendered, sections = self._sections(html)
        assert [h["text"] for h in headings] == ["T", "History", "Plain"]
        assert [s["title"] for s in sections] == ["T", "History", "Plain"]

    def test_inline_link_heading_is_located(self) -> None:
        html = (
            "<html><body><h1>T</h1><p>intro</p>"
            '<h2><a href="X">Linked</a> part</h2><p>linked body</p>'
            "<h2>Plain</h2><p>plain body</p></body></html>"
        )
        _headings, rendered, sections = self._sections(html)
        assert "## [Linked](X) part" in rendered
        titles = [s["title"] for s in sections]
        assert "Linked part" in titles
        # The located section must slice its own body and stop at its
        # sibling's heading line.
        linked_section = next(s for s in sections if s["title"] == "Linked part")
        body = rendered[linked_section["char_start"] : linked_section["char_end"]]
        assert "linked body" in body
        assert "plain body" not in body
        assert linked_section["char_end"] <= rendered.index("## Plain")
