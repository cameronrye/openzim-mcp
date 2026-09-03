"""Where a first ZIM archive comes from, stated once.

The server is inert without an archive, and the three places that have to
say so — the startup log, the empty-listing tool result, and the
no-archive-selected gate — used to say nothing useful, or would each have
grown their own copy of the same URL. They share this module instead, and
``tests/test_onboarding_zim_acquisition.py`` holds the README and the docs
site to the same values, so the command a user is given is the command
that was last verified.

The starter archive is a real 13.6 MB extract of English Wikipedia on
climate change from the openZIM project's own testing suite: a stable
raw.githubusercontent URL, no account, nothing to install. Verified
2026-09-03: HTTP 200, 14,239,035 bytes.
"""

from __future__ import annotations

import logging
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

#: Human-readable size, stated identically in the README and on the docs
#: site (14,239,035 bytes).
STARTER_ARCHIVE_SIZE = "13.6 MB"

#: The download, as a single copy-pasteable line.
STARTER_ARCHIVE_COMMAND = (
    f"curl -fsSL -o ~/zim-files/{STARTER_ARCHIVE_FILENAME} {STARTER_ARCHIVE_URL}"
)


def count_zim_files(directories: Iterable[str]) -> int:
    """Count discoverable ``.zim`` files across ``directories``.

    Mirrors the ``glob("**/*.zim")`` traversal that
    ``ZimOperations._glob_zim_paths`` uses for the real listing — a
    top-level-only count would nag an operator whose archives sit one
    directory down while the server itself found them fine.

    Never raises: a directory that cannot be walked contributes nothing,
    exactly as it does in the listing. This runs on the startup path, and
    a diagnostic that can abort a boot is worse than no diagnostic.
    """
    total = 0
    for directory in directories:
        try:
            total += sum(1 for _ in Path(directory).glob("**/*.zim"))
        except Exception as exc:  # noqa: BLE001 — a hint must never abort boot
            logger.debug("ZIM count failed for %s: %s", directory, exc)
    return total


def no_archives_log_message(directories: Iterable[str]) -> str:
    """The startup warning for a directory tree holding no archives.

    Emitted through the logger — and therefore stderr — never ``print``:
    under the default stdio transport stdout carries the JSON-RPC stream,
    and prose written there corrupts it for every stdio client.
    """
    listed = ", ".join(directories) or "(none)"
    return (
        "0 ZIM files found in the allowed directories (%s) — the server will "
        "start but every query will come back empty. Browse %s for full "
        "archives, or get a %s starter archive with: %s"
        % (
            listed,
            KIWIX_LIBRARY_URL,
            STARTER_ARCHIVE_SIZE,
            STARTER_ARCHIVE_COMMAND,
        )
    )


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
        "- Then point the server's allowed directory at where you saved it"
    )
