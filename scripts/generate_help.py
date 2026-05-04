#!/usr/bin/env python3
"""Generate help output for the Makefile by parsing targets and their comments.

This script provides cross-platform compatibility for the make help command.
"""

import os
import re
import signal
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Enable ANSI colors on Windows
if os.name == "nt":
    import contextlib

    with contextlib.suppress(OSError):
        # Enable ANSI escape sequence processing on Windows 10+
        os.system("")  # nosec B605,B607 - empty string to enable ANSI on Windows


class RegexTimeoutError(Exception):
    """Raised when regex processing takes too long."""

    pass


def timeout_handler(signum, frame):
    """Signal handler for regex timeout."""
    raise RegexTimeoutError("Regex processing timed out")


def safe_regex_findall(
    pattern: str, text: str, flags: int = 0, timeout: int = 5
) -> List[Tuple[str, str]]:
    """
    Safely execute regex findall with timeout protection.

    Args:
        pattern: The regex pattern to match
        text: The text to search in
        flags: Regex flags
        timeout: Maximum time in seconds to allow for regex processing

    Returns:
        List of matches as tuples

    Raises:
        RegexTimeoutError: If regex processing takes longer than timeout
    """
    # Set up timeout handler (Unix-like systems only)
    old_handler = None
    if hasattr(signal, "SIGALRM"):
        old_handler = signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout)

    try:
        # Compile the regex first to catch any compilation errors
        compiled_pattern = re.compile(pattern, flags)
        matches = compiled_pattern.findall(text)
        return matches
    except RegexTimeoutError:
        print(
            "Warning: Regex processing timed out, using fallback parsing",
            file=sys.stderr,
        )
        return []
    except re.error as e:
        print(
            f"Warning: Regex compilation error: {e}, using fallback parsing",
            file=sys.stderr,
        )
        return []
    finally:
        # Clean up timeout handler
        if hasattr(signal, "SIGALRM") and old_handler is not None:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)


_CATEGORY_NAMES = (
    "Setup & Installation",
    "Code Quality",
    "Testing",
    "Data Management",
    "Build & Distribution",
    "Utilities",
)

_SETUP_TARGETS = {
    "install",
    "install-dev",
    "install-hooks",
    "setup-dev",
    "check-tools",
}

_QUALITY_TARGETS = {"lint", "format", "type-check", "security"}


def _categorise_target(target: str) -> str:
    """Map a Makefile target name to one of ``_CATEGORY_NAMES``."""
    if target in _SETUP_TARGETS:
        return "Setup & Installation"
    if target in _QUALITY_TARGETS:
        return "Code Quality"
    if target.startswith("test") or target == "benchmark":
        return "Testing"
    if target.startswith(("download", "list", "clean")):
        return "Data Management"
    if target.startswith(("build", "publish")):
        return "Build & Distribution"
    return "Utilities"


def _extract_targets(content: str) -> List[Tuple[str, str]]:
    """Pull (target, description) pairs out of Makefile contents.

    Limits per-line work and total line count to keep the regex pass
    bounded even on adversarial input.
    """
    lines = content.split("\n")
    max_lines = 10000
    if len(lines) > max_lines:
        print(
            f"Warning: Makefile has {len(lines)} lines, "
            f"processing only first {max_lines}",
            file=sys.stderr,
        )
        lines = lines[:max_lines]

    target_pattern = re.compile(r"^([a-zA-Z][a-zA-Z0-9_-]{0,50}):")
    comment_pattern = re.compile(r"## (.{0,200})$")

    matches: List[Tuple[str, str]] = []
    for line_num, line in enumerate(lines, 1):
        if len(line) > 1000:
            continue
        try:
            target_match = target_pattern.match(line)
            if not target_match:
                continue
            comment_match = comment_pattern.search(line)
            if not comment_match:
                continue
            target_name = target_match.group(1)
            comment_text = comment_match.group(1).strip()
            if target_name and comment_text:
                matches.append((target_name, comment_text))
        except Exception as e:
            print(f"Warning: Error processing line {line_num}: {e}", file=sys.stderr)
    return matches


def parse_makefile(makefile_path: Path) -> Dict[str, List[Tuple[str, str]]]:
    """Parse the Makefile and extract targets with help comments."""
    result: Dict[str, List[Tuple[str, str]]] = {c: [] for c in _CATEGORY_NAMES}

    try:
        with open(makefile_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: Makefile not found at {makefile_path}")
        sys.exit(1)

    try:
        for target, description in _extract_targets(content):
            result[_categorise_target(target)].append((target, description))
    except Exception as e:
        print(f"Error parsing Makefile: {e}", file=sys.stderr)
        return {c: [] for c in _CATEGORY_NAMES}

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
    elif os.name == "nt":
        # On Windows, try to enable ANSI color support
        try:
            # Enable ANSI escape sequence processing on Windows 10+
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(
                handle, mode.value | 0x0004
            )  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except (OSError, AttributeError, ValueError):
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
    """Generate and display help from the Makefile."""
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
