# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0](https://github.com/cameronrye/openzim-mcp/compare/v0.3.3...v0.4.0) (2025-09-15)


### Features

* overhaul release system for reliability and enterprise-grade automation ([#9](https://github.com/cameronrye/openzim-mcp/issues/9)) ([ef0f1b8](https://github.com/cameronrye/openzim-mcp/commit/ef0f1b8f2eaac99a1850672088ddc29d28f0bcde))

## [0.3.1](https://github.com/cameronrye/openzim-mcp/compare/v0.3.0...v0.3.1) (2025-09-15)


### Bug Fixes

* add manual trigger support to Release workflow ([b968cf6](https://github.com/cameronrye/openzim-mcp/commit/b968cf661f536183f4ef5fd6374e75a847a0123f))
* ensure Release workflow checks out correct tag for all jobs ([b4a61ca](https://github.com/cameronrye/openzim-mcp/commit/b4a61ca7a034f9eefae2606c4eb9769ef4f79379))

## [0.3.0](https://github.com/cameronrye/openzim-mcp/compare/v0.2.0...v0.3.0) (2025-09-15)


### Features

* add automated version bumping with release-please ([6b4e27c](https://github.com/cameronrye/openzim-mcp/commit/6b4e27c0382bb4cfa16a7e101f012e8355f7c827))


### Bug Fixes

* resolve release-please workflow issues ([68b47ea](https://github.com/cameronrye/openzim-mcp/commit/68b47ea711525e126ec3ed8297808f7779edd87e))

## [Unreleased]

### Added

- **Smart Retrieval System**: Intelligent ZIM entry retrieval with automatic fallback
  - Direct access attempt followed by search-based fallback for reliable entry retrieval
  - Automatic handling of path encoding differences (spaces vs underscores, URL encoding, etc.)
  - Path mapping cache for improved performance on repeated access
  - Enhanced error messages with actionable guidance for LLM users
  - Transparent operation eliminating need for manual search-first methodology

### Enhanced

- **get_zim_entry function**: Now includes smart retrieval capabilities for better reliability
- **Cache system**: Added path mapping cache with automatic invalidation of stale entries
- **Error handling**: Improved error messages specifically designed for LLM user experience

## [0.2.0] - 2025-01-15

### Added

- **Complete Architecture Refactoring**: Modular design with dependency injection
- **Enhanced Security**: 
  - Fixed path traversal vulnerability using secure path validation
  - Comprehensive input sanitization and validation
  - Protection against directory traversal attacks
- **Comprehensive Testing**: 90%+ test coverage with pytest
  - Unit tests for all components
  - Integration tests for end-to-end functionality
  - Security tests for vulnerability prevention
- **Intelligent Caching**: LRU cache with TTL support for improved performance
- **Modern Configuration Management**: Pydantic-based configuration with validation
- **Structured Logging**: Configurable logging with proper error handling
- **Type Safety**: Complete type annotations throughout the codebase
- **Resource Management**: Proper cleanup with context managers
- **Health Monitoring**: Built-in health check endpoint
- **Development Tools**: 
  - Makefile for common development tasks
  - Black, flake8, mypy, isort for code quality
  - Comprehensive development dependencies

### Changed

- **Project Name**: Changed from "zim-mcp-server" to "openzim-mcp" for consistency
- **Entry Point**: New `python -m openzim_mcp` interface (backwards compatible)
- **Error Handling**: Consistent custom exception hierarchy
- **Content Processing**: Improved HTML to text conversion
- **API**: Enhanced tool interfaces with better validation

### Security

- **CRITICAL**: Fixed path traversal vulnerability in PathManager
- **HIGH**: Added comprehensive input validation
- **MEDIUM**: Sanitized error messages to prevent information disclosure

### Performance

- **Caching**: Intelligent caching reduces ZIM file access overhead
- **Resource Management**: Proper cleanup prevents memory leaks
- **Optimized Processing**: Improved content processing performance

## [0.1.0] - 2024-XX-XX

### Added

- Initial release of ZIM MCP Server
- Basic ZIM file operations (list, search, get entry)
- Simple path management
- HTML to text conversion
- MCP server implementation

### Known Issues (Fixed in 0.2.0)

- Path traversal security vulnerability
- No input validation
- Missing error handling
- No testing framework
- Resource management issues
- Global state management problems
