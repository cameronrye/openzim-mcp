# Security Policy

## Supported Versions

We actively support the following versions of OpenZIM MCP with security updates:

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | ✅ Yes             |
| 0.1.x   | ❌ No (deprecated) |

## Reporting a Vulnerability

We take security vulnerabilities seriously and appreciate your help in keeping OpenZIM MCP secure.

### For Sensitive Security Issues

**Please DO NOT report sensitive security vulnerabilities through public GitHub issues.**

Instead, please report them privately using one of these methods:

#### 1. GitHub Private Vulnerability Reporting (Preferred)

1. Go to the [Security tab](https://github.com/cameronrye/openzim-mcp/security) of this repository
2. Click "Report a vulnerability"
3. Fill out the vulnerability report form
4. Submit the report

#### 2. Email Reporting

Send an email to: **security@[project-domain]** (replace with actual email)

Include in your email:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fixes
- Your contact information for follow-up

#### 3. Encrypted Communication

For highly sensitive issues, you can use PGP encryption:

```
-----BEGIN PGP PUBLIC KEY BLOCK-----
[PGP public key would go here]
-----END PGP PUBLIC KEY BLOCK-----
```

### For Non-Sensitive Security Issues

For general security improvements, hardening suggestions, or non-exploitable security-related issues, you can:

- Open a public GitHub issue using the "Security Vulnerability Report" template
- Start a discussion in GitHub Discussions

## What to Include in Your Report

Please include as much information as possible:

### Required Information

- **Description**: Clear description of the vulnerability
- **Impact**: What could an attacker accomplish?
- **Reproduction**: Step-by-step instructions to reproduce
- **Environment**: OS, Python version, OpenZIM MCP version
- **ZIM Files**: Information about test files used (if relevant)

### Optional but Helpful

- **Proof of Concept**: Code or commands demonstrating the issue
- **Suggested Fix**: Ideas for how to address the vulnerability
- **References**: Links to similar vulnerabilities or security resources
- **CVSS Score**: If you can calculate one

## Response Timeline

We are committed to responding to security reports promptly:

| Timeline | Action |
|----------|--------|
| 24 hours | Initial acknowledgment of your report |
| 72 hours | Initial assessment and severity classification |
| 7 days   | Detailed response with our planned approach |
| 30 days  | Target for fix development and testing |
| 45 days  | Target for public disclosure (coordinated) |

**Note**: Complex vulnerabilities may require more time. We will keep you updated on our progress.

## Severity Classification

We classify vulnerabilities using the following criteria:

### Critical (CVSS 9.0-10.0)
- Remote code execution
- Privilege escalation to system level
- Data exfiltration of sensitive information

### High (CVSS 7.0-8.9)
- Local privilege escalation
- Authentication bypass
- Significant data exposure

### Medium (CVSS 4.0-6.9)
- Information disclosure
- Denial of service
- Path traversal (limited impact)

### Low (CVSS 0.1-3.9)
- Minor information leaks
- Security misconfigurations
- Theoretical attacks with high complexity

## Security Measures

OpenZIM MCP implements several security measures:

### Input Validation
- Comprehensive path validation to prevent directory traversal
- Input sanitization for all user-provided data
- Type checking and validation using Pydantic

### Secure Defaults
- Restricted file access to allowed directories only
- Secure error handling that doesn't leak sensitive information
- Resource limits to prevent abuse

### Code Security
- Regular security scanning with bandit
- Dependency vulnerability scanning
- Type safety with mypy
- Comprehensive testing including security tests

### Development Security
- Pre-commit hooks for security checks
- Automated security scanning in CI/CD
- Regular dependency updates
- Code review requirements

## Known Security Considerations

### ZIM File Processing
- ZIM files are processed using the libzim library
- Content is sanitized before processing
- Large files are handled with appropriate limits

### Path Handling
- All file paths are validated against allowed directories
- Path traversal attacks are prevented through secure path resolution
- Symbolic links are handled safely

### Caching
- Cache keys are validated to prevent cache poisoning
- Cached content has appropriate TTL limits
- Cache size is limited to prevent memory exhaustion

## Security Best Practices for Users

### Deployment Security
- Run OpenZIM MCP with minimal required privileges
- Use allowed directories to restrict file access
- Monitor logs for suspicious activity
- Keep dependencies updated

### ZIM File Security
- Only use ZIM files from trusted sources
- Verify ZIM file integrity when possible
- Be cautious with user-provided ZIM files

### Configuration Security
- Use environment variables for sensitive configuration
- Avoid logging sensitive information
- Implement appropriate access controls

## Disclosure Policy

### Coordinated Disclosure

We follow responsible disclosure practices:

1. **Private Reporting**: Vulnerabilities are reported privately
2. **Assessment**: We assess and develop fixes privately
3. **Coordination**: We coordinate with reporters on disclosure timing
4. **Public Disclosure**: We disclose publicly after fixes are available

### Public Disclosure

After a fix is available:

1. **Security Advisory**: We publish a GitHub Security Advisory
2. **Release Notes**: Security fixes are noted in release notes
3. **CVE Assignment**: We request CVE assignment for significant vulnerabilities
4. **Credit**: We credit reporters (unless they prefer anonymity)

## Security Updates

### Notification Channels

Stay informed about security updates:

- **GitHub Security Advisories**: Watch this repository for security advisories
- **Release Notes**: Check release notes for security fixes
- **Mailing List**: Subscribe to our security mailing list (if available)

### Update Process

When security updates are released:

1. **Immediate**: Critical vulnerabilities require immediate updates
2. **Scheduled**: Lower severity issues may be bundled with regular releases
3. **Backports**: Security fixes are backported to supported versions

## Bug Bounty Program

Currently, we do not have a formal bug bounty program. However, we greatly appreciate security researchers who help improve our security posture.

### Recognition

We recognize security contributors through:

- Public acknowledgment in security advisories
- Credit in release notes
- Hall of fame in documentation (if desired)

## Contact Information

### Security Team

- **Primary Contact**: [security email]
- **Backup Contact**: [backup email]
- **Response Time**: 24 hours for initial response

### General Security Questions

For general security questions or discussions:

- **GitHub Discussions**: Use the Security category
- **Email**: [general email]

## Legal

### Safe Harbor

We support security research conducted in good faith. We will not pursue legal action against researchers who:

- Report vulnerabilities responsibly through proper channels
- Do not access or modify data beyond what is necessary to demonstrate the vulnerability
- Do not perform testing on production systems without permission
- Respect user privacy and data protection laws

### Responsible Research

Please ensure your security research:

- Complies with applicable laws and regulations
- Respects user privacy and data protection
- Does not cause harm to our systems or users
- Follows coordinated disclosure practices

---

Thank you for helping to keep OpenZIM MCP secure! 🔒
