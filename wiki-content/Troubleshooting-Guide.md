# Troubleshooting Guide

Common issues, error messages, and solutions for OpenZIM MCP.

## 🚨 Quick Diagnostics

### Health Check Command

First, run the server health check to identify issues:

```bash
# In your MCP client, ask:
"Check the server health and diagnose any issues"
```

This will run `get_server_health` and `diagnose_server_state` to identify problems.

## 🔧 Installation Issues

### Python Version Problems

**Error**: `Python 3.12+ required`

**Symptoms**:
- Server fails to start
- Import errors during installation

**Solutions**:
1. **Check Python version**: `python --version`
2. **Install Python 3.12+**: Visit [python.org](https://python.org)
3. **Use correct Python**: `python3.12 -m openzim_mcp`

### Package Installation Failures

**Error**: `uv not found` or `pip install failed`

**Solutions**:
1. **Install uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. **Use pip instead**: `pip install -e .`
3. **Check permissions**: Ensure write access to installation directory

### Virtual Environment Issues

**Error**: `ModuleNotFoundError: No module named 'openzim_mcp'`

**Solutions**:
1. **Activate virtual environment**:
   ```bash
   # Windows
   venv\Scripts\activate
   # macOS/Linux
   source venv/bin/activate
   ```
2. **Reinstall in virtual environment**: `pip install -e .`

## 📁 ZIM File Issues

### No ZIM Files Found

**Error**: `No ZIM files found in directory`

**Symptoms**:
- Empty file list from `list_zim_files`
- Server starts but no content available

**Solutions**:
1. **Check directory path**: Verify the path exists and is correct
2. **Check file extensions**: Ensure files have `.zim` extension
3. **Check permissions**: Ensure read access to directory and files
4. **Download ZIM files**: Get files from [Kiwix Library](https://browse.library.kiwix.org/)

### Permission Denied

**Error**: `Permission denied: '/path/to/zim/files'`

**Solutions**:
1. **Fix directory permissions**: `chmod 755 /path/to/zim/files`
2. **Fix file permissions**: `chmod 644 /path/to/zim/files/*.zim`
3. **Run as correct user**: Ensure user has read access
4. **Check SELinux/AppArmor**: May block file access on some systems

### Corrupted ZIM Files

**Error**: `Failed to open ZIM file` or `Invalid ZIM format`

**Symptoms**:
- Search operations fail
- Content retrieval errors
- Metadata extraction fails

**Solutions**:
1. **Verify file integrity**: Re-download the ZIM file
2. **Check file size**: Compare with expected size from download source
3. **Test with different file**: Try a known-good ZIM file
4. **Check disk space**: Ensure sufficient space for file operations

## 🔌 MCP Client Configuration

### Server Not Responding

**Error**: `Connection refused` or `Server timeout`

**Symptoms**:
- MCP client can't connect
- Commands hang or timeout
- No response from server

**Solutions**:
1. **Check server process**: Ensure server is running
2. **Verify configuration**: Check MCP client config file
3. **Check paths**: Ensure all paths in config are correct
4. **Restart client**: Restart MCP client application
5. **Check logs**: Look for error messages in server output

### Configuration File Issues

**Error**: `Invalid configuration` or `Command not found`

**Common Issues**:
```json
// ❌ Wrong - missing directory parameter
{
  "command": "python",
  "args": ["-m", "openzim_mcp"]
}

// ✅ Correct - includes directory and ZIM path
{
  "command": "uv",
  "args": [
    "--directory", "/path/to/openzim-mcp",
    "run", "python", "-m", "openzim_mcp",
    "/path/to/zim/files"
  ]
}
```

**Solutions**:
1. **Validate JSON**: Use a JSON validator to check syntax
2. **Check paths**: Ensure all paths exist and are accessible
3. **Use absolute paths**: Avoid relative paths in configuration
4. **Test command manually**: Run the command in terminal first

## 🔍 Search and Content Issues

### No Search Results

**Error**: `No matches found` or empty search results

**Possible Causes**:
1. **Typos in search terms**: Check spelling
2. **Content not in ZIM file**: Verify content exists
3. **Wrong namespace**: Try different namespaces
4. **Search index issues**: ZIM file may lack search index

**Solutions**:
1. **Try broader terms**: Use more general search terms
2. **Browse namespaces**: Use `browse_namespace` to explore content
3. **Check ZIM metadata**: Use `get_zim_metadata` to understand content
4. **Try different ZIM files**: Test with known-good content

### Entry Not Found

**Error**: `Entry not found: 'A/Article_Name'`

**Smart Retrieval**: OpenZIM MCP automatically tries to find entries with different encodings, but sometimes manual intervention is needed.

**Solutions**:
1. **Use search first**: Search for the article title
2. **Check exact path**: Use `browse_namespace` to find correct path
3. **Try different encodings**: 
   - `A/Article_Name` vs `A/Article%20Name`
   - `A/Article_Name` vs `A/Article-Name`
4. **Check namespace**: Ensure correct namespace (A, C, etc.)

### Content Truncation

**Issue**: Content appears cut off

**Cause**: `max_content_length` parameter limiting content

**Solutions**:
1. **Increase limit**: Use higher `max_content_length` value
2. **Get structure first**: Use `get_article_structure` to understand content
3. **Request specific sections**: Target specific parts of long articles

## ⚡ Performance Issues

### Slow Response Times

**Symptoms**:
- Long delays for search results
- Timeouts on large operations
- High memory usage

**Solutions**:
1. **Check cache settings**: Ensure caching is enabled
2. **Reduce result limits**: Use smaller `limit` values
3. **Monitor server health**: Check cache hit rates
4. **Optimize ZIM files**: Use smaller or more focused ZIM files
5. **Increase system resources**: More RAM helps with large ZIM files

### Memory Issues

**Error**: `Out of memory` or system becomes unresponsive

**Solutions**:
1. **Reduce cache size**: Lower `OPENZIM_MCP_CACHE__MAX_SIZE`
2. **Use smaller ZIM files**: Start with smaller content sets
3. **Limit concurrent operations**: Avoid multiple large operations
4. **Increase system RAM**: 2GB+ recommended for large ZIM files

### Cache Problems

**Issue**: Poor cache performance or cache misses

**Diagnostics**:
```bash
# Check cache statistics
"Get server health and show cache performance"
```

**Solutions**:
1. **Increase cache size**: Raise `OPENZIM_MCP_CACHE__MAX_SIZE`
2. **Increase TTL**: Raise `OPENZIM_MCP_CACHE__TTL_SECONDS`
3. **Clear cache**: Restart server to clear cache
4. **Monitor hit rates**: Aim for >70% cache hit rate

## 🔒 Security Issues

### Path Traversal Warnings

**Error**: `Path traversal attempt detected`

**Cause**: Attempting to access files outside allowed directories

**Solutions**:
1. **Check file paths**: Ensure paths are within allowed directories
2. **Use relative paths**: Avoid `../` in file paths
3. **Verify configuration**: Check allowed directories setting

### Permission Errors

**Error**: `Access denied` or `Permission denied`

**Solutions**:
1. **Check file ownership**: Ensure correct user owns files
2. **Fix permissions**: Use `chmod` to set appropriate permissions
3. **Check parent directories**: Ensure all parent directories are accessible
4. **Avoid running as root**: Use appropriate user account

## 🔄 Multi-Instance Issues

### Server Conflicts

**Warning**: `Server conflict detected`

**Symptoms**:
- Inconsistent search results
- Configuration warnings
- Multiple server instances detected

**Solutions**:
1. **Run conflict resolution**: Use `resolve_server_conflicts`
2. **Stop duplicate servers**: Ensure only one server per directory
3. **Use consistent configuration**: Same settings across instances
4. **Clean stale instances**: Remove orphaned instance files

### Instance Tracking Problems

**Issue**: False conflict warnings

**Solutions**:
1. **Clean instance files**: Remove files in `~/.openzim_mcp_instances/`
2. **Restart server**: Fresh start clears tracking issues
3. **Check process IDs**: Ensure no zombie processes

## 🛠️ Advanced Debugging

### Enable Debug Logging

```bash
export OPENZIM_MCP_LOGGING__LEVEL=DEBUG
uv run python -m openzim_mcp /path/to/zim/files
```

### Check Server Logs

Look for error patterns in server output:
- `ERROR`: Critical errors requiring attention
- `WARNING`: Potential issues to investigate
- `INFO`: Normal operation messages

### Test with Minimal Setup

1. **Use small ZIM file**: Test with <100MB file
2. **Single operation**: Test one tool at a time
3. **Fresh environment**: Clean virtual environment
4. **Default configuration**: No custom environment variables

## 📞 Getting Help

### Before Asking for Help

1. **Check this guide**: Review relevant sections above
2. **Run diagnostics**: Use `diagnose_server_state`
3. **Check logs**: Look for error messages
4. **Test minimal case**: Reproduce with simple setup

### Where to Get Help

1. **GitHub Issues**: [Report bugs](https://github.com/cameronrye/openzim-mcp/issues)
2. **GitHub Discussions**: [Ask questions](https://github.com/cameronrye/openzim-mcp/discussions)
3. **Documentation**: Check other wiki pages

### Information to Include

When reporting issues, include:
- **Operating system** and version
- **Python version**: `python --version`
- **OpenZIM MCP version**: Check `pyproject.toml`
- **ZIM file details**: Size, source, name
- **Error messages**: Full error text
- **Configuration**: MCP client config (remove sensitive paths)
- **Steps to reproduce**: Exact commands used

---

**Still having issues?** Don't hesitate to [open an issue](https://github.com/cameronrye/openzim-mcp/issues) with detailed information about your problem.
