"""Regressions from the 2026-11 sweep: archive access, caching, link graph.

Each class pins one defect that reproduced against ``main`` at e945188 and
names the inputs that exposed it.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pytest
from libzim.writer import Creator  # type: ignore[import-untyped]

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
from tests.conftest_v2_fixtures import _HtmlItem


def _ops(directory: Path, **cache_kwargs: Any) -> ZimOperations:
    cache_settings: Dict[str, Any] = {
        "enabled": True,
        "max_size": 100,
        "ttl_seconds": 3600,
    }
    cache_settings.update(cache_kwargs)
    config = OpenZimMcpConfig(
        allowed_directories=[str(directory)],
        tool_mode="advanced",
        cache=CacheConfig(**cache_settings),
        content=ContentConfig(max_content_length=10000, snippet_length=200),
        logging=LoggingConfig(level="WARNING"),
    )
    return ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache, enable_background_cleanup=False),
        ContentProcessor(snippet_length=config.content.snippet_length),
    )


def _build_article_zim(
    path: Path, *, heading: str, body: str, scraper: str = "zimwriterfs"
) -> Path:
    with Creator(str(path)).config_indexing(True, "eng") as creator:
        creator.add_metadata("Scraper", scraper)
        creator.add_item(
            _HtmlItem(
                "A/Article",
                "Article",
                f"<html><body><h1>Article</h1><h2>{heading}</h2>"
                f"<p>{body}</p></body></html>",
            )
        )
        creator.set_mainpath("A/Article")
    return path


@pytest.fixture
def refresh_after_open(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Path, Path], None]:
    """Arm a refresh that replaces ``live`` just after the next open of it.

    That is the window the defect lived in: the call already holds a handle
    on the old revision, and every ``stat()`` from then on describes the new
    one. ``os.replace`` consumes the staged file, so the refresh lands once.
    """
    import openzim_mcp.zim_operations as zim_ops_shim

    real_archive = zim_ops_shim.Archive

    def arm(live: Path, staged: Path) -> None:
        def opening_then_refreshed(path: str) -> Any:
            handle = real_archive(path)
            if Path(path) == live and staged.exists():
                os.replace(staged, live)
            return handle

        monkeypatch.setattr(zim_ops_shim, "Archive", opening_then_refreshed)

    return arm


class TestMidCallRefreshIsNotCachedAsTheNewRevision:
    """A refresh landing mid-call filed the old revision under the new token.

    The bundle, namespace-listing, preset and snippet-render caches each
    took ``archive_stat_token`` while their archive was already open, so
    the key described the file now on disk while the value came from the
    handle on the old one. Every later call then hit that entry and served
    the old revision until the TTL ran out.
    """

    def _revisions(self, tmp_path: Path, **rev1: str) -> tuple[Path, Path, Path]:
        build = tmp_path / "build"
        build.mkdir()
        live_dir = tmp_path / "live"
        live_dir.mkdir()
        rev1_path = _build_article_zim(
            build / "rev1.zim",
            heading=rev1.get("heading", "Old Heading 2025-01"),
            body=rev1.get("body", "glacier retreat in the old revision"),
            scraper=rev1.get("scraper", "zimwriterfs"),
        )
        live = live_dir / "wiki.zim"
        shutil.copy(rev1_path, live)
        return build, live, live_dir / "wiki.zim.new"

    def test_table_of_contents_serves_the_new_revision_next_call(
        self, tmp_path: Path, refresh_after_open: Callable[[Path, Path], None]
    ) -> None:
        build, live, staged = self._revisions(tmp_path)
        _build_article_zim(
            staged, heading="New Heading 2025-02", body="a longer new body"
        )
        ops = _ops(live.parent)
        refresh_after_open(live, staged)

        during = ops.get_table_of_contents_data(str(live), "A/Article")
        after = ops.get_table_of_contents_data(str(live), "A/Article")

        def headings(toc: Dict[str, Any]) -> list[str]:
            return [node["text"] for node in toc["toc"][0]["children"]]

        assert not staged.exists(), "the refresh never landed"
        assert headings(during) == ["Old Heading 2025-01"]
        assert headings(after) == ["New Heading 2025-02"]

    def test_search_snippet_serves_the_new_revision_next_call(
        self, tmp_path: Path, refresh_after_open: Callable[[Path, Path], None]
    ) -> None:
        build, live, staged = self._revisions(tmp_path)
        _build_article_zim(
            staged,
            heading="Old Heading 2025-01",
            body="glacier retreat in the new revision, which is longer",
        )
        ops = _ops(live.parent)
        refresh_after_open(live, staged)

        during = ops.search_zim_file_data(str(live), "glacier", limit=5)
        after = ops.search_zim_file_data(str(live), "glacier", limit=5)

        assert not staged.exists(), "the refresh never landed"
        assert "old revision" in during["results"][0]["snippet"]
        assert "new revision" in after["results"][0]["snippet"]
        assert "old revision" not in after["results"][0]["snippet"]

    def test_preset_follows_the_new_revision_next_call(
        self, tmp_path: Path, refresh_after_open: Callable[[Path, Path], None]
    ) -> None:
        build, live, staged = self._revisions(tmp_path, scraper="mwoffliner 1.14")
        _build_article_zim(
            staged,
            heading="Old Heading 2025-01",
            body="glacier retreat in the old revision",
            scraper="sotoki 2.1",
        )
        ops = _ops(live.parent)
        refresh_after_open(live, staged)

        during = ops.get_entry_summary_data(str(live), "A/Article")
        after = ops.get_entry_summary_data(str(live), "A/Article")

        assert not staged.exists(), "the refresh never landed"
        assert during["_meta"]["preset_applied"] == "wikipedia"
        assert after["_meta"]["preset_applied"] == "stackexchange"

    def test_namespace_listing_serves_the_new_revision_next_call(
        self,
        tmp_path: Path,
        basic_test_zim_files: Dict[str, Optional[Path]],
        real_content_zim_files: Dict[str, Optional[Path]],
        refresh_after_open: Callable[[Path, Path], None],
    ) -> None:
        # Old-scheme fixtures: a new-scheme archive (all a Creator can write)
        # never reaches the listing cache for a content namespace.
        old, new = basic_test_zim_files["withns"], real_content_zim_files["wikibooks"]
        if old is None or new is None:
            pytest.skip("withns small.zim / wikibooks fixtures not available")
        live = tmp_path / "wiki.zim"
        staged = tmp_path / "wiki.zim.new"
        shutil.copy(old, live)
        shutil.copy(new, staged)
        ops = _ops(tmp_path)
        refresh_after_open(live, staged)

        during = ops.browse_namespace_data(str(live), "A", limit=50)
        after = ops.browse_namespace_data(str(live), "A", limit=20)
        fresh = _ops(tmp_path).browse_namespace_data(str(live), "A", limit=20)

        assert not staged.exists(), "the refresh never landed"
        assert during["total"] != fresh["total"]
        assert after["total"] == fresh["total"]
        assert [r["path"] for r in after["results"]] == [
            r["path"] for r in fresh["results"]
        ]
        assert after["results"], "the new revision's rows were dropped"

    def test_a_nested_open_keys_on_the_outer_handles_revision(
        self, tmp_path: Path
    ) -> None:
        """One call holding the path open twice keys on the older handle.

        The inner handle reads the newer revision, so keying on it would file
        the outer handle's output as that revision: the defect again.
        """
        from openzim_mcp.bundle import archive_stat_token, open_archive_token
        from openzim_mcp.zim_operations import zim_archive

        build, live, staged = self._revisions(tmp_path)
        _build_article_zim(staged, heading="New Heading 2025-02", body="new")
        rev1_token = archive_stat_token(live)

        with zim_archive(live):
            os.replace(staged, live)
            rev2_token = archive_stat_token(live)
            with zim_archive(live):
                assert open_archive_token(live) == rev1_token
            assert open_archive_token(live) == rev1_token

        assert rev2_token != rev1_token
        assert open_archive_token(live) == rev2_token
