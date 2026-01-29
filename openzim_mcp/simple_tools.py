"""
Simple tools implementation for OpenZIM MCP server.

This module provides intelligent, natural language-based tools that abstract
away the complexity of multiple specialized tools. Designed for LLMs with
limited tool-calling capabilities or context windows.
"""

import logging
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from .constants import REGEX_TIMEOUT_SECONDS
from .exceptions import RegexTimeoutError
from .timeout_utils import regex_timeout, run_with_timeout
from .zim_operations import ZimOperations

logger = logging.getLogger(__name__)


def safe_regex_search(
    pattern: str,
    text: str,
    flags: int = 0,
    timeout_seconds: float = REGEX_TIMEOUT_SECONDS,
) -> Optional[re.Match[str]]:
    """
    Perform a regex search with cross-platform timeout protection.

    This function provides ReDoS protection on all platforms by wrapping
    the regex operation with appropriate timeout mechanisms.

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
    if sys.platform == "win32":
        # Use threading-based timeout on Windows
        return run_with_timeout(
            lambda: re.search(pattern, text, flags),
            timeout_seconds,
            f"Regex operation timed out after {timeout_seconds} seconds",
            RegexTimeoutError,
        )
    else:
        # Use signal-based timeout on Unix
        with regex_timeout(timeout_seconds):
            return re.search(pattern, text, flags)


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
            r"\b(get|retrieve|download|extract|fetch)\s+(binary|raw|pdf|image|video|audio|media)\b",
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
        # Get article - common words
        (
            r"\b(get|show|read|display|fetch)\s+(article|entry|page)\b",
            "get_article",
            0.75,
            5,
        ),
        # Search - general fallback
        (r"\b(search|find|look\s+for|query)\b", "search", 0.7, 3),
    ]

    @classmethod
    def parse_intent(cls, query: str) -> Tuple[str, Dict[str, Any], float]:
        """
        Parse a natural language query to determine intent with multi-match resolution.

        This method collects ALL matching patterns and uses a weighted scoring system
        to select the best match. This prevents earlier patterns from incorrectly
        shadowing more specific patterns that match later.

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
                    # Boost confidence if extracted params are valid
                    confidence = base_confidence
                    if params and any(v for v in params.values() if v):
                        confidence = min(1.0, confidence + 0.1)
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
        """
        Select the best match from multiple matching patterns.

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
                f"selected '{scored_matches[0][0]}' with score {scored_matches[0][3]:.3f}"
            )

        best = scored_matches[0]
        return best[0], best[1], best[2]

    @classmethod
    def _extract_params(cls, query: str, intent: str) -> Dict[str, Any]:
        """
        Extract parameters from query based on intent.

        Uses cross-platform timeout protection to prevent ReDoS attacks.

        Args:
            query: Original query string
            intent: Detected intent type

        Returns:
            Dictionary of extracted parameters
        """
        params: Dict[str, Any] = {}

        try:
            if intent == "browse":
                # Extract namespace from query
                namespace_match = safe_regex_search(
                    r"namespace\s+['\"]?([A-Za-z0-9_.-]+)['\"]?",
                    query,
                    re.IGNORECASE,
                )
                if namespace_match:
                    params["namespace"] = namespace_match.group(1)

            elif intent == "filtered_search":
                # Extract search query and filters
                # Try to extract the search term
                search_match = safe_regex_search(
                    r"(?:search|find|look)\s+(?:for\s+)?['\"]?([^'\"]+?)['\"]?\s+(?:in|within)",
                    query,
                    re.IGNORECASE,
                )
                if search_match:
                    params["query"] = search_match.group(1).strip()

                # Extract namespace filter
                namespace_match = safe_regex_search(
                    r"namespace\s+['\"]?([A-Za-z0-9_.-]+)['\"]?",
                    query,
                    re.IGNORECASE,
                )
                if namespace_match:
                    params["namespace"] = namespace_match.group(1)

                # Extract content type filter
                type_match = safe_regex_search(
                    r"type\s+['\"]?([A-Za-z0-9_/.-]+)['\"]?", query, re.IGNORECASE
                )
                if type_match:
                    params["content_type"] = type_match.group(1)

            elif intent in ["get_article", "structure", "links", "toc", "summary"]:
                # Extract article/entry path
                # Try to find quoted strings first
                quoted_match = safe_regex_search(r"['\"]([^'\"]+)['\"]", query)
                if quoted_match:
                    params["entry_path"] = quoted_match.group(1)
                else:
                    # Try to extract after keywords
                    # For links: "links in Biology", "references from Evolution"
                    # For structure: "structure of Biology"
                    # For toc: "table of contents for Biology"
                    # For summary: "summary of Biology"
                    # For get_article: "get article Biology"
                    path_match = safe_regex_search(
                        r"(?:article|entry|page|of|for|in|from|to|contents)\s+([A-Za-z0-9_/.-]+)",
                        query,
                        re.IGNORECASE,
                    )
                    if path_match:
                        params["entry_path"] = path_match.group(1)

            elif intent == "binary":
                # Extract entry path for binary content retrieval
                # Try to find quoted strings first
                quoted_match = safe_regex_search(r"['\"]([^'\"]+)['\"]", query)
                if quoted_match:
                    params["entry_path"] = quoted_match.group(1)
                else:
                    # Try to extract path after keywords
                    # "get binary content from I/image.png"
                    # "extract pdf I/document.pdf"
                    # "retrieve image logo.png"
                    path_match = safe_regex_search(
                        r"(?:content|data|entry|from|of|for|pdf|image|video|audio|media)\s+['\"]?([A-Za-z0-9_/.-]+)['\"]?",
                        query,
                        re.IGNORECASE,
                    )
                    if path_match:
                        params["entry_path"] = path_match.group(1)

                # Check for metadata-only mode
                metadata_match = safe_regex_search(
                    r"\b(metadata|info)\s+only\b", query, re.IGNORECASE
                )
                if metadata_match:
                    params["include_data"] = False

            elif intent == "suggestions":
                # Extract partial query
                suggest_match = safe_regex_search(
                    r"(?:suggestions?|autocomplete|complete|hints?)\s+(?:for\s+)?['\"]?([^'\"]+)['\"]?",
                    query,
                    re.IGNORECASE,
                )
                if suggest_match:
                    params["partial_query"] = suggest_match.group(1).strip()

            elif intent == "search":
                # For general search, use the whole query or extract search term
                search_match = safe_regex_search(
                    r"(?:search|find|look)\s+(?:for\s+)?['\"]?([^'\"]+)['\"]?",
                    query,
                    re.IGNORECASE,
                )
                if search_match:
                    params["query"] = search_match.group(1).strip()
                else:
                    params["query"] = query

        except RegexTimeoutError:
            logger.warning(
                f"Regex timeout during param extraction for intent {intent}: {query[:50]}..."
            )
            # Return empty params on timeout - caller will handle gracefully

        return params


class SimpleToolsHandler:
    """Handler for simple, intelligent MCP tools."""

    def __init__(self, zim_operations: ZimOperations):
        """
        Initialize simple tools handler.

        Args:
            zim_operations: ZimOperations instance for underlying operations
        """
        self.zim_operations = zim_operations
        self.intent_parser = IntentParser()

    def handle_zim_query(
        self,
        query: str,
        zim_file_path: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Handle a natural language query about ZIM file content.

        This is the main intelligent tool that routes queries to appropriate
        underlying operations based on intent parsing.

        Args:
            query: Natural language query
            zim_file_path: Optional path to ZIM file (auto-selects if not provided)
            options: Optional dict with advanced options (limit, offset, etc.)

        Returns:
            Response string with results
        """
        try:
            options = options or {}

            # Parse intent from query (now returns confidence score)
            intent, params, confidence = self.intent_parser.parse_intent(query)
            logger.info(
                f"Parsed intent: {intent}, params: {params}, confidence: {confidence:.2f}"
            )

            # If confidence is very low, add a note to the response
            low_confidence_note = ""
            if confidence < 0.6:
                low_confidence_note = (
                    "\n\n*Note: This query interpretation has moderate confidence. "
                    "If the results aren't what you expected, try rephrasing your query.*\n"
                )

            # Handle file listing (doesn't require zim_file_path)
            if intent == "list_files":
                result = self.zim_operations.list_zim_files()
                return result + low_confidence_note

            # Auto-select ZIM file if not provided
            if not zim_file_path:
                zim_file_path = self._auto_select_zim_file()
                if not zim_file_path:
                    return (
                        "**No ZIM File Specified**\n\n"
                        "Please specify a ZIM file path, or ensure there is exactly one ZIM file available.\n\n"
                        "**Available files:**\n"
                        f"{self.zim_operations.list_zim_files()}"
                    )

            # Route to appropriate operation based on intent
            if intent == "metadata":
                result = self.zim_operations.get_zim_metadata(zim_file_path)
                return result + low_confidence_note

            elif intent == "main_page":
                result = self.zim_operations.get_main_page(zim_file_path)
                return result + low_confidence_note

            elif intent == "list_namespaces":
                result = self.zim_operations.list_namespaces(zim_file_path)
                return result + low_confidence_note

            elif intent == "browse":
                namespace = params.get("namespace", "C")
                limit = options.get("limit", 50)
                offset = options.get("offset", 0)
                result = self.zim_operations.browse_namespace(
                    zim_file_path, namespace, limit, offset
                )
                return result + low_confidence_note

            elif intent == "structure":
                entry_path = params.get("entry_path")
                if not entry_path:
                    return (
                        "**Missing Article Path**\n\n"
                        "Please specify which article you want to get the structure for.\n"
                        "**Example**: 'structure of Biology' or 'structure of \"C/Evolution\"'"
                    )
                result = self.zim_operations.get_article_structure(
                    zim_file_path, entry_path
                )
                return result + low_confidence_note

            elif intent == "toc":
                entry_path = params.get("entry_path")
                if not entry_path:
                    return (
                        "**Missing Article Path**\n\n"
                        "Please specify which article you want the table of contents for.\n"
                        "**Example**: 'table of contents for Biology' or 'toc of \"C/Evolution\"'"
                    )
                result = self.zim_operations.get_table_of_contents(
                    zim_file_path, entry_path
                )
                return result + low_confidence_note

            elif intent == "summary":
                entry_path = params.get("entry_path")
                if not entry_path:
                    return (
                        "**Missing Article Path**\n\n"
                        "Please specify which article you want a summary for.\n"
                        "**Example**: 'summary of Biology' or 'summarize \"C/Evolution\"'"
                    )
                max_words = options.get("max_words", 200)
                result = self.zim_operations.get_entry_summary(
                    zim_file_path, entry_path, max_words
                )
                return result + low_confidence_note

            elif intent == "links":
                entry_path = params.get("entry_path")
                if not entry_path:
                    return (
                        "**Missing Article Path**\n\n"
                        "Please specify which article you want to extract links from.\n"
                        "**Example**: 'links in Biology' or 'links from \"C/Evolution\"'"
                    )
                result = self.zim_operations.extract_article_links(
                    zim_file_path, entry_path
                )
                return result + low_confidence_note

            elif intent == "binary":
                entry_path = params.get("entry_path")
                if not entry_path:
                    return (
                        "**Missing Entry Path**\n\n"
                        "Please specify the path of the binary content to retrieve.\n"
                        "**Examples**:\n"
                        "- 'get binary content from \"I/image.png\"'\n"
                        "- 'extract pdf \"I/document.pdf\"'\n"
                        "- 'retrieve image I/logo.png'\n\n"
                        "**Tip**: Use `extract_article_links` to discover embedded media paths."
                    )
                include_data = params.get("include_data", True)
                max_size_bytes = options.get("max_size_bytes")
                result = self.zim_operations.get_binary_entry(
                    zim_file_path, entry_path, max_size_bytes, include_data
                )
                return result + low_confidence_note

            elif intent == "suggestions":
                partial_query = params.get("partial_query", "")
                if not partial_query:
                    return (
                        "**Missing Search Term**\n\n"
                        "Please specify what you want suggestions for.\n"
                        "**Example**: 'suggestions for bio' or 'autocomplete \"evol\"'"
                    )
                limit = options.get("limit", 10)
                result = self.zim_operations.get_search_suggestions(
                    zim_file_path, partial_query, limit
                )
                return result + low_confidence_note

            elif intent == "filtered_search":
                search_query = params.get("query", query)
                namespace = params.get("namespace")
                content_type = params.get("content_type")
                limit = options.get("limit")
                offset = options.get("offset", 0)
                result = self.zim_operations.search_with_filters(
                    zim_file_path, search_query, namespace, content_type, limit, offset
                )
                return result + low_confidence_note

            elif intent == "get_article":
                entry_path = params.get("entry_path")
                if not entry_path:
                    # If no specific path, try to extract from query
                    # Remove common words and use remainder as entry path
                    cleaned_query = re.sub(
                        r"\b(get|show|read|display|fetch|article|entry|page)\b",
                        "",
                        query,
                        flags=re.IGNORECASE,
                    ).strip()
                    if cleaned_query:
                        entry_path = cleaned_query
                    else:
                        return (
                            "**Missing Article Path**\n\n"
                            "Please specify which article you want to read.\n"
                            "**Example**: 'get article Biology' or 'show \"C/Evolution\"'"
                        )
                max_content_length = options.get("max_content_length")
                result = self.zim_operations.get_zim_entry(
                    zim_file_path, entry_path, max_content_length
                )
                return result + low_confidence_note

            elif intent == "search":
                search_query = params.get("query", query)
                limit = options.get("limit")
                offset = options.get("offset", 0)
                result = self.zim_operations.search_zim_file(
                    zim_file_path, search_query, limit, offset
                )
                return result + low_confidence_note

            else:
                # Fallback to search
                result = self.zim_operations.search_zim_file(
                    zim_file_path, query, options.get("limit"), options.get("offset", 0)
                )
                return result + low_confidence_note

        except Exception as e:
            logger.error(f"Error handling zim_query: {e}")
            return (
                f"**Error Processing Query**\n\n"
                f"**Query**: {query}\n"
                f"**Error**: {str(e)}\n\n"
                f"**Troubleshooting**:\n"
                f"1. Check that the ZIM file path is correct\n"
                f"2. Verify the query format\n"
                f"3. Try a simpler query\n"
                f"4. Check server logs for details"
            )

    def _auto_select_zim_file(self) -> Optional[str]:
        """
        Auto-select a ZIM file if only one is available.

        Returns:
            Path to ZIM file if exactly one exists, None otherwise.
            Returns None with appropriate logging if multiple files exist or on error.
        """
        try:
            # Use the structured data method directly instead of parsing JSON from string
            files = self.zim_operations.list_zim_files_data()

            if len(files) == 0:
                logger.info(
                    "Auto-select failed: no ZIM files found in allowed directories"
                )
                return None
            elif len(files) == 1:
                selected = str(files[0]["path"])
                logger.debug(f"Auto-selected ZIM file: {selected}")
                return selected
            else:
                logger.info(
                    f"Auto-select skipped: {len(files)} ZIM files found, "
                    "please specify which file to use"
                )
                return None

        except Exception as e:
            # Log at warning level with specific error for debugging
            logger.warning(
                f"Auto-select ZIM file failed with error: {type(e).__name__}: {e}"
            )
            return None
