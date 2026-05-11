"""Shared title-promotion helpers.

Several operations need the same logic: "given a topic and a list of
search hits, is the top hit actually the canonical article for the
topic, and if not, can we find one?" Extracted here so
``tell me about``, ``synthesize``, and ``search`` all share the same
decision rather than re-deriving it.

The match decision (:func:`is_strong_title_match`) was originally the
``_is_strong_title_match`` static on the simple-tools handler; the
title-index promotion (:func:`find_title_match`) was
``_find_title_match_for_topic``. Both moved here unchanged in v2.0.0a9
so the synthesize and search-result paths can reuse them without
importing the simple-tools handler.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def is_strong_title_match(topic: str, path: str, title: str) -> bool:
    """Return True iff ``path`` or ``title`` looks like the article for ``topic``.

    Tokenizes both sides on alphanumerics (so ``"Martin_Luther_King_Jr."``
    and ``"Martin Luther King Jr."`` both yield
    ``("martin", "luther", "king", "jr")``), then accepts the match when
    the token lists are either equal or one is a prefix of the other.
    The 3-char-minimum guard prevents ``"Pi"`` from prefix-matching
    ``"Pizza"`` while still allowing exact short-topic matches.
    """
    topic_tokens = tuple(_TOKEN_RE.findall(topic.lower()))
    if not topic_tokens:
        return False

    for candidate in (path, title):
        if not candidate:
            continue
        cand_tokens = tuple(_TOKEN_RE.findall(candidate.lower()))
        if not cand_tokens:
            continue
        if topic_tokens == cand_tokens:
            return True
        if sum(len(t) for t in topic_tokens) < 3:
            continue
        if cand_tokens[: len(topic_tokens)] == topic_tokens:
            return True
        if topic_tokens[: len(cand_tokens)] == cand_tokens:
            return True
    return False


def find_title_match(
    zim_operations: Any,
    zim_file_path: str,
    topic: str,
    *,
    cross_file: bool = False,
) -> Optional[Dict[str, Any]]:
    """Ask the title index whether ``topic`` resolves to a score-1.0 entry.

    Returns ``{"path": ..., "title": ..., "zim_file": ...}`` when an
    exact-title match exists; ``None`` otherwise. Used by callers that
    want to promote the canonical article past a noisy BM25 ranking
    (``List of songs about Berlin`` outranks ``Berlin`` for the query
    ``Berlin`` on Wikipedia because title-match boost isn't strong
    enough). Score 1.0 is the safe promotion threshold — lower-confidence
    matches (0.95, fuzzy 0.85) can introduce false positives like
    ``Java`` → ``Java (programming language)``.

    ``cross_file=True`` searches across all configured archives. Errors
    in the backend are logged and swallowed so a transient failure
    blanks the promotion path rather than the whole response.
    """
    try:
        data = zim_operations.find_entry_by_title_data(
            zim_file_path, topic, cross_file=cross_file, limit=3
        )
    except Exception as e:
        logger.debug("find_title_match: find_entry_by_title_data failed: %s", e)
        return None
    results = data.get("results") if isinstance(data, dict) else None
    if not results:
        return None
    top = results[0]
    if not isinstance(top, dict):
        return None
    if float(top.get("score", 0.0)) < 1.0:
        return None
    return {
        "path": str(top.get("path", "")),
        "title": str(top.get("title", "")),
        "zim_file": str(top.get("zim_file", zim_file_path)),
    }
