# Installation Guide

This guide covers installing OpenZIM MCP on different platforms and for various use cases.

## 📋 Prerequisites

### System Requirements
- **Python**: 3.12 or higher (3.13 also supported)
- **Operating System**: Windows, macOS, or Linux
- **Memory**: Minimum 512MB RAM (2GB+ recommended for large ZIM files)
- **Storage**: Space for ZIM files (varies by content, typically 100MB - 50GB+)

### Required Tools
- **uv** (recommended) or **pip** for package management
- **Git** for cloning the repository

## 🚀 Quick Installation

### Option 1: Using uv (Recommended)

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/cameronrye/openzim-mcp.git
cd openzim-mcp

# Install dependencies
uv sync

# Install development dependencies (optional)
uv sync --dev
```

### Option 2: Using pip

```bash
# Clone the repository
git clone https://github.com/cameronrye/openzim-mcp.git
cd openzim-mcp

# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -e .
```

## 📁 Setting Up ZIM Files

### Download ZIM Files

1. **Visit the Kiwix Library**: https://browse.library.kiwix.org/
2. **Choose content**: Wikipedia, Wiktionary, Stack Overflow, etc.
3. **Download ZIM files** to a dedicated directory

```bash
# Create ZIM files directory
mkdir ~/zim-files

# Example: Download a small Wikipedia subset
# (Download from Kiwix Library and place in ~/zim-files/)
```

### Recommended ZIM Files for Testing

- **Wikipedia (English, Top 100)**: ~300MB - Good for testing
- **Wikipedia (English, Top 1000)**: ~2GB - Comprehensive testing
- **Simple English Wikipedia**: ~200MB - Lightweight option

## 🔧 Platform-Specific Installation

### Windows

```powershell
# Install Python 3.12+ from python.org
# Install Git from git-scm.com

# Clone and install
git clone https://github.com/cameronrye/openzim-mcp.git
cd openzim-mcp

# Using uv (recommended)
uv sync

# Or using pip
python -m venv venv
venv\Scripts\activate
pip install -e .
```

### macOS

```bash
# Install Python 3.12+ using Homebrew
brew install python@3.12

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone https://github.com/cameronrye/openzim-mcp.git
cd openzim-mcp
uv sync
```

### Linux (Ubuntu/Debian)

```bash
# Install Python 3.12+
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-dev git

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone https://github.com/cameronrye/openzim-mcp.git
cd openzim-mcp
uv sync
```

### Linux (CentOS/RHEL/Fedora)

```bash
# Install Python 3.12+
sudo dnf install python3.12 python3.12-venv python3.12-devel git

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone https://github.com/cameronrye/openzim-mcp.git
cd openzim-mcp
uv sync
```

## 🐳 Docker Installation (Coming Soon)

Docker support is planned for future releases. Track progress in [GitHub Issues](https://github.com/cameronrye/openzim-mcp/issues).

## ✅ Verification

### Test the Installation

```bash
# Test basic functionality
uv run python -m openzim_mcp --help

# Run with a ZIM file directory
uv run python -m openzim_mcp /path/to/zim/files

# Run tests to verify everything works
make test
```

### Expected Output

```
OpenZIM MCP Server starting...
Server name: openzim-mcp
Allowed directories: ['/path/to/zim/files']
Cache enabled: True
Server ready for MCP connections.
```

## 🔧 MCP Client Configuration

### Claude Desktop

Add to your Claude Desktop configuration file:

**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Linux**: `~/.config/claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "openzim-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/openzim-mcp",
        "run",
        "python",
        "-m",
        "openzim_mcp",
        "/path/to/zim/files"
      ]
    }
  }
}
```

### Other MCP Clients

For other MCP-compatible clients, use the command:
```bash
uv run python -m openzim_mcp /path/to/zim/files
```

## 🚨 Troubleshooting Installation

### Common Issues

**Python Version Error**
```
Error: Python 3.12+ required
```
**Solution**: Install Python 3.12 or higher from [python.org](https://python.org)

**uv Not Found**
```
Command 'uv' not found
```
**Solution**: Install uv using the installation script or use pip instead

**Permission Denied**
```
Permission denied: '/path/to/zim/files'
```
**Solution**: Ensure the ZIM files directory is readable by the user running the server

**ZIM Files Not Found**
```
No ZIM files found in directory
```
**Solution**: Download ZIM files from [Kiwix Library](https://browse.library.kiwix.org/) and place them in the specified directory

### Getting Help

- **Check the [Troubleshooting Guide](Troubleshooting-Guide)** for detailed solutions
- **Open an issue** on [GitHub](https://github.com/cameronrye/openzim-mcp/issues)
- **Join discussions** on [GitHub Discussions](https://github.com/cameronrye/openzim-mcp/discussions)

## ⏭️ Next Steps

1. **[Quick Start Tutorial](Quick-Start-Tutorial)** - Learn basic usage
2. **[Configuration Guide](Configuration-Guide)** - Customize your setup
3. **[API Reference](API-Reference)** - Explore available tools

---

**Installation complete!** Continue with the [Quick Start Tutorial](Quick-Start-Tutorial) to start using OpenZIM MCP.
