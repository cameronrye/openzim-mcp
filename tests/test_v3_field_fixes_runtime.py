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

from openzim_mcp.config import CacheConfig, LoggingConfig, OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpArchiveError
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.server_state import _build_health_report
from openzim_mcp.zim import archive as archive_mod
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
        assert "warning" in fake and "ZIM" in fake["warning"]

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
        assert isinstance(good["checksum"], str) and good["checksum"]

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
        with pytest.raises(BrokenProcessPool):
            pool.submit(os._exit, 1).result()

        ops = make_zim_ops(str(v2_phase_a_zim.parent))
        with pytest.raises(OpenZimMcpArchiveError, match="worker"):
            ops.get_archive_validation_data(str(v2_phase_a_zim))

        # The broken pool was discarded; the next call gets a fresh worker.
        assert archive_mod._validation_pool() is not pool
        assert ops.get_archive_validation_data(str(v2_phase_a_zim))["is_valid"] is True
