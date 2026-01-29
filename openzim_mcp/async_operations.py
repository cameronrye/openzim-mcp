"""
Async wrappers for ZIM operations.

This module provides async versions of ZimOperations methods by wrapping
the synchronous operations with asyncio.to_thread() to prevent blocking
the event loop during I/O-bound operations.
"""

import asyncio
import logging
from typing import Optional

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

    async def list_zim_files(self) -> str:
        """List all ZIM files in allowed directories (async).

        Returns:
            JSON string containing the list of ZIM files
        """
        return await asyncio.to_thread(self._ops.list_zim_files)

    async def list_zim_files_data(self) -> list:
        """List all ZIM files as structured data (async).

        Returns:
            List of dictionaries containing ZIM file information
        """
        return await asyncio.to_thread(self._ops.list_zim_files_data)

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
    ) -> str:
        """Get an entry from a ZIM file (async).

        Args:
            zim_file_path: Path to the ZIM file
            entry_path: Path to the entry within the ZIM file
            max_content_length: Maximum content length to return

        Returns:
            Entry content as text
        """
        return await asyncio.to_thread(
            self._ops.get_zim_entry, zim_file_path, entry_path, max_content_length
        )

    async def get_zim_metadata(self, zim_file_path: str) -> str:
        """Get metadata for a ZIM file (async).

        Args:
            zim_file_path: Path to the ZIM file

        Returns:
            Metadata as JSON string
        """
        return await asyncio.to_thread(self._ops.get_zim_metadata, zim_file_path)

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
