# LLM ZIM File Format Mastery Manual

## Table of Contents

1. [ZIM Format Fundamentals](#1-zim-format-fundamentals)
2. [Technical Implementation Details](#2-technical-implementation-details)
3. [Practical Usage Patterns](#3-practical-usage-patterns)
4. [LLM-Specific Guidance](#4-llm-specific-guidance)
5. [Hands-on Examples](#5-hands-on-examples)

---

## 1. ZIM Format Fundamentals

### 1.1 Overview

ZIM (Zeno IMproved) is an open file format designed for storing web content offline. It's optimized for compression and fast random access, making it ideal for distributing large content collections like Wikipedia.

### 1.2 File Structure

A ZIM file consists of:

- **Header**: Contains metadata and pointers to other sections
- **MIME Type List**: Defines content types used in the file
- **Path Pointer List**: Ordered list of entry locations by path
- **Title Pointer List**: Ordered list of entry locations by title
- **Directory Entries**: Metadata for each piece of content
- **Cluster Pointer List**: Locations of compressed data clusters
- **Clusters**: Compressed content data

### 1.3 Header Specification

```
Offset | Length | Field Name      | Description
-------|--------|-----------------|----------------------------------
0      | 4      | magicNumber     | 0x44D495A (file format identifier)
4      | 2      | majorVersion    | Major version (6 for current format)
6      | 2      | minorVersion    | Minor version (0-3 for current)
8      | 16     | uuid            | Unique identifier for this archive
24     | 4      | entryCount      | Total number of entries
28     | 4      | clusterCount    | Total number of clusters
32     | 8      | pathPtrPos      | Position of path pointer list
40     | 8      | titlePtrPos     | Position of title pointer list
48     | 8      | clusterPtrPos   | Position of cluster pointer list
56     | 8      | mimeListPos     | Position of MIME type list
64     | 4      | mainPage        | Main page entry index (or 0xffffffff)
68     | 4      | layoutPage      | Layout page (deprecated, always 0xffffffff)
72     | 8      | checksumPos     | Position of MD5 checksum
```

### 1.4 Namespace System

ZIM uses a strict namespace system to organize content:

- **C (Content)**: User-facing articles and resources
  - Articles: Full HTML pages for display
  - Resources: CSS, images, JavaScript, fonts
- **M (Metadata)**: Archive metadata and configuration
- **W (Well-known)**: Standard entries like main page redirects
- **X (Search)**: Search indexes and content listings

### 1.5 Entry Types

**Content Entry Structure:**

```
Offset | Length | Field Name    | Description
-------|--------|---------------|----------------------------------
0      | 2      | mimetype      | MIME type index
2      | 1      | parameter len | Extra parameters length (must be 0)
3      | 1      | namespace     | Namespace character (C, M, W, X)
4      | 4      | revision      | Revision number (must be 0)
8      | 4      | cluster number| Cluster containing this entry
12     | 4      | blob number   | Blob number within cluster
16     | var    | path          | UTF-8 encoded path (zero-terminated)
var    | var    | title         | UTF-8 encoded title (zero-terminated)
```

**Redirect Entry Structure:**

```
Offset | Length | Field Name     | Description
-------|--------|----------------|----------------------------------
0      | 2      | mimetype       | 0xffff (indicates redirect)
2      | 1      | parameter len  | Extra parameters length (must be 0)
3      | 1      | namespace      | Namespace character
4      | 4      | revision       | Revision number (must be 0)
8      | 4      | redirect index | Target entry index
12     | var    | path           | UTF-8 encoded path (zero-terminated)
var    | var    | title          | UTF-8 encoded title (zero-terminated)
```

---

## 2. Technical Implementation Details

### 2.1 Encoding Standards

- **Character Encoding**: UTF-8 for all text content
- **Integer Encoding**: Little-endian unsigned integers
- **Path Encoding**: UTF-8, NOT URL-encoded (critical distinction)

### 2.2 Compression and Clusters

Clusters contain the actual content data and can be compressed:

**Cluster Information Byte:**

- Bits 0-3: Compression type
  - 1: No compression
  - 4: LZMA2 compression (XZ format)
  - 5: Zstandard compression
- Bit 4: Extended cluster flag
  - 0: Normal (4-byte offsets, <4GB content)
  - 1: Extended (8-byte offsets, >4GB content)

**Cluster Structure:**

```plain
Offset | Length      | Description
-------|-------------|----------------------------------
0      | 1           | Cluster information byte
1      | OFFSET_SIZE | Offset to first blob
...    | OFFSET_SIZE | Offset to nth blob
...    | OFFSET_SIZE | Offset to end of cluster (n+1 offsets total)
...    | variable    | Blob data
```

### 2.3 Index Structures

**Path Pointer List**: 8-byte offsets to directory entries, ordered by full path (`<namespace><path>`)
**Title Pointer List**: 4-byte indices into path pointer list, ordered by title (`<namespace><title>`)

### 2.4 Search Indexes (X Namespace)

- **X/fulltext/xapian**: Xapian full-text search database
- **X/title/xapian**: Xapian title search database
- **X/listing/titleOrdered/v0**: Binary list of all entries by title
- **X/listing/titleOrdered/v1**: Binary list of article entries by title

---

## 3. Practical Usage Patterns

### 3.1 Common Use Cases

- **Offline Wikipedia**: Complete Wikipedia dumps for offline access
- **Educational Content**: Textbooks, reference materials, course content
- **Documentation**: Software documentation, manuals, guides
- **Digital Libraries**: Books, journals, multimedia collections

### 3.2 Tools and Libraries

**Core Library:**

- **libzim**: C++ library for reading/writing ZIM files
- **Bindings**: Python, Java, JavaScript wrappers available

**Command-Line Tools:**

- **zimdump**: Extract and inspect ZIM file contents
- **zimcheck**: Validate ZIM file integrity and structure
- **zimsplit**: Split large ZIM files into chunks

**Readers:**

- **[Kiwix](https://www.kiwix.org/)**: Cross-platform ZIM reader with web interface
- **Browser extensions**: For online ZIM access
- **Mobile apps**: iOS/Android ZIM readers
- **OpenVIM**: Vim-based ZIM viewing standard for command-line access
- **OpenZIM MCP**: MCP server for AI model integration with advanced LLM features

**OpenZIM Ecosystem Resources:**

- **[OpenZIM Wiki](https://wiki.openzim.org/)**: Comprehensive documentation and specifications
- **[OpenZIM GitHub](https://github.com/openzim)**: Open source libraries, tools, and scrapers

### 3.3 Best Practices

- **Content Organization**: Use clear, hierarchical path structures
- **Compression**: Balance compression ratio vs. access speed
- **Indexing**: Include appropriate search indexes for content type
- **Metadata**: Provide comprehensive metadata in M namespace
- **Testing**: Always validate with zimcheck before distribution

---

## 4. LLM-Specific Guidance

### 4.1 Content Search Strategies

**Path vs. Title Search:**

- Use path search for exact URL-like lookups
- Use title search for human-readable content discovery
- Remember: paths are UTF-8 encoded, not URL-encoded

**Namespace-Aware Searching:**

```plain
Content lookup priority:
1. C namespace for user content
2. W namespace for well-known entries (main page, etc.)
3. M namespace for metadata
4. X namespace for search capabilities
```

**Handling Redirects:**
Always check if an entry is a redirect before accessing content:

```cpp
if (entry.isRedirect()) {
    entry = entry.getRedirectArticle();
}
```

### 4.2 Content Relationship Navigation

**Main Page Discovery:**

1. Check header.mainPage for main page entry index
2. Look for W/mainPage redirect entry
3. Fall back to first article in C namespace

**Link Resolution:**

- Links in HTML content use relative paths
- Convert HTML href attributes to ZIM paths
- Handle local anchors (#fragments) client-side

**Related Content:**

- Use title-ordered listings for browsing
- Leverage full-text search for content discovery
- Follow redirect chains to find canonical content

### 4.3 Information Extraction Methods

**Article Content:**

```cpp
// Get article HTML content
zim::Article article = file.getArticle(namespace, path);
std::string html = article.getData();
// Parse HTML to extract text, links, metadata
```

**Metadata Extraction:**

- Check M namespace for archive-level metadata
- Parse HTML meta tags in article content
- Use title vs. path differences for content categorization

**Search Index Utilization:**

- Use X/listing/titleOrdered/v1 for article-only browsing
- Implement full-text search with X/fulltext/xapian
- Use title search for auto-completion features

### 4.4 Smart Retrieval System (OpenZIM MCP Enhancement)

**Automatic Path Resolution:**

OpenZIM MCP implements an intelligent entry retrieval system that automatically handles common path encoding issues:

```plain
 Smart: get_zim_entry("A/Test Article")
   → Tries direct access first
   → Falls back to search if needed
   → Automatically finds "A/Test_Article"
   → Caches the mapping for future use
```

**Benefits for LLM Applications:**

- **Transparent Operation**: No need to understand ZIM path encoding complexities
- **Single API Call**: Eliminates manual search-first methodology
- **Automatic Fallback**: Handles spaces, underscores, URL encoding differences
- **Performance Caching**: Path mappings cached for repeated access
- **Clear Error Guidance**: Actionable suggestions when entries not found

**Supported Path Variations:**

```plain
Input Path          → Actual ZIM Path
"A/Test Article"    → "A/Test_Article"
"C/Café"           → "C/Caf%C3%A9"
"A/Some-Page"      → "A/Some_Page"
"C/Index.html"     → "C/index.html"
```

### 4.5 Common Pitfalls and Solutions

**Path Encoding Issues:**

```plain
 Wrong: Store URL-encoded paths like "foo%20bar.html"
 Correct: Store UTF-8 paths like "foo bar.html"
 Better: Use OpenZIM MCP smart retrieval (handles both automatically)
```

**Namespace Confusion:**

```plain
 Wrong: Looking for articles in M or X namespaces
 Correct: User content is always in C namespace
```

**Redirect Handling:**

```plain
 Wrong: Accessing redirect entry content directly
 Correct: Follow redirect to target entry first
```

**Version Compatibility:**

- Always check major/minor version in header
- Handle missing features gracefully in older versions
- Use appropriate cluster offset sizes (4 vs 8 bytes)

---

## 5. Hands-on Examples

### 5.1 Basic File Inspection

**Reading Header Information:**

```cpp
#include <zim/file.h>
#include <iostream>

zim::File zimFile("example.zim");
std::cout << "Entry count: " << zimFile.getCountArticles() << std::endl;
std::cout << "Main page: " << zimFile.getMainPage().getTitle() << std::endl;
```

**Listing All Entries:**

```cpp
for (auto it = zimFile.begin(); it != zimFile.end(); ++it) {
    std::cout << "Namespace: " << it->getNamespace()
              << ", Path: " << it->getUrl()
              << ", Title: " << it->getTitle() << std::endl;
}
```

### 5.2 Content Retrieval Examples

**Finding Article by Path:**

```cpp
try {
    zim::Article article = zimFile.getArticleByUrl('C', "index.html");
    if (article.isRedirect()) {
        article = article.getRedirectArticle();
    }
    std::cout << article.getData() << std::endl;
} catch (const zim::EntryNotFound& e) {
    std::cout << "Article not found" << std::endl;
}
```

**Finding Article by Title:**

```cpp
auto result = zimFile.findByTitle('C', "Wikipedia");
if (result != zimFile.end()) {
    std::cout << "Found: " << result->getUrl() << std::endl;
    std::cout << "Content: " << result->getData() << std::endl;
}
```

### 5.3 Search Implementation

**Title-based Search:**

```cpp
std::string searchTerm = "physics";
auto it = zimFile.findByTitle('C', searchTerm);
while (it != zimFile.end() &&
       it->getTitle().substr(0, searchTerm.length()) == searchTerm) {
    std::cout << "Match: " << it->getTitle() << std::endl;
    ++it;
}
```

### 5.4 Troubleshooting Guide

#### Problem: "Entry not found" errors

- Solution: Check namespace and path encoding
- Verify path is UTF-8, not URL-encoded
- Try both path and title searches

#### Problem: Garbled content

- Solution: Check MIME type and handle appropriately
- Ensure proper UTF-8 decoding for text content
- Verify cluster decompression is working

#### Problem: Slow access

- Solution: Use appropriate search method (path vs title)
- Cache frequently accessed entries
- Consider using search indexes for large datasets

#### Problem: Version compatibility issues

- Solution: Check major/minor version in header
- Handle extended clusters appropriately
- Fall back to older features when needed

---

## Quick Reference

### Key Constants

- Magic Number: `0x44D495A`
- Current Major Version: `6`
- Redirect MIME Type: `0xffff`
- No Main Page: `0xffffffff`

### Namespace Meanings

- `C`: Content (articles, resources)
- `M`: Metadata
- `W`: Well-known entries
- `X`: Search indexes

### Compression Types

- `1`: No compression
- `4`: LZMA2 (XZ)
- `5`: Zstandard

This manual provides the foundation for understanding and working with ZIM files effectively. Always refer to the official OpenZIM documentation for the most current specifications.
