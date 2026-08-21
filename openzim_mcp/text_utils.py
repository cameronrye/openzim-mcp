"""Small shared text helpers with no package-internal dependencies."""

from __future__ import annotations

import re
from typing import Set

#: Minimum token length for relevance/overlap comparisons. Shorter tokens
#: (``a``, ``of``, ``to``) are too common to discriminate topics.
RELEVANCE_TOKEN_MIN_LEN = 3

_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Site-scraped archives (zimit / warc2zim) suffix every title with the site
#: name: ``Diabetes | Type 1 Diabetes | MedlinePlus``, ``Virtue Ethics |
#: Internet Encyclopedia of Philosophy``. The head before the first
#: separator is the article's own name.
SITE_SUFFIX_SEPARATOR = " | "


def strip_site_suffix(title: str) -> str:
    """Return the article's own name from a site-suffixed title.

    ``Plato | Internet Encyclopedia of Philosophy`` -> ``Plato``; a title
    without the separator is returned unchanged (stripped).
    """
    head, sep, _tail = title.partition(SITE_SUFFIX_SEPARATOR)
    return (head if sep else title).strip()


def tokenize_for_relevance(
    text: str, *, min_len: int = RELEVANCE_TOKEN_MIN_LEN
) -> Set[str]:
    """Return the set of lowercase alphanumeric tokens in ``text`` whose
    length is at least ``min_len``. Used for cheap topic-overlap checks
    (search relevance scoring, cursor query-continuity)."""
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= min_len}
