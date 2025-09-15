# Automated Versioning Setup

This document explains the automated version bumping system implemented for the openzim-mcp project.

## Overview

The project now uses [release-please](https://github.com/googleapis/release-please) for automated version management based on [Conventional Commits](https://www.conventionalcommits.org/). This system automatically:

- Analyzes commit messages to determine version bump type
- Updates version numbers in all relevant files
- Generates and maintains CHANGELOG.md
- Creates GitHub releases with release notes
- Integrates with existing CI/CD pipeline

## How It Works

### 1. Conventional Commits

Commit messages follow the conventional commit format to trigger appropriate version bumps:

```
<type>[optional scope]: <description>

[optional body]

[optional footer(s)]
```

**Version Bump Types:**
- `feat:` → Minor version bump (0.2.0 → 0.3.0)
- `fix:` → Patch version bump (0.2.0 → 0.2.1)
- `feat!:` or `BREAKING CHANGE:` → Major version bump (0.2.0 → 1.0.0)
- `perf:` → Patch version bump (0.2.0 → 0.2.1)
- `docs:`, `style:`, `refactor:`, `test:`, `chore:` → No version bump

### 2. Automated Workflow

The release-please workflow (`.github/workflows/release-please.yml`) runs on:
- Every push to the `main` branch
- Manual workflow dispatch (for emergency releases)

**Process:**
1. Analyzes commits since last release
2. Determines appropriate version bump
3. Creates a "Release PR" with:
   - Updated version numbers
   - Updated CHANGELOG.md
   - All necessary file changes
4. When Release PR is merged:
   - Creates git tag
   - Triggers existing release workflow
   - Publishes to PyPI
   - Creates GitHub release

### 3. Files Updated Automatically

- `pyproject.toml` - Project version
- `openzim_mcp/__init__.py` - Package version
- `CHANGELOG.md` - Release notes

## Configuration Files

### `.github/workflows/release-please.yml`
Main workflow that handles version bumping and release PR creation.

### `release-please-config.json`
Configuration for release-please behavior:
- Package type: Python
- Changelog sections mapping
- File update patterns
- Release settings

### `.release-please-manifest.json`
Tracks current version state for release-please.

## Usage Examples

### Regular Development

```bash
# Feature addition
git commit -m "feat: add search suggestions endpoint"

# Bug fix
git commit -m "fix: resolve path traversal vulnerability"

# Documentation update
git commit -m "docs: update installation instructions"

# Performance improvement
git commit -m "perf: optimize ZIM file caching"
```

### Breaking Changes

```bash
# Method 1: Use exclamation mark
git commit -m "feat!: change API response format"

# Method 2: Use footer
git commit -m "feat: change API response format

BREAKING CHANGE: API now returns structured response instead of plain text"
```

### With Scope

```bash
git commit -m "feat(api): add new search endpoint"
git commit -m "fix(security): resolve path traversal issue"
git commit -m "docs(readme): update installation guide"
```

## Manual Release Process

For emergency releases or when automatic detection fails:

1. **Workflow Dispatch**: Use GitHub Actions UI to manually trigger release
2. **Choose Release Type**: Select patch, minor, or major
3. **Review Release PR**: Check generated changes
4. **Merge**: Complete the release process

## Integration with Existing Workflows

The automated versioning integrates seamlessly with existing workflows:

- **Testing**: All tests run before release PR creation
- **Building**: Existing build process unchanged
- **Publishing**: Existing PyPI publishing workflow continues to work
- **Security**: No additional permissions required

## Monitoring and Troubleshooting

### Checking Release Status

- **Release PRs**: Look for PRs titled "chore: release X.Y.Z"
- **Workflow Runs**: Check GitHub Actions for release-please runs
- **Tags**: Verify git tags are created correctly

### Common Issues

1. **No Release PR Created**: Check commit message format
2. **Wrong Version Bump**: Verify conventional commit types
3. **Missing Files**: Check release-please-config.json file patterns
4. **Workflow Failures**: Review GitHub Actions logs

### Manual Intervention

If automatic process fails:
1. Check workflow logs for errors
2. Manually create release PR if needed
3. Use workflow dispatch for emergency releases
4. Contact maintainers for complex issues

## Benefits

- **Consistency**: Standardized versioning across all releases
- **Automation**: Reduces manual release overhead
- **Transparency**: Clear changelog and release notes
- **Integration**: Works with existing development workflow
- **Flexibility**: Manual override options available

## Migration Notes

- Existing release workflow continues to work
- No changes to development process except commit messages
- Backward compatibility maintained
- Manual releases still possible as fallback

For more information, see:
- [Conventional Commits](https://www.conventionalcommits.org/)
- [release-please Documentation](https://github.com/googleapis/release-please)
- [Semantic Versioning](https://semver.org/)
