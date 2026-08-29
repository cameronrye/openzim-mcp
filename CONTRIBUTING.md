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

# Run the integration-test file only
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
├── openzim_mcp/                # Main package (abridged — see the source tree for the full listing)
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
│   ├── subscriptions.py        # MtimeWatcher and publish_change (SDK subscription bus)
│   ├── simple_tools.py         # Simple-mode `zim_query` tool
│   ├── intent_parser.py        # Natural-language intent parsing
│   ├── tool_schemas.py         # Per-tool response TypedDicts
│   ├── constants.py            # Shared constants
│   ├── zim_operations.py       # Backward-compat shim re-exporting from zim/ package
│   ├── cli/                    # `openzim-mcp build` subcommands (link-graph sidecar)
│   ├── linkgraph/              # Inbound link-graph sidecar build + runtime read
│   ├── ml/                     # Optional reranker extra + model-download CLI
│   ├── data/                   # Packaged data files (presets.toml, …)
│   ├── zim/                    # ZIM access (split from monolithic zim_operations.py)
│   │   ├── __init__.py         # ZimOperations facade composed of mixins
│   │   ├── archive.py          # Archive open/close, file listing, name resolution
│   │   ├── content.py          # Entry retrieval, summaries, batch get
│   │   ├── namespace.py        # Namespace listing, browse, walk
│   │   ├── search.py           # Full-text + suggestion search; cursor pagination
│   │   └── structure.py        # Article structure, links, related articles
│   └── tools/                  # MCP tool registrations — one module per v2 tool
│       ├── __init__.py         # register_phase_f_tools(); simple mode stops after zim_query
│       ├── _common.py          # description loader, rate limit, cursor decode, error envelope
│       ├── zim_query.py        # zim_query — NL entry point (registered in both tool modes)
│       ├── zim_search.py       # zim_search — fulltext/title/suggest, cross_file fan-out
│       ├── zim_get.py          # zim_get — single/batch/binary/main_page; view=full|summary|toc|structure
│       ├── zim_get_section.py  # zim_get_section — one named section of an article
│       ├── zim_browse.py       # zim_browse — namespace enumeration, mode=page|walk
│       ├── zim_metadata.py     # zim_metadata — M-namespace fields + namespace inventory
│       ├── zim_links.py        # zim_links — direction=outbound|inbound|related
│       ├── zim_health.py       # zim_health — health+config+archives, or archive validation
│       ├── *_description.md    # LLM-facing tool descriptions, loaded at import
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
- **`deps:`** - Dependency updates (triggers patch version bump)
- **`docs:`** - Documentation changes (triggers patch version bump)
- **`refactor:`** - Code refactoring (triggers patch version bump)
- **`revert:`** - Reverts (triggers patch version bump)
- **`style:`** - Code style changes (no version bump)
- **`test:`** - Test changes (no version bump)
- **`chore:`** - Maintenance tasks (no version bump)
- **`ci:`** - CI/CD changes (no version bump)
- **`build:`** - Build system changes (no version bump)

The rule is the changelog config, not the type name: any type with a **visible**
section in `release-please-config.json` cuts a release on its own. Only the
`hidden: true` types (`style`, `test`, `chore`, `ci`, `build`) are free.

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

### Documentation site

The docs site lives in `website/` (Astro + an MDX content collection) and needs
Node 22+. It is **not** built by `make check` — its gate is the `Website CI`
workflow, which runs on any PR that touches `website/`.

```bash
make site-build              # npm ci + astro check + astro build
make check-links             # internal links and heading anchors
make check-links EXTERNAL=1  # also probe every external URL
```

Each page under `website/src/content/docs/` needs four frontmatter fields:
`title`, `summary`, `group` (one of `Get started`, `Reference`, `Guides`,
`Operations` — the enum is pinned in `src/content.config.ts`, and a value
outside it fails the build) and `sidebar_order` (numbered **per group**, not
globally). Internal links use the full base path, e.g.
`/openzim-mcp/docs/api-reference/`, with a trailing slash.

Some doc facts are gated by tests rather than review — see
`tests/test_docs_freshness.py` for the schema footprint, version declarations
and API-reference signature parity, and `tests/test_mcpb_distribution.py` for
the release-please-stamped files.

### Test Markers

The project registers three custom markers:

```python
@pytest.mark.live               # Spawns a real server subprocess (deselected by default via addopts)
@pytest.mark.docker             # Additionally requires a running Docker daemon
@pytest.mark.requires_reranker  # Needs the [reranker] extra; auto-skipped when fastembed is missing
```

The first two are registered in `tests/conftest.py`, the third in
`tests/ml/conftest.py`.

### Running Specific Tests

```bash
# Run specific test file
uv run pytest tests/test_security.py -v

# Run tests with specific marker (the default addopts already deselect live tests)
uv run pytest -m "not live"

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

- Run security scans: `make security` (bandit code scan + pip-audit dependency scan)
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

1. **Check existing issues**
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

- [README.md](README.md) - Project overview and install/quick-start (the configuration and API reference live on the [docs site](https://cameronrye.github.io/openzim-mcp/docs/))
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

- **GitHub Issues**: For bugs, feature requests, and questions
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
| `deps:` | Dependencies | patch |
| `docs:` | Documentation | patch |
| `refactor:` | Refactored | patch |
| `revert:` | Reverted | patch |
| `chore:` / `ci:` / `build:` / `test:` / `style:` | hidden (no section) | none |

Every type above with a visible section cuts a release by itself. This is not
theoretical: **v3.2.2 was cut from a single `docs:` commit** and **v3.1.2 from a
single `deps:` commit**, with no `feat`/`fix`/`perf` in either range.

Breaking changes: append `!` to the type (`feat!:`) or include a `BREAKING CHANGE:` footer. Either form triggers a major bump.

### Automatic release flow

1. Land conventional commits on `main` via squash-merge.
2. `release-please.yml` opens a release PR (updates `CHANGELOG.md`, `pyproject.toml`, `.release-please-manifest.json`, `website/src/pages/llms.txt.ts`, `server.json`, `packaging/mcpb/manifest.json`, and the `x-release-please-version`-annotated docs; a follow-up `sync-uv-lock` job keeps `uv.lock` in step). `openzim_mcp/__init__.py` needs no stamp — it derives `__version__` via `importlib.metadata`.
3. Review and merge the release PR.
4. `release-please` pushes the `v<X.Y.Z>` tag and creates the GitHub Release. `release-please-config.json` sets `"draft": false`, so the release is **published immediately** — briefly with no assets attached.
5. `release-please.yml`'s `trigger-release` job dispatches `release.yml`: full `make check` gate → wheel + sdist + `.mcpb` bundle build → PyPI upload (Trusted Publishing, no token) → assets uploaded to the existing release (notes come from `CHANGELOG.md`). `release.yml` also runs a `publish-registry` job that publishes to the official MCP Registry via OIDC; it is deliberately *not* a dependency of `create-release`, so a registry hiccup cannot hold up the GitHub release.
6. `release-please.yml`'s `trigger-docker-publish` job dispatches `docker-publish.yml`: multi-arch build → push to `ghcr.io/cameronrye/openzim-mcp:<X.Y.Z>` and `:latest`.

Both workflows also declare a `push: tags: v*` trigger, but that trigger never fires for an automated release: release-please pushes the tag with `GITHUB_TOKEN`, and GitHub deliberately does not start workflow runs from `GITHUB_TOKEN`-authored events. The explicit `workflow_dispatch` calls in steps 5 and 6 are what actually start them — which is why every automated release run shows up as `workflow_dispatch`. The `push: tags` trigger exists for the manual path below.

`release.yml`'s "Publish draft release" step is therefore a no-op on the release-please path (the release is already published) and only does real work on the manual-tag path, where `release.yml` creates the release as a draft, uploads assets, then publishes — the order that keeps assets attachable under GitHub's immutable-releases behavior.

### Manual / emergency release

For tag-only releases when `release-please` isn't appropriate:

```bash
git tag v<X.Y.Z>
git push origin v<X.Y.Z>
```

`release.yml` and `docker-publish.yml` fire directly on the tag push and run the normal release pipeline.

### Troubleshooting

- **No release PR after merging commits**: check commit messages are conventional. Only the `hidden: true` types (`chore`, `ci`, `build`, `test`, `style`) fail to bump a version on their own.
- **`test_no_unannotated_current_version_claims` fails after a release**: a doc states the new version without an `x-release-please-version` marker, or `_HISTORICAL_VERSIONS` in `tests/test_mcpb_distribution.py` has not been given the *previous* version yet. This gate runs after the tag is pushed, so it fails on `main` rather than blocking the release PR — add the previous version to that set as part of the follow-up.
- **Version sync failure**: `pyproject.toml`, `.release-please-manifest.json`, `server.json` (both version fields), and `packaging/mcpb/manifest.json` must agree on the version (`openzim_mcp/__init__.py` is intentionally excluded — it reads its version via `importlib.metadata`). If they drift (rare; usually a manual edit), align them in a follow-up PR.
- **PyPI upload failure with "already exists"**: harmless; the workflow uses `skip-existing: true`. A true conflict (same version, different artifact) requires bumping the version.

### Source files

- [`release-please-config.json`](release-please-config.json)
- [`.github/workflows/release-please.yml`](.github/workflows/release-please.yml)
- [`.github/workflows/release.yml`](.github/workflows/release.yml)
- [`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml)

---

Thank you for contributing to OpenZIM MCP!
