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


class TestInlineMediaGetsNoInventedPath:
    """A ``data:`` image's media row was given ``<source dir>/data:…``.

    ``_resolve_link_to_entry_path`` treated only ``://`` and ``//`` as not
    relative, so every inline image was joined onto the page's directory:
    175 rows on IEP ``lesniewski-logic/``, 706 KB of a 1.4 MB response, and
    not one of those paths fetches anything.
    """

    _PIXEL = (
        "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAA"
        "DUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )

    def test_a_non_navigable_src_ships_without_a_path(self, tmp_path: Path) -> None:
        from tests.test_fr_namespace_browse import _AssetItem

        zim = tmp_path / "inline.zim"
        source = "iep.utm.edu/lesniewski-logic/"
        with Creator(str(zim)).config_indexing(True, "eng") as creator:
            creator.add_item(
                _HtmlItem(
                    source,
                    "Lesniewski",
                    f'<html><body><p><img src="{self._PIXEL}" alt="formula">'
                    '<img src="about:blank" alt="unarchived">'
                    '<img src="../media/portrait.png" alt="portrait">'
                    '<img src="File:Diagram.png" alt="colon">'
                    "</p></body></html>",
                )
            )
            creator.add_item(
                _AssetItem("iep.utm.edu/media/portrait.png", "image/png", "png")
            )
            creator.set_mainpath(source)
        ops = _ops(tmp_path)

        media = ops.extract_article_links_data(str(zim), source, kind="media")
        rows = {row["alt"]: row for row in media["results"]}

        assert rows["portrait"]["path"] == "iep.utm.edu/media/portrait.png"
        # A colon is not a scheme: mwoffliner names entries ``File:…``.
        assert rows["colon"]["path"] == f"{source}File:Diagram.png"
        assert rows["formula"]["url"] == self._PIXEL
        assert "path" not in rows["formula"], rows["formula"]
        assert "path" not in rows["unarchived"], rows["unarchived"]


class TestListingFollowsAFileChangedInPlace:
    """The archive listing was keyed on the set of paths alone.

    A download that completes in place keeps its path, so ``zim_health``
    went on listing it as a truncated, unreadable file while its own
    warnings (computed fresh) said nothing was wrong. The key also lacked
    the render epoch, so a persisted listing outlived a release that
    changed what a row says.
    """

    @pytest.mark.asyncio
    async def test_zim_health_agrees_with_itself_once_a_download_completes(
        self, tmp_path: Path, real_content_zim_files: Dict[str, Optional[Path]]
    ) -> None:
        from openzim_mcp.server import OpenZimMcpServer

        source = real_content_zim_files.get("wikibooks")
        if source is None:
            pytest.skip("wikibooks fixture not available")
        data = source.read_bytes()
        live = tmp_path / "wikibooks.zim"
        live.write_bytes(data[: len(data) // 2])
        server = OpenZimMcpServer(
            OpenZimMcpConfig(
                allowed_directories=[str(tmp_path)],
                tool_mode="advanced",
                cache=CacheConfig(enabled=True),
            )
        )
        health = server.mcp._tool_manager._tools["zim_health"].fn

        partial = await health()
        with live.open("ab") as handle:
            handle.write(data[len(data) // 2 :])
        complete = await health()

        assert [f["readable"] for f in partial["loaded_archives"]] == [False]
        assert any("Truncated" in w for w in partial["health"]["warnings"])
        assert [f["readable"] for f in complete["loaded_archives"]] == [True]
        assert "warning" not in complete["loaded_archives"][0]
        assert complete["loaded_archives"][0]["size_bytes"] == len(data)
        assert not complete["health"].get("warnings")

    def test_a_render_epoch_bump_rescans_the_listing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "alpha.zim").write_text("alpha")
        ops = _ops(tmp_path)
        scans: list[int] = []
        real_scan = ops._scan_zim_files

        def counting(grouped: Any) -> Any:
            scans.append(1)
            return real_scan(grouped)

        monkeypatch.setattr(ops, "_scan_zim_files", counting)

        ops.list_zim_files_data()
        ops.list_zim_files_data()
        assert len(scans) == 1, "an unchanged directory must stay cached"

        monkeypatch.setattr("openzim_mcp.bundle._RENDER_EPOCH", "r-next")
        ops.list_zim_files_data()
        assert len(scans) == 2


class TestAHeaderStubIsNotListedAsReadable:
    """A file shorter than the 80-byte header passed the signature probe.

    ``has_zim_signature`` saw the magic, found no ``checksumPos`` to compare
    (the header is cut off before it) and answered True, so the corpus's own
    ``invalid.smaller_than_header.zim`` was listed readable with no warning
    while every open of it failed. ``is_truncated_zim`` already called it a
    truncated download; it was simply never asked.
    """

    @pytest.mark.asyncio
    async def test_zim_health_calls_the_stub_a_truncated_download(
        self, tmp_path: Path, zim_test_data_dir: Optional[Path]
    ) -> None:
        from openzim_mcp.server import OpenZimMcpServer
        from openzim_mcp.zim.archive import TRUNCATED_ZIM_WARNING

        withns = zim_test_data_dir / "withns" if zim_test_data_dir else None
        if withns is None or not (withns / "invalid.smaller_than_header.zim").exists():
            pytest.skip("zim-testing-suite withns fixtures not available")
        shutil.copy(withns / "invalid.smaller_than_header.zim", tmp_path / "stub.zim")
        shutil.copy(withns / "small.zim", tmp_path / "small.zim")
        server = OpenZimMcpServer(
            OpenZimMcpConfig(
                allowed_directories=[str(tmp_path)],
                tool_mode="advanced",
                cache=CacheConfig(enabled=False),
            )
        )

        out = await server.mcp._tool_manager._tools["zim_health"].fn()
        rows = {row["name"]: row for row in out["loaded_archives"]}

        assert (tmp_path / "stub.zim").stat().st_size < 80
        assert rows["stub.zim"]["readable"] is False
        assert rows["stub.zim"]["warning"] == TRUNCATED_ZIM_WARNING
        assert any(
            w.startswith("Truncated .zim file") and "stub.zim" in w
            for w in out["health"]["warnings"]
        ), out["health"]["warnings"]
        # The full archive beside it is untouched.
        assert rows["small.zim"]["readable"] is True
        assert "warning" not in rows["small.zim"]


class TestASymlinkedArchiveGetsTheSidecarTheServerReads:
    """The CLI built ``<link>.linkgraph.sqlite``; the server reads ``<target>``.

    The server resolves symlinks before deriving the sidecar path, while
    ``openzim-mcp build link-graph`` and ``build_link_graph`` used the path
    as given. A build through a stable ``wikipedia.zim`` symlink succeeded
    and inbound still answered "build a link-graph sidecar".
    """

    def test_a_build_through_the_symlink_serves_inbound(
        self,
        tmp_path: Path,
        wikibooks_copy: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        from openzim_mcp.cli.build import build_main

        link = tmp_path / "wikibooks.zim"
        link.symlink_to(wikibooks_copy.name)
        beside_target = Path(f"{wikibooks_copy.resolve()}.linkgraph.sqlite")

        assert build_main(["link-graph", str(link), "--quiet"]) == 0

        assert capsys.readouterr().out.startswith(f"built {beside_target}:")
        assert beside_target.is_file()
        assert not Path(f"{link}.linkgraph.sqlite").exists()
        ops = _ops(tmp_path)
        inbound = ops.get_inbound_links_data(str(link), "A/Эспэранта.html")
        assert inbound["total"] > 0
        assert ops.get_archive_validation_data(str(link))["has_link_graph"] is True


class TestConcurrentLinkGraphBuildsKeepTheirOwnFiles:
    """Every build of one sidecar wrote the same ``<sidecar>.tmp``.

    A second build removed the first's half-written file and wrote its own
    under that name, so the first published the second's partial file as
    its result and the second's rename then raised FileNotFoundError. A
    build that failed also left its ``.tmp`` behind.
    """

    def test_each_build_publishes_its_own_file(self, tmp_path: Path) -> None:
        import threading

        from openzim_mcp.linkgraph.builder import build_from_link_stream
        from openzim_mcp.linkgraph.reader import LinkGraphReader, read_sidecar_meta

        archive = str(tmp_path / "x.zim")
        out = f"{archive}.linkgraph.sqlite"
        a_mid, b_mid, a_done, a_checked = (threading.Event() for _ in range(4))
        results: Dict[str, Any] = {}

        def stream_a() -> Any:
            yield ("A/src", [("A/t1", "one")])
            a_mid.set()
            b_mid.wait(5)  # B has started its own file meanwhile
            yield ("A/src2", [("A/t2", "two")])

        def stream_b() -> Any:
            yield ("B/src", [("B/t1", "uno")])
            b_mid.set()
            a_done.wait(5)
            a_checked.wait(5)  # hold B half-written while A's file is read
            yield ("B/src2", [("B/t2", "dos")])

        def run(name: str, stream: Any) -> None:
            try:
                results[name] = build_from_link_stream(
                    out, archive_uuid=f"uuid-{name}", link_stream=stream, force=True
                )
            except Exception as e:  # recorded, asserted below
                results[name] = e
            finally:
                if name == "A":
                    a_done.set()

        build_a = threading.Thread(target=run, args=("A", stream_a()))
        build_a.start()
        a_mid.wait(5)
        build_b = threading.Thread(target=run, args=("B", stream_b()))
        build_b.start()
        build_a.join(10)
        published_by_a = read_sidecar_meta(archive)
        reader = LinkGraphReader.open_for(archive, live_archive_uuid="uuid-A")
        a_checked.set()
        build_b.join(10)

        assert not isinstance(results["A"], Exception), results["A"]
        assert published_by_a is not None
        assert published_by_a["archive_uuid"] == "uuid-A"
        assert reader is not None
        reader.close()
        assert not isinstance(results["B"], Exception), results["B"]
        assert read_sidecar_meta(archive)["archive_uuid"] == "uuid-B"
        assert sorted(p.name for p in tmp_path.iterdir()) == [Path(out).name]

    def test_a_failed_build_leaves_nothing_behind(self, tmp_path: Path) -> None:
        from openzim_mcp.linkgraph.builder import build_from_link_stream
        from openzim_mcp.linkgraph.reader import read_sidecar_meta

        archive = str(tmp_path / "x.zim")
        out = f"{archive}.linkgraph.sqlite"
        build_from_link_stream(
            out, archive_uuid="good", link_stream=iter([("A/s", [("A/t", "t")])])
        )

        def failing() -> Any:
            yield ("A/s", [("A/t", "t")])
            raise RuntimeError("entry read failed")

        with pytest.raises(RuntimeError):
            build_from_link_stream(
                out, archive_uuid="bad", link_stream=failing(), force=True
            )

        assert sorted(p.name for p in tmp_path.iterdir()) == [Path(out).name]
        assert read_sidecar_meta(archive)["archive_uuid"] == "good"

    def test_the_sidecar_keeps_the_permissions_sqlite_gives_it(
        self, tmp_path: Path
    ) -> None:
        """Not ``mkstemp``'s 0600: the Docker image reads it as ``appuser``."""
        from openzim_mcp.linkgraph.builder import build_from_link_stream

        out = tmp_path / "x.zim.linkgraph.sqlite"
        umask = os.umask(0o022)
        try:
            build_from_link_stream(
                str(out), archive_uuid="u", link_stream=iter([("A/s", [])])
            )
        finally:
            os.umask(umask)

        assert out.stat().st_mode & 0o777 == 0o644
