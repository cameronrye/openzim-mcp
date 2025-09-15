# Quick Start Tutorial

Get up and running with OpenZIM MCP in just a few minutes! This tutorial will walk you through your first successful setup and usage.

## 🎯 What You'll Learn

- How to set up OpenZIM MCP with a test ZIM file
- How to configure your MCP client
- How to perform basic searches and content retrieval
- How to verify everything is working correctly

## ⏱️ Time Required: ~10 minutes

## 📋 Before You Start

Make sure you have completed the [Installation Guide](Installation-Guide) and have:
- ✅ OpenZIM MCP installed
- ✅ Python 3.12+ available
- ✅ A ZIM file downloaded (we'll help you get one if needed)

## 🚀 Step 1: Get a Test ZIM File

### Option A: Download a Small Test File

```bash
# Create a directory for ZIM files
mkdir ~/zim-files
cd ~/zim-files

# Download a small Wikipedia subset (recommended for testing)
# Visit: https://browse.library.kiwix.org/
# Search for "Wikipedia English Top 100" (~300MB)
# Download and save to ~/zim-files/
```

### Option B: Use Our Test Data

```bash
# From your openzim-mcp directory
make download-test-data

# This downloads small test ZIM files to tests/data/
```

## 🔧 Step 2: Start the Server

```bash
# Navigate to your openzim-mcp directory
cd /path/to/openzim-mcp

# Start the server with your ZIM files directory
uv run python -m openzim_mcp ~/zim-files

# You should see output like:
# OpenZIM MCP Server starting...
# Server name: openzim-mcp
# Allowed directories: ['/home/user/zim-files']
# Cache enabled: True
# Server ready for MCP connections.
```

## 📱 Step 3: Configure Your MCP Client

### For Claude Desktop

1. **Find your configuration file**:
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Linux**: `~/.config/claude/claude_desktop_config.json`

2. **Add OpenZIM MCP configuration**:

```json
{
  "mcpServers": {
    "openzim-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/your/openzim-mcp",
        "run",
        "python",
        "-m",
        "openzim_mcp",
        "/path/to/your/zim-files"
      ]
    }
  }
}
```

3. **Restart Claude Desktop**

### For Other MCP Clients

Use the command: `uv run python -m openzim_mcp /path/to/zim-files`

## 🧪 Step 4: Test Basic Functionality

### Test 1: List Available ZIM Files

In your MCP client, try:

```
Can you list the available ZIM files?
```

**Expected Response**: A list of ZIM files in your directory with details like size and modification date.

### Test 2: Search for Content

```
Search for "biology" in the ZIM files
```

**Expected Response**: Search results showing articles related to biology with snippets and paths.

### Test 3: Get Specific Content

```
Get the content of the "Biology" article from the ZIM file
```

**Expected Response**: The full content of the Biology article with proper formatting.

## 🔍 Step 5: Explore Advanced Features

### Smart Retrieval

Try accessing an article with different path formats:

```
Get the article "Test Article" from the ZIM file
```

The system will automatically handle path encoding differences (spaces vs underscores, etc.).

### Namespace Browsing

```
Browse the C namespace in the ZIM file, show me the first 10 entries
```

### Article Structure

```
Show me the structure and headings of the "Evolution" article
```

### Search Suggestions

```
Give me search suggestions for "bio"
```

## ✅ Step 6: Verify Everything Works

### Health Check

```
Check the server health and status
```

**Expected Response**: Server status, cache information, and performance metrics.

### Performance Test

```
Search for "computer" and then get the full content of one of the results
```

This tests both search and content retrieval functionality.

## 🎉 Success! What's Next?

Congratulations! You now have OpenZIM MCP running successfully. Here's what you can explore next:

### 📚 Learn More
- **[API Reference](API-Reference)** - Explore all available tools
- **[LLM Integration Patterns](LLM-Integration-Patterns)** - Best practices for AI integration
- **[Configuration Guide](Configuration-Guide)** - Customize your setup

### 🚀 Advanced Usage
- **[Performance Optimization](Performance-Optimization-Guide)** - Optimize for production
- **[Security Best Practices](Security-Best-Practices)** - Secure your deployment
- **[Architecture Overview](Architecture-Overview)** - Understand the system design

### 🛠️ Development
- **[Contributing Guidelines](https://github.com/cameronrye/openzim-mcp/blob/main/CONTRIBUTING.md)** - Contribute to the project
- **[Testing Guide](https://github.com/cameronrye/openzim-mcp/blob/main/docs/TESTING.md)** - Run tests and add new ones

## 🆘 Troubleshooting

### Common Issues

**"No ZIM files found"**
- Verify ZIM files are in the correct directory
- Check file permissions
- Ensure files have `.zim` extension

**"Server not responding"**
- Check if the server process is running
- Verify the correct path in MCP client configuration
- Look for error messages in the server output

**"Permission denied"**
- Ensure the user has read access to ZIM files directory
- Check directory permissions

### Getting Help

- **[Troubleshooting Guide](Troubleshooting-Guide)** - Detailed solutions
- **[GitHub Issues](https://github.com/cameronrye/openzim-mcp/issues)** - Report bugs
- **[GitHub Discussions](https://github.com/cameronrye/openzim-mcp/discussions)** - Ask questions

## 💡 Pro Tips

1. **Start Small**: Use smaller ZIM files (100-500MB) for initial testing
2. **Monitor Performance**: Use the health check tools to monitor cache performance
3. **Experiment**: Try different search terms and content types to understand capabilities
4. **Read the Logs**: Server logs provide valuable debugging information

---

**Great job!** You're now ready to harness the full power of OpenZIM MCP for your AI applications. Happy exploring! 🎯
