# Smart Retrieval System Guide

Comprehensive guide to OpenZIM MCP's intelligent entry retrieval system with automatic fallback and path mapping cache.

## 📋 Overview

The Smart Retrieval System is one of OpenZIM MCP's most powerful features, designed to handle the complexities of ZIM file path encoding automatically. It provides transparent, reliable access to ZIM entries regardless of path format inconsistencies.

## 🧠 How Smart Retrieval Works

### The Challenge

ZIM files often contain entries with inconsistent path encoding:
- Spaces vs underscores: `"Test Article"` vs `"Test_Article"`
- URL encoding: `"Café"` vs `"Caf%C3%A9"`
- Case variations: `"DNA"` vs `"dna"`
- Special characters: `"C++"` vs `"C%2B%2B"`

### The Solution

Smart Retrieval uses a multi-stage approach:

```
1. Direct Access Attempt
   ↓ (if fails)
2. Search-Based Fallback
   ↓
3. Path Mapping Cache
   ↓
4. Multiple Search Strategies
   ↓
5. Best Match Selection
   ↓
6. Cache Update
   ↓
7. Content Retrieval
```

## 🔄 Retrieval Process

### Stage 1: Direct Access

First, the system attempts direct access using the provided path:

```python
# Example: User requests "A/Test Article"
try:
    entry = zim_file.get_entry_by_path("A/Test Article")
    return entry.content
except EntryNotFound:
    # Proceed to fallback
    pass
```

### Stage 2: Path Mapping Cache Check

Check if we've seen this path before:

```python
# Check cache for known mapping
cached_path = path_cache.get("A/Test Article")
if cached_path:
    return zim_file.get_entry_by_path(cached_path)
```

### Stage 3: Search-Based Fallback

If direct access fails, multiple search strategies are employed:

#### Strategy 1: Exact Title Search
```python
# Search for exact title match
results = search_zim_file(query="Test Article", namespace="A")
```

#### Strategy 2: Normalized Search
```python
# Try with underscores
results = search_zim_file(query="Test_Article", namespace="A")
```

#### Strategy 3: URL Decoded Search
```python
# Try URL decoding
results = search_zim_file(query=url_decode("Test%20Article"), namespace="A")
```

#### Strategy 4: Fuzzy Matching
```python
# Fuzzy search for close matches
results = fuzzy_search(query="Test Article", threshold=0.8)
```

### Stage 4: Best Match Selection

The system evaluates search results using multiple criteria:

```python
def score_match(result, original_query):
    score = 0.0
    
    # Exact title match (highest priority)
    if result.title.lower() == original_query.lower():
        score += 1.0
    
    # Path similarity
    score += path_similarity(result.path, original_query)
    
    # Namespace match
    if result.namespace == expected_namespace:
        score += 0.5
    
    # Content relevance
    score += content_relevance(result.snippet, original_query)
    
    return score
```

### Stage 5: Cache Update

Successful mappings are cached for future use:

```python
# Cache the successful mapping
path_cache.set(
    key="A/Test Article",
    value="A/Test_Article",
    ttl=3600  # 1 hour
)
```

## 🗂️ Path Mapping Cache

### Cache Structure

The path mapping cache stores successful path resolutions:

```json
{
  "cache_entries": {
    "A/Test Article": {
      "resolved_path": "A/Test_Article",
      "timestamp": "2025-09-15T10:30:00Z",
      "hit_count": 15,
      "confidence": 1.0
    },
    "C/Café": {
      "resolved_path": "C/Caf%C3%A9",
      "timestamp": "2025-09-15T10:25:00Z",
      "hit_count": 3,
      "confidence": 0.95
    }
  },
  "statistics": {
    "total_entries": 2,
    "hit_rate": 0.87,
    "cache_size_mb": 0.5
  }
}
```

### Cache Management

#### Automatic Invalidation
- **TTL-based**: Entries expire after configured time
- **Size-based**: LRU eviction when cache is full
- **Confidence-based**: Low-confidence entries expire sooner

#### Cache Optimization
```python
# High-confidence entries get longer TTL
if confidence > 0.9:
    ttl = 7200  # 2 hours
elif confidence > 0.7:
    ttl = 3600  # 1 hour
else:
    ttl = 1800  # 30 minutes
```

## 🎯 Usage Examples

### Basic Usage

The Smart Retrieval System works transparently:

```json
{
  "name": "get_zim_entry",
  "arguments": {
    "zim_file_path": "/path/to/file.zim",
    "entry_path": "A/Test Article"
  }
}
```

**Response with Smart Retrieval**:
```
# Test Article

Requested Path: A/Test Article
Actual Path: A/Test_Article
Type: text/html
Retrieval Method: smart_fallback

## Content

This article demonstrates the smart retrieval system...
```

### Advanced Scenarios

#### Scenario 1: URL Encoded Paths
```json
{
  "name": "get_zim_entry",
  "arguments": {
    "entry_path": "C/Caf%C3%A9"
  }
}
```

**Smart Retrieval Process**:
1. Try direct: `C/Caf%C3%A9` ❌
2. Try decoded: `C/Café` ✅
3. Cache mapping: `C/Caf%C3%A9` → `C/Café`

#### Scenario 2: Space vs Underscore
```json
{
  "name": "get_zim_entry",
  "arguments": {
    "entry_path": "A/Machine Learning"
  }
}
```

**Smart Retrieval Process**:
1. Try direct: `A/Machine Learning` ❌
2. Try with underscores: `A/Machine_Learning` ✅
3. Cache mapping: `A/Machine Learning` → `A/Machine_Learning`

#### Scenario 3: Case Sensitivity
```json
{
  "name": "get_zim_entry",
  "arguments": {
    "entry_path": "C/dna"
  }
}
```

**Smart Retrieval Process**:
1. Try direct: `C/dna` ❌
2. Search with case variations: `DNA`, `Dna` ✅
3. Cache mapping: `C/dna` → `C/DNA`

## ⚡ Performance Optimizations

### Cache Hit Rates

Typical cache performance:
- **First access**: 0% hit rate (cache miss)
- **Subsequent access**: 95%+ hit rate
- **Similar paths**: 80%+ hit rate (pattern recognition)

### Performance Metrics

```json
{
  "smart_retrieval_stats": {
    "total_requests": 1000,
    "direct_hits": 650,
    "cache_hits": 280,
    "fallback_successes": 65,
    "failures": 5,
    "average_resolution_time_ms": 45,
    "cache_hit_rate": 0.93
  }
}
```

### Optimization Strategies

#### 1. Preload Common Patterns
```python
# Preload known path mappings
common_patterns = {
    " ": "_",           # Space to underscore
    "%20": "_",         # URL encoded space
    "%C3%A9": "é",      # URL encoded é
}
```

#### 2. Pattern Learning
```python
# Learn from successful mappings
def learn_pattern(original, resolved):
    pattern = extract_pattern(original, resolved)
    pattern_cache.add(pattern)
```

#### 3. Batch Processing
```python
# Process multiple paths efficiently
def resolve_paths_batch(paths):
    # Group by pattern
    # Process in parallel
    # Update cache in batch
```

## 🔧 Configuration

### Smart Retrieval Settings

```bash
# Enable/disable smart retrieval (default: true)
export OPENZIM_MCP_SMART_RETRIEVAL__ENABLED=true

# Path cache size (default: 1000)
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_SIZE=2000

# Cache TTL in seconds (default: 3600)
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_TTL=7200

# Fallback search limit (default: 10)
export OPENZIM_MCP_SMART_RETRIEVAL__SEARCH_LIMIT=20

# Confidence threshold (default: 0.7)
export OPENZIM_MCP_SMART_RETRIEVAL__MIN_CONFIDENCE=0.8
```

### Performance Tuning

#### High-Performance Profile
```bash
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_SIZE=5000
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_TTL=14400
export OPENZIM_MCP_SMART_RETRIEVAL__SEARCH_LIMIT=50
```

#### Memory-Constrained Profile
```bash
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_SIZE=500
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_TTL=1800
export OPENZIM_MCP_SMART_RETRIEVAL__SEARCH_LIMIT=5
```

## 📊 Monitoring and Diagnostics

### Health Monitoring

Check smart retrieval performance:

```json
{
  "name": "get_server_health"
}
```

**Response includes**:
```json
{
  "smart_retrieval": {
    "enabled": true,
    "cache_size": 1500,
    "cache_hit_rate": 0.93,
    "average_resolution_time_ms": 45,
    "fallback_success_rate": 0.87
  }
}
```

### Performance Analysis

```json
{
  "name": "diagnose_server_state"
}
```

**Smart Retrieval Diagnostics**:
```json
{
  "smart_retrieval_analysis": {
    "cache_efficiency": "excellent",
    "fallback_performance": "good",
    "common_patterns": [
      "space_to_underscore: 45%",
      "url_encoding: 25%",
      "case_variations: 20%"
    ],
    "recommendations": [
      "Cache performance is optimal",
      "Consider increasing cache size for better hit rates"
    ]
  }
}
```

## 🚨 Troubleshooting

### Common Issues

#### Issue: Low Cache Hit Rate
**Symptoms**: Slow response times, frequent fallback searches
**Causes**: 
- Cache size too small
- TTL too short
- Highly variable path patterns

**Solutions**:
```bash
# Increase cache size
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_SIZE=3000

# Increase TTL
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_TTL=7200
```

#### Issue: Fallback Failures
**Symptoms**: "Entry not found" errors for existing content
**Causes**:
- Search limit too low
- Confidence threshold too high
- Unusual path encoding

**Solutions**:
```bash
# Increase search limit
export OPENZIM_MCP_SMART_RETRIEVAL__SEARCH_LIMIT=30

# Lower confidence threshold
export OPENZIM_MCP_SMART_RETRIEVAL__MIN_CONFIDENCE=0.6
```

#### Issue: Slow Resolution Times
**Symptoms**: High average resolution times
**Causes**:
- Too many fallback searches
- Large search limits
- Cache misses

**Solutions**:
1. Monitor cache hit rates
2. Optimize search strategies
3. Preload common patterns

### Diagnostic Commands

#### Check Cache Status
```bash
# View cache statistics
curl -X POST http://localhost:8000/mcp \
  -d '{"name": "get_server_health"}' | \
  jq '.smart_retrieval'
```

#### Test Path Resolution
```bash
# Test specific path resolution
curl -X POST http://localhost:8000/mcp \
  -d '{"name": "get_zim_entry", "arguments": {"zim_file_path": "/path/to/file.zim", "entry_path": "A/Test Article"}}' | \
  grep "Retrieval Method"
```

---

**Want to optimize performance?** Check the [Performance Optimization Guide](Performance-Optimization-Guide) for advanced tuning strategies.
