# Release Process Guide

This guide provides comprehensive instructions for the openzim-mcp release system, which has been redesigned for reliability and simplicity.

## Overview

The release system uses a **single consolidated workflow** with multiple trigger methods:

1. **Automated Releases** (Recommended) - via Release Please
2. **Manual Releases** - via GitHub Actions UI
3. **Emergency Releases** - via direct tag push

## 🚀 Release Methods

### Method 1: Automated Releases (Recommended)

This is the primary release method using conventional commits and Release Please.

#### Step 1: Make Changes with Conventional Commits
```bash
# Feature additions (minor version bump)
git commit -m "feat: add search suggestions endpoint"

# Bug fixes (patch version bump)  
git commit -m "fix: resolve path traversal vulnerability"

# Breaking changes (major version bump)
git commit -m "feat!: change API response format"
# OR
git commit -m "feat: change API response format

BREAKING CHANGE: API now returns structured response instead of plain text"

# Other changes (no version bump)
git commit -m "docs: update installation instructions"
git commit -m "chore: update dependencies"
```

#### Step 2: Push to Main
```bash
git push origin main
```

#### Step 3: Review and Merge Release PR
- Release Please automatically creates a PR with version bump and changelog
- Review the generated changes
- Merge the PR to trigger the release

#### Step 4: Automatic Release
- Tag is created automatically
- Release workflow runs automatically
- Package is built and published to PyPI
- GitHub release is created with release notes

### Method 2: Manual Releases

For emergency releases or when you need direct control:

#### Option A: Create New Release
1. Go to **Actions** → **Release**
2. Click **Run workflow**
3. Leave **tag** field empty
4. Set **create_tag** to `true`
5. Choose **release_type** (patch/minor/major)
6. Click **Run workflow**

#### Option B: Release Existing Tag
1. Go to **Actions** → **Release**
2. Click **Run workflow**
3. Enter existing **tag** (e.g., `v0.3.4`)
4. Set **create_tag** to `false`
5. Click **Run workflow**

### Method 3: Emergency Releases

For critical fixes that need immediate release:

```bash
# Create and push tag directly
git tag v0.3.4
git push origin v0.3.4
```

This automatically triggers the release workflow.

## 🔍 Release Validation

The system includes automatic validation:

### Version Synchronization Check
- Validates all version files match (pyproject.toml, __init__.py, manifest)
- Fails the release if versions are out of sync
- Provides clear error messages for debugging

### Pre-Release Testing
- Full test suite runs before any release
- Multi-platform testing (Ubuntu, Windows, macOS)
- Security scanning with Bandit and Safety
- Type checking with mypy

### Build Validation
- Package builds successfully
- All artifacts are created
- PyPI upload validation

## 📊 Monitoring Release Health

### GitHub Actions Dashboard
- Monitor workflow runs in the Actions tab
- Check for failed releases and error messages
- Review build logs for debugging

### Release Status Indicators
- ✅ **Green**: All steps completed successfully
- ⚠️ **Yellow**: Some steps skipped (usually expected)
- ❌ **Red**: Release failed - requires investigation

### Common Success Patterns
```
✅ Validate and Prepare Release (for manual releases)
✅ Test before release
✅ Build distribution  
✅ Publish to PyPI
✅ Create GitHub Release
```

## 🛠️ Troubleshooting

### Version Mismatch Errors
**Error**: "Version mismatch detected!"
**Solution**: 
1. Check which files have wrong versions
2. Update manually or create a fix commit
3. Re-run the release

### PyPI Upload Failures
**Error**: "File already exists" or "Version already published"
**Solution**:
1. Increment version number
2. Create new tag
3. Re-run release

### Test Failures
**Error**: Tests fail during release
**Solution**:
1. Fix the failing tests
2. Push fixes to main
3. Re-run release (for manual) or merge new release PR (for automated)

### Tag Creation Issues
**Error**: "Tag already exists"
**Solution**:
1. Use existing tag with `create_tag: false`
2. Or delete existing tag and recreate
3. Or increment version number

## 🔒 Security and Permissions

### Branch Protection
- Main branch requires PR reviews
- All status checks must pass
- No direct pushes allowed
- Linear history enforced

### Release Permissions
- Only maintainers can trigger manual releases
- Automated releases require PR approval
- PyPI publishing uses trusted publishing (no tokens)

### Environment Protection
- PyPI environment only allows deployments from tags
- Prevents accidental deployments from main branch

## 📈 Best Practices

### Commit Messages
- Use conventional commit format consistently
- Be descriptive in commit messages
- Group related changes in single commits

### Release Timing
- Avoid releases on Fridays or before holidays
- Test thoroughly in development before releasing
- Consider impact on downstream users

### Version Strategy
- Use semantic versioning (MAJOR.MINOR.PATCH)
- Reserve major versions for breaking changes
- Use patch versions for bug fixes
- Use minor versions for new features

## 🆘 Emergency Procedures

### Critical Security Fix
1. Create hotfix branch from latest release tag
2. Apply minimal fix
3. Use emergency release method (direct tag push)
4. Follow up with proper PR to main

### Rollback Release
1. Identify problematic release
2. Create new release with reverted changes
3. Communicate issue to users
4. Update documentation if needed

### System Recovery
If the release system is completely broken:
1. Check this troubleshooting guide
2. Review recent changes to workflows
3. Test with a patch release first
4. Contact maintainers if issues persist

## 📚 Related Documentation

- [Automated Versioning Setup](AUTOMATED_VERSIONING.md)
- [Deployment Guide](DEPLOYMENT_GUIDE.md)
- [Branch Protection Rules](BRANCH_PROTECTION.md)
- [Contributing Guidelines](../CONTRIBUTING.md)
