"""Field-report fixes for the schema/description surface (v3.3.1 sweep).

Five defects, all in text a client reads while it is deciding what to call
next:

* **fid 18** — ``url_shaped_path_hint`` told a caller who pasted
  ``https://www.iep.utm.edu/ibnrushd/`` to try ``www.iep.utm.edu/ibnrushd/``.
  That path 404s on the very archives the hint fires for (warc2zim files the
  entry under ``iep.utm.edu/ibnrushd/``), and the second failure carries no
  hint at all because the scheme is gone — a confidently wrong correction.
* **fid 8** — a directory the server cannot read reports "0 ZIM files found,
  here is how to download one". Downloading a second copy into an unreadable
  directory fails identically; the fix is ``chmod``, which nothing said.
* **fid 9** — the copy-pasteable starter command omitted ``mkdir -p``, so it
  aborts with ``curl: (23)`` when the directory does not exist yet. The
  README has carried the ``mkdir`` line all along.
* **fid 31/22** — ``zim_get``'s description printed a default only for the
  ``binary=True`` branch (10MB). The text branch's 100,000-char default —
  25x ``zim_query``'s documented 4,000 — was stated nowhere.
* **fid 69** — ``zim_search``'s ``query`` line said what is *not* parsed and
  never said that terms are AND-ed, so one out-of-vocabulary word silently
  zeroes the result set with no stated recovery.
* **fid 30/36** — two working ``zim_query`` intents (binary fetch, batch
  fetch) appeared nowhere in the only description simple-mode clients can
  read, and ``zim_get_section``'s ``compact_budget`` said "Inert." without
  naming the tool that does honour it.

Every description assertion below reads the *registered* tool description off
a live server rather than the markdown file, so a change that edits the file
without reaching the wire fails here.
"""

from __future__ import annotations

import logging
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Dict, Literal, Optional
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp import onboarding
from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import (
    CacheConfig,
    ContentConfig,
    LoggingConfig,
    OpenZimMcpConfig,
)
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.defaults import CONTENT as CONTENT_DEFAULTS
from openzim_mcp.exceptions import OpenZimMcpEntryNotFoundError
from openzim_mcp.intent_parser import IntentParser
from openzim_mcp.security import PathValidator
from openzim_mcp.server import OpenZimMcpServer
from openzim_mcp.zim_operations import ZimOperations

# --------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def ops_for_zim_data(
    basic_test_zim_files: Dict[str, Optional[Path]],
) -> ZimOperations:
    """A real ``ZimOperations`` rooted at the testing-suite directory."""
    sample = basic_test_zim_files.get("withns") or basic_test_zim_files.get("nons")
    if sample is None:
        pytest.skip("ZIM testing-suite fixture not available")
    root = sample.parent.parent
    cfg = OpenZimMcpConfig(
        allowed_directories=[str(root)],
        cache=CacheConfig(enabled=False, max_size=10, ttl_seconds=60),
        content=ContentConfig(max_content_length=1000, snippet_length=100),
        logging=LoggingConfig(level="ERROR"),
    )
    return ZimOperations(
        cfg,
        PathValidator(cfg.allowed_directories),
        OpenZimMcpCache(cfg.cache),
        ContentProcessor(snippet_length=100),
    )


def _require(path: Optional[Path]) -> Path:
    if path is None:
        pytest.skip("ZIM testing-suite fixture not available")
    return path


_DESCRIPTION_DIR = tempfile.mkdtemp(prefix="openzim_mcp_fr_schema_docs_")


def _wire_description(
    tool_name: str, mode: Literal["advanced", "simple"] = "advanced"
) -> str:
    """The description string ``tools/list`` actually ships for a tool."""
    cfg = OpenZimMcpConfig(allowed_directories=[_DESCRIPTION_DIR], tool_mode=mode)
    server = OpenZimMcpServer(cfg)
    tools = server.mcp._tool_manager._tools
    assert tool_name in tools, f"{tool_name} is not registered in {mode} mode"
    return tools[tool_name].description or ""


# --------------------------------------------------------------------------
# fid 18 — the URL-shaped-path hint must suggest a path that resolves
# --------------------------------------------------------------------------


class TestUrlHintOnWwwHosts:
    """The hint fires on real ``www.``-carrying hrefs; it must correct them."""

    def test_www_url_is_corrected_to_the_host_the_archive_files_under(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ) -> None:
        """Drive the real not-found path with the URL zim_links hands out.

        ``iep.utm.edu/ibnrushd/`` resolves in the IEP archive;
        ``www.iep.utm.edu/ibnrushd/`` does not. The hint used to suggest the
        second one, so following it burned a second call and produced a
        not-found message with no hint left to give.
        """
        zim = _require(
            basic_test_zim_files.get("withns") or basic_test_zim_files.get("nons")
        )
        with pytest.raises(OpenZimMcpEntryNotFoundError) as excinfo:
            ops_for_zim_data.get_zim_entry(
                str(zim), "https://www.example.com/ibnrushd/"
            )
        message = str(excinfo.value)

        # Positive: the suggestion offered first is the ``www.``-stripped one.
        assert "(e.g. 'example.com/ibnrushd/'" in message, message
        # Negative (paired with the positive above): the leading example is
        # not the ``www.`` form that 404s.
        assert "(e.g. 'www.example.com/ibnrushd/'" not in message, message
        # ...and the ``www.`` spelling is still offered as the fallback, since
        # an archive seeded from a ``www.`` URL does file entries under it.
        assert "'www.example.com/ibnrushd/'" in message, message

    def test_a_scheme_only_url_still_keeps_the_host(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ) -> None:
        """No ``www.`` means no second candidate — don't invent one.

        The host itself must survive: zimit archives file entries *under* the
        host, so "drop the host" advice sends the caller to a second 404.
        """
        zim = _require(
            basic_test_zim_files.get("withns") or basic_test_zim_files.get("nons")
        )
        with pytest.raises(OpenZimMcpEntryNotFoundError) as excinfo:
            ops_for_zim_data.get_zim_entry(str(zim), "https://example.com/stoicism/")
        message = str(excinfo.value)

        assert "(e.g. 'example.com/stoicism/')" in message, message
        assert " or '" not in message, message


# --------------------------------------------------------------------------
# fid 8 / fid 9 — onboarding text a broken setup can act on
# --------------------------------------------------------------------------


def _unreadable_dir(tmp_path: Path) -> Path:
    """A directory holding an archive that the process cannot walk."""
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    (blocked / "wikipedia.zim").write_bytes(b"not a real archive")
    blocked.chmod(0o000)
    if os.access(blocked, os.R_OK):  # running as root, or a permissive FS
        blocked.chmod(stat.S_IRWXU)
        pytest.skip("filesystem/user ignores directory permissions")
    return blocked


class TestUnreadableDirectoryIsNamedAsSuch:
    def test_startup_warning_says_permissions_not_go_download_one(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The Docker bind-mount / NAS shape, end to end through ``main()``.

        ``has_zim_files`` deliberately swallows the traversal failure (a
        diagnostic must never abort a boot), so the *message* is where the
        distinction has to be drawn.
        """
        blocked = _unreadable_dir(tmp_path)
        try:
            from openzim_mcp.main import main

            with (
                patch("openzim_mcp.main.OpenZimMcpServer") as server_cls,
                patch("sys.argv", ["openzim-mcp", str(blocked)]),
                caplog.at_level(logging.DEBUG, logger="openzim_mcp.main"),
            ):
                server_cls.return_value = MagicMock()
                main()
        finally:
            blocked.chmod(stat.S_IRWXU)

        warnings = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.levelno >= logging.WARNING
        )
        assert warnings, "no warning was emitted at all"
        # Positive: the directory is named as unreadable, with the fix.
        assert str(blocked) in warnings, warnings
        assert "permission" in warnings.lower(), warnings
        # Negative (paired): the download command must not be the only advice.
        head = warnings.split(onboarding.STARTER_ARCHIVE_URL)[0]
        assert "permission" in head.lower(), (
            "the permission diagnosis must come before the download command, "
            f"not after it: {warnings}"
        )

    def test_a_readable_empty_directory_is_still_told_to_download(
        self, tmp_path: Path
    ) -> None:
        """The permission branch must not swallow the ordinary empty case."""
        message = onboarding.no_archives_log_message([str(tmp_path)])
        assert "0 ZIM files found" in message
        assert onboarding.STARTER_ARCHIVE_URL in message
        assert "permission" not in message.lower(), message


class TestStarterCommandCreatesItsOwnDirectory:
    def test_the_command_makes_the_directory_it_downloads_into(self) -> None:
        """``curl -fsSL -o missing/dir/x.zim`` aborts; ``mkdir -p`` first."""
        command = onboarding.STARTER_ARCHIVE_COMMAND
        assert f"mkdir -p {onboarding.STARTER_ARCHIVE_DIR}" in command, command
        assert command.index("mkdir") < command.index("curl"), command
        assert onboarding.STARTER_ARCHIVE_URL in command

    def test_both_runtime_surfaces_carry_the_directory_creation(self) -> None:
        """The log line and the GUI-visible markdown are the same command."""
        for surface in (
            onboarding.acquisition_hint_line(),
            onboarding.acquisition_hint_markdown(),
        ):
            assert "mkdir -p" in surface, surface
            assert onboarding.STARTER_ARCHIVE_URL in surface, surface


# --------------------------------------------------------------------------
# fid 31 / 22 — zim_get's text-branch default must be on the wire
# --------------------------------------------------------------------------


class TestZimGetDocumentsItsTextDefault:
    def test_description_states_the_text_branch_default(self) -> None:
        """The 100,000 figure is derived from the config default, not typed.

        A hardcoded expectation here would go stale the moment the default
        moved; the point is that the number a client reads is the number the
        server uses.
        """
        description = _wire_description("zim_get")
        default = CONTENT_DEFAULTS.MAX_CONTENT_LENGTH
        assert (
            default
            == OpenZimMcpConfig(
                allowed_directories=[_DESCRIPTION_DIR]
            ).content.max_content_length
        )
        assert f"{default:,}" in description, description
        # Paired negative: the 10MB binary default is still documented, so a
        # reader can tell the two branches apart.
        assert "10MB" in description, description


# --------------------------------------------------------------------------
# fid 69 — zim_search must state the semantics it actually implements
# --------------------------------------------------------------------------


class TestZimSearchDocumentsConjunctiveTerms:
    def test_description_says_terms_are_and_ed(self) -> None:
        description = _wire_description("zim_search")
        assert "AND-ed" in description, description
        # The claim the field report got wrong stays: wildcards really are
        # matched literally (``aspir*`` returns aspir's 256 hits, not
        # aspirin's 834), so the description must keep saying so.
        assert "wildcards are not parsed" in description, description

    def test_one_absent_term_really_does_zero_the_result_set(
        self,
        ops_for_zim_data: ZimOperations,
        basic_test_zim_files: Dict[str, Optional[Path]],
    ) -> None:
        """The documented behaviour, measured against a real index."""
        sample = _require(basic_test_zim_files.get("withns"))
        zim = sample.parent / "wikipedia_en_climate_change_mini_2024-06.zim"
        if not zim.is_file():
            pytest.skip("needs the climate-change mini fixture")
        present = ops_for_zim_data.search_zim_file_data(str(zim), "climate", limit=5)
        one_term = present.get("total") or 0
        if not one_term:
            pytest.skip("fixture archive has no usable fulltext index")
        both = ops_for_zim_data.search_zim_file_data(
            str(zim), "climate zzzzqqqqxyzzy", limit=5
        )
        assert both.get("total") == 0, both
        assert one_term > 0, present


# --------------------------------------------------------------------------
# fid 30 / 36 — the simple-mode menu, and a parameter that names its owner
# --------------------------------------------------------------------------


_OPERATIONS_ROW = re.compile(r"^  (\S.*?)\s+- ", re.MULTILINE)


def _operations_rows(description: str) -> list[str]:
    block = description.split("OPERATIONS (pass one as `query`):", 1)[1]
    block = block.split("\n\nArgs:", 1)[0]
    return [row.strip() for row in _OPERATIONS_ROW.findall(block)]


def _example_for(phrasing: str) -> str:
    """Turn a menu row's placeholder shape into a concrete query."""
    filled = phrasing.replace("<letter>", "C")
    filled = re.sub(r"<p1>, <p2>", "C/Ant, C/Bee", filled)
    filled = re.sub(r"<path>", "C/Logo.png", filled)
    filled = re.sub(r"<file>", "wikipedia.zim", filled)
    filled = re.sub(r"<prefix>", "Cli", filled)
    return re.sub(r"<[a-z]+>", "Climate change", filled)


class TestZimQueryMenuIsTheWholeSurface:
    def test_every_menu_row_reaches_its_own_handler(self) -> None:
        """A menu row that lands on someone else's intent is worse than none.

        "it parsed" is no evidence at all here: the parser never reports
        failure — an unrecognised string falls back to ``tell_me_about`` at a
        fixed low confidence — so the fallback is measured first and every row
        is required to beat it, and to reach an intent no other row claims.
        """
        rows = _operations_rows(_wire_description("zim_query", mode="simple"))
        assert len(rows) >= 16, rows
        parser = IntentParser()
        fallback_intent, _p, fallback_confidence = parser.parse_intent(
            "transmogrify the Climate change widget"
        )

        claimed_by: dict[str, str] = {}
        weak: list[str] = []
        collisions: list[str] = []
        for row in rows:
            example = _example_for(row)
            intent, _params, confidence = parser.parse_intent(example)
            if intent == fallback_intent and confidence <= fallback_confidence:
                weak.append(
                    f"{row!r} -> {example!r} only reaches the {intent!r} "
                    f"fallback (confidence {confidence})"
                )
            elif intent in claimed_by:
                collisions.append(
                    f"{row!r} and {claimed_by[intent]!r} both dispatch to "
                    f"{intent!r}"
                )
            else:
                claimed_by[intent] = row

        assert not weak, weak
        assert not collisions, collisions
        assert len(claimed_by) == len(rows), (claimed_by, rows)

    def test_the_menu_offers_binary_and_batch_fetch(self) -> None:
        """Two working intents used to appear nowhere in the description.

        Simple mode registers ``zim_query`` alone, so a capability with no
        phrasing in this text is a capability the client cannot discover —
        the same criterion the website phrasebook is already held to.
        """
        description = _wire_description("zim_query", mode="simple")
        rows = _operations_rows(description)
        parser = IntentParser()
        reachable = {parser.parse_intent(_example_for(row))[0]: row for row in rows}
        for intent in ("binary", "get_zim_entries"):
            assert intent in reachable, (
                f"no OPERATIONS row dispatches to {intent!r}; menu rows were "
                f"{sorted(reachable)}"
            )


class TestCompactBudgetNamesTheToolThatHonoursIt:
    def test_zim_get_section_says_which_tool_honours_compact_budget(self) -> None:
        description = _wire_description("zim_get_section")
        assert "compact_budget" in description
        inert = description.split("compact_budget", 1)[1][:200]
        assert "Inert" in inert, inert
        assert "zim_query" in inert, inert
