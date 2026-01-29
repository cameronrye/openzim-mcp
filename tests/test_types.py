"""
Tests for types module.

This module tests the TypedDict definitions to ensure they:
1. Can be properly instantiated with correct fields
2. Have required vs optional fields correctly defined
3. Support proper type checking usage patterns
"""

from typing import get_type_hints

from openzim_mcp.types import (
    ArticleMetadata,
    ArticleStructure,
    BinaryEntryResponse,
    CacheStats,
    CleanupResults,
    ConfigurationInfo,
    ConflictInfo,
    ConflictResolutionResponse,
    DiagnosticsResponse,
    EnvironmentCheck,
    HeadingInfo,
    HealthCheckResponse,
    HealthChecksInfo,
    InstanceTrackingInfo,
    LinkInfo,
    LinksData,
    NamespaceEntry,
    NamespaceInfo,
    NamespaceListEntry,
    SearchResponse,
    SearchResultEntry,
    SectionInfo,
    ServerInstanceInfo,
    SummaryData,
    TOCData,
    TOCEntry,
    UptimeInfo,
    ZimFileInfo,
)


class TestZimFileInfo:
    """Test ZimFileInfo TypedDict."""

    def test_create_zim_file_info(self):
        """Test creating a valid ZimFileInfo."""
        info: ZimFileInfo = {
            "name": "wikipedia.zim",
            "path": "/data/wikipedia.zim",
            "directory": "/data",
            "size": "2.5 GB",
            "size_bytes": 2684354560,
            "modified": "2024-01-15T10:30:00",
        }

        assert info["name"] == "wikipedia.zim"
        assert info["path"] == "/data/wikipedia.zim"
        assert info["directory"] == "/data"
        assert info["size"] == "2.5 GB"
        assert info["size_bytes"] == 2684354560
        assert info["modified"] == "2024-01-15T10:30:00"

    def test_zim_file_info_has_correct_fields(self):
        """Test that ZimFileInfo has all required fields."""
        hints = get_type_hints(ZimFileInfo)

        assert "name" in hints
        assert "path" in hints
        assert "directory" in hints
        assert "size" in hints
        assert "size_bytes" in hints
        assert "modified" in hints


class TestSearchTypes:
    """Test search-related TypedDicts."""

    def test_create_search_result_entry(self):
        """Test creating a valid SearchResultEntry."""
        entry: SearchResultEntry = {
            "title": "Python Programming",
            "path": "C/Python_(programming_language)",
        }
        assert entry["title"] == "Python Programming"
        assert entry["path"] == "C/Python_(programming_language)"

    def test_search_result_entry_with_optional_fields(self):
        """Test SearchResultEntry with optional fields."""
        entry: SearchResultEntry = {
            "title": "Python",
            "path": "C/Python",
            "score": 0.95,
            "snippet": "Python is a high-level programming language...",
        }
        assert entry["score"] == 0.95
        assert "programming language" in entry["snippet"]

    def test_create_search_response(self):
        """Test creating a valid SearchResponse."""
        response: SearchResponse = {
            "query": "python",
            "results": [
                {"title": "Python", "path": "C/Python"},
                {"title": "Monty Python", "path": "C/Monty_Python"},
            ],
            "total_results": 100,
            "has_more": True,
        }

        assert response["query"] == "python"
        assert len(response["results"]) == 2
        assert response["total_results"] == 100
        assert response["has_more"] is True

    def test_search_response_with_cursor(self):
        """Test SearchResponse with optional next_cursor."""
        response: SearchResponse = {
            "query": "test",
            "results": [],
            "total_results": 0,
            "has_more": False,
            "next_cursor": "abc123",
        }
        assert response["next_cursor"] == "abc123"


class TestNamespaceTypes:
    """Test namespace-related TypedDicts."""

    def test_create_namespace_entry(self):
        """Test creating a valid NamespaceEntry."""
        entry: NamespaceEntry = {
            "path": "C/Article_Name",
            "title": "Article Name",
        }
        assert entry["path"] == "C/Article_Name"
        assert entry["title"] == "Article Name"

    def test_namespace_entry_with_mime_type(self):
        """Test NamespaceEntry with optional mime_type."""
        entry: NamespaceEntry = {
            "path": "I/image.png",
            "title": "Image",
            "mime_type": "image/png",
        }
        assert entry["mime_type"] == "image/png"

    def test_create_namespace_info(self):
        """Test creating a valid NamespaceInfo."""
        info: NamespaceInfo = {
            "namespace": "C",
            "entry_count": 1000,
            "entries": [{"path": "C/Test", "title": "Test"}],
            "has_more": True,
            "offset": 0,
            "limit": 50,
        }

        assert info["namespace"] == "C"
        assert info["entry_count"] == 1000
        assert len(info["entries"]) == 1
        assert info["has_more"] is True

    def test_create_namespace_list_entry(self):
        """Test creating a valid NamespaceListEntry."""
        entry: NamespaceListEntry = {
            "namespace": "C",
            "count": 5000,
        }
        assert entry["namespace"] == "C"
        assert entry["count"] == 5000

    def test_namespace_list_entry_with_description(self):
        """Test NamespaceListEntry with optional description."""
        entry: NamespaceListEntry = {
            "namespace": "C",
            "count": 5000,
            "description": "Article content",
        }
        assert entry["description"] == "Article content"


class TestInstanceTrackingTypes:
    """Test instance tracking and conflict TypedDicts."""

    def test_create_server_instance_info(self):
        """Test creating a valid ServerInstanceInfo."""
        info: ServerInstanceInfo = {
            "pid": 12345,
            "start_time": "2024-01-15T10:00:00",
            "config_hash": "abc123def456",
            "server_name": "openzim-mcp",
            "allowed_directories": ["/data/zim"],
        }

        assert info["pid"] == 12345
        assert info["config_hash"] == "abc123def456"
        assert len(info["allowed_directories"]) == 1

    def test_create_conflict_info(self):
        """Test creating a valid ConflictInfo."""
        conflict: ConflictInfo = {
            "type": "configuration_mismatch",
            "instance": {
                "pid": 67890,
                "start_time": "2024-01-15T09:00:00",
                "config_hash": "xyz789",
                "server_name": "openzim-mcp",
                "allowed_directories": ["/other/path"],
            },
            "severity": "high",
        }

        assert conflict["type"] == "configuration_mismatch"
        assert conflict["severity"] == "high"
        assert conflict["instance"]["pid"] == 67890

    def test_conflict_info_with_details(self):
        """Test ConflictInfo with optional details."""
        conflict: ConflictInfo = {
            "type": "multiple_instances",
            "instance": {
                "pid": 111,
                "start_time": "2024-01-15T09:00:00",
                "config_hash": "hash",
                "server_name": "test",
                "allowed_directories": [],
            },
            "severity": "warning",
            "details": "Additional info about the conflict",
        }
        assert conflict["details"] == "Additional info about the conflict"

    def test_create_instance_tracking_info(self):
        """Test creating a valid InstanceTrackingInfo."""
        info: InstanceTrackingInfo = {
            "enabled": True,
            "active_instances": 2,
            "conflicts_detected": 1,
            "stale_instances": 0,
        }

        assert info["enabled"] is True
        assert info["active_instances"] == 2
        assert info["conflicts_detected"] == 1


class TestHealthCheckTypes:
    """Test health check-related TypedDicts."""

    def test_create_uptime_info(self):
        """Test creating a valid UptimeInfo."""
        info: UptimeInfo = {
            "process_id": 12345,
            "started_at": "2024-01-15T10:00:00Z",
        }

        assert info["process_id"] == 12345
        assert info["started_at"] == "2024-01-15T10:00:00Z"

    def test_create_configuration_info(self):
        """Test creating a valid ConfigurationInfo."""
        info: ConfigurationInfo = {
            "allowed_directories": 3,
            "cache_enabled": True,
            "config_hash": "hash123",
        }

        assert info["allowed_directories"] == 3
        assert info["cache_enabled"] is True

    def test_create_health_checks_info(self):
        """Test creating a valid HealthChecksInfo."""
        info: HealthChecksInfo = {
            "directories_accessible": 2,
            "zim_files_found": 5,
            "permissions_ok": True,
        }

        assert info["directories_accessible"] == 2
        assert info["zim_files_found"] == 5

    def test_create_cache_stats(self):
        """Test creating a valid CacheStats."""
        stats: CacheStats = {
            "hits": 100,
            "misses": 25,
            "size": 50,
            "max_size": 100,
            "hit_rate": 0.8,
        }

        assert stats["hits"] == 100
        assert stats["misses"] == 25
        assert stats["hit_rate"] == 0.8

    def test_create_health_check_response(self):
        """Test creating a valid HealthCheckResponse."""
        response: HealthCheckResponse = {
            "timestamp": "2024-01-15T10:30:00Z",
            "status": "healthy",
            "server_name": "openzim-mcp",
            "uptime_info": {"process_id": 123, "started_at": "2024-01-15T10:00:00Z"},
            "configuration": {
                "allowed_directories": 2,
                "cache_enabled": True,
                "config_hash": "hash",
            },
            "cache_performance": {
                "hits": 50,
                "misses": 10,
                "size": 30,
                "max_size": 100,
                "hit_rate": 0.83,
            },
            "instance_tracking": {
                "enabled": True,
                "active_instances": 1,
                "conflicts_detected": 0,
                "stale_instances": 0,
            },
            "health_checks": {
                "directories_accessible": 2,
                "zim_files_found": 3,
                "permissions_ok": True,
            },
            "recommendations": [],
            "warnings": [],
        }

        assert response["status"] == "healthy"
        assert response["server_name"] == "openzim-mcp"


class TestBinaryEntryTypes:
    """Test binary entry TypedDicts."""

    def test_create_binary_entry_response(self):
        """Test creating a valid BinaryEntryResponse."""
        response: BinaryEntryResponse = {
            "path": "I/image.png",
            "title": "Sample Image",
            "mime_type": "image/png",
            "size": 1024,
            "size_human": "1 KB",
            "encoding": "base64",
            "data": "iVBORw0KGgoAAAANSUhEUg...",
            "truncated": False,
        }

        assert response["path"] == "I/image.png"
        assert response["mime_type"] == "image/png"
        assert response["encoding"] == "base64"
        assert response["truncated"] is False

    def test_binary_entry_response_without_data(self):
        """Test BinaryEntryResponse without data (metadata only)."""
        response: BinaryEntryResponse = {
            "path": "I/large_video.mp4",
            "title": "Large Video",
            "mime_type": "video/mp4",
            "size": 100000000,
            "size_human": "100 MB",
            "encoding": None,
            "data": None,
            "truncated": True,
            "message": "Content exceeds size limit",
        }

        assert response["encoding"] is None
        assert response["data"] is None
        assert response["truncated"] is True


class TestArticleStructureTypes:
    """Test article structure TypedDicts."""

    def test_create_heading_info(self):
        """Test creating a valid HeadingInfo."""
        heading: HeadingInfo = {
            "level": 2,
            "text": "Introduction",
            "id": "introduction",
        }

        assert heading["level"] == 2
        assert heading["text"] == "Introduction"
        assert heading["id"] == "introduction"

    def test_create_section_info(self):
        """Test creating a valid SectionInfo."""
        section: SectionInfo = {
            "title": "History",
            "content_preview": "The history of Python begins in the late 1980s...",
        }

        assert section["title"] == "History"
        assert "Python" in section["content_preview"]

    def test_create_article_metadata(self):
        """Test creating a valid ArticleMetadata."""
        metadata: ArticleMetadata = {}  # All fields are optional
        assert metadata is not None

    def test_article_metadata_with_all_fields(self):
        """Test ArticleMetadata with all optional fields."""
        metadata: ArticleMetadata = {
            "categories": ["Programming", "Software"],
            "infobox": {"type": "programming_language", "designer": "Guido van Rossum"},
            "references_count": 150,
        }

        assert len(metadata["categories"]) == 2
        assert metadata["infobox"]["designer"] == "Guido van Rossum"
        assert metadata["references_count"] == 150

    def test_create_article_structure(self):
        """Test creating a valid ArticleStructure."""
        structure: ArticleStructure = {
            "title": "Python (programming language)",
            "path": "C/Python_(programming_language)",
            "content_type": "text/html",
            "headings": [{"level": 1, "text": "Python", "id": "python"}],
            "sections": [{"title": "Overview", "content_preview": "Python is..."}],
            "metadata": {},
            "word_count": 5000,
            "character_count": 30000,
        }

        assert structure["title"] == "Python (programming language)"
        assert len(structure["headings"]) == 1
        assert structure["word_count"] == 5000


class TestLinkTypes:
    """Test link extraction TypedDicts."""

    def test_create_link_info(self):
        """Test creating a valid LinkInfo."""
        link: LinkInfo = {
            "href": "C/Guido_van_Rossum",
            "text": "Guido van Rossum",
        }

        assert link["href"] == "C/Guido_van_Rossum"
        assert link["text"] == "Guido van Rossum"

    def test_link_info_with_title(self):
        """Test LinkInfo with optional title."""
        link: LinkInfo = {
            "href": "https://python.org",
            "text": "Official Website",
            "title": "Python official website",
        }
        assert link["title"] == "Python official website"

    def test_create_links_data(self):
        """Test creating a valid LinksData."""
        data: LinksData = {
            "title": "Python",
            "path": "C/Python",
            "internal_links": [{"href": "C/Guido", "text": "Guido"}],
            "external_links": [{"href": "https://python.org", "text": "Python.org"}],
            "total_internal": 50,
            "total_external": 10,
        }

        assert len(data["internal_links"]) == 1
        assert len(data["external_links"]) == 1
        assert data["total_internal"] == 50


class TestSummaryTypes:
    """Test summary TypedDicts."""

    def test_create_summary_data(self):
        """Test creating a valid SummaryData."""
        summary: SummaryData = {
            "title": "Python",
            "path": "C/Python",
            "content_type": "text/html",
            "summary": "Python is a high-level, general-purpose programming language.",
            "word_count": 50,
            "is_truncated": False,
        }

        assert summary["title"] == "Python"
        assert summary["word_count"] == 50
        assert summary["is_truncated"] is False


class TestTOCTypes:
    """Test table of contents TypedDicts."""

    def test_create_toc_entry(self):
        """Test creating a valid TOCEntry."""
        entry: TOCEntry = {
            "level": 1,
            "text": "Introduction",
            "id": "introduction",
            "children": [],
        }

        assert entry["level"] == 1
        assert entry["children"] == []

    def test_toc_entry_with_nested_children(self):
        """Test TOCEntry with nested children."""
        entry: TOCEntry = {
            "level": 1,
            "text": "History",
            "id": "history",
            "children": [
                {
                    "level": 2,
                    "text": "Early development",
                    "id": "early-development",
                    "children": [],
                },
                {
                    "level": 2,
                    "text": "Version 3",
                    "id": "version-3",
                    "children": [],
                },
            ],
        }

        assert len(entry["children"]) == 2
        assert entry["children"][0]["level"] == 2

    def test_create_toc_data(self):
        """Test creating a valid TOCData."""
        data: TOCData = {
            "title": "Python",
            "path": "C/Python",
            "content_type": "text/html",
            "toc": [],
            "heading_count": 0,
            "max_depth": 0,
        }

        assert data["heading_count"] == 0

    def test_toc_data_with_message(self):
        """Test TOCData with optional message."""
        data: TOCData = {
            "title": "Non-HTML Content",
            "path": "I/image.png",
            "content_type": "image/png",
            "toc": [],
            "heading_count": 0,
            "max_depth": 0,
            "message": "TOC not available for non-HTML content",
        }
        assert "not available" in data["message"]


class TestDiagnosticsTypes:
    """Test diagnostics TypedDicts."""

    def test_create_environment_check(self):
        """Test creating a valid EnvironmentCheck."""
        check: EnvironmentCheck = {
            "name": "Python version",
            "status": "ok",
            "message": "Python 3.12 detected",
        }

        assert check["name"] == "Python version"
        assert check["status"] == "ok"

    def test_environment_check_statuses(self):
        """Test different EnvironmentCheck statuses."""
        for status in ["ok", "warning", "error"]:
            check: EnvironmentCheck = {
                "name": "Test check",
                "status": status,
                "message": f"Status is {status}",
            }
            assert check["status"] == status

    def test_create_diagnostics_response(self):
        """Test creating a valid DiagnosticsResponse."""
        response: DiagnosticsResponse = {
            "timestamp": "2024-01-15T10:30:00Z",
            "server_info": {"version": "0.8.0", "name": "openzim-mcp"},
            "conflicts": [],
            "environment_checks": [
                {"name": "Check 1", "status": "ok", "message": "All good"}
            ],
            "recommendations": ["Consider increasing cache size"],
        }

        assert response["timestamp"] == "2024-01-15T10:30:00Z"
        assert len(response["conflicts"]) == 0
        assert len(response["recommendations"]) == 1


class TestConflictResolutionTypes:
    """Test conflict resolution TypedDicts."""

    def test_create_cleanup_results(self):
        """Test creating a valid CleanupResults."""
        results: CleanupResults = {
            "stale_instances_cleaned": 2,
            "active_instances_remaining": 1,
            "current_instance_registered": True,
        }

        assert results["stale_instances_cleaned"] == 2
        assert results["active_instances_remaining"] == 1
        assert results["current_instance_registered"] is True

    def test_create_conflict_resolution_response(self):
        """Test creating a valid ConflictResolutionResponse."""
        response: ConflictResolutionResponse = {
            "timestamp": "2024-01-15T10:30:00Z",
            "action": "cleanup",
            "conflicts_found": [],
            "cleanup_results": {
                "stale_instances_cleaned": 1,
                "active_instances_remaining": 1,
                "current_instance_registered": True,
            },
            "status": "resolved",
            "recommendations": [],
        }

        assert response["action"] == "cleanup"
        assert response["status"] == "resolved"
        assert response["cleanup_results"]["stale_instances_cleaned"] == 1


class TestTypeImports:
    """Test that all types can be imported from the module."""

    def test_all_types_importable(self):
        """Test that all documented types are importable."""
        # This test passes if we get here without import errors
        # The imports are done at the top of the file
        assert ZimFileInfo is not None
        assert SearchResultEntry is not None
        assert SearchResponse is not None
        assert NamespaceEntry is not None
        assert NamespaceInfo is not None
        assert NamespaceListEntry is not None
        assert ServerInstanceInfo is not None
        assert ConflictInfo is not None
        assert InstanceTrackingInfo is not None
        assert UptimeInfo is not None
        assert ConfigurationInfo is not None
        assert HealthChecksInfo is not None
        assert CacheStats is not None
        assert HealthCheckResponse is not None
        assert BinaryEntryResponse is not None
        assert HeadingInfo is not None
        assert SectionInfo is not None
        assert ArticleMetadata is not None
        assert ArticleStructure is not None
        assert LinkInfo is not None
        assert LinksData is not None
        assert SummaryData is not None
        assert TOCEntry is not None
        assert TOCData is not None
        assert EnvironmentCheck is not None
        assert DiagnosticsResponse is not None
        assert CleanupResults is not None
        assert ConflictResolutionResponse is not None
