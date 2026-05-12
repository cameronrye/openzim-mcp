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
    the token lists are equal OR when one prefixes the other within
    reason. Two directions are valid:

    * **Candidate extends topic** (``Berlin`` → ``Berlin (city)``):
      unconditional. The candidate is the canonical article with a
      disambiguator; the topic is the bare term the model asked about.
    * **Topic extends candidate** (``Apollo 11 (mission)`` → ``Apollo_11``):
      bounded — the topic must carry at most one extra token beyond the
      candidate. This covers parenthetical disambiguation on the topic
      side (the model asked about ``Berlin (city)`` and we found
      ``Berlin``). Wider drops (``Martin Luther King`` → ``Martin``)
      are NOT accepted — a bare-first-name stub shouldn't outrank the
      canonical full-name article (H20 regression).

    The 3-char-minimum guard on each side prevents trivially-short
    tokens (``Pi``) from driving prefix matches.
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
        if sum(len(t) for t in cand_tokens) < 3:
            continue
        # Candidate-extends-topic — unconditional (canonical promotion).
        if cand_tokens[: len(topic_tokens)] == topic_tokens:
            return True
        # Topic-extends-candidate — bounded to a 1-token diff so
        # ``Apollo 11 (mission)`` → ``Apollo_11`` works but
        # ``Martin Luther King`` → ``Martin`` doesn't.
        diff = len(topic_tokens) - len(cand_tokens)
        if 0 < diff <= 1 and topic_tokens[: len(cand_tokens)] == cand_tokens:
            return True
    return False


def find_title_match(
    zim_operations: Any,
    zim_file_path: str,
    topic: str,
    *,
    cross_file: bool = False,
    min_score: float = 1.0,
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

    ``cross_file=True`` searches across all configured archives.
    ``min_score`` lets typo-tolerant callers (D3 fix:
    ``tell me about Photosythesis``) accept the fuzzy-fallback 0.85
    score the title index produces for single-edit typos. Errors in
    the backend are logged and swallowed so a transient failure blanks
    the promotion path rather than the whole response.
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
    if float(top.get("score", 0.0)) < min_score:
        return None
    return {
        "path": str(top.get("path", "")),
        "title": str(top.get("title", "")),
        "zim_file": str(top.get("zim_file", zim_file_path)),
    }
