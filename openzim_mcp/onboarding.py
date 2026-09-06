"""Where a first ZIM archive comes from, stated once.

The server is inert without an archive, and every place that has to say so
— the startup log, the empty-listing tool result, the no-archive-selected
gate, the zero-archive ``search all files`` fan-out and the ``zim_health``
report — used to say nothing useful, or would each have grown its own copy
of the same URL. They share this module instead, and
``tests/test_onboarding_zim_acquisition.py`` holds the README, the docs
site, the ``.mcpb`` bundle and ``server.json`` to the same values, so the
command a user is given is the command that was last verified.

The starter archive is a real 13.6 MB extract of English Wikipedia on
climate change from the openZIM project's own testing suite: a stable
raw.githubusercontent URL, no account, nothing to install. Verified
2026-09-03: HTTP 200, 14,239,035 bytes.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

#: Full library — everything past a first run lives here.
KIWIX_LIBRARY_URL = "https://browse.library.kiwix.org/"

#: Host alone, for prose and log lines that should stay one line.
KIWIX_LIBRARY_HOST = "browse.library.kiwix.org"

STARTER_ARCHIVE_FILENAME = "wikipedia_en_climate_change_mini_2024-06.zim"

STARTER_ARCHIVE_URL = (
    "https://raw.githubusercontent.com/openzim/zim-testing-suite/main/data/withns/"
    + STARTER_ARCHIVE_FILENAME
)

#: Where the documented command puts the archive — and therefore the
#: directory every documented invocation has to point the server at. The
#: README used to download into this directory and then configure the
#: server against a ``/path/to/zim/files`` placeholder, so following it
#: top-to-bottom produced "Directory does not exist".
STARTER_ARCHIVE_DIR = "~/zim-files"

#: The two facts a reader can verify for themselves, and the ones the docs
#: quote. ``STARTER_ARCHIVE_SIZE`` is derived from the byte count rather
#: than restated independently of it (see the test).
STARTER_ARCHIVE_BYTES = 14_239_035
STARTER_ARCHIVE_SHA256 = (
    "72db7ae7708d3a4cff918495078901ec027b14b427433a2328286ec130d1c43b"
)

#: Human-readable size, stated identically in the README and on the docs
#: site (14,239,035 bytes).
STARTER_ARCHIVE_SIZE = "13.6 MB"

#: The download, as a single copy-pasteable line.
#:
#: The ``mkdir -p`` is not decoration: ``curl -o`` into a directory that
#: does not exist yet aborts with ``curl: (23) Failure writing output to
#: destination``, and this text is shown *only* to people whose archive
#: situation is already broken, so it has to work on the first paste. The
#: README has carried the ``mkdir`` line as a separate command since the
#: block was written; the runtime copy did not.
STARTER_ARCHIVE_COMMAND = (
    f"mkdir -p {STARTER_ARCHIVE_DIR} && "
    f"curl -fsSL -o {STARTER_ARCHIVE_DIR}/{STARTER_ARCHIVE_FILENAME} "
    f"{STARTER_ARCHIVE_URL}"
)


def has_zim_files(directories: Iterable[str]) -> bool:
    """True as soon as one discoverable ``.zim`` file is found.

    Mirrors the ``glob("**/*.zim")`` traversal that
    ``ZimOperations._glob_zim_paths`` uses for the real listing — a
    top-level-only probe would nag an operator whose archives sit one
    directory down while the server itself found them fine.

    Short-circuits on the first hit rather than counting every match: the
    only caller wants a yes/no, this runs on the boot path *before*
    ``server.run()`` starts reading stdin, and an allowed directory can
    legitimately be a home directory or a network share. Enumerating one
    of those to produce a number nobody reads can stall the client's
    ``initialize`` long enough to drop the connection.

    Never raises: a directory that cannot be walked contributes nothing,
    exactly as it does in the listing. A diagnostic that can abort a boot
    is worse than no diagnostic.
    """
    for directory in directories:
        try:
            if any(Path(directory).glob("**/*.zim")):
                return True
        except Exception as exc:  # noqa: BLE001 — a hint must never abort boot
            logger.debug("ZIM probe failed for %s: %s", directory, exc)
    return False


def unreadable_directories(directories: Iterable[str]) -> list[str]:
    """The configured directories this process cannot list at all.

    ``has_zim_files`` deliberately reports False for one of these — a
    diagnostic that can abort a boot is worse than no diagnostic, and
    ``Path.glob`` swallows the ``PermissionError`` on its own besides. But
    "0 ZIM files found, here is how to download one" is the opposite of
    the advice that fixes it: the archive is already there, the directory
    just cannot be opened. Downloading a second copy into it fails
    identically, which is the shape a Docker bind mount with the wrong
    ownership, a NAS mount, or macOS Full Disk Access takes.

    Probes with ``scandir`` rather than the ``glob`` walk because that
    walk is exactly what hides the failure. Never raises, for the same
    reason ``has_zim_files`` never raises; anything unexpected is simply
    not reported as a permission problem.
    """
    blocked: list[str] = []
    for directory in directories:
        try:
            path = Path(directory)
            if not path.is_dir():
                continue
            with os.scandir(path):
                pass
        except PermissionError as exc:
            # v3.3.1 field report follow-up: this used to catch bare ``OSError``
            # while the caller's message hardcodes "Permission denied", so any
            # unrelated OS failure (a stale NFS handle, ENOTDIR on a race) was
            # reported to the user as a permissions problem and sent them to
            # chmod something that was never the cause. Narrow the catch to the
            # one errno the wording actually describes; everything else falls
            # through to the debug-logged catch-all below and is simply not
            # claimed as a permission fault.
            logger.debug("ZIM directory %s is unreadable: %s", directory, exc)
            blocked.append(directory)
        except Exception as exc:  # noqa: BLE001 — a hint must never abort boot
            logger.debug("ZIM directory probe failed for %s: %s", directory, exc)
    return blocked


def acquisition_hint_line() -> str:
    """The guidance as one plain-text line, for logs and JSON string fields.

    ``zim_health`` returns JSON, so it cannot carry the markdown block
    below; it gets this instead, so the tool the troubleshooting page
    sends people to says the same thing as the listing beside it.
    """
    return (
        f"Browse {KIWIX_LIBRARY_URL} for full archives, or get a "
        f"{STARTER_ARCHIVE_SIZE} starter archive with: {STARTER_ARCHIVE_COMMAND}"
    )


def no_archives_log_message(directories: Iterable[str]) -> str:
    """The startup warning for a directory tree holding no archives.

    Emitted through the logger — and therefore stderr — never ``print``:
    under the default stdio transport stdout carries the JSON-RPC stream,
    and prose written there corrupts it for every stdio client.

    A directory that could not be read is named first, before the download
    command, because for that operator the download command is the wrong
    advice: it succeeds, lands the archive in a directory the server still
    cannot open, and reports "0 ZIM files" again.
    """
    directories = list(directories)
    listed = ", ".join(directories) or "(none)"
    message = (
        "0 ZIM files found in the allowed directories (%s) — the server will "
        "start but every query will come back empty. " % listed
    )
    blocked = unreadable_directories(directories)
    if blocked:
        message += (
            "Permission denied reading %s — an archive already in there is "
            "invisible to the server, so fix that directory's permissions "
            "before downloading anything. " % ", ".join(blocked)
        )
    return message + acquisition_hint_line()


def acquisition_hint_markdown() -> str:
    """The same guidance for a tool result, where a GUI client shows it.

    Claude Desktop and its peers keep stderr in a log file the user never
    opens, so the log line above is invisible to exactly the audience most
    likely to have no archive yet. This is the copy they do see.
    """
    return (
        "**Get an archive:**\n"
        f"- Browse [{KIWIX_LIBRARY_HOST}]({KIWIX_LIBRARY_URL}) for full "
        "archives (Wikipedia, Wiktionary, Stack Exchange, …)\n"
        f"- Or start with a {STARTER_ARCHIVE_SIZE} sample:\n"
        f"  `{STARTER_ARCHIVE_COMMAND}`\n"
        f"- Then point the server at `{STARTER_ARCHIVE_DIR}` "
        "(the directory that command fills)"
    )
