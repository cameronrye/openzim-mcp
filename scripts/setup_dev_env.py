#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Setup development environment for OpenZIM MCP.

This script helps developers set up their environment for OpenZIM MCP development,
including downloading test data and verifying the setup.
"""

import argparse
import subprocess
import sys
from pathlib import Path

# Ensure UTF-8 encoding for Windows compatibility
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def run_command(cmd: str, description: str) -> bool:
    """Run a command and return success status."""
    print(f"[RUNNING] {description}...")
    try:
        result = subprocess.run(cmd, shell=True, check=True, capture_output=True, text=True)
        print(f"[OK] {description} completed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[FAIL] {description} failed:")
        print(f"   Command: {cmd}")
        print(f"   Error: {e.stderr}")
        return False


def check_requirements() -> bool:
    """Check if required tools are available."""
    print("[CHECK] Checking requirements...")

    # Check Python version
    if sys.version_info < (3, 12):
        print("[FAIL] Python 3.12+ is required")
        return False
    print(f"[OK] Python {sys.version_info.major}.{sys.version_info.minor} found")

    # Check uv
    try:
        subprocess.run(["uv", "--version"], check=True, capture_output=True)
        print("[OK] uv found")
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("[FAIL] uv not found. Please install uv: https://docs.astral.sh/uv/")
        return False

    return True


def setup_environment() -> bool:
    """Set up the development environment."""
    print("\n[SETUP] Setting up development environment...")

    steps = [
        ("uv sync", "Installing dependencies"),
        ("make download-test-data", "Downloading essential test data"),
    ]

    for cmd, description in steps:
        if not run_command(cmd, description):
            return False

    return True


def run_tests() -> bool:
    """Run tests to verify setup."""
    print("\n[TEST] Running tests to verify setup...")

    test_steps = [
        ("make lint", "Running linting"),
        ("make type-check", "Running type checking"),
        ("make test", "Running unit tests"),
        ("make test-requires-zim-data", "Running ZIM data tests"),
    ]

    success_count = 0
    for cmd, description in test_steps:
        if run_command(cmd, description):
            success_count += 1

    print(f"\n[RESULTS] Test Results: {success_count}/{len(test_steps)} passed")
    return success_count == len(test_steps)


def show_next_steps():
    """Show next steps for development."""
    print("\n[SUCCESS] Development environment setup complete!")
    print("\n[INFO] Next steps:")
    print("   1. Start developing: Edit files in openzim_mcp/")
    print("   2. Run tests: make test")
    print("   3. Run with ZIM data: make test-with-zim-data")
    print("   4. Check coverage: make test-cov && open htmlcov/index.html")
    print("   5. Format code: make format")
    print("   6. Run all checks: make check")
    print("\n[DOCS] Documentation:")
    print("   - Testing guide: docs/TESTING.md")
    print("   - Main README: README.md")
    print("\n[COMMANDS] Useful commands:")
    print("   - make help                    # Show all available commands")
    print("   - make download-test-data-all  # Download all test files")
    print("   - make list-test-data          # List available test files")
    print("   - make clean-test-data         # Clean test data")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Setup OpenZIM MCP development environment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script will:
1. Check system requirements (Python 3.12+, uv)
2. Install project dependencies
3. Download essential ZIM test data
4. Run tests to verify setup
5. Show next steps for development

Examples:
  %(prog)s                    # Full setup
  %(prog)s --skip-tests       # Setup without running tests
  %(prog)s --test-only        # Only run tests (assume setup done)
        """
    )
    
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running tests after setup"
    )
    
    parser.add_argument(
        "--test-only",
        action="store_true",
        help="Only run tests (skip environment setup)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )
    
    args = parser.parse_args()
    
    print("[START] OpenZIM MCP Development Environment Setup")
    print("=" * 50)

    # Check requirements
    if not check_requirements():
        print("\n[FAIL] Requirements check failed. Please install missing dependencies.")
        return 1

    # Setup environment (unless test-only)
    if not args.test_only:
        if not setup_environment():
            print("\n[FAIL] Environment setup failed.")
            return 1

    # Run tests (unless skipped)
    if not args.skip_tests:
        if not run_tests():
            print("\n[WARN] Some tests failed. Environment may not be fully functional.")
            print("   Check the error messages above and try running tests manually.")
    
    # Show next steps
    show_next_steps()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
