# Frequently Asked Questions (FAQ)

Common questions and answers about OpenZIM MCP.

## 🤔 General Questions

### What is OpenZIM MCP?

OpenZIM MCP is a Model Context Protocol (MCP) server that enables AI models to access and search ZIM format knowledge bases offline. It provides intelligent, structured access to content like Wikipedia, Wiktionary, and other knowledge repositories.

### What makes it different from other file readers?

Unlike basic file readers, OpenZIM MCP provides:
- **Smart Navigation**: Browse by namespace instead of blind searching
- **Context-Aware Discovery**: Get article structure and relationships
- **Intelligent Search**: Advanced filtering and auto-complete
- **Performance Optimization**: Caching and pagination for large archives
- **LLM-Optimized**: Designed specifically for AI model integration

### What are ZIM files?

ZIM (Zeno IMproved) files are an open format for storing web content offline. They're highly compressed and optimized for fast access, commonly used for Wikipedia, Wiktionary, and other reference materials.

## 🚀 Getting Started

### How do I install OpenZIM MCP?

1. **Install Python 3.12+**
2. **Install OpenZIM MCP**: `pip install openzim-mcp`
3. **Download ZIM files** from [Kiwix Library](https://browse.library.kiwix.org/)
4. **Configure your MCP client** with the server command

See the [Installation Guide](Installation-Guide) for detailed instructions.

### Where can I get ZIM files?

Download ZIM files from the [Kiwix Library](https://browse.library.kiwix.org/). Popular options include:
- Wikipedia (various languages and sizes)
- Wiktionary (dictionaries)
- Stack Overflow (programming Q&A)
- Medical and educational content

### What's the minimum system requirements?

- **Python**: 3.12 or higher
- **Memory**: 512MB minimum (2GB+ recommended for large ZIM files)
- **Storage**: Space for ZIM files (100MB to 50GB+ depending on content)
- **OS**: Windows, macOS, or Linux

## 🔧 Configuration

### How do I configure caching?

Use environment variables:
```bash
export OPENZIM_MCP_CACHE__ENABLED=true
export OPENZIM_MCP_CACHE__MAX_SIZE=200
export OPENZIM_MCP_CACHE__TTL_SECONDS=7200
```

See the [Configuration Guide](Configuration-Guide) for all options.

### Can I use multiple ZIM files?

Yes! Place multiple ZIM files in your directory and OpenZIM MCP will automatically detect and provide access to all of them.

### How do I optimize performance?

Key optimization strategies:
- **Increase cache size** for frequently accessed content
- **Use appropriate content limits** for your use case
- **Monitor cache hit rates** (target >70%)
- **Choose the right ZIM files** for your needs

See the [Performance Optimization Guide](Performance-Optimization-Guide) for details.

## 🔍 Usage

### How do I search for content?

Use natural language with your MCP client:
- "Search for biology in the ZIM files"
- "Find articles about evolution"
- "Get search suggestions for 'bio'"

The system supports various search strategies and filters.

### How do I get specific articles?

Request articles directly:
- "Get the Biology article from the ZIM file"
- "Show me the content of the Evolution page"

The smart retrieval system automatically handles path encoding differences.

### Can I get article structure without full content?

Yes! Use structure requests:
- "Show me the structure of the Evolution article"
- "What are the main sections in the Biology page?"

This gives you headings, sections, and metadata without loading full content.

## 🚨 Troubleshooting

### "No ZIM files found" error

**Causes**:
- Wrong directory path
- Missing `.zim` file extension
- Permission issues

**Solutions**:
1. Verify the directory path exists
2. Check file permissions (`chmod 644 *.zim`)
3. Ensure files have `.zim` extension
4. Download ZIM files if directory is empty

### Server not responding

**Causes**:
- Server process not running
- Wrong configuration path
- Permission issues

**Solutions**:
1. Check if server process is running
2. Verify MCP client configuration paths
3. Restart the server
4. Check server logs for errors

### Search returns no results

**Causes**:
- Typos in search terms
- Content not in ZIM file
- Wrong namespace

**Solutions**:
1. Check spelling of search terms
2. Try broader search terms
3. Browse namespaces to explore content
4. Verify ZIM file contains expected content

### Slow performance

**Causes**:
- Large ZIM files
- Low cache hit rate
- Insufficient system resources

**Solutions**:
1. Increase cache size
2. Use smaller ZIM files for testing
3. Monitor system resources
4. Optimize search patterns

See the [Troubleshooting Guide](Troubleshooting-Guide) for detailed solutions.

## 🔒 Security

### Is OpenZIM MCP secure?

Yes! OpenZIM MCP includes multiple security layers:
- **Path traversal protection**
- **Input validation and sanitization**
- **Directory access restrictions**
- **Resource usage limits**

See [Security Best Practices](Security-Best-Practices) for deployment guidelines.

### Can I restrict access to certain files?

Yes, use the allowed directories configuration to limit access to specific paths. The system prevents access outside configured directories.

### How do I run it securely in production?

Follow security best practices:
- Run as dedicated user (not root)
- Set appropriate file permissions
- Enable comprehensive logging
- Regular security updates
- Monitor for suspicious activity

## 🔄 Advanced Usage

### Can I use it with multiple MCP clients?

Yes, but be aware of potential conflicts. Use the conflict detection and resolution tools to manage multiple instances.

### How do I integrate with my application?

OpenZIM MCP follows the standard MCP protocol. Any MCP-compatible client can integrate with it. See [LLM Integration Patterns](LLM-Integration-Patterns) for best practices.

### Can I extend functionality?

The modular architecture supports extensions. Check the [Architecture Overview](Architecture-Overview) for technical details and extension points.

### Does it support custom ZIM files?

Yes! Any valid ZIM file works with OpenZIM MCP. You can create custom ZIM files using tools from the OpenZIM project.

## 📊 Performance

### What's a good cache hit rate?

Target >70% cache hit rate for good performance. Monitor using the health check tools and adjust cache size accordingly.

### How much memory does it use?

Memory usage depends on:
- Cache size configuration
- ZIM file sizes
- Concurrent operations
- Content length limits

Typical usage: 100-500MB for moderate workloads.

### Can it handle large ZIM files?

Yes, but performance depends on system resources. For very large files (>10GB):
- Increase system RAM
- Optimize cache settings
- Use SSD storage
- Monitor performance metrics

## 🛠️ Development

### How do I contribute?

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests (`make test`)
5. Submit a pull request

See [Contributing Guidelines](https://github.com/cameronrye/openzim-mcp/blob/main/CONTRIBUTING.md) for details.

### How do I run tests?

```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run integration tests with real ZIM files
make test-with-zim-data
```

### Where can I report bugs?

Report bugs on [GitHub Issues](https://github.com/cameronrye/openzim-mcp/issues). Include:
- Operating system and version
- Python version
- Error messages
- Steps to reproduce

## 📚 Resources

### Where can I learn more?

- **[Quick Start Tutorial](Quick-Start-Tutorial)** - Get started quickly
- **[API Reference](API-Reference)** - Complete tool documentation
- **[Architecture Overview](Architecture-Overview)** - Technical details
- **[GitHub Repository](https://github.com/cameronrye/openzim-mcp)** - Source code and issues

### What about the ZIM format?

Learn more about ZIM files:
- **[OpenZIM Project](https://openzim.org/)** - Official ZIM format documentation
- **[Kiwix](https://www.kiwix.org/)** - ZIM file reader and library
- **[ZIM Format Specification](https://openzim.org/wiki/ZIM_file_format)** - Technical details

### Community and Support

- **[GitHub Discussions](https://github.com/cameronrye/openzim-mcp/discussions)** - Ask questions and share ideas
- **[GitHub Issues](https://github.com/cameronrye/openzim-mcp/issues)** - Report bugs and request features

## 🔮 Future Plans

### What's coming next?

Planned features include:
- Docker container support
- Enhanced multi-instance management
- Performance improvements
- Additional content formats
- Web interface (optional)

### How can I stay updated?

- **Watch the repository** on GitHub for updates
- **Check the [CHANGELOG](https://github.com/cameronrye/openzim-mcp/blob/main/CHANGELOG.md)** for release notes
- **Follow discussions** for feature announcements

---

**Still have questions?** Check the other wiki pages or [ask in GitHub Discussions](https://github.com/cameronrye/openzim-mcp/discussions)!
