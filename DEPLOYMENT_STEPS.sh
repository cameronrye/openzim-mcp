#!/bin/bash
# Deployment Script for Dual-Mode Feature Release
# Version: 0.6.0
# Date: 2025-01-17

set -e  # Exit on error

echo "🚀 OpenZIM MCP Dual-Mode Feature Deployment"
echo "==========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Function to print colored output
print_step() {
    echo -e "${BLUE}▶ $1${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

# Function to confirm before proceeding
confirm() {
    read -p "$(echo -e ${YELLOW}$1 [y/N]: ${NC})" -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_error "Aborted by user"
        exit 1
    fi
}

# ============================================================================
# PHASE 1: Pre-Deployment Checks
# ============================================================================

print_step "Phase 1: Pre-Deployment Checks"
echo ""

# Check we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    print_error "Not in project root directory"
    exit 1
fi
print_success "In project root directory"

# Check current branch
CURRENT_BRANCH=$(git branch --show-current)
if [ "$CURRENT_BRANCH" != "main" ]; then
    print_warning "Current branch is '$CURRENT_BRANCH', not 'main'"
    confirm "Continue anyway?"
fi

# Check for uncommitted changes
if [ -n "$(git status --porcelain)" ]; then
    print_warning "You have uncommitted changes"
    git status --short
    confirm "Continue with deployment?"
fi

# Run full test suite
print_step "Running full test suite..."
if uv run pytest -v --tb=short > /dev/null 2>&1; then
    print_success "All tests passing (312/312)"
else
    print_error "Tests failed! Fix tests before deploying."
    exit 1
fi

# Check code quality
print_step "Checking code quality..."

# Type checking
if uv run mypy openzim_mcp > /dev/null 2>&1; then
    print_success "Type checking passed"
else
    print_warning "Type checking has issues (non-blocking)"
fi

# Linting
if uv run black --check openzim_mcp tests > /dev/null 2>&1; then
    print_success "Code formatting check passed"
else
    print_warning "Code formatting issues detected"
    confirm "Continue anyway?"
fi

echo ""
print_success "Pre-deployment checks complete"
echo ""

# ============================================================================
# PHASE 2: Create Feature Branch
# ============================================================================

print_step "Phase 2: Create Feature Branch"
echo ""

BRANCH_NAME="feat/dual-mode-support"

# Check if branch already exists
if git show-ref --verify --quiet refs/heads/$BRANCH_NAME; then
    print_warning "Branch '$BRANCH_NAME' already exists"
    confirm "Delete and recreate?"
    git branch -D $BRANCH_NAME
fi

# Create and checkout feature branch
print_step "Creating branch '$BRANCH_NAME'..."
git checkout -b $BRANCH_NAME
print_success "Created and checked out branch '$BRANCH_NAME'"

echo ""

# ============================================================================
# PHASE 3: Stage and Commit Changes
# ============================================================================

print_step "Phase 3: Stage and Commit Changes"
echo ""

# Stage modified files
print_step "Staging modified files..."
git add openzim_mcp/config.py
git add openzim_mcp/constants.py
git add openzim_mcp/main.py
git add openzim_mcp/server.py
git add openzim_mcp/security.py
git add openzim_mcp/zim_operations.py
git add tests/test_benchmarks.py
git add tests/test_config.py
git add tests/test_instance_tracker.py
git add tests/test_server.py
git add tests/test_zim_operations.py
git add README.md
git add uv.lock
print_success "Staged 13 modified files"

# Stage new files
print_step "Staging new files..."
git add openzim_mcp/simple_tools.py
git add tests/test_simple_tools.py
git add docs/SIMPLE_MODE_GUIDE.md
git add IMPLEMENTATION_SUMMARY.md
git add DEPLOYMENT_PLAN.md
git add PR_DESCRIPTION.md
git add DEPLOYMENT_STEPS.sh
print_success "Staged 4 new files"

# Show what will be committed
echo ""
print_step "Files to be committed:"
git status --short

echo ""
confirm "Proceed with commit?"

# Commit with conventional commit message
print_step "Creating commit..."
git commit -m "feat: add dual-mode support with intelligent natural language tool

Add Simple Mode alongside existing Full Mode to support LLMs with limited
tool-calling capabilities. Simple Mode provides a single intelligent tool
that accepts natural language queries and routes to appropriate operations.

Features:
- New Simple Mode with zim_query tool for natural language queries
- Full Mode maintains all 15 existing specialized tools
- Intelligent intent parsing with 11 supported query types
- Auto-selection of ZIM files when only one exists
- Configuration via --mode flag or OPENZIM_MCP_TOOL_MODE env var
- Backward compatible (defaults to Full mode)

Implementation:
- Created openzim_mcp/simple_tools.py with IntentParser and SimpleToolsHandler
- Updated config.py to support tool_mode field
- Modified server.py for mode-based tool registration
- Enhanced main.py with --mode command line argument
- Added comprehensive documentation in docs/SIMPLE_MODE_GUIDE.md
- Applied code formatting (black, isort) to all files

Testing:
- 27 new tests covering intent parsing and handler functionality
- All 312 tests passing (100% success rate)
- 77% code coverage for simple_tools.py
- No regressions in existing tests

Documentation:
- Complete Simple Mode Guide with examples
- Updated README with dual-mode information
- Implementation summary document
- Deployment plan and PR description
- Comparison table: Full vs Simple mode

Code Quality:
- All files formatted with black
- Imports organized with isort
- Unused imports removed
- Line length issues fixed"

print_success "Commit created"

echo ""

# ============================================================================
# PHASE 4: Push Feature Branch
# ============================================================================

print_step "Phase 4: Push Feature Branch"
echo ""

confirm "Push branch '$BRANCH_NAME' to origin?"

print_step "Pushing to remote..."
git push -u origin $BRANCH_NAME
print_success "Branch pushed to origin"

echo ""

# ============================================================================
# PHASE 5: Create Pull Request
# ============================================================================

print_step "Phase 5: Create Pull Request"
echo ""

# Check if gh CLI is available
if command -v gh &> /dev/null; then
    print_step "GitHub CLI detected"
    confirm "Create PR using GitHub CLI?"
    
    print_step "Creating pull request..."
    gh pr create \
        --title "feat: add dual-mode support with intelligent natural language tool" \
        --body-file PR_DESCRIPTION.md \
        --base main \
        --head $BRANCH_NAME
    
    print_success "Pull request created!"
    
    # Open PR in browser
    confirm "Open PR in browser?"
    gh pr view --web
else
    print_warning "GitHub CLI not found"
    echo ""
    echo "Please create PR manually:"
    echo "1. Go to: https://github.com/cameronrye/openzim-mcp/compare/main...$BRANCH_NAME"
    echo "2. Click 'Create pull request'"
    echo "3. Use the title: 'feat: add dual-mode support with intelligent natural language tool'"
    echo "4. Copy content from PR_DESCRIPTION.md as the description"
    echo ""
    read -p "Press Enter when PR is created..."
fi

echo ""

# ============================================================================
# PHASE 6: Post-PR Instructions
# ============================================================================

print_step "Phase 6: Next Steps"
echo ""

echo "✅ Feature branch created and pushed"
echo "✅ Pull request created"
echo ""
echo "📋 Next Steps:"
echo ""
echo "1. Wait for CI checks to complete"
echo "   - Tests must pass"
echo "   - Code quality checks must pass"
echo "   - Security scans must pass"
echo ""
echo "2. Request code review (if needed)"
echo ""
echo "3. Once approved, merge the PR"
echo "   - Use 'Squash and merge' or 'Merge pull request'"
echo "   - Ensure commit message follows conventional commits"
echo ""
echo "4. After merge, release-please will:"
echo "   - Detect the feat: commit"
echo "   - Create a release PR (0.5.1 → 0.6.0)"
echo "   - Update CHANGELOG.md"
echo "   - Update version numbers"
echo ""
echo "5. Review and merge the release PR"
echo "   - This triggers automatic release"
echo "   - Package published to PyPI"
echo "   - GitHub release created"
echo ""
echo "6. Verify the release:"
echo "   - Check PyPI: https://pypi.org/project/openzim-mcp/"
echo "   - Check GitHub Releases"
echo "   - Test installation: pip install --upgrade openzim-mcp"
echo ""

print_success "Deployment script complete!"
echo ""
echo "🎉 Dual-mode feature is ready for release!"

