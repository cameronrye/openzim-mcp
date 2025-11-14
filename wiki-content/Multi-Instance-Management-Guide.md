# Multi-Instance Management Guide

Advanced guide for managing multiple OpenZIM MCP server instances with conflict detection and resolution.

## Overview

OpenZIM MCP includes sophisticated multi-instance management capabilities that allow multiple server instances to run simultaneously while detecting and resolving conflicts automatically. This enterprise-grade feature ensures reliable operation in complex deployment scenarios.

## Instance Tracking System

### How It Works

The instance tracking system automatically:

1. **Registers each server instance** with unique process ID and configuration hash
2. **Monitors instance health** and detects when processes terminate
3. **Detects configuration conflicts** between multiple instances
4. **Provides cleanup utilities** for stale instance files
5. **Offers diagnostic tools** for troubleshooting multi-instance issues

### Instance Registration

When a server starts, it automatically registers itself:

```python
# Automatic registration on startup
instance = InstanceTracker.register_instance(
    config_hash="abc123def456...",
    allowed_directories=["/path/to/zim/files"],
    server_name="openzim-mcp"
)
```

**Instance Information Stored**:

- Process ID (PID)
- Configuration hash
- Allowed directories
- Start time and last heartbeat
- Server name and description

## Conflict Detection

### Types of Conflicts

#### 1. Configuration Mismatch

Multiple servers with different configurations accessing the same directories.

**Example Scenario**:

```bash
# Server 1
export OPENZIM_MCP_CACHE__MAX_SIZE=100
openzim-mcp /shared/zim/files

# Server 2 (different config)
export OPENZIM_MCP_CACHE__MAX_SIZE=200
openzim-mcp /shared/zim/files
```

**Detection**: Configuration hash comparison
**Severity**: High
**Impact**: Inconsistent behavior, cache conflicts

#### 2. Multiple Active Instances

Multiple servers running simultaneously on the same directories.

**Example Scenario**:

```bash
# Terminal 1
openzim-mcp /zim/files &

# Terminal 2 (same config, same directories)
openzim-mcp /zim/files &
```

**Detection**: Active process monitoring
**Severity**: Warning
**Impact**: Resource contention, potential confusion

#### 3. Stale Instance Files

Orphaned instance files from terminated processes.

**Example Scenario**:

- Server process crashes or is killed
- Instance file remains in tracking directory
- New server detects "ghost" instance

**Detection**: Process existence check
**Severity**: Low
**Impact**: False conflict warnings

### Conflict Detection Process

```
1. Server Startup
   ↓
2. Load Existing Instance Files
   ↓
3. Check Process Existence
   ↓
4. Compare Configurations
   ↓
5. Detect Directory Overlaps
   ↓
6. Generate Conflict Report
   ↓
7. Provide Resolution Recommendations
```

## Using Management Tools

### Check Server Health

Monitor instance tracking status:

```json
{
  "name": "get_server_health"
}
```

**Response includes**:

```json
{
  "instance_tracking": {
    "active_instances": 2,
    "conflicts_detected": 1,
    "current_instance_id": "server_12345",
    "tracking_enabled": true
  }
}
```

### Diagnose Server State

Get comprehensive diagnostics:

```json
{
  "name": "diagnose_server_state"
}
```

**Conflict Information**:

```json
{
  "conflicts": [
    {
      "type": "configuration_mismatch",
      "instance": {
        "pid": 67890,
        "server_name": "openzim-mcp",
        "config_hash": "different_hash...",
        "directories": ["/shared/zim/files"]
      },
      "severity": "high",
      "details": "Different cache configuration detected"
    }
  ]
}
```

### Resolve Conflicts

Automatically clean up and resolve issues:

```json
{
  "name": "resolve_server_conflicts"
}
```

**Cleanup Actions**:

```json
{
  "cleanup_results": {
    "stale_instances_removed": 2,
    "files_cleaned": [
      "/home/user/.openzim_mcp_instances/server_99999.json"
    ]
  },
  "actions_taken": [
    "Removed 2 stale instance files",
    "Validated current instance configuration"
  ]
}
```

## Configuration

### Instance Tracking Settings

```bash
# Enable/disable instance tracking (default: true)
export OPENZIM_MCP_INSTANCE__TRACKING_ENABLED=true

# Custom tracking directory (default: ~/.openzim_mcp_instances)
export OPENZIM_MCP_INSTANCE__TRACKING_DIR="/var/lib/openzim_mcp"

# Conflict detection sensitivity (default: strict)
export OPENZIM_MCP_INSTANCE__CONFLICT_DETECTION=moderate
```

### Conflict Detection Levels

#### Strict (Default)

- Detects all configuration differences
- Reports multiple instances as conflicts
- Strict directory overlap checking

#### Moderate

- Ignores minor configuration differences
- Allows multiple instances with warnings
- Relaxed directory overlap rules

#### Relaxed

- Only reports major configuration conflicts
- Minimal instance overlap checking
- Suitable for development environments

## Best Practices

### Production Deployments

#### 1. Use Consistent Configuration

```bash
# Create shared configuration script
cat > /etc/openzim-mcp/config.sh << 'EOF'
export OPENZIM_MCP_CACHE__MAX_SIZE=500
export OPENZIM_MCP_CACHE__TTL_SECONDS=14400
export OPENZIM_MCP_LOGGING__LEVEL=INFO
export OPENZIM_MCP_INSTANCE__CONFLICT_DETECTION=strict
EOF

# Source in all deployments
source /etc/openzim-mcp/config.sh
openzim-mcp /path/to/zim/files
```

#### 2. Monitor Instance Health

```bash
# Regular health checks
curl -X POST http://localhost:8000/mcp \
  -d '{"name": "get_server_health"}' | \
  jq '.instance_tracking'
```

#### 3. Automated Conflict Resolution

```bash
# Scheduled cleanup (cron job)
0 */6 * * * curl -X POST http://localhost:8000/mcp \
  -d '{"name": "resolve_server_conflicts"}' > /dev/null
```

### Development Environments

#### 1. Use Relaxed Detection

```bash
export OPENZIM_MCP_INSTANCE__CONFLICT_DETECTION=relaxed
```

#### 2. Separate Tracking Directories

```bash
# Developer 1
export OPENZIM_MCP_INSTANCE__TRACKING_DIR="/tmp/dev1_instances"

# Developer 2
export OPENZIM_MCP_INSTANCE__TRACKING_DIR="/tmp/dev2_instances"
```

#### 3. Quick Cleanup

```bash
# Clean all instances for fresh start
rm -rf ~/.openzim_mcp_instances/*
```

## Troubleshooting

### Common Issues

#### Issue: False Conflict Warnings

**Symptoms**: Warnings about conflicts when only one server is running
**Cause**: Stale instance files from previous sessions
**Solution**:

```json
{"name": "resolve_server_conflicts"}
```

#### Issue: Configuration Mismatch Errors

**Symptoms**: High-severity conflicts between instances
**Cause**: Different environment variables or configuration
**Solution**:

1. Standardize configuration across instances
2. Use configuration management tools
3. Document configuration requirements

#### Issue: Instance Tracking Disabled

**Symptoms**: No conflict detection, missing health information
**Cause**: `OPENZIM_MCP_INSTANCE__TRACKING_ENABLED=false`
**Solution**:

```bash
export OPENZIM_MCP_INSTANCE__TRACKING_ENABLED=true
```

### Diagnostic Commands

#### Check Instance Files

```bash
ls -la ~/.openzim_mcp_instances/
cat ~/.openzim_mcp_instances/server_*.json
```

#### Verify Process Status

```bash
ps aux | grep openzim-mcp
```

#### Test Configuration Hash

```bash
# Compare configuration between instances
curl -X POST http://localhost:8000/mcp \
  -d '{"name": "get_server_configuration"}' | \
  jq '.configuration.config_hash'
```

## Advanced Configuration

### Custom Instance Tracking

For specialized deployments, you can customize instance tracking behavior:

```bash
# Extended heartbeat interval
export OPENZIM_MCP_INSTANCE__HEARTBEAT_INTERVAL=300

# Custom instance naming
export OPENZIM_MCP_SERVER_NAME="production-server-01"

# Enhanced conflict logging
export OPENZIM_MCP_LOGGING__LEVEL=DEBUG
```

### Integration with Monitoring Systems

#### Prometheus Metrics (Future)

```bash
# Enable metrics endpoint
export OPENZIM_MCP_METRICS__ENABLED=true
export OPENZIM_MCP_METRICS__PORT=9090
```

#### Health Check Endpoints

```bash
# Configure health check URL
curl http://localhost:8000/health/instances
```

---

**Need help with deployment?** Check the [Configuration Guide](Configuration-Guide) for detailed setup instructions.
