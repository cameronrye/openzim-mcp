"""
Type definitions for OpenZIM MCP server.

This module provides TypedDict definitions for structured data returned by
the server's operations, improving type safety and IDE support.
"""

from typing import List, Optional

from typing_extensions import NotRequired, TypedDict

# =============================================================================
# ZIM File Listing Types
# =============================================================================


class ZimFileInfo(TypedDict):
    """Information about a ZIM file in the allowed directories."""

    name: str
    path: str
    directory: str
    size: str
    size_bytes: int
    modified: str


# =============================================================================
# Search Types
# =============================================================================


class SearchResultEntry(TypedDict):
    """A single search result entry."""

    title: str
    path: str
    score: NotRequired[float]
    snippet: NotRequired[str]


class SearchResponse(TypedDict):
    """Response from search operations."""

    query: str
    results: List[SearchResultEntry]
    total_results: int
    has_more: bool
    next_cursor: NotRequired[str]


# =============================================================================
# Namespace Types
# =============================================================================


class NamespaceEntry(TypedDict):
    """An entry within a namespace."""

    path: str
    title: str
    mime_type: NotRequired[str]


class NamespaceInfo(TypedDict):
    """Information about a namespace and its contents."""

    namespace: str
    entry_count: int
    entries: List[NamespaceEntry]
    has_more: bool
    offset: int
    limit: int


class NamespaceListEntry(TypedDict):
    """A namespace entry in the namespace list."""

    namespace: str
    count: int
    description: NotRequired[str]


# =============================================================================
# Instance Tracking and Conflict Types
# =============================================================================


class ServerInstanceInfo(TypedDict):
    """Information about a server instance."""

    pid: int
    start_time: str
    config_hash: str
    server_name: str
    allowed_directories: List[str]


class ConflictInfo(TypedDict):
    """Information about a detected server conflict."""

    type: str  # "multiple_instances" or "configuration_mismatch"
    instance: ServerInstanceInfo
    severity: str  # "warning" or "high"
    details: NotRequired[str]


class InstanceTrackingInfo(TypedDict):
    """Instance tracking statistics."""

    enabled: bool
    active_instances: int
    conflicts_detected: int
    stale_instances: int


# =============================================================================
# Health Check Types
# =============================================================================


class UptimeInfo(TypedDict):
    """Process uptime information."""

    process_id: int
    started_at: str


class ConfigurationInfo(TypedDict):
    """Server configuration summary for health check."""

    allowed_directories: int
    cache_enabled: bool
    config_hash: str


class HealthChecksInfo(TypedDict):
    """Directory and file health check results."""

    directories_accessible: int
    zim_files_found: int
    permissions_ok: bool


class CacheStats(TypedDict):
    """Cache performance statistics."""

    hits: int
    misses: int
    size: int
    max_size: int
    hit_rate: float


class HealthCheckResponse(TypedDict):
    """Full health check response."""

    timestamp: str
    status: str  # "healthy", "warning", or "unhealthy"
    server_name: str
    uptime_info: UptimeInfo
    configuration: ConfigurationInfo
    cache_performance: CacheStats
    instance_tracking: InstanceTrackingInfo
    health_checks: HealthChecksInfo
    recommendations: List[str]
    warnings: List[str]


# =============================================================================
# Binary Entry Types
# =============================================================================


class BinaryEntryResponse(TypedDict):
    """Response from binary entry retrieval."""

    path: str
    title: str
    mime_type: str
    size: int
    size_human: str
    encoding: Optional[str]  # "base64" or None
    data: Optional[str]  # Base64-encoded data or None
    truncated: bool
    message: NotRequired[str]


# =============================================================================
# Article Structure Types
# =============================================================================


class HeadingInfo(TypedDict):
    """Information about a heading in an article."""

    level: int
    text: str
    id: str


class SectionInfo(TypedDict):
    """Information about a section in an article."""

    title: str
    content_preview: str


class ArticleMetadata(TypedDict):
    """Metadata extracted from an article."""

    categories: NotRequired[List[str]]
    infobox: NotRequired[dict]
    references_count: NotRequired[int]


class ArticleStructure(TypedDict):
    """Structure of an article."""

    title: str
    path: str
    content_type: str
    headings: List[HeadingInfo]
    sections: List[SectionInfo]
    metadata: ArticleMetadata
    word_count: int
    character_count: int


# =============================================================================
# Link Extraction Types
# =============================================================================


class LinkInfo(TypedDict):
    """Information about a link."""

    href: str
    text: str
    title: NotRequired[str]


class LinksData(TypedDict):
    """Links extracted from an article."""

    title: str
    path: str
    internal_links: List[LinkInfo]
    external_links: List[LinkInfo]
    total_internal: int
    total_external: int


# =============================================================================
# Summary Types
# =============================================================================


class SummaryData(TypedDict):
    """Summary of an article."""

    title: str
    path: str
    content_type: str
    summary: str
    word_count: int
    is_truncated: bool


# =============================================================================
# Table of Contents Types
# =============================================================================


class TOCEntry(TypedDict):
    """A table of contents entry with nested children."""

    level: int
    text: str
    id: str
    children: List["TOCEntry"]


class TOCData(TypedDict):
    """Table of contents data."""

    title: str
    path: str
    content_type: str
    toc: List[TOCEntry]
    heading_count: int
    max_depth: int
    message: NotRequired[str]


# =============================================================================
# Diagnostics Types
# =============================================================================


class EnvironmentCheck(TypedDict):
    """Result of an environment check."""

    name: str
    status: str  # "ok", "warning", "error"
    message: str


class DiagnosticsResponse(TypedDict):
    """Full diagnostics response."""

    timestamp: str
    server_info: dict
    conflicts: List[ConflictInfo]
    environment_checks: List[EnvironmentCheck]
    recommendations: List[str]


# =============================================================================
# Conflict Resolution Types
# =============================================================================


class CleanupResults(TypedDict):
    """Results of conflict cleanup operations."""

    stale_instances_cleaned: int
    active_instances_remaining: int
    current_instance_registered: bool


class ConflictResolutionResponse(TypedDict):
    """Response from conflict resolution."""

    timestamp: str
    action: str
    conflicts_found: List[ConflictInfo]
    cleanup_results: CleanupResults
    status: str
    recommendations: List[str]
