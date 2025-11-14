# OpenZIM MCP Simple Mode Guide

## Overview

OpenZIM MCP supports two distinct modes to accommodate different LLM capabilities:

1. **Simple Mode** (default): Provides just 1 primary intelligent tool that accepts natural language queries
2. **Advanced Mode**: Exposes all 15 specialized MCP tools for maximum control and flexibility

## Why Simple Mode?

Simple mode is designed for:

- **LLMs with limited tool-calling capabilities**: Some models struggle with managing many tools
- **Reduced context window usage**: Fewer tools mean less context consumed by tool definitions
- **Simpler integration**: Easier to integrate with basic MCP clients
- **Natural language interface**: More intuitive for conversational AI applications

## Enabling Simple Mode

### Command Line

```bash
# Simple mode (default)
python -m openzim_mcp /path/to/zim/files
# or explicitly
python -m openzim_mcp --mode simple /path/to/zim/files

# Advanced mode
python -m openzim_mcp --mode advanced /path/to/zim/files
```

### Environment Variable

```bash
export OPENZIM_MCP_TOOL_MODE=simple
python -m openzim_mcp /path/to/zim/files
```

### MCP Client Configuration

For Claude Desktop or other MCP clients:

```json
{
  "mcpServers": {
    "openzim-mcp-simple": {
      "command": "python",
      "args": [
        "-m",
        "openzim_mcp",
        "--mode",
        "simple",
        "/path/to/zim/files"
      ]
    }
  }
}
```

Or using environment variable:

```json
{
  "mcpServers": {
    "openzim-mcp-simple": {
      "command": "python",
      "args": ["-m", "openzim_mcp", "/path/to/zim/files"],
      "env": {
        "OPENZIM_MCP_TOOL_MODE": "simple"
      }
    }
  }
}
```

## Simple Mode Tools

### zim_query

The primary tool for all ZIM content operations. It accepts natural language queries and intelligently routes them to the appropriate underlying operations.

**Parameters:**

- `query` (required): Natural language query describing what you want
- `zim_file_path` (optional): Path to ZIM file (auto-selects if only one exists)
- `limit` (optional): Maximum number of results for search/browse operations
- `offset` (optional): Starting offset for pagination
- `max_content_length` (optional): Maximum content length for articles

**Supported Query Types:**

#### File Listing

```
"list files"
"what ZIM files are available"
"show available archives"
```

#### Metadata

```
"metadata for wikipedia.zim"
"info about this ZIM file"
"details of the archive"
```

#### Main Page

```
"show main page"
"get home page"
"display start page"
```

#### Namespaces

```
"list namespaces"
"what namespaces exist"
"show available namespaces"
```

#### Browsing

```
"browse namespace C"
"show articles in namespace A"
"explore namespace C with limit 20"
```

#### Article Structure

```
"structure of Biology"
"outline of Evolution"
"show sections of Protein"
```

#### Links Extraction

```
"links in Biology"
"references from Evolution"
"show related articles in Protein"
```

#### Search Suggestions

```
"suggestions for bio"
"autocomplete evol"
"hints for prot"
```

#### Filtered Search

```
"search evolution in namespace C"
"find biology in type text/html"
"search protein in namespace C type text/html"
```

#### Get Article

```
"get article Biology"
"show Evolution"
"read Protein"
"display article on DNA"
```

#### General Search

```
"search for biology"
"find evolution"
"look for protein"
```

## Examples

### Basic Usage

```json
{
  "name": "zim_query",
  "arguments": {
    "query": "list files"
  }
}
```

### Search with Auto-Selection

If only one ZIM file exists, you don't need to specify the path:

```json
{
  "name": "zim_query",
  "arguments": {
    "query": "search for biology"
  }
}
```

### Search with Specific File

```json
{
  "name": "zim_query",
  "arguments": {
    "query": "search for biology",
    "zim_file_path": "/path/to/wikipedia.zim",
    "limit": 5
  }
}
```

### Get Article Content

```json
{
  "name": "zim_query",
  "arguments": {
    "query": "get article Evolution",
    "zim_file_path": "/path/to/wikipedia.zim",
    "max_content_length": 5000
  }
}
```

### Browse Namespace

```json
{
  "name": "zim_query",
  "arguments": {
    "query": "browse namespace C",
    "zim_file_path": "/path/to/wikipedia.zim",
    "limit": 20,
    "offset": 0
  }
}
```

### Get Article Structure

```json
{
  "name": "zim_query",
  "arguments": {
    "query": "structure of Biology",
    "zim_file_path": "/path/to/wikipedia.zim"
  }
}
```

## Intent Parsing

The `zim_query` tool uses intelligent intent parsing to understand your query:

1. **Keyword Matching**: Looks for specific keywords like "search", "get", "browse", etc.
2. **Pattern Recognition**: Identifies patterns like "X in namespace Y"
3. **Parameter Extraction**: Extracts article names, namespaces, and other parameters
4. **Priority Ordering**: More specific patterns are checked first
5. **Fallback**: Defaults to search if intent is unclear

## Comparison: Advanced vs Simple Mode

| Aspect | Advanced Mode | Simple Mode |
|--------|-----------|-------------|
| Number of Tools | 15 specialized tools | 1 primary tool |
| Interface | Explicit tool selection | Natural language queries |
| Context Usage | Higher (all tool definitions) | Lower (minimal tool definitions) |
| Flexibility | Maximum control | Simplified interface |
| Learning Curve | Steeper (need to know which tool to use) | Gentler (just describe what you want) |
| Best For | Advanced LLMs, power users | Simple LLMs, conversational AI |

## Advanced Mode Tools (for reference)

When in advanced mode, these 15 tools are available:

1. `list_zim_files` - List all ZIM files
2. `search_zim_file` - Search within ZIM file
3. `get_zim_entry` - Get specific entry content
4. `get_zim_metadata` - Get ZIM file metadata
5. `get_main_page` - Get main page entry
6. `list_namespaces` - List available namespaces
7. `browse_namespace` - Browse entries in namespace
8. `search_with_filters` - Advanced filtered search
9. `get_search_suggestions` - Auto-complete suggestions
10. `get_article_structure` - Extract article structure
11. `extract_article_links` - Extract article links
12. `get_server_health` - Server health and statistics
13. `get_server_configuration` - Server configuration
14. `diagnose_server_state` - Comprehensive diagnostics
15. `resolve_server_conflicts` - Resolve server conflicts

## Tips for Using Simple Mode

1. **Be Descriptive**: The more descriptive your query, the better the intent parsing
2. **Use Quotes**: For specific article names, use quotes: `"get article \"C/Biology\""`
3. **Specify Limits**: Add "with limit X" to control result count
4. **Auto-Selection**: If you have only one ZIM file, you can omit the file path
5. **Fallback to Search**: If intent is unclear, the tool defaults to search

## Troubleshooting

### Query Not Understood

If your query isn't understood correctly:

1. Try being more explicit: "search for X" instead of just "X"
2. Use keywords from the supported query types
3. Check the response for suggestions
4. Fall back to more specific queries

### Wrong Operation Executed

If the wrong operation is executed:

1. Use more specific keywords
2. Check the intent parsing patterns in the documentation
3. Try rephrasing your query
4. Consider using advanced mode for precise control

## Migration Between Modes

You can switch between modes at any time by changing the configuration:

```bash
# Switch to advanced mode
export OPENZIM_MCP_TOOL_MODE=advanced

# Switch to simple mode (default)
export OPENZIM_MCP_TOOL_MODE=simple
# or
unset OPENZIM_MCP_TOOL_MODE  # defaults to simple
```

No data migration is needed - both modes use the same underlying operations and data.
