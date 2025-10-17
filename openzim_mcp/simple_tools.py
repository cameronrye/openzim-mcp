"""
Simple tools implementation for OpenZIM MCP server.

This module provides intelligent, natural language-based tools that abstract
away the complexity of multiple specialized tools. Designed for LLMs with
limited tool-calling capabilities or context windows.
"""

import logging
import re
from typing import Any, Dict, Optional, Tuple

from .zim_operations import ZimOperations

logger = logging.getLogger(__name__)


class IntentParser:
    """Parse natural language queries to determine user intent."""

    # Intent patterns with priority (checked in order)
    INTENT_PATTERNS = [
        # File listing intents
        (
            r"\b(list|show|what|available|get)\s+(files?|zim|archives?)\b",
            "list_files",
        ),
        # Metadata intents (more specific patterns)
        (
            r"\b(metadata|info|details?)\s+(for|about|of)\s+(file|zim|archive)\b",
            "metadata",
        ),
        (
            r"\b(metadata|info|details?)\s+(for|about|of)\s+this\s+(file|zim|archive)\b",
            "metadata",
        ),
        (r"\b(metadata|info|details?)\s+for\b", "metadata"),
        (r"\binfo\s+about\b", "metadata"),
        (r"\bdetails?\s+of\b", "metadata"),
        # Main page intents
        (r"\b(main|home|start)\s+page\b", "main_page"),
        # Namespace listing intents
        (r"\b(list|show|what)\s+namespaces?\b", "list_namespaces"),
        # Browse intents
        (r"\b(browse|explore|show|list)\s+(namespace|articles?|entries)\b", "browse"),
        # Article structure intents
        (r"\b(structure|outline|sections?|headings?)\s+(of|for)?\b", "structure"),
        # Links extraction intents
        (r"\b(links?|references?|related)\s+(in|from|to)\b", "links"),
        # Suggestions intents (more specific)
        (r"\b(suggestions?|autocomplete|complete|hints?)\s+(for|of)\b", "suggestions"),
        (r"\b(suggest|autocomplete|complete)\b", "suggestions"),
        # Filtered search intents
        (
            r"\b(search|find|look)\s+.+\s+(in|within)\s+(namespace|type)\b",
            "filtered_search",
        ),
        # Get article intents (specific)
        (r"\b(get|show|read|display|fetch)\s+(article|entry|page)\b", "get_article"),
        # Search intents (general)
        (r"\b(search|find|look\s+for|query)\b", "search"),
    ]

    @classmethod
    def parse_intent(cls, query: str) -> Tuple[str, Dict[str, Any]]:
        """
        Parse a natural language query to determine intent.

        Args:
            query: Natural language query string

        Returns:
            Tuple of (intent_type, extracted_params)
        """
        query_lower = query.lower()

        # Check each pattern in priority order
        for pattern, intent in cls.INTENT_PATTERNS:
            if re.search(pattern, query_lower, re.IGNORECASE):
                params = cls._extract_params(query, intent)
                return intent, params

        # Default to search if no specific intent detected
        return "search", {"query": query}

    @classmethod
    def _extract_params(cls, query: str, intent: str) -> Dict[str, Any]:
        """
        Extract parameters from query based on intent.

        Args:
            query: Original query string
            intent: Detected intent type

        Returns:
            Dictionary of extracted parameters
        """
        params: Dict[str, Any] = {}

        if intent == "browse":
            # Extract namespace from query
            namespace_match = re.search(
                r"namespace\s+['\"]?([A-Za-z0-9_.-]+)['\"]?", query, re.IGNORECASE
            )
            if namespace_match:
                params["namespace"] = namespace_match.group(1)

        elif intent == "filtered_search":
            # Extract search query and filters
            # Try to extract the search term
            search_match = re.search(
                r"(?:search|find|look)\s+(?:for\s+)?['\"]?([^'\"]+?)['\"]?\s+(?:in|within)",
                query,
                re.IGNORECASE,
            )
            if search_match:
                params["query"] = search_match.group(1).strip()

            # Extract namespace filter
            namespace_match = re.search(
                r"namespace\s+['\"]?([A-Za-z0-9_.-]+)['\"]?", query, re.IGNORECASE
            )
            if namespace_match:
                params["namespace"] = namespace_match.group(1)

            # Extract content type filter
            type_match = re.search(
                r"type\s+['\"]?([A-Za-z0-9_/.-]+)['\"]?", query, re.IGNORECASE
            )
            if type_match:
                params["content_type"] = type_match.group(1)

        elif intent in ["get_article", "structure", "links"]:
            # Extract article/entry path
            # Try to find quoted strings first
            quoted_match = re.search(r"['\"]([^'\"]+)['\"]", query)
            if quoted_match:
                params["entry_path"] = quoted_match.group(1)
            else:
                # Try to extract after keywords
                # For links: "links in Biology", "references from Evolution"
                # For structure: "structure of Biology"
                # For get_article: "get article Biology"
                path_match = re.search(
                    r"(?:article|entry|page|of|for|in|from|to)\s+([A-Za-z0-9_/.-]+)",
                    query,
                    re.IGNORECASE,
                )
                if path_match:
                    params["entry_path"] = path_match.group(1)

        elif intent == "suggestions":
            # Extract partial query
            suggest_match = re.search(
                r"(?:suggestions?|autocomplete|complete|hints?)\s+(?:for\s+)?['\"]?([^'\"]+)['\"]?",
                query,
                re.IGNORECASE,
            )
            if suggest_match:
                params["partial_query"] = suggest_match.group(1).strip()

        elif intent == "search":
            # For general search, use the whole query or extract search term
            search_match = re.search(
                r"(?:search|find|look)\s+(?:for\s+)?['\"]?([^'\"]+)['\"]?",
                query,
                re.IGNORECASE,
            )
            if search_match:
                params["query"] = search_match.group(1).strip()
            else:
                params["query"] = query

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

            # Parse intent from query
            intent, params = self.intent_parser.parse_intent(query)
            logger.info(f"Parsed intent: {intent}, params: {params}")

            # Handle file listing (doesn't require zim_file_path)
            if intent == "list_files":
                return self.zim_operations.list_zim_files()

            # Auto-select ZIM file if not provided
            if not zim_file_path:
                zim_file_path = self._auto_select_zim_file()
                if not zim_file_path:
                    return (
                        "❌ **No ZIM File Specified**\n\n"
                        "Please specify a ZIM file path, or ensure there is exactly one ZIM file available.\n\n"
                        "**Available files:**\n"
                        f"{self.zim_operations.list_zim_files()}"
                    )

            # Route to appropriate operation based on intent
            if intent == "metadata":
                return self.zim_operations.get_zim_metadata(zim_file_path)

            elif intent == "main_page":
                return self.zim_operations.get_main_page(zim_file_path)

            elif intent == "list_namespaces":
                return self.zim_operations.list_namespaces(zim_file_path)

            elif intent == "browse":
                namespace = params.get("namespace", "C")
                limit = options.get("limit", 50)
                offset = options.get("offset", 0)
                return self.zim_operations.browse_namespace(
                    zim_file_path, namespace, limit, offset
                )

            elif intent == "structure":
                entry_path = params.get("entry_path")
                if not entry_path:
                    return (
                        "⚠️ **Missing Article Path**\n\n"
                        "Please specify which article you want to get the structure for.\n"
                        "**Example**: 'structure of Biology' or 'structure of \"C/Evolution\"'"
                    )
                return self.zim_operations.get_article_structure(
                    zim_file_path, entry_path
                )

            elif intent == "links":
                entry_path = params.get("entry_path")
                if not entry_path:
                    return (
                        "⚠️ **Missing Article Path**\n\n"
                        "Please specify which article you want to extract links from.\n"
                        "**Example**: 'links in Biology' or 'links from \"C/Evolution\"'"
                    )
                return self.zim_operations.extract_article_links(
                    zim_file_path, entry_path
                )

            elif intent == "suggestions":
                partial_query = params.get("partial_query", "")
                if not partial_query:
                    return (
                        "⚠️ **Missing Search Term**\n\n"
                        "Please specify what you want suggestions for.\n"
                        "**Example**: 'suggestions for bio' or 'autocomplete \"evol\"'"
                    )
                limit = options.get("limit", 10)
                return self.zim_operations.get_search_suggestions(
                    zim_file_path, partial_query, limit
                )

            elif intent == "filtered_search":
                search_query = params.get("query", query)
                namespace = params.get("namespace")
                content_type = params.get("content_type")
                limit = options.get("limit")
                offset = options.get("offset", 0)
                return self.zim_operations.search_with_filters(
                    zim_file_path, search_query, namespace, content_type, limit, offset
                )

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
                            "⚠️ **Missing Article Path**\n\n"
                            "Please specify which article you want to read.\n"
                            "**Example**: 'get article Biology' or 'show \"C/Evolution\"'"
                        )
                max_content_length = options.get("max_content_length")
                return self.zim_operations.get_zim_entry(
                    zim_file_path, entry_path, max_content_length
                )

            elif intent == "search":
                search_query = params.get("query", query)
                limit = options.get("limit")
                offset = options.get("offset", 0)
                return self.zim_operations.search_zim_file(
                    zim_file_path, search_query, limit, offset
                )

            else:
                # Fallback to search
                return self.zim_operations.search_zim_file(
                    zim_file_path, query, options.get("limit"), options.get("offset", 0)
                )

        except Exception as e:
            logger.error(f"Error handling zim_query: {e}")
            return (
                f"❌ **Error Processing Query**\n\n"
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
            Path to ZIM file if exactly one exists, None otherwise
        """
        try:
            import json

            files_result = self.zim_operations.list_zim_files()

            # Try to parse the JSON response
            # The list_zim_files returns a formatted string, so we need to extract the JSON
            if "[" in files_result and "]" in files_result:
                start = files_result.index("[")
                end = files_result.rindex("]") + 1
                files_json = files_result[start:end]
                files = json.loads(files_json)

                if len(files) == 1:
                    return str(files[0]["path"])

        except Exception as e:
            logger.warning(f"Could not auto-select ZIM file: {e}")

        return None

    def handle_server_status(self, action: Optional[str] = None) -> str:
        """
        Handle server management and diagnostics queries.

        This intelligent tool routes server management queries to appropriate
        underlying operations.

        Args:
            action: Optional action or natural language query
                   (e.g., "health", "diagnose", "fix", or natural language)

        Returns:
            Response string with server status information
        """
        try:
            # If no action specified, default to health check
            if not action:
                # Import here to avoid circular dependency
                from .server import OpenZimMcpServer  # noqa: F401

                # We need access to the server instance methods
                # This will be called from the server context
                # For now, return a helpful message
                return (
                    "ℹ️ **Server Status Tool**\n\n"
                    "Please specify what you want to check:\n"
                    "- 'health' or 'status' - Get server health and statistics\n"
                    "- 'diagnose' or 'check' - Run comprehensive diagnostics\n"
                    "- 'fix' or 'resolve' - Resolve server conflicts\n"
                    "- 'config' or 'configuration' - Get server configuration\n\n"
                    "**Example**: 'health' or 'diagnose server'"
                )

            action_lower = action.lower()

            # Parse intent from action
            if any(
                keyword in action_lower
                for keyword in ["health", "status", "stats", "performance"]
            ):
                intent = "health"
            elif any(
                keyword in action_lower
                for keyword in ["diagnose", "check", "problems", "issues", "validate"]
            ):
                intent = "diagnose"
            elif any(
                keyword in action_lower
                for keyword in ["fix", "resolve", "conflicts", "cleanup", "repair"]
            ):
                intent = "resolve"
            elif any(
                keyword in action_lower
                for keyword in ["config", "configuration", "settings", "setup"]
            ):
                intent = "config"
            else:
                # Default to health check
                intent = "health"

            # Return intent information
            # The actual routing will be done in the server.py when registering tools
            return f"Intent: {intent}, Action: {action}"

        except Exception as e:
            logger.error(f"Error handling server_status: {e}")
            return (
                f"❌ **Error Processing Server Status Query**\n\n"
                f"**Action**: {action}\n"
                f"**Error**: {str(e)}\n\n"
                f"**Troubleshooting**:\n"
                f"1. Try a simpler action like 'health' or 'diagnose'\n"
                f"2. Check server logs for details"
            )
