# 🎯 Dual-Mode Support: Full Mode + Simple Mode

## Summary

This PR introduces dual-mode support for openzim-mcp, allowing users to choose between:
- **Full Mode** (default): All 15 specialized MCP tools for maximum control
- **Simple Mode**: 1 intelligent natural language tool for simplified interaction

This feature makes openzim-mcp accessible to LLMs with limited tool-calling capabilities while preserving full functionality for advanced use cases.

## 🚀 Features

### Simple Mode
- **Single intelligent tool**: `zim_query` accepts natural language queries
- **Intent parsing**: Automatically detects user intent from 11 query types
- **Auto-selection**: Automatically selects ZIM file when only one exists
- **Smart routing**: Routes queries to appropriate underlying operations

### Configuration
- Command line: `--mode simple` or `--mode full`
- Environment variable: `OPENZIM_MCP_TOOL_MODE=simple`
- Default: Full mode (backward compatible)

## 📁 Files Changed

### New Files (4)
- `openzim_mcp/simple_tools.py` - Intent parser and handler (445 lines)
- `tests/test_simple_tools.py` - 27 test cases (277 lines)
- `docs/SIMPLE_MODE_GUIDE.md` - Comprehensive user guide (333 lines)
- `IMPLEMENTATION_SUMMARY.md` - Technical documentation

### Modified Files (6)
- `openzim_mcp/constants.py` - Added tool mode constants
- `openzim_mcp/config.py` - Added tool_mode configuration field
- `openzim_mcp/server.py` - Mode-based tool registration
- `openzim_mcp/main.py` - Added --mode CLI argument
- `README.md` - Updated with dual-mode information
- `uv.lock` - Dependency lock file update

## ✅ Testing

- **312 total tests** - All passing ✅
- **27 new tests** for simple tools functionality
- **79% overall code coverage** (77% for simple_tools.py)
- **No regressions** - All existing tests pass
- **Multi-platform tested** (Ubuntu, Windows, macOS via CI)

## 📚 Documentation

- ✅ Complete Simple Mode Guide with examples
- ✅ Updated README with dual-mode info
- ✅ Implementation summary document
- ✅ Code docstrings and type annotations
- ✅ Comparison table: Full vs Simple mode

## 🔄 Breaking Changes

**None** - This is a backward-compatible feature addition.
- Default mode is "full" (existing behavior)
- All existing tools work unchanged
- Simple mode is opt-in

## 🎯 Use Cases

### Simple Mode Best For:
- LLMs with limited tool-calling capabilities
- Reduced context window usage
- Conversational AI applications
- Simpler integrations

### Full Mode Best For:
- Advanced LLMs (Claude, GPT-4, etc.)
- Maximum control and flexibility
- Power users
- Complex workflows

## 📊 Metrics

- Lines of code added: ~1,000
- Test coverage: 77% (simple_tools.py), 79% (overall)
- Documentation: 600+ lines
- Supported query types: 11
- Tools in simple mode: 1 (vs 15 in full mode)

## 🔗 Related Documentation

- [Simple Mode Guide](docs/SIMPLE_MODE_GUIDE.md)
- [Implementation Summary](IMPLEMENTATION_SUMMARY.md)
- [Deployment Plan](DEPLOYMENT_PLAN.md)

## ✨ Examples

### Simple Mode Usage
```bash
# Enable simple mode
openzim-mcp --mode simple /path/to/zim/files

# Natural language queries
"search for biology"
"get article Evolution"
"show structure of DNA"
"list available files"
```

### Full Mode Usage (Default)
```bash
# Full mode (default)
openzim-mcp /path/to/zim/files

# Use specific tools
list_zim_files()
search_zim_file(path, query)
get_zim_entry(path, entry)
```

## 🧪 Test Results

```
============================= 312 passed in 37.22s =============================

Coverage:
- openzim_mcp/simple_tools.py: 77%
- openzim_mcp/config.py: 97%
- openzim_mcp/constants.py: 100%
- openzim_mcp/main.py: 92%
- openzim_mcp/server.py: 60%
- Overall: 79%
```

## 🎉 Ready to Merge

- ✅ All 312 tests passing
- ✅ Documentation complete
- ✅ Backward compatible
- ✅ Code quality checks pass
- ✅ Security scans pass
- ✅ Type checking passes

## 📝 Conventional Commit

This PR follows conventional commits and will trigger a **minor version bump** (0.5.1 → 0.6.0) when merged, as it introduces a new feature while maintaining backward compatibility.

## 🔍 Review Checklist

- [ ] Code changes reviewed
- [ ] Tests reviewed and passing
- [ ] Documentation reviewed
- [ ] No security concerns
- [ ] Backward compatibility verified
- [ ] CI/CD checks passing

