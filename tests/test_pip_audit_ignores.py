"""The pip-audit gate's accepted advisories (``.github/pip-audit-ignore.txt``).

Both consumers, the Security Scanning step in ``.github/workflows/test.yml``
and ``make security``, strip ``#`` comments and blank lines and pass every
remaining token to pip-audit as ``--ignore-vuln``. An entry that has outlived
its reason fails nothing: pip-audit stays green and the file goes on claiming
an exception nobody needs. So each block's exit condition is asserted here,
and the day it holds this fails, naming the block to delete.

The pillow block's other half of that condition, whether fastembed still caps
pillow below 13, needs fastembed's installed metadata, so it lives in
``tests/ml/test_pillow_cap.py``, which the ML job runs with the extra installed.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from packaging.version import Version

REPO = Path(__file__).resolve().parents[1]
IGNORE_FILE = REPO / ".github" / "pip-audit-ignore.txt"

# The ID shapes pip-audit reports as a vulnerability's primary id.
_ADVISORY_ID = re.compile(
    r"(CVE-\d{4}-\d{4,}|GHSA(-[23456789cfghjmpqrvwx]{4}){3}|PYSEC-\d{4}-\d+)"
)


def ignored_ids() -> list[str]:
    """Every ID the consumers pass, parsed the way their ``sed`` does."""
    ids = []
    for line in IGNORE_FILE.read_text(encoding="utf-8").splitlines():
        token = re.sub(r"\s", "", line.split("#", 1)[0])
        if token:
            ids.append(token)
    return ids


def _locked_version(name: str) -> Version:
    lock = tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))
    for package in lock["package"]:
        if package["name"] == name:
            return Version(package["version"])
    raise AssertionError(f"{name} not found in uv.lock")


def test_every_entry_is_one_well_formed_advisory_id() -> None:
    """One ID per line, no duplicates.

    Two IDs on one line would reach pip-audit glued into a single token that
    matches nothing, and the advisories behind both would start failing the
    gate with the file still listing them.
    """
    ids = ignored_ids()
    assert ids, "the ignore file lists nothing; delete it and its two consumers"
    malformed = [i for i in ids if not _ADVISORY_ID.fullmatch(i)]
    assert not malformed, f"not an advisory id: {malformed}"
    assert len(ids) == len(set(ids)), "duplicate ids in the ignore file"


def test_pillow_block_is_still_needed() -> None:
    """The pillow advisories are all fixed in 13.0.0.

    Once the lock reaches 13 they match nothing, and the block is a stale
    exception that reads as though pillow were still vulnerable.
    """
    pillow = _locked_version("pillow")
    assert pillow < Version("13.0.0"), (
        f"uv.lock now pins pillow {pillow}, which fixes every pillow advisory "
        "in .github/pip-audit-ignore.txt: delete the pillow block."
    )
