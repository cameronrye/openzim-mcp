# API Reference

Complete documentation for all OpenZIM MCP tools and their parameters.

## Overview

OpenZIM MCP provides a comprehensive set of tools for accessing and searching ZIM format knowledge bases. All tools are designed to work seamlessly with LLMs and provide intelligent, structured access to offline content.

## Content Access Tools

### list_zim_files

Lists all ZIM files in allowed directories with metadata.

**Parameters**: None

**Returns**: JSON array of ZIM files with details

**Example**:

```json
{
  "name": "list_zim_files"
}
```

**Response**:

```json
[
  {
    "name": "wikipedia_en_100_2025-08.zim",
    "path": "/path/to/wikipedia_en_100_2025-08.zim",
    "directory": "/path/to/zim-files",
    "size": "310.77 MB",
    "modified": "2025-09-11T10:20:50.148427"
  }
]
```

### search_zim_file

Search within ZIM file content with basic parameters.

**Required Parameters**:

- `zim_file_path` (string): Path to the ZIM file
- `query` (string): Search query term

**Optional Parameters**:

- `limit` (integer, default: 10): Maximum number of results
- `offset` (integer, default: 0): Starting offset for pagination

**Example**:

```json
{
  "name": "search_zim_file",
  "arguments": {
    "zim_file_path": "/path/to/file.zim",
    "query": "biology",
    "limit": 5
  }
}
```

### get_zim_entry

Get detailed content of a specific entry with smart retrieval.

**Required Parameters**:

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path (e.g., 'A/Some_Article')

**Optional Parameters**:

- `max_content_length` (integer, default: 100000, min: 1000): Maximum content length

**Smart Features**:

- Automatic fallback to search if direct access fails
- Path mapping cache for performance
- Handles encoding differences automatically

**Example**:

```json
{
  "name": "get_zim_entry",
  "arguments": {
    "zim_file_path": "/path/to/file.zim",
    "entry_path": "C/Biology"
  }
}
```

## Metadata & Structure Tools

### get_zim_metadata

Get ZIM file metadata from M namespace entries.

**Required Parameters**:

- `zim_file_path` (string): Path to the ZIM file

**Returns**: JSON with entry counts, archive info, and metadata

**Example**:

```json
{
  "name": "get_zim_metadata",
  "arguments": {
    "zim_file_path": "/path/to/file.zim"
  }
}
```

### get_main_page

Get the main page entry from W namespace.

**Required Parameters**:

- `zim_file_path` (string): Path to the ZIM file

**Returns**: Main page content or information

### list_namespaces

List available namespaces and their entry counts.

**Required Parameters**:

- `zim_file_path` (string): Path to the ZIM file

**Returns**: JSON with namespace information and sample entries

**Example Response**:

```json
{
  "namespaces": {
    "C": {"count": 80000, "description": "Content articles"},
    "M": {"count": 50, "description": "Metadata"},
    "W": {"count": 1, "description": "Welcome page"}
  }
}
```

### browse_namespace

Browse entries in a specific namespace with pagination.

**Required Parameters**:

- `zim_file_path` (string): Path to the ZIM file
- `namespace` (string): Namespace to browse (C, M, W, X, A, I, etc.)

**Optional Parameters**:

- `limit` (integer, default: 50, range: 1-200): Maximum entries to return
- `offset` (integer, default: 0): Starting offset for pagination

**Example**:

```json
{
  "name": "browse_namespace",
  "arguments": {
    "zim_file_path": "/path/to/file.zim",
    "namespace": "C",
    "limit": 10
  }
}
```

## Advanced Search Tools

### search_with_filters

Search with advanced namespace and content type filters.

**Required Parameters**:

- `zim_file_path` (string): Path to the ZIM file
- `query` (string): Search query term

**Optional Parameters**:

- `namespace` (string): Namespace filter (C, M, W, X, etc.)
- `content_type` (string): Content type filter (text/html, text/plain, etc.)
- `limit` (integer, default: 10, range: 1-100): Maximum results
- `offset` (integer, default: 0): Starting offset

**Example**:

```json
{
  "name": "search_with_filters",
  "arguments": {
    "zim_file_path": "/path/to/file.zim",
    "query": "evolution",
    "namespace": "C",
    "content_type": "text/html",
    "limit": 5
  }
}
```

### get_search_suggestions

Get intelligent search suggestions and auto-complete for partial queries based on article titles and content.

**Required Parameters**:

- `zim_file_path` (string): Path to the ZIM file
- `partial_query` (string): Partial search query (minimum 2 characters)

**Optional Parameters**:

- `limit` (integer, default: 10, range: 1-50): Maximum number of suggestions to return

**Features**:

- Title-based matching with priority ranking
- Content-based suggestions for broader discovery
- Fuzzy matching for typo tolerance
- Namespace-aware suggestions

**Example**:

```json
{
  "name": "get_search_suggestions",
  "arguments": {
    "zim_file_path": "/path/to/file.zim",
    "partial_query": "bio",
    "limit": 5
  }
}
```

**Response**:

```json
{
  "partial_query": "bio",
  "suggestions": [
    {
      "text": "Biology",
      "path": "C/Biology",
      "type": "title_start_match",
      "score": 1.0,
      "namespace": "C"
    },
    {
      "text": "Biochemistry",
      "path": "C/Biochemistry",
      "type": "title_start_match",
      "score": 0.95,
      "namespace": "C"
    },
    {
      "text": "Biodiversity",
      "path": "C/Biodiversity",
      "type": "title_contains_match",
      "score": 0.85,
      "namespace": "C"
    },
    {
      "text": "Biography",
      "path": "C/Biography",
      "type": "title_fuzzy_match",
      "score": 0.75,
      "namespace": "C"
    },
    {
      "text": "Bioethics",
      "path": "C/Bioethics",
      "type": "content_match",
      "score": 0.65,
      "namespace": "C"
    }
  ],
  "count": 5,
  "total_available": 23,
  "query_time_ms": 15
}
```

## Content Analysis Tools

### get_article_structure

Extract comprehensive article structure including headings hierarchy, sections, metadata, and content analysis.

**Required Parameters**:

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path (e.g., 'C/Some_Article')

**Returns**: Detailed JSON structure with headings, sections, word count, and metadata

**Features**:

- Hierarchical heading extraction with IDs
- Section-by-section content analysis
- Word count and reading time estimation
- Table of contents generation
- Content type detection

**Example**:

```json
{
  "name": "get_article_structure",
  "arguments": {
    "zim_file_path": "/path/to/file.zim",
    "entry_path": "C/Evolution"
  }
}
```

**Response Structure**:

```json
{
  "title": "Evolution",
  "path": "C/Evolution",
  "content_type": "text/html",
  "language": "en",
  "last_modified": "2025-08-15T10:30:00Z",
  "headings": [
    {
      "level": 1,
      "text": "Evolution",
      "id": "evolution",
      "position": 0
    },
    {
      "level": 2,
      "text": "History of evolutionary thought",
      "id": "history",
      "position": 1,
      "parent_id": "evolution"
    },
    {
      "level": 3,
      "text": "Ancient and medieval understanding",
      "id": "ancient",
      "position": 2,
      "parent_id": "history"
    },
    {
      "level": 2,
      "text": "Mechanisms of evolution",
      "id": "mechanisms",
      "position": 3,
      "parent_id": "evolution"
    }
  ],
  "sections": [
    {
      "title": "Evolution",
      "level": 1,
      "id": "evolution",
      "content_preview": "Evolution is the change in heritable traits of biological populations over successive generations...",
      "word_count": 150,
      "reading_time_minutes": 1,
      "has_subsections": true
    },
    {
      "title": "History of evolutionary thought",
      "level": 2,
      "id": "history",
      "content_preview": "The proposal that one type of organism could descend from another type goes back to some of the first pre-Socratic Greek philosophers...",
      "word_count": 800,
      "reading_time_minutes": 4,
      "has_subsections": true
    }
  ],
  "statistics": {
    "total_word_count": 5000,
    "estimated_reading_time_minutes": 20,
    "heading_count": 15,
    "section_count": 8,
    "paragraph_count": 45,
    "image_count": 12,
    "link_count": 89
  },
  "table_of_contents": [
    {
      "title": "Evolution",
      "level": 1,
      "anchor": "#evolution",
      "children": [
        {
          "title": "History of evolutionary thought",
          "level": 2,
          "anchor": "#history",
          "children": [
            {
              "title": "Ancient and medieval understanding",
              "level": 3,
              "anchor": "#ancient"
            }
          ]
        },
        {
          "title": "Mechanisms of evolution",
          "level": 2,
          "anchor": "#mechanisms"
        }
      ]
    }
  ]
}
```

### extract_article_links

Extract and categorize all internal and external links from an article with detailed metadata.

**Required Parameters**:

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path (e.g., 'C/Some_Article')

**Returns**: Comprehensive JSON with categorized links, metadata, and relationship information

**Features**:

- Internal ZIM links with target validation
- External web links with domain analysis
- Media links (images, videos, audio)
- Citation and reference links
- Link context and anchor text analysis

**Example**:

```json
{
  "name": "extract_article_links",
  "arguments": {
    "zim_file_path": "/path/to/file.zim",
    "entry_path": "C/Biology"
  }
}
```

**Response Structure**:

```json
{
  "article": {
    "title": "Biology",
    "path": "C/Biology",
    "content_type": "text/html"
  },
  "links": {
    "internal": [
      {
        "text": "Evolution",
        "target_path": "C/Evolution",
        "target_title": "Evolution",
        "namespace": "C",
        "exists": true,
        "context": "The study of evolution is central to biology",
        "position": 1,
        "section": "Introduction"
      },
      {
        "text": "Cell biology",
        "target_path": "C/Cell_biology",
        "target_title": "Cell biology",
        "namespace": "C",
        "exists": true,
        "context": "Cell biology examines the basic unit of life",
        "position": 2,
        "section": "Branches"
      }
    ],
    "external": [
      {
        "text": "National Center for Biotechnology Information",
        "url": "https://www.ncbi.nlm.nih.gov/",
        "domain": "ncbi.nlm.nih.gov",
        "type": "reference",
        "context": "For more information, see NCBI database",
        "position": 15,
        "section": "References"
      }
    ],
    "media": [
      {
        "text": "DNA structure diagram",
        "target_path": "I/DNA_structure.png",
        "media_type": "image",
        "namespace": "I",
        "exists": true,
        "alt_text": "Double helix structure of DNA",
        "context": "Figure 1: DNA structure",
        "position": 5,
        "section": "Molecular biology"
      }
    ],
    "citations": [
      {
        "text": "[1]",
        "target": "#cite_note-1",
        "type": "footnote",
        "context": "Darwin's theory of evolution[1]",
        "position": 8,
        "section": "History"
      }
    ]
  },
  "statistics": {
    "total_links": 89,
    "internal_links": 67,
    "external_links": 15,
    "media_links": 5,
    "citation_links": 2,
    "broken_links": 0,
    "unique_domains": 8,
    "most_linked_article": "Evolution",
    "most_linked_domain": "ncbi.nlm.nih.gov"
  },
  "related_articles": [
    {
      "title": "Evolution",
      "path": "C/Evolution",
      "link_count": 12,
      "relevance_score": 0.95
    },
    {
      "title": "Genetics",
      "path": "C/Genetics",
      "link_count": 8,
      "relevance_score": 0.87
    }
  ]
}
```

### get_entry_summary

Get a concise summary of an article without loading the full content. Useful for quick content preview and understanding article context.

**Required Parameters**:

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path (e.g., 'C/Some_Article')

**Optional Parameters**:

- `max_words` (integer, default: 200, range: 10-1000): Maximum number of words in the summary

**Returns**: Structured JSON with article summary and metadata

**Features**:

- Extracts opening paragraphs while removing infoboxes, navigation, and sidebars
- Provides quick article overview without loading full content
- Includes truncation status and word count

**Example**:

```json
{
  "name": "get_entry_summary",
  "arguments": {
    "zim_file_path": "/path/to/file.zim",
    "entry_path": "C/Evolution",
    "max_words": 150
  }
}
```

**Response**:

```json
{
  "title": "Evolution",
  "path": "C/Evolution",
  "content_type": "text/html",
  "summary": "Evolution is the change in heritable characteristics of biological populations over successive generations. These characteristics are the expressions of genes, which are passed from parent to offspring during reproduction. Different characteristics tend to exist within any given population as a result of mutation, genetic recombination and other sources of genetic variation...",
  "word_count": 150,
  "is_truncated": true
}
```

### get_table_of_contents

Extract a hierarchical table of contents from an article based on heading levels (h1-h6). Enables LLMs to understand article structure and navigate to specific sections.

**Required Parameters**:

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path (e.g., 'C/Some_Article')

**Returns**: Hierarchical JSON structure with nested headings

**Features**:

- Hierarchical tree structure with nested children
- Includes heading levels, text, and anchor IDs
- Provides heading count and maximum depth statistics
- Enables direct navigation to specific sections

**Example**:

```json
{
  "name": "get_table_of_contents",
  "arguments": {
    "zim_file_path": "/path/to/file.zim",
    "entry_path": "C/Evolution"
  }
}
```

**Response**:

```json
{
  "title": "Evolution",
  "path": "C/Evolution",
  "content_type": "text/html",
  "toc": [
    {
      "level": 1,
      "text": "Evolution",
      "id": "evolution",
      "children": [
        {
          "level": 2,
          "text": "History of evolutionary thought",
          "id": "history",
          "children": [
            {
              "level": 3,
              "text": "Ancient and medieval understanding",
              "id": "ancient",
              "children": []
            }
          ]
        },
        {
          "level": 2,
          "text": "Mechanisms of evolution",
          "id": "mechanisms",
          "children": []
        }
      ]
    }
  ],
  "heading_count": 15,
  "max_depth": 4
}
```

### get_binary_entry

Retrieve binary content from a ZIM entry, enabling integration with external tools for processing embedded media like PDFs, videos, and images.

**Required Parameters**:

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path (e.g., 'I/image.png' or 'I/document.pdf')

**Optional Parameters**:

- `max_size_bytes` (integer): Maximum size of content to return in bytes (default: 10MB). Content larger than this will return metadata only.
- `include_data` (boolean): If true (default), include base64-encoded data. Set to false to retrieve metadata only without the binary data.

**Returns**: JSON with binary content metadata and optionally base64-encoded data

**Features**:

- Base64 encoding for safe transport through text-based protocols
- Size limits with truncation handling for large files
- Metadata-only mode for discovering content without downloading
- Smart retrieval with automatic path resolution
- Human-readable size formatting

**Example**:

```json
{
  "name": "get_binary_entry",
  "arguments": {
    "zim_file_path": "/path/to/file.zim",
    "entry_path": "I/document.pdf"
  }
}
```

**Response Structure**:

```json
{
  "path": "I/document.pdf",
  "title": "Important Document",
  "mime_type": "application/pdf",
  "size": 245678,
  "size_human": "239.92 KB",
  "encoding": "base64",
  "data": "JVBERi0xLjQKJeLjz9MKMyAwIG9iago8PC...",
  "truncated": false
}
```

**Metadata-Only Example** (for large files or discovery):

```json
{
  "name": "get_binary_entry",
  "arguments": {
    "zim_file_path": "/path/to/file.zim",
    "entry_path": "I/large_video.mp4",
    "include_data": false
  }
}
```

**Response**:

```json
{
  "path": "I/large_video.mp4",
  "title": "Tutorial Video",
  "mime_type": "video/mp4",
  "size": 52428800,
  "size_human": "50.00 MB",
  "encoding": null,
  "data": null,
  "truncated": false,
  "message": "Data not included (include_data=False)"
}
```

**Use Cases**:

- **PDF Processing**: Extract PDFs and pass to PDF parsing tools for text extraction or summarization
- **Image Analysis**: Pass images to vision models or OCR tools
- **Video/Audio Transcription**: Retrieve media files for transcription services
- **Multi-Agent Workflows**: Enable knowledge agents to delegate specialized content processing to other tools

## Server Management Tools

### get_server_health

Get comprehensive server health and statistics including cache performance, instance tracking, and system metrics.

**Parameters**: None

**Returns**: Detailed server health information with performance metrics

**Example**:

```json
{
  "name": "get_server_health"
}
```

**Response**:

```json
{
  "status": "healthy",
  "server_name": "openzim-mcp",
  "uptime_info": {
    "process_id": 12345,
    "started_at": "2025-09-14T10:30:00Z",
    "uptime_seconds": 3600
  },
  "cache_performance": {
    "enabled": true,
    "size": 15,
    "max_size": 100,
    "hit_rate": 0.85,
    "total_hits": 850,
    "total_misses": 150,
    "evictions": 5
  },
  "instance_tracking": {
    "active_instances": 1,
    "conflicts_detected": 0,
    "current_instance_id": "server_12345",
    "tracking_enabled": true
  },
  "memory_usage": {
    "cache_memory_mb": 45.2,
    "total_memory_mb": 128.5
  },
  "request_metrics": {
    "total_requests": 1000,
    "successful_requests": 995,
    "failed_requests": 5,
    "average_response_time_ms": 125
  }
}
```

### get_server_configuration

Get detailed server configuration with diagnostics and validation results.

**Parameters**: None

**Returns**: Complete configuration details, validation status, and recommendations

**Example**:

```json
{
  "name": "get_server_configuration"
}
```

**Response**:

```json
{
  "configuration": {
    "server_name": "openzim-mcp",
    "allowed_directories": ["/path/to/zim/files"],
    "cache_enabled": true,
    "cache_max_size": 100,
    "cache_ttl_seconds": 3600,
    "max_content_length": 100000,
    "config_hash": "abc123def456...",
    "server_pid": 12345
  },
  "diagnostics": {
    "validation_status": "healthy",
    "config_valid": true,
    "directories_accessible": true,
    "conflicts_detected": [],
    "warnings": [],
    "recommendations": [
      "Consider increasing cache size for better performance"
    ]
  },
  "environment": {
    "python_version": "3.11.0",
    "libzim_version": "8.2.1",
    "platform": "linux"
  }
}
```

### diagnose_server_state

Comprehensive server diagnostics including instance conflicts, configuration validation, file accessibility, and performance analysis.

**Parameters**: None

**Returns**: Detailed diagnostic information with actionable recommendations

**Example**:

```json
{
  "name": "diagnose_server_state"
}
```

**Response**:

```json
{
  "status": "healthy",
  "timestamp": "2025-09-15T10:30:00Z",
  "server_info": {
    "pid": 12345,
    "server_name": "openzim-mcp",
    "config_hash": "abc123def456...",
    "uptime_seconds": 3600
  },
  "conflicts": [],
  "issues": [],
  "warnings": [
    {
      "type": "performance",
      "message": "Cache hit rate below optimal threshold",
      "severity": "low",
      "recommendation": "Consider increasing cache TTL"
    }
  ],
  "recommendations": [
    "Server appears to be running normally",
    "Consider monitoring cache performance"
  ],
  "environment_checks": {
    "directories_accessible": true,
    "cache_functional": true,
    "zim_files_found": 5,
    "permissions_valid": true
  },
  "performance_analysis": {
    "cache_efficiency": "good",
    "memory_usage": "normal",
    "response_times": "optimal"
  }
}
```

### resolve_server_conflicts

Identify and resolve server instance conflicts including stale instance cleanup and configuration validation.

**Parameters**: None

**Returns**: Conflict resolution results and cleanup actions taken

**Example**:

```json
{
  "name": "resolve_server_conflicts"
}
```

**Response**:

```json
{
  "status": "success",
  "timestamp": "2025-09-15T10:30:00Z",
  "cleanup_results": {
    "stale_instances_removed": 2,
    "files_cleaned": [
      "/home/user/.openzim_mcp_instances/server_99999.json",
      "/home/user/.openzim_mcp_instances/server_88888.json"
    ],
    "orphaned_processes": 0
  },
  "conflicts_found": [
    {
      "type": "stale_instance",
      "instance_id": "server_99999",
      "details": "Process no longer running",
      "resolved": true
    }
  ],
  "actions_taken": [
    "Removed 2 stale instance files",
    "Validated current instance configuration",
    "Updated instance tracking registry"
  ],
  "recommendations": [
    "No active conflicts detected after cleanup",
    "Instance tracking is functioning normally"
  ],
  "active_instances_after_cleanup": 1
}
```

## Response Formats

### Standard Response Structure

All tools return structured responses with consistent formatting:

```json
{
  "status": "success|error",
  "data": {...},
  "metadata": {
    "timestamp": "2025-09-15T10:30:00Z",
    "server_name": "openzim-mcp",
    "cache_hit": true
  }
}
```

### Error Responses

```json
{
  "status": "error",
  "error": {
    "code": "ZIM_FILE_NOT_FOUND",
    "message": "ZIM file not found: /path/to/file.zim",
    "suggestions": ["Check file path", "Verify permissions"]
  }
}
```

## Error Codes

| Code | Description | Common Causes |
|------|-------------|---------------|
| `ZIM_FILE_NOT_FOUND` | ZIM file doesn't exist | Wrong path, file moved |
| `ENTRY_NOT_FOUND` | Entry doesn't exist in ZIM | Wrong entry path, typo |
| `INVALID_NAMESPACE` | Invalid namespace specified | Typo in namespace name |
| `SEARCH_FAILED` | Search operation failed | Corrupted ZIM file |
| `PERMISSION_DENIED` | Access denied | File permissions issue |
| `INVALID_PARAMETER` | Invalid parameter value | Wrong data type or range |

## Best Practices

### Performance Tips

1. **Use caching**: Repeated queries benefit from built-in caching
2. **Limit results**: Use appropriate `limit` values to avoid timeouts
3. **Batch operations**: Group related queries when possible

### Search Strategies

1. **Start broad**: Use general terms, then refine with filters
2. **Use suggestions**: Leverage auto-complete for better queries
3. **Explore structure**: Use `get_article_structure` to understand content

### Error Handling

1. **Check responses**: Always verify the response status
2. **Handle fallbacks**: Use search when direct access fails
3. **Monitor health**: Regular health checks prevent issues

---

**Need more help?** Check the [LLM Integration Patterns](LLM-Integration-Patterns) for usage examples and best practices.
