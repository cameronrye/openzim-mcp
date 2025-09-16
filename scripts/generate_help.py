#!/usr/bin/env python3
"""
Generate help output for the Makefile by parsing targets and their comments.
This script provides cross-platform compatibility for the make help command.
"""

import re
import sys
import os
from pathlib import Path
from typing import Dict, List, Tuple

# Enable ANSI colors on Windows
if os.name == 'nt':
    try:
        # Enable ANSI escape sequence processing on Windows 10+
        import subprocess
        subprocess.run([''], shell=True, check=True, capture_output=True)
        os.system('')
    except:
        pass


def parse_makefile(makefile_path: Path) -> Dict[str, List[Tuple[str, str]]]:
    """Parse the Makefile and extract targets with help comments."""
    categories = {
        "Setup & Installation": ["install", "setup", "check-tools"],
        "Code Quality": ["lint", "format", "type-check", "security"],
        "Testing": ["test", "benchmark"],
        "Data Management": ["download", "list", "clean"],
        "Build & Distribution": ["build", "publish"],
        "Utilities": ["check", "ci", "run", "help"]
    }
    
    # Initialize result dictionary
    result = {category: [] for category in categories.keys()}
    
    try:
        with open(makefile_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: Makefile not found at {makefile_path}")
        sys.exit(1)
    
    # Find all targets with help comments
    pattern = r'^([a-zA-Z][a-zA-Z0-9_-]*):.*?## (.*)$'
    matches = re.findall(pattern, content, re.MULTILINE)
    
    # Categorize targets with more specific matching
    for target, description in matches:
        # Use more specific categorization rules
        if target in ["install", "install-dev", "install-hooks", "setup-dev", "check-tools"]:
            result["Setup & Installation"].append((target, description))
        elif target in ["lint", "format", "type-check", "security"]:
            result["Code Quality"].append((target, description))
        elif target.startswith("test") or target == "benchmark":
            result["Testing"].append((target, description))
        elif target.startswith("download") or target.startswith("list") or target.startswith("clean"):
            result["Data Management"].append((target, description))
        elif target.startswith("build") or target.startswith("publish"):
            result["Build & Distribution"].append((target, description))
        else:
            result["Utilities"].append((target, description))
    
    # Sort targets within each category
    for category in result:
        result[category].sort(key=lambda x: x[0])
    
    return result


def format_help_output(categories: Dict[str, List[Tuple[str, str]]]) -> str:
    """Format the help output with colors and proper spacing."""
    output = []

    # Header
    output.append("OpenZIM MCP Development Commands")
    output.append("=" * 32)
    output.append("")

    # Check if colors should be used
    use_colors = True

    # Check if we're in a terminal that supports colors
    if not sys.stdout.isatty():
        use_colors = False
    elif os.name == 'nt':
        # On Windows, try to enable ANSI color support
        try:
            # Enable ANSI escape sequence processing on Windows 10+
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except:
            # If that fails, disable colors for better compatibility
            use_colors = False

    # Color codes
    if use_colors:
        blue = "\033[1;34m"
        cyan = "\033[36m"
        reset = "\033[0m"
    else:
        blue = cyan = reset = ""
    
    # Generate output for each category
    for category, targets in categories.items():
        if targets:  # Only show categories that have targets
            output.append(f"{blue}{category}:{reset}")
            for target, description in targets:
                output.append(f"  {cyan}{target:<20}{reset} {description}")
            output.append("")
    
    return "\n".join(output)


def main():
    """Main function to generate and display help."""
    # Find the Makefile (should be in the parent directory of this script)
    script_dir = Path(__file__).parent
    makefile_path = script_dir.parent / "Makefile"
    
    if not makefile_path.exists():
        print(f"Error: Makefile not found at {makefile_path}")
        sys.exit(1)
    
    # Parse the Makefile and generate help
    categories = parse_makefile(makefile_path)
    help_output = format_help_output(categories)
    
    print(help_output)


if __name__ == "__main__":
    main()
