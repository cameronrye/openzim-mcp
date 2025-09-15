# Deployment Guide

This guide explains how to properly deploy the openzim-mcp package to PyPI.

## Problem Background

The PyPI deployment was failing due to GitHub environment protection rules. The `pypi` environment is configured to only allow deployments from version tag branches, not from the `main` branch. This is a security best practice to ensure only tagged releases are published.

## Solution

We've implemented a two-workflow solution:

1. **Manual Release Workflow** (`manual-release.yml`) - For creating and triggering releases safely
2. **Release Workflow** (`release.yml`) - The main release workflow that handles building and publishing

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

If you need to create a manual release:

1. **Use the Manual Release Workflow**:
   - Go to Actions → Manual Release
   - Click "Run workflow"
   - Enter the tag name (e.g., `v0.3.2`)
   - Choose whether to create the tag if it doesn't exist
   - Click "Run workflow"

2. **The workflow will**:
   - Validate the tag format
   - Create the tag if requested
   - Trigger the main release workflow from the correct tag context

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

## Troubleshooting

### "Branch 'main' is not allowed to deploy to pypi"

This error occurs when:
- The release workflow is triggered manually from the main branch
- The workflow_dispatch doesn't specify a valid tag

**Solution**: Use the Manual Release workflow instead of triggering the Release workflow directly.

### "Tag does not exist"

This error occurs when:
- You specify a tag that doesn't exist in the repository
- There's a typo in the tag name

**Solution**: 
- Check existing tags: `git tag -l`
- Use the Manual Release workflow with `create_tag: true`
- Create the tag manually first

### PyPI Upload Fails

If the PyPI upload itself fails:
- Check if the version already exists on PyPI
- Verify the package builds correctly
- Check PyPI trusted publishing configuration

## Workflow Files

- `.github/workflows/release.yml` - Main release workflow (triggered by tags)
- `.github/workflows/manual-release.yml` - Safe manual release workflow
- `.github/workflows/release-please.yml` - Automated version management

## Security Notes

- Only tagged releases are published to PyPI
- The `pypi` environment requires proper authentication
- Trusted publishing is used for secure PyPI uploads
- Manual releases require explicit confirmation steps
