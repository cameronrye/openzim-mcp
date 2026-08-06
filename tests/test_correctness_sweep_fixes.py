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
