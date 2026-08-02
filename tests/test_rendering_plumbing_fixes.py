"""Regression tests for the rendering + plumbing fix batch.

Covers:

* P12 — backend ``OpenZimMcpValidationError`` rendered as ``**Article not
  found**`` with four dead-end recovery commands, plus the ``limit`` range
  mismatch between ``zim_query`` (1..1000) and the intent backends (500 / 100)
  that produced it.
* P16 — ``was_truncated`` derived from a length comparison, which is False
  whenever the appended truncation note is longer than the overflow.
* P17 — ``compact_budget="2000"`` (a numeric string, which pydantic's smart
  union keeps as ``str``) silently resolving to the medium profile.
* P18 — ``render_search_all`` rendering 5 hits under a header claiming N.
* P21 — ``compact_structure_payload`` attaching the first duplicate heading's
  summary to every later heading of the same title.
* P23 — ``EntryBundle`` keeping the pre-redirect path, so relative hrefs
  resolved against the wrong directory.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from openzim_mcp.bundle import extract_entry_bundle
from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.compact_format import _CompactFormatMixin
from openzim_mcp.compact_renderers import compact_structure_payload, render_search_all
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.exceptions import OpenZimMcpArchiveError, OpenZimMcpValidationError
from openzim_mcp.security import PathValidator
from openzim_mcp.simple_tools import SimpleToolsHandler
from openzim_mcp.zim_operations import ZimOperations

# ===========================================================================
# P12 — validation errors must not be rendered as "Article not found"
# ===========================================================================


class TestValidationErrorsAreNotArticleNotFound:
    """A limit-range rejection means the ARGUMENT was wrong, not the article.

    Pre-fix every handler funnelled ``OpenZimMcpValidationError`` into the
    shared ``except Exception`` and reported ``**Article not found: `X`**``
    with four recovery commands that could never help — the article existed.
    """

    @staticmethod
    def _ops() -> MagicMock:
        ops = MagicMock()
        ops.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        ops.config.meta.footer_enabled = False
        return ops

    @pytest.mark.parametrize(
        "query,attr",
        [
            ("show structure of Biology", "get_article_structure"),
            ("table of contents for Biology", "get_table_of_contents"),
            ("summary of Biology", "get_entry_summary"),
            ("links in Biology", "extract_article_links"),
            ("get article Biology", "get_zim_entry"),
            ("articles related to Biology", "get_related_articles"),
        ],
    )
    def test_validation_error_renders_invalid_request(
        self, query: str, attr: str
    ) -> None:
        ops = self._ops()
        getattr(ops, attr).side_effect = OpenZimMcpValidationError(
            "limit must be between 1 and 500 (provided: 1000)"
        )
        handler = SimpleToolsHandler(ops)
        out = handler.handle_zim_query(query, "/x.zim")
        assert isinstance(out, str)
        assert "Article not found" not in out, out[:400]
        assert "**Invalid Request**" in out, out[:400]
        # The real constraint must be named, not paraphrased away.
        assert "1 and 500" in out, out[:400]

    @pytest.mark.parametrize(
        "query,attr",
        [
            ("show structure of Biology", "get_article_structure"),
            ("table of contents for Biology", "get_table_of_contents"),
            ("summary of Biology", "get_entry_summary"),
            ("links in Biology", "extract_article_links"),
            ("get article Biology", "get_zim_entry"),
            ("articles related to Biology", "get_related_articles"),
        ],
    )
    def test_plain_exceptions_keep_the_not_found_envelope(
        self, query: str, attr: str
    ) -> None:
        """The trailing ``except Exception`` stays broad: a bare ``Exception``
        and an ``OpenZimMcpArchiveError`` genuinely do mean "not found"."""
        for exc in (
            Exception("Entry not found: Biology"),
            OpenZimMcpArchiveError("Cannot find entry"),
        ):
            ops = self._ops()
            getattr(ops, attr).side_effect = exc
            handler = SimpleToolsHandler(ops)
            out = handler.handle_zim_query(query, "/x.zim")
            assert isinstance(out, str)
            assert "Article not found" in out, out[:400]
            assert "**Invalid Request**" not in out


class TestIntentLimitRangeIsCoherent:
    """P12 fix (b): ``zim_query`` documents ``limit`` 1..1000 while the links
    backend caps at 500 and the related backend at 100. Clamp at the handler
    boundary and SAY SO rather than letting the backend reject the call.
    """

    @staticmethod
    def _ops() -> MagicMock:
        ops = MagicMock()
        ops.list_zim_files_data.return_value = [{"path": "/x.zim"}]
        ops.config.meta.footer_enabled = False
        ops.extract_article_links_data.return_value = {
            "title": "Biology",
            "path": "A/Biology",
            "results": [],
            "category_totals": {"internal": 0, "external": 0},
        }
        ops.get_related_articles_data.return_value = {
            "path": "A/Biology",
            "results": [],
        }
        return ops

    def test_links_limit_1000_is_clamped_not_rejected(self) -> None:
        ops = self._ops()
        handler = SimpleToolsHandler(ops)
        out = handler.handle_zim_query(
            "links in Biology", "/x.zim", options={"compact": True, "limit": 1000}
        )
        assert isinstance(out, str)
        assert "Article not found" not in out, out[:400]
        assert "maximum of 500" in out, out[:400]
        _, kwargs = ops.extract_article_links_data.call_args
        assert kwargs["limit"] == 500

    def test_related_limit_1000_is_clamped_not_rejected(self) -> None:
        ops = self._ops()
        handler = SimpleToolsHandler(ops)
        out = handler.handle_zim_query(
            "articles related to Biology",
            "/x.zim",
            options={"compact": True, "limit": 1000},
        )
        assert isinstance(out, str)
        assert "Article not found" not in out, out[:400]
        assert "maximum of 100" in out, out[:400]
        _, kwargs = ops.get_related_articles_data.call_args
        assert kwargs["limit"] == 100

    def test_in_range_limit_is_untouched_and_unannotated(self) -> None:
        ops = self._ops()
        handler = SimpleToolsHandler(ops)
        out = handler.handle_zim_query(
            "links in Biology", "/x.zim", options={"compact": True, "limit": 30}
        )
        assert isinstance(out, str)
        assert "maximum of" not in out
        _, kwargs = ops.extract_article_links_data.call_args
        assert kwargs["limit"] == 30


# ===========================================================================
# P16 — was_truncated must key on the cap, not on rendered lengths
# ===========================================================================


class TestTruncationFlagAgainstCap:
    """``truncate_content`` appends a ~150-char note, so an overflow smaller
    than the note left ``len(truncated) < len(content)`` False: no
    ``_meta.truncated``, no ``more_at_offset``, no ``_total_chars`` — while
    the body visibly carried the truncation notice.
    """

    @pytest.fixture
    def ops(self, real_content_zim_files: Dict[str, Optional[Path]]) -> ZimOperations:
        zim = real_content_zim_files.get("wikipedia_climate")
        if zim is None:
            pytest.skip("real content ZIM fixtures not available")
        cfg = OpenZimMcpConfig(
            allowed_directories=[str(zim.parent)],
            cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
            content=ContentConfig(max_content_length=100_000, snippet_length=100),
            logging=LoggingConfig(level="ERROR"),
        )
        return ZimOperations(
            cfg,
            PathValidator(cfg.allowed_directories),
            OpenZimMcpCache(cfg.cache),
            ContentProcessor(snippet_length=100),
        )

    @pytest.fixture
    def zim_path(self, real_content_zim_files: Dict[str, Optional[Path]]) -> str:
        zim = real_content_zim_files.get("wikipedia_climate")
        if zim is None:
            pytest.skip("real content ZIM fixtures not available")
        return str(zim)

    def test_overflow_smaller_than_the_note_is_still_truncated(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        entry = "A/Climate_change"
        full = ops.get_zim_entry_data(zim_path, entry, max_content_length=10_000_000)
        body_len = len(str(full["content"]))
        assert body_len > 200

        # 50 chars of overflow — far shorter than the appended note, which is
        # exactly the case the length comparison got backwards.
        cap = body_len - 50
        res = ops.get_zim_entry_data(zim_path, entry, max_content_length=cap)
        meta: Dict[str, Any] = res["_meta"]  # type: ignore[typeddict-item]
        assert meta["truncated"] is True, meta
        assert meta["more_at_offset"] == cap, meta

    def test_body_within_the_cap_is_not_flagged(
        self, ops: ZimOperations, zim_path: str
    ) -> None:
        entry = "A/Climate_change"
        res = ops.get_zim_entry_data(zim_path, entry, max_content_length=10_000_000)
        meta: Dict[str, Any] = res["_meta"]  # type: ignore[typeddict-item]
        assert meta.get("truncated") is not True
        assert "more_at_offset" not in meta

    def test_main_page_truncation_flag_keys_on_the_cap(
        self,
        ops: ZimOperations,
        zim_path: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Same defect at ``zim/archive.py`` for the main-page path."""
        import openzim_mcp.zim.archive as archive_mod

        full = ops.get_main_page_data(zim_path)
        body_len = len(str(full["content"]))
        assert body_len > 200
        monkeypatch.setattr(
            archive_mod, "DEFAULT_MAIN_PAGE_TRUNCATION", body_len - 50, raising=True
        )
        ops.cache.clear()
        res = ops.get_main_page_data(zim_path)
        meta: Dict[str, Any] = res["_meta"]  # type: ignore[typeddict-item]
        assert meta["truncated"] is True, meta
        assert meta["total_chars"] == body_len, meta


# ===========================================================================
# P17 — a numeric string is a budget, not an unknown profile name
# ===========================================================================


class TestCompactBudgetNumericStrings:
    """``compact_budget`` is declared ``Optional[Union[str, int]]``, and
    pydantic's smart union keeps ``"2000"`` a ``str`` — which fell through the
    profile lookup to the medium default, doubling the response the caller
    asked to cap.
    """

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2000", 2000),
            ("  3000 ", 3000),
            ("-100", 500),  # clamped to the same [500, 64_000] bounds as int
            ("1000000", 64_000),
        ],
    )
    def test_numeric_strings_resolve_and_clamp(self, raw: str, expected: int) -> None:
        assert _CompactFormatMixin._resolve_compact_budget(raw) == expected

    @pytest.mark.parametrize("raw", ["1e9", "3.5", "banana", ""])
    def test_non_integer_strings_keep_the_medium_default(self, raw: str) -> None:
        medium = _CompactFormatMixin._COMPACT_BUDGET_PROFILES["medium"]
        assert _CompactFormatMixin._resolve_compact_budget(raw) == medium

    def test_profile_names_still_win_over_the_int_parse(self) -> None:
        for name, value in _CompactFormatMixin._COMPACT_BUDGET_PROFILES.items():
            assert _CompactFormatMixin._resolve_compact_budget(name) == value
            assert _CompactFormatMixin._resolve_compact_budget(name.upper()) == value


# ===========================================================================
# P18 — the header must not claim more hits than the body renders
# ===========================================================================


class TestSearchAllRendersEveryHit:
    def test_twenty_hits_render_twenty_bullets(self) -> None:
        results = [{"title": f"T{i}", "path": f"A/T{i}"} for i in range(20)]
        out = render_search_all(
            {
                "files_with_hits": 1,
                "files_searched": 1,
                "results": [
                    {
                        "name": "wikipedia",
                        "result": {"results": results, "total": 4321},
                    }
                ],
            },
            "berlin",
        )
        assert "— 20 hits" in out
        bullets = [ln for ln in out.splitlines() if ln.startswith("- **T")]
        assert len(bullets) == 20, out
        # Pre-fix hits 6..20 were rendered nowhere and reachable by nothing.
        assert "- **T19** — `A/T19`" in out


# ===========================================================================
# P21 — duplicate headings must not share the first one's summary
# ===========================================================================


class TestCompactStructureDuplicateHeadings:
    def test_duplicate_headings_get_distinct_summaries(self) -> None:
        payload = {
            "title": "C++",
            "path": "A/C++",
            "headings": [
                {"level": 2, "text": "See also", "id": "h1"},
                {"level": 2, "text": "Syntax", "id": "h2"},
                {"level": 3, "text": "See also", "id": "h3"},
            ],
            "sections": [
                {"title": "See also", "content_preview": "Top-level pointers."},
                {"title": "Syntax", "content_preview": "Declarations and blocks."},
                {"title": "See also", "content_preview": "Syntax-specific pointers."},
            ],
        }
        out = json.loads(compact_structure_payload(payload))
        summaries = [h.get("summary") for h in out["headings"]]
        assert summaries[0] == "Top-level pointers."
        assert summaries[1] == "Declarations and blocks."
        # Pre-fix this was the FIRST "See also" body.
        assert summaries[2] == "Syntax-specific pointers."

    def test_falls_back_to_the_title_map_when_lists_desync(self) -> None:
        """A shorter ``sections`` list means the index join is untrustworthy;
        the title-keyed map must still supply what it can."""
        payload = {
            "title": "X",
            "path": "A/X",
            "headings": [
                {"level": 2, "text": "Alpha", "id": "h1"},
                {"level": 2, "text": "Beta", "id": "h2"},
            ],
            "sections": [{"title": "Beta", "content_preview": "Beta body."}],
        }
        out = json.loads(compact_structure_payload(payload))
        by_text = {h["text"]: h.get("summary") for h in out["headings"]}
        assert by_text["Beta"] == "Beta body."
        assert by_text["Alpha"] is None


# ===========================================================================
# P23 — the bundle must key on the POST-redirect path
# ===========================================================================


class _FakeItem:
    def __init__(self, path: str, html: str) -> None:
        self.path = path
        self.mimetype = "text/html"
        self.content = html.encode("utf-8")


class _FakeEntry:
    def __init__(self, title: str, item: _FakeItem) -> None:
        self.title = title
        self._item = item

    def get_item(self) -> _FakeItem:
        return self._item


class _FakeArchive:
    def __init__(self, entry: _FakeEntry) -> None:
        self._entry = entry

    def get_entry_by_path(self, path: str) -> _FakeEntry:
        return self._entry


class TestBundleUsesResolvedPath:
    """``entry.get_item()`` transparently follows redirects, so ``item.path``
    names the entry actually SERVED — and the relative hrefs in the returned
    HTML are relative to THAT directory. Keeping the caller's pre-redirect
    path made ``extract_article_links_data``'s ``payload["path"]`` (and hence
    ``get_related_articles_data``) resolve siblings against the wrong dir.
    """

    def test_redirect_target_path_is_stored(self) -> None:
        item = _FakeItem("sub/target", "<html><body><p>Body</p></body></html>")
        archive = _FakeArchive(_FakeEntry("Target", item))
        bundle = extract_entry_bundle(
            archive,  # type: ignore[arg-type]
            "alias",
            content_processor=ContentProcessor(snippet_length=100),
        )
        assert bundle["entry_path"] == "sub/target"

    def test_non_redirect_path_is_unchanged(self) -> None:
        item = _FakeItem("A/Berlin", "<html><body><p>Body</p></body></html>")
        archive = _FakeArchive(_FakeEntry("Berlin", item))
        bundle = extract_entry_bundle(
            archive,  # type: ignore[arg-type]
            "A/Berlin",
            content_processor=ContentProcessor(snippet_length=100),
        )
        assert bundle["entry_path"] == "A/Berlin"

    def test_magicmock_item_path_falls_back_to_the_caller_path(self) -> None:
        """The ``isinstance(served, str)`` guard is load-bearing: the mock
        archives used across the suite expose a ``MagicMock`` ``item.path``."""
        archive = MagicMock()
        entry = archive.get_entry_by_path.return_value
        entry.title = "Berlin"
        item = entry.get_item.return_value
        item.mimetype = "text/html"
        item.content = b"<html><body><p>Body</p></body></html>"
        bundle = extract_entry_bundle(
            archive,
            "A/Berlin",
            content_processor=ContentProcessor(snippet_length=100),
        )
        assert bundle["entry_path"] == "A/Berlin"
