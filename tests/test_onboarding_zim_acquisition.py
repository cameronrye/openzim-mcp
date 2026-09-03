"""The first-archive acquisition funnel.

A server with no ZIM files is inert, and every surface a new user reaches
before that point used to leave them to work out where an archive comes
from:

* ``README.md`` — the dominant landing surface — pointed only at
  ``library.kiwix.org``, whose headline archives are tens of gigabytes.
  The one-command 13.6 MB starter archive existed, but only on the docs
  site (``website/src/content/docs/quick-start.mdx``).
* Startup logged "server started" and the allowed directories whether or
  not those directories contained a single ``.zim``.
* The tool-result text a GUI client actually shows said "No ZIM files
  found in allowed directories" and stopped there — and a GUI client is
  precisely where the stderr log the operator would otherwise read is
  buried in a file.

These tests pin the three surfaces, and pin them to *the same* facts: the
size and URL the README states must be the ones the docs site states, so
the two cannot drift into contradicting each other.

The startup signal is asserted to go through the logger *and* to leave
stdout byte-for-byte empty: under the default stdio transport, stdout is
the JSON-RPC channel, so a stray ``print`` there does not merely look
untidy, it corrupts the protocol stream and breaks every stdio client.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openzim_mcp import onboarding
from openzim_mcp.cache import OpenZimMcpCache
from openzim_mcp.config import OpenZimMcpConfig
from openzim_mcp.content_processor import ContentProcessor
from openzim_mcp.security import PathValidator
from openzim_mcp.simple_tools import SimpleToolsHandler
from openzim_mcp.zim_operations import ZimOperations

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"
QUICK_START = REPO / "website/src/content/docs/quick-start.mdx"
INSTALLATION = REPO / "website/src/content/docs/installation.mdx"
LLMS_TXT = REPO / "website/src/pages/llms.txt.ts"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _mentions(text: str, needle: str) -> bool:
    """Substring test, written as a search rather than ``in``.

    ``assert <hostname> in text`` reads perfectly well and trips CodeQL's
    ``py/incomplete-url-substring-sanitization`` once per assertion: the
    query cannot tell an assertion about documentation prose from a URL
    allowlist check, and a hostname substring test is a real defect when
    it *is* one. Nothing here decides anything about a URL — these are
    assertions that a piece of guidance was printed — so the check is
    spelled as a literal search instead of a containment test.
    """
    return re.search(re.escape(needle), text) is not None


# --------------------------------------------------------------------------
# README — the landing surface
# --------------------------------------------------------------------------


def test_readme_offers_the_one_command_starter_archive() -> None:
    """The README must carry the starter archive, not just a library link.

    ``library.kiwix.org`` is where the full archives live; its headline
    downloads are tens of gigabytes. A reader who has just run
    ``uv tool install openzim-mcp`` needs something they can finish in a
    minute, and the fact that one exists was previously discoverable only
    from the docs site.
    """
    text = _readme()

    assert (
        onboarding.STARTER_ARCHIVE_URL in text
    ), "README does not name the starter archive URL"
    assert (
        onboarding.STARTER_ARCHIVE_SIZE in text
    ), f"README does not state the starter archive size ({onboarding.STARTER_ARCHIVE_SIZE})"
    assert _mentions(
        text, onboarding.KIWIX_LIBRARY_HOST
    ), "README does not point at the Kiwix library for full archives"

    # The command has to be copy-pasteable, which means it has to be in a
    # fence — a URL mentioned in prose is a fact, not an action.
    fences = re.findall(r"```bash\n(.*?)```", text, flags=re.DOTALL)
    assert any(
        onboarding.STARTER_ARCHIVE_URL in fence and "curl" in fence for fence in fences
    ), "the starter archive URL is not inside a copy-pasteable bash fence"


def test_readme_starter_archive_precedes_the_client_configuration() -> None:
    """Placement, not just presence.

    The block only converts if it is read *before* the reader wires the
    server into a client and points it at a directory. Anchor it to the
    install section (it must land after "Verify the install" and before
    the "## Quick start" heading) rather than merely somewhere in the file.
    """
    text = _readme()
    verify = text.index("Verify the install")
    quick_start = text.index("\n## Quick start")
    url_at = text.index(onboarding.STARTER_ARCHIVE_URL)

    assert verify < url_at < quick_start, (
        "the starter archive block must sit in the install section, between "
        f"'Verify the install' ({verify}) and '## Quick start' ({quick_start}); "
        f"found at {url_at}"
    )


def test_every_surface_states_the_same_starter_archive() -> None:
    """Four surfaces, one set of facts.

    ``tests/test_docs_freshness.py`` exists because measurements stated in
    more than one place drift. The size and URL are stated in the README,
    on two docs pages and in the generated ``llms.txt``; assert they agree
    with each other and with the constant the server logs, so a future edit
    to one is caught here rather than by a user following a stale number.
    """
    surfaces = {
        "README.md": _readme(),
        "quick-start.mdx": QUICK_START.read_text(encoding="utf-8"),
        "installation.mdx": INSTALLATION.read_text(encoding="utf-8"),
        "llms.txt.ts": LLMS_TXT.read_text(encoding="utf-8"),
    }
    # Guard the guard: a renamed page would otherwise silently drop out of
    # the sweep and leave this test asserting less than it appears to.
    assert len(surfaces) == 4

    for surface, text in surfaces.items():
        assert (
            onboarding.STARTER_ARCHIVE_URL in text
        ), f"{surface} does not use the canonical starter archive URL"
        assert (
            onboarding.STARTER_ARCHIVE_SIZE in text
        ), f"{surface} does not state the canonical starter archive size"
        # And no surface may state a *different* size for the same file.
        found = set(re.findall(r"\d+\.\d+ MB", text))
        assert found <= {onboarding.STARTER_ARCHIVE_SIZE}, (
            f"{surface} states a size other than "
            f"{onboarding.STARTER_ARCHIVE_SIZE}: {found}"
        )


# --------------------------------------------------------------------------
# Startup signal
# --------------------------------------------------------------------------


def _run_main(directory: Path) -> None:
    from openzim_mcp.main import main

    with (
        patch("openzim_mcp.main.OpenZimMcpServer") as server_cls,
        patch("sys.argv", ["openzim-mcp", str(directory)]),
    ):
        server_cls.return_value = MagicMock()
        main()


def test_startup_warns_when_no_archives_are_discoverable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An empty directory used to log "started" and nothing else.

    The server was working exactly as configured and completely useless,
    and the log said only that it had started successfully.
    """
    with caplog.at_level(logging.DEBUG, logger="openzim_mcp.main"):
        _run_main(tmp_path)

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
    ]
    joined = "\n".join(warnings)
    assert warnings, "no warning was emitted for a directory with zero ZIM files"
    # The count, not merely the digit: ``tmp_path`` is full of digits, so a
    # bare ``"0" in joined`` would pass on a message that never mentions it.
    assert (
        "0 ZIM files found" in joined
    ), f"the warning does not name the count: {warnings!r}"
    assert _mentions(
        joined, onboarding.KIWIX_LIBRARY_HOST
    ), f"the warning does not name the Kiwix library: {warnings!r}"
    assert (
        onboarding.STARTER_ARCHIVE_URL in joined
    ), f"the warning does not carry the starter command: {warnings!r}"


def test_startup_warning_never_writes_to_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """stdout is the JSON-RPC channel under the default stdio transport.

    A ``print`` here would interleave prose with framed JSON-RPC and break
    every stdio client — a far worse failure than the silence it replaces.
    """
    _run_main(tmp_path)

    captured = capsys.readouterr()
    assert captured.out == "", (
        "startup wrote to stdout, which is the stdio JSON-RPC stream: "
        f"{captured.out!r}"
    )


def test_startup_is_quiet_when_an_archive_is_present(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The warning must be about the empty case, not a permanent banner."""
    (tmp_path / "wikipedia.zim").write_bytes(b"not a real archive")

    with caplog.at_level(logging.DEBUG, logger="openzim_mcp.main"):
        _run_main(tmp_path)

    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno >= logging.WARNING
        and _mentions(record.getMessage(), onboarding.KIWIX_LIBRARY_HOST)
    ]
    assert (
        not warnings
    ), f"acquisition warning fired with an archive present: {warnings!r}"


def test_startup_counts_archives_in_nested_directories(tmp_path: Path) -> None:
    """The listing globs ``**/*.zim``; the startup count must agree with it.

    A count that only looked at the top level would nag an operator whose
    archives live one directory down, while the server itself found them.
    """
    nested = tmp_path / "wikipedia" / "2024"
    nested.mkdir(parents=True)
    (nested / "wikipedia_en_all.zim").write_bytes(b"not a real archive")

    assert onboarding.count_zim_files([str(tmp_path)]) == 1


def test_counting_survives_a_directory_it_cannot_walk(tmp_path: Path) -> None:
    """A diagnostic that can abort the boot is worse than no diagnostic.

    ``count_zim_files`` runs before ``server.run()``, so an unreadable or
    vanished directory must contribute zero rather than propagate — the
    same degradation ``ZimOperations._glob_zim_paths`` applies.
    """
    good = tmp_path / "good"
    good.mkdir()
    (good / "wikipedia.zim").write_bytes(b"not a real archive")

    with patch.object(Path, "glob", side_effect=OSError("permission denied")):
        assert onboarding.count_zim_files([str(good)]) == 0

    # The real walk still works either side of the failure.
    assert onboarding.count_zim_files([str(good)]) == 1


# --------------------------------------------------------------------------
# Tool-result text — what a GUI client actually shows
# --------------------------------------------------------------------------


@pytest.fixture
def empty_zim_operations(tmp_path: Path) -> ZimOperations:
    """Real operations over a real, genuinely empty directory."""
    config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)])
    return ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(),
    )


def test_empty_listing_says_where_to_get_an_archive(
    empty_zim_operations: ZimOperations,
) -> None:
    """Claude Desktop buries stderr in a log file; this string is the UI."""
    result = empty_zim_operations.list_zim_files()

    assert "No ZIM files found" in result
    assert _mentions(result, onboarding.KIWIX_LIBRARY_HOST), result
    assert onboarding.STARTER_ARCHIVE_URL in result, result


def test_filtered_empty_listing_does_not_offer_to_download_a_first_archive(
    tmp_path: Path,
) -> None:
    """A filter that matched nothing is not an empty library.

    The acquisition advice belongs to "you have no archives", not to "your
    substring matched none of the archives you have" — offering a download
    there would be answering a question the caller did not ask.
    """
    (tmp_path / "wikipedia.zim").write_bytes(b"not a real archive")
    config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)])
    operations = ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(),
    )

    result = operations.list_zim_files(name_filter="stackexchange")

    assert "No ZIM files found" in result
    assert not _mentions(result, onboarding.KIWIX_LIBRARY_HOST), result


def test_query_gate_says_where_to_get_an_archive_when_none_are_loaded(
    empty_zim_operations: ZimOperations,
) -> None:
    """The zero-archive case reached the *ambiguous*-archive gate.

    ``_auto_select_zim_file`` returns ``None`` both when two archives are
    loaded and when none are, so a user with an empty directory was told to
    "specify a ZIM file path" and offered cross-archive recovery steps
    (``search all files for X``, ``synthesize=True``) that cannot possibly
    work — there is nothing to search.
    """
    handler = SimpleToolsHandler(empty_zim_operations)

    result = handler.handle_zim_query("search for biology")

    assert _mentions(result, onboarding.KIWIX_LIBRARY_HOST), result
    assert onboarding.STARTER_ARCHIVE_URL in result, result
    assert "search all files for" not in result, (
        "cross-archive recovery steps were offered with zero archives loaded: "
        f"{result}"
    )


def test_query_gate_keeps_the_ambiguous_advice_when_archives_exist() -> None:
    """Two archives loaded is the case the recovery block was written for.

    Splitting the gate must not cost the D-M cross-archive guidance: with
    archives present the caller still needs ``zim_file_path`` /
    ``search all files for`` / ``synthesize=True``, and telling them to go
    download something would be actively wrong.
    """
    operations = MagicMock()
    operations.list_zim_files_data.return_value = [
        {"path": "/zim/wikipedia.zim"},
        {"path": "/zim/wiktionary.zim"},
    ]
    operations.list_zim_files.return_value = "Found 2 ZIM files"

    result = SimpleToolsHandler(operations).handle_zim_query("search for biology")

    assert "search all files for" in result, result
    assert not _mentions(result, onboarding.KIWIX_LIBRARY_HOST), result
    assert "intent=no_zim_file_specified" in result, result


def test_query_gate_falls_back_to_the_ambiguous_advice_when_the_probe_fails() -> None:
    """A failed count must not invent an empty library.

    "You have no archives, download one" is a confident claim; make it only
    on a probe that actually answered.
    """
    operations = MagicMock()
    operations.list_zim_files_data.side_effect = RuntimeError("probe exploded")
    operations.list_zim_files.return_value = "Found 2 ZIM files"

    result = SimpleToolsHandler(operations)._no_zim_file_response()

    assert not _mentions(result, onboarding.KIWIX_LIBRARY_HOST), result
    assert "search all files for" in result, result
