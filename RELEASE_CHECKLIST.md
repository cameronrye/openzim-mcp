# Release Checklist: v0.6.0 - Dual-Mode Feature

## 📋 Pre-Release Verification

### Code Quality
- [x] All 312 tests passing
- [x] 79% overall code coverage
- [x] 77% coverage for new simple_tools.py
- [ ] Type checking passes (mypy)
- [ ] Linting passes (black, isort, flake8)
- [ ] Security scan passes (bandit, safety)
- [ ] No critical code smells

### Documentation
- [x] Simple Mode Guide created (`docs/SIMPLE_MODE_GUIDE.md`)
- [x] README updated with dual-mode info
- [x] Implementation summary documented
- [x] PR description prepared
- [x] Deployment plan created
- [ ] API reference updated (if applicable)
- [ ] Wiki pages updated (if applicable)
- [ ] All documentation links verified

### Version Management
- [ ] Version bumped to 0.6.0 in `pyproject.toml`
- [ ] Version bumped to 0.6.0 in `openzim_mcp/__init__.py`
- [ ] `.release-please-manifest.json` updated to 0.6.0
- [ ] CHANGELOG entry prepared

---

## 🚀 Deployment Steps

### Phase 1: Branch & Commit
- [ ] Feature branch created (`feat/dual-mode-support`)
- [ ] All changes staged
- [ ] Conventional commit created
- [ ] Branch pushed to origin

**Command:**
```bash
./DEPLOYMENT_STEPS.sh
```

### Phase 2: Pull Request
- [ ] PR created with comprehensive description
- [ ] PR title follows conventional commits
- [ ] All CI checks passing
- [ ] Code review completed (if required)
- [ ] No merge conflicts
- [ ] Branch up to date with main

**PR URL:** _________________

### Phase 3: Merge to Main
- [ ] PR approved
- [ ] PR merged to main
- [ ] Feature branch deleted (optional)

**Merge Method:** Squash and merge / Merge commit

### Phase 4: Release-Please Automation
- [ ] Release-please PR created automatically
- [ ] Version bump verified (0.5.1 → 0.6.0)
- [ ] CHANGELOG.md updated correctly
- [ ] All version files synchronized
- [ ] Release PR reviewed

**Release PR URL:** _________________

### Phase 5: Release Publication
- [ ] Release PR merged
- [ ] Git tag created (v0.6.0)
- [ ] GitHub release created
- [ ] Package built successfully
- [ ] Package published to PyPI

**Release URL:** _________________

---

## ✅ Post-Release Verification

### PyPI Package
- [ ] Package visible on PyPI
- [ ] Version 0.6.0 listed
- [ ] Package metadata correct
- [ ] Installation works: `pip install openzim-mcp==0.6.0`
- [ ] Simple mode works: `openzim-mcp --mode simple /path/to/zim`
- [ ] Full mode works: `openzim-mcp /path/to/zim`

**PyPI URL:** https://pypi.org/project/openzim-mcp/0.6.0/

### GitHub Release
- [ ] Release v0.6.0 visible
- [ ] Release notes complete
- [ ] Assets attached (if applicable)
- [ ] Tag points to correct commit

**GitHub Release URL:** https://github.com/cameronrye/openzim-mcp/releases/tag/v0.6.0

### Documentation Site
- [ ] GitHub Pages updated
- [ ] Simple Mode Guide accessible
- [ ] All links working
- [ ] Examples tested

**Docs URL:** https://cameronrye.github.io/openzim-mcp/

### Functionality Testing
- [ ] Install from PyPI works
- [ ] Simple mode activates correctly
- [ ] Full mode works (default)
- [ ] Natural language queries work
- [ ] Intent parsing accurate
- [ ] Auto-selection works
- [ ] All 15 full mode tools work
- [ ] Configuration options work
- [ ] Environment variable works

**Test Commands:**
```bash
# Install
pip install --upgrade openzim-mcp==0.6.0

# Verify version
python -c "import openzim_mcp; print(openzim_mcp.__version__)"

# Test simple mode
openzim-mcp --mode simple /path/to/test/zim

# Test full mode
openzim-mcp /path/to/test/zim

# Test environment variable
export OPENZIM_MCP_TOOL_MODE=simple
openzim-mcp /path/to/test/zim
```

---

## 📢 Communication

### Announcements
- [ ] GitHub Discussions post
- [ ] Release notes published
- [ ] README badges updated
- [ ] Social media announcement (if applicable)
- [ ] Community notification

### Monitoring
- [ ] Monitor issue tracker for feedback
- [ ] Monitor PyPI download stats
- [ ] Monitor CI/CD for any issues
- [ ] Check for user reports

---

## 🔄 Rollback Plan (If Needed)

### Quick Fix
If minor issues discovered:
```bash
git checkout -b hotfix/fix-simple-mode-issue
# Make fixes
git commit -m "fix: resolve simple mode issue"
git push -u origin hotfix/fix-simple-mode-issue
# Create PR and merge
```

### Full Revert
If critical issues discovered:
```bash
# Revert the merge commit
git revert -m 1 <merge-commit-hash>
git push origin main

# Yank from PyPI (contact PyPI support)
# Or use: pip yank openzim-mcp==0.6.0
```

---

## 📊 Success Metrics

### Immediate (Day 1)
- [ ] Release published successfully
- [ ] No critical bugs reported
- [ ] Installation works for users
- [ ] Documentation accessible

### Short-term (Week 1)
- [ ] PyPI downloads increasing
- [ ] Positive user feedback
- [ ] No major issues reported
- [ ] Simple mode adoption visible

### Long-term (Month 1)
- [ ] Feature usage metrics collected
- [ ] User satisfaction measured
- [ ] Performance metrics stable
- [ ] Community engagement positive

---

## 📝 Notes

### Issues Encountered
_Document any issues encountered during deployment:_

- 

### Lessons Learned
_Document lessons learned for future releases:_

- 

### Follow-up Tasks
_Tasks to complete after release:_

- [ ] Update wiki with simple mode examples
- [ ] Create video tutorial (optional)
- [ ] Write blog post about feature (optional)
- [ ] Gather user feedback
- [ ] Plan next release

---

## ✍️ Sign-off

**Prepared by:** _________________  
**Date:** _________________  
**Release Manager:** _________________  
**Approved by:** _________________  

**Status:** ⬜ Not Started | ⬜ In Progress | ⬜ Complete | ⬜ Verified

---

## 🎉 Release Complete!

Once all items are checked:
1. Mark status as "Complete"
2. Archive this checklist
3. Begin monitoring phase
4. Plan next release

**Congratulations on releasing v0.6.0! 🚀**

