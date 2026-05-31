"""Small shared text helpers with no package-internal dependencies."""

from __future__ import annotations

import re
from typing import Set

#: Minimum token length for relevance/overlap comparisons. Shorter tokens
#: (``a``, ``of``, ``to``) are too common to discriminate topics.
RELEVANCE_TOKEN_MIN_LEN = 3

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize_for_relevance(
    text: str, *, min_len: int = RELEVANCE_TOKEN_MIN_LEN
) -> Set[str]:
    """Return the set of lowercase alphanumeric tokens in ``text`` whose
    length is at least ``min_len``. Used for cheap topic-overlap checks
    (search relevance scoring, cursor query-continuity)."""
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= min_len}
