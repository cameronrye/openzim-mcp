# API Reference

Complete documentation for all OpenZIM MCP tools and their parameters.

## 📋 Overview

OpenZIM MCP provides a comprehensive set of tools for accessing and searching ZIM format knowledge bases. All tools are designed to work seamlessly with LLMs and provide intelligent, structured access to offline content.

## 🔍 Content Access Tools

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

## 🗂️ Metadata & Structure Tools

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

## 🔎 Advanced Search Tools

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

Get search suggestions and auto-complete for partial queries.

**Required Parameters**:
- `zim_file_path` (string): Path to the ZIM file
- `partial_query` (string): Partial search query (min 2 characters)

**Optional Parameters**:
- `limit` (integer, default: 10, range: 1-50): Maximum suggestions

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

## 📄 Content Analysis Tools

### get_article_structure

Extract article structure including headings, sections, and metadata.

**Required Parameters**:
- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path (e.g., 'C/Some_Article')

**Returns**: JSON with headings, sections, word count, and metadata

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
  "headings": [
    {"level": 1, "text": "Evolution", "id": "evolution"},
    {"level": 2, "text": "History", "id": "history"}
  ],
  "sections": [...],
  "word_count": 5000
}
```

### extract_article_links

Extract internal and external links from an article.

**Required Parameters**:
- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path (e.g., 'C/Some_Article')

**Returns**: JSON with categorized links (internal, external, media)

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

## 🔧 Server Management Tools

### get_server_health

Get comprehensive server health and statistics.

**Parameters**: None

**Returns**: Server status, cache metrics, instance tracking

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
  "cache": {
    "enabled": true,
    "size": 15,
    "max_size": 100,
    "hit_rate": 0.85
  },
  "instance_tracking": {
    "active_instances": 1,
    "conflicts_detected": 0
  }
}
```

### get_server_configuration

Get detailed server configuration with diagnostics.

**Parameters**: None

**Returns**: Configuration details, validation results, recommendations

### diagnose_server_state

Comprehensive server diagnostics and health checks.

**Parameters**: None

**Returns**: Diagnostic information, conflicts, issues, recommendations

### resolve_server_conflicts

Identify and resolve server instance conflicts.

**Parameters**: None

**Returns**: Conflict resolution results and cleanup actions

## 📊 Response Formats

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

## 🚨 Error Codes

| Code | Description | Common Causes |
|------|-------------|---------------|
| `ZIM_FILE_NOT_FOUND` | ZIM file doesn't exist | Wrong path, file moved |
| `ENTRY_NOT_FOUND` | Entry doesn't exist in ZIM | Wrong entry path, typo |
| `INVALID_NAMESPACE` | Invalid namespace specified | Typo in namespace name |
| `SEARCH_FAILED` | Search operation failed | Corrupted ZIM file |
| `PERMISSION_DENIED` | Access denied | File permissions issue |
| `INVALID_PARAMETER` | Invalid parameter value | Wrong data type or range |

## 💡 Best Practices

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
