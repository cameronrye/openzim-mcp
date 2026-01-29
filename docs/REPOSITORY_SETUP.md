# Repository Setup and Configuration

This document outlines the comprehensive setup and configuration applied to make OpenZIM MCP a best-in-class open source project.

## Repository Settings

### Basic Configuration

- **Description**: OpenZIM MCP is a modern, secure, and high-performance MCP (Model Context Protocol) server that enables AI models to access and search ZIM format knowledge bases offline.
- **Homepage**: <https://cameronrye.github.io/openzim-mcp/>
- **Topics**: `mcp`, `mcp-server`, `openzim`, `zim`, `kiwix`, `ai`, `llm`, `knowledge-base`, `offline`, `wikipedia`, `python`, `libzim`

### Features Enabled

- Issues
- Projects
- Wiki
- Discussions
- GitHub Pages
- Downloads

### Merge Settings

- Allow squash merging (default)
- Allow merge commits (disabled for clean history)
- Allow rebase merging (disabled for consistency)
- Automatically delete head branches
- Allow auto-merge
- Allow update branch
- Use PR title as default for squash merge

## Security Configuration

### Branch Protection (main branch)

- Require pull request reviews before merging
- Required approving reviews: 1
- Dismiss stale reviews when new commits are pushed
- Require review from code owners
- Require status checks to pass before merging
- Require branches to be up to date before merging
- Required status checks:
  - `test (ubuntu-latest, 3.12)`
  - `test (ubuntu-latest, 3.13)`
  - `security`
  - `CodeQL`
- Require conversation resolution before merging
- Enforce restrictions for administrators (allows admin override)
- Allow force pushes
- Allow deletions

### Security Features

- Dependabot security updates
- Secret scanning
- Secret scanning push protection
- CodeQL analysis
- Dependency review

## Badges and Metrics

### Build and Quality Badges

- **CI Status**: Shows build status across multiple Python versions and OS
- **Code Coverage**: Codecov integration for coverage reporting
- **CodeQL**: Security analysis status
- **Security Rating**: SonarCloud integration (when configured)

### Package Information

- **PyPI Version**: Current published version
- **Python Versions**: Supported Python versions
- **Downloads**: Monthly download statistics
- **GitHub Release**: Latest release information

### Code Quality

- **Code Style**: Black formatter compliance
- **Import Sorting**: isort compliance
- **Type Checking**: mypy compliance
- **License**: MIT license badge

### Community Metrics

- **Issues**: Open issues count
- **Pull Requests**: Open PR count
- **Contributors**: Number of contributors
- **Stars**: GitHub stars (social proof)

## Automation

### GitHub Actions Workflows

1. **CI (`test.yml`)**: Comprehensive testing across multiple environments
2. **Release (`release.yml`)**: Automated releases to PyPI and GitHub
3. **CodeQL (`codeql.yml`)**: Security analysis
4. **Performance (`performance.yml`)**: Performance benchmarking
5. **Dependency Updates (`dependency-update.yml`)**: Automated dependency management

### Dependabot Configuration

- **Python Dependencies**: Weekly updates with grouping
- **GitHub Actions**: Weekly updates
- **Security Updates**: Immediate updates for vulnerabilities

## Documentation Structure

### Core Documentation

- `README.md`: Comprehensive project overview with badges
- `CHANGELOG.md`: Detailed change history
- `CONTRIBUTING.md`: Contribution guidelines
- `SECURITY.md`: Security policy and reporting
- `LICENSE`: MIT license

### Extended Documentation

- `docs/`: Additional documentation
- `wiki-content/`: Wiki content for GitHub Pages
- Issue templates for bugs, features, and security reports
- Pull request template

## Best Practices Implemented

### Code Quality

- 80%+ test coverage requirement
- Type safety with mypy
- Code formatting with black
- Import sorting with isort
- Security scanning with bandit
- Dependency vulnerability scanning with safety

### Release Management

- Semantic versioning
- Automated changelog generation
- PyPI publishing with trusted publishing
- GitHub releases with artifacts
- Pre-release testing

### Community Management

- Clear contribution guidelines
- Code of conduct
- Issue and PR templates
- Code owners for review assignment
- Security reporting process

### Performance and Reliability

- Multi-platform testing (Linux, Windows, macOS)
- Multiple Python version support (3.12, 3.13)
- Performance benchmarking
- Comprehensive integration testing

## Getting Started for Contributors

1. **Fork the repository**
2. **Clone your fork**: `git clone https://github.com/YOUR_USERNAME/openzim-mcp.git`
3. **Install dependencies**: `uv sync --dev`
4. **Run tests**: `make check`
5. **Create a feature branch**: `git checkout -b feature/amazing-feature`
6. **Make changes and test**: `make test-cov`
7. **Submit a pull request**

All pull requests will automatically trigger the CI pipeline and require:

- Passing tests on all supported platforms
- Code coverage maintenance
- Security scan approval
- Code owner review

## Monitoring and Maintenance

### Regular Tasks

- Monitor Dependabot PRs and merge when appropriate
- Review security alerts and address vulnerabilities
- Update documentation as features evolve
- Monitor performance benchmarks for regressions
- Review and respond to community issues and PRs

### Quarterly Reviews

- Review and update repository settings
- Audit security configurations
- Update development dependencies
- Review and improve documentation
- Analyze usage metrics and community feedback

This configuration ensures OpenZIM MCP maintains high standards for code quality, security, and community engagement while providing a smooth experience for both users and contributors.
