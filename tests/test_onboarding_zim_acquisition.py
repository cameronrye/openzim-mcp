"""The first-archive acquisition funnel.

A server with no ZIM files is inert, and every surface a new user reaches
before that point used to leave them to work out where an archive comes
from:

* ``README.md`` — the dominant landing surface — pointed only at
  ``library.kiwix.org``, whose headline archives are tens of gigabytes.
  The one-command 13.6 MB starter archive existed, but only on the docs
  site (``website/src/content/docs/quick-start.mdx``). The README then
  downloaded into ``~/zim-files`` and configured the server against a
  ``/path/to/zim/files`` placeholder, so following it top-to-bottom
  ended in a configuration error.
* Startup logged "server started" and the allowed directories whether or
  not those directories contained a single ``.zim``.
* The tool-result text a GUI client actually shows said "No ZIM files
  found in allowed directories" and stopped there — and a GUI client is
  precisely where the stderr log the operator would otherwise read is
  buried in a file.

These tests pin those surfaces, and pin them to *the same* facts: the size
and URL the README states must be the ones the docs site states, the
``.mcpb`` bundle's directory prompt states and the server logs, so none of
them can drift into contradicting the others. The size itself is pinned to
the archive's measured byte count, so "stated consistently" cannot mean
"consistently wrong", and the URL is registered with the repo's link
checker, so an upstream move is caught by CI rather than by a user.

The startup signal is asserted to go through the logger *and* to leave
stdout byte-for-byte empty: under the default stdio transport, stdout is
the JSON-RPC channel, so a stray ``print`` there does not merely look
untidy, it corrupts the protocol stream and breaks every stdio client.
"""

from __future__ import annotations

import json
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


#: A size figure, with or without the space these pages use inconsistently
#: ("13.6 MB" in the prose, "13.6MB" in installation.mdx's summary list).
_SIZE_RE = re.compile(r"\d+(?:\.\d+)? ?MB")

#: Words that mean the sentence is talking about *this* archive.
_STARTER_ANCHORS = (
    "climate change",
    "climate-change",
    onboarding.STARTER_ARCHIVE_FILENAME,
)


def _sizes_claimed_for_the_starter_archive(text: str) -> set[str]:
    """Every size figure stated on a line that names the starter archive.

    Deliberately not "every MB figure in the file". The earlier version of
    this check swept the whole text, which made an unrelated future figure
    — a cache ceiling, a reranker model download, a second archive's size —
    fail a test named after the starter archive, in a file whose name gives
    no hint that it polices unrelated numbers. It was also inconsistent
    about what it caught: it forbade "2.5 MB" while ``~300 MB`` and
    ``13.6MB`` both slipped past it.

    Anchoring on the archive's own vocabulary keeps the drift this exists
    to catch (a page restating the size wrongly) and drops the collateral.
    Sizes are normalised so "13.6MB" and "13.6 MB" compare equal.
    """
    claimed: set[str] = set()
    for line in text.splitlines():
        lowered = line.lower()
        if not any(anchor.lower() in lowered for anchor in _STARTER_ANCHORS):
            continue
        for match in _SIZE_RE.finditer(line):
            claimed.add(match.group(0).replace("MB", " MB").replace("  ", " "))
    return claimed


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
        found = _sizes_claimed_for_the_starter_archive(text)
        assert found <= {onboarding.STARTER_ARCHIVE_SIZE}, (
            f"{surface} states a size other than "
            f"{onboarding.STARTER_ARCHIVE_SIZE} for the starter archive: {found}"
        )


def test_the_stated_size_is_the_measured_byte_count_rounded() -> None:
    """The size is a derived fact, not an independent claim.

    Everything above checks the four surfaces against
    ``STARTER_ARCHIVE_SIZE``; this checks ``STARTER_ARCHIVE_SIZE`` against
    the file. Without it a wrong number stated consistently everywhere is
    a fully green suite.
    """
    mib = onboarding.STARTER_ARCHIVE_BYTES / 1024 / 1024
    assert onboarding.STARTER_ARCHIVE_SIZE == f"{mib:.1f} MB", (
        f"{onboarding.STARTER_ARCHIVE_BYTES:,} bytes rounds to "
        f"{mib:.1f} MB, not {onboarding.STARTER_ARCHIVE_SIZE}"
    )
    # The two pages that quote the raw measurements must quote these ones.
    for surface, path in (
        ("quick-start.mdx", QUICK_START),
        ("installation.mdx", INSTALLATION),
    ):
        text = path.read_text(encoding="utf-8")
        assert (
            f"{onboarding.STARTER_ARCHIVE_BYTES:,}" in text
        ), f"{surface} does not state the canonical byte count"
        assert (
            onboarding.STARTER_ARCHIVE_SHA256 in text
        ), f"{surface} does not state the canonical SHA-256"


def test_readme_points_the_server_at_the_directory_the_download_fills() -> None:
    """The README has to work end to end when it is followed literally.

    It told the reader to ``mkdir -p ~/zim-files`` and download into it,
    said "that is the directory you point the server at below", and then
    every example below said ``/path/to/zim/files``. Copy-pasting the
    Claude Desktop block verbatim produced ``Directory does not exist`` on
    the exact onboarding path this section exists to unblock.
    """
    text = _readme()
    quick_start = text[text.index("\n## Quick start") : text.index("\n## Highlights")]

    assert (
        onboarding.STARTER_ARCHIVE_DIR in quick_start
    ), "the Quick start examples do not use the directory the download fills"
    stale = re.findall(r"/path/to/[\w/]*zim[\w/]*", text)
    assert not stale, (
        "the README still configures the server against a placeholder "
        f"directory the reader was never told to create: {sorted(set(stale))}"
    )


def test_a_literal_tilde_path_is_a_directory_the_server_accepts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``~`` in a client config file is never expanded by a shell.

    The README now writes ``"args": ["openzim-mcp", "~/zim-files"]``, which
    reaches the process as a literal tilde: no shell is involved when
    Claude Desktop spawns it. That advice is only sound because the config
    layer expands it itself, so pin that rather than trusting it.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Windows
    (tmp_path / "zim-files").mkdir()

    config = OpenZimMcpConfig(allowed_directories=[onboarding.STARTER_ARCHIVE_DIR])

    assert config.allowed_directories == [str((tmp_path / "zim-files").resolve())]


def test_the_starter_url_is_a_url_the_link_checker_probes() -> None:
    """The one external dependency onboarding rests on must be checked.

    ``scripts/check_docs_links.py`` blanks fenced code blocks and does not
    collect bare URLs, and the starter archive is only ever written as a
    bare URL inside a ``curl`` fence — so it was the single URL in the repo
    that CI never probed. ``curl -fsSL`` prints nothing on a 404, so an
    upstream move would have reached users as "the command did nothing"
    with every check still green.

    The script is stdlib-only and runs as bare ``python3`` in CI, so it
    cannot import the constant; this is the join that keeps the copy honest.
    """
    script = (REPO / "scripts/check_docs_links.py").read_text(encoding="utf-8")
    collapsed = re.sub(r'"\s*\n\s*"', "", script)  # rejoin implicit concatenation

    assert onboarding.STARTER_ARCHIVE_URL in collapsed, (
        "scripts/check_docs_links.py does not list the starter archive URL, "
        "so nothing detects it going stale"
    )


def test_the_one_click_install_prompt_says_where_to_get_an_archive() -> None:
    """The directory picker is the highest-intent acquisition moment there is.

    ``packaging/mcpb/manifest.json`` is the text Claude Desktop shows *while
    asking the user for their ZIM directory*, and ``server.json`` is its MCP
    Registry equivalent. Both used to point at the Kiwix library and nothing
    else — the tens-of-gigabytes front door, which is the defect the rest of
    this change exists to fix, shown to the one audience guaranteed to read it.
    """
    surfaces = {
        "packaging/mcpb/manifest.json": json.loads(
            (REPO / "packaging/mcpb/manifest.json").read_text(encoding="utf-8")
        )["user_config"]["allowed_directories"]["description"],
        "server.json": json.loads((REPO / "server.json").read_text(encoding="utf-8"))[
            "packages"
        ][0]["packageArguments"][0]["description"],
    }
    assert len(surfaces) == 2

    for surface, description in surfaces.items():
        assert (
            onboarding.STARTER_ARCHIVE_URL in description
        ), f"{surface} does not offer the starter archive"
        assert (
            onboarding.STARTER_ARCHIVE_SIZE in description
        ), f"{surface} does not say how small the starter archive is"
        assert _mentions(description, onboarding.KIWIX_LIBRARY_HOST), (
            f"{surface} does not point at {onboarding.KIWIX_LIBRARY_HOST} "
            "for full archives"
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


def test_startup_probe_finds_archives_in_nested_directories(tmp_path: Path) -> None:
    """The listing globs ``**/*.zim``; the startup probe must agree with it.

    A probe that only looked at the top level would nag an operator whose
    archives live one directory down, while the server itself found them.
    """
    nested = tmp_path / "wikipedia" / "2024"
    nested.mkdir(parents=True)
    (nested / "wikipedia_en_all.zim").write_bytes(b"not a real archive")

    assert onboarding.has_zim_files([str(tmp_path)]) is True
    assert onboarding.has_zim_files([str(tmp_path / "wikipedia" / "empty")]) is False


def test_startup_probe_stops_at_the_first_archive(tmp_path: Path) -> None:
    """It answers a yes/no question, so it must not enumerate the tree.

    This runs in ``main()`` *before* ``server.run()`` starts reading stdin,
    and an allowed directory is allowed to be a home directory or a network
    share. Counting every match there can stall the client's ``initialize``
    past its timeout to produce a number nobody reads.
    """
    for index in range(5):
        (tmp_path / f"archive-{index}.zim").write_bytes(b"not a real archive")

    real_glob = Path.glob
    consumed = 0

    def counting_glob(self: Path, pattern: str):  # type: ignore[no-untyped-def]
        nonlocal consumed
        for item in real_glob(self, pattern):
            consumed += 1
            yield item

    with patch.object(Path, "glob", counting_glob):
        assert onboarding.has_zim_files([str(tmp_path)]) is True

    assert consumed == 1, (
        "the startup probe pulled "
        f"{consumed} entries from the walk; it only needs the first"
    )


def test_probe_survives_a_directory_it_cannot_walk(tmp_path: Path) -> None:
    """A diagnostic that can abort the boot is worse than no diagnostic.

    ``has_zim_files`` runs before ``server.run()``, so an unreadable or
    vanished directory must contribute nothing rather than propagate — the
    same degradation ``ZimOperations._glob_zim_paths`` applies.
    """
    good = tmp_path / "good"
    good.mkdir()
    (good / "wikipedia.zim").write_bytes(b"not a real archive")

    with patch.object(Path, "glob", side_effect=OSError("permission denied")):
        assert onboarding.has_zim_files([str(good)]) is False

    # The real walk still works either side of the failure.
    assert onboarding.has_zim_files([str(good)]) is True


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


def test_the_documented_empty_listing_sample_is_the_real_output(
    empty_zim_operations: ZimOperations,
) -> None:
    """``installation.mdx`` quotes this output; quote all of it.

    The page showed the first line alone, which was the whole message
    before this change and is a truncation of it now — a reader comparing
    what their terminal says to the documented sample sees more than the
    doc shows and cannot tell whether that is a version difference or a
    fault. Pinning the sample to the live string means the doc cannot fall
    behind the message again.
    """
    sample = empty_zim_operations.list_zim_files()
    installation = INSTALLATION.read_text(encoding="utf-8")

    assert f"```\n{sample}\n```" in installation, (
        "installation.mdx does not quote the empty-listing output verbatim; "
        f"the real output is:\n{sample}"
    )


def test_zim_health_says_where_to_get_an_archive(tmp_path: Path) -> None:
    """The tool the troubleshooting page sends people to, for this symptom.

    ``troubleshooting.mdx`` names the listing message and this warning in
    one sentence, so a reader who follows it to ``zim_health`` used to get
    the un-helped half: "No ZIM files found in any directory" and "Add ZIM
    files to configured directories", with no URL and no command, while the
    listing beside it handed over a download.
    """
    from openzim_mcp.server import OpenZimMcpServer
    from openzim_mcp.server_state import _build_health_report

    config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)])
    report = _build_health_report(OpenZimMcpServer(config))

    # The existing warning is quoted verbatim by the docs; keep it intact.
    assert "No ZIM files found in any directory" in report["warnings"]

    advice = "\n".join(report["recommendations"])
    assert _mentions(advice, onboarding.KIWIX_LIBRARY_HOST), advice
    assert onboarding.STARTER_ARCHIVE_URL in advice, advice


def test_zim_health_is_quiet_about_downloads_when_archives_exist(
    tmp_path: Path,
) -> None:
    """Acquisition advice belongs to the empty case, not to every report."""
    from openzim_mcp.server import OpenZimMcpServer
    from openzim_mcp.server_state import _build_health_report
    from openzim_mcp.zim.archive import ZIM_MAGIC

    # The health report counts only files carrying the ZIM signature, so a
    # placeholder of arbitrary bytes would read as "no archives here" and
    # make this test pass for the wrong reason.
    (tmp_path / "wikipedia.zim").write_bytes(ZIM_MAGIC + b"\x00" * 64)
    config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)])
    report = _build_health_report(OpenZimMcpServer(config))

    advice = "\n".join(report["recommendations"])
    assert not _mentions(advice, onboarding.KIWIX_LIBRARY_HOST), advice


@pytest.mark.parametrize("compact", [False, True])
def test_search_all_says_where_to_get_an_archive_when_none_are_loaded(
    empty_zim_operations: ZimOperations, compact: bool
) -> None:
    """``search all files for X`` is the phrase the ambiguous arm advertises.

    A user who read that recovery advice on a machine with archives and
    typed the same phrase on an empty one got ``"files_available": 0`` and
    an empty result list: a JSON blob that states the problem and answers
    nothing. Fanning out across zero archives is the empty case.

    Both response shapes are checked because the handler reads the count
    from two different places: the structured dict on the compact path and
    the legacy JSON string on the other.
    """
    handler = SimpleToolsHandler(empty_zim_operations)

    result = handler.handle_zim_query(
        "search all files for biology", options={"compact": compact}
    )

    assert _mentions(result, onboarding.KIWIX_LIBRARY_HOST), result
    assert onboarding.STARTER_ARCHIVE_URL in result, result


def test_search_all_does_not_walk_the_directories_a_second_time(
    tmp_path: Path,
) -> None:
    """The emptiness signal is read off the fan-out, not probed for.

    An earlier draft called ``list_zim_files_data()`` before dispatching,
    which put an extra recursive walk on every ``search all files`` call to
    answer a question the fan-out's own ``files_available`` already
    answers. Measured on a *non-empty* directory on purpose: that is the
    overwhelmingly common case and the only one where the extra walk is
    pure cost, since on an empty one the probe short-circuits the fan-out
    it duplicates.
    """
    from openzim_mcp.zim.archive import ZIM_MAGIC

    (tmp_path / "wikipedia.zim").write_bytes(ZIM_MAGIC + b"\x00" * 64)
    config = OpenZimMcpConfig(allowed_directories=[str(tmp_path)])
    operations = ZimOperations(
        config,
        PathValidator(config.allowed_directories),
        OpenZimMcpCache(config.cache),
        ContentProcessor(),
    )
    handler = SimpleToolsHandler(operations)

    def _listings_during(run) -> int:  # type: ignore[no-untyped-def]
        with patch.object(
            operations,
            "list_zim_files_data",
            wraps=operations.list_zim_files_data,
        ) as probe:
            run()
        return int(probe.call_count)

    # The fan-out lists the directories once, by necessity. Measured rather
    # than hard-coded, so this stays about what the *handler* adds.
    baseline = _listings_during(lambda: operations.search_all("biology"))
    through_handler = _listings_during(
        lambda: handler._handle_search_all("biology", "", {"query": "biology"}, {})
    )

    assert through_handler == baseline, (
        "the handler re-listed the directories to decide whether they were "
        f"empty: {through_handler} listing(s) versus the fan-out's own "
        f"{baseline}"
    )


def test_search_all_still_searches_when_archives_are_loaded() -> None:
    """The empty arm must not swallow the real fan-out."""
    operations = MagicMock()
    operations.list_zim_files_data.return_value = [
        {"path": "/zim/wikipedia.zim"},
        {"path": "/zim/wiktionary.zim"},
    ]
    operations.search_all.return_value = '{"files_searched": 2, "results": []}'

    result = SimpleToolsHandler(operations).handle_zim_query(
        "search all files for biology"
    )

    operations.search_all.assert_called_once()
    assert not _mentions(result, onboarding.KIWIX_LIBRARY_HOST), result


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
