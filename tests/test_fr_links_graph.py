"""Field-report fixes — ``links-graph`` group (2026-09 real-world sweep).

Three findings, all reproduced against real archives:

* **fid 0** — ``zim_health()`` reported ``status: "healthy"`` and "Server is
  running optimally" for a half-downloaded archive that libzim cannot open at
  all, because the readability probe read only the four magic bytes, which an
  interrupted download keeps. The very next tool call failed, and its
  troubleshooting text pointed the user back at ``zim_health``.
* **fid 10** — libzim's own diagnosis ("Zim file(s) is of bad size or
  corrupted", "zim-file is too small to contain a header") was dropped when the
  open failure was re-wrapped, so a truncated download, a stray text file and a
  header stub all produced one identical string with three different remedies.
* **fid 95** — ``openzim-mcp build link-graph`` reported a numerator of
  ARTICLES against a denominator of total ENTRIES, so the percentage stalled
  around half and the counter could never reach the denominator.

Every archive here is a real one built by libzim's ``Creator`` (or truncated
from one), so the verdicts under test are checked against what libzim itself
does with the same file rather than against a hand-written header.
"""

from __future__ import annotations

import subprocess  # nosec B404 — fixed argv, no shell, test-local paths
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple, cast

import pytest
from libzim.reader import Archive  # type: ignore[import-untyped]
from libzim.writer import (  # type: ignore[import-untyped]
    Creator,
    Hint,
    Item,
    StringProvider,
)

from openzim_mcp.config import CacheConfig, LoggingConfig, OpenZimMcpConfig
from openzim_mcp.exceptions import OpenZimMcpArchiveError
from openzim_mcp.linkgraph.builder import build_link_graph
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.server_state import _build_health_report
from openzim_mcp.zim_operations import zim_archive
from tests.conftest_v2_fixtures import make_zim_ops

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _server_for(directory: Path) -> OpenZimMcpServer:
    return OpenZimMcpServer(
        OpenZimMcpConfig(
            allowed_directories=[str(directory)],
            tool_mode="advanced",
            # Cache ON: with it off the report recommends enabling it, and the
            # "Server is running optimally" assertions below would pass or fail
            # for the wrong reason.
            cache=CacheConfig(enabled=True, max_size=10, ttl_seconds=60),
            logging=LoggingConfig(level="WARNING"),
        )
    )


def _health_of(directory: Path) -> Dict[str, Any]:
    return cast(Dict[str, Any], _build_health_report(_server_for(directory)))


@pytest.fixture
def intact_zim(tmp_path: Path, v2_phase_a_zim: Path) -> Path:
    """A complete, openable copy of the fixture archive."""
    target = tmp_path / "complete.zim"
    target.write_bytes(v2_phase_a_zim.read_bytes())
    return target


@pytest.fixture
def half_downloaded_zim(tmp_path: Path, v2_phase_a_zim: Path) -> Path:
    """The first half of a real archive — exactly what an interrupted
    multi-GB Kiwix download leaves on disk: correct magic bytes, a complete
    header, and a body that stops in the middle."""
    payload = v2_phase_a_zim.read_bytes()
    target = tmp_path / "broken.zim"
    target.write_bytes(payload[: len(payload) // 2])
    return target


# ---------------------------------------------------------------------------
# fid 0 — a half-downloaded archive must not read as a healthy loaded archive
# ---------------------------------------------------------------------------


def test_libzim_really_refuses_the_half_downloaded_archive(
    half_downloaded_zim: Path, intact_zim: Path
) -> None:
    """Ground truth for every verdict below: the truncated file is unopenable
    and the intact one opens."""
    with pytest.raises(RuntimeError):
        Archive(str(half_downloaded_zim))

    assert Archive(str(intact_zim)).entry_count > 0


def test_listing_marks_a_half_downloaded_archive_unreadable(
    tmp_path: Path, intact_zim: Path, half_downloaded_zim: Path
) -> None:
    """``loaded_archives`` presented the truncated file as a loaded archive
    with ``readable: true`` because only the 4 magic bytes were checked."""
    by_name = {e["name"]: e for e in make_zim_ops(str(tmp_path)).list_zim_files_data()}
    assert set(by_name) == {"complete.zim", "broken.zim"}

    # Positive: the intact copy of the same archive is still readable.
    assert by_name["complete.zim"]["readable"] is True
    assert "warning" not in by_name["complete.zim"]

    # Negative: the truncated copy is flagged, and the warning says which of
    # the two remedies applies (re-download, not "delete this junk file").
    broken = by_name["broken.zim"]
    assert broken["readable"] is False
    assert "truncated" in broken["warning"].lower(), broken["warning"]
    assert "re-download" in broken["warning"].lower(), broken["warning"]


def test_health_downgrades_and_names_the_half_downloaded_archive(
    tmp_path: Path, intact_zim: Path, half_downloaded_zim: Path
) -> None:
    """The report said "healthy" / "Server is running optimally" while one of
    the two archives could not be opened at all."""
    health = _health_of(tmp_path)

    assert health["status"] == "warning"
    assert health["health_checks"]["zim_files_found"] == 1
    assert any("broken.zim" in w for w in health["warnings"]), health["warnings"]
    assert "Server is running optimally" not in health["recommendations"]
    # A truncated download is not a permission problem: that verdict must not
    # be borrowed to express this one.
    assert health["health_checks"]["permissions_ok"] is True


def test_health_still_reports_optimal_for_a_directory_of_intact_archives(
    tmp_path: Path, intact_zim: Path
) -> None:
    """The positive half of the pair: the stricter probe must not start
    condemning archives that are perfectly fine."""
    health = _health_of(tmp_path)

    assert health["status"] == "healthy"
    assert health["health_checks"]["zim_files_found"] == 1
    assert health["warnings"] == []
    assert "Server is running optimally" in health["recommendations"]


# ---------------------------------------------------------------------------
# fid 10 — libzim's diagnosis must survive the re-wrap
# ---------------------------------------------------------------------------


def _open_error(path: Path) -> OpenZimMcpArchiveError:
    with pytest.raises(OpenZimMcpArchiveError) as excinfo:
        with zim_archive(path):
            pass  # pragma: no cover — the open above always raises here
    return excinfo.value


def test_open_failure_carries_libzims_own_diagnosis(
    half_downloaded_zim: Path,
) -> None:
    """ "Zim file(s) is of bad size or corrupted" is the one sentence that tells
    a user to re-download; it was thrown away one line from where it was
    caught."""
    error = _open_error(half_downloaded_zim)
    message = str(error)

    # Positive: the path the caller needs is still there.
    assert str(half_downloaded_zim) in message
    assert message.startswith("Failed to open ZIM archive:")

    # The wrapped cause's own words reach the client, not just __cause__
    # (which never leaves this process). Whitespace is normalised by the
    # wrapper so the message stays one line.
    cause = " ".join(str(error.__cause__).split())
    assert cause, "libzim raised without a message; nothing to carry through"
    assert cause in message, message
    assert "corrupt" in message.lower(), message


def test_three_different_open_failures_no_longer_collapse_to_one_string(
    tmp_path: Path, half_downloaded_zim: Path
) -> None:
    """A truncated download, a renamed text file and a header stub have three
    different remedies and used to produce one identical message."""
    not_a_zim = tmp_path / "notazim.zim"
    not_a_zim.write_bytes(b"not a zim at all")

    truncated_message = str(_open_error(half_downloaded_zim))
    wrong_file_message = str(_open_error(not_a_zim))

    # Strip the paths so only the diagnosis is compared.
    truncated_diagnosis = truncated_message.replace(str(half_downloaded_zim), "")
    wrong_file_diagnosis = wrong_file_message.replace(str(not_a_zim), "")
    assert truncated_diagnosis != wrong_file_diagnosis

    # Positive on each: the wrong-file case names the header, the truncated
    # case names corruption.
    assert "header" in wrong_file_diagnosis.lower(), wrong_file_message
    assert "corrupt" in truncated_diagnosis.lower(), truncated_message


def test_validation_surface_shows_the_diagnosis_to_the_client(
    tmp_path: Path, half_downloaded_zim: Path
) -> None:
    """End to end through ``zim_health(zim_file_path=...)``'s operation: the
    rendered message, not just the exception chain, must carry the reason."""
    ops = make_zim_ops(str(tmp_path))

    with pytest.raises(OpenZimMcpArchiveError) as excinfo:
        ops.get_archive_validation_data(str(half_downloaded_zim))

    rendered = str(excinfo.value)
    assert rendered.startswith("Validation failed:")
    assert str(half_downloaded_zim) in rendered
    assert "corrupt" in rendered.lower(), rendered


# ---------------------------------------------------------------------------
# fid 95 — build progress must count the population it reports against
# ---------------------------------------------------------------------------


class _HtmlItem(Item):
    """A minimal HTML item for the libzim ``Creator`` API."""

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

    def get_hints(self) -> Dict[Hint, int]:
        return {Hint.FRONT_ARTICLE: 1}


class _AssetItem(_HtmlItem):
    """A non-article entry in the content namespace (ZIMIT stores plenty)."""

    def get_mimetype(self) -> str:
        return "image/png"

    def get_hints(self) -> Dict[Hint, int]:
        return {Hint.FRONT_ARTICLE: 0}


# Deliberately NOT a multiple of the progress stride, so the closing tick
# that lands the report on 100 % has a failing case of its own.
_ARTICLES = 901
_ASSETS = 601


@pytest.fixture(scope="module")
def mixed_zim(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An archive whose entries are mostly, but not all, articles.

    The article count and the entry count must differ, otherwise a build that
    counts articles and a build that counts entries are indistinguishable.
    """
    out = tmp_path_factory.mktemp("fr-linkgraph") / "mixed.zim"
    with Creator(out).config_indexing(False, "eng") as creator:
        for i in range(_ARTICLES):
            creator.add_item(
                _HtmlItem(
                    f"A/Art{i}",
                    f"Art {i}",
                    f'<html><body><p>body</p><a href="Art{(i + 1) % _ARTICLES}">'
                    "next</a></body></html>",
                )
            )
        for i in range(_ASSETS):
            creator.add_item(_AssetItem(f"A/asset{i}.png", f"asset {i}", "PNG"))
        creator.set_mainpath("A/Art0")
    return out


def _build_with_progress(archive_path: Path, out: Path) -> List[Tuple[int, int]]:
    seen: List[Tuple[int, int]] = []

    def _progress(done: int, total: int) -> None:
        seen.append((done, total))

    build_link_graph(str(archive_path), str(out), progress=_progress)
    return seen


def test_progress_counts_entries_walked_against_the_entry_count(
    tmp_path: Path, mixed_zim: Path
) -> None:
    """The numerator enumerated article sources while the denominator was
    ``entry_count``, so the counter could never reach it and read ~35 % at
    two-thirds done."""
    entry_count = Archive(str(mixed_zim)).entry_count
    assert entry_count > _ARTICLES, "fixture must hold non-article entries too"

    seen = _build_with_progress(mixed_zim, tmp_path / "mixed.linkgraph.sqlite")

    assert seen, "a build of this size reported no progress at all"
    assert {total for _done, total in seen} == {entry_count}

    # The ticks step evenly across the WHOLE entry range and land on it. A
    # numerator that counted only the 901 articles would keep the same stride
    # but run out of ticks long before the denominator, which is exactly the
    # "stalls around half" symptom.
    dones = [done for done, _total in seen]
    stride = dones[0]
    assert stride > 0, dones
    expected = list(range(stride, entry_count + 1, stride))
    if expected[-1] != entry_count:
        expected.append(entry_count)
    assert dones == expected, dones
    assert len(dones) > 1, dones


def test_progress_line_the_operator_sees_reaches_100_percent(
    tmp_path: Path, mixed_zim: Path
) -> None:
    """End to end through ``python -m openzim_mcp build link-graph``: the
    rendered stderr line is what the operator judges a long build by."""
    archive = tmp_path / "mixed.zim"
    archive.write_bytes(mixed_zim.read_bytes())
    entry_count = Archive(str(archive)).entry_count

    completed = subprocess.run(  # nosec B603 — fixed argv, no shell
        [sys.executable, "-m", "openzim_mcp", "build", "link-graph", str(archive)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr

    walked = [line for line in completed.stderr.splitlines() if "walked" in line]
    assert walked, completed.stderr
    assert walked[-1].strip() == f"…walked {entry_count}/{entry_count} entries", walked
    for line in walked:
        assert line.strip().endswith(f"/{entry_count} entries"), line


def test_progress_is_optional_and_the_build_still_succeeds(
    tmp_path: Path, mixed_zim: Path
) -> None:
    """The no-reporter path is the one every runtime caller uses."""
    out = tmp_path / "quiet.linkgraph.sqlite"
    stats = build_link_graph(str(mixed_zim), str(out))

    assert stats.node_count > 0
    assert stats.edge_count > 0
    assert out.exists()
