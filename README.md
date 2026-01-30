<p align="center">
  <img src="https://raw.githubusercontent.com/cameronrye/openzim-mcp/main/website/assets/logo.svg" alt="OpenZIM MCP Logo" width="120" height="120">
</p>

<h1 align="center">OpenZIM MCP Server</h1>

<p align="center">
  <strong>Transform static ZIM archives into dynamic knowledge engines for AI models</strong>
</p>

<p align="center">
  <a href="https://github.com/cameronrye/openzim-mcp/actions/workflows/test.yml"><img src="https://github.com/cameronrye/openzim-mcp/workflows/CI/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/cameronrye/openzim-mcp"><img src="https://codecov.io/gh/cameronrye/openzim-mcp/branch/main/graph/badge.svg" alt="codecov"></a>
  <a href="https://github.com/cameronrye/openzim-mcp/actions/workflows/codeql.yml"><img src="https://github.com/cameronrye/openzim-mcp/workflows/CodeQL%20Security%20Analysis/badge.svg" alt="CodeQL"></a>
  <a href="https://sonarcloud.io/summary/new_code?id=cameronrye_openzim-mcp"><img src="https://sonarcloud.io/api/project_badges/measure?project=cameronrye_openzim-mcp&metric=security_rating" alt="Security Rating"></a>
</p>

<p align="center">
  <a href="https://badge.fury.io/py/openzim-mcp"><img src="https://badge.fury.io/py/openzim-mcp.svg" alt="PyPI version"></a>
  <a href="https://pypi.org/project/openzim-mcp/"><img src="https://img.shields.io/pypi/pyversions/openzim-mcp" alt="PyPI - Python Version"></a>
  <a href="https://pypi.org/project/openzim-mcp/"><img src="https://img.shields.io/pypi/dm/openzim-mcp" alt="PyPI - Downloads"></a>
  <a href="https://github.com/cameronrye/openzim-mcp/releases"><img src="https://img.shields.io/github/v/release/cameronrye/openzim-mcp" alt="GitHub release"></a>
</p>

<p align="center">
  <a href="https://github.com/psf/black"><img src="https://img.shields.io/badge/code%20style-black-000000.svg" alt="Code style: black"></a>
  <a href="https://pycqa.github.io/isort/"><img src="https://img.shields.io/badge/%20imports-isort-%231674b1?style=flat&labelColor=ef8336" alt="Imports: isort"></a>
  <a href="https://mypy-lang.org/"><img src="https://img.shields.io/badge/type%20checked-mypy-blue" alt="Type checked: mypy"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="https://github.com/cameronrye/openzim-mcp/issues"><img src="https://img.shields.io/github/issues/cameronrye/openzim-mcp" alt="GitHub issues"></a>
  <a href="https://github.com/cameronrye/openzim-mcp/pulls"><img src="https://img.shields.io/github/issues-pr/cameronrye/openzim-mcp" alt="GitHub pull requests"></a>
  <a href="https://github.com/cameronrye/openzim-mcp/graphs/contributors"><img src="https://img.shields.io/github/contributors/cameronrye/openzim-mcp" alt="GitHub contributors"></a>
  <a href="https://github.com/cameronrye/openzim-mcp/stargazers"><img src="https://img.shields.io/github/stars/cameronrye/openzim-mcp?style=social" alt="GitHub stars"></a>
</p>

---

> 🆕 **NEW: Article Summaries & Table of Contents!** Extract concise article summaries and hierarchical table of contents for quick content overview. Plus pagination cursors for seamless navigation! [Learn more →](#get_entry_summary---get-a-concise-article-summary)

> **Dual Mode Support:** Choose between Simple mode (1 intelligent natural language tool, default) or Advanced mode (18 specialized tools) to match your LLM's capabilities.

## Built for LLM Intelligence

**OpenZIM MCP transforms static ZIM archives into dynamic knowledge engines for Large Language Models.** Unlike basic file readers, this tool provides *intelligent, structured access* that LLMs need to effectively navigate and understand vast knowledge repositories.

 **Why LLMs Love OpenZIM MCP:**

- **Smart Navigation**: Browse by namespace (articles, metadata, media) instead of blind searching
- **Context-Aware Discovery**: Get article structure, relationships, and metadata for deeper understanding
- **Intelligent Search**: Advanced filtering, auto-complete suggestions, and relevance-ranked results
- **Performance Optimized**: Cached operations and pagination prevent timeouts on massive archives
- **Relationship Mapping**: Extract internal/external links to understand content connections

Whether you're building a research assistant, knowledge chatbot, or content analysis system, OpenZIM MCP gives your LLM the structured access patterns it needs to unlock the full potential of offline knowledge archives. No more fumbling through raw text dumps!

**OpenZIM MCP** is a modern, secure, and high-performance MCP (Model Context Protocol) server that enables AI models to access and search [ZIM format](https://en.wikipedia.org/wiki/ZIM_(file_format)) knowledge bases offline.

[ZIM](https://en.wikipedia.org/wiki/ZIM_(file_format)) (Zeno IMproved) is an open file format developed by the [openZIM project](https://openzim.org/), designed specifically for offline storage and access to website content. The format supports high compression rates using Zstandard compression (default since 2021) and enables fast full-text searching, making it ideal for storing entire Wikipedia content and other large reference materials in relatively compact files. The openZIM project is sponsored by Wikimedia CH and supported by the Wikimedia Foundation, ensuring the format's continued development and adoption for offline knowledge access, especially in environments without reliable internet connectivity.

## Features

- **Dual Mode Support**: Choose between Simple mode (1 intelligent natural language tool, default) or Advanced mode (18 specialized tools)
- **Binary Content Retrieval**: 🆕 Extract PDFs, images, videos, and other embedded media for multi-agent workflows
- **Security First**: Comprehensive input validation and path traversal protection
- **High Performance**: Intelligent caching and optimized ZIM file operations
- **Smart Retrieval**: Automatic fallback from direct access to search-based retrieval for reliable entry access
- **Well Tested**: 80%+ test coverage with comprehensive test suite
- **Modern Architecture**: Modular design with dependency injection
- **Type Safe**: Full type annotations throughout the codebase
- **Configurable**: Flexible configuration with validation
- **Observable**: Structured logging and health monitoring

## Quick Start

### Installation

```bash
# Install from PyPI (recommended)
pip install openzim-mcp
```

### Development Installation

For contributors and developers:

```bash
# Clone the repository
git clone https://github.com/cameronrye/openzim-mcp.git
cd openzim-mcp

# Install dependencies
uv sync

# Install development dependencies
uv sync --dev
```

### Prepare ZIM Files

Download ZIM files (e.g., Wikipedia, Wiktionary, etc.) from the [Kiwix Library](https://browse.library.kiwix.org/) and place them in a directory:

```bash
mkdir ~/zim-files
# Download ZIM files to ~/zim-files/
```

### Running the Server

```bash
# Simple mode (default) - 1 intelligent natural language tool
openzim-mcp /path/to/zim/files
python -m openzim_mcp /path/to/zim/files

# Advanced mode - all 18 specialized tools
openzim-mcp --mode advanced /path/to/zim/files
python -m openzim_mcp --mode advanced /path/to/zim/files

# For development (from source)
uv run python -m openzim_mcp /path/to/zim/files
uv run python -m openzim_mcp --mode advanced /path/to/zim/files

# Or using make (development)
make run ZIM_DIR=/path/to/zim/files
```

### Tool Modes

OpenZIM MCP supports two modes:

- **Simple Mode** (default): Provides 1 intelligent tool (`zim_query`) that accepts natural language queries
- **Advanced Mode**: Exposes all 18 specialized MCP tools for maximum control

See [Simple Mode Guide](docs/SIMPLE_MODE_GUIDE.md) for detailed information.

### MCP Configuration

**Simple Mode (default):**

```json
{
  "openzim-mcp": {
    "command": "openzim-mcp",
    "args": ["/path/to/zim/files"]
  }
}
```

**Advanced Mode:**

```json
{
  "openzim-mcp-advanced": {
    "command": "openzim-mcp",
    "args": ["--mode", "advanced", "/path/to/zim/files"]
  }
}
```

Alternative configuration using Python module:

```json
{
  "openzim-mcp": {
    "command": "python",
    "args": [
      "-m",
      "openzim_mcp",
      "/path/to/zim/files"
    ]
  }
}
```

For development (from source):

```json
{
  "openzim-mcp": {
    "command": "uv",
    "args": [
      "--directory",
      "/path/to/openzim-mcp",
      "run",
      "python",
      "-m",
      "openzim_mcp",
      "/path/to/zim/files"
    ]
  }
}
```

## Development

### Running Tests

```bash
# Run all tests
make test

# Run tests with coverage
make test-cov

# Run specific test file
uv run pytest tests/test_security.py -v

# Run tests with ZIM test data (comprehensive testing)
make test-with-zim-data

# Run integration tests only
make test-integration

# Run tests that require ZIM test data
make test-requires-zim-data
```

### ZIM Test Data Integration

OpenZIM MCP integrates with the official [zim-testing-suite](https://github.com/openzim/zim-testing-suite) for comprehensive testing with real ZIM files:

```bash
# Download essential test files (basic testing)
make download-test-data

# Download all test files (comprehensive testing)
make download-test-data-all

# List available test files
make list-test-data

# Clean downloaded test data
make clean-test-data
```

The test data includes:

- **Basic files**: Small ZIM files for essential testing
- **Real content**: Actual Wikipedia/Wikibooks content for integration testing
- **Invalid files**: Malformed ZIM files for error handling testing
- **Special cases**: Embedded content, split files, and edge cases

Test files are automatically organized by category and priority level.

### Code Quality

```bash
# Format code
make format

# Run linting
make lint

# Type checking
make type-check

# Run all checks
make check
```

### Project Structure

```text
openzim-mcp/
├── openzim_mcp/             # Main package
│   ├── __init__.py        # Package initialization
│   ├── __main__.py        # Module entry point
│   ├── main.py            # Main entry point
│   ├── server.py          # MCP server implementation
│   ├── config.py          # Configuration management
│   ├── security.py        # Security and validation
│   ├── cache.py           # Caching functionality
│   ├── content_processor.py # Content processing
│   ├── zim_operations.py  # ZIM file operations
│   ├── exceptions.py      # Custom exceptions
│   └── constants.py       # Application constants
├── tests/                 # Test suite
├── pyproject.toml        # Project configuration
├── Makefile              # Development commands
└── README.md             # This file
```

---

## API Reference

### Available Tools

### list_zim_files - List all ZIM files in allowed directories

No parameters required.

### search_zim_file - Search within ZIM file content

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `query` (string): Search query term

**Optional parameters:**

- `limit` (integer, default: 10): Maximum number of results to return
- `offset` (integer, default: 0): Starting offset for results (for pagination)

### get_zim_entry - Get detailed content of a specific entry in a ZIM file

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path, e.g., 'A/Some_Article'

**Optional parameters:**

- `max_content_length` (integer, default: 100000, minimum: 1000): Maximum length of returned content

**Smart Retrieval Features:**

- **Automatic Fallback**: If direct path access fails, automatically searches for the entry and uses the exact path found
- **Path Mapping Cache**: Caches successful path mappings for improved performance on repeated access
- **Enhanced Error Guidance**: Provides clear guidance when entries cannot be found, suggesting alternative approaches
- **Transparent Operation**: Works seamlessly regardless of path encoding differences (spaces vs underscores, URL encoding, etc.)

### get_zim_metadata - Get ZIM file metadata from M namespace entries

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file

**Returns:**
JSON string containing ZIM metadata including entry counts, archive information, and metadata entries like title, description, language, creator, etc.

### get_main_page - Get the main page entry from W namespace

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file

**Returns:**
Main page content or information about the main page entry.

### list_namespaces - List available namespaces and their entry counts

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file

**Returns:**
JSON string containing namespace information with entry counts, descriptions, and sample entries for each namespace (C, M, W, X, etc.).

### browse_namespace - Browse entries in a specific namespace with pagination

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `namespace` (string): Namespace to browse (C, M, W, X, A, I, etc.)

**Optional parameters:**

- `limit` (integer, default: 50, range: 1-200): Maximum number of entries to return
- `offset` (integer, default: 0): Starting offset for pagination

**Returns:**
JSON string containing namespace entries with titles, content previews, and pagination information.

### search_with_filters - Search within ZIM file content with advanced filters

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `query` (string): Search query term

**Optional parameters:**

- `namespace` (string): Optional namespace filter (C, M, W, X, etc.)
- `content_type` (string): Optional content type filter (text/html, text/plain, etc.)
- `limit` (integer, default: 10, range: 1-100): Maximum number of results to return
- `offset` (integer, default: 0): Starting offset for pagination

**Returns:**
Filtered search results with namespace and content type information.

### get_search_suggestions - Get search suggestions and auto-complete

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `partial_query` (string): Partial search query (minimum 2 characters)

**Optional parameters:**

- `limit` (integer, default: 10, range: 1-50): Maximum number of suggestions to return

**Returns:**
JSON string containing search suggestions based on article titles and content.

### get_article_structure - Extract article structure and metadata

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path, e.g., 'C/Some_Article'

**Returns:**
JSON string containing article structure including headings, sections, metadata, and word count.

### extract_article_links - Extract internal and external links from an article

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path, e.g., 'C/Some_Article'

**Returns:**
JSON string containing categorized links (internal, external, media) with titles and metadata.

### get_entry_summary - Get a concise article summary

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path, e.g., 'C/Some_Article'

**Optional parameters:**

- `max_words` (integer, default: 200, range: 10-1000): Maximum number of words in the summary

**Returns:**
JSON string containing a concise summary extracted from the article's opening paragraphs, with metadata including title, word count, and truncation status.

**Features:**

- Extracts opening paragraphs while removing infoboxes, navigation, and sidebars
- Provides quick article overview without loading full content
- Useful for LLMs to understand article context before deciding to read more

### get_table_of_contents - Extract hierarchical table of contents

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path, e.g., 'C/Some_Article'

**Returns:**
JSON string containing a hierarchical tree structure of article headings (h1-h6), suitable for navigation and content overview.

**Features:**

- Hierarchical tree structure with nested children
- Includes heading levels, text, and anchor IDs
- Provides heading count and maximum depth statistics
- Enables LLMs to navigate directly to specific sections

### get_binary_entry - Retrieve binary content from a ZIM entry

**Required parameters:**

- `zim_file_path` (string): Path to the ZIM file
- `entry_path` (string): Entry path, e.g., 'I/image.png' or 'I/document.pdf'

**Optional parameters:**

- `max_size_bytes` (integer): Maximum size of content to return (default: 10MB). Content larger than this will return metadata only.
- `include_data` (boolean): If true (default), include base64-encoded data. Set to false to retrieve metadata only.

**Returns:**

JSON string containing:

- `path`: Entry path in ZIM file
- `title`: Entry title
- `mime_type`: Content type (e.g., "application/pdf", "image/png")
- `size`: Size in bytes
- `size_human`: Human-readable size (e.g., "1.5 MB")
- `encoding`: "base64" when data is included, null otherwise
- `data`: Base64-encoded content (if include_data=true and under size limit)
- `truncated`: Boolean indicating if content exceeded size limit

**Use Cases:**

- Retrieve PDFs for processing with PDF parsing tools
- Extract images for vision models or OCR tools
- Get video/audio files for transcription services
- Enable multi-agent workflows with specialized content processors

---

## Examples

### Listing ZIM files

```json
{
  "name": "list_zim_files"
}
```

Response:

```plain
Found 1 ZIM files in 1 directories:

[
  {
    "name": "wikipedia_en_100_2025-08.zim",
    "path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "directory": "C:\\zim",
    "size": "310.77 MB",
    "modified": "2025-09-11T10:20:50.148427"
  }
]
```

### Searching ZIM files

```json
{
  "name": "search_zim_file",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "query": "biology",
    "limit": 3
  }
}
```

Response:

```plain
Found 51 matches for "biology", showing 1-3:

## 1. Taxonomy (biology)
Path: Taxonomy_(biology)
Snippet: #  Taxonomy (biology) Part of a series on
---
Evolutionary biology
Darwin's finches by John Gould

  * Index
  * Introduction
  * [Main](Evolution "Evolution")
  * Outline

## 2. Protein
Path: Protein
Snippet: #  Protein A representation of the 3D structure of the protein myoglobin showing turquoise α-helices. This protein was the first to have its structure solved by X-ray crystallography. Toward the right-center among the coils, a prosthetic group called a heme group (shown in gray) with a bound oxygen molecule (red).

## 3. Ant
Path: Ant
Snippet: #  Ant Ants
Temporal range: Late Aptian – Present
---
Fire ants
[Scientific classification](Taxonomy_\(biology\) "Taxonomy \(biology\)")
Kingdom:  | [Animalia](Animal "Animal")
Phylum:  | [Arthropoda](Arthropod "Arthropod")
Class:  | [Insecta](Insect "Insect")
Order:  | Hymenoptera
Infraorder:  | Aculeata
Superfamily:  |
Latreille, 1809[1]
Family:  |
Latreille, 1809
```

### Getting ZIM entries

```json
{
  "name": "get_zim_entry",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "entry_path": "Protein"
  }
}
```

Response:

```plain
# Protein

Path: Protein
Type: text/html
## Content

#  Protein

A representation of the 3D structure of the protein myoglobin showing turquoise α-helices. This protein was the first to have its structure solved by X-ray crystallography. Toward the right-center among the coils, a prosthetic group called a heme group (shown in gray) with a bound oxygen molecule (red).

**Proteins** are large biomolecules and macromolecules that comprise one or more long chains of amino acid residues. Proteins perform a vast array of functions within organisms, including catalysing metabolic reactions, DNA replication, responding to stimuli, providing structure to cells and organisms, and transporting molecules from one location to another. Proteins differ from one another primarily in their sequence of amino acids, which is dictated by the nucleotide sequence of their genes, and which usually results in protein folding into a specific 3D structure that determines its activity.

A linear chain of amino acid residues is called a polypeptide. A protein contains at least one long polypeptide. Short polypeptides, containing less than 20–30 residues, are rarely considered to be proteins and are commonly called peptides.

... [Content truncated, total of 56,202 characters, only showing first 1,500 characters] ...
```

### Smart Retrieval in Action

**Example: Automatic path resolution**

```json
{
  "name": "get_zim_entry",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "entry_path": "A/Test Article"
  }
}
```

Response (showing smart retrieval working):

```plain
# Test Article

Requested Path: A/Test Article
Actual Path: A/Test_Article
Type: text/html

## Content

# Test Article

This article demonstrates the smart retrieval system automatically handling
path encoding differences. The system tried "A/Test Article" directly,
then automatically searched and found "A/Test_Article".

... [Content continues] ...
```

### get_server_health - Get server health and statistics

No parameters required.

**Returns:**

- Server status and performance metrics
- Cache statistics
- Configuration information
- Instance tracking information
- Conflict detection results

**Example Response:**

```json
{
  "status": "healthy",
  "server_name": "openzim-mcp",
  "allowed_directories": 1,
  "cache": {
    "enabled": true,
    "size": 1,
    "max_size": 100,
    "ttl_seconds": 3600
  },
  "instance_tracking": {
    "active_instances": 1,
    "conflicts_detected": 0
  }
}
```

### get_server_configuration - Get detailed server configuration

No parameters required.

**Returns:**
Comprehensive server configuration including diagnostics, validation results, and conflict detection.

**Example Response:**

```json
{
  "configuration": {
    "server_name": "openzim-mcp",
    "allowed_directories": ["/path/to/zim/files"],
    "cache_enabled": true,
    "config_hash": "abc123...",
    "server_pid": 12345
  },
  "diagnostics": {
    "validation_status": "healthy",
    "conflicts_detected": [],
    "warnings": [],
    "recommendations": []
  }
}
```

### diagnose_server_state - Comprehensive server diagnostics

No parameters required.

**Returns:**
Detailed diagnostic information including instance conflicts, configuration validation, file accessibility checks, and actionable recommendations.

**Example Response:**

```json
{
  "status": "healthy",
  "server_info": {
    "pid": 12345,
    "server_name": "openzim-mcp",
    "config_hash": "abc123..."
  },
  "conflicts": [],
  "issues": [],
  "recommendations": ["Server appears to be running normally"],
  "environment_checks": {
    "directories_accessible": true,
    "cache_functional": true
  }
}
```

### resolve_server_conflicts - Identify and resolve server conflicts

No parameters required.

**Returns:**
Results of conflict resolution including cleanup actions and recommendations.

**Example Response:**

```json
{
  "status": "success",
  "cleanup_results": {
    "stale_instances_removed": 2
  },
  "conflicts_found": [],
  "actions_taken": ["Removed 2 stale instance files"],
  "recommendations": ["No active conflicts detected"]
}
```

### Additional Search Examples

**Computer-related search:**

```json
{
  "name": "search_zim_file",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "query": "computer",
    "limit": 2
  }
}
```

Response:

```plain
Found 39 matches for "computer", showing 1-2:

## 1. Video game
Path: Video_game
Snippet: #  Video game First-generation _Pong_ console at the Computerspielemuseum Berlin
---
Platforms

## 2. Protein
Path: Protein
Snippet: #  Protein A representation of the 3D structure of the protein myoglobin showing turquoise α-helices. This protein was the first to have its structure solved by X-ray crystallography. Toward the right-center among the coils, a prosthetic group called a heme group (shown in gray) with a bound oxygen molecule (red).
```

**Getting detailed content:**

```json
{
  "name": "get_zim_entry",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "entry_path": "Evolution",
    "max_content_length": 1500
  }
}
```

Response:

```plain
# Evolution

Path: Evolution
Type: text/html
## Content

#  Evolution

Part of the Biology series on
---
****
Mechanisms and processes

  * Adaptation
  * Genetic drift
  * Gene flow
  * History of life
  * Maladaptation
  * Mutation
  * Natural selection
  * Neutral theory
  * Population genetics
  * Speciation

... [Content truncated, total of 110,237 characters, only showing first 1,500 characters] ...
```

### Advanced Knowledge Retrieval Examples

**Getting ZIM metadata:**

```json
{
  "name": "get_zim_metadata",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim"
  }
}
```

Response:

```json
{
  "entry_count": 100000,
  "all_entry_count": 120000,
  "article_count": 80000,
  "media_count": 20000,
  "metadata_entries": {
    "Title": "Wikipedia (English)",
    "Description": "Wikipedia articles in English",
    "Language": "eng",
    "Creator": "Kiwix",
    "Date": "2025-08-15"
  }
}
```

**Browsing a namespace:**

```json
{
  "name": "browse_namespace",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "namespace": "C",
    "limit": 5,
    "offset": 0
  }
}
```

Response:

```json
{
  "namespace": "C",
  "total_in_namespace": 80000,
  "offset": 0,
  "limit": 5,
  "returned_count": 5,
  "has_more": true,
  "entries": [
    {
      "path": "C/Biology",
      "title": "Biology",
      "content_type": "text/html",
      "preview": "Biology is the scientific study of life..."
    }
  ]
}
```

**Filtered search:**

```json
{
  "name": "search_with_filters",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "query": "evolution",
    "namespace": "C",
    "content_type": "text/html",
    "limit": 3
  }
}
```

**Getting article structure:**

```json
{
  "name": "get_article_structure",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "entry_path": "C/Evolution"
  }
}
```

Response:

```json
{
  "title": "Evolution",
  "path": "C/Evolution",
  "content_type": "text/html",
  "headings": [
    {"level": 1, "text": "Evolution", "id": "evolution"},
    {"level": 2, "text": "History", "id": "history"},
    {"level": 2, "text": "Mechanisms", "id": "mechanisms"}
  ],
  "sections": [
    {
      "title": "Evolution",
      "level": 1,
      "content_preview": "Evolution is the change in heritable traits...",
      "word_count": 150
    }
  ],
  "word_count": 5000
}
```

**Getting article summary:**

```json
{
  "name": "get_entry_summary",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "entry_path": "C/Evolution",
    "max_words": 100
  }
}
```

Response:

```json
{
  "title": "Evolution",
  "path": "C/Evolution",
  "content_type": "text/html",
  "summary": "Evolution is the change in heritable characteristics of biological populations over successive generations. These characteristics are the expressions of genes, which are passed from parent to offspring during reproduction...",
  "word_count": 100,
  "is_truncated": true
}
```

**Getting table of contents:**

```json
{
  "name": "get_table_of_contents",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "entry_path": "C/Evolution"
  }
}
```

Response:

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
          "children": []
        },
        {
          "level": 2,
          "text": "Mechanisms",
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

**Getting search suggestions:**

```json
{
  "name": "get_search_suggestions",
  "arguments": {
    "zim_file_path": "C:\\zim\\wikipedia_en_100_2025-08.zim",
    "partial_query": "bio",
    "limit": 5
  }
}
```

Response:

```json
{
  "partial_query": "bio",
  "suggestions": [
    {"text": "Biology", "path": "C/Biology", "type": "title_start_match"},
    {"text": "Biochemistry", "path": "C/Biochemistry", "type": "title_start_match"},
    {"text": "Biodiversity", "path": "C/Biodiversity", "type": "title_start_match"}
  ],
  "count": 3
}
```

### Server Management and Diagnostics Examples

**Getting server health:**

```json
{
  "name": "get_server_health"
}
```

Response:

```json
{
  "status": "healthy",
  "server_name": "openzim-mcp",
  "uptime_info": {
    "process_id": 12345,
    "started_at": "2025-09-14T10:30:00"
  },
  "cache_performance": {
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

**Diagnosing server state:**

```json
{
  "name": "diagnose_server_state"
}
```

Response:

```json
{
  "status": "healthy",
  "server_info": {
    "pid": 12345,
    "server_name": "openzim-mcp",
    "config_hash": "abc123def456..."
  },
  "conflicts": [],
  "issues": [],
  "recommendations": ["Server appears to be running normally. No issues detected."],
  "environment_checks": {
    "directories_accessible": true,
    "cache_functional": true,
    "zim_files_found": 5
  }
}
```

**Resolving server conflicts:**

```json
{
  "name": "resolve_server_conflicts"
}
```

Response:

```json
{
  "status": "success",
  "cleanup_results": {
    "stale_instances_removed": 2,
    "files_cleaned": ["/home/user/.openzim_mcp_instances/server_99999.json"]
  },
  "conflicts_found": [],
  "actions_taken": ["Removed 2 stale instance files"],
  "recommendations": ["No active conflicts detected after cleanup"]
}
```

---

## ZIM Entry Retrieval Best Practices

### Smart Retrieval System

OpenZIM MCP implements an intelligent entry retrieval system that automatically handles path encoding inconsistencies common in ZIM files:

**How It Works:**

1. **Direct Access First**: Attempts to retrieve the entry using the provided path exactly as given
2. **Automatic Fallback**: If direct access fails, automatically searches for the entry using various search terms
3. **Path Mapping Cache**: Caches successful path mappings to improve performance for repeated access
4. **Enhanced Error Guidance**: Provides clear guidance when entries cannot be found

**Benefits for LLM Users:**

- **Transparent Operation**: No need to understand ZIM path encoding complexities
- **Single Tool Call**: Eliminates the need for manual search-first methodology
- **Reliable Results**: Consistent success across different path formats (spaces vs underscores, URL encoding, etc.)
- **Performance Optimized**: Cached mappings improve repeated access speed

**Example Scenarios Handled Automatically:**

- `A/Test Article` → `A/Test_Article` (space to underscore conversion)
- `C/Café` → `C/Caf%C3%A9` (URL encoding differences)
- `A/Some-Page` → `A/Some_Page` (hyphen to underscore conversion)

### Usage Recommendations

**For Direct Entry Access:**

```json
{
  "name": "get_zim_entry",
  "arguments": {
    "zim_file_path": "/path/to/file.zim",
    "entry_path": "A/Article_Name"
  }
}
```

**When Entry Not Found:**
The system will automatically provide guidance:

```
Entry not found: 'A/Article_Name'.
The entry path may not exist in this ZIM file.
Try using search_zim_file() to find available entries,
or browse_namespace() to explore the file structure.
```

---

## Important Notes and Limitations

### Content Length Requirements

- The `max_content_length` parameter for `get_zim_entry` must be at least 1000 characters
- Content longer than the specified limit will be truncated with a note showing the total character count

### Search Behavior

- Search results may include articles that contain the search terms in various contexts
- Results are ranked by relevance but may not always be directly related to the primary meaning of the search term
- Search snippets provide a preview of the content but may not show the exact location where the search term appears

### File Format Support

- Currently supports ZIM files (Zeno IMproved format)
- Tested with Wikipedia ZIM files (e.g., `wikipedia_en_100_2025-08.zim`)
- File paths must be properly escaped in JSON (use `\\` for Windows paths)

---

## Multi-Server Instance Management

OpenZIM MCP includes advanced multi-server instance tracking and conflict detection to ensure reliable operation when multiple server instances are running.

### Instance Tracking Features

- **Automatic Instance Registration**: Each server instance is automatically registered with a unique process ID and configuration hash
- **Conflict Detection**: Detects when multiple servers with different configurations are accessing the same directories
- **Stale Instance Cleanup**: Automatically identifies and cleans up orphaned instance files from terminated processes
- **Configuration Validation**: Ensures all server instances use compatible configurations

### Conflict Types

1. **Configuration Mismatch**: Multiple servers with different settings accessing the same directories
2. **Multiple Instances**: Multiple servers running simultaneously (may cause confusion)
3. **Stale Instances**: Orphaned instance files from terminated processes

### Automatic Conflict Warnings

OpenZIM MCP automatically includes conflict warnings in search results and file listings when issues are detected:

```plain
 **Server Conflict Detected**
 Configuration mismatch with server PID 12345. Search results may be inconsistent.
 Use 'resolve_server_conflicts()' to fix these issues.
```

### Best Practices

- Use `diagnose_server_state()` regularly to check for conflicts
- Run `resolve_server_conflicts()` to clean up stale instances
- Ensure all server instances use the same configuration when accessing shared directories
- Monitor server health with `get_server_health()` for instance tracking information

---

## Configuration

OpenZIM MCP supports configuration through environment variables with the `OPENZIM_MCP_` prefix:

```bash
# Cache configuration
export OPENZIM_MCP_CACHE__ENABLED=true
export OPENZIM_MCP_CACHE__MAX_SIZE=200
export OPENZIM_MCP_CACHE__TTL_SECONDS=7200

# Content configuration
export OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH=200000
export OPENZIM_MCP_CONTENT__SNIPPET_LENGTH=2000
export OPENZIM_MCP_CONTENT__DEFAULT_SEARCH_LIMIT=20

# Logging configuration
export OPENZIM_MCP_LOGGING__LEVEL=DEBUG
export OPENZIM_MCP_LOGGING__FORMAT="%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Server configuration
export OPENZIM_MCP_SERVER_NAME=my_openzim_mcp_server
```

### Configuration Options

| Setting | Default | Description |
|---------|---------|-------------|
| `OPENZIM_MCP_CACHE__ENABLED` | `true` | Enable/disable caching |
| `OPENZIM_MCP_CACHE__MAX_SIZE` | `100` | Maximum cache entries |
| `OPENZIM_MCP_CACHE__TTL_SECONDS` | `3600` | Cache TTL in seconds |
| `OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH` | `100000` | Max content length |
| `OPENZIM_MCP_CONTENT__SNIPPET_LENGTH` | `1000` | Max snippet length |
| `OPENZIM_MCP_CONTENT__DEFAULT_SEARCH_LIMIT` | `10` | Default search result limit |
| `OPENZIM_MCP_LOGGING__LEVEL` | `INFO` | Logging level |
| `OPENZIM_MCP_LOGGING__FORMAT` | `%(asctime)s - %(name)s - %(levelname)s - %(message)s` | Log message format |
| `OPENZIM_MCP_SERVER_NAME` | `openzim-mcp` | Server instance name |

---

## Security Features

- **Path Traversal Protection**: Secure path validation prevents access outside allowed directories
- **Input Sanitization**: All user inputs are validated and sanitized
- **Resource Management**: Proper cleanup of ZIM archive resources
- **Error Handling**: Sanitized error messages prevent information disclosure
- **Type Safety**: Full type annotations prevent type-related vulnerabilities

---

## Performance Features

- **Intelligent Caching**: LRU cache with TTL for frequently accessed content
- **Resource Pooling**: Efficient ZIM archive management
- **Optimized Content Processing**: Fast HTML to text conversion
- **Lazy Loading**: Components initialized only when needed
- **Memory Management**: Proper cleanup and resource management

---

## Testing

The project includes comprehensive testing with 80%+ coverage using both mock data and real ZIM files:

### Test Categories

- **Unit Tests**: Individual component testing with mocks
- **Integration Tests**: End-to-end functionality testing with real ZIM files
- **Security Tests**: Path traversal and input validation testing
- **Performance Tests**: Cache and resource management testing
- **Format Compatibility**: Testing with various ZIM file formats and versions
- **Error Handling**: Testing with invalid and malformed ZIM files

### Test Infrastructure

OpenZIM MCP uses a hybrid testing approach:

1. **Mock-based tests**: Fast unit tests using mocked libzim components
2. **Real ZIM file tests**: Integration tests using official zim-testing-suite files
3. **Automatic test data management**: Download and organize test files as needed

### Test Data Sources

- **Built-in test data**: Basic test files included in the repository
- **zim-testing-suite integration**: Official test files from the OpenZIM project
- **Environment variable support**: `ZIM_TEST_DATA_DIR` for custom test data locations

```bash
# Run tests with coverage report
make test-cov

# View coverage report
open htmlcov/index.html

# Run comprehensive tests with real ZIM files
make test-with-zim-data
```

### Test Markers

Tests are organized with pytest markers:

- `@pytest.mark.requires_zim_data`: Tests requiring ZIM test data files
- `@pytest.mark.integration`: Integration tests
- `@pytest.mark.slow`: Long-running tests

---

## Monitoring

OpenZIM MCP provides built-in monitoring capabilities:

- **Health Checks**: Server health and status monitoring
- **Cache Metrics**: Cache hit rates and performance statistics
- **Structured Logging**: JSON-formatted logs for easy parsing
- **Error Tracking**: Comprehensive error logging and tracking

---

## Versioning

This project uses [Semantic Versioning](https://semver.org/) with automated version management through [release-please](https://github.com/googleapis/release-please).

### Automated Releases

Version bumps and releases are automated based on [Conventional Commits](https://www.conventionalcommits.org/):

- **`feat:`** - New features (minor version bump)
- **`fix:`** - Bug fixes (patch version bump)
- **`feat!:`** or **`BREAKING CHANGE:`** - Breaking changes (major version bump)
- **`perf:`** - Performance improvements (patch version bump)
- **`docs:`**, **`style:`**, **`refactor:`**, **`test:`**, **`chore:`** - No version bump

### Release Process

The project uses an **improved, consolidated release system** with automatic validation:

1. **Automatic** (Recommended): Push conventional commits → Release Please creates PR → Merge PR → Automatic release
2. **Manual**: Use GitHub Actions UI for direct control over releases
3. **Emergency**: Push tags directly for critical fixes

**Key Features:**

- **Zero-touch releases** from main branch
- **Automatic version synchronization** validation
- **Comprehensive testing** before every release
- **Improved error handling** and rollback capabilities
- **Branch protection** prevents broken releases

For detailed instructions, see [Release Process Guide](docs/RELEASE_PROCESS_GUIDE.md).

### Commit Message Format

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

**Examples:**

```bash
feat: add search suggestions endpoint
fix: resolve path traversal vulnerability
feat!: change API response format
docs: update installation instructions
```

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests (`make check`)
5. **Use conventional commit messages** (`git commit -m 'feat: add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Development Guidelines

- Follow PEP 8 style guidelines
- Add type hints to all functions
- Write tests for new functionality
- Update documentation as needed
- **Use conventional commit messages** for automatic versioning
- Ensure all tests pass before submitting

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## Acknowledgments

- [Kiwix](https://www.kiwix.org/) for the ZIM format and libzim library
- [MCP](https://modelcontextprotocol.io/) for the Model Context Protocol
- The open-source community for the excellent libraries used in this project

---

Made with ❤️ by [Cameron Rye](https://rye.dev)
