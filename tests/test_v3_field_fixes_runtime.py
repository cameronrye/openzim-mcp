"""v3.0.0 field-defect fixes — ``runtime`` workstream.

Covers the three runtime defects from the 2026-08-19 real-world sweep:

* D01 — ``zim_health()`` listed unreadable garbage ``*.zim`` files as
  ``loaded_archives`` and counted them in ``zim_files_found`` while staying
  ``healthy``. The scan now cheap-validates the ZIM signature and marks bad
  files instead of presenting them as loaded.
* D64 — ``Archive.check()`` holds the GIL inside python-libzim, so running it
  on a worker thread still froze the event loop. Validation now runs in a
  separate process.
* D65 — one ``limit=100`` search inserted ~100 per-result snippet entries and
  flushed every other response out of the count-capped cache while the byte
  budget sat at 2%. Per-result fragments no longer count toward ``max_size``.
"""

from __future__ import annotations

import os
import shutil
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pytest

from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import CacheConfig, LoggingConfig, OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.exceptions import OpenZimMcpArchiveError
from openzim_mcp.security import PathValidator
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.server_state import _build_health_report
from openzim_mcp.zim import archive as archive_mod
from openzim_mcp.zim_operations import ZimOperations
from tests.conftest_v2_fixtures import make_zim_ops

GARBAGE = b"not a zim"


def _dir_with(tmp_path: Path, real_zim: Path | None, garbage_names: list[str]) -> Path:
    """Populate ``tmp_path`` with an optional real ZIM plus garbage ``.zim`` files."""
    if real_zim is not None:
        shutil.copy(real_zim, tmp_path / real_zim.name)
    for name in garbage_names:
        (tmp_path / name).write_bytes(GARBAGE)
    return tmp_path


def _server_for(directory: Path) -> OpenZimMcpServer:
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(directory)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=False),
            logging=LoggingConfig(level="WARNING"),
        )
    )


# ---------------------------------------------------------------------------
# D01 — garbage *.zim files must not masquerade as loaded, healthy archives
# ---------------------------------------------------------------------------


class TestD01UnreadableZimFilesAreFlagged:
    def test_listing_marks_garbage_zim_unreadable(
        self, tmp_path: Path, v2_phase_a_zim: Path
    ) -> None:
        directory = _dir_with(tmp_path, v2_phase_a_zim, ["fake.zim"])
        ops = make_zim_ops(str(directory))

        by_name = {e["name"]: e for e in ops.list_zim_files_data()}
        # Marking, not silent exclusion: the operator must still see the file.
        assert set(by_name) == {v2_phase_a_zim.name, "fake.zim"}

        real = by_name[v2_phase_a_zim.name]
        assert real["readable"] is True
        assert "warning" not in real

        fake = by_name["fake.zim"]
        assert fake["readable"] is False
        assert "warning" in fake
        assert "ZIM" in fake["warning"]

    def test_listing_marks_truncated_header_unreadable(self, tmp_path: Path) -> None:
        # Shorter than the 4-byte signature: must be flagged, not crash the scan.
        (tmp_path / "stub.zim").write_bytes(b"ZI")
        ops = make_zim_ops(str(tmp_path))
        (entry,) = ops.list_zim_files_data()
        assert entry["readable"] is False

    def test_health_counts_only_readable_files_and_warns(
        self, tmp_path: Path, v2_phase_a_zim: Path
    ) -> None:
        directory = _dir_with(tmp_path, v2_phase_a_zim, ["fake.zim"])
        health = _build_health_report(_server_for(directory))

        assert health["health_checks"]["zim_files_found"] == 1
        assert health["status"] == "warning"
        assert any("fake.zim" in w for w in health["warnings"]), health["warnings"]
        assert "Server is running optimally" not in health["recommendations"]

    def test_health_with_only_garbage_reports_no_zim_files(
        self, tmp_path: Path
    ) -> None:
        directory = _dir_with(tmp_path, None, ["fake.zim"])
        health = _build_health_report(_server_for(directory))

        assert health["health_checks"]["zim_files_found"] == 0
        assert health["status"] == "warning"
        assert any("no zim files" in w.lower() for w in health["warnings"])
        assert any("fake.zim" in w for w in health["warnings"])

    def test_health_stays_optimal_when_every_zim_is_readable(
        self, tmp_path: Path, v2_phase_a_zim: Path
    ) -> None:
        directory = _dir_with(tmp_path, v2_phase_a_zim, [])
        health = _build_health_report(_server_for(directory))

        assert health["health_checks"]["zim_files_found"] == 1
        assert health["status"] == "healthy"
        assert health["warnings"] == []


# ---------------------------------------------------------------------------
# D64 — Archive.check() must not freeze the event loop (runs out of process)
# ---------------------------------------------------------------------------


class TestD64IntegrityCheckRunsOutOfProcess:
    def test_validation_verdicts_still_correct_on_suite_zims(
        self, zim_test_data_dir: Path | None
    ) -> None:
        if zim_test_data_dir is None:
            pytest.skip("ZIM test suite not available")
        withns = zim_test_data_dir / "withns"
        ops = make_zim_ops(str(withns))

        good = ops.get_archive_validation_data(str(withns / "small.zim"))
        assert good["is_valid"] is True
        assert good["has_checksum"] is True
        assert isinstance(good["checksum"], str)
        assert good["checksum"]

        # Opens fine but fails its internal checksum: the verdict must come
        # back False, not be lost in the process hop.
        bad = ops.get_archive_validation_data(
            str(withns / "invalid.bad_mimetype_in_dirent.zim")
        )
        assert bad["is_valid"] is False

    def test_integrity_check_leaves_this_interpreter(
        self, v2_phase_a_zim: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The pool is the mechanism: its worker must be another process.
        pool = archive_mod._validation_pool()
        assert pool.submit(os.getpid).result() != os.getpid()

        # ...and get_archive_validation_data must route check() through it.
        routed: list[Path] = []
        real = archive_mod.check_archive_integrity

        def spy(path: Path) -> bool:
            routed.append(path)
            return real(path)

        monkeypatch.setattr(archive_mod, "check_archive_integrity", spy)
        ops = make_zim_ops(str(v2_phase_a_zim.parent))
        data = ops.get_archive_validation_data(str(v2_phase_a_zim))
        assert data["is_valid"] is True
        assert routed == [v2_phase_a_zim.resolve()]

    def test_worker_crash_is_a_validation_error_and_the_pool_recovers(
        self, v2_phase_a_zim: Path
    ) -> None:
        pool = archive_mod._validation_pool()
        crash = pool.submit(os._exit, 1)
        with pytest.raises(BrokenProcessPool):
            crash.result()

        ops = make_zim_ops(str(v2_phase_a_zim.parent))
        with pytest.raises(OpenZimMcpArchiveError, match="worker"):
            ops.get_archive_validation_data(str(v2_phase_a_zim))

        # The broken pool was discarded; the next call gets a fresh worker.
        assert archive_mod._validation_pool() is not pool
        assert ops.get_archive_validation_data(str(v2_phase_a_zim))["is_valid"] is True


# ---------------------------------------------------------------------------
# D65 — per-result snippet fragments must not flush whole responses
# ---------------------------------------------------------------------------


def _cache(max_size: int, max_bytes: int) -> OpenZimMcpCache:
    return OpenZimMcpCache(
        CacheConfig(
            enabled=True, max_size=max_size, ttl_seconds=60, max_bytes=max_bytes
        ),
        enable_background_cleanup=False,
    )


class TestD65AncillaryEntriesDoNotConsumeTheCountCap:
    def test_fragment_fanout_leaves_responses_in_place(self) -> None:
        cache = _cache(max_size=3, max_bytes=1024 * 1024)
        cache.set("resp:a", {"a": 1})
        cache.set("resp:b", {"b": 2})
        for i in range(100):
            cache.set(f"snippet_render:v1:{i}", "x" * 100, ancillary=True)

        assert cache.get("resp:a") == {"a": 1}
        assert cache.get("resp:b") == {"b": 2}
        stats = cache.stats()
        assert stats["size"] == 2
        assert stats["total_entries"] == 102
        assert stats["ancillary_entries"] == 100

    def test_ancillary_entries_remain_bounded_by_the_byte_budget(self) -> None:
        cache = _cache(max_size=100, max_bytes=6 * 1024)
        for i in range(10):
            cache.set(f"frag:{i}", "X" * 2048, ancillary=True)
        assert cache.stats()["size_bytes"] <= 6 * 1024 + 1024
        assert cache.stats()["total_entries"] < 10

    def test_ancillary_counts_toward_max_size_when_byte_budget_is_off(self) -> None:
        # With max_bytes=0 nothing else bounds fragments, so the count cap must.
        cache = _cache(max_size=3, max_bytes=0)
        for i in range(5):
            cache.set(f"frag:{i}", "x", ancillary=True)
        assert cache.stats()["size"] == 3
        assert cache.stats()["ancillary_entries"] == 0

    def test_count_cap_still_bounds_responses_with_fragments_present(self) -> None:
        cache = _cache(max_size=2, max_bytes=1024 * 1024)
        cache.set("frag:1", "x", ancillary=True)
        cache.set("frag:2", "x", ancillary=True)
        cache.set("resp:1", 1)
        cache.set("resp:2", 2)
        cache.set("resp:3", 3)  # must push a response out, not just a fragment

        stats = cache.stats()
        assert stats["size"] <= 2
        assert cache.get("resp:1") is None
        assert cache.get("resp:2") == 2
        assert cache.get("resp:3") == 3

    def test_delete_and_clear_forget_the_ancillary_marker(self) -> None:
        cache = _cache(max_size=5, max_bytes=1024 * 1024)
        cache.set("frag:1", "x", ancillary=True)
        cache.delete("frag:1")
        assert cache.stats()["ancillary_entries"] == 0
        cache.set("frag:2", "x", ancillary=True)
        cache.clear()
        assert cache.stats()["ancillary_entries"] == 0

    def test_persistence_round_trips_the_ancillary_marker(self, tmp_path: Path) -> None:
        cfg = CacheConfig(
            enabled=True,
            max_size=5,
            ttl_seconds=60,
            max_bytes=1024 * 1024,
            persistence_enabled=True,
            persistence_path=str(tmp_path / "cache"),
        )
        first = OpenZimMcpCache(cfg, enable_background_cleanup=False)
        first.set("resp:a", {"a": 1})
        first.set("frag:1", "x", ancillary=True)
        first.shutdown()

        second = OpenZimMcpCache(cfg, enable_background_cleanup=False)
        stats = second.stats()
        assert stats["size"] == 1
        assert stats["total_entries"] == 2
        assert stats["ancillary_entries"] == 1
        second.shutdown()

    def test_search_fanout_does_not_evict_cached_metadata(self, tmp_path: Path) -> None:
        """End to end: a search whose result count exceeds ``max_size`` used to
        flush every other response (the packet's limit=100 repro, scaled down)."""
        from libzim.writer import Creator

        from tests.conftest_v2_fixtures import _HtmlItem

        zp = tmp_path / "fixture.zim"
        with Creator(zp).config_indexing(True, "eng") as creator:
            for i in range(12):
                creator.add_item(
                    _HtmlItem(
                        f"A/Art{i}",
                        f"Einstein article {i}",
                        f"<html><body><h1>Einstein {i}</h1><p>Albert Einstein "
                        f"body {i} relativity physics.</p></body></html>",
                    )
                )
            creator.set_mainpath("A/Art0")

        config = OpenZimMcpConfig(
            allowed_directories=[str(tmp_path)],
            tool_mode="advanced",
            cache=CacheConfig(enabled=True, max_size=8, ttl_seconds=300),
            logging=LoggingConfig(level="WARNING"),
        )
        ops = ZimOperations(
            config,
            PathValidator(config.allowed_directories),
            OpenZimMcpCache(config.cache, enable_background_cleanup=False),
            ContentProcessor(snippet_length=200),
        )

        ops.get_zim_metadata_data(str(zp))
        hits_before = ops.cache.stats()["hits"]

        results = ops.search_zim_file_data(str(zp), "Einstein", limit=10)
        assert len(results["results"]) == 10  # ten per-result fragments inserted

        ops.get_zim_metadata_data(str(zp))
        assert (
            ops.cache.stats()["hits"] == hits_before + 1
        ), "the limit=10 search flushed the cached metadata response"
        stats = ops.cache.stats()
        assert stats["ancillary_entries"] == 10
        assert stats["size"] <= 8


# ---------------------------------------------------------------------------
# R2-5 — ``size`` must measure what ``max_size`` bounds
# ---------------------------------------------------------------------------


class TestR25CacheSizeNeverExceedsMaxSize:
    """D65 exempted fragments from the count cap but left ``size`` counting
    them, so zim_health reported size=107 against max_size=100 and readers
    concluded the cap was broken. ``size`` now counts only charged entries;
    the grand total lives under ``total_entries``."""

    def test_size_is_the_charged_count_and_total_entries_is_everything(
        self,
    ) -> None:
        cache = _cache(max_size=3, max_bytes=1024 * 1024)
        cache.set("resp:a", {"a": 1})
        cache.set("resp:b", {"b": 2})
        for i in range(100):
            cache.set(f"snippet_render:v1:{i}", "x" * 100, ancillary=True)

        stats = cache.stats()
        assert stats["size"] == 2
        assert stats["ancillary_entries"] == 100
        assert stats["total_entries"] == 102
        assert stats["size"] + stats["ancillary_entries"] == stats["total_entries"]

    def test_size_never_exceeds_max_size_under_fragment_fanout(self) -> None:
        cache = _cache(max_size=3, max_bytes=1024 * 1024)
        for i in range(10):
            cache.set(f"resp:{i}", i)
            for j in range(20):
                cache.set(f"frag:{i}:{j}", "x" * 50, ancillary=True)
            stats = cache.stats()
            assert stats["size"] <= stats["max_size"], stats

    def test_without_a_byte_budget_the_two_counts_agree(self) -> None:
        # max_bytes=0 charges fragments to the count cap, so there is no
        # exempt population and size == total_entries.
        cache = _cache(max_size=3, max_bytes=0)
        for i in range(5):
            cache.set(f"frag:{i}", "x", ancillary=True)
        stats = cache.stats()
        assert stats["size"] == 3
        assert stats["total_entries"] == 3
        assert stats["ancillary_entries"] == 0
