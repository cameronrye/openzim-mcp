# Release Troubleshooting Runbook

This runbook provides quick solutions for common release system issues.

## 🚨 Critical Issues

### Version Synchronization Failure

**Symptoms:**
- Release Please creates PR but versions don't match
- PyPI deployment fails with version conflicts
- `__init__.py` version differs from `pyproject.toml`

**Quick Fix:**
```bash
# Check current versions
grep 'version = ' pyproject.toml
grep '__version__ = ' openzim_mcp/__init__.py
cat .release-please-manifest.json

# Fix manually if needed
# Update __init__.py to match pyproject.toml
sed -i 's/__version__ = ".*"/__version__ = "X.Y.Z"/' openzim_mcp/__init__.py

# Update manifest
echo '{"." : "X.Y.Z"}' > .release-please-manifest.json

# Commit and push
git add .
git commit -m "fix: synchronize version numbers"
git push origin main
```

**Prevention:** The validation job now catches this automatically.

### Release Notes Extraction Failure

**Symptoms:**
- GitHub releases show "Release notes not found in CHANGELOG.md"
- Empty or generic release notes

**Quick Fix:**
1. Check CHANGELOG.md format around the version
2. Ensure version follows pattern: `## [X.Y.Z]` or `## X.Y.Z`
3. Manually edit release notes in GitHub UI if needed

**Root Cause:** The improved extraction script now handles multiple formats.

### PyPI Deployment Rejection

**Symptoms:**
- Error: "Branch 'main' is not allowed to deploy to pypi"
- Deployment fails with environment protection error

**Quick Fix:**
```bash
# Use the consolidated release workflow instead
# Go to Actions → Release → Run workflow
# Enter tag name and set create_tag: true
```

**Root Cause:** Environment protection rules require tag-based deployments.

## ⚠️ Common Issues

### Release Please Not Creating PR

**Symptoms:**
- Commits pushed to main but no release PR appears
- Release Please workflow runs but no output

**Diagnosis:**
```bash
# Check recent commits for conventional format
git log --oneline -10

# Check if commits follow conventional format
# Should see: feat:, fix:, docs:, etc.
```

**Solutions:**
1. **No conventional commits:** Add a conventional commit
   ```bash
   git commit --allow-empty -m "chore: trigger release"
   git push origin main
   ```

2. **Already at latest version:** Make a meaningful change
   ```bash
   git commit -m "feat: improve error handling"
   git push origin main
   ```

3. **Manual trigger:** Use GitHub Actions UI
   - Go to Actions → Release Please → Run workflow

### Test Failures During Release

**Symptoms:**
- Release workflow fails at test step
- Red X on test jobs

**Quick Diagnosis:**
```bash
# Run tests locally
make test
make test-cov
make lint
make type-check
```

**Solutions:**
1. **Fix tests locally:**
   ```bash
   # Fix the failing tests
   git add .
   git commit -m "fix: resolve test failures"
   git push origin main
   ```

2. **Skip tests for emergency release:**
   - Not recommended, but possible by editing workflow temporarily

### Build Failures

**Symptoms:**
- Package build fails
- Missing dependencies or import errors

**Diagnosis:**
```bash
# Test build locally
uv build
# Check for missing files or dependencies
```

**Solutions:**
1. **Missing files:** Update `pyproject.toml` includes
2. **Dependency issues:** Update `pyproject.toml` dependencies
3. **Import errors:** Check package structure

### Tag Already Exists

**Symptoms:**
- Error: "Tag vX.Y.Z already exists"
- Cannot create release

**Solutions:**
1. **Use existing tag:**
   - Go to Actions → Release → Run workflow
   - Enter existing tag, set `create_tag: false`

2. **Delete and recreate tag:**
   ```bash
   git tag -d v0.3.4
   git push origin :refs/tags/v0.3.4
   # Then create new release
   ```

3. **Increment version:**
   - Create new version instead

## 🔧 Diagnostic Commands

### Check Release System Health
```bash
# Verify all versions match
echo "pyproject.toml: $(grep 'version = ' pyproject.toml)"
echo "__init__.py: $(grep '__version__ = ' openzim_mcp/__init__.py)"
echo "manifest: $(cat .release-please-manifest.json)"

# Check recent releases
gh release list --limit 5

# Check workflow status
gh run list --workflow=release.yml --limit 5
gh run list --workflow=release-please.yml --limit 5
```

### Validate Release Configuration
```bash
# Check Release Please config
cat release-please-config.json | jq .

# Validate workflow syntax
gh workflow list
gh workflow view release.yml
```

### Test Release Components
```bash
# Test build process
uv build
ls -la dist/

# Test package installation
pip install dist/*.whl
python -c "import openzim_mcp; print(openzim_mcp.__version__)"
```

## 🚑 Emergency Procedures

### Complete Release System Failure

**When to use:** Multiple releases failing, system appears broken

**Steps:**
1. **Assess damage:**
   ```bash
   # Check recent workflow runs
   gh run list --limit 10
   
   # Check current state
   git status
   git log --oneline -5
   ```

2. **Emergency release bypass:**
   ```bash
   # Create tag manually and push
   git tag v0.3.5
   git push origin v0.3.5
   # This triggers basic release workflow
   ```

3. **System recovery:**
   - Revert recent workflow changes if needed
   - Test with patch release first
   - Contact maintainers

### Rollback Bad Release

**When to use:** Released version has critical issues

**Steps:**
1. **Immediate action:**
   ```bash
   # Create hotfix tag from previous good release
   git checkout v0.3.3  # Last good release
   git tag v0.3.6       # New hotfix version
   git push origin v0.3.6
   ```

2. **Communication:**
   - Update GitHub release notes with warning
   - Notify users via appropriate channels
   - Document the issue

3. **Follow-up:**
   - Create proper fix in main branch
   - Release corrected version
   - Update documentation

### PyPI Package Issues

**When to use:** Package on PyPI is broken or wrong

**Important:** You cannot delete or replace PyPI packages

**Steps:**
1. **Immediate fix:**
   ```bash
   # Create new patch version with fix
   git commit -m "fix: critical issue in v0.3.4"
   # Release as v0.3.5
   ```

2. **Mark bad version:**
   - Add warning to GitHub release notes
   - Consider yanking on PyPI (advanced users only)

## 📞 Escalation

### When to Escalate
- Multiple diagnostic attempts failed
- System-wide release failures
- Security-related release issues
- PyPI publishing completely broken

### How to Escalate
1. **Gather information:**
   - Recent workflow run URLs
   - Error messages and logs
   - Steps attempted
   - Current system state

2. **Contact maintainers:**
   - Create GitHub issue with "release-system" label
   - Include all diagnostic information
   - Mark as urgent if blocking releases

3. **Temporary workarounds:**
   - Use emergency release procedures
   - Document any manual steps taken
   - Communicate status to team

## 📚 Additional Resources

- [Release Process Guide](RELEASE_PROCESS_GUIDE.md)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Release Please Documentation](https://github.com/googleapis/release-please)
- [PyPI Publishing Guide](https://packaging.python.org/en/latest/guides/publishing-package-distribution-releases-using-github-actions-ci-cd-workflows/)
