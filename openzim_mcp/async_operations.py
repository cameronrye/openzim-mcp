"""
Async wrappers for ZIM operations.

This module provides async versions of ZimOperations methods by wrapping
the synchronous operations with asyncio.to_thread() to prevent blocking
the event loop during I/O-bound operations.
"""

import asyncio
import logging
from typing import Dict, List, Optional

from .zim_operations import ZimOperations

logger = logging.getLogger(__name__)


class AsyncZimOperations:
    """Async wrapper for ZimOperations.

    Provides async versions of all ZimOperations methods that run
    the underlying sync operations in a thread pool to prevent
    blocking the event loop.
    """

    def __init__(self, zim_operations: ZimOperations):
        """Initialize async operations wrapper.

        Args:
            zim_operations: Underlying synchronous ZimOperations instance
        """
        self._ops = zim_operations
        logger.debug("AsyncZimOperations initialized")

    @property
    def sync_ops(self) -> ZimOperations:
        """Access the underlying synchronous operations."""
        return self._ops

    async def list_zim_files(self, name_filter: Optional[str] = None) -> str:
        """List all ZIM files in allowed directories (async).

        Args:
            name_filter: Optional case-insensitive substring filter on filename.

        Returns:
            JSON string containing the list of ZIM files
        """
        return await asyncio.to_thread(
            self._ops.list_zim_files, name_filter=name_filter
        )

    async def list_zim_files_data(self, name_filter: Optional[str] = None) -> list:
        """List all ZIM files as structured data (async).

        Args:
            name_filter: Optional case-insensitive substring filter on filename.

        Returns:
            List of dictionaries containing ZIM file information
        """
        return await asyncio.to_thread(
            self._ops.list_zim_files_data, name_filter=name_filter
        )

    async def list_zim_files_summary_data(
        self, name_filter: Optional[str] = None
    ) -> dict:
        """Structured variant of ``list_zim_files`` (async).

        Returns the count/directories_count/name_filter/files envelope
        used by the migrated MCP tool.
        """
        return await asyncio.to_thread(
            self._ops.list_zim_files_summary_data, name_filter=name_filter
        )

    async def search_zim_file(
        self,
        zim_file_path: str,
        query: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> str:
        """Search within ZIM file content (async).

        Args:
            zim_file_path: Path to the ZIM file
            query: Search query term
            limit: Maximum number of results to return
            offset: Result starting offset (for pagination)

        Returns:
            Search result text
        """
        return await asyncio.to_thread(
            self._ops.search_zim_file, zim_file_path, query, limit, offset
        )

    async def get_zim_entry(
        self,
        zim_file_path: str,
        entry_path: str,
        max_content_length: Optional[int] = None,
        content_offset: int = 0,
    ) -> str:
        """Get an entry from a ZIM file (async).

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Path to the entry within the ZIM file
            max_content_length: Maximum content length to return
            content_offset: Character offset to start reading from (default 0)

        Returns:
            Entry content as text
        """
        return await asyncio.to_thread(
            self._ops.get_zim_entry,
            zim_file_path,
            entry_path,
            max_content_length,
            content_offset,
        )

    async def get_entries(
        self,
        entries: List[Dict[str, str]],
        max_content_length: Optional[int] = None,
    ) -> str:
        """Fetch multiple ZIM entries in one call (async).

        Args:
            entries: list of ``{"zim_file_path", "entry_path"}`` dicts.
            max_content_length: per-entry max content length.

        Returns:
            JSON string with results, succeeded, failed counts.
        """
        return await asyncio.to_thread(
            self._ops.get_entries,
            entries,
            max_content_length,
        )

    async def get_zim_metadata(self, zim_file_path: str) -> str:
        """Get metadata for a ZIM file (async).

        Args:
            zim_file_path: Path to the ZIM file

        Returns:
            Metadata as JSON string
        """
        return await asyncio.to_thread(self._ops.get_zim_metadata, zim_file_path)

    async def get_zim_metadata_data(self, zim_file_path: str) -> dict:
        """Structured variant of ``get_zim_metadata`` (async)."""
        return await asyncio.to_thread(self._ops.get_zim_metadata_data, zim_file_path)

    async def get_main_page(self, zim_file_path: str) -> str:
        """Get the main page of a ZIM file (async).

        Args:
            zim_file_path: Path to the ZIM file

        Returns:
            Main page content
        """
        return await asyncio.to_thread(self._ops.get_main_page, zim_file_path)

    async def list_namespaces(self, zim_file_path: str) -> str:
        """List all namespaces in a ZIM file (async).

        Args:
            zim_file_path: Path to the ZIM file

        Returns:
            Namespaces as JSON string
        """
        return await asyncio.to_thread(self._ops.list_namespaces, zim_file_path)

    async def list_namespaces_data(self, zim_file_path: str) -> dict:
        """Structured variant of ``list_namespaces`` (async)."""
        return await asyncio.to_thread(self._ops.list_namespaces_data, zim_file_path)

    async def browse_namespace(
        self,
        zim_file_path: str,
        namespace: str = "C",
        limit: int = 50,
        offset: int = 0,
    ) -> str:
        """Browse entries in a namespace (async).

        Args:
            zim_file_path: Path to the ZIM file
            namespace: Namespace to browse
            limit: Maximum number of entries
            offset: Starting offset

        Returns:
            Entries as JSON string
        """
        return await asyncio.to_thread(
            self._ops.browse_namespace, zim_file_path, namespace, limit, offset
        )

    async def browse_namespace_data(
        self,
        zim_file_path: str,
        namespace: str = "C",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """Structured variant of ``browse_namespace`` (async)."""
        return await asyncio.to_thread(
            self._ops.browse_namespace_data,
            zim_file_path,
            namespace,
            limit,
            offset,
        )

    async def search_with_filters(
        self,
        zim_file_path: str,
        query: str,
        namespace: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> str:
        """Search with filters (async).

        Args:
            zim_file_path: Path to the ZIM file
            query: Search query
            namespace: Optional namespace filter
            content_type: Optional content type filter
            limit: Maximum results
            offset: Starting offset

        Returns:
            Search results as JSON string
        """
        return await asyncio.to_thread(
            self._ops.search_with_filters,
            zim_file_path,
            query,
            namespace,
            content_type,
            limit,
            offset,
        )

    async def get_search_suggestions(
        self,
        zim_file_path: str,
        partial_query: str,
        limit: int = 10,
    ) -> str:
        """Get search suggestions (async).

        Args:
            zim_file_path: Path to the ZIM file
            partial_query: Partial search query
            limit: Maximum suggestions

        Returns:
            Suggestions as JSON string
        """
        return await asyncio.to_thread(
            self._ops.get_search_suggestions, zim_file_path, partial_query, limit
        )

    async def get_search_suggestions_data(
        self,
        zim_file_path: str,
        partial_query: str,
        limit: int = 10,
    ) -> dict:
        """Structured variant of ``get_search_suggestions`` (async)."""
        return await asyncio.to_thread(
            self._ops.get_search_suggestions_data,
            zim_file_path,
            partial_query,
            limit,
        )

    async def get_article_structure(
        self,
        zim_file_path: str,
        entry_path: str,
    ) -> str:
        """Get article structure (async).

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Path to the entry

        Returns:
            Article structure as JSON string
        """
        return await asyncio.to_thread(
            self._ops.get_article_structure, zim_file_path, entry_path
        )

    async def extract_article_links(
        self,
        zim_file_path: str,
        entry_path: str,
    ) -> str:
        """Extract links from an article (async).

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Path to the entry

        Returns:
            Links as JSON string
        """
        return await asyncio.to_thread(
            self._ops.extract_article_links, zim_file_path, entry_path
        )

    async def get_entry_summary(
        self,
        zim_file_path: str,
        entry_path: str,
        max_words: int = 200,
    ) -> str:
        """Get entry summary (async).

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Path to the entry
            max_words: Maximum words in summary

        Returns:
            Summary text
        """
        return await asyncio.to_thread(
            self._ops.get_entry_summary, zim_file_path, entry_path, max_words
        )

    async def get_table_of_contents(
        self,
        zim_file_path: str,
        entry_path: str,
    ) -> str:
        """Get table of contents (async).

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Path to the entry

        Returns:
            Table of contents as JSON string
        """
        return await asyncio.to_thread(
            self._ops.get_table_of_contents, zim_file_path, entry_path
        )

    async def get_binary_entry(
        self,
        zim_file_path: str,
        entry_path: str,
        max_size_bytes: Optional[int] = None,
        include_data: bool = True,
    ) -> str:
        """Get binary entry content (async).

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Path to the entry
            max_size_bytes: Maximum size to retrieve
            include_data: Whether to include base64 data

        Returns:
            Binary entry as JSON string
        """
        return await asyncio.to_thread(
            self._ops.get_binary_entry,
            zim_file_path,
            entry_path,
            max_size_bytes,
            include_data,
        )

    async def walk_namespace(
        self,
        zim_file_path: str,
        namespace: str,
        cursor: int = 0,
        limit: int = 200,
    ) -> str:
        """Walk all entries in a namespace by ID (async)."""
        return await asyncio.to_thread(
            self._ops.walk_namespace, zim_file_path, namespace, cursor, limit
        )

    async def walk_namespace_data(
        self,
        zim_file_path: str,
        namespace: str,
        cursor: int = 0,
        limit: int = 200,
    ) -> dict:
        """Structured variant of ``walk_namespace`` (async)."""
        return await asyncio.to_thread(
            self._ops.walk_namespace_data,
            zim_file_path,
            namespace,
            cursor,
            limit,
        )

    async def search_all(self, query: str, limit_per_file: int = 5) -> str:
        """Search across every ZIM file in allowed dirs (async)."""
        return await asyncio.to_thread(self._ops.search_all, query, limit_per_file)

    async def search_all_data(self, query: str, limit_per_file: int = 5) -> dict:
        """Structured variant of ``search_all`` (async)."""
        return await asyncio.to_thread(self._ops.search_all_data, query, limit_per_file)

    async def find_entry_by_title(
        self,
        zim_file_path: str,
        title: str,
        cross_file: bool = False,
        limit: int = 10,
    ) -> str:
        """Resolve title to entry path(s) (async)."""
        return await asyncio.to_thread(
            self._ops.find_entry_by_title,
            zim_file_path,
            title,
            cross_file,
            limit,
        )

    async def find_entry_by_title_data(
        self,
        zim_file_path: str,
        title: str,
        cross_file: bool = False,
        limit: int = 10,
    ) -> dict:
        """Structured variant of ``find_entry_by_title`` (async)."""
        return await asyncio.to_thread(
            self._ops.find_entry_by_title_data,
            zim_file_path,
            title,
            cross_file,
            limit,
        )

    async def get_related_articles(
        self,
        zim_file_path: str,
        entry_path: str,
        limit: int = 10,
    ) -> str:
        """Get related articles via outbound link graph (async)."""
        return await asyncio.to_thread(
            self._ops.get_related_articles,
            zim_file_path,
            entry_path,
            limit,
        )
