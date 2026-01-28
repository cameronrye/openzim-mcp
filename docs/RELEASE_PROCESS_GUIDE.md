# Release Process Guide

This is a quick reference for the openzim-mcp release system. For comprehensive documentation, see the [Release System Guide](../wiki-content/Release-System-Guide.md) in the wiki.

## Quick Start

### Automated Releases (Recommended)

1. **Make changes with conventional commits:**

   ```bash
   git commit -m "feat: add new feature"    # Minor version bump
   git commit -m "fix: resolve bug"         # Patch version bump
   git commit -m "feat!: breaking change"   # Major version bump
   ```

2. **Push to main** - Release Please creates a PR automatically
3. **Merge the release PR** - Triggers automated release to PyPI

### Manual/Emergency Releases

```bash
# Direct tag push for emergencies
git tag v0.6.3
git push origin v0.6.3
```

Or use GitHub Actions → Release → Run workflow.

## Key Points

- **Conventional commits** drive automatic versioning
- **Release Please** manages changelog and version bumps
- **PyPI publishing** uses trusted publishing (no tokens needed)
- **All tests must pass** before release

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Version mismatch | Check pyproject.toml and **init**.py match |
| PyPI upload fails | Version may already exist; increment version |
| Tests fail | Fix tests, push to main, re-run release |

## Related Documentation

- [Release System Guide](../wiki-content/Release-System-Guide.md) - Comprehensive guide
- [Automated Versioning Setup](AUTOMATED_VERSIONING.md)
- [Deployment Guide](DEPLOYMENT_GUIDE.md)
- [Branch Protection Rules](BRANCH_PROTECTION.md)
- [Contributing Guidelines](../CONTRIBUTING.md)
