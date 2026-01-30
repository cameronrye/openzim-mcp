#!/usr/bin/env python3
"""Check required tools for the OpenZIM MCP development environment.

This script provides cross-platform compatibility for the make check-tools command.
"""

import shutil
import subprocess  # nosec B404 - needed for running build commands
import sys


def check_command_exists(command: str) -> bool:
    """Check if a command exists in the system PATH."""
    return shutil.which(command) is not None


def get_command_version(command: str, version_arg: str = "--version") -> str:
    """Get the version of a command."""
    try:
        result = subprocess.run(  # nosec B603 - safe, hardcoded commands only
            [command, version_arg], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return result.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        return "Unknown"


def check_python_version() -> tuple[bool, str]:
    """Check if Python version meets requirements (3.12+)."""
    try:
        result = subprocess.run(  # nosec B603 - safe, sys.executable only
            [sys.executable, "--version"], capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            version_str = result.stdout.strip()
            # Extract version number (e.g., "Python 3.12.0" -> "3.12.0")
            version_parts = version_str.split()
            if len(version_parts) >= 2:
                version = version_parts[1]
                # Check if version is 3.12 or higher
                try:
                    major, minor = map(int, version.split(".")[:2])
                    is_valid = (major > 3) or (major == 3 and minor >= 12)
                    return is_valid, version_str
                except ValueError:
                    return False, version_str
            return False, version_str
        else:
            return False, f"Error: {result.stderr.strip()}"
    except (
        subprocess.TimeoutExpired,
        FileNotFoundError,
        subprocess.SubprocessError,
    ) as e:
        return False, f"Error checking Python version: {e}"


def main():
    """Check all required tools for the development environment."""
    print("Checking required tools...")

    all_good = True

    # Check uv
    if check_command_exists("uv"):
        version = get_command_version("uv")
        print(f"[OK] uv found: {version}")
    else:
        print("[FAIL] uv not found. Install from: https://docs.astral.sh/uv/")
        all_good = False

    # Check Python version
    python_ok, python_version = check_python_version()
    if python_ok:
        print(f"[OK] Python version: {python_version}")
    else:
        print(f"[FAIL] Python 3.12+ required. Current: {python_version}")
        all_good = False

    if all_good:
        print("[OK] All required tools are available")
        sys.exit(0)
    else:
        print("[FAIL] Some required tools are missing or incompatible")
        sys.exit(1)


if __name__ == "__main__":
    main()
