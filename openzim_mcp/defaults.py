"""
Centralized default values for OpenZIM MCP server configuration.

This module consolidates all default configuration values in one place,
making it easier to understand and modify the server's default behavior.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


def _default_persistence_path() -> str:
    """Return the default cache persistence path as a resolved absolute path.

    Uses ``~/.cache/openzim-mcp`` rather than a CWD-relative path so the
    cache lands in a predictable location regardless of how the server is
    invoked (containers, systemd units, etc. often run from ``/`` and a
    relative default would silently land in the working directory or in a
    world-writable surface).
    """
    return str((Path.home() / ".cache" / "openzim-mcp").resolve())


@dataclass(frozen=True)
class CacheDefaults:
    """Default values for cache configuration."""

    ENABLED: bool = True
    MAX_SIZE: int = 100
    TTL_SECONDS: int = 3600  # 1 hour
    # Soft cap on total approximate cache size (JSON-rendered bytes
    # across all entries). Eviction kicks in BEFORE ``MAX_SIZE`` if
    # entries are large (Phase C bundles can be hundreds of KB each).
    # 64 MB keeps memory bounded on long-running servers without
    # measurably degrading hit rate for typical workloads.
    MAX_BYTES: int = 64 * 1024 * 1024
    PERSISTENCE_ENABLED: bool = False
    PERSISTENCE_PATH: str = field(default_factory=_default_persistence_path)


@dataclass(frozen=True)
class ContentDefaults:
    """Default values for content processing."""

    SNIPPET_LENGTH: int = 3000
    MAX_CONTENT_LENGTH: int = 100000
    SEARCH_LIMIT: int = 10
    MAX_BINARY_SIZE: int = 10_000_000  # 10MB
    MAIN_PAGE_TRUNCATION: int = 5000  # Characters for main page display
    # Maximum redirect chain length before bailing out. Real ZIM redirects
    # rarely chain more than once or twice; ten is well above any legitimate
    # depth and guards against pathological data or cycles libzim itself
    # does not detect.
    MAX_REDIRECT_DEPTH: int = 10
    # Phase A item #2 — table & infobox handling in compact mode.
    TABLE_ROW_THRESHOLD: int = 8
    TABLE_CHAR_THRESHOLD: int = 600
    INFOBOX_KV_LIMIT: int = 30


@dataclass(frozen=True)
class RateLimitDefaults:
    """Default values for rate limiting."""

    ENABLED: bool = True
    REQUESTS_PER_SECOND: float = 10.0
    BURST_SIZE: int = 20


@dataclass(frozen=True)
class InputLimitDefaults:
    """Default values for input validation limits."""

    FILE_PATH: int = 1000
    QUERY: int = 500
    ENTRY_PATH: int = 500
    NAMESPACE: int = 100
    CONTENT_TYPE: int = 100
    PARTIAL_QUERY: int = 200


@dataclass(frozen=True)
class CachePerformanceThresholds:
    """Threshold values for cache performance analysis."""

    LOW_HIT_RATE: float = 0.3  # Below this is considered poor performance
    HIGH_HIT_RATE: float = 0.8  # Above this is considered good performance


@dataclass(frozen=True)
class NamespaceSamplingDefaults:
    """Default values for namespace discovery sampling."""

    MAX_SAMPLE_SIZE: int = 1000  # Maximum entries to sample for namespace discovery
    MAX_NAMESPACE_ENTRIES: int = 200  # Maximum entries to collect per namespace
    MAX_SAMPLE_ATTEMPTS_MULTIPLIER: int = 3  # sample_size * multiplier = max attempts


@dataclass(frozen=True)
class TimeoutDefaults:
    """Default values for timeouts."""

    REGEX_SECONDS: float = 1.0
    ARCHIVE_OPEN_SECONDS: float = 30.0
    # Per-subscriber timeout for ``send_resource_updated`` during broadcast.
    # A subscriber that doesn't respond within this window is treated as dead
    # and evicted from the registry. The fan-out is concurrent
    # (``asyncio.gather``), so one hung subscriber never delays the others —
    # this timeout only bounds how long an individual hung send blocks its
    # own task before being cancelled.
    SUBSCRIPTION_SEND_SECONDS: float = 5.0


@dataclass(frozen=True)
class ServerDefaults:
    """Default values for server configuration."""

    NAME: str = "openzim-mcp"
    TOOL_MODE: str = "simple"
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@dataclass(frozen=True)
class BatchDefaults:
    """Default values for batch operations."""

    MAX_SIZE: int = 50  # max entries per get_zim_entries call


@dataclass(frozen=True)
class MetaDefaults:
    """Default values for the response `_meta` envelope (Phase A item #5)."""

    FOOTER_ENABLED: bool = True
    TOKENIZER_ENCODING: str = "cl100k_base"


@dataclass(frozen=True)
class SearchDefaults:
    """Default values for search-side knobs (Phase A items #4, #14)."""

    STRUCTURED_SUGGESTIONS_LIMIT: int = 5
    FUZZY_TITLE_MIN_QUERY_LEN: int = 4
    FUZZY_TITLE_SCORE_PENALTY: float = 0.85
    # Upper bound on a caller-supplied ``limit`` for the search family
    # (zim_search / zim_query). The legacy granular search tools capped at
    # 100; the v2 rewrite kept only the ``limit >= 1`` floor, so an
    # unbounded ``limit`` (e.g. 999999) would ask the data layer to
    # materialise every match — a real resource/token blow-up on a
    # multi-million-entry archive. Reject above this ceiling and point the
    # caller at ``offset`` pagination instead. Generous (10x the legacy
    # cap) so no legitimate single-page request is affected.
    MAX_RESULT_LIMIT: int = 1000


# Instantiate defaults for easy access
CACHE = CacheDefaults()
CONTENT = ContentDefaults()
RATE_LIMIT = RateLimitDefaults()
INPUT_LIMITS = InputLimitDefaults()
TIMEOUTS = TimeoutDefaults()
SERVER = ServerDefaults()
CACHE_PERFORMANCE = CachePerformanceThresholds()
NAMESPACE_SAMPLING = NamespaceSamplingDefaults()
BATCH = BatchDefaults()
META = MetaDefaults()
SEARCH = SearchDefaults()

# Tool mode constants
TOOL_MODE_ADVANCED = "advanced"
TOOL_MODE_SIMPLE = "simple"
VALID_TOOL_MODES = {TOOL_MODE_ADVANCED, TOOL_MODE_SIMPLE}

# File validation constants
ZIM_FILE_EXTENSION = ".zim"

# Valid transport types for MCP server
VALID_TRANSPORT_TYPES = {"stdio", "sse", "streamable-http"}

# HTML processing constants - selectors to remove during content processing
UNWANTED_HTML_SELECTORS: List[str] = [
    "script",
    "style",
    "meta",
    "link",
    "head",
    "footer",
    ".mw-parser-output .reflist",
    ".mw-editsection",
    # Image captions: Wikipedia's article HTML puts a figure with a caption
    # before the lead paragraph, so snippets start with "Schematic of …"
    # instead of the actual lead. Stripping the figure container removes
    # the caption text and the orphan alt-text noise. Galleries (".gallery")
    # have the same problem at section boundaries.
    "figure",
    "figcaption",
    ".thumb",
    ".thumbcaption",
    ".gallery",
    # Disambiguation hatnotes ("For other uses, see X") sit between the H1
    # and the lead paragraph. They're 99% navigation noise for a small model
    # following a topic; keep the canonical link discovery in extract_links.
    ".hatnote",
    # "Part of a series on" right-rail navigation. Render as pipe-soup noise
    # at the top of the rendered article body, displacing the actual lead.
    ".sidebar",
    ".navbox",
    ".metadata.mbox-small",
    # Inline citation superscripts (``<sup class="reference">[1]</sup>``)
    # html2text renders as bare ``[1]``/``[a]`` text inline with prose
    # — pure noise for a small model that won't follow them anyway and
    # can request the reflist explicitly if needed. Stripping them
    # noticeably tightens snippet density.
    "sup.reference",
    "sup.cite_ref",
    ".reference",
    # MediaWiki collapsed-content toggles ("show"/"hide") — render as
    # bare ``[show]``/``[hide]`` text inline with the heading.
    ".mw-collapsible-toggle",
    # Coordinate displays in infoboxes: html2text mangles the
    # microformat into pipe-soup like
    # ``52°31′07″N 13°24′16″E / 52.518691°N 13.404183°E``. Useful for
    # GIS, useless for a small model trying to read the article body.
    ".geo-default",
    ".geo-dms",
    ".geo-dec",
    ".geo-nondefault",
    ".geo-multi-punct",
]

# In-article "furniture" headings to drop on ZIMIT/warc2zim pages. The
# main-content landmark scoping (``select_main_content``) removes chrome
# OUTSIDE the <article>, but MedlinePlus encodes boilerplate nav/quiz/metadata
# blocks as ordinary headed sections INSIDE it. We strip a section whose
# heading text EXACTLY matches one of these (case-insensitive, whitespace-
# collapsed, trailing punctuation trimmed) up to the next same-or-higher-level
# heading. Matching is exact — NOT substring — so a real section like
# "Learn More About Diabetes" is never clipped by the "learn more" entry.
# Kept intentionally conservative and MedlinePlus-shaped: only labels that are
# unambiguously furniture (never a plausible prose-section title). Generic
# medical words MedlinePlus also reuses as topic-nav ("Symptoms", "Causes",
# "Diagnosis and Tests", ...) are deliberately EXCLUDED to avoid clipping real
# article content; grow this list only with archive-confirmed evidence. The
# strip is landmark-gated, so Wikipedia/mwoffliner pages never see it.
FURNITURE_HEADING_DENYLIST: frozenset = frozenset(
    {
        "test your knowledge",
        "see, play and learn",
        "find an expert",
        "patient handouts",
        "related issues",
        "related health topics",
        "related medlineplus health topics",
        "learn more",
        "review date",
        "reference desk",
        "videos and tutorials",
    }
)

# Furniture headings whose label carries a VARIABLE trailing value (a date,
# count, etc.) so exact match misses them — e.g. MedlinePlus renders the
# "last reviewed" footer as ``Review Date 2/10/2023``. These match by prefix
# (the normalized heading must equal the prefix or start with ``prefix + " "``,
# so a real section like "Review Dates of Treaties" is NOT clipped). Kept
# separate from the exact denylist and intentionally tiny — only labels that
# are furniture even with a trailing value belong here.
FURNITURE_HEADING_PREFIXES: frozenset = frozenset(
    {
        "review date",
    }
)

# Rate limiter operation costs
RATE_LIMIT_COSTS: Dict[str, int] = {
    "search": 2,
    "search_with_filters": 2,
    "find_entry_by_title": 2,
    "get_entry": 1,
    "get_zim_entries": 1,
    "get_binary_entry": 3,
    "browse_namespace": 1,
    "get_metadata": 1,
    "get_structure": 1,
    "get_related_articles": 2,
    "suggestions": 1,
    "default": 1,
}
