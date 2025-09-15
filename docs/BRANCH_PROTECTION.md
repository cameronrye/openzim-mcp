# Branch Protection Rules

This document outlines the recommended branch protection rules for the zimp repository to ensure code quality and security.

## Recommended Settings

### Main Branch Protection

Configure the following settings for the `main` branch in GitHub repository settings:

#### General Settings
- ✅ **Restrict pushes that create files larger than 100 MB**
- ✅ **Restrict pushes that create files larger than a specified limit**: 50 MB

#### Branch Protection Rules for `main`

1. **Require a pull request before merging**
   - ✅ Require approvals: **1**
   - ✅ Dismiss stale PR approvals when new commits are pushed
   - ✅ Require review from code owners (when CODEOWNERS file is present)
   - ✅ Restrict pushes that create files larger than 100 MB

2. **Require status checks to pass before merging**
   - ✅ Require branches to be up to date before merging
   - **Required status checks:**
     - `Test Python 3.12 on ubuntu-latest`
     - `Test Python 3.12 on windows-latest`
     - `Test Python 3.12 on macos-latest`
     - `Test Python 3.13 on ubuntu-latest`
     - `Security Scanning`
     - `CodeQL`

3. **Require conversation resolution before merging**
   - ✅ All conversations on code must be resolved

4. **Require signed commits**
   - ✅ Require signed commits (recommended for security)

5. **Require linear history**
   - ✅ Require linear history (prevents merge commits)

6. **Include administrators**
   - ✅ Include administrators (applies rules to admins too)

7. **Allow force pushes**
   - ❌ Do not allow force pushes

8. **Allow deletions**
   - ❌ Do not allow deletions

### Develop Branch Protection (if used)

If using a `develop` branch for integration:

1. **Require a pull request before merging**
   - ✅ Require approvals: **1**
   - ✅ Dismiss stale PR approvals when new commits are pushed

2. **Require status checks to pass before merging**
   - ✅ Require branches to be up to date before merging
   - **Required status checks:**
     - `Test Python 3.12 on ubuntu-latest`
     - `Security Scanning`

## Setting Up Branch Protection

### Via GitHub Web Interface

1. Go to your repository on GitHub
2. Click **Settings** tab
3. Click **Branches** in the left sidebar
4. Click **Add rule** or edit existing rule
5. Configure the settings as outlined above

### Via GitHub CLI

```bash
# Install GitHub CLI if not already installed
# https://cli.github.com/

# Set up main branch protection
gh api repos/:owner/:repo/branches/main/protection \
  --method PUT \
  --field required_status_checks='{"strict":true,"contexts":["Test Python 3.12 on ubuntu-latest","Test Python 3.12 on windows-latest","Test Python 3.12 on macos-latest","Test Python 3.13 on ubuntu-latest","Security Scanning","CodeQL"]}' \
  --field enforce_admins=true \
  --field required_pull_request_reviews='{"required_approving_review_count":1,"dismiss_stale_reviews":true}' \
  --field restrictions=null \
  --field required_linear_history=true \
  --field allow_force_pushes=false \
  --field allow_deletions=false
```

## Code Owners (Optional)

Create a `.github/CODEOWNERS` file to automatically request reviews from specific people or teams:

```
# Global owners
* @maintainer-username

# Python code
*.py @python-team

# Documentation
*.md @docs-team
docs/ @docs-team

# CI/CD
.github/ @devops-team

# Configuration
pyproject.toml @maintainer-username
```

## Verification

After setting up branch protection:

1. Try to push directly to `main` - should be blocked
2. Create a test PR without required checks - should not be mergeable
3. Verify that all required status checks appear in PR

## Troubleshooting

### Status Checks Not Appearing

- Ensure the workflow names in branch protection match exactly with workflow job names
- Check that workflows are enabled in repository settings
- Verify workflows run on pull requests to the protected branch

### Cannot Merge Despite Passing Checks

- Check if all conversations are resolved
- Verify branch is up to date with base branch
- Ensure all required reviewers have approved

### Emergency Procedures

In case of emergency (critical security fix):

1. Repository admins can temporarily disable branch protection
2. Apply the fix
3. Re-enable branch protection immediately
4. Create a post-incident review

## Best Practices

1. **Regular Review**: Review and update branch protection rules quarterly
2. **Team Training**: Ensure all team members understand the workflow
3. **Documentation**: Keep this document updated with any changes
4. **Monitoring**: Monitor for any bypasses or issues with the protection rules

## Related Documentation

- [Contributing Guidelines](../CONTRIBUTING.md)
- [Security Policy](../SECURITY.md)
- [Development Setup](../README.md#development)
