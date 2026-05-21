"""Loader for sub-D-2 query-rewrite data files.

Module-level functions cached with ``lru_cache`` so the data is read
exactly once per (file path) per process. None paths load the bundled
defaults via ``importlib.resources``."""

from __future__ import annotations

import functools
import logging
from importlib import resources
from pathlib import Path
from typing import FrozenSet, Mapping, Optional

logger = logging.getLogger(__name__)

_HARD_CAP_MAP_ENTRIES = 500
_HARD_CAP_EXCLUSIONS = 200


def _read_lines(path: Optional[Path], bundled_name: str) -> list[str]:
    if path is not None:
        text = Path(path).read_text(encoding="utf-8")
    else:
        # importlib.resources gives a clean handle on bundled package data.
        text = (
            resources.files("openzim_mcp.data")
            .joinpath(bundled_name)
            .read_text(encoding="utf-8")
        )
    return text.splitlines()


@functools.lru_cache(maxsize=8)
def load_misspellings(path: Optional[Path]) -> Mapping[str, str]:
    """Load a misspellings map. ``path=None`` loads the bundled default.

    Format: ``wrong=right`` per line. ``#`` starts a comment. Blank
    lines and malformed lines (no ``=``) are silently skipped so a
    typo in the data file doesn't blow up the server at import time.

    Hard-capped at 500 entries; entries beyond the cap are dropped
    with a logged warning."""
    mapping: dict[str, str] = {}
    overflow = 0
    for raw in _read_lines(path, "misspellings.txt"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        wrong, _, right = line.partition("=")
        wrong = wrong.strip().lower()
        right = right.strip().lower()
        if not wrong or not right:
            continue
        if len(mapping) >= _HARD_CAP_MAP_ENTRIES:
            overflow += 1
            continue
        mapping[wrong] = right
    if overflow:
        logger.warning(
            "query_rewrite_data: %d misspelling entries dropped (cap %d)",
            overflow,
            _HARD_CAP_MAP_ENTRIES,
        )
    return mapping


@functools.lru_cache(maxsize=8)
def load_exclusions(path: Optional[Path]) -> FrozenSet[str]:
    """Load the misspelling-substitution exclusions. ``path=None`` loads
    the bundled default. Returns a frozenset of lowercase tokens that
    rule 2 will refuse to substitute even when listed in the map."""
    items: set[str] = set()
    for raw in _read_lines(path, "misspellings_exclusions.txt"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if len(items) >= _HARD_CAP_EXCLUSIONS:
            logger.warning(
                "query_rewrite_data: exclusions cap %d hit; remainder dropped",
                _HARD_CAP_EXCLUSIONS,
            )
            break
        items.add(line.lower())
    return frozenset(items)
