# Performance Optimization Guide

Tips and techniques for optimizing OpenZIM MCP performance in production environments.

## Performance Overview

OpenZIM MCP is designed for high performance with intelligent caching, optimized ZIM operations, and efficient resource management. This guide helps you maximize performance for your specific use case.

## Advanced Performance Monitoring

### Comprehensive Health Monitoring

OpenZIM MCP includes enterprise-grade monitoring capabilities:

```json
{
  "name": "get_server_health"
}
```

**Detailed Health Response**:

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
    "size": 150,
    "max_size": 500,
    "hit_rate": 0.87,
    "total_hits": 8700,
    "total_misses": 1300,
    "evictions": 25,
    "memory_usage_mb": 45.2
  },
  "instance_tracking": {
    "active_instances": 1,
    "conflicts_detected": 0,
    "tracking_enabled": true
  },
  "request_metrics": {
    "total_requests": 10000,
    "successful_requests": 9950,
    "failed_requests": 50,
    "average_response_time_ms": 125,
    "p95_response_time_ms": 250,
    "p99_response_time_ms": 500
  },
  "smart_retrieval": {
    "enabled": true,
    "cache_hit_rate": 0.93,
    "fallback_success_rate": 0.87,
    "average_resolution_time_ms": 45
  }
}
```

### Advanced Diagnostics

```json
{
  "name": "diagnose_server_state"
}
```

**Performance Analysis Response**:

```json
{
  "performance_analysis": {
    "cache_efficiency": "excellent",
    "memory_usage": "normal",
    "response_times": "optimal",
    "smart_retrieval_performance": "good",
    "instance_management": "healthy"
  },
  "recommendations": [
    "Cache performance is optimal",
    "Consider increasing smart retrieval cache size",
    "Monitor memory usage trends"
  ],
  "bottlenecks_detected": [],
  "optimization_opportunities": [
    {
      "area": "cache_tuning",
      "impact": "medium",
      "suggestion": "Increase cache TTL for better hit rates"
    }
  ]
}
```

### Key Performance Indicators (KPIs)

#### Primary Metrics

1. **Cache Hit Rate**: Target >85% for optimal performance
2. **Smart Retrieval Hit Rate**: Target >90% for path resolution
3. **Average Response Time**: Target <100ms for search operations
4. **Memory Efficiency**: Monitor cache memory vs total memory
5. **Instance Health**: Zero conflicts in production

#### Secondary Metrics

1. **Request Success Rate**: Target >99.5%
2. **Fallback Success Rate**: Target >85% for smart retrieval
3. **Concurrent Request Handling**: Monitor queue depth
4. **ZIM File Access Patterns**: Track I/O efficiency
5. **Configuration Stability**: Monitor config hash changes

## Cache Optimization

### Cache Configuration

**Development Environment**:

```bash
export OPENZIM_MCP_CACHE__MAX_SIZE=50
export OPENZIM_MCP_CACHE__TTL_SECONDS=1800  # 30 minutes
```

**Production Environment**:

```bash
export OPENZIM_MCP_CACHE__MAX_SIZE=500
export OPENZIM_MCP_CACHE__TTL_SECONDS=14400  # 4 hours
```

**High-Memory Systems**:

```bash
export OPENZIM_MCP_CACHE__MAX_SIZE=1000
export OPENZIM_MCP_CACHE__TTL_SECONDS=28800  # 8 hours
```

## Monitoring and Alerting

### Real-Time Monitoring

**Continuous Health Monitoring**:

```bash
#!/bin/bash
# health_monitor.sh - Continuous health monitoring script

HEALTH_CHECK_INTERVAL=60  # seconds
LOG_FILE="/var/log/openzim-mcp/health.log"

while true; do
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    # Get health metrics
    HEALTH_DATA=$(curl -s -X POST http://localhost:8000/mcp \
        -H "Content-Type: application/json" \
        -d '{"name": "get_server_health"}')

    # Extract key metrics
    CACHE_HIT_RATE=$(echo "$HEALTH_DATA" | jq -r '.cache_performance.hit_rate')
    RESPONSE_TIME=$(echo "$HEALTH_DATA" | jq -r '.request_metrics.average_response_time_ms')
    MEMORY_USAGE=$(echo "$HEALTH_DATA" | jq -r '.cache_performance.memory_usage_mb')

    # Log metrics
    echo "$TIMESTAMP,cache_hit_rate:$CACHE_HIT_RATE,response_time:$RESPONSE_TIME,memory_mb:$MEMORY_USAGE" >> "$LOG_FILE"

    # Check thresholds and alert
    if (( $(echo "$CACHE_HIT_RATE < 0.7" | bc -l) )); then
        echo "ALERT: Low cache hit rate: $CACHE_HIT_RATE" | logger -t openzim-mcp
    fi

    if (( $(echo "$RESPONSE_TIME > 200" | bc -l) )); then
        echo "ALERT: High response time: ${RESPONSE_TIME}ms" | logger -t openzim-mcp
    fi

    sleep $HEALTH_CHECK_INTERVAL
done
```

### Performance Dashboards

**Grafana Dashboard Configuration** (Future):

```json
{
  "dashboard": {
    "title": "OpenZIM MCP Performance",
    "panels": [
      {
        "title": "Cache Hit Rate",
        "type": "stat",
        "targets": [
          {
            "expr": "openzim_cache_hit_rate",
            "legendFormat": "Hit Rate"
          }
        ]
      },
      {
        "title": "Response Times",
        "type": "graph",
        "targets": [
          {
            "expr": "openzim_response_time_ms",
            "legendFormat": "Response Time"
          }
        ]
      },
      {
        "title": "Memory Usage",
        "type": "graph",
        "targets": [
          {
            "expr": "openzim_memory_usage_mb",
            "legendFormat": "Memory MB"
          }
        ]
      }
    ]
  }
}
```

### Alerting Rules

**Performance Alert Thresholds**:

```yaml
# alerts.yml - Performance alerting configuration
groups:
  - name: openzim_mcp_performance
    rules:
      - alert: LowCacheHitRate
        expr: openzim_cache_hit_rate < 0.7
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "OpenZIM MCP cache hit rate is low"
          description: "Cache hit rate is {{ $value }}, below 70% threshold"

      - alert: HighResponseTime
        expr: openzim_response_time_ms > 200
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "OpenZIM MCP response time is high"
          description: "Average response time is {{ $value }}ms"

      - alert: MemoryUsageHigh
        expr: openzim_memory_usage_mb > 1000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "OpenZIM MCP memory usage is high"
          description: "Memory usage is {{ $value }}MB"

      - alert: InstanceConflict
        expr: openzim_instance_conflicts > 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "OpenZIM MCP instance conflicts detected"
          description: "{{ $value }} instance conflicts detected"
```

### Cache Strategy Optimization

**For Frequent Searches**:

- Increase cache size
- Longer TTL for stable content
- Monitor hit rates regularly

**For Memory-Constrained Systems**:

- Smaller cache size
- Shorter TTL
- Focus on most accessed content

### Cache Performance Patterns

```python
# Good: Reuse common queries
popular_topics = ["Biology", "Physics", "Chemistry"]
for topic in popular_topics:
    # These benefit from caching
    search_zim_file(zim_path, topic)

# Good: Sequential access for related content
base_article = get_zim_entry(zim_path, "C/Evolution")
related_links = extract_article_links(zim_path, "C/Evolution")
# Related articles likely to be cached
```

## Search Optimization

### Efficient Search Strategies

**Start Broad, Then Narrow**:

```python
# 1. Broad search first
results = search_zim_file(zim_path, "biology", limit=10)

# 2. Filter results programmatically
filtered = [r for r in results if "molecular" in r.title.lower()]

# 3. Get detailed content only for relevant results
for result in filtered[:3]:  # Limit to top 3
    content = get_zim_entry(zim_path, result.path)
```

**Use Appropriate Limits**:

```python
# Good: Reasonable limits
search_zim_file(zim_path, query, limit=10)  # For exploration
search_zim_file(zim_path, query, limit=5)   # For specific answers

# Avoid: Excessive limits
search_zim_file(zim_path, query, limit=100) # May cause timeouts
```

**Leverage Filters**:

```python
# More efficient than post-processing
search_with_filters(
    zim_path,
    query="evolution",
    namespace="C",           # Content only
    content_type="text/html", # HTML articles only
    limit=10
)
```

### Search Performance Tips

1. **Use Auto-Complete**: Get suggestions before full search
2. **Cache Popular Queries**: Repeated searches are fast
3. **Batch Related Searches**: Process similar queries together
4. **Monitor Search Patterns**: Optimize based on usage

## Content Retrieval Optimization

### Content Length Management

**For Previews**:

```python
preview = get_zim_entry(
    zim_path,
    entry_path,
    max_content_length=5000  # Quick preview
)
```

**For Full Reading**:

```python
full_content = get_zim_entry(
    zim_path,
    entry_path,
    max_content_length=100000  # Complete article
)
```

**For Analysis**:

```python
# Get structure first, then content
structure = get_article_structure(zim_path, entry_path)
if structure.word_count < 10000:  # Only for shorter articles
    content = get_zim_entry(zim_path, entry_path)
```

### Progressive Content Loading

```python
def load_content_progressively(entry_path):
    # 1. Get structure overview
    structure = get_article_structure(zim_path, entry_path)

    # 2. Show structure to user
    present_structure(structure)

    # 3. Load content based on user interest
    if user_wants_full_content():
        content = get_zim_entry(zim_path, entry_path)
    else:
        # Just show preview
        preview = get_zim_entry(zim_path, entry_path, max_content_length=2000)

    return content
```

## ZIM File Optimization

### File Selection

**For Development**:

- Use smaller ZIM files (100-500MB)
- Wikipedia "Top 100" or "Top 1000" editions
- Subject-specific collections

**For Production**:

- Choose appropriate content scope
- Balance file size vs. content coverage
- Consider multiple specialized ZIM files vs. one large file

### File Organization

```bash
# Good: Organized by purpose
~/zim-files/
├── reference/
│   ├── wikipedia_en_top_2025.zim
│   └── wiktionary_en_2025.zim
├── technical/
│   ├── stackoverflow_2025.zim
│   └── documentation_2025.zim
└── specialized/
    ├── medical_2025.zim
    └── legal_2025.zim
```

### Storage Optimization

1. **SSD Storage**: Faster random access for ZIM files
2. **Local Storage**: Avoid network-mounted ZIM files
3. **Sufficient Space**: Ensure adequate free space for operations
4. **Regular Cleanup**: Remove unused or outdated ZIM files

## System Resource Optimization

### Memory Management

**Monitor Memory Usage**:

```bash
# Check memory usage
ps aux | grep openzim_mcp
top -p $(pgrep -f openzim_mcp)
```

**Memory Configuration**:

```bash
# For systems with limited RAM (< 4GB)
export OPENZIM_MCP_CACHE__MAX_SIZE=25
export OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH=50000
export OPENZIM_MCP_SERVER__MAX_CONCURRENT=5

# For systems with ample RAM (> 8GB)
export OPENZIM_MCP_CACHE__MAX_SIZE=1000
export OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH=200000
export OPENZIM_MCP_SERVER__MAX_CONCURRENT=20
```

### CPU Optimization

**Concurrent Operations**:

```bash
# Adjust based on CPU cores
export OPENZIM_MCP_SERVER__MAX_CONCURRENT=10  # For 4-core systems
export OPENZIM_MCP_SERVER__MAX_CONCURRENT=20  # For 8-core systems
```

**Request Timeout**:

```bash
# Balance responsiveness vs. completion
export OPENZIM_MCP_SERVER__REQUEST_TIMEOUT=30   # Default
export OPENZIM_MCP_SERVER__REQUEST_TIMEOUT=60   # For complex operations
export OPENZIM_MCP_SERVER__REQUEST_TIMEOUT=120  # For large content
```

## Multi-Instance Optimization

### Instance Management

**Avoid Conflicts**:

- Use consistent configuration across instances
- Monitor for configuration mismatches
- Regular conflict resolution

**Load Distribution**:

- Different ZIM files per instance
- Specialized instances for different content types
- Geographic distribution for global access

### Conflict Resolution

```bash
# Regular maintenance
"Resolve server conflicts and clean up stale instances"
```

## Performance Tuning by Use Case

### Research Applications

```bash
# Optimize for deep content access
export OPENZIM_MCP_CACHE__MAX_SIZE=500
export OPENZIM_MCP_CACHE__TTL_SECONDS=21600  # 6 hours
export OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH=200000
export OPENZIM_MCP_CONTENT__DEFAULT_SEARCH_LIMIT=20
```

### Educational Applications

```bash
# Optimize for broad exploration
export OPENZIM_MCP_CACHE__MAX_SIZE=300
export OPENZIM_MCP_CACHE__TTL_SECONDS=7200   # 2 hours
export OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH=100000
export OPENZIM_MCP_CONTENT__DEFAULT_SEARCH_LIMIT=15
```

### Quick Reference Applications

```bash
# Optimize for fast responses
export OPENZIM_MCP_CACHE__MAX_SIZE=200
export OPENZIM_MCP_CACHE__TTL_SECONDS=3600   # 1 hour
export OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH=50000
export OPENZIM_MCP_CONTENT__DEFAULT_SEARCH_LIMIT=10
```

### High-Volume Applications

```bash
# Optimize for throughput
export OPENZIM_MCP_CACHE__MAX_SIZE=1000
export OPENZIM_MCP_CACHE__TTL_SECONDS=28800  # 8 hours
export OPENZIM_MCP_SERVER__MAX_CONCURRENT=30
export OPENZIM_MCP_SERVER__REQUEST_TIMEOUT=45
```

## Advanced Optimization Techniques

### Preloading Strategies

```python
# Preload popular content
popular_articles = [
    "C/Biology", "C/Physics", "C/Chemistry",
    "C/Mathematics", "C/Computer_science"
]

for article in popular_articles:
    # Preload into cache
    get_zim_entry(zim_path, article, max_content_length=10000)
    get_article_structure(zim_path, article)
```

### Batch Processing

```python
# Process related operations together
def process_topic_batch(topic_list):
    # Search for all topics first
    search_results = []
    for topic in topic_list:
        results = search_zim_file(zim_path, topic, limit=5)
        search_results.extend(results)

    # Then get content for all results
    content_results = []
    for result in search_results:
        content = get_zim_entry(zim_path, result.path)
        content_results.append(content)

    return content_results
```

### Smart Caching Patterns

```python
# Cache-friendly access patterns
def explore_topic_efficiently(main_topic):
    # 1. Get main article (cached)
    main_article = get_zim_entry(zim_path, f"C/{main_topic}")

    # 2. Get structure (cached)
    structure = get_article_structure(zim_path, f"C/{main_topic}")

    # 3. Get related links (cached)
    links = extract_article_links(zim_path, f"C/{main_topic}")

    # 4. Access related articles (likely cached due to common topics)
    related_content = []
    for link in links.internal_links[:5]:  # Top 5 only
        content = get_zim_entry(zim_path, link.path)
        related_content.append(content)

    return {
        "main": main_article,
        "structure": structure,
        "related": related_content
    }
```

## Performance Benchmarking

### Baseline Measurements

**Measure Current Performance**:

```bash
# Time operations
time search_operation
time content_retrieval
time structure_analysis
```

**Monitor Over Time**:

- Track cache hit rates daily
- Monitor response times
- Watch memory usage trends
- Analyze usage patterns

### Performance Targets

| Operation | Target Time | Good Performance | Excellent Performance |
|-----------|-------------|------------------|----------------------|
| Search (10 results) | < 2 seconds | < 1 second | < 500ms |
| Content Retrieval | < 3 seconds | < 1 second | < 500ms |
| Article Structure | < 1 second | < 500ms | < 200ms |
| Health Check | < 500ms | < 200ms | < 100ms |

### Optimization Checklist

- [ ] Cache hit rate > 70%
- [ ] Memory usage stable over time
- [ ] Response times within targets
- [ ] No memory leaks detected
- [ ] Appropriate cache size for workload
- [ ] Optimal content length limits
- [ ] Efficient search patterns
- [ ] Regular conflict resolution
- [ ] Monitoring in place
- [ ] Performance baselines established

## Performance Troubleshooting

### Common Performance Issues

**Slow Search Results**:

- Check cache hit rate
- Reduce search result limits
- Verify ZIM file integrity
- Monitor system resources

**High Memory Usage**:

- Reduce cache size
- Lower content length limits
- Check for memory leaks
- Restart server periodically

**Timeouts**:

- Increase request timeout
- Reduce concurrent operations
- Check system load
- Optimize query patterns

### Performance Debugging

```bash
# Enable debug logging
export OPENZIM_MCP_LOGGING__LEVEL=DEBUG

# Monitor resource usage
htop
iotop
```

---

**Need more help?** Check the [Configuration Guide](Configuration-Guide) for detailed settings and the [Troubleshooting Guide](Troubleshooting-Guide) for common issues.
