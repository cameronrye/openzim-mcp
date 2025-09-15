# Contributing to OpenZIM MCP

Thank you for your interest in contributing to OpenZIM MCP! This document provides guidelines and information for contributors.

## 🚀 Quick Start

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/openzim-mcp.git
   cd openzim-mcp
   ```
3. **Set up development environment**:
   ```bash
   python scripts/setup_dev_env.py
   ```
4. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature-name
   ```
5. **Make your changes** and commit them
6. **Push to your fork** and create a pull request

## 🛠️ Development Setup

### Prerequisites

- **Python 3.12+** (Python 3.13 also supported)
- **uv** package manager (recommended) or pip
- **Git** for version control

### Environment Setup

```bash
# Clone the repository
git clone https://github.com/cameronrye/openzim-mcp.git
cd openzim-mcp

# Install dependencies
uv sync

# Install pre-commit hooks (recommended)
uv run pre-commit install

# Download test data
make download-test-data

# Run tests to verify setup
make test
```

### Development Commands

```bash
# Run all tests
make test

# Run tests with coverage
make test-cov

# Run linting
make lint

# Format code
make format

# Type checking
make type-check

# Run all checks (lint + type-check + test)
make check

# Run integration tests with ZIM data
make test-with-zim-data
```

## 📝 Code Style and Standards

### Code Formatting

We use several tools to maintain code quality:

- **Black** for code formatting (line length: 88)
- **isort** for import sorting
- **flake8** for linting
- **mypy** for type checking
- **bandit** for security scanning

### Pre-commit Hooks

Install pre-commit hooks to automatically check your code:

```bash
uv run pre-commit install
```

This will run checks on every commit. You can also run manually:

```bash
uv run pre-commit run --all-files
```

### Type Hints

- All functions must have type hints
- Use `from __future__ import annotations` for forward references
- Follow PEP 484 and PEP 585 guidelines

### Documentation

- Use Google-style docstrings
- Document all public functions and classes
- Include examples in docstrings where helpful
- Update README.md for user-facing changes

## 🧪 Testing

### Test Categories

1. **Unit Tests**: Fast tests with mocked dependencies
2. **Integration Tests**: Tests with real ZIM files
3. **Security Tests**: Path traversal and input validation
4. **Performance Tests**: Caching and resource management

### Writing Tests

- Place tests in the `tests/` directory
- Use descriptive test names: `test_should_do_something_when_condition`
- Follow the Arrange-Act-Assert pattern
- Mock external dependencies in unit tests
- Use real ZIM files for integration tests when needed

### Test Markers

Use pytest markers to categorize tests:

```python
@pytest.mark.requires_zim_data  # Requires ZIM test files
@pytest.mark.integration       # Integration test
@pytest.mark.slow             # Long-running test
```

### Running Specific Tests

```bash
# Run specific test file
uv run pytest tests/test_security.py -v

# Run tests with specific marker
uv run pytest -m "not slow"

# Run tests requiring ZIM data
make test-requires-zim-data
```

## 🔒 Security

### Security Guidelines

- Never commit sensitive information (API keys, passwords, etc.)
- Validate all user inputs
- Use secure path handling to prevent directory traversal
- Follow the principle of least privilege
- Report security vulnerabilities privately (see SECURITY.md)

### Security Testing

- Run security scans: `uv run bandit -r openzim_mcp`
- Test with malicious inputs
- Verify path traversal protection
- Check for information disclosure in error messages

## 📋 Pull Request Process

### Before Submitting

1. **Run all checks**: `make check`
2. **Update tests** for new functionality
3. **Update documentation** if needed
4. **Add changelog entry** if user-facing change
5. **Ensure CI passes** on your branch

### PR Guidelines

- **Clear title**: Describe what the PR does
- **Detailed description**: Explain the changes and why
- **Link issues**: Reference related issues with "Fixes #123"
- **Small PRs**: Keep changes focused and reviewable
- **Tests included**: Add tests for new functionality

### PR Template

When creating a PR, include:

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Tests pass locally
- [ ] New tests added for new functionality
- [ ] Integration tests pass

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] Changelog updated (if needed)
```

## 🐛 Bug Reports

### Before Reporting

1. **Search existing issues** to avoid duplicates
2. **Update to latest version** and test again
3. **Check documentation** for known limitations
4. **Gather information** about your environment

### Bug Report Template

Include:

- **Environment**: OS, Python version, package version
- **Steps to reproduce**: Minimal example
- **Expected behavior**: What should happen
- **Actual behavior**: What actually happens
- **Error messages**: Full stack traces
- **ZIM files**: Information about test files used

## 💡 Feature Requests

### Before Requesting

1. **Check existing issues** and discussions
2. **Consider scope**: Does it fit the project goals?
3. **Think about implementation**: How might it work?

### Feature Request Template

Include:

- **Problem**: What problem does this solve?
- **Solution**: Proposed solution or approach
- **Alternatives**: Other solutions considered
- **Use cases**: How would this be used?
- **Breaking changes**: Any compatibility concerns

## 🏷️ Issue Labels

We use labels to categorize issues:

- **bug**: Something isn't working
- **enhancement**: New feature or improvement
- **documentation**: Documentation improvements
- **good first issue**: Good for newcomers
- **help wanted**: Extra attention needed
- **security**: Security-related issues
- **performance**: Performance improvements
- **testing**: Testing improvements

## 🎯 Development Focus Areas

### High Priority

- **Security**: Input validation, path traversal protection
- **Performance**: Caching, resource management
- **Testing**: Comprehensive test coverage
- **Documentation**: Clear, helpful documentation

### Good First Issues

- Documentation improvements
- Test coverage improvements
- Code quality enhancements
- Minor bug fixes

## 📚 Resources

### Documentation

- [README.md](README.md) - Project overview and usage
- [docs/TESTING.md](docs/TESTING.md) - Testing guide
- [docs/LLM.md](docs/LLM.md) - LLM integration guide
- [docs/BRANCH_PROTECTION.md](docs/BRANCH_PROTECTION.md) - Branch protection setup

### External Resources

- [ZIM Format Documentation](https://openzim.org/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Python Type Hints](https://docs.python.org/3/library/typing.html)
- [pytest Documentation](https://docs.pytest.org/)

## 🤝 Community

### Code of Conduct

Please read and follow our [Code of Conduct](CODE_OF_CONDUCT.md).

### Getting Help

- **GitHub Issues**: For bugs and feature requests
- **GitHub Discussions**: For questions and general discussion
- **Documentation**: Check existing docs first

### Recognition

Contributors are recognized in:

- GitHub contributors list
- Release notes for significant contributions
- Special thanks in documentation

## 📄 License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

Thank you for contributing to OpenZIM MCP! 🎉
