"""
Article structure and content analysis tools for OpenZIM MCP server.
"""

import logging
from typing import TYPE_CHECKING, Optional

from ..constants import INPUT_LIMIT_ENTRY_PATH, INPUT_LIMIT_FILE_PATH
from ..exceptions import OpenZimMcpRateLimitError
from ..security import sanitize_input

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)


def register_structure_tools(server: "OpenZimMcpServer") -> None:
    """
    Register article structure and content analysis tools.

    Args:
        server: The OpenZimMcpServer instance to register tools on
    """

    @server.mcp.tool()
    async def get_article_structure(zim_file_path: str, entry_path: str) -> str:
        """Extract article structure including headings, sections, and key metadata.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'C/Some_Article'

        Returns:
            JSON string containing article structure
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("get_structure")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="get article structure",
                    error=e,
                    context=f"Entry: {entry_path}",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)

            # Use async operations
            return await server.async_zim_operations.get_article_structure(
                zim_file_path, entry_path
            )

        except Exception as e:
            logger.error(f"Error getting article structure: {e}")
            return server._create_enhanced_error_message(
                operation="get article structure",
                error=e,
                context=f"File: {zim_file_path}, Entry: {entry_path}",
            )

    @server.mcp.tool()
    async def extract_article_links(zim_file_path: str, entry_path: str) -> str:
        """Extract internal and external links from an article.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'C/Some_Article'

        Returns:
            JSON string containing extracted links
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("get_structure")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="extract article links",
                    error=e,
                    context=f"Entry: {entry_path}",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)

            # Use async operations
            return await server.async_zim_operations.extract_article_links(
                zim_file_path, entry_path
            )

        except Exception as e:
            logger.error(f"Error extracting article links: {e}")
            return server._create_enhanced_error_message(
                operation="extract article links",
                error=e,
                context=f"File: {zim_file_path}, Entry: {entry_path}",
            )

    @server.mcp.tool()
    async def get_entry_summary(
        zim_file_path: str,
        entry_path: str,
        max_words: int = 200,
    ) -> str:
        """Get a concise summary of an article without returning the full content.

        This tool extracts the opening paragraph(s) or introduction section,
        providing a quick overview of the article content. Useful for getting
        context without loading full articles.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'C/Some_Article'
            max_words: Maximum number of words in the summary (default: 200, max: 1000)

        Returns:
            JSON string containing:
            - title: Article title
            - path: Entry path
            - summary: Extracted summary text
            - word_count: Number of words in summary
            - is_truncated: Whether the summary was truncated

        Examples:
            - Quick overview: get_entry_summary("/path/to/wiki.zim", "Biology")
            - Longer summary: get_entry_summary(..., "Evolution", max_words=500)
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("get_entry")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="get entry summary",
                    error=e,
                    context=f"Entry: {entry_path}",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)

            # Use async operations
            return await server.async_zim_operations.get_entry_summary(
                zim_file_path, entry_path, max_words
            )

        except Exception as e:
            logger.error(f"Error getting entry summary: {e}")
            return server._create_enhanced_error_message(
                operation="get entry summary",
                error=e,
                context=f"File: {zim_file_path}, Entry: {entry_path}",
            )

    @server.mcp.tool()
    async def get_table_of_contents(
        zim_file_path: str,
        entry_path: str,
    ) -> str:
        """Extract a hierarchical table of contents from an article.

        Returns a structured TOC tree based on heading levels (h1-h6),
        suitable for navigation and content overview.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'C/Some_Article'

        Returns:
            JSON string containing:
            - title: Article title
            - path: Entry path
            - toc: Hierarchical list of headings with children
            - heading_count: Total number of headings
            - max_depth: Deepest heading level used

        Each TOC entry contains:
            - level: Heading level (1-6)
            - text: Heading text
            - id: Anchor ID for linking
            - children: Nested subheadings

        Examples:
            - Get TOC: get_table_of_contents("/path/to/wiki.zim", "Biology")
        """
        try:
            # Check rate limit
            try:
                server.rate_limiter.check_rate_limit("get_structure")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="get table of contents",
                    error=e,
                    context=f"Entry: {entry_path}",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)

            # Use async operations
            return await server.async_zim_operations.get_table_of_contents(
                zim_file_path, entry_path
            )

        except Exception as e:
            logger.error(f"Error getting table of contents: {e}")
            return server._create_enhanced_error_message(
                operation="get table of contents",
                error=e,
                context=f"File: {zim_file_path}, Entry: {entry_path}",
            )

    @server.mcp.tool()
    async def get_binary_entry(
        zim_file_path: str,
        entry_path: str,
        max_size_bytes: Optional[int] = None,
        include_data: bool = True,
    ) -> str:
        """Retrieve binary content from a ZIM entry.

        This tool returns raw binary content encoded in base64, enabling
        integration with external tools for processing embedded media like
        PDFs, videos, and images.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path, e.g., 'I/image.png' or 'C/document.pdf'
            max_size_bytes: Maximum size of content to return (default: 10MB).
                Content larger than this will return metadata only.
            include_data: If True (default), include base64-encoded data.
                Set to False to retrieve metadata only without the binary data.

        Returns:
            JSON string containing:
            - path: Entry path in ZIM file
            - title: Entry title
            - mime_type: Content type (e.g., "application/pdf", "image/png")
            - size: Size in bytes
            - size_human: Human-readable size (e.g., "1.5 MB")
            - encoding: "base64" when data is included, null otherwise
            - data: Base64-encoded content (if include_data=True and under size limit)
            - truncated: Boolean indicating if content exceeded size limit

        Examples:
            - Get a PDF: get_binary_entry("/path/to/file.zim", "I/document.pdf")
            - Get image metadata: get_binary_entry(..., "I/logo.png", include_data=False)
            - Large video: get_binary_entry(..., "I/video.mp4", max_size_bytes=100000000)
        """
        try:
            # Check rate limit (binary is most expensive)
            try:
                server.rate_limiter.check_rate_limit("get_binary_entry")
            except OpenZimMcpRateLimitError as e:
                return server._create_enhanced_error_message(
                    operation="retrieve binary entry",
                    error=e,
                    context=f"Entry: {entry_path}",
                )

            # Sanitize inputs
            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)

            # Use async operations
            return await server.async_zim_operations.get_binary_entry(
                zim_file_path, entry_path, max_size_bytes, include_data
            )

        except Exception as e:
            logger.error(f"Error retrieving binary entry: {e}")
            return server._create_enhanced_error_message(
                operation="retrieve binary entry",
                error=e,
                context=f"File: {zim_file_path}, Entry: {entry_path}",
            )
