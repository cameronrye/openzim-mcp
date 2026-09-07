"""Say which archives could not be used, and say why correctly.

Two v3.3.1 field-report items about the same thing from opposite ends: an
archive the server could not read, and whether the caller is told.

**fid 4** — ``synthesize=True`` opens every allowed archive and quietly
drops the ones that fail::

    "archives_searched": ["iep"]
    "fallback_used": "xapian_score"
    isError: false, a full confident answer

The half-downloaded second archive appears in no field. Only stderr
carried ``Could not open archive … for synthesize``, which a GUI client
never shows — while plain ``search all files for aristotle`` on the same
server DOES report ``## wikipedia_… — error``. A synthesized answer that
silently excludes an archive is a coverage claim the caller cannot audit.

**fid 0's residual** — the health report's aggregate line calls every
unopenable file "Unreadable .zim file (missing ZIM signature)". A truncated
download *does* carry the signature; that is why the per-archive
``loaded_archives[].warning`` distinguishes it and tells the operator to
re-download. The aggregate line still contradicts it three lines up, and
"missing signature" points at replacing a file whose bytes are fine as far
as they go.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional

import pytest

from openzim_mcp.config import CacheConfig, OpenZimMcpConfig
from openzim_mcp.server import OpenZimMcpServer

_MINI = "wikipedia_en_climate_change_mini_2024-06.zim"


def _corpus(tmp_path: Path, source_dir: Optional[Path]) -> Path:
    if source_dir is None:
        pytest.skip("ZIM_TEST_DATA_DIR not set")
    source = source_dir / "withns" / _MINI
    if not source.exists():
        pytest.skip(f"{_MINI} not in the corpus")
    zims = tmp_path / "zims"
    zims.mkdir()
    shutil.copy(source, zims / _MINI)
    return zims


def _truncate_into(zims: Path, name: str) -> Path:
    """A half-finished download: real ZIM magic, far too few bytes."""
    good = (zims / _MINI).read_bytes()
    broken = zims / name
    broken.write_bytes(good[: len(good) // 4])
    return broken


def _server(zims: Path, mode: str = "simple") -> OpenZimMcpServer:
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(zims)],
            tool_mode=mode,
            cache=CacheConfig(enabled=False),
        )
    )


# ---------------------------------------------------------------------------
# fid 4 — a briefing must declare the archives it could not read
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_names_the_archive_it_could_not_open(
    tmp_path, zim_test_data_dir
):
    zims = _corpus(tmp_path, zim_test_data_dir)
    _truncate_into(zims, "half_downloaded.zim")
    tool = _server(zims).mcp._tool_manager._tools["zim_query"].fn

    out = await tool(query="climate change", synthesize=True)

    assert out.get("error") is not True, out
    failed = out.get("archives_failed")
    assert failed, (
        "the briefing was built from one of two archives and said so "
        f"nowhere: {sorted(out)}"
    )
    assert any("half_downloaded" in str(f) for f in failed), failed


@pytest.mark.asyncio
async def test_the_answer_is_still_returned(tmp_path, zim_test_data_dir):
    """Degrading gracefully is right; degrading silently is the defect.

    Paired with the test above so "declares the failure" cannot be
    satisfied by refusing the whole call.
    """
    zims = _corpus(tmp_path, zim_test_data_dir)
    _truncate_into(zims, "half_downloaded.zim")
    tool = _server(zims).mcp._tool_manager._tools["zim_query"].fn

    out = await tool(query="climate change", synthesize=True)

    assert out["answer_markdown"], out
    assert out["archives_searched"], out


@pytest.mark.asyncio
async def test_a_healthy_corpus_carries_no_failure_field(tmp_path, zim_test_data_dir):
    """Control: the field marks a real failure, so it must be absent when
    there is none — otherwise it is noise on every response."""
    zims = _corpus(tmp_path, zim_test_data_dir)
    tool = _server(zims).mcp._tool_manager._tools["zim_query"].fn

    out = await tool(query="climate change", synthesize=True)

    assert out.get("error") is not True, out
    assert "archives_failed" not in out, out["archives_failed"]


# ---------------------------------------------------------------------------
# fid 0 residual — the aggregate line must not contradict the per-archive one
# ---------------------------------------------------------------------------


def _health(server: OpenZimMcpServer) -> Any:
    from openzim_mcp.server_state import _build_health_report

    return _build_health_report(server)


def test_a_truncated_download_is_not_called_a_missing_signature(
    tmp_path, zim_test_data_dir
):
    zims = _corpus(tmp_path, zim_test_data_dir)
    _truncate_into(zims, "half_downloaded.zim")

    warnings = " ".join(_health(_server(zims, "advanced")).get("warnings") or [])

    assert "half_downloaded.zim" in warnings, warnings
    assert "missing ZIM signature" not in warnings, warnings
    assert "runcated" in warnings, warnings


def test_a_file_that_was_never_an_archive_still_says_so(tmp_path, zim_test_data_dir):
    """Control, and the distinction's whole point: the two remedies differ.

    A README renamed ``.zim`` should be removed; a truncated download should
    be re-fetched. Collapsing them was the defect in the other direction.
    """
    zims = _corpus(tmp_path, zim_test_data_dir)
    (zims / "not_an_archive.zim").write_bytes(b"<html><body>404</body></html>" * 20)

    warnings = " ".join(_health(_server(zims, "advanced")).get("warnings") or [])

    assert "not_an_archive.zim" in warnings, warnings
    assert "missing ZIM signature" in warnings, warnings


def test_the_aggregate_agrees_with_the_per_archive_verdict(tmp_path, zim_test_data_dir):
    """The finding's actual complaint: two lines of one payload disagreeing.

    ``loaded_archives[].warning`` has said "Truncated ZIM archive … re-
    download it" since fid 0 was fixed; ``health.warnings`` kept saying
    "missing ZIM signature" about the same file.
    """
    zims = _corpus(tmp_path, zim_test_data_dir)
    _truncate_into(zims, "half_downloaded.zim")
    server = _server(zims, "advanced")

    aggregate = " ".join(_health(server).get("warnings") or [])
    per_archive = " ".join(
        str(a.get("warning") or "")
        for a in server.zim_operations.list_zim_files_data()
        if "half_downloaded" in str(a.get("path", ""))
    )

    assert "runcated" in per_archive, per_archive
    assert ("missing ZIM signature" in aggregate) == (
        "missing ZIM signature" in per_archive
    ), (aggregate, per_archive)
