"""Simple tools implementation for OpenZIM MCP server.

This module provides intelligent, natural language-based tools that abstract
away the complexity of multiple specialized tools. Designed for LLMs with
limited tool-calling capabilities or context windows.

The regex-heavy intent-parsing layer lives in :mod:`openzim_mcp.intent_parser`.
``IntentParser``, ``safe_regex_search`` and ``safe_regex_findall`` are
re-exported here for backward-compatibility with existing imports.
"""

import logging
import re
from typing import Any, Dict, Optional

from .intent_parser import (  # noqa: F401  (re-exported for back-compat)
    IntentParser,
    safe_regex_findall,
    safe_regex_search,
)
from .security import sanitize_context_for_error
from .zim_operations import ZimOperations

logger = logging.getLogger(__name__)


class SimpleToolsHandler:
    """Handler for simple, intelligent MCP tools."""

    def __init__(self, zim_operations: ZimOperations):
        """Initialize simple tools handler.

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
        """Handle a natural language query about ZIM file content.

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
                f"Parsed intent: {intent}, params: {params}, "
                f"confidence: {confidence:.2f}"
            )

            # If confidence is very low, add a note to the response
            low_confidence_note = ""
            if confidence < 0.6:
                low_confidence_note = (
                    "\n\n*Note: This query interpretation has moderate confidence. "
                    "If the results aren't what you expected, "
                    "try rephrasing your query.*\n"
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
                        "Please specify a ZIM file path, or ensure there is "
                        "exactly one ZIM file available.\n\n"
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
                        "Please specify which article you want the structure for.\n"
                        "**Example**: 'structure of Biology' or "
                        "'structure of \"C/Evolution\"'"
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
                        "Please specify which article you want the TOC for.\n"
                        "**Example**: 'table of contents for Biology' or "
                        "'toc of \"C/Evolution\"'"
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
                        "**Example**: 'summary of Biology' or "
                        "'summarize \"C/Evolution\"'"
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
                        "Please specify which article to extract links from.\n"
                        "**Example**: 'links in Biology' or "
                        "'links from \"C/Evolution\"'"
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
                        "Please specify the path of the binary content.\n"
                        "**Examples**:\n"
                        "- 'get binary content from \"I/image.png\"'\n"
                        "- 'extract pdf \"I/document.pdf\"'\n"
                        "- 'retrieve image I/logo.png'\n\n"
                        "**Tip**: Use `extract_article_links` to discover "
                        "embedded media paths."
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
                        "**Example**: 'suggestions for bio' or "
                        "'autocomplete \"evol\"'"
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
                            "**Example**: 'get article Biology' or "
                            "'show \"C/Evolution\"'"
                        )
                max_content_length = options.get("max_content_length")
                content_offset = options.get("content_offset", 0)
                result = self.zim_operations.get_zim_entry(
                    zim_file_path, entry_path, max_content_length, content_offset
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

            elif intent == "search_all":
                # Honour caller-supplied ``limit`` (mapped to ``limit_per_file``
                # for symmetry with other tools) and fall back to 5 — matching
                # ``search_zim_file``'s explicit ``limit_per_file=5`` default.
                result = self.zim_operations.search_all(
                    params.get("query", query),
                    limit_per_file=options.get("limit", 5),
                )
                return result + low_confidence_note
            elif intent == "walk_namespace":
                # zim_file_path was already populated by the function-level
                # auto-select guard above; honor whatever the caller supplied.
                # ``offset`` semantically maps to ``cursor`` here — a resume
                # token, not pagination skip — but it's the only general-purpose
                # passthrough channel so we honour it.
                result = self.zim_operations.walk_namespace(
                    zim_file_path,
                    params.get("namespace", "C"),
                    cursor=options.get("offset", 0),
                    limit=options.get("limit", 200),
                )
                return result + low_confidence_note
            elif intent == "find_by_title":
                result = self.zim_operations.find_entry_by_title(
                    zim_file_path,
                    params.get("title", query),
                    cross_file=False,
                    limit=options.get("limit", 10),
                )
                return result + low_confidence_note
            elif intent == "related":
                result = self.zim_operations.get_related_articles(
                    zim_file_path,
                    params.get("entry_path", ""),
                    limit=options.get("limit", 10),
                )
                return result + low_confidence_note
            elif intent == "get_zim_entries":
                # Batch fetch: route to ZimOperations.get_entries with the
                # extracted path list. If no paths were extracted, return a
                # help response rather than silently falling through to search.
                entry_paths = params.get("entries") or []
                if not entry_paths:
                    return (
                        "**Missing Entry Paths**\n\n"
                        "I couldn't extract entry paths from your query. "
                        "Use namespace/path syntax, e.g., "
                        "'fetch entries C/Photosynthesis C/Cell_biology'."
                    ) + low_confidence_note
                entries = [
                    {"zim_file_path": zim_file_path, "entry_path": p}
                    for p in entry_paths
                ]
                max_content_length = options.get("max_content_length")
                result = self.zim_operations.get_entries(entries, max_content_length)
                return result + low_confidence_note

            else:
                # Fallback to search
                result = self.zim_operations.search_zim_file(
                    zim_file_path, query, options.get("limit"), options.get("offset", 0)
                )
                return result + low_confidence_note

        except Exception as e:
            logger.error(f"Error handling zim_query: {e}")
            # Sanitize both the query and error text to avoid leaking
            # absolute filesystem paths back to the MCP client.
            safe_query = sanitize_context_for_error(query)
            safe_error = sanitize_context_for_error(str(e))
            return (
                f"**Error Processing Query**\n\n"
                f"**Query**: {safe_query}\n"
                f"**Error**: {safe_error}\n\n"
                f"**Troubleshooting**:\n"
                f"1. Check that the ZIM file path is correct\n"
                f"2. Verify the query format\n"
                f"3. Try a simpler query\n"
                f"4. Check server logs for details"
            )

    def _auto_select_zim_file(self) -> Optional[str]:
        """Auto-select a ZIM file if only one is available.

        Returns:
            Path to ZIM file if exactly one exists, None otherwise.
            Returns None with appropriate logging if multiple files exist
            or on error.
        """
        try:
            # Use structured data method directly (not parsing JSON from string)
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
