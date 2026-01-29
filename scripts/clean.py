#!/usr/bin/env python3
"""
Clean up generated files and directories.
This script provides cross-platform compatibility for the make clean command.
"""

import os
import shutil
from pathlib import Path


def remove_path(path: Path, description: str = None) -> bool:
    """Remove a file or directory safely."""
    try:
        if path.exists():
            if path.is_file():
                path.unlink()
                if description:
                    print(f"  Removed file: {description}")
                return True
            elif path.is_dir():
                shutil.rmtree(path)
                if description:
                    print(f"  Removed directory: {description}")
                return True
        return False
    except (OSError, PermissionError) as e:
        print(f"  Warning: Could not remove {path}: {e}")
        return False


def remove_pattern(root_dir: Path, pattern: str, description: str = None) -> int:
    """Remove files/directories matching a pattern."""
    count = 0
    try:
        for path in root_dir.rglob(pattern):
            if remove_path(path):
                count += 1
        if count > 0 and description:
            print(f"  Removed {count} {description}")
    except (OSError, PermissionError) as e:
        print(f"  Warning: Error processing pattern {pattern}: {e}")
    return count


def main():
    """Main function to clean up generated files."""
    print("Cleaning up generated files...")

    # Get the project root directory
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    # Change to project root
    os.chdir(project_root)

    # Remove build directories
    build_dirs = ["build", "dist", ".pytest_cache", "htmlcov", ".mypy_cache"]
    for dir_name in build_dirs:
        remove_path(Path(dir_name), dir_name)

    # Remove coverage files
    remove_path(Path(".coverage"), ".coverage")
    remove_path(Path("coverage.xml"), "coverage.xml")

    # Remove root-level build artifacts
    for whl_file in Path(".").glob("*.whl"):
        remove_path(whl_file, f"wheel file: {whl_file.name}")
    for tar_file in Path(".").glob("*.tar.gz"):
        remove_path(tar_file, f"tarball: {tar_file.name}")

    # Remove egg-info directories
    remove_pattern(Path("."), "*.egg-info", "egg-info directories")

    # Remove __pycache__ directories
    remove_pattern(Path("."), "__pycache__", "__pycache__ directories")

    # Remove .pyc files
    remove_pattern(Path("."), "*.pyc", ".pyc files")

    print("Clean completed.")


if __name__ == "__main__":
    main()
