# Security Best Practices

Security considerations and best practices for deploying OpenZIM MCP in production environments.

## 🔒 Security Overview

OpenZIM MCP implements multiple layers of security to protect against common vulnerabilities and ensure safe operation in production environments.

## 🛡️ Built-in Security Features

### Advanced Path Traversal Protection

**Enterprise-Grade Protection**:
- Multi-layer path normalization and validation
- Whitelist-based directory access with inheritance checking
- Symbolic link resolution blocking with recursive detection
- Relative path prevention with canonical path verification
- Directory escape detection using multiple algorithms
- Real-time path validation with caching

**Enhanced Security Implementation**:
```python
# Advanced path validation process
def validate_path_enterprise(self, path: str) -> ValidationResult:
    # 1. Normalize path separators and resolve relative components
    normalized = os.path.normpath(path.replace('\\', '/'))

    # 2. Detect common traversal patterns
    traversal_patterns = ['../', '..\\', '%2e%2e%2f', '%2e%2e%5c']
    for pattern in traversal_patterns:
        if pattern in path.lower():
            return ValidationResult.BLOCKED_TRAVERSAL

    # 3. Resolve symbolic links and get canonical path
    try:
        canonical = os.path.realpath(normalized)
    except (OSError, ValueError):
        return ValidationResult.INVALID_PATH

    # 4. Verify against allowed directories
    for allowed_dir in self.allowed_directories:
        allowed_canonical = os.path.realpath(allowed_dir)
        if canonical.startswith(allowed_canonical + os.sep):
            return ValidationResult.ALLOWED

    return ValidationResult.BLOCKED_UNAUTHORIZED
```

**Configuration**:
```bash
# Enable strict path validation (default: true)
export OPENZIM_MCP_SECURITY__STRICT_PATHS=true

# Limit path depth (default: 10)
export OPENZIM_MCP_SECURITY__MAX_PATH_DEPTH=15

# Enable advanced traversal detection (default: true)
export OPENZIM_MCP_SECURITY__ADVANCED_TRAVERSAL_DETECTION=true

# Path validation cache size (default: 1000)
export OPENZIM_MCP_SECURITY__PATH_CACHE_SIZE=2000
```

### Input Validation

**Comprehensive Validation**:
- Query length limits
- Parameter type checking
- Content sanitization
- File extension validation

**Configuration**:
```bash
# Maximum query length (default: 1000)
export OPENZIM_MCP_SECURITY__MAX_QUERY_LENGTH=2000

# Enable input sanitization (default: true)
export OPENZIM_MCP_SECURITY__SANITIZE_INPUT=true

# Allowed file extensions (default: .zim)
export OPENZIM_MCP_SECURITY__ALLOWED_EXTENSIONS=".zim,.zimaa"
```

### Multi-Instance Security

**Enterprise Instance Management**:
- Automatic instance registration with security validation
- Configuration hash verification to prevent tampering
- Process isolation and conflict detection
- Secure instance file storage with permission validation
- Automatic cleanup of stale instances

**Security Features**:
```python
# Instance security validation
def validate_instance_security(self, instance: ServerInstance) -> SecurityResult:
    # 1. Verify process ownership
    try:
        process = psutil.Process(instance.pid)
        if process.username() != self.expected_user:
            return SecurityResult.UNAUTHORIZED_PROCESS
    except psutil.NoSuchProcess:
        return SecurityResult.STALE_INSTANCE

    # 2. Validate configuration hash
    if not self.verify_config_hash(instance.config_hash):
        return SecurityResult.TAMPERED_CONFIG

    # 3. Check directory permissions
    for directory in instance.allowed_directories:
        if not self.validate_directory_permissions(directory):
            return SecurityResult.INSECURE_PERMISSIONS

    return SecurityResult.SECURE
```

**Configuration**:
```bash
# Enable instance tracking (default: true)
export OPENZIM_MCP_INSTANCE__TRACKING_ENABLED=true

# Secure instance directory (default: ~/.openzim_mcp_instances)
export OPENZIM_MCP_INSTANCE__TRACKING_DIR="/var/lib/openzim_mcp_secure"

# Strict conflict detection (default: strict)
export OPENZIM_MCP_INSTANCE__CONFLICT_DETECTION=strict

# Instance file permissions (default: 600)
export OPENZIM_MCP_INSTANCE__FILE_PERMISSIONS=600

# Enable process validation (default: true)
export OPENZIM_MCP_INSTANCE__VALIDATE_PROCESSES=true
```

## 🏗️ Deployment Security

### File System Security

**Directory Permissions**:
```bash
# Set appropriate permissions for ZIM files directory
chmod 755 /path/to/zim/files
chmod 644 /path/to/zim/files/*.zim

# Ensure proper ownership
chown -R zimuser:zimgroup /path/to/zim/files
```

**Access Control**:
```bash
# Create dedicated user for OpenZIM MCP
sudo useradd -r -s /bin/false zimuser
sudo usermod -a -G zimgroup zimuser

# Run server as dedicated user
sudo -u zimuser uv run python -m openzim_mcp /path/to/zim/files
```

### Network Security

**Local Access Only** (Recommended):
- OpenZIM MCP is designed for local MCP client connections
- Avoid exposing directly to network interfaces
- Use reverse proxy if network access is required

**Firewall Configuration**:
```bash
# Block external access to MCP ports
sudo ufw deny from any to any port 3000  # Example MCP port
sudo ufw allow from 127.0.0.1 to any port 3000  # Local only
```

## 🔐 Access Control

### Directory Restrictions

**Principle of Least Privilege**:
```bash
# Only allow access to specific ZIM directories
export OPENZIM_MCP_ALLOWED_DIRECTORIES="/opt/zim-files:/var/lib/zim-content"

# Avoid broad access
# DON'T: export OPENZIM_MCP_ALLOWED_DIRECTORIES="/"
```

**Directory Structure**:
```bash
# Recommended structure
/opt/zim-files/
├── public/          # General access ZIM files
├── restricted/      # Limited access content
└── temp/           # Temporary files (regularly cleaned)

# Set permissions appropriately
chmod 755 /opt/zim-files/public
chmod 750 /opt/zim-files/restricted
chmod 700 /opt/zim-files/temp
```

### File Validation

**ZIM File Integrity**:
```bash
# Verify ZIM file integrity before use
zimcheck /path/to/file.zim

# Check file signatures (if available)
sha256sum -c zim-files.sha256
```

**Content Validation**:
- Only use ZIM files from trusted sources
- Verify download integrity
- Regular security scans of content

## 🔍 Input Security

### Query Sanitization

**Automatic Sanitization**:
- HTML entity encoding
- Special character filtering
- Length limit enforcement
- Type validation

**Custom Validation**:
```python
# Example additional validation
def validate_search_query(query: str) -> bool:
    # Check for suspicious patterns
    suspicious_patterns = [
        r'<script',
        r'javascript:',
        r'data:',
        r'vbscript:'
    ]

    for pattern in suspicious_patterns:
        if re.search(pattern, query, re.IGNORECASE):
            return False

    return True
```

### Parameter Validation

**Built-in Limits**:
- Maximum content length: 1,000,000 characters
- Maximum search results: 100
- Maximum query length: 10,000 characters
- Path depth limits: 50 levels

**Custom Limits**:
```bash
# Stricter limits for high-security environments
export OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH=50000
export OPENZIM_MCP_SECURITY__MAX_QUERY_LENGTH=500
export OPENZIM_MCP_SECURITY__MAX_PATH_DEPTH=5
```

## 📝 Logging and Monitoring

### Security Logging

**Enable Comprehensive Logging**:
```bash
export OPENZIM_MCP_LOGGING__LEVEL=INFO
export OPENZIM_MCP_LOGGING__JSON=true
export OPENZIM_MCP_LOGGING__SECURITY_EVENTS=true
```

**Log Monitoring**:
```bash
# Monitor for security events
tail -f /var/log/openzim-mcp/security.log | grep -E "(SECURITY|ERROR|WARNING)"

# Set up log rotation
logrotate /etc/logrotate.d/openzim-mcp
```

### Security Metrics

**Monitor Key Indicators**:
- Failed access attempts
- Path traversal attempts
- Invalid input patterns
- Unusual request patterns
- Resource exhaustion attempts

**Alerting**:
```bash
# Example monitoring script
#!/bin/bash
SECURITY_LOG="/var/log/openzim-mcp/security.log"
ALERT_THRESHOLD=10

# Count security events in last hour
EVENTS=$(grep -c "SECURITY_VIOLATION" "$SECURITY_LOG" | tail -n 60)

if [ "$EVENTS" -gt "$ALERT_THRESHOLD" ]; then
    echo "Security alert: $EVENTS violations in last hour" | mail -s "OpenZIM MCP Security Alert" admin@example.com
fi
```

## 🔄 Update and Maintenance

### Regular Updates

**Keep Dependencies Updated**:
```bash
# Update Python packages
uv sync --upgrade

# Check for security advisories
pip-audit

# Update system packages
sudo apt update && sudo apt upgrade
```

**ZIM File Updates**:
- Regular content updates from trusted sources
- Verify integrity of new ZIM files
- Remove outdated or unused content

### Security Auditing

**Regular Security Checks**:
```bash
# Run security diagnostics
"Diagnose server state and check for security issues"

# Check file permissions
find /path/to/zim/files -type f -perm /o+w -ls

# Verify configuration
"Get server configuration and validate security settings"
```

**Vulnerability Scanning**:
```bash
# Scan for known vulnerabilities
bandit -r openzim_mcp/

# Check dependencies
safety check

# System-level scanning
sudo lynis audit system
```

## 🚨 Incident Response

### Security Event Detection

**Automated Detection**:
- Path traversal attempts
- Excessive request rates
- Invalid input patterns
- Configuration tampering

**Response Procedures**:
1. **Immediate**: Log and block suspicious activity
2. **Short-term**: Investigate and assess impact
3. **Long-term**: Implement additional protections

### Incident Handling

**Security Incident Checklist**:
- [ ] Identify and contain the threat
- [ ] Preserve logs and evidence
- [ ] Assess impact and scope
- [ ] Implement immediate mitigations
- [ ] Notify relevant stakeholders
- [ ] Document lessons learned
- [ ] Update security measures

## 🔧 Hardening Configuration

### Production Security Profile

```bash
# Maximum security configuration
export OPENZIM_MCP_SECURITY__STRICT_PATHS=true
export OPENZIM_MCP_SECURITY__MAX_PATH_DEPTH=5
export OPENZIM_MCP_SECURITY__MAX_QUERY_LENGTH=500
export OPENZIM_MCP_SECURITY__SANITIZE_INPUT=true
export OPENZIM_MCP_SECURITY__ALLOWED_EXTENSIONS=".zim"

# Logging
export OPENZIM_MCP_LOGGING__LEVEL=INFO
export OPENZIM_MCP_LOGGING__JSON=true
export OPENZIM_MCP_LOGGING__SECURITY_EVENTS=true

# Resource limits
export OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH=100000
export OPENZIM_MCP_SERVER__MAX_CONCURRENT=10
export OPENZIM_MCP_SERVER__REQUEST_TIMEOUT=30
```

### Environment Isolation

**Container Security** (Future):
```dockerfile
# Example secure container configuration
FROM python:3.12-slim

# Create non-root user
RUN useradd -r -s /bin/false zimuser

# Set up secure directories
RUN mkdir -p /opt/zim-files /var/log/openzim-mcp
RUN chown zimuser:zimuser /opt/zim-files /var/log/openzim-mcp

# Switch to non-root user
USER zimuser

# Run with minimal privileges
CMD ["python", "-m", "openzim_mcp", "/opt/zim-files"]
```

**Process Isolation**:
```bash
# Use systemd for process management
sudo systemctl enable openzim-mcp
sudo systemctl start openzim-mcp

# Set resource limits
echo "zimuser soft nofile 1024" >> /etc/security/limits.conf
echo "zimuser hard nofile 2048" >> /etc/security/limits.conf
```

## 📋 Security Checklist

### Pre-Deployment

- [ ] Dedicated user account created
- [ ] Appropriate file permissions set
- [ ] Directory access restricted
- [ ] Input validation configured
- [ ] Logging enabled and configured
- [ ] Security monitoring in place
- [ ] Firewall rules configured
- [ ] ZIM files verified and trusted

### Post-Deployment

- [ ] Security logs monitored
- [ ] Regular security audits scheduled
- [ ] Update procedures established
- [ ] Incident response plan documented
- [ ] Backup and recovery tested
- [ ] Performance monitoring active
- [ ] Access controls verified
- [ ] Documentation updated

### Ongoing Maintenance

- [ ] Regular dependency updates
- [ ] Security patch management
- [ ] Log analysis and alerting
- [ ] Configuration drift detection
- [ ] Vulnerability assessments
- [ ] Penetration testing (if applicable)
- [ ] Security training for operators
- [ ] Incident response drills

## 🔍 Security Testing

### Validation Tests

**Path Traversal Testing**:
```bash
# Test path traversal protection
# These should all be blocked:
# ../../../etc/passwd
# ..\\..\\..\\windows\\system32
# /etc/passwd
# C:\Windows\System32
```

**Input Validation Testing**:
```bash
# Test input sanitization
# These should be sanitized or rejected:
# <script>alert('xss')</script>
# javascript:alert('xss')
# data:text/html,<script>alert('xss')</script>
```

**Resource Exhaustion Testing**:
```bash
# Test resource limits
# Large queries, excessive requests, etc.
```

## 🚀 Advanced Security

### Future Enhancements

**Planned Security Features**:
- Rate limiting and throttling
- Authentication and authorization
- Encrypted communication
- Audit trail enhancement
- Advanced threat detection

**Integration Opportunities**:
- SIEM system integration
- Security orchestration platforms
- Threat intelligence feeds
- Compliance frameworks

---

**Security Questions?** Check the [Troubleshooting Guide](Troubleshooting-Guide) for security-related issues or [open an issue](https://github.com/cameronrye/openzim-mcp/issues) for security concerns.
