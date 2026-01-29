# Welcome to OpenZIM MCP Wiki

**OpenZIM MCP** is a modern, secure, and high-performance MCP (Model Context Protocol) server that enables AI models to access and search [ZIM format](https://en.wikipedia.org/wiki/ZIM_(file_format)) knowledge bases offline.

> **NEW: Binary Content Retrieval!** Extract PDFs, images, videos, and other embedded media from ZIM archives for processing with external tools. Perfect for multi-agent workflows where you need to pass content to specialized processors like PDF parsers, vision models, or transcription services. [See API Reference →](API-Reference#get_binary_entry)

## Quick Navigation

### Getting Started

- **[Installation Guide](Installation-Guide)** - Set up OpenZIM MCP on your system
- **[Quick Start Tutorial](Quick-Start-Tutorial)** - Get up and running in minutes
- **[Configuration Guide](Configuration-Guide)** - Advanced configuration options

### User Documentation

- **[API Reference](API-Reference)** - Complete tool documentation
- **[LLM Integration Patterns](LLM-Integration-Patterns)** - Best practices for AI integration
- **[Performance Optimization](Performance-Optimization-Guide)** - Maximize performance

### Developer Resources

- **[Architecture Overview](Architecture-Overview)** - Technical system design
- **[Contributing Guidelines](https://github.com/cameronrye/openzim-mcp/blob/main/CONTRIBUTING.md)** - How to contribute
- **[Testing Guide](https://github.com/cameronrye/openzim-mcp/blob/main/docs/TESTING.md)** - Testing documentation

### Support & Troubleshooting

- **[Troubleshooting Guide](Troubleshooting-Guide)** - Common issues and solutions
- **[Security Best Practices](Security-Best-Practices)** - Security considerations
- **[FAQ](FAQ)** - Frequently asked questions

## What Makes OpenZIM MCP Special?

### Built for LLM Intelligence

Unlike basic file readers, OpenZIM MCP provides **intelligent, structured access** that LLMs need:

- **Smart Navigation**: Browse by namespace (articles, metadata, media) instead of blind searching
- **Context-Aware Discovery**: Get article structure, relationships, and metadata
- **Intelligent Search**: Advanced filtering, auto-complete suggestions, and relevance-ranked results
- **Performance Optimized**: Cached operations and pagination prevent timeouts
- **Relationship Mapping**: Extract internal/external links to understand content connections

### Enterprise-Ready Features

- **Binary Content Retrieval**: Extract PDFs, images, videos for multi-agent workflows
- **Security First**: Comprehensive input validation and path traversal protection
- **High Performance**: Intelligent caching and optimized ZIM file operations
- **Smart Retrieval**: Automatic fallback from direct access to search-based retrieval
- **Well Tested**: 80%+ test coverage with comprehensive test suite
- **Modern Architecture**: Modular design with dependency injection
- **Type Safe**: Full type annotations throughout the codebase
- **Configurable**: Flexible configuration with validation
- **Observable**: Structured logging and health monitoring

## Use Cases

### Research & Knowledge Management

- **Academic Research**: Access offline Wikipedia, academic papers, and reference materials
- **Knowledge Chatbots**: Build AI assistants with access to vast knowledge repositories
- **Content Analysis**: Analyze and extract insights from large knowledge bases

### Enterprise Applications

- **Offline Documentation**: Provide AI access to company knowledge bases without internet
- **Training Data**: Use curated knowledge bases for AI model training and fine-tuning
- **Compliance**: Ensure data privacy with offline knowledge access

### Development & Integration

- **MCP Integration**: Seamlessly integrate with any MCP-compatible AI system
- **Custom Applications**: Build specialized tools using the comprehensive API
- **Performance Critical**: Deploy in environments requiring fast, reliable knowledge access

## Project Status

- **Version**: 0.8.0
- **License**: MIT
- **Python**: 3.12+ (3.13 supported)
- **Test Coverage**: 90%+
- **Documentation**: Comprehensive

## Quick Links

- **[GitHub Repository](https://github.com/cameronrye/openzim-mcp)**
- **[Issues & Bug Reports](https://github.com/cameronrye/openzim-mcp/issues)**
- **[Discussions](https://github.com/cameronrye/openzim-mcp/discussions)**
- **[Releases](https://github.com/cameronrye/openzim-mcp/releases)**

## Latest Updates

Check the [CHANGELOG.md](https://github.com/cameronrye/openzim-mcp/blob/main/CHANGELOG.md) for the latest updates and release notes.

---

**Need help?** Start with the [Quick Start Tutorial](Quick-Start-Tutorial) or check the [Troubleshooting Guide](Troubleshooting-Guide) for common issues.
