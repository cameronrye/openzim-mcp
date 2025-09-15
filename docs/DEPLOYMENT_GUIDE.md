# Deployment Guide

This guide explains how to properly deploy the openzim-mcp package to PyPI using the improved release system.

## System Overview

The release system has been completely redesigned for reliability and simplicity:

✅ **Single consolidated workflow** (`release.yml`)
✅ **Automatic version synchronization validation**
✅ **Improved release notes extraction**
✅ **Multiple trigger methods for flexibility**
✅ **Comprehensive error handling and rollback**

## Key Improvements

- **Fixed version synchronization issues** that were causing deployment failures
- **Consolidated workflows** to eliminate confusion and conflicts
- **Enhanced validation** to catch issues before deployment
- **Better error messages** for faster troubleshooting
- **Branch protection rules** to prevent direct pushes to main

## How to Deploy

### Method 1: Automatic Release (Recommended)

1. **Use Release Please**: The repository uses release-please for automated versioning
   ```bash
   # Make changes with conventional commits
   git commit -m "feat: add new feature"
   git commit -m "fix: resolve bug"
   
   # Push to main - this triggers release-please
   git push origin main
   ```

2. **Merge Release PR**: Release-please will create a PR with version bump and changelog
   - Review and merge the release PR
   - This automatically creates a tag and triggers the release workflow

### Method 2: Manual Release

The consolidated release workflow now supports manual releases directly:

1. **Go to Actions → Release**
2. **Click "Run workflow"**
3. **Choose your options:**
   - **For new release:** Leave tag empty, set `create_tag: true`, choose release type
   - **For existing tag:** Enter tag name, set `create_tag: false`
4. **Click "Run workflow"**

The workflow will:
- Validate inputs and tag format
- Create tag if requested (with automatic version increment)
- Run full test suite
- Build and publish to PyPI
- Create GitHub release with proper release notes

### Method 3: Direct Tag Push (Advanced)

For advanced users who want direct control:

1. **Create and push a tag**:
   ```bash
   git tag v0.3.2
   git push origin v0.3.2
   ```

2. **This automatically triggers the release workflow**

## Environment Protection Rules

The `pypi` environment has protection rules that:
- ✅ Allow deployments from version tag branches (e.g., `v0.2.0`)
- ❌ Reject deployments from the `main` branch
- ✅ Allow deployments when triggered by tag pushes
- ❌ Reject deployments when triggered by workflow_dispatch from main

## Validation and Safety Features

### Automatic Version Validation
- **Pre-release checks** ensure all version files are synchronized
- **Build validation** confirms package builds successfully
- **Test validation** runs full test suite before deployment
- **Environment protection** prevents deployments from wrong contexts

### Error Prevention
- **Tag validation** ensures proper semantic versioning format
- **Duplicate prevention** checks for existing tags/versions
- **Branch protection** requires PR reviews and status checks
- **Rollback capabilities** for failed deployments

## Troubleshooting

### Version Synchronization Issues
**Error**: "Version mismatch detected!"
**Solution**: See [Release Troubleshooting Guide](RELEASE_TROUBLESHOOTING.md#version-synchronization-failure)

### Release Notes Missing
**Error**: "Release notes not found in CHANGELOG.md"
**Solution**: The improved extraction script now handles this automatically with fallback notes

### PyPI Upload Failures
**Error**: Various PyPI-related errors
**Solution**: Check [Release Troubleshooting Guide](RELEASE_TROUBLESHOOTING.md#pypi-deployment-rejection)

## Workflow Files

- `.github/workflows/release.yml` - **Consolidated release workflow** (handles all release types)
- `.github/workflows/release-please.yml` - **Automated version management**
- ~~`.github/workflows/manual-release.yml`~~ - **Removed** (functionality merged into main workflow)

## Security Notes

- Only tagged releases are published to PyPI
- The `pypi` environment requires proper authentication
- Trusted publishing is used for secure PyPI uploads
- Manual releases require explicit confirmation steps
