"""
Async wrappers for ZIM operations.

This module provides async versions of ZimOperations methods by wrapping
the synchronous operations with asyncio.to_thread() to prevent blocking
the event loop during I/O-bound operations.
"""

import asyncio
import logging
from functools import partial
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

from .meta import attach_meta
from .zim_operations import ZimOperations

if TYPE_CHECKING:
    from .responses import ToolErrorPayload
    from .server import OpenZimMcpServer
    from .tool_schemas import (
        ArchiveMetadataResponse,
        ArchiveValidationResponse,
        ArticleStructureResponse,
        BatchEntryResponse,
        BinaryEntryResponse,
        BrowseNamespaceResponse,
        EntryResponse,
        EntrySummaryResponse,
        FindEntryResponse,
        GetSectionResponse,
        LinksResponse,
        RelatedArticlesResponse,
        SearchAllResponse,
        SearchResponse,
        SearchSuggestionsResponse,
        SearchWithFiltersResponse,
        ServerHealthResponse,
        TableOfContentsResponse,
        WalkNamespaceResponse,
    )

logger = logging.getLogger(__name__)


class AsyncZimOperations:
    """Async wrapper for ZimOperations.

    Provides async versions of the ZimOperations ``*_data`` methods the
    tools call, running the underlying sync operations in a thread pool
    to prevent blocking the event loop.
    """

    def __init__(self, zim_operations: ZimOperations):
        """Initialize async operations wrapper.

        Args:
            zim_operations: Underlying synchronous ZimOperations instance
        """
        self._ops = zim_operations
        logger.debug("AsyncZimOperations initialized")

    async def search_zim_file_data(
        self,
        zim_file_path: str,
        query: str,
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        cursor_archive_identity: Optional[str] = None,
    ) -> "SearchResponse":
        """Structured variant of ``search_zim_file`` (async)."""
        return await asyncio.to_thread(
            partial(
                self._ops.search_zim_file_data,
                zim_file_path,
                query,
                limit,
                offset,
                cursor_archive_identity=cursor_archive_identity,
            ),
        )

    async def get_zim_entry_data(
        self,
        zim_file_path: str,
        entry_path: str,
        max_content_length: Optional[int] = None,
        content_offset: int = 0,
        *,
        compact: bool = False,
    ) -> "EntryResponse":
        """Structured variant of ``get_zim_entry`` (async).

        Op2: forwards ``compact`` so the advanced tool surface can opt
        into the same compact-mode rendering simple-mode uses.
        """
        return await asyncio.to_thread(
            lambda: self._ops.get_zim_entry_data(
                zim_file_path,
                entry_path,
                max_content_length,
                content_offset,
                compact=compact,
            )
        )

    async def get_entries_data(
        self,
        entries: List[Dict[str, str]],
        max_content_length: Optional[int] = None,
        *,
        compact: bool = False,
    ) -> "BatchEntryResponse":
        """Structured variant of ``get_entries`` (async)."""
        return await asyncio.to_thread(
            lambda: self._ops.get_entries_data(
                entries, max_content_length, compact=compact
            )
        )

    async def get_main_page_data(
        self,
        zim_file_path: str,
        *,
        compact: bool = False,
        max_content_length: Optional[int] = None,
    ) -> "EntryResponse":
        """Structured variant of ``get_main_page`` (async)."""
        return await asyncio.to_thread(
            self._ops.get_main_page_data,
            zim_file_path,
            compact=compact,
            max_content_length=max_content_length,
        )

    async def browse_namespace_data(
        self,
        zim_file_path: str,
        namespace: str = "C",
        limit: int = 50,
        offset: int = 0,
        *,
        cursor_archive_identity: Optional[str] = None,
        include_assets: bool = False,
    ) -> "BrowseNamespaceResponse":
        """Structured variant of ``browse_namespace`` (async)."""
        return await asyncio.to_thread(
            partial(
                self._ops.browse_namespace_data,
                zim_file_path,
                namespace,
                limit,
                offset,
                cursor_archive_identity=cursor_archive_identity,
                include_assets=include_assets,
            ),
        )

    async def search_with_filters_data(
        self,
        zim_file_path: str,
        query: str,
        namespace: Optional[str] = None,
        content_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        cursor_archive_identity: Optional[str] = None,
    ) -> "SearchWithFiltersResponse":
        """Structured variant of ``search_with_filters`` (async)."""
        return await asyncio.to_thread(
            partial(
                self._ops.search_with_filters_data,
                zim_file_path,
                query,
                namespace,
                content_type,
                limit,
                offset,
                cursor_archive_identity=cursor_archive_identity,
            ),
        )

    async def get_search_suggestions_data(
        self,
        zim_file_path: str,
        partial_query: str,
        limit: int = 10,
    ) -> "SearchSuggestionsResponse":
        """Structured variant of ``get_search_suggestions`` (async)."""
        return await asyncio.to_thread(
            self._ops.get_search_suggestions_data,
            zim_file_path,
            partial_query,
            limit,
        )

    async def get_article_structure_data(
        self,
        zim_file_path: str,
        entry_path: str,
    ) -> "ArticleStructureResponse":
        """Structured variant of ``get_article_structure`` (async)."""
        return await asyncio.to_thread(
            self._ops.get_article_structure_data, zim_file_path, entry_path
        )

    async def extract_article_links_data(
        self,
        zim_file_path: str,
        entry_path: str,
        limit: int = 100,
        offset: int = 0,
        kind: str = "internal",
        *,
        cursor_archive_identity: Optional[str] = None,
    ) -> "LinksResponse":
        """Structured variant of ``extract_article_links`` (async, paginated)."""
        return await asyncio.to_thread(
            self._ops.extract_article_links_data,
            zim_file_path,
            entry_path,
            limit,
            offset,
            kind,
            cursor_archive_identity=cursor_archive_identity,
        )

    async def get_entry_summary_data(
        self,
        zim_file_path: str,
        entry_path: str,
        max_words: int = 200,
        *,
        compact: bool = False,
    ) -> "EntrySummaryResponse":
        """Structured variant of ``get_entry_summary`` (async)."""
        return await asyncio.to_thread(
            lambda: self._ops.get_entry_summary_data(
                zim_file_path, entry_path, max_words, compact=compact
            )
        )

    async def get_table_of_contents_data(
        self,
        zim_file_path: str,
        entry_path: str,
    ) -> "TableOfContentsResponse":
        """Structured variant of ``get_table_of_contents`` (async)."""
        return await asyncio.to_thread(
            self._ops.get_table_of_contents_data, zim_file_path, entry_path
        )

    async def get_binary_entry_data(
        self,
        zim_file_path: str,
        entry_path: str,
        max_size_bytes: Optional[int] = None,
        include_data: bool = True,
    ) -> "BinaryEntryResponse":
        """Structured variant of ``get_binary_entry`` (async)."""
        return await asyncio.to_thread(
            self._ops.get_binary_entry_data,
            zim_file_path,
            entry_path,
            max_size_bytes,
            include_data,
        )

    async def walk_namespace_data(
        self,
        zim_file_path: str,
        namespace: str,
        cursor_state: Optional[Dict[str, Any]] = None,
        limit: int = 200,
        *,
        include_assets: bool = False,
    ) -> "WalkNamespaceResponse":
        """Structured variant of ``walk_namespace`` (async)."""
        return await asyncio.to_thread(
            partial(
                self._ops.walk_namespace_data,
                zim_file_path,
                namespace,
                cursor_state,
                limit,
                include_assets=include_assets,
            ),
        )

    async def search_all_data(
        self, query: str, limit_per_file: int = 5
    ) -> "SearchAllResponse":
        """Structured variant of ``search_all`` (async)."""
        return await asyncio.to_thread(self._ops.search_all_data, query, limit_per_file)

    async def find_entry_by_title_data(
        self,
        zim_file_path: str,
        title: str,
        cross_file: bool = False,
        limit: int = 10,
    ) -> "FindEntryResponse":
        """Structured variant of ``find_entry_by_title`` (async)."""
        return await asyncio.to_thread(
            self._ops.find_entry_by_title_data,
            zim_file_path,
            title,
            cross_file,
            limit,
        )

    async def get_related_articles_data(
        self,
        zim_file_path: str,
        entry_path: str,
        limit: int = 10,
    ) -> "RelatedArticlesResponse":
        """Structured variant of ``get_related_articles`` (async)."""
        return await asyncio.to_thread(
            self._ops.get_related_articles_data,
            zim_file_path,
            entry_path,
            limit,
        )

    async def get_inbound_links_data(
        self,
        zim_file_path: str,
        entry_path: str,
        limit: int = 10,
        offset: int = 0,
        *,
        cursor_archive_identity: Optional[str] = None,
    ) -> "RelatedArticlesResponse":
        """Structured variant of inbound link lookup (async)."""
        return await asyncio.to_thread(
            self._ops.get_inbound_links_data,
            zim_file_path,
            entry_path,
            limit,
            offset,
            cursor_archive_identity=cursor_archive_identity,
        )

    async def get_section_data(
        self,
        zim_file_path: str,
        entry_path: str,
        section_id: str,
        max_chars: Optional[int] = None,
        *,
        include_subsections: bool = True,
        compact: bool = True,
    ) -> "Union[GetSectionResponse, ToolErrorPayload]":
        """Structured variant of ``get_section`` (async)."""
        return await asyncio.to_thread(
            self._ops.get_section_data,
            zim_file_path,
            entry_path,
            section_id,
            max_chars=max_chars,
            include_subsections=include_subsections,
            compact=compact,
        )

    # -----------------------------------------------------------------
    # Phase F combined wrappers (Task D2)
    #
    # Each combined wrapper composes existing single-purpose data calls
    # into the new combined response shape from tool_schemas.py
    # (ArchiveMetadataResponse, ServerHealthResponse). The Phase F tools
    # zim_metadata and zim_health register thin async functions that
    # delegate here; the composition logic lives in one place so the
    # legacy single-purpose tools and the combined Phase F tools can't
    # drift.
    # -----------------------------------------------------------------

    async def get_archive_metadata_data(
        self, zim_file_path: str
    ) -> "ArchiveMetadataResponse":
        """Build the combined ``zim_metadata`` response.

        M-namespace fields plus list-form namespaces. Async-safe; defers
        both source calls to a thread pool concurrently because they touch
        different archive slices and run independently.
        """
        metadata_resp, namespaces_resp = await asyncio.gather(
            asyncio.to_thread(self._ops.get_zim_metadata_data, zim_file_path),
            asyncio.to_thread(self._ops.list_namespaces_data, zim_file_path),
        )
        # The legacy list_namespaces_data returns a dict keyed by namespace
        # letter; the Phase F combined response wants a list with the letter
        # carried as an explicit field so small models can iterate naturally.
        ns_dict = namespaces_resp.get("namespaces", {})
        namespaces_list: List[Dict[str, Any]] = []
        for letter, summary in ns_dict.items():
            entry: Dict[str, Any] = {"letter": letter}
            entry.update(summary)
            namespaces_list.append(entry)
        # M-namespace fields are surfaced as a flat str→str map. The legacy
        # ZimMetadataResponse.metadata_entries is dict[str, Any]; in practice
        # libzim only emits str values for the M-namespace, so the cast is
        # a tightening, not a lossy projection.
        metadata_entries = metadata_resp.get("metadata_entries", {}) or {}
        flat_metadata: Dict[str, str] = {k: str(v) for k, v in metadata_entries.items()}
        # Surface the native identity + index-capability fields (and the
        # parsed Counter breakdown) carried on the ZimMetadataResponse. They
        # are grouped into nested objects so small models can read them as a
        # unit rather than null-checking a handful of flat keys.
        result: Dict[str, Any] = {
            "metadata": flat_metadata,
            "namespaces": namespaces_list,
            "archive_identity": {
                "uuid": metadata_resp.get("uuid"),
                "is_multipart": metadata_resp.get("is_multipart"),
            },
            "index_capabilities": {
                "has_fulltext_index": metadata_resp.get("has_fulltext_index"),
                "has_title_index": metadata_resp.get("has_title_index"),
            },
        }
        counter_breakdown = metadata_resp.get("counter_breakdown")
        if counter_breakdown:
            result["counter_breakdown"] = counter_breakdown
        # The archive-type annotations are computed by the source metadata
        # call and ride its envelope; carry them onto the combined one so
        # they stay reachable on the Phase F surface.
        source_meta: Dict[str, Any] = dict(metadata_resp.get("_meta", {}) or {})
        attach_meta(
            result,
            detected_type=source_meta.get("detected_type"),
            detection_confidence=source_meta.get("detection_confidence"),
        )
        return cast("ArchiveMetadataResponse", result)

    async def get_archive_validation_data(
        self, zim_file_path: str
    ) -> "ArchiveValidationResponse":
        """Per-archive validation (``zim_health(zim_file_path=...)``).

        The checksum / index / identity reads run in a worker thread; the
        ``Archive.check()`` integrity scan itself is delegated to a separate
        process (``zim.archive.check_archive_integrity``) because the libzim
        binding holds the GIL for the whole pass, so a thread alone could not
        keep the event loop responsive.
        """
        return await asyncio.to_thread(
            self._ops.get_archive_validation_data, zim_file_path
        )

    async def get_health_data(
        self, server: "OpenZimMcpServer"
    ) -> "ServerHealthResponse":
        """Build the combined ``zim_health`` response.

        Health + configuration + loaded_archives in one envelope.

        The health and configuration builders live in
        ``tools/server_tools`` (the legacy registration site) so this
        wrapper imports them lazily to avoid a circular dependency.
        The legacy single-purpose ``get_server_health`` /
        ``get_server_configuration`` tools call the same builders, so
        the combined response stays in lockstep with the per-tool
        responses by construction.
        """
        # The builders live in openzim_mcp.server_state — extracted there
        # in Task D12 when the legacy tools/server_tools.py was deleted.
        # Lazy import keeps server_state out of the module-level import
        # graph (server_state itself imports tool_schemas, which routes
        # back through async_operations during type-checking).
        from .server_state import (
            _build_configuration_report,
            _build_health_report,
        )

        health, configuration, loaded_archives = await asyncio.gather(
            asyncio.to_thread(_build_health_report, server),
            asyncio.to_thread(_build_configuration_report, server),
            asyncio.to_thread(self._ops.list_zim_files_data, None),
        )
        result: Dict[str, Any] = {
            "health": health,
            "configuration": configuration,
            "loaded_archives": loaded_archives,
        }
        attach_meta(result)
        return cast("ServerHealthResponse", result)
