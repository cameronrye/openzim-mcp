# Contributing to OpenZIM MCP

Thank you for your interest in contributing to OpenZIM MCP! This document provides guidelines and information for contributors.

## Quick Start

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

## Development

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

# Run specific test file
uv run pytest tests/test_security.py -v

# Run tests with ZIM test data (comprehensive testing)
make test-with-zim-data

# Run integration tests only
make test-integration

# Run linting
make lint

# Format code
make format

# Type checking
make type-check

# Run all checks (lint + type-check + security + test)
make check
```

### Project Structure

```text
openzim-mcp/
├── openzim_mcp/                # Main package
│   ├── __init__.py             # Package init, exports __version__ via importlib.metadata
│   ├── __main__.py             # Module entry point (`python -m openzim_mcp`)
│   ├── main.py                 # CLI entry point and arg parsing
│   ├── server.py               # MCP server setup, transport selection
│   ├── http_app.py             # Streamable HTTP / SSE transport, auth, CORS, health
│   ├── config.py               # Pydantic config + env var bindings
│   ├── defaults.py             # Default values and tunables
│   ├── security.py             # Path validation, traversal protection, sanitization
│   ├── error_messages.py       # User-facing error message catalog
│   ├── exceptions.py           # Custom exception hierarchy
│   ├── cache.py                # LRU cache with TTL
│   ├── rate_limiter.py         # Per-client + global token-bucket rate limiting
│   ├── content_processor.py    # HTML→text, heading-id, link extraction
│   ├── async_operations.py     # asyncio helpers and timeouts
│   ├── timeout_utils.py        # Timeout primitives
│   ├── subscriptions.py        # MtimeWatcher and SubscriberRegistry
│   ├── simple_tools.py         # Simple-mode `zim_query` tool
│   ├── intent_parser.py        # Natural-language intent parsing
│   ├── types.py                # Shared TypedDicts
│   ├── constants.py            # Shared constants
│   ├── zim_operations.py       # Backward-compat shim re-exporting from zim/ package
│   ├── zim/                    # ZIM access (split from monolithic zim_operations.py)
│   │   ├── __init__.py         # ZimOperations facade composed of mixins
│   │   ├── archive.py          # Archive open/close, file listing, name resolution
│   │   ├── content.py          # Entry retrieval, summaries, batch get
│   │   ├── namespace.py        # Namespace listing, browse, walk
│   │   ├── search.py           # Full-text + suggestion search; cursor pagination
│   │   └── structure.py        # Article structure, links, related articles
│   └── tools/                  # MCP tool registrations
│       ├── __init__.py
│       ├── file_tools.py       # list_zim_files
│       ├── content_tools.py    # get_zim_entry, get_zim_entries
│       ├── search_tools.py     # search_zim_file, search_all, find_entry_by_title
│       ├── navigation_tools.py # browse_namespace, walk_namespace, search_with_filters, get_search_suggestions
│       ├── structure_tools.py  # get_article_structure, extract_article_links, get_entry_summary, get_table_of_contents, get_binary_entry
│       ├── metadata_tools.py   # get_zim_metadata, get_main_page, list_namespaces
│       ├── server_tools.py     # get_server_health, get_server_configuration
│       ├── resource_tools.py   # MCP resources (zim://files, zim://{name}/...)
│       └── prompts.py          # MCP prompts (/research, /summarize, /explore)
├── tests/                      # Test suite (pytest)
├── website/                    # GitHub Pages site source
├── pyproject.toml              # Project configuration
├── Makefile                    # Development commands
├── Dockerfile                  # Multi-stage container build
└── README.md                   # Project overview
```

## Code Style and Standards

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

### Commit Messages

This project uses [Conventional Commits](https://www.conventionalcommits.org/) for automated versioning and changelog generation.

#### Format

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

#### Types

- **`feat:`** - New features (triggers minor version bump)
- **`fix:`** - Bug fixes (triggers patch version bump)
- **`perf:`** - Performance improvements (triggers patch version bump)
- **`docs:`** - Documentation changes (no version bump)
- **`style:`** - Code style changes (no version bump)
- **`refactor:`** - Code refactoring (no version bump)
- **`test:`** - Test changes (no version bump)
- **`chore:`** - Maintenance tasks (no version bump)
- **`ci:`** - CI/CD changes (no version bump)
- **`build:`** - Build system changes (no version bump)

#### Breaking Changes

For breaking changes, use:

- **`feat!:`** or **`fix!:`** with exclamation mark
- Or include **`BREAKING CHANGE:`** in the footer

#### Examples

```bash
feat: add search suggestions endpoint
fix: resolve path traversal vulnerability
feat!: change API response format
docs: update installation instructions
perf: optimize ZIM file caching
test: add integration tests for new endpoint
chore: update dependencies
```

#### Scope (Optional)

You can add a scope to provide more context:

```bash
feat(api): add new search endpoint
fix(security): resolve path traversal issue
docs(readme): update installation guide
```

## Testing

The project maintains 80%+ test coverage using a hybrid of mock data and real ZIM files.

### Test Categories

1. **Unit Tests**: Fast tests with mocked dependencies
2. **Integration Tests**: End-to-end functionality testing with real ZIM files
3. **Security Tests**: Path traversal and input validation
4. **Performance Tests**: Caching and resource management
5. **Format Compatibility**: Various ZIM file formats and versions
6. **Error Handling**: Invalid and malformed ZIM files

### Test Infrastructure

OpenZIM MCP uses a hybrid testing approach:

1. **Mock-based tests**: Fast unit tests using mocked libzim components
2. **Real ZIM file tests**: Integration tests using official zim-testing-suite files
3. **Automatic test data management**: Download and organize test files as needed

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

Test files are automatically organized by category and priority level. Set `ZIM_TEST_DATA_DIR` to use a custom test data location.

### Writing Tests

- Place tests in the `tests/` directory
- Use descriptive test names: `test_should_do_something_when_condition`
- Follow the Arrange-Act-Assert pattern
- Mock external dependencies in unit tests
- Use real ZIM files for integration tests when needed

### Test Markers

Use pytest markers to categorize tests:

```python
@pytest.mark.integration  # Integration test
@pytest.mark.slow         # Long-running test
```

### Running Specific Tests

```bash
# Run specific test file
uv run pytest tests/test_security.py -v

# Run tests with specific marker
uv run pytest -m "not slow"

# Run tests with coverage and open HTML report
make test-cov
open htmlcov/index.html
```

## Security

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

## Pull Request Process

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

## Bug Reports

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

## Feature Requests

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

## Issue Labels

We use labels to categorize issues:

- **bug**: Something isn't working
- **enhancement**: New feature or improvement
- **documentation**: Documentation improvements
- **good first issue**: Good for newcomers
- **help wanted**: Extra attention needed
- **security**: Security-related issues
- **performance**: Performance improvements
- **testing**: Testing improvements

## Development Focus Areas

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

## Resources

### Documentation

- [README.md](README.md) - Project overview, configuration, and API reference
- [CHANGELOG.md](CHANGELOG.md) - Release history
- [SECURITY.md](SECURITY.md) - Security policy and reporting
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) - Community standards

### External Resources

- [ZIM Format Documentation](https://openzim.org/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [Python Type Hints](https://docs.python.org/3/library/typing.html)
- [pytest Documentation](https://docs.pytest.org/)

## Community

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

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Release process

Releases are driven by [release-please](https://github.com/googleapis/release-please) reading conventional commits on `main`. When a release PR merges, GitHub Actions builds and publishes the wheel to PyPI (via Trusted Publishing), creates the GitHub Release, and pushes a multi-arch Docker image to `ghcr.io/cameronrye/openzim-mcp`.

### Conventional commits drive versioning

Commit message prefixes map to semver bumps and `CHANGELOG.md` sections:

| Prefix | Section | Version bump |
| --- | --- | --- |
| `feat:` | Added | minor |
| `fix:` | Fixed | patch |
| `perf:` | Performance | patch |
| `deps:` | Dependencies | none |
| `docs:` | Documentation | none |
| `refactor:` | Refactored | none |
| `chore:` / `ci:` / `build:` / `test:` / `style:` | Maintenance (hidden) | none |

Breaking changes: append `!` to the type (`feat!:`) or include a `BREAKING CHANGE:` footer. Either form triggers a major bump.

### Automatic release flow

1. Land conventional commits on `main` via squash-merge.
2. `release-please.yml` opens a release PR (updates `CHANGELOG.md`, `pyproject.toml`, `openzim_mcp/__init__.py`, `.release-please-manifest.json`, `website/llm.txt`).
3. Review and merge the release PR.
4. `release-please` pushes the `v<X.Y.Z>` tag.
5. `release.yml` triggers on the tag: version-sync check → integration tests → wheel + sdist build → PyPI upload (Trusted Publishing, no token) → GitHub Release creation with notes pulled from `CHANGELOG.md` and wheel + sdist attached.
6. `docker-publish.yml` triggers on the same tag: multi-arch build → push to `ghcr.io/cameronrye/openzim-mcp:<X.Y.Z>` and `:latest`.

`release-please-config.json` sets `skip-github-release: true`, so the GitHub Release is created by `release.yml` *after* PyPI succeeds (avoids orphaned releases if PyPI fails).

### Manual / emergency release

For tag-only releases when `release-please` isn't appropriate:

```bash
git tag v<X.Y.Z>
git push origin v<X.Y.Z>
```

`tag-release.yml` fires on the tag push and runs the same pipeline as `release.yml`.

### Troubleshooting

- **No release PR after merging commits**: check commit messages are conventional. Non-`feat`/`fix`/`perf`/`deps` commits don't bump versions on their own.
- **Version sync failure**: `pyproject.toml`, `openzim_mcp/__init__.py`, and `.release-please-manifest.json` must agree on the version. If they drift (rare; usually a manual edit), align them in a follow-up PR.
- **PyPI upload failure with "already exists"**: harmless; the workflow uses `skip-existing: true`. A true conflict (same version, different artifact) requires bumping the version.

### Source files

- [`release-please-config.json`](release-please-config.json)
- [`.github/workflows/release-please.yml`](.github/workflows/release-please.yml)
- [`.github/workflows/release.yml`](.github/workflows/release.yml)
- [`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml)
- [`.github/workflows/tag-release.yml`](.github/workflows/tag-release.yml)

---

Thank you for contributing to OpenZIM MCP!
