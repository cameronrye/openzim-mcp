# Configuration Guide

Advanced configuration options and environment variables for OpenZIM MCP.

## Overview

OpenZIM MCP supports extensive configuration through environment variables, allowing you to customize behavior for different deployment scenarios.

## Configuration Methods

### Environment Variables

All configuration uses the `OPENZIM_MCP_` prefix:

```bash
export OPENZIM_MCP_CACHE__ENABLED=true
export OPENZIM_MCP_CACHE__MAX_SIZE=200
```

### Configuration File (Future)

Configuration file support is planned for future releases.

## Tool Mode Configuration

OpenZIM MCP supports two operational modes:

```bash
# Tool mode (default: simple)
# Options: simple, advanced
export OPENZIM_MCP_TOOL_MODE=simple
```

**Simple Mode (default)**: Provides 1 intelligent tool (`zim_query`) that accepts natural language queries. Best for most LLMs and use cases.

**Advanced Mode**: Exposes all 15 specialized MCP tools for maximum control. Useful when you need fine-grained control over ZIM operations.

See the [Simple Mode Guide](../docs/SIMPLE_MODE_GUIDE.md) for detailed information about the differences between modes.

## Cache Configuration

### Basic Cache Settings

```bash
# Enable/disable caching (default: true)
export OPENZIM_MCP_CACHE__ENABLED=true

# Maximum cache entries (default: 100)
export OPENZIM_MCP_CACHE__MAX_SIZE=200

# Cache TTL in seconds (default: 3600 = 1 hour)
export OPENZIM_MCP_CACHE__TTL_SECONDS=7200
```

### Cache Performance Tuning

**For Development**:

```bash
export OPENZIM_MCP_CACHE__MAX_SIZE=50
export OPENZIM_MCP_CACHE__TTL_SECONDS=1800  # 30 minutes
```

**For Production**:

```bash
export OPENZIM_MCP_CACHE__MAX_SIZE=500
export OPENZIM_MCP_CACHE__TTL_SECONDS=14400  # 4 hours
```

**For High-Memory Systems**:

```bash
export OPENZIM_MCP_CACHE__MAX_SIZE=1000
export OPENZIM_MCP_CACHE__TTL_SECONDS=28800  # 8 hours
```

## Content Configuration

### Content Length Limits

```bash
# Maximum content length for get_zim_entry (default: 100000)
export OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH=200000

# Maximum snippet length for search results (default: 1000)
export OPENZIM_MCP_CONTENT__SNIPPET_LENGTH=2000

# Default search result limit (default: 10)
export OPENZIM_MCP_CONTENT__DEFAULT_SEARCH_LIMIT=20
```

### Content Processing

```bash
# Enable HTML to text conversion (default: true)
export OPENZIM_MCP_CONTENT__CONVERT_HTML=true

# Preserve formatting in text conversion (default: true)
export OPENZIM_MCP_CONTENT__PRESERVE_FORMATTING=true
```

## Logging Configuration

### Log Levels

```bash
# Logging level (default: INFO)
# Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
export OPENZIM_MCP_LOGGING__LEVEL=DEBUG

# Log format (default: structured format)
export OPENZIM_MCP_LOGGING__FORMAT="%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Enable JSON logging (default: false)
export OPENZIM_MCP_LOGGING__JSON=true
```

### Development Logging

```bash
export OPENZIM_MCP_LOGGING__LEVEL=DEBUG
export OPENZIM_MCP_LOGGING__FORMAT="%(levelname)s: %(message)s"
```

### Production Logging

```bash
export OPENZIM_MCP_LOGGING__LEVEL=INFO
export OPENZIM_MCP_LOGGING__JSON=true
export OPENZIM_MCP_LOGGING__FORMAT="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

## Server Configuration

### Server Identity

```bash
# Server instance name (default: openzim-mcp)
export OPENZIM_MCP_SERVER_NAME=my_openzim_server

# Server description (optional)
export OPENZIM_MCP_SERVER_DESCRIPTION="Production OpenZIM MCP Server"
```

### Performance Settings

```bash
# Enable performance monitoring (default: true)
export OPENZIM_MCP_SERVER__ENABLE_MONITORING=true

# Request timeout in seconds (default: 30)
export OPENZIM_MCP_SERVER__REQUEST_TIMEOUT=60

# Maximum concurrent operations (default: 10)
export OPENZIM_MCP_SERVER__MAX_CONCURRENT=20
```

## Security Configuration

### Path Security

```bash
# Enable strict path validation (default: true)
export OPENZIM_MCP_SECURITY__STRICT_PATHS=true

# Maximum path depth (default: 10)
export OPENZIM_MCP_SECURITY__MAX_PATH_DEPTH=15

# Allowed file extensions (default: .zim)
export OPENZIM_MCP_SECURITY__ALLOWED_EXTENSIONS=".zim,.zimaa"
```

### Input Validation

```bash
# Maximum query length (default: 1000)
export OPENZIM_MCP_SECURITY__MAX_QUERY_LENGTH=2000

# Enable input sanitization (default: true)
export OPENZIM_MCP_SECURITY__SANITIZE_INPUT=true
```

## Instance Management

### Multi-Instance Settings

```bash
# Enable instance tracking (default: true)
export OPENZIM_MCP_INSTANCE__TRACKING_ENABLED=true

# Instance file directory (default: ~/.openzim_mcp_instances)
export OPENZIM_MCP_INSTANCE__TRACKING_DIR="/var/lib/openzim_mcp"

# Conflict detection sensitivity (default: strict)
# Options: strict, moderate, relaxed
export OPENZIM_MCP_INSTANCE__CONFLICT_DETECTION=moderate

# Heartbeat interval in seconds (default: 60)
export OPENZIM_MCP_INSTANCE__HEARTBEAT_INTERVAL=30

# Instance cleanup interval in seconds (default: 300)
export OPENZIM_MCP_INSTANCE__CLEANUP_INTERVAL=600

# Maximum stale instance age in seconds (default: 3600)
export OPENZIM_MCP_INSTANCE__MAX_STALE_AGE=7200
```

### Instance Tracking Profiles

**Production Environment**:

```bash
export OPENZIM_MCP_INSTANCE__TRACKING_ENABLED=true
export OPENZIM_MCP_INSTANCE__CONFLICT_DETECTION=strict
export OPENZIM_MCP_INSTANCE__HEARTBEAT_INTERVAL=60
export OPENZIM_MCP_INSTANCE__CLEANUP_INTERVAL=300
```

**Development Environment**:

```bash
export OPENZIM_MCP_INSTANCE__TRACKING_ENABLED=true
export OPENZIM_MCP_INSTANCE__CONFLICT_DETECTION=relaxed
export OPENZIM_MCP_INSTANCE__HEARTBEAT_INTERVAL=120
export OPENZIM_MCP_INSTANCE__CLEANUP_INTERVAL=600
```

**High-Availability Environment**:

```bash
export OPENZIM_MCP_INSTANCE__TRACKING_ENABLED=true
export OPENZIM_MCP_INSTANCE__CONFLICT_DETECTION=strict
export OPENZIM_MCP_INSTANCE__HEARTBEAT_INTERVAL=30
export OPENZIM_MCP_INSTANCE__CLEANUP_INTERVAL=120
export OPENZIM_MCP_INSTANCE__MAX_STALE_AGE=1800
```

## Smart Retrieval Configuration

### Smart Retrieval Settings

```bash
# Enable/disable smart retrieval (default: true)
export OPENZIM_MCP_SMART_RETRIEVAL__ENABLED=true

# Path mapping cache size (default: 1000)
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_SIZE=2000

# Cache TTL in seconds (default: 3600)
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_TTL=7200

# Fallback search limit (default: 10)
export OPENZIM_MCP_SMART_RETRIEVAL__SEARCH_LIMIT=20

# Minimum confidence threshold (default: 0.7)
export OPENZIM_MCP_SMART_RETRIEVAL__MIN_CONFIDENCE=0.8

# Enable pattern learning (default: true)
export OPENZIM_MCP_SMART_RETRIEVAL__PATTERN_LEARNING=true

# Maximum fallback attempts (default: 5)
export OPENZIM_MCP_SMART_RETRIEVAL__MAX_ATTEMPTS=10
```

### Smart Retrieval Profiles

**High-Performance Profile**:

```bash
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_SIZE=5000
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_TTL=14400
export OPENZIM_MCP_SMART_RETRIEVAL__SEARCH_LIMIT=50
export OPENZIM_MCP_SMART_RETRIEVAL__MIN_CONFIDENCE=0.6
export OPENZIM_MCP_SMART_RETRIEVAL__MAX_ATTEMPTS=15
```

**Memory-Constrained Profile**:

```bash
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_SIZE=500
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_TTL=1800
export OPENZIM_MCP_SMART_RETRIEVAL__SEARCH_LIMIT=5
export OPENZIM_MCP_SMART_RETRIEVAL__MIN_CONFIDENCE=0.8
export OPENZIM_MCP_SMART_RETRIEVAL__MAX_ATTEMPTS=3
```

**Development Profile**:

```bash
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_SIZE=1000
export OPENZIM_MCP_SMART_RETRIEVAL__CACHE_TTL=3600
export OPENZIM_MCP_SMART_RETRIEVAL__SEARCH_LIMIT=15
export OPENZIM_MCP_SMART_RETRIEVAL__MIN_CONFIDENCE=0.7
export OPENZIM_MCP_SMART_RETRIEVAL__PATTERN_LEARNING=true
```

## Complete Configuration Reference

| Setting | Default | Description | Valid Values |
|---------|---------|-------------|--------------|
| **Tool Mode** |
| `TOOL_MODE` | `simple` | Tool operation mode | `simple`, `advanced` |
| **Cache Settings** |
| `CACHE__ENABLED` | `true` | Enable caching | `true`, `false` |
| `CACHE__MAX_SIZE` | `100` | Max cache entries | `1-10000` |
| `CACHE__TTL_SECONDS` | `3600` | Cache TTL | `60-86400` |
| **Content Settings** |
| `CONTENT__MAX_CONTENT_LENGTH` | `100000` | Max content length | `1000-1000000` |
| `CONTENT__SNIPPET_LENGTH` | `1000` | Max snippet length | `100-10000` |
| `CONTENT__DEFAULT_SEARCH_LIMIT` | `10` | Default search limit | `1-100` |
| `CONTENT__CONVERT_HTML` | `true` | Convert HTML to text | `true`, `false` |
| `CONTENT__PRESERVE_FORMATTING` | `true` | Preserve text formatting | `true`, `false` |
| **Logging Settings** |
| `LOGGING__LEVEL` | `INFO` | Log level | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `LOGGING__JSON` | `false` | JSON log format | `true`, `false` |
| `LOGGING__FORMAT` | (structured) | Log message format | Any valid format string |
| **Server Settings** |
| `SERVER_NAME` | `openzim-mcp` | Server instance name | Any string |
| `SERVER_DESCRIPTION` | (empty) | Server description | Any string |
| `SERVER__ENABLE_MONITORING` | `true` | Enable monitoring | `true`, `false` |
| `SERVER__REQUEST_TIMEOUT` | `30` | Request timeout (sec) | `5-300` |
| `SERVER__MAX_CONCURRENT` | `10` | Max concurrent ops | `1-100` |
| **Security Settings** |
| `SECURITY__STRICT_PATHS` | `true` | Strict path validation | `true`, `false` |
| `SECURITY__MAX_PATH_DEPTH` | `10` | Max path depth | `1-50` |
| `SECURITY__ALLOWED_EXTENSIONS` | `.zim` | Allowed file extensions | Comma-separated list |
| `SECURITY__MAX_QUERY_LENGTH` | `1000` | Max query length | `10-10000` |
| `SECURITY__SANITIZE_INPUT` | `true` | Input sanitization | `true`, `false` |
| **Instance Settings** |
| `INSTANCE__TRACKING_ENABLED` | `true` | Instance tracking | `true`, `false` |
| `INSTANCE__TRACKING_DIR` | `~/.openzim_mcp_instances` | Tracking directory | Any valid path |
| `INSTANCE__CONFLICT_DETECTION` | `strict` | Conflict detection | `strict`, `moderate`, `relaxed` |
| `INSTANCE__HEARTBEAT_INTERVAL` | `60` | Heartbeat interval (sec) | `30-300` |
| `INSTANCE__CLEANUP_INTERVAL` | `300` | Cleanup interval (sec) | `60-3600` |
| `INSTANCE__MAX_STALE_AGE` | `3600` | Max stale age (sec) | `300-86400` |
| **Smart Retrieval Settings** |
| `SMART_RETRIEVAL__ENABLED` | `true` | Enable smart retrieval | `true`, `false` |
| `SMART_RETRIEVAL__CACHE_SIZE` | `1000` | Path cache size | `100-10000` |
| `SMART_RETRIEVAL__CACHE_TTL` | `3600` | Cache TTL (sec) | `300-86400` |
| `SMART_RETRIEVAL__SEARCH_LIMIT` | `10` | Fallback search limit | `1-100` |
| `SMART_RETRIEVAL__MIN_CONFIDENCE` | `0.7` | Min confidence threshold | `0.1-1.0` |
| `SMART_RETRIEVAL__PATTERN_LEARNING` | `true` | Enable pattern learning | `true`, `false` |
| `SMART_RETRIEVAL__MAX_ATTEMPTS` | `5` | Max fallback attempts | `1-20` |

## Configuration Profiles

### Development Profile

```bash
# Development configuration
export OPENZIM_MCP_LOGGING__LEVEL=DEBUG
export OPENZIM_MCP_CACHE__MAX_SIZE=50
export OPENZIM_MCP_CACHE__TTL_SECONDS=1800
export OPENZIM_MCP_CONTENT__DEFAULT_SEARCH_LIMIT=5
export OPENZIM_MCP_SERVER__REQUEST_TIMEOUT=60
```

### Production Profile

```bash
# Production configuration
export OPENZIM_MCP_LOGGING__LEVEL=INFO
export OPENZIM_MCP_LOGGING__JSON=true
export OPENZIM_MCP_CACHE__MAX_SIZE=500
export OPENZIM_MCP_CACHE__TTL_SECONDS=14400
export OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH=200000
export OPENZIM_MCP_SERVER__MAX_CONCURRENT=20
export OPENZIM_MCP_SECURITY__STRICT_PATHS=true
```

### High-Performance Profile

```bash
# High-performance configuration
export OPENZIM_MCP_CACHE__MAX_SIZE=1000
export OPENZIM_MCP_CACHE__TTL_SECONDS=28800
export OPENZIM_MCP_CONTENT__DEFAULT_SEARCH_LIMIT=50
export OPENZIM_MCP_SERVER__MAX_CONCURRENT=50
export OPENZIM_MCP_SERVER__REQUEST_TIMEOUT=120
```

### Memory-Constrained Profile

```bash
# Memory-constrained configuration
export OPENZIM_MCP_CACHE__MAX_SIZE=25
export OPENZIM_MCP_CACHE__TTL_SECONDS=900
export OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH=50000
export OPENZIM_MCP_CONTENT__SNIPPET_LENGTH=500
export OPENZIM_MCP_SERVER__MAX_CONCURRENT=5
```

## Configuration Management

### Setting Configuration

**Linux/macOS**:

```bash
# Set in shell profile (.bashrc, .zshrc, etc.)
echo 'export OPENZIM_MCP_CACHE__MAX_SIZE=200' >> ~/.bashrc
source ~/.bashrc
```

**Windows**:

```powershell
# Set environment variable
$env:OPENZIM_MCP_CACHE__MAX_SIZE = "200"

# Or set permanently
[Environment]::SetEnvironmentVariable("OPENZIM_MCP_CACHE__MAX_SIZE", "200", "User")
```

### Configuration Scripts

Create configuration scripts for different environments:

**config-dev.sh**:

```bash
#!/bin/bash
export OPENZIM_MCP_LOGGING__LEVEL=DEBUG
export OPENZIM_MCP_CACHE__MAX_SIZE=50
# ... other dev settings
```

**config-prod.sh**:

```bash
#!/bin/bash
export OPENZIM_MCP_LOGGING__LEVEL=INFO
export OPENZIM_MCP_CACHE__MAX_SIZE=500
# ... other prod settings
```

Usage:

```bash
source config-dev.sh

# Standard installation
openzim-mcp /path/to/zim/files

# Development installation
uv run python -m openzim_mcp /path/to/zim/files
```

## Monitoring Configuration

### Health Check Settings

```bash
# Enable detailed health checks (default: true)
export OPENZIM_MCP_MONITORING__DETAILED_HEALTH=true

# Health check interval in seconds (default: 60)
export OPENZIM_MCP_MONITORING__HEALTH_INTERVAL=30

# Enable performance metrics (default: true)
export OPENZIM_MCP_MONITORING__PERFORMANCE_METRICS=true
```

### Metrics Collection

```bash
# Enable cache metrics (default: true)
export OPENZIM_MCP_METRICS__CACHE_ENABLED=true

# Enable request metrics (default: true)
export OPENZIM_MCP_METRICS__REQUESTS_ENABLED=true

# Metrics retention period in seconds (default: 3600)
export OPENZIM_MCP_METRICS__RETENTION_PERIOD=7200
```

## Configuration Validation

### Validate Configuration

Use the server diagnostics to validate your configuration:

```bash
# In your MCP client:
"Diagnose the server state and validate configuration"
```

This will check for:

- Invalid configuration values
- Conflicting settings
- Performance recommendations
- Security warnings

### Common Validation Issues

1. **Cache size too large**: May cause memory issues
2. **TTL too short**: Reduces cache effectiveness
3. **Content length too high**: May cause timeouts
4. **Concurrent operations too high**: May overwhelm system

---

**Need help with configuration?** Check the [Performance Optimization Guide](Performance-Optimization-Guide) for tuning recommendations.
