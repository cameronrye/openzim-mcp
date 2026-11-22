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


@pytest.fixture
def iep_like_zim(tmp_path: Path) -> Path:
    """The warc2zim-shaped archive ``test_fr_self_absolute_links`` builds."""
    from libzim.writer import Hint  # type: ignore[import-untyped]

    import tests.test_fr_self_absolute_links as fid17

    out = tmp_path / "iep_like.zim"
    with Creator(str(out)).config_indexing(True, "eng") as creator:
        for path, (title, body) in fid17._PAGES.items():
            creator.add_item(_HtmlItem(path, title, body))
        for src, dst in fid17._REDIRECTS.items():
            creator.add_redirection(src, src, dst, {Hint.FRONT_ARTICLE: 1})
        creator.set_mainpath(f"{fid17.HOST}/aristotle/")
    return out


class TestSameHostLinksReachRelatedAndInbound:
    """fid 17 promoted same-host absolute links on the outbound side only.

    ``https://www.iep.utm.edu/aris-log/`` became an internal row with a
    ``path``, but related re-resolved each row's ``url`` (``None`` for
    anything with ``://``) and the sidecar builder read only the anchors
    the classifier calls internal. On the real IEP ``aristotle/`` page
    related returned 3 of 9 neighbours and inbound for ``lyceum/`` and
    ``aristotle-logic/`` never listed Aristotle.
    """

    _SOURCE = "iep.utm.edu/aristotle/"

    def test_related_ranks_the_promoted_rows(self, iep_like_zim: Path) -> None:
        ops = _ops(iep_like_zim.parent)

        related = ops.get_related_articles_data(str(iep_like_zim), self._SOURCE)
        paths = [row["path"] for row in related["results"]]

        assert "iep.utm.edu/aristotle-logic/" in paths, paths
        assert "iep.utm.edu/ibn-rushd-averroes/" in paths, paths
        assert "iep.utm.edu/plato/" in paths, paths
        # The relative link that always worked, and nothing invented for the
        # same-host link the archive cannot serve.
        assert "iep.utm.edu/lyceum/" in paths, paths
        assert not any("never-scraped" in p for p in paths), paths
        assert related["total"] == 4

    def test_inbound_lists_a_same_host_linker(self, iep_like_zim: Path) -> None:
        from openzim_mcp.linkgraph.builder import build_link_graph

        build_link_graph(str(iep_like_zim))
        ops = _ops(iep_like_zim.parent)

        def linkers(target: str) -> list[str]:
            page = ops.get_inbound_links_data(str(iep_like_zim), target)
            return [row["path"] for row in page["results"]]

        assert linkers("iep.utm.edu/aristotle-logic/") == [self._SOURCE]
        assert linkers("iep.utm.edu/ibn-rushd-averroes/") == [self._SOURCE]
        assert linkers("iep.utm.edu/plato/") == [self._SOURCE]
        assert linkers("iep.utm.edu/lyceum/") == [self._SOURCE]
        # Never promoted, so never indexed: the archive and the index have
        # both not heard of it.
        from openzim_mcp.exceptions import OpenZimMcpArchiveError

        with pytest.raises(OpenZimMcpArchiveError):
            linkers("iep.utm.edu/never-scraped/")

    def test_a_same_host_link_to_an_asset_stays_out_of_the_index(
        self, tmp_path: Path
    ) -> None:
        """Related drops asset targets, so the promoted edges must too."""
        from openzim_mcp.linkgraph.builder import build_link_graph
        from tests.test_fr_namespace_browse import _AssetItem

        zim = tmp_path / "iep_assets.zim"
        source, lyceum = "iep.utm.edu/plato/", "iep.utm.edu/lyceum/"
        image = "iep.utm.edu/wp-content/media/plato.jpg"
        with Creator(str(zim)).config_indexing(True, "eng") as creator:
            creator.add_item(
                _HtmlItem(
                    source,
                    "Plato",
                    f'<html><body><p><a href="https://www.{image}">portrait</a>'
                    f' and <a href="https://www.{lyceum}">the Lyceum</a>'
                    "</p></body></html>",
                )
            )
            creator.add_item(_HtmlItem(lyceum, "The Lyceum", "<p>Lyceum.</p>"))
            creator.add_item(_AssetItem(image, "image/jpeg", "not really a jpeg"))
            creator.set_mainpath(source)
        build_link_graph(str(zim))
        ops = _ops(tmp_path)

        def linkers(target: str) -> list[str]:
            page = ops.get_inbound_links_data(str(zim), target)
            return [row["path"] for row in page["results"]]

        assert linkers(lyceum) == [source]
        assert linkers(image) == []

    def test_a_sidecar_built_before_the_fix_is_reported_stale(
        self, iep_like_zim: Path
    ) -> None:
        """A 3.4.1 sidecar lacks these edges, so it must not pass as current."""
        import sqlite3

        from openzim_mcp.linkgraph.builder import build_link_graph
        from openzim_mcp.linkgraph.reader import LinkGraphUnavailable

        build_link_graph(str(iep_like_zim))
        ops = _ops(iep_like_zim.parent)
        current = ops.get_archive_validation_data(str(iep_like_zim))
        assert current["link_graph"]["is_stale"] is False, current

        conn = sqlite3.connect(f"{iep_like_zim}.linkgraph.sqlite")
        with conn:
            conn.execute("UPDATE meta SET value = '3' WHERE key = 'schema_version'")
        conn.close()
        ops = _ops(iep_like_zim.parent)

        stale = ops.get_archive_validation_data(str(iep_like_zim))
        assert stale["link_graph"]["is_stale"] is True, stale
        with pytest.raises(LinkGraphUnavailable):
            ops.get_inbound_links_data(str(iep_like_zim), "iep.utm.edu/lyceum/")


@pytest.fixture
def wikibooks_copy(
    tmp_path: Path, real_content_zim_files: Dict[str, Optional[Path]]
) -> Path:
    source = real_content_zim_files.get("wikibooks")
    if source is None:
        pytest.skip("wikibooks fixture not available")
    copy = tmp_path / "wb.zim"
    shutil.copy(source, copy)
    return copy


class TestCachedValidationFollowsTheSidecar:
    """``zim_health(path)`` cached the sidecar report with the archive verdict.

    The key is the archive's stat token, which a sidecar build or delete
    does not move: a sidecar built after the first call stayed
    ``has_link_graph: false`` while inbound answered, and a deleted one
    stayed ``true`` (``node_count: 66``) while inbound refused.
    """

    @pytest.fixture
    def integrity_checks(self, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
        """Record each ``Archive.check()`` pass, the cost the cache saves."""
        import openzim_mcp.zim.archive as archive_mod

        calls: list[Path] = []
        real = archive_mod.check_archive_integrity

        def counting(path: Path) -> bool:
            calls.append(path)
            return real(path)

        monkeypatch.setattr(archive_mod, "check_archive_integrity", counting)
        return calls

    def test_a_sidecar_built_after_the_first_call_is_reported(
        self, wikibooks_copy: Path, integrity_checks: list[Path]
    ) -> None:
        from openzim_mcp.linkgraph.builder import build_link_graph

        ops = _ops(wikibooks_copy.parent)
        before = ops.get_archive_validation_data(str(wikibooks_copy))
        build_link_graph(str(wikibooks_copy))
        after = ops.get_archive_validation_data(str(wikibooks_copy))

        assert before["has_link_graph"] is False
        assert after["has_link_graph"] is True
        assert after["link_graph"]["is_stale"] is False
        assert after["link_graph"]["node_count"] == 66
        # The integrity verdict is still the cached one.
        assert len(integrity_checks) == 1
        assert after["is_valid"] is True

    def test_a_deleted_sidecar_is_no_longer_reported(
        self, wikibooks_copy: Path, integrity_checks: list[Path]
    ) -> None:
        from openzim_mcp.linkgraph.builder import build_link_graph

        build_link_graph(str(wikibooks_copy))
        ops = _ops(wikibooks_copy.parent)
        before = ops.get_archive_validation_data(str(wikibooks_copy))
        os.remove(f"{wikibooks_copy}.linkgraph.sqlite")
        after = ops.get_archive_validation_data(str(wikibooks_copy))

        assert before["has_link_graph"] is True
        assert after["has_link_graph"] is False
        assert "link_graph" not in after
        assert len(integrity_checks) == 1
        assert after["uuid"] == before["uuid"]

    def test_a_verdict_cached_by_the_previous_release_is_not_reused(
        self, wikibooks_copy: Path
    ) -> None:
        """3.4.1 cached the sidecar report inside the verdict; with
        persistence on, a restored entry would carry it past the fix."""
        from openzim_mcp.bundle import archive_stat_token

        ops = _ops(wikibooks_copy.parent)
        validated = ops._validate_zim_path(str(wikibooks_copy))
        ops.cache.set(
            f"validation_data:{validated}:{archive_stat_token(validated)}",
            {
                "uuid": "restored",
                "is_valid": True,
                "has_link_graph": True,
                "link_graph": {"node_count": 66, "is_stale": False},
            },
        )

        out = ops.get_archive_validation_data(str(wikibooks_copy))

        assert out["has_link_graph"] is False
        assert "link_graph" not in out
        assert out["uuid"] != "restored"
