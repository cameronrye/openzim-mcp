"""Article structure and content analysis tools for OpenZIM MCP server."""

import logging
from typing import TYPE_CHECKING, Optional, Union

from ..constants import INPUT_LIMIT_ENTRY_PATH, INPUT_LIMIT_FILE_PATH
from ..exceptions import OpenZimMcpRateLimitError
from ..responses import ToolErrorPayload, tool_error
from ..security import sanitize_input
from ..tool_schemas import (
    ArticleStructureResponse,
    BinaryEntryResponse,
    EntrySummaryResponse,
    GetSectionResponse,
    LinksResponse,
    RelatedArticlesResponse,
    TableOfContentsResponse,
)

if TYPE_CHECKING:
    from ..server import OpenZimMcpServer

logger = logging.getLogger(__name__)

# Bound for ``get_binary_entry``: reading and base64-encoding is performed
# in memory, so an unbounded value lets a single call attempt to buffer
# arbitrarily large data and exhaust the process.
_MAX_BINARY_LIMIT = 100 * 1024 * 1024  # 100 MB


def register_structure_tools(server: "OpenZimMcpServer") -> None:
    """Register article structure and content analysis tools."""
    _register_get_article_structure(server)
    _register_extract_article_links(server)
    _register_get_entry_summary(server)
    _register_get_table_of_contents(server)
    _register_get_binary_entry(server)
    _register_get_related_articles(server)
    _register_get_section(server)


def _register_get_article_structure(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def get_article_structure(
        zim_file_path: str, entry_path: str
    ) -> Union[ArticleStructureResponse, ToolErrorPayload]:
        """Extract article structure including headings, sections, and key metadata.

        Note: depends on heading markup in the source HTML. ZIM builds with
        the "mini" or "nopic" flavour often strip sub-section headings, in
        which case this tool returns only the top-level H1. Check the ZIM's
        Flavour metadata via get_zim_metadata() if you expect rich structure.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path; replace ``<entry_path>`` with a real path
                from ``find_entry_by_title`` or ``browse_namespace`` (e.g.
                ``"C/Biology"``). Never copy ``<entry_path>`` verbatim.

        Returns:
            Dict containing article structure (title, path, headings, sections,
            metadata, word_count, character_count). On failure, returns a
            ``{"error": True, ...}`` envelope (see ``responses.tool_error``).
        """
        try:
            try:
                server.rate_limiter.check_rate_limit("get_structure")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="get article structure",
                    message=server._create_enhanced_error_message(
                        operation="get article structure",
                        error=e,
                        context=f"Entry: {entry_path}",
                    ),
                    context=f"Entry: {entry_path}",
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)

            return await server.async_zim_operations.get_article_structure_data(
                zim_file_path, entry_path
            )

        except Exception as e:
            logger.error(f"Error getting article structure: {e}")
            return tool_error(
                operation="get article structure",
                message=server._create_enhanced_error_message(
                    operation="get article structure",
                    error=e,
                    context=f"File: {zim_file_path}, Entry: {entry_path}",
                ),
                context=f"File: {zim_file_path}, Entry: {entry_path}",
            )


def _register_extract_article_links(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def extract_article_links(
        zim_file_path: str,
        entry_path: str,
        limit: int = 100,
        offset: int = 0,
        kind: str = "internal",
        cursor: Optional[str] = None,
    ) -> Union[LinksResponse, ToolErrorPayload]:
        """Extract one category of links from an article (paginated).

        v2 BREAKING: each call returns a single category in ``results``.
        ``kind`` is required-with-default (``"internal"``). To enumerate
        every category, issue three calls with ``kind="internal"``,
        ``kind="external"``, and ``kind="media"``. ``category_totals``
        echoes counts for all three so callers can plan their fetches.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path; replace ``<entry_path>`` with a real path
                from ``find_entry_by_title`` or ``browse_namespace`` (e.g.
                ``"C/Biology"``). Never copy ``<entry_path>`` verbatim.
            limit: Max items per page (1-500, default 100).
            offset: Starting offset within the requested category (default 0).
            kind: Which category — ``"internal"`` (default), ``"external"``,
                or ``"media"``.
            cursor: Opaque pagination token from a previous result's
                ``next_cursor`` field. ``None`` starts from ``offset``.

        Returns:
            ``LinksResponse``-shaped dict on success (Phase B contract:
            top-level ``results`` / ``next_cursor`` / ``total`` / ``done``
            / ``page_info`` plus ``title`` / ``path`` / ``content_type`` /
            ``kind`` / ``category_totals``); ``ToolErrorPayload`` envelope
            on failure.
        """
        try:
            # Phase B: cursor wins on conflict per response-contract spec.
            if cursor is not None:
                from ..pagination import Cursor, CursorMismatchError

                try:
                    decoded = Cursor.decode(
                        cursor, expected_tool="extract_article_links"
                    )
                except CursorMismatchError as e:
                    return tool_error(
                        operation="extract article links",
                        message=str(e),
                        context="Tool: extract_article_links, cursor=<truncated>",
                    )
                except ValueError as e:
                    return tool_error(
                        operation="extract article links",
                        message=f"Invalid pagination cursor: {e}",
                        context="Tool: extract_article_links",
                    )
                state = decoded["s"]
                offset = state["o"]
                limit = state.get("l", limit)
                entry_path = state.get("ep", entry_path)
                kind = state.get("k", kind)
                cursor_ai: Optional[str] = state.get("ai")
            else:
                cursor_ai = None

            try:
                server.rate_limiter.check_rate_limit("get_structure")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="extract article links",
                    message=server._create_enhanced_error_message(
                        operation="extract article links",
                        error=e,
                        context=f"Entry: {entry_path}",
                    ),
                    context=f"Entry: {entry_path}",
                )

            if kind not in ("internal", "external", "media"):
                return tool_error(
                    operation="extract article links",
                    message=(
                        "**Parameter Validation Error**\n\n"
                        f"**Issue**: kind must be one of 'internal', "
                        f"'external', 'media' (provided: {kind!r})"
                    ),
                    context=f"Entry: {entry_path}, kind: {kind!r}",
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)

            return await server.async_zim_operations.extract_article_links_data(
                zim_file_path,
                entry_path,
                limit=limit,
                offset=offset,
                kind=kind,
                cursor_archive_identity=cursor_ai,
            )

        except Exception as e:
            logger.error(f"Error extracting article links: {e}")
            return tool_error(
                operation="extract article links",
                message=server._create_enhanced_error_message(
                    operation="extract article links",
                    error=e,
                    context=f"File: {zim_file_path}, Entry: {entry_path}",
                ),
                context=f"File: {zim_file_path}, Entry: {entry_path}",
            )


def _register_get_entry_summary(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def get_entry_summary(
        zim_file_path: str,
        entry_path: str,
        max_words: int = 200,
        compact: bool = False,
    ) -> Union[EntrySummaryResponse, ToolErrorPayload]:
        """Get a concise summary of an article without returning the full content.

        This tool extracts the opening paragraph(s) or introduction section,
        providing a quick overview of the article content. Useful for getting
        context without loading full articles.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path; replace ``<entry_path>`` with a real path
                from ``find_entry_by_title`` or ``browse_namespace`` (e.g.
                ``"C/Biology"``). Never copy ``<entry_path>`` verbatim.
            max_words: Maximum number of words in the summary (default: 200, max: 1000)
            compact: Op2 — when True, render the summary with compact
                semantics (infoboxes extracted, oversized tables
                replaced). Defaults to False (v1.2.0-compatible).

        Returns:
            ``EntrySummaryResponse``-shaped dict with ``path``, ``title``,
            ``summary``, optionally ``word_count``/``content_type``/
            ``is_truncated``, plus the ``_meta`` envelope. On failure,
            returns a ``ToolErrorPayload`` envelope (see
            ``responses.tool_error``).

        Examples (call ``list_zim_files`` first for the real ``zim_file_path``;
        the placeholder ``<zim_path>`` below must be replaced with that
        real path, never copied verbatim):
            - Quick overview: get_entry_summary(<zim_path>, "Biology")
            - Longer summary: get_entry_summary(<zim_path>, "Evolution", max_words=500)
            - Compact body: get_entry_summary(<zim_path>, "Tiger", compact=True)
        """
        try:
            try:
                server.rate_limiter.check_rate_limit("get_entry")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="get entry summary",
                    message=server._create_enhanced_error_message(
                        operation="get entry summary",
                        error=e,
                        context=f"Entry: {entry_path}",
                    ),
                    context=f"Entry: {entry_path}",
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)

            if max_words < 1 or max_words > 1000:
                return tool_error(
                    operation="get entry summary",
                    message=(
                        "**Parameter Validation Error**\n\n"
                        f"**Issue**: max_words must be between 1 and 1000 "
                        f"(provided: {max_words})\n\n"
                        "**Troubleshooting**: Adjust max_words to a value within "
                        "the valid range.\n"
                        "**Example**: Use `max_words=200` for a typical summary."
                    ),
                    context=f"Entry: {entry_path}, max_words: {max_words}",
                )

            return await server.async_zim_operations.get_entry_summary_data(
                zim_file_path, entry_path, max_words, compact=compact
            )

        except Exception as e:
            logger.error(f"Error getting entry summary: {e}")
            return tool_error(
                operation="get entry summary",
                message=server._create_enhanced_error_message(
                    operation="get entry summary",
                    error=e,
                    context=f"File: {zim_file_path}, Entry: {entry_path}",
                ),
                context=f"File: {zim_file_path}, Entry: {entry_path}",
            )


def _register_get_table_of_contents(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def get_table_of_contents(
        zim_file_path: str,
        entry_path: str,
    ) -> Union[TableOfContentsResponse, ToolErrorPayload]:
        """Extract a hierarchical table of contents from an article.

        Returns a structured TOC tree based on heading levels (h1-h6),
        suitable for navigation and content overview.

        Note: depends on heading markup in the source HTML. ZIM builds with
        the "mini" or "nopic" flavour often strip sub-section headings, in
        which case this tool returns only the top-level H1 (heading_count=1).
        If you expect rich structure, check the ZIM's Flavour metadata via
        get_zim_metadata() first.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Entry path; replace ``<entry_path>`` with a real path
                from ``find_entry_by_title`` or ``browse_namespace`` (e.g.
                ``"C/Biology"``). Never copy ``<entry_path>`` verbatim.

        Returns:
            Dict containing:
            - title: Article title
            - path: Entry path
            - toc: Hierarchical list of headings with children
            - heading_count: Total number of headings
            - max_depth: Deepest heading level used

            On failure, returns a ``{"error": True, ...}`` envelope (see
            ``responses.tool_error``).

        Each TOC entry contains:
            - level: Heading level (1-6)
            - text: Heading text
            - section_id: Section identifier — pass to get_section(section_id=...)
              to fetch this heading's body. Renamed from the legacy ``id`` field
              in Phase C; clients that read ``heading["id"]`` will get a KeyError.
            - id_source: How the section_id was derived — ``"id"`` /
              ``"descendant_anchor"`` / ``"preceding_anchor"`` (stable, author-provided)
              or ``"slug"`` (generated from heading text).
            - children: Nested subheadings

        Examples (replace ``<zim_path>`` with the real path returned by
        ``list_zim_files`` — never copy the placeholder verbatim):
            - Get TOC: get_table_of_contents(<zim_path>, "Biology")
        """
        try:
            try:
                server.rate_limiter.check_rate_limit("get_structure")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="get table of contents",
                    message=server._create_enhanced_error_message(
                        operation="get table of contents",
                        error=e,
                        context=f"Entry: {entry_path}",
                    ),
                    context=f"Entry: {entry_path}",
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)

            return await server.async_zim_operations.get_table_of_contents_data(
                zim_file_path, entry_path
            )

        except Exception as e:
            logger.error(f"Error getting table of contents: {e}")
            return tool_error(
                operation="get table of contents",
                message=server._create_enhanced_error_message(
                    operation="get table of contents",
                    error=e,
                    context=f"File: {zim_file_path}, Entry: {entry_path}",
                ),
                context=f"File: {zim_file_path}, Entry: {entry_path}",
            )


def _register_get_binary_entry(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def get_binary_entry(
        zim_file_path: str,
        entry_path: str,
        max_size_bytes: Optional[int] = None,
        include_data: bool = True,
    ) -> Union[BinaryEntryResponse, ToolErrorPayload]:
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
            Dict containing:
            - path: Entry path in ZIM file
            - title: Entry title
            - mime_type: Content type (e.g., "application/pdf", "image/png")
            - size: Size in bytes
            - size_human: Human-readable size (e.g., "1.5 MB")
            - encoding: "base64" when data is included, null otherwise
            - data: Base64-encoded content (if include_data=True and under size limit)
            - truncated: Boolean indicating if content exceeded size limit

            On failure, returns a ``{"error": True, ...}`` envelope (see
            ``responses.tool_error``).

        Examples (replace ``<zim_path>`` with the real path returned by
        ``list_zim_files`` — never copy the placeholder verbatim):
            - Get a PDF: get_binary_entry(<zim_path>, "I/document.pdf")
            - Image metadata: get_binary_entry(<zim_path>, "I/logo.png", include_data=False)
            - Large video: get_binary_entry(<zim_path>, "I/video.mp4", 100000000)
        """
        try:
            try:
                server.rate_limiter.check_rate_limit("get_binary_entry")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="retrieve binary entry",
                    message=server._create_enhanced_error_message(
                        operation="retrieve binary entry",
                        error=e,
                        context=f"Entry: {entry_path}",
                    ),
                    context=f"Entry: {entry_path}",
                )

            if max_size_bytes is not None and (
                max_size_bytes < 1 or max_size_bytes > _MAX_BINARY_LIMIT
            ):
                return tool_error(
                    operation="retrieve binary entry",
                    message=(
                        "**Parameter Validation Error**\n\n"
                        f"**Issue**: max_size_bytes must be between 1 and "
                        f"{_MAX_BINARY_LIMIT} bytes (100 MB), got "
                        f"{max_size_bytes}.\n"
                        "**Tip**: For larger entries, retrieve the entry in "
                        "chunks via repeated calls or use include_data=False to "
                        "fetch metadata only."
                    ),
                    context=(f"Entry: {entry_path}, max_size_bytes: {max_size_bytes}"),
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)

            return await server.async_zim_operations.get_binary_entry_data(
                zim_file_path, entry_path, max_size_bytes, include_data
            )

        except Exception as e:
            logger.error(f"Error retrieving binary entry: {e}")
            return tool_error(
                operation="retrieve binary entry",
                message=server._create_enhanced_error_message(
                    operation="retrieve binary entry",
                    error=e,
                    context=f"File: {zim_file_path}, Entry: {entry_path}",
                ),
                context=f"File: {zim_file_path}, Entry: {entry_path}",
            )


def _register_get_related_articles(server: "OpenZimMcpServer") -> None:
    @server.mcp.tool()
    async def get_related_articles(
        zim_file_path: str,
        entry_path: str,
        limit: int = 10,
    ) -> Union[RelatedArticlesResponse, ToolErrorPayload]:
        """Find articles related to entry_path via outbound links.

        Composes extract_article_links and deduplicates internal links,
        returning up to `limit` outbound targets. (Inbound discovery was
        removed — it required a bounded full-archive scan that was too
        expensive for interactive use; reach for full-text search instead.)

        v2 BREAKING: ``outbound_results`` renamed to ``results``.
        Anticipates Phase E inbound-link feature where ``direction`` becomes
        a parameter; the ``results`` field then covers either side.

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Source entry path; replace ``<entry_path>`` with a real
                path from ``find_entry_by_title`` or ``browse_namespace``
                (e.g. ``"C/Biology"``). Never copy ``<entry_path>`` verbatim.
            limit: Max results (1-100, default: 10)

        Returns:
            ``RelatedArticlesResponse``-shaped dict on success (Phase B
            contract: top-level ``results`` / ``next_cursor`` / ``total``
            / ``done`` / ``page_info`` plus tool-specific ``entry_path``;
            ``outbound_error`` set on partial-success). ``results`` is a
            list of ``{path, title, link_text}`` records. ``title`` is the
            linked entry's actual archive title (resolved by archive
            lookup; falls back to ``path`` when the entry is missing).
            ``link_text`` is the original anchor text from the source
            article — useful when the source links to the target with a
            different display string. On failure, returns a
            ``ToolErrorPayload`` envelope (see ``responses.tool_error``).
        """
        try:
            try:
                server.rate_limiter.check_rate_limit("get_related_articles")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation="get related articles",
                    message=server._create_enhanced_error_message(
                        operation="get related articles",
                        error=e,
                        context=f"Entry: {entry_path}",
                    ),
                    context=f"Entry: {entry_path}",
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)

            return await server.async_zim_operations.get_related_articles_data(
                zim_file_path,
                entry_path,
                limit,
            )

        except Exception as e:
            logger.error(f"Error in get_related_articles: {e}")
            return tool_error(
                operation="get related articles",
                message=server._create_enhanced_error_message(
                    operation="get related articles",
                    error=e,
                    context=f"File: {zim_file_path}, Entry: {entry_path}",
                ),
                context=f"File: {zim_file_path}, Entry: {entry_path}",
            )


def _register_get_section(server: "OpenZimMcpServer") -> None:
    _op = "get section"

    @server.mcp.tool()
    async def get_section(
        zim_file_path: str,
        entry_path: str,
        section_id: str,
        max_chars: Optional[int] = None,
        include_subsections: bool = True,
    ) -> Union[GetSectionResponse, ToolErrorPayload]:
        """Fetch a single section from an entry by its section_id.

        section_id values come from get_table_of_contents (TocHeading.section_id)
        or get_article_structure (heading[].id). Returns the section body as
        markdown plus metadata. Sections are sized for direct consumption
        (≈500-1500 tokens); a max_chars cap truncates the body and sets
        truncated=True.

        On a miss (no section with that id), returns a ToolErrorPayload with
        error="section_not_found" and available_section_ids in the payload so
        the model can self-correct.

        Args:
            zim_file_path: Path to the ZIM file.
            entry_path: Entry path (e.g., 'C/Berlin'). Use the
                namespace convention from the archive's actual paths
                (modern Wikipedia ZIMs use ``C/``; legacy ZIMs use
                ``A/``) — call ``find_entry_by_title`` first to
                discover the real namespace before copying.
            section_id: Section identifier from TOC.
            max_chars: Optional cap on section body chars (default uses
                       config.content.max_content_length).
            include_subsections: When True (default), the returned slice
                covers the section plus its nested children (Geography
                returns Geography + Topography + Climate). When False,
                the slice ends at the next heading of *any* level, so
                only the section's own body — not its sub-tree — is
                returned. Use False when the caller already has the
                TOC and wants to drill into one heading at a time.
        """
        try:
            try:
                server.rate_limiter.check_rate_limit("get_structure")
            except OpenZimMcpRateLimitError as e:
                return tool_error(
                    operation=_op,
                    message=server._create_enhanced_error_message(
                        operation=_op,
                        error=e,
                        context=f"Entry: {entry_path}, section_id: {section_id}",
                    ),
                    context=f"Entry: {entry_path}, section_id: {section_id}",
                )

            zim_file_path = sanitize_input(zim_file_path, INPUT_LIMIT_FILE_PATH)
            entry_path = sanitize_input(entry_path, INPUT_LIMIT_ENTRY_PATH)

            return await server.async_zim_operations.get_section_data(
                zim_file_path,
                entry_path,
                section_id,
                max_chars=max_chars,
                include_subsections=include_subsections,
            )

        except Exception as e:
            logger.error(f"Error in get_section: {e}")
            return tool_error(
                operation=_op,
                message=server._create_enhanced_error_message(
                    operation=_op,
                    error=e,
                    context=f"File: {zim_file_path}, Entry: {entry_path}, "
                    f"section_id: {section_id}",
                ),
                context=f"File: {zim_file_path}, Entry: {entry_path}, "
                f"section_id: {section_id}",
            )
