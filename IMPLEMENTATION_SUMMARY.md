# OpenZIM MCP Dual Mode Implementation Summary

## Overview

Successfully implemented dual-mode support for the OpenZIM MCP server, allowing users to choose between:

1. **Full Mode** (default): All 15 specialized MCP tools for maximum control
2. **Simple Mode**: 1 intelligent natural language tool for simplified interaction

## Implementation Details

### Files Created

1. **`openzim_mcp/simple_tools.py`** (445 lines)
   - `IntentParser` class: Parses natural language queries to determine user intent
   - `SimpleToolsHandler` class: Routes queries to appropriate underlying operations
   - Supports 11 different intent types with intelligent parameter extraction

2. **`docs/SIMPLE_MODE_GUIDE.md`** (300 lines)
   - Comprehensive guide for using simple mode
   - Examples for all supported query types
   - Comparison between full and simple modes
   - Troubleshooting tips

3. **`tests/test_simple_tools.py`** (300 lines)
   - 27 test cases covering intent parsing and handler functionality
   - All tests passing ✅
   - 77% code coverage for simple_tools.py

### Files Modified

1. **`openzim_mcp/constants.py`**
   - Added `TOOL_MODE_FULL`, `TOOL_MODE_SIMPLE`, `VALID_TOOL_MODES` constants

2. **`openzim_mcp/config.py`**
   - Added `tool_mode` field with validation
   - Updated configuration hash and summary to include tool mode
   - Environment variable support: `OPENZIM_MCP_TOOL_MODE`

3. **`openzim_mcp/server.py`**
   - Added `SimpleToolsHandler` initialization for simple mode
   - Created `_register_simple_tools()` method
   - Modified `_register_tools()` to check mode and register appropriate tools
   - Renamed existing tool registration to `_register_full_tools()`

4. **`openzim_mcp/main.py`**
   - Added `--mode` command line argument
   - Updated help text with examples
   - Enhanced startup messages to show current mode

5. **`README.md`**
   - Added dual mode announcement at top
   - Updated features list
   - Added mode selection examples
   - Updated MCP configuration examples

## Features

### Simple Mode Tool: `zim_query`

A single intelligent tool that handles all ZIM content operations through natural language:

**Supported Query Types:**
- File listing: "list files", "what ZIM files are available"
- Metadata: "metadata for file.zim", "info about this ZIM"
- Main page: "show main page", "get home page"
- Namespaces: "list namespaces", "what namespaces exist"
- Browsing: "browse namespace C", "show articles in namespace A"
- Article structure: "structure of Biology", "outline of Evolution"
- Links: "links in Biology", "references from Evolution"
- Suggestions: "suggestions for bio", "autocomplete evol"
- Filtered search: "search evolution in namespace C"
- Get article: "get article Biology", "show Evolution"
- General search: "search for biology", "find evolution"

**Parameters:**
- `query` (required): Natural language query
- `zim_file_path` (optional): Auto-selects if only one file exists
- `limit` (optional): Maximum results for search/browse
- `offset` (optional): Pagination offset
- `max_content_length` (optional): Maximum content length for articles

### Intent Parsing

The `IntentParser` uses:
- Regex pattern matching with priority ordering
- Keyword detection (case-insensitive)
- Parameter extraction from natural language
- Fallback to search for ambiguous queries

### Auto-Selection

When `zim_file_path` is not provided:
- Lists available ZIM files
- Auto-selects if exactly one file exists
- Returns helpful error with file list if multiple files exist

## Configuration

### Command Line

```bash
# Full mode (default)
openzim-mcp /path/to/zim/files

# Simple mode
openzim-mcp --mode simple /path/to/zim/files
```

### Environment Variable

```bash
export OPENZIM_MCP_TOOL_MODE=simple
openzim-mcp /path/to/zim/files
```

### MCP Client Configuration

```json
{
  "openzim-mcp-simple": {
    "command": "openzim-mcp",
    "args": ["--mode", "simple", "/path/to/zim/files"]
  }
}
```

## Benefits

### For Simple LLMs
- **Reduced Complexity**: 1 tool instead of 15
- **Lower Context Usage**: Minimal tool definitions
- **Natural Language**: Intuitive conversational interface
- **Easier Integration**: Simpler for basic MCP clients

### For Advanced LLMs
- **Full Control**: All 15 specialized tools available
- **Maximum Flexibility**: Precise control over operations
- **Backward Compatible**: Existing integrations unchanged

## Testing

- **27 test cases** for simple tools functionality
- **All tests passing** ✅
- **77% code coverage** for simple_tools.py
- Tests cover:
  - Intent parsing for all query types
  - Parameter extraction
  - Handler routing
  - Auto-selection logic
  - Error handling

## Backward Compatibility

- **Default mode is "full"**: Existing users unaffected
- **No breaking changes**: All existing tools work as before
- **Opt-in simple mode**: Users choose when to use it
- **Same underlying operations**: Both modes use identical ZIM operations

## Documentation

1. **Simple Mode Guide** (`docs/SIMPLE_MODE_GUIDE.md`)
   - Complete usage guide
   - Examples for all query types
   - Comparison table
   - Troubleshooting tips

2. **Updated README**
   - Dual mode announcement
   - Quick start examples
   - Configuration examples

3. **Code Documentation**
   - Comprehensive docstrings
   - Type annotations
   - Inline comments

## Future Enhancements

Potential improvements for future versions:

1. **Enhanced Intent Parsing**
   - Machine learning-based intent detection
   - Context-aware query understanding
   - Multi-turn conversation support

2. **Additional Simple Tools**
   - `zim_server_status`: Server management tool (partially implemented)
   - Combined operations for common workflows

3. **Query Suggestions**
   - Auto-suggest query formats
   - Example queries in error messages
   - Interactive query builder

4. **Performance Optimization**
   - Cache intent parsing results
   - Optimize regex patterns
   - Batch operations

## Conclusion

The dual-mode implementation successfully addresses the need for both:
- **Simplicity** for LLMs with limited capabilities
- **Power** for advanced use cases

The implementation maintains full backward compatibility while providing a natural language interface that makes OpenZIM MCP accessible to a wider range of LLMs and use cases.

