"""Intent parsing for the OpenZIM MCP simple-tools handler.

This module contains the regex-heavy, pure-parsing layer that turns a
natural-language query into a structured ``(intent, params, confidence)``
tuple. It intentionally has no dependency on :mod:`openzim_mcp.zim_operations`
or any I/O, which makes it cheap to unit-test in isolation.
"""

import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .constants import REGEX_TIMEOUT_SECONDS
from .exceptions import RegexTimeoutError
from .query_rewrite_data import load_exclusions, load_misspellings
from .timeout_utils import run_with_timeout

logger = logging.getLogger(__name__)

__all__ = [
    "IntentParser",
    "safe_regex_search",
    "safe_regex_findall",
    "safe_regex_sub",
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


def safe_regex_sub(
    pattern: Union[str, "re.Pattern[str]"],
    repl: Union[str, Callable[["re.Match[str]"], str]],
    text: str,
    flags: int = 0,
    timeout_seconds: float = REGEX_TIMEOUT_SECONDS,
) -> str:
    """re.sub with cross-platform timeout protection.

    Accepts either a string pattern or a pre-compiled :class:`re.Pattern`.
    When a pre-compiled pattern is passed, ``flags`` is ignored (use the
    pattern's own flags). Same threading-based timeout as
    :func:`safe_regex_search`.

    Used by the compact-rendering layer to defang catastrophic-backtracking
    risk on adversarial article bodies (long unclosed markdown links,
    pathological snippet headers, etc.).
    """
    if isinstance(pattern, re.Pattern):
        return run_with_timeout(
            lambda: pattern.sub(repl, text),
            timeout_seconds,
            f"Regex operation timed out after {timeout_seconds} seconds",
            RegexTimeoutError,
        )
    return run_with_timeout(
        lambda: re.sub(pattern, repl, text, flags=flags),
        timeout_seconds,
        f"Regex operation timed out after {timeout_seconds} seconds",
        RegexTimeoutError,
    )


# Per-intent parameter extractors. Each mutates ``params`` in place so the
# dispatching wrapper in ``IntentParser._extract_params`` stays small and the
# overall flow reads as one regex per intent rather than one giant if/elif.


def _extract_browse(query: str, params: Dict[str, Any]) -> None:
    # A15 post-a15 P6-D2: the original regex
    # ``namespace\s+['\"]?([A-Za-z0-9_.-]+)['\"]?`` accepted multi-
    # character, digit, and special-char namespace arguments
    # (``browse namespace AB``, ``browse namespace 1``,
    # ``browse namespace _``) and didn't uppercase lowercase input.
    # The sibling ``_extract_walk_namespace`` is strict (single
    # letter, ``.upper()``); these two should agree. Tighten the
    # regex so a malformed argument fails to match and the handler's
    # missing-arg guard fires consistently across the two tools.
    namespace_match = safe_regex_search(
        r"namespace\s+['\"]?([A-Za-z])\b['\"]?",
        query,
        re.IGNORECASE,
    )
    if namespace_match:
        params["namespace"] = namespace_match.group(1).upper()


def _extract_filtered_search(query: str, params: Dict[str, Any]) -> None:
    search_match = safe_regex_search(
        rf"(?:search|find|look)\s+(?:for\s+)?{_QUOTE_OPEN}?"
        rf"({_QUOTE_NOT}+?){_QUOTE_OPEN}?\s+(?:in|within)",
        query,
        re.IGNORECASE,
    )
    if search_match:
        params["query"] = search_match.group(1).strip()

    # A16 post-a16 D6: tighten the namespace regex to a single letter
    # with a word boundary so ``search foo in namespace AB`` / ``... 1``
    # / ``... _`` fails to match and the handler's validation guard
    # fires consistently — matching the input-validation parity that
    # P6-D1/D2 added to ``browse_namespace`` and ``walk_namespace`` in
    # a16. Pre-fix, the regex accepted ``[A-Za-z0-9_.-]+`` and silently
    # passed the malformed argument through to the backend, which
    # returned ``No filtered matches`` with no signal that the
    # namespace itself was invalid.
    namespace_match = safe_regex_search(
        rf"namespace\s+{_QUOTE_OPEN}?([A-Za-z])\b{_QUOTE_OPEN}?",
        query,
        re.IGNORECASE,
    )
    if namespace_match:
        params["namespace"] = namespace_match.group(1).upper()

    type_match = safe_regex_search(
        rf"type\s+{_QUOTE_OPEN}?([A-Za-z0-9_/.-]+){_QUOTE_OPEN}?",
        query,
        re.IGNORECASE,
    )
    if type_match:
        params["content_type"] = type_match.group(1)


def _extract_entry_path_keyworded(query: str, params: Dict[str, Any]) -> None:
    """Shared extractor for get_article / structure / links / toc / summary.

    Locates the LAST keyword (article / entry / page / of / for / in /
    from / to) and treats everything after it as the entry path. This
    captures multi-word titles (``United States``, ``World War II``,
    ``Albert Einstein``) and Wikipedia-legal punctuation like ``@`` (in
    metadata illustration paths ``M/Illustration_48x48@1``), apostrophes,
    parens, etc. — all of which the previous ``[A-Za-z0-9_/.-]+`` capture
    silently truncated, dropping the user at the wrong article (the
    common silent-fall-through failure mode for ``show structure of
    United States`` returning the ``United`` disambig page).

    The downstream :meth:`SimpleToolsHandler._resolve_natural_language_path`
    helper then runs the captured tail through ``find_title_match`` so a
    free-form title like ``United States`` resolves to the canonical
    stored path ``United_States``.
    """
    quoted_match = safe_regex_search(
        rf"{_QUOTE_OPEN}({_QUOTE_NOT}+){_QUOTE_OPEN}", query
    )
    if quoted_match:
        params["entry_path"] = quoted_match.group(1)
        return

    # Find every keyword position; take the LAST so that
    # "table of contents for Biology" picks "Biology" (after "for")
    # rather than "contents for Biology" (after "of"). The keyword set
    # intentionally excludes "contents" so the "of contents" pair
    # doesn't shadow the trailing "for <target>" anchor.
    keyword_re = re.compile(
        r"\b(?:article|entry|page|of|for|in|from|to)\s+",
        re.IGNORECASE,
    )
    matches = list(keyword_re.finditer(query))
    if not matches:
        return
    tail = query[matches[-1].end() :].strip().rstrip("?.,;:!").strip()
    if tail:
        params["entry_path"] = tail


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
        candidate = suggest_match.group(1).strip()
        # A15 post-a15 P4-D1: when the user types ``suggestions for``
        # with no actual prefix after it, the optional ``(?:for\s+)?``
        # fails to match (no trailing whitespace before EOL), and the
        # regex's mandatory capture group falls back to swallowing
        # "for" itself as the prefix. Handler's missing-arg guard
        # (``if not partial_query``) then never fires because "for"
        # is non-empty. Treat a bare-"for" capture as if no prefix
        # was supplied so the existing guard takes over and the user
        # gets the structured "Missing Search Term" error instead of
        # autocompleting against the literal "for".
        if candidate.lower() != "for":
            params["partial_query"] = candidate


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


def _extract_tell_me_about(query: str, params: Dict[str, Any]) -> None:
    """Extract the topic from a ``tell_me_about``-shaped query.

    Examples:
      * ``"tell me about Photosynthesis"`` -> topic ``"Photosynthesis"``
      * ``"who is Martin Luther King Jr."`` -> topic ``"Martin Luther King Jr."``
      * ``"what is DNA"`` -> topic ``"DNA"``
      * ``"info about the Apollo program"`` -> topic ``"the Apollo program"``
      * ``"explain Berlin to me"`` -> topic ``"Berlin"``  (A11 B3)

    Strips the verb / interrogative prefix, any trailing politeness
    tail ("to me", "for me", "please"), and any trailing sentence
    punctuation. Falls back to the raw query so the search has
    *something* to look up if no prefix matched.
    """
    # A15 post-a15: politeness lead-in ("could you tell me about X",
    # "can you describe Y", "would you explain Z") used to bypass the
    # verb prefix entirely — the regex anchors at ``^\s*`` and "could
    # you" doesn't match the verb alternation, so the whole query fell
    # through to ``topic = query.strip()`` and downstream relied on the
    # tail-probe entity resolver to rescue the actual article. Strip
    # the leading modal scaffold first so the verb regex sees the
    # cleaned query.
    #
    # A15 post-a15 P6-D3: loop the strip so successive politeness
    # phrases peel cleanly (``please could you tell me about X`` →
    # ``could you tell me about X`` → ``tell me about X``). Two
    # separate patterns rather than one combined regex because
    # ``please`` is also legitimate trailing politeness (already
    # handled below) — keeping the leading-only strip narrow
    # (``please``, ``kindly``) avoids accidentally matching mid-
    # query mentions.
    for _ in range(3):
        before = query
        query = safe_regex_sub(
            r"^\s*(?:please|kindly)\s+",
            "",
            query,
            flags=re.IGNORECASE,
        ).strip()
        query = safe_regex_sub(
            r"^\s*(?:could|can|would|will)\s+(?:you|we|i)\s+(?:please\s+)?",
            "",
            query,
            flags=re.IGNORECASE,
        ).strip()
        if query == before:
            break
    # A11 B2: verb prefix uses ``\b`` (word boundary) and the topic
    # capture is ``(.*?)`` (zero-or-more, non-greedy) so ``tell me
    # about`` / ``tell me about `` / ``describe`` produce ``topic=""``
    # instead of falling through to the else-branch with the entire
    # raw query as the topic ("tell me about" → topic="tell me about"
    # → disambiguation to articles titled "Tell Me About Tomorrow").
    # The caller (simple_tools) checks for empty topic and surfaces a
    # ``Topic Required`` error.
    m = safe_regex_search(
        r"^\s*("
        r"tell\s+me\s+about\b|"
        r"who\s+(?:is|was|are|were)\b|"
        r"what\s+(?:is|are|was|were)\b|"
        r"describe\b|"
        r"explain\b|"
        r"info(?:rmation)?\s+(?:about|on)\b"
        r")\s*(.*?)\s*\??\s*$",
        query,
        re.IGNORECASE,
    )
    if m:
        topic = m.group(2).strip().rstrip("?.,;:!")
    else:
        topic = query.strip().rstrip("?.,;:!")
    # A11 B3 (post-a10 review): topic-asking phrasings commonly carry a
    # politeness tail — ``explain Berlin to me``, ``describe DNA for
    # me``, ``tell me about cats please``, ``describe DNA for me
    # please``. Strip the trailing politeness so the topic that
    # reaches the search query is clean.
    #
    # Order matters: ``please`` can wrap an inner ``to me`` /
    # ``for me`` (``DNA for me please``), so strip ``please`` FIRST,
    # then strip the bare ``to/for me`` tail. Loop both strips until
    # idempotent in case an unusual phrasing carries both forms.
    for _ in range(3):
        before = topic
        topic = safe_regex_sub(
            r"\s*,?\s*please\s*$",
            "",
            topic,
            flags=re.IGNORECASE,
        ).strip()
        topic = safe_regex_sub(
            r"\s+(?:to|for)\s+(?:me|us)\s*$",
            "",
            topic,
            flags=re.IGNORECASE,
        ).strip()
        if topic == before:
            break
    # A16 post-a16 D2: strip orphan trailing chain connectors. ``tell
    # me about Apollo 11 also`` with no right-hand topic used to leave
    # ``Apollo 11 also`` as the search topic, where the fuzzy ranker
    # promoted the unrelated ``Also`` disambig article above Apollo 11
    # (the word ``also`` is a stronger exact-title-token match than the
    # full phrase). The chained-intent guidance can't help here — the
    # connector regex requires a right-hand operand. Strip the orphan
    # tail before the search sees it.
    #
    # Pass-2 self-audit: ``then`` deliberately NOT in the strip list.
    # Real article titles end with ``Then`` (``Now and Then``,
    # ``Back Then``, ``Once Upon a Time ... Then ...``) often enough
    # that stripping it would mangle valid topics. ``then`` orphans
    # (``Apollo 11 then``) are rare and the search ranker degrades
    # gracefully.
    for _ in range(3):
        before = topic
        topic = safe_regex_sub(
            r"\s+(?:and|or|also|plus)\s*$",
            "",
            topic,
            flags=re.IGNORECASE,
        ).strip()
        topic = safe_regex_sub(r"\s*[,&]\s*$", "", topic).strip()
        if topic == before:
            break
    params["topic"] = topic


def _extract_get_zim_entries(query: str, params: Dict[str, Any]) -> None:
    """Extract namespace/path tokens like ``A/Foo`` or ``M/Image.png``.

    Both uppercase and lowercase namespace letters are accepted so that
    Sub-D-2 Rule 1 (which lowercases the query before extraction) does
    not suppress matches. The single-letter + ``/`` + non-dot-only suffix
    shape is specific enough to exclude bare file paths like
    ``wikipedia.zim`` while matching ZIM entry paths (``a/foo``,
    ``m/image.png``, etc.).
    """
    entries = safe_regex_findall(r"[A-Za-z]/[\w\-./%]+", query)
    if entries:
        # Strip trailing sentence punctuation that the character class
        # greedily captures (e.g. "A/Bar." -> "A/Bar").
        params["entries"] = [e.rstrip(".?,;:!") for e in entries]


def _extract_get_section(query: str, params: Dict[str, Any]) -> None:
    """Extract ``section_name`` and ``entry_path`` from a section query.

    Examples:
      * ``"section Evolution of Biology"`` -> name=Evolution, path=Biology
      * ``"the Evolution section of Biology"`` -> name=Evolution, path=Biology
      * ``"section 'Cellular respiration' of Biology"`` -> name=Cellular
        respiration, path=Biology
      * ``"section 3 of Biology"`` -> name="3" (numeric) — handler treats
        bare integers as 1-indexed positions into the article's headings.
      * ``"narrow section Geography of Berlin"`` (or ``"just section …"``)
        -> name=Geography, path=Berlin, narrow=True. Tells the handler
        to scope the slice to the heading itself (no nested
        subsections). Op3: surfaces ``include_subsections=False`` to
        small-model callers via a memorable verb.

    Two separate patterns because the section-name placement differs:
    pre-keyword (``"section X of Y"``) vs. pre-keyword-with-determiner
    (``"the X section of Y"``). Quoted names take precedence so a
    section called ``"In the news"`` doesn't get parsed as ``"In"`` +
    `` the news`` of nothing.
    """
    # Op3: detect a "narrow" / "just" prefix and strip it before the
    # regular section-extraction passes run. Stays a flag in ``params``
    # so the handler can switch ``include_subsections``.
    narrow_match = safe_regex_search(
        r"^\s*(?:narrow|just|only)\s+", query, re.IGNORECASE
    )
    if narrow_match:
        params["narrow"] = True
        query = query[narrow_match.end() :]
    # Form A: ``[the] section <name> of|in|from <path>``
    m = safe_regex_search(
        rf"\b(?:the\s+)?section\s+{_QUOTE_OPEN}?({_QUOTE_NOT}+?){_QUOTE_OPEN}?"
        rf"\s+(?:of|in|from)\s+{_QUOTE_OPEN}?(.+?){_QUOTE_OPEN}?\s*\??\s*$",
        query,
        re.IGNORECASE,
    )
    if m:
        params["section_name"] = m.group(1).strip()
        params["entry_path"] = m.group(2).strip().rstrip("?.,;:!")
        return
    # Form B: ``the <name> section of|in|from <path>``
    m = safe_regex_search(
        rf"\bthe\s+{_QUOTE_OPEN}?({_QUOTE_NOT}+?){_QUOTE_OPEN}?\s+section"
        rf"\s+(?:of|in|from)\s+{_QUOTE_OPEN}?(.+?){_QUOTE_OPEN}?\s*\??\s*$",
        query,
        re.IGNORECASE,
    )
    if m:
        params["section_name"] = m.group(1).strip()
        params["entry_path"] = m.group(2).strip().rstrip("?.,;:!")


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
    "tell_me_about": _extract_tell_me_about,
    "walk_namespace": _extract_walk_namespace,
    "find_by_title": _extract_find_by_title,
    "related": _extract_related,
    "get_zim_entries": _extract_get_zim_entries,
    "get_section": _extract_get_section,
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
        # Get specific article section — must beat the generic
        # ``structure`` pattern below (which also matches ``section``).
        # Two surface forms: ``section X of Y`` and ``the X section of Y``.
        # Specificity 10 + base 0.95 keeps it well above the
        # ``sections? of`` pattern (specificity 8, base 0.85).
        (
            r"\bsection\s+\S+.*\s+(?:of|in|from)\s+\S+",
            "get_section",
            0.95,
            10,
        ),
        (
            r"\bthe\s+\S+.*\s+section\s+(?:of|in|from)\s+\S+",
            "get_section",
            0.95,
            10,
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
        # Suggestions - moderately specific. The trailing assertion
        # accepts a word boundary (``autocomplete evol``) OR a quote
        # character (``autocomplete "evol"``) so the quoted form
        # advertised in the missing-arg hint actually routes to this
        # intent (P3-D4). Pre-fix, the bare ``\b`` after the optional
        # ``(for|of)?`` group failed before a quote char and the query
        # silently fell through to the ``search`` general fallback.
        (
            r"\b(suggestions?|autocomplete|complete|hints?)\s+(for|of)?"
            r"(?=\b|['\"‘’“”])",
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
        # Topic ask — explicit interrogative or "tell me about" phrasing.
        # Routes to the ``tell_me_about`` handler which runs a search and,
        # when the top result is a strong title match, also fetches the
        # article body so the caller gets primary content in a single
        # round trip. Confidence is set to beat the bare ``search``
        # fallback (0.7) but stay below specific intents like
        # ``walk_namespace`` / ``search_all`` (>= 0.9).
        (
            r"\b(tell\s+me\s+about|"
            r"who\s+(is|was|are|were)|"
            r"what\s+(is|are|was|were)|"
            r"describe|explain|"
            r"info(rmation)?\s+(about|on))\b",
            "tell_me_about",
            0.85,
            7,
        ),
    ]

    # Post-a20 PD2-1: trailing politeness markers ("please", "thanks",
    # "thank you", "kindly") were stripped only by
    # ``_extract_tell_me_about``. Every other extractor that captures
    # the topic / search-terms with a greedy tail
    # ((``_extract_search``, ``_extract_search_all``, ``_extract_find_by_title``,
    # ``_extract_related``, ``_extract_suggestions``,
    # ``_extract_entry_path_keyworded`` — feeding get_article / links /
    # structure / toc / summary, ``_extract_get_zim_entries``,
    # ``_extract_get_section``) silently swallowed the politeness as
    # part of the captured value:
    #
    #   * ``search for biology please`` → ``query="biology please"`` →
    #     ranks ``Thanks Maa`` etc. above ``Biology``.
    #   * ``find article titled Berlin please`` → looks up
    #     ``Berlin please`` (not found).
    #   * ``links in Photosynthesis please`` → tries to fetch
    #     ``Photosynthesis please`` (not found).
    #
    # Strip universally at the top of ``parse_intent`` so every
    # extractor sees the cleaned query. The strip is end-anchored
    # (``\s*$``), so legitimate uses of the politeness word as content
    # (``search for "Please Understand Me"`` — song title; the quoted
    # form fully encloses the content phrase, and the trailing ``please``
    # after the close-quote is what gets stripped) are unaffected. Loop
    # the strip so combinations like ``biology, thanks please`` peel
    # cleanly.
    # Post-a21 P1-D6 + P1-D7: widen the politeness token list to cover
    # British/texting variants (``ta`` / ``cheers`` / ``thx`` / ``ty``
    # / ``pls``) and the obvious multi-language tokens (``bitte`` /
    # ``danke`` / ``merci`` / ``gracias`` / ``por favor``). Live
    # transcripts show small models speculatively appending these
    # too — same shape as the post-a20 PD2-1 ``please``/``thanks``
    # leak. Several of the new tokens are short (``ta`` is 2 chars,
    # ``ty`` is 2 chars) so the leading anchor must guarantee a
    # word boundary or ``cantata`` / ``feta`` / ``Dante`` would get
    # their last 2 chars eaten. Pre-extension, the leading anchor
    # was ``\s*[,;.!?]?\s*`` — zero-or-more whitespace lets the
    # regex match mid-word. The extension tightens to
    # ``(?:^|\s+|[,;.!?]\s*)`` — start-of-string OR at least one
    # whitespace OR punctuation + optional whitespace. Embedded
    # ``ta`` / ``ty`` substrings inside other words no longer match.
    #
    # Post-a22 P1-D2: further extend with the SMS / chat variants the
    # post-a21 enumeration didn't cover — ``thnx`` / ``thanx`` /
    # ``tysm`` / ``kthx`` / ``kthxbai``. Live a22 sweep observed
    # ``search for biology thnx`` searching for ``"biology thnx"``
    # (3 irrelevant matches), and ``search for biology thanx``
    # searching for ``"biology thanx"`` — same shape as the missed
    # ``ta`` / ``cheers`` class in the post-a21 sweep. The leading
    # word-boundary anchor still protects against in-word matches
    # (``thank`` ends ``cathank``? no, but ``thnx`` inside another
    # word is structurally unlikely; ``ty`` inside ``cantata``
    # is — and the existing anchor already handles that). All new
    # tokens are also ≥4 chars except ``kthx``, which is still
    # word-anchored.
    #
    # Post-a23 P1-D2: narrow-scope sibling sweep widened the SMS family
    # to cover live-observed misses — ``tx`` / ``txs`` / ``tyvm`` /
    # ``thnks`` / ``thxx`` / ``kthxbye``, multi-word ``thanks a million``
    # and ``thank (you|u) (so|very) much``, and the second wave of
    # multilingual tokens ``obrigado(a)?`` (Portuguese), ``arigatou?``
    # (Japanese romaji), ``spasibo`` (Russian). Same narrow-enumeration
    # shape as the a22 → a23 progression — every politeness sweep so
    # far has shipped narrower than the natural family. The 2-char
    # token ``tx`` keeps the leading word-boundary anchor (already
    # tightened post-a21) so it can't eat the last two chars of
    # embedded words; word-anchored 2-char tokens are still safer than
    # mid-word matches.
    # Post-a24 P1-D3 / P1-D4: third-wave multilingual extensions.
    # P1-D3 — multi-word counterparts of the existing single-word
    # multilingual tokens (``merci beaucoup``, ``vielen dank``,
    # ``muchas gracias``, ``arigatou gozaimasu``, ``domo arigato``,
    # ``terima kasih``). Pre-fix, the regex only matched the single-word
    # form, leaving the leading qualifier behind (``muchas gracias`` →
    # ``gracias`` peeled, ``muchas`` left → ``"biology muchas"`` searched).
    # P1-D4 — more single-word tokens live-observed in post-a24 probes:
    # ``mahalo`` (Hawaiian), ``xie xie``/``xièxie`` (Chinese romaji),
    # ``shukran`` (Arabic), ``kiitos`` (Finnish), ``tack`` (Swedish),
    # ``gomawo``/``kamsahamnida`` (Korean romaji), ``dhanyavad`` (Hindi
    # romaji), ``domo`` (Japanese), ``gozaimasu`` (Japanese formal
    # suffix). Same narrow-scope sibling pattern as a23 → a24 — each
    # sweep has shipped the politeness regex narrower than the natural
    # family.
    #
    # Embedded-token safety: every new token preserves the leading
    # ``(?:^|\s+|[,;.!?]\s*)`` anchor, so ``tack`` inside ``attack`` /
    # ``thumbtack`` and ``domo`` inside ``domoic`` / ``Komodo`` don't
    # match — there's no whitespace / punctuation between the embedding
    # word's prefix and the politeness candidate. Multi-word entries are
    # listed BEFORE their single-word counterparts so the alternation
    # engine matches the maximal phrase even though Python's regex is
    # leftmost-first (the end-anchor + backtracking would still find the
    # longer match, but explicit ordering keeps the pattern's intent
    # readable).
    _TRAILING_POLITENESS_RE = (
        r"(?:^|\s+|[,;.!?]\s*)"
        r"(?:please|kindly|"
        # ``thanks (a lot|a million)`` — multi-word extensions of the
        # base ``thanks`` token.
        r"thanks(?:\s+a\s+(?:lot|million))?|"
        # ``thank (you|u) (so|very) much`` + plain ``thank (you|u)``.
        # Optional ``(so|very) much`` tail captures the heavier
        # politeness wrap small models emit.
        r"thank\s+(?:you|u)(?:\s+(?:so|very)\s+much)?|"
        # Longest-first within each family so the regex engine matches
        # the maximal token even though Python's alternation is
        # leftmost-first (backtracking would still find the longer
        # match thanks to the end-anchor, but explicit ordering keeps
        # the pattern readable and avoids relying on backtracking).
        r"kthxbai|kthxbye|kthx|"
        r"tyvm|tysm|ty|"
        r"thnks|thanx|thnx|thxx|thx|"
        r"pls|ta|cheers|txs|tx|"
        # Post-a24 P1-D3: multi-word multilingual variants — listed
        # before their single-word forms so the longer phrase wins. The
        # single-word forms still match alone when the qualifier is
        # absent.
        r"merci\s+beaucoup|"
        r"vielen\s+dank|"
        r"muchas\s+gracias|"
        r"arigatou?\s+gozaimasu|"
        r"domo\s+arigatou?|"
        r"terima\s+kasih|"
        r"por\s+favor|"
        # Multilingual politeness — Latin family + Asian-language
        # romaji. The Cyrillic ``спасибо`` and Devanagari forms aren't
        # included because they don't appear in ASCII-leaked queries
        # from current small models; revisit if live transcripts show
        # them.
        r"bitte|danke|merci|gracias|"
        r"obrigad[oa]|arigatou?|spasibo|"
        # Post-a24 P1-D4: third-wave single-word multilingual tokens.
        # ``xie\s*xie`` handles ``xie xie`` (space) and ``xiexie`` (no
        # space); ``xièxie`` listed separately because ``[eè]`` would
        # bloat the prior alternation. ``gozaimasu`` / ``domo`` are
        # listed for the post-strip remainders of ``arigatou
        # gozaimasu`` / ``domo arigato`` chains (the multi-word forms
        # above peel the whole pair in one match).
        r"mahalo|xi[eè]\s*xie|shukran|kiitos|tack|"
        r"gomawo|kamsahamnida|dhanyavad|"
        r"gozaimasu|domo)"
        r"\s*[,;.!?]*\s*$"
    )

    @classmethod
    def _strip_trailing_politeness(cls, query: str) -> str:
        """Peel trailing politeness tokens (``please`` / ``thanks`` /
        ``thank you`` / ``kindly``) off ``query``. Idempotent; loops
        until a pass produces no change so combinations like
        ``biology, thanks please`` strip in one call.
        """
        for _ in range(4):
            before = query
            query = safe_regex_sub(
                cls._TRAILING_POLITENESS_RE,
                "",
                query,
                flags=re.IGNORECASE,
            ).strip()
            if query == before:
                break
        return query

    # Post-a23 P1-D3: small models occasionally leak MCP tool parameters
    # INTO the natural-language query as text — ``tell me about
    # Photosynthesis limit=10`` or ``Berlin compact_budget=200`` instead
    # of passing them as the typed ``limit`` / ``compact_budget`` kwargs.
    # The title-promotion tokeniser then sees ``"10"`` / ``"200"`` as
    # clean ASCII digit tails, scores them against the title index, and
    # silently returns the ``10`` / ``200`` number article (or year
    # article) — a wildly unrelated body that masks the model's actual
    # topic.
    #
    # Live a23 sweep reproduced for ``limit=N`` (returns ``"N"``),
    # ``content_offset=N`` (returns ``"N"``), ``compact_budget=N``
    # (returns year ``"N"`` article), ``offset=N`` (returns ``"N"``)
    # on ``tell me about <topic> <param>=<value>``. Strip these BEFORE
    # the politeness loop / pattern matching so every downstream
    # extractor sees the cleaned query. Token list mirrors the public
    # ``zim_query`` argument set; covers the param names live a23
    # sweep observed plus their obvious neighbours.
    #
    # Word-boundary anchored at the front so we don't eat the leading
    # part of a multi-word topic (``offsetting`` / ``compactor`` /
    # ``cursor`` mid-topic are protected by the ``\s+`` requirement —
    # we only strip when the param keyword is preceded by whitespace,
    # and we require ``=`` so prose mentions of these words stay
    # intact). The value side matches ``\S+`` so quoted strings,
    # paths, numbers, and booleans all peel cleanly.
    # Post-a24 P1-D5: ``query`` was the only missing argument from the
    # public ``zim_query`` parameter set. Live a24 probe of
    # ``tell me about Photosynthesis query=biology`` returned the
    # ``Biology`` disambiguation page (the ``=biology`` suffix prevented
    # the title-promotion tokeniser from matching ``Photosynthesis``
    # cleanly; ``Biology`` won via fuzzy match on the trailing tokens).
    # Adding ``query`` closes the loop — every public ``zim_query``
    # parameter name now strips when a model leaks it as a query suffix.
    _PARAM_LEAK_RE = (
        r"\s+"
        r"(?:limit|offset|content_offset|max_content_length|"
        r"max_words|compact_budget|compact|synthesize|cursor|"
        r"zim_file_path|entry_path|namespace|partial_query|"
        r"query)"
        r"\s*=\s*\S+"
    )

    @classmethod
    def _strip_param_leaks(cls, query: str) -> str:
        """Peel leaked ``param=value`` suffixes off ``query``. Idempotent;
        loops until stable so a query carrying multiple params
        (``Photosynthesis limit=10 compact_budget=200``) strips in one
        call.
        """
        for _ in range(4):
            before = query
            query = safe_regex_sub(
                cls._PARAM_LEAK_RE,
                "",
                query,
                flags=re.IGNORECASE,
            ).strip()
            if query == before:
                break
        return query

    @classmethod
    def parse_intent(
        cls,
        query: str,
        *,
        title_probe: Optional[Callable[[str], bool]] = None,
    ) -> Tuple[str, Dict[str, Any], float]:
        """Parse a natural language query to determine intent.

        This method collects ALL matching patterns and uses a weighted scoring
        system to select the best match. This prevents earlier patterns from
        incorrectly shadowing more specific patterns that match later.

        Args:
            query: Natural language query string

        Returns:
            Tuple of (intent_type, extracted_params, confidence_score)

        Sub-D-2: a ``title_probe`` callback may be passed. When
        provided, rules 2 and 3 consult it to suppress false-positive
        rewrites (real proper nouns, canonical titles). When ``None``,
        rules 2 and 3 run in degraded mode (substitute without
        probing, strip without probing).
        """
        # Sub-D-2 Tier 1 rewrites — must run BEFORE the existing
        # _strip_* chain so downstream regexes see a normalized query.
        # Order is fixed: lowercase → misspellings → stopword phrase →
        # decomposition. Each rule is idempotent; we don't need a loop.
        query = cls._normalize_topic_case(query)
        query = cls._apply_misspelling_map(query, title_probe=title_probe)
        query = cls._detect_stopword_phrase(query, title_probe=title_probe)
        query, decomposition_hint = cls._decompose_x_of_y(query)

        # Post-a23 P1-D3: peel leaked ``param=value`` suffixes BEFORE
        # politeness so the politeness regex (and every downstream
        # extractor) sees the clean topic. See ``_PARAM_LEAK_RE`` for
        # the live-observed defect class. Order matters: politeness
        # then runs over the cleaned topic without ``limit=10`` /
        # ``offset=5`` confusing its leading word-boundary anchor.
        query = cls._strip_param_leaks(query)
        # Post-a20 PD2-1: peel trailing politeness BEFORE pattern
        # matching + extraction so every extractor sees the cleaned
        # query. See ``_TRAILING_POLITENESS_RE`` above for rationale +
        # sibling-defect enumeration.
        query = cls._strip_trailing_politeness(query)
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
            # Default fallback. A query that didn't match any pattern falls
            # into one of two buckets:
            #
            # * A bare topic name (proper-noun phrase with no verb,
            #   e.g. ``"Martin Luther King Jr."`` or ``"Photosynthesis"``).
            #   The caller almost certainly wants information *about* that
            #   topic — route to ``tell_me_about`` so the handler fetches
            #   the article body when the top hit is a strong title match.
            #
            # * Anything else — keep the legacy bare-search fallback.
            if cls._looks_like_bare_topic(query):
                params = {"topic": query.strip()}
                if decomposition_hint is not None:
                    params["decomposition_hint"] = decomposition_hint
                return "tell_me_about", params, 0.7
            params = {"query": query}
            if decomposition_hint is not None:
                params["decomposition_hint"] = decomposition_hint
            return "search", params, 0.5

        # Select best match using weighted scoring
        # Primary: confidence, Secondary: specificity
        best_match = cls._select_best_match(matches)
        intent_type, params, confidence = (
            best_match[0],
            best_match[1],
            best_match[2],
        )
        if decomposition_hint is not None:
            params["decomposition_hint"] = decomposition_hint
        return intent_type, params, confidence

    # Words that signal an explicit verb-shaped intent. If a query contains
    # one of these (case-insensitive, whole-word), it isn't "bare-topic" — it
    # has structure the intent classifier should have caught, and a
    # bare-topic fallback is inappropriate. Conservative list: only words
    # the intent parser specifically looks for as command verbs /
    # interrogatives, not generic English words like "the" or "of" that
    # appear in titles ("The Lord of the Rings").
    _BARE_TOPIC_VERB_TOKENS = frozenset(
        {
            "what",
            "who",
            "when",
            "where",
            "why",
            "how",
            "which",
            "list",
            "show",
            "get",
            "find",
            "fetch",
            "search",
            "browse",
            "tell",
            "describe",
            "explain",
            "give",
            "info",
            "about",
            "metadata",
            "namespace",
            "namespaces",
            "main",
            "page",
            "structure",
            "outline",
            "links",
            "related",
            "suggestions",
            "autocomplete",
            "walk",
            "all",
        }
    )

    # Common English filler / conversational tokens. A query whose tokens
    # are *only* drawn from this set looks like meta-instruction or
    # conversational filler ("do both", "try again", "ok", "test this")
    # rather than a topic ask, even though none of the tokens are
    # explicit command verbs in ``_BARE_TOPIC_VERB_TOKENS``. Used by
    # ``_looks_like_bare_topic`` to require at least one *content-shaped*
    # token before treating a query as a bare topic — otherwise small
    # LLMs that copy the user's literal message verbatim will trip the
    # bare-topic-fallback into ``tell_me_about``, where the strong-title
    # match path can dump entire article bodies for unrelated common-word
    # collisions (Aaliyah's "Try Again" for the literal user string
    # ``"try again"`` is the canonical motivating example).
    _COMMON_FILLER_TOKENS = frozenset(
        {
            # Affirmation / negation / acknowledgement
            "yes",
            "yeah",
            "yep",
            "no",
            "nope",
            "nah",
            "ok",
            "okay",
            "sure",
            "alright",
            "fine",
            # Greetings / politeness
            "hi",
            "hello",
            "hey",
            "thanks",
            "thank",
            "please",
            # Continuation cues
            "go",
            "continue",
            "next",
            "more",
            "again",
            "also",
            "still",
            "keep",
            "going",
            # Determiners / particles
            "the",
            "a",
            "an",
            "this",
            "that",
            "these",
            "those",
            "here",
            "there",
            "now",
            # Pronouns
            "i",
            "me",
            "my",
            "mine",
            "you",
            "your",
            "yours",
            "we",
            "us",
            "our",
            "ours",
            "they",
            "them",
            "their",
            "it",
            "its",
            # Coordinators
            "and",
            "or",
            "but",
            "if",
            "then",
            "else",
            # Common prepositions / particles (added for Sub-D-2 Rule 1
            # compatibility: lowercasing removes the capitalization signal
            # so short non-filler tokens now need explicit coverage to
            # prevent e.g. ``"go on"`` from being a bare topic because
            # ``"on"`` is 2 chars and not in the filler set).
            "on",
            "at",
            "in",
            "by",
            "up",
            "to",
            "as",
            "of",
            "so",
            "not",
            "yet",
            "for",
            "nor",
            "per",
            "via",
            # Common short verbs (non-intent)
            "do",
            "does",
            "did",
            "doing",
            "done",
            "try",
            "tries",
            "tried",
            "trying",
            "use",
            "uses",
            "used",
            "using",
            "have",
            "has",
            "had",
            "is",
            "are",
            "was",
            "were",
            "am",
            "be",
            "been",
            "being",
            "can",
            "could",
            "would",
            "should",
            "may",
            "might",
            "must",
            "will",
            "shall",
            # Meta-tool vocabulary (matches the LLM-passthrough patterns
            # observed in the v1.2.0 beta-test transcripts)
            "test",
            "tests",
            "tested",
            "testing",
            "tester",
            "demo",
            "demos",
            "explore",
            "exploring",
            "beta",
            "alpha",
            "regression",
            "stress",
            "smoke",
            "tool",
            "tools",
            # Vague nouns / quantifiers
            "thing",
            "things",
            "stuff",
            "anything",
            "everything",
            "something",
            "nothing",
            "any",
            "each",
            "every",
            "some",
            "none",
            "both",
            # Generic responses
            "right",
            "wrong",
            "true",
            "false",
            # User asked for help on the tool, not for a "Help" article
            "help",
        }
    )

    @classmethod
    def _looks_like_bare_topic(cls, query: str) -> bool:
        """Return True if ``query`` looks like a bare topic name.

        Two layers of evidence:

        1. Negative — the query has no command-verb / interrogative
           tokens from ``_BARE_TOPIC_VERB_TOKENS`` (otherwise it has
           structure the intent classifier should have caught).

        2. Positive — at least one token is *distinctive*: not common
           filler AND either capitalized in the original query
           (proper-noun signal) or at least five characters long
           (content-word signal).

        The positive layer is what stops conversational fragments like
        ``"do both"`` / ``"try again"`` / ``"test"`` / ``"help"`` from
        qualifying as bare topics under the negative-only rule. Without
        it, the strong-title-match branch in
        ``SimpleToolsHandler._handle_tell_me_about`` could dump full
        article bodies for unrelated common-word matches (the
        ``"try again"`` -> 105k-char Aaliyah article body trap).

        Examples:
          * ``"Martin Luther King Jr."`` qualifies (proper-noun cap).
          * ``"biology"`` qualifies (>=5 chars, not filler).
          * ``"DNA"`` qualifies (cap, not filler — even at 3 chars).
          * ``"量子力学"`` qualifies (non-Latin script — Chinese, Arabic,
            Russian, etc. — is treated as inherently distinctive since
            those scripts don't have casing or short ASCII filler).
          * ``"do both"`` does NOT (every token is common filler).
          * ``"try again"`` does NOT (every token is common filler).
          * ``"test"`` / ``"help"`` do NOT (single filler token).
          * ``"tell me about MLK"`` does NOT (verb ``tell``).
        """
        if not query or len(query) > 80:
            return False
        # Non-Latin scripts (CJK, Cyrillic, Arabic, Devanagari, Hebrew,
        # …) have no casing and no overlap with the ASCII filler-token
        # set, so any unicode "letter" character is a strong distinctive
        # signal on its own. Without this, the ASCII-only tokenizer below
        # treats ``"量子力学"`` as zero tokens and the gate falsely
        # rejects every non-Latin topic ask. ``str.isalpha()`` returns
        # True for letters in any script.
        if any(c.isalpha() and ord(c) > 127 for c in query):
            verb_match = re.search(r"[A-Za-z]+", query)
            if verb_match:
                ascii_tokens = [t.lower() for t in re.findall(r"[A-Za-z]+", query)]
                if any(t in cls._BARE_TOPIC_VERB_TOKENS for t in ascii_tokens):
                    return False
            return True
        # Tokenize on alphanumerics so punctuation in titles ("Jr.",
        # "U.S.A.") doesn't fragment names.
        raw_tokens = re.findall(r"[A-Za-z0-9]+", query)
        if not raw_tokens:
            return False
        lower_tokens = [t.lower() for t in raw_tokens]
        if any(t in cls._BARE_TOPIC_VERB_TOKENS for t in lower_tokens):
            return False
        # Positive check: any single token that is non-filler AND either
        # capitalized in the original query, content-word-length (≥5), OR
        # at least 2 characters is enough evidence that this is a topic
        # ask. The 2-char floor exists because Sub-D-2 Rule 1 lowercases
        # the query before this check fires, removing the capitalization
        # signal — short acronyms like ``dna`` / ``pi`` / ``ai`` / ``rna``
        # are still valid topics that must not fall through to search.
        # Single-char inputs are excluded (len(t) >= 2) to stop bare
        # single letters from qualifying.
        return any(
            t.lower() not in cls._COMMON_FILLER_TOKENS
            and (t[0].isupper() or len(t) >= 2)
            for t in raw_tokens
        )

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

    # ----- sub-D-2 Tier 1 query rewriting rules -----

    @classmethod
    def _normalize_topic_case(cls, query: str) -> str:
        """Sub-D-2 rule 1: lowercase the query.

        Replaces scattered `.lower()` calls in the relevance pipeline
        with a named pass. Idempotent. No telemetry — fires on
        essentially every query."""
        return query.lower()

    # Class-level overridable paths (None = use bundled defaults).
    # Tests can monkeypatch these to swap in fixture files.
    _misspellings_path: Optional["Path"] = None
    _exclusions_path: Optional["Path"] = None

    @classmethod
    def _apply_misspelling_map(
        cls,
        query: str,
        *,
        title_probe: Optional[Callable[[str], bool]],
    ) -> str:
        """Sub-D-2 rule 2: substitute known misspellings token-by-token.

        Probe-gated when ``title_probe`` is provided: if the original
        token canonically resolves to a real entity, the substitution
        is suppressed. Degrades to ``substitute-without-probe`` when
        ``title_probe`` is None.

        Idempotent: a corrected word is never itself a key in the map.
        Telemetry (``query_rewrite.misspelling``) is emitted by the
        caller (simple_tools.py wiring) based on the before/after diff."""
        mapping = load_misspellings(cls._misspellings_path)
        exclusions = load_exclusions(cls._exclusions_path)
        if not mapping:
            return query

        # Split on whitespace; preserve runs of whitespace between tokens.
        # re.split with a captured group keeps the separators in the list.
        parts = re.split(r"(\s+)", query)
        out: list[str] = []
        for part in parts:
            if not part or part.isspace():
                out.append(part)
                continue
            lower = part.lower()
            replacement = mapping.get(lower)
            if replacement is None:
                out.append(part)
                continue
            if lower in exclusions:
                out.append(part)
                continue
            if title_probe is not None and title_probe(part):
                out.append(part)
                continue
            out.append(replacement)
        return "".join(out)

    _LEADING_ARTICLE_RE = re.compile(r"^(the|a|an|of)\s+", re.IGNORECASE)

    # Guard: patterns where a leading article is PART of the command
    # signal, not a standalone article to strip. The primary case is
    # ``the X section of Y`` (``get_section`` intent) where stripping
    # ``the`` leaves ``X section of Y`` which matches the generic
    # ``structure`` pattern instead. Both surface-forms use
    # ``\bsection\b`` but the second (``the X section of Y``) requires
    # ``the`` to be present for the intent regex to fire.
    _RULE3_SECTION_COMMAND_RE = re.compile(
        r"^the\s+\S+.*\s+section\s+(?:of|in|from)\s+\S+",
        re.IGNORECASE,
    )

    @classmethod
    def _detect_stopword_phrase(
        cls,
        query: str,
        *,
        title_probe: Optional[Callable[[str], bool]],
    ) -> str:
        """Sub-D-2 rule 3: strip a leading article unless the full
        query (with article) is a canonical title.

        Probe-gated: the probe is called ONCE per query on the full
        query string. If the probe says yes → keep the article (e.g.
        ``The Beatles``). If no, or if ``title_probe`` is None → strip.

        Idempotent: stripping a leading article doesn't introduce a
        new one.

        Guard: ``the X section of Y`` / ``the X section in Y`` is a
        ``get_section`` command where ``the`` is syntactically load-
        bearing. Stripping it would break the intent regex. Skip the
        strip when the query matches this shape."""
        match = cls._LEADING_ARTICLE_RE.match(query)
        if not match:
            return query
        # Guard: ``the X section of/in/from Y`` is a get_section command.
        if cls._RULE3_SECTION_COMMAND_RE.match(query):
            return query
        if title_probe is not None and title_probe(query):
            # Real canonical title — keep the article.
            return query
        return query[match.end() :]

    # Rule 4 regex shapes. Both require a single-word attribute so we
    # don't mis-decompose multi-word phrases — multi-hop / multi-word
    # attribute decomposition is a deferred sub-D-3 concern.
    _X_OF_Y_RE = re.compile(
        r"^(?P<attr>\w+)\s+of\s+(?P<entity>.+)$",
        re.IGNORECASE,
    )
    _POSSESSIVE_RE = re.compile(
        r"^(?P<entity>\w+)'s\s+(?P<attr>\w+)$",
        re.IGNORECASE,
    )

    # Rule 4 guard: attribute words that are recognised intent keywords.
    # When the attr group matches one of these, the query is a structured
    # command (e.g. ``structure of Biology``, ``sections of Protein``)
    # rather than a factual decomposition (``population of Berlin``).
    # Decomposing these would rewrite them into bare noun phrases that
    # lose the command signal and misroute to ``search`` / ``tell_me_about``.
    _DECOMPOSE_SKIP_ATTRS: frozenset[str] = frozenset(
        {
            # Structure/TOC intent keywords (INTENT_PATTERNS, specificity 8–10)
            "structure",
            "outline",
            "sections",
            "section",
            "headings",
            "heading",
            "toc",
            "contents",
            # ``table`` as in ``table of contents`` — the multi-word phrase
            # ``table of contents for X`` starts with ``table``, so Rule 4
            # must not consume it before the toc intent regex can see it.
            "table",
            # Metadata intent keywords
            "metadata",
            "info",
            "details",
            "detail",
            # Summary intent keywords
            "summary",
            "overview",
            "brief",
            # Links intent keywords
            "links",
            "link",
            "references",
            "related",
            # Browse intent keywords
            "list",
            "browse",
            # Binary intent keywords
            "binary",
            # Search / find command verbs
            "find",
            "search",
            "get",
        }
    )

    @classmethod
    def _decompose_x_of_y(cls, query: str) -> tuple[str, Optional[dict[str, str]]]:
        """Sub-D-2 rule 4: decompose `<attr> of <entity>` and
        `<entity>'s <attr>` shapes.

        Returns ``(rewritten_query, hint_or_None)``:
        - ``rewritten_query`` collapses to ``<entity> <attr>`` when
          decomposition matches; otherwise returns input unchanged.
        - ``hint_or_None`` is ``{"entity": ..., "attribute": ...}`` on
          match, else None. The hint rides inside ``params`` in the
          parse_intent return value; ``_handle_tell_me_about`` reads it
          to skip its own extraction.

        Idempotent: a rewritten ``berlin population`` no longer matches
        either regex.

        Guard: when the attr word is a recognised intent keyword (e.g.
        ``structure``, ``sections``, ``metadata``), the query is a
        structured command and must NOT be decomposed — decomposing
        would destroy the command signal and misroute the query."""
        m = cls._X_OF_Y_RE.match(query)
        if not m:
            m = cls._POSSESSIVE_RE.match(query)
        if not m:
            return query, None
        entity = m.group("entity").strip()
        attr = m.group("attr").strip()
        # Guard: do not decompose known command-keyword attributes.
        if attr.lower() in cls._DECOMPOSE_SKIP_ATTRS:
            return query, None
        return f"{entity} {attr}", {"entity": entity, "attribute": attr}
