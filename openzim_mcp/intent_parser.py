"""Intent parsing for the OpenZIM MCP simple-tools handler.

This module contains the regex-heavy, pure-parsing layer that turns a
natural-language query into a structured ``(intent, params, confidence)``
tuple. It intentionally has no dependency on :mod:`openzim_mcp.zim_operations`
or any I/O, which makes it cheap to unit-test in isolation.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from .constants import REGEX_TIMEOUT_SECONDS
from .exceptions import RegexTimeoutError
from .timeout_utils import run_with_timeout

logger = logging.getLogger(__name__)

__all__ = [
    "IntentParser",
    "safe_regex_search",
    "safe_regex_findall",
]


def safe_regex_search(
    pattern: str,
    text: str,
    flags: int = 0,
    timeout_seconds: float = REGEX_TIMEOUT_SECONDS,
) -> Optional[re.Match[str]]:
    """Perform a regex search with cross-platform timeout protection.

    Always uses a threading-based timeout so it works on every platform and
    on any thread (asyncio executors, worker threads, etc.). Signal-based
    timeouts are not safe outside the main thread.

    Args:
        pattern: Regular expression pattern
        text: Text to search
        flags: Regex flags (e.g., re.IGNORECASE)
        timeout_seconds: Maximum time allowed for the operation

    Returns:
        Match object if found, None otherwise

    Raises:
        RegexTimeoutError: If the operation exceeds the time limit
    """
    return run_with_timeout(
        lambda: re.search(pattern, text, flags),
        timeout_seconds,
        f"Regex operation timed out after {timeout_seconds} seconds",
        RegexTimeoutError,
    )


# Character class covering ASCII and common Unicode "smart" quotes that LLMs
# and copy-pasted text frequently use. Used wherever we extract a quoted token
# from a user query.
_QUOTE_CHARS = "'\"‘’“”"
_QUOTE_OPEN = f"[{_QUOTE_CHARS}]"
_QUOTE_NOT = f"[^{_QUOTE_CHARS}]"


def safe_regex_findall(
    pattern: str,
    text: str,
    flags: int = 0,
    timeout_seconds: float = REGEX_TIMEOUT_SECONDS,
) -> List[Any]:
    """Find all regex matches with timeout protection.

    Same protections as safe_regex_search; returns the list of capture groups
    (re.findall semantics).
    """
    return run_with_timeout(
        lambda: re.findall(pattern, text, flags),
        timeout_seconds,
        f"Regex operation timed out after {timeout_seconds} seconds",
        RegexTimeoutError,
    )


# Per-intent parameter extractors. Each mutates ``params`` in place so the
# dispatching wrapper in ``IntentParser._extract_params`` stays small and the
# overall flow reads as one regex per intent rather than one giant if/elif.


def _extract_browse(query: str, params: Dict[str, Any]) -> None:
    namespace_match = safe_regex_search(
        r"namespace\s+['\"]?([A-Za-z0-9_.-]+)['\"]?",
        query,
        re.IGNORECASE,
    )
    if namespace_match:
        params["namespace"] = namespace_match.group(1)


def _extract_filtered_search(query: str, params: Dict[str, Any]) -> None:
    search_match = safe_regex_search(
        rf"(?:search|find|look)\s+(?:for\s+)?{_QUOTE_OPEN}?"
        rf"({_QUOTE_NOT}+?){_QUOTE_OPEN}?\s+(?:in|within)",
        query,
        re.IGNORECASE,
    )
    if search_match:
        params["query"] = search_match.group(1).strip()

    namespace_match = safe_regex_search(
        rf"namespace\s+{_QUOTE_OPEN}?([A-Za-z0-9_.-]+){_QUOTE_OPEN}?",
        query,
        re.IGNORECASE,
    )
    if namespace_match:
        params["namespace"] = namespace_match.group(1)

    type_match = safe_regex_search(
        rf"type\s+{_QUOTE_OPEN}?([A-Za-z0-9_/.-]+){_QUOTE_OPEN}?",
        query,
        re.IGNORECASE,
    )
    if type_match:
        params["content_type"] = type_match.group(1)


def _extract_entry_path_keyworded(query: str, params: Dict[str, Any]) -> None:
    """Shared extractor for get_article / structure / links / toc / summary."""
    quoted_match = safe_regex_search(
        rf"{_QUOTE_OPEN}({_QUOTE_NOT}+){_QUOTE_OPEN}", query
    )
    if quoted_match:
        params["entry_path"] = quoted_match.group(1)
        return

    # The keyword set intentionally excludes "contents" — for "table of
    # contents for Biology" we don't want "of contents" to capture
    # "contents". We use the LAST match rather than the first: queries
    # like "table of contents for Biology" have multiple keyword hits
    # ("of <stop-word>", "for <real-target>") and the trailing match is
    # the actual target the user named.
    path_pattern = r"(?:article|entry|page|of|for|in|from|to)" r"\s+([A-Za-z0-9_/.-]+)"
    path_matches = safe_regex_findall(path_pattern, query, re.IGNORECASE)
    if path_matches:
        params["entry_path"] = path_matches[-1]


def _extract_binary(query: str, params: Dict[str, Any]) -> None:
    quoted_match = safe_regex_search(
        rf"{_QUOTE_OPEN}({_QUOTE_NOT}+){_QUOTE_OPEN}", query
    )
    if quoted_match:
        params["entry_path"] = quoted_match.group(1)
    else:
        # "get binary content from I/image.png", "extract pdf I/document.pdf",
        # "retrieve image logo.png".
        binary_pattern = (
            r"(?:content|data|entry|from|of|for|"
            r"pdf|image|video|audio|media)"
            rf"\s+{_QUOTE_OPEN}?([A-Za-z0-9_/.-]+){_QUOTE_OPEN}?"
        )
        path_match = safe_regex_search(binary_pattern, query, re.IGNORECASE)
        if path_match:
            params["entry_path"] = path_match.group(1)

    metadata_match = safe_regex_search(
        r"\b(metadata|info)\s+only\b", query, re.IGNORECASE
    )
    if metadata_match:
        params["include_data"] = False


def _extract_suggestions(query: str, params: Dict[str, Any]) -> None:
    suggest_pattern = (
        r"(?:suggestions?|autocomplete|complete|hints?)"
        rf"\s+(?:for\s+)?{_QUOTE_OPEN}?({_QUOTE_NOT}+){_QUOTE_OPEN}?"
    )
    suggest_match = safe_regex_search(suggest_pattern, query, re.IGNORECASE)
    if suggest_match:
        params["partial_query"] = suggest_match.group(1).strip()


def _extract_search(query: str, params: Dict[str, Any]) -> None:
    search_match = safe_regex_search(
        rf"(?:search|find|look)\s+(?:for\s+)?"
        rf"{_QUOTE_OPEN}?({_QUOTE_NOT}+){_QUOTE_OPEN}?",
        query,
        re.IGNORECASE,
    )
    params["query"] = search_match.group(1).strip() if search_match else query


def _extract_search_all(query: str, params: Dict[str, Any]) -> None:
    """Strip "search all files for" prefix to recover the bare query.

    The lazy ``^.*?`` in the substitution is a known ReDoS vector on
    adversarial input, so wrap it in the standard timeout helper and
    fall back to the raw query on timeout — better to search a slightly
    noisy term than to hang the worker.
    """
    try:
        cleaned = run_with_timeout(
            lambda: re.sub(
                r"^.*?(search\s+(all|every(thing|where)?|across)"
                r"\s+(files?|zims?)?\s*for\s*)",
                "",
                query,
                flags=re.IGNORECASE,
            ),
            REGEX_TIMEOUT_SECONDS,
            f"Regex operation timed out after {REGEX_TIMEOUT_SECONDS} seconds",
            RegexTimeoutError,
        ).strip()
        params["query"] = cleaned
    except RegexTimeoutError:
        logger.warning(
            "Regex timeout while extracting search_all query " f"from: {query[:50]}..."
        )
        params["query"] = query.strip()


def _extract_walk_namespace(query: str, params: Dict[str, Any]) -> None:
    m = safe_regex_search(r"namespace\s+([A-Za-z])\b", query, re.IGNORECASE)
    if m:
        params["namespace"] = m.group(1).upper()


def _extract_find_by_title(query: str, params: Dict[str, Any]) -> None:
    m = safe_regex_search(
        r"(?:titled|named|called|path\s+for)\s+(.+?)$", query, re.IGNORECASE
    )
    if m:
        params["title"] = m.group(1).strip().rstrip("?.")


def _extract_related(query: str, params: Dict[str, Any]) -> None:
    m = safe_regex_search(
        r"(?:related\s+to|linking\s+to|links\s+(?:to|from))\s+(.+?)$",
        query,
        re.IGNORECASE,
    )
    if m:
        params["entry_path"] = m.group(1).strip().rstrip("?.")


def _extract_get_zim_entries(query: str, params: Dict[str, Any]) -> None:
    """Extract namespace/path tokens like ``A/Foo`` or ``M/Image.png``.

    Uppercase namespace letter is required, which excludes file paths
    like ``wikipedia.zim`` but matches ZIM entry paths.
    """
    entries = safe_regex_findall(r"[A-Z]/[\w\-./%]+", query)
    if entries:
        # Strip trailing sentence punctuation that the character class
        # greedily captures (e.g. "A/Bar." -> "A/Bar").
        params["entries"] = [e.rstrip(".?,;:!") for e in entries]


_PARAM_EXTRACTORS = {
    "browse": _extract_browse,
    "filtered_search": _extract_filtered_search,
    "get_article": _extract_entry_path_keyworded,
    "structure": _extract_entry_path_keyworded,
    "links": _extract_entry_path_keyworded,
    "toc": _extract_entry_path_keyworded,
    "summary": _extract_entry_path_keyworded,
    "binary": _extract_binary,
    "suggestions": _extract_suggestions,
    "search": _extract_search,
    "search_all": _extract_search_all,
    "walk_namespace": _extract_walk_namespace,
    "find_by_title": _extract_find_by_title,
    "related": _extract_related,
    "get_zim_entries": _extract_get_zim_entries,
}


class IntentParser:
    """Parse natural language queries to determine user intent."""

    # Intent patterns with priority, confidence scores, and intent type
    # Format: (pattern, intent, base_confidence, specificity_weight)
    # specificity_weight: higher = more specific pattern, used for tie-breaking
    INTENT_PATTERNS = [
        # File listing - very specific
        (
            r"\b(list|show|what|available|get)\s+(files?|zim|archives?)\b",
            "list_files",
            0.95,
            10,
        ),
        # Metadata - specific keywords
        (r"\b(metadata|info|details?)\s+(for|about|of)\b", "metadata", 0.9, 9),
        (r"\binfo\s+about\b", "metadata", 0.9, 9),
        # Main page - very specific
        (r"\b(main|home|start)\s+page\b", "main_page", 0.95, 10),
        # Namespace listing - very specific
        (r"\b(list|show|what)\s+namespaces?\b", "list_namespaces", 0.95, 10),
        # Browse - moderately specific
        (
            r"\b(browse|explore|show|list)\s+(namespace|articles?|entries)\b",
            "browse",
            0.85,
            7,
        ),
        # Article structure - moderately specific
        (
            r"\b(structure|outline|sections?|headings?)\s+(of|for)?\b",
            "structure",
            0.85,
            8,
        ),
        # Table of contents - specific
        (r"\b(table\s+of\s+contents|toc|contents)\s*(of|for)?\b", "toc", 0.95, 10),
        # Summary - specific
        (
            r"\b(summary|summarize|summarise|overview|brief)\s*(of|for)?\b",
            "summary",
            0.9,
            9,
        ),
        # Links - moderately specific
        (r"\b(links?|references?|related)\s+(in|from|to)\b", "links", 0.85, 7),
        # Binary/media - specific keywords
        (
            r"\b(get|retrieve|download|extract|fetch)\s+"
            r"(binary|raw|pdf|image|video|audio|media)\b",
            "binary",
            0.9,
            9,
        ),
        (r"\b(binary|raw)\s+(content|data)\s+(for|from|of)\b", "binary", 0.9, 9),
        # Suggestions - moderately specific
        (
            r"\b(suggestions?|autocomplete|complete|hints?)\s+(for|of)?\b",
            "suggestions",
            0.85,
            7,
        ),
        # Filtered search - less specific
        (
            r"\b(search|find|look)\s+.+\s+(in|within)\s+(namespace|type)\b",
            "filtered_search",
            0.8,
            6,
        ),
        # Get multiple entries (batch) - explicit plural cue, beats singular.
        # Singular `(article|entry|page)\b` won't match plural `articles` /
        # `entries` because of the word-boundary, so this pattern lights up
        # only on plural cues.
        (
            r"\b(get|fetch|retrieve|read)\s+(articles|entries|multiple)\b",
            "get_zim_entries",
            0.9,
            8,
        ),
        # Get article - common words
        (
            r"\b(get|show|read|display|fetch)\s+(article|entry|page)\b",
            "get_article",
            0.75,
            5,
        ),
        # search_all - very specific
        (
            r"\bsearch\s+(all|every(thing|where)?|across)\s+(files?|zims?)?\b",
            "search_all",
            0.95,
            10,
        ),
        # walk_namespace - very specific
        (
            r"\b(walk|iterate|dump|enumerate)\s+namespace\b",
            "walk_namespace",
            0.95,
            10,
        ),
        # find_by_title - moderately specific
        (
            r"\b(find|locate|resolve)\s+(article|entry|page)?"
            r"\s*(titled|named|called)\b",
            "find_by_title",
            0.9,
            8,
        ),
        (r"\bwhat'?s\s+the\s+path\s+for\b", "find_by_title", 0.9, 8),
        # related - moderately specific
        (
            r"\b(related\s+to|articles?\s+linking\s+to|what\s+links\s+(to|from))\b",
            "related",
            0.9,
            8,
        ),
        # Search - general fallback
        (r"\b(search|find|look\s+for|query)\b", "search", 0.7, 3),
    ]

    @classmethod
    def parse_intent(cls, query: str) -> Tuple[str, Dict[str, Any], float]:
        """Parse a natural language query to determine intent.

        This method collects ALL matching patterns and uses a weighted scoring
        system to select the best match. This prevents earlier patterns from
        incorrectly shadowing more specific patterns that match later.

        Args:
            query: Natural language query string

        Returns:
            Tuple of (intent_type, extracted_params, confidence_score)
        """
        query_lower = query.lower()

        # Collect all matching patterns
        matches: List[Tuple[str, Dict[str, Any], float, int]] = []

        for pattern, intent, base_confidence, specificity in cls.INTENT_PATTERNS:
            try:
                match = safe_regex_search(pattern, query_lower, re.IGNORECASE)
                if match:
                    params = cls._extract_params(query, intent)
                    # Boost confidence only when params extract AND base is
                    # below 0.8 — the boost is a tie-breaker for ambiguous
                    # low-priority matches, not a way to lift them above
                    # high-priority param-less intents (M17). Cap at 0.85
                    # to keep low-priority + boost strictly below high-base
                    # intents (>= 0.9).
                    confidence = base_confidence
                    if (
                        base_confidence < 0.8
                        and params
                        and any(v for v in params.values() if v)
                    ):
                        confidence = min(base_confidence + 0.05, 0.85)
                    matches.append((intent, params, confidence, specificity))
            except RegexTimeoutError:
                logger.warning(f"Regex timeout for pattern: {pattern[:30]}...")
                continue

        if not matches:
            # Default to search
            return "search", {"query": query}, 0.5

        # Select best match using weighted scoring
        # Primary: confidence, Secondary: specificity
        best_match = cls._select_best_match(matches)
        return best_match[0], best_match[1], best_match[2]

    @classmethod
    def _select_best_match(
        cls, matches: List[Tuple[str, Dict[str, Any], float, int]]
    ) -> Tuple[str, Dict[str, Any], float]:
        """Select the best match from multiple matching patterns.

        Uses a weighted scoring algorithm:
        - Primary factor: confidence score (0-1)
        - Secondary factor: specificity weight (normalized to 0-1)
        - Combined score = confidence * 0.7 + (specificity / 10) * 0.3

        Args:
            matches: List of (intent, params, confidence, specificity) tuples

        Returns:
            Best match as (intent, params, confidence) tuple
        """
        if len(matches) == 1:
            intent, params, confidence, _ = matches[0]
            return intent, params, confidence

        # Calculate combined scores
        scored_matches = []
        for intent, params, confidence, specificity in matches:
            # Normalize specificity to 0-1 range (max specificity is 10)
            normalized_specificity = specificity / 10.0
            # Weighted combination: 70% confidence, 30% specificity
            combined_score = (confidence * 0.7) + (normalized_specificity * 0.3)
            scored_matches.append((intent, params, confidence, combined_score))

        # Sort by combined score (descending)
        scored_matches.sort(key=lambda x: x[3], reverse=True)

        # Log multi-match resolution for debugging
        if len(matches) > 1:
            logger.debug(
                f"Multi-match resolution: {len(matches)} patterns matched, "
                f"selected '{scored_matches[0][0]}' "
                f"with score {scored_matches[0][3]:.3f}"
            )

        best = scored_matches[0]
        return best[0], best[1], best[2]

    @classmethod
    def _extract_params(cls, query: str, intent: str) -> Dict[str, Any]:
        """Extract parameters from query based on intent.

        Uses cross-platform timeout protection to prevent ReDoS attacks.

        Args:
            query: Original query string
            intent: Detected intent type

        Returns:
            Dictionary of extracted parameters
        """
        params: Dict[str, Any] = {}
        extractor = _PARAM_EXTRACTORS.get(intent)
        if extractor is None:
            return params

        try:
            extractor(query, params)
        except RegexTimeoutError:
            logger.warning(
                f"Regex timeout during param extraction for intent {intent}: "
                f"{query[:50]}..."
            )
            # Caller handles missing params gracefully.
            return {}

        return params
