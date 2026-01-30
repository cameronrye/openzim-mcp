#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download test data from zim-testing-suite repository.

This script downloads essential ZIM test files from the official zim-testing-suite
repository for comprehensive testing of OpenZIM MCP functionality.
"""

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional
from urllib.error import URLError
from urllib.request import urlretrieve

# Ensure UTF-8 encoding for Windows compatibility
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Base URL for zim-testing-suite repository
BASE_URL = "https://raw.githubusercontent.com/openzim/zim-testing-suite/main/data"

# Essential test files to download by category
ESSENTIAL_FILES = {
    "basic": {
        "withns/small.zim": {
            "description": "Small ZIM file with namespaces for basic testing",
            "size_mb": 0.08,
            "priority": 1,
        },
        "nons/small.zim": {
            "description": "Small ZIM file without namespaces for basic testing",
            "size_mb": 0.04,
            "priority": 1,
        },
    },
    "real_content": {
        "withns/wikibooks_be_all_nopic_2017-02.zim": {
            "description": "Real Wikibooks content for integration testing",
            "size_mb": 0.15,
            "priority": 2,
        },
        "withns/wikipedia_en_climate_change_mini_2024-06.zim": {
            "description": "Wikipedia climate change mini for comprehensive testing",
            "size_mb": 13.6,
            "priority": 3,
        },
    },
    "invalid_files": {
        "withns/invalid.smaller_than_header.zim": {
            "description": "Invalid ZIM file smaller than header",
            "size_mb": 0.00004,
            "priority": 2,
        },
        "withns/invalid.bad_mimetype_in_dirent.zim": {
            "description": "Invalid ZIM file with bad MIME type in dirent",
            "size_mb": 0.08,
            "priority": 2,
        },
        "withns/invalid.outofbounds_clusterptrpos.zim": {
            "description": "Invalid ZIM file with out-of-bounds cluster pointer",
            "size_mb": 0.08,
            "priority": 2,
        },
    },
    "special_cases": {
        "withns/small.zim.embedded": {
            "description": "ZIM file with embedded content",
            "size_mb": 0.08,
            "priority": 3,
        },
        "withns/wikibooks_be_all_nopic_2017-02_splitted.zimaa": {
            "description": "Split ZIM file part A",
            "size_mb": 0.05,
            "priority": 3,
        },
        "withns/wikibooks_be_all_nopic_2017-02_splitted.zimab": {
            "description": "Split ZIM file part B",
            "size_mb": 0.05,
            "priority": 3,
        },
        "withns/wikibooks_be_all_nopic_2017-02_splitted.zimac": {
            "description": "Split ZIM file part C",
            "size_mb": 0.05,
            "priority": 3,
        },
    },
}


def get_file_hash(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()


def download_file(url: str, dest_path: Path, description: str) -> bool:
    """Download a file from URL to destination path.

    Args:
        url: Source URL
        dest_path: Destination file path
        description: File description for logging

    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"Downloading {description}...")
        logger.debug(f"URL: {url}")
        logger.debug(f"Destination: {dest_path}")

        # Create parent directory if it doesn't exist
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        # Download with progress indication for large files
        def progress_hook(block_num: int, block_size: int, total_size: int) -> None:
            if total_size > 0:
                percent = min(100, (block_num * block_size * 100) // total_size)
                if (
                    block_num % 100 == 0 or percent >= 100
                ):  # Update every 100 blocks or at completion
                    logger.debug(f"Progress: {percent}%")

        urlretrieve(url, dest_path, reporthook=progress_hook)
        logger.info(f"[OK] Downloaded: {dest_path.name}")
        return True

    except URLError as e:
        logger.error(f"[FAIL] Failed to download {dest_path.name}: {e}")
        return False
    except Exception as e:
        logger.error(f"[FAIL] Unexpected error downloading {dest_path.name}: {e}")
        return False


def list_available_files() -> None:
    """List all available test files by category."""
    print("\nAvailable test files by category:\n")

    total_size = 0
    total_files = 0

    for category, files in ESSENTIAL_FILES.items():
        print(f"[DIR] {category.upper().replace('_', ' ')}")
        print("=" * 50)

        for file_path, info in files.items():
            size_mb = info["size_mb"]
            priority = info["priority"]
            description = info["description"]

            priority_str = (
                "[HIGH]" if priority == 1 else "[MED]" if priority == 2 else "[LOW]"
            )
            print(f"  {priority_str} {file_path}")
            print(f"     {description}")
            print(f"     Size: {size_mb:.2f} MB")
            print()

            total_size += size_mb
            total_files += 1

    print(f"Total: {total_files} files, {total_size:.2f} MB")
    print("\nPriority levels:")
    print("[HIGH] Priority 1: Essential for basic testing")
    print("[MED]  Priority 2: Important for comprehensive testing")
    print("[LOW]  Priority 3: Advanced testing scenarios")


def download_files(
    output_dir: Path,
    categories: Optional[List[str]] = None,
    max_priority: int = 3,
    force: bool = False,
) -> bool:
    """Download test files based on criteria.

    Args:
        output_dir: Output directory for downloaded files
        categories: List of categories to download (None for all)
        max_priority: Maximum priority level to download (1-3)
        force: Force re-download even if file exists

    Returns:
        True if all downloads successful, False otherwise
    """
    success_count = 0
    total_count = 0
    total_size = 0

    # Filter files based on criteria
    files_to_download = {}
    for category, files in ESSENTIAL_FILES.items():
        if categories and category not in categories:
            continue

        for file_path, info in files.items():
            if info["priority"] <= max_priority:
                files_to_download[file_path] = info
                total_size += info["size_mb"]

    total_count = len(files_to_download)

    if total_count == 0:
        logger.warning("No files match the specified criteria")
        return False

    logger.info(f"Downloading {total_count} files ({total_size:.2f} MB total)")

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Download files
    for file_path, info in files_to_download.items():
        dest_path = output_dir / file_path

        # Skip if file exists and not forcing
        if dest_path.exists() and not force:
            logger.info(f"[SKIP] Skipping existing file: {dest_path.name}")
            success_count += 1
            continue

        url = f"{BASE_URL}/{file_path}"
        if download_file(url, dest_path, info["description"]):
            success_count += 1

    # Summary
    logger.info(f"\nDownload complete: {success_count}/{total_count} files successful")

    if success_count == total_count:
        logger.info("[OK] All downloads completed successfully!")
        return True
    else:
        logger.warning(f"[FAIL] {total_count - success_count} downloads failed")
        return False


def create_manifest(output_dir: Path) -> None:
    """Create a manifest file with downloaded file information."""
    manifest_path = output_dir / "manifest.json"
    manifest = {"created": str(Path.cwd()), "files": {}}

    for category, files in ESSENTIAL_FILES.items():
        for file_path, info in files.items():
            dest_path = output_dir / file_path
            if dest_path.exists():
                manifest["files"][file_path] = {
                    "category": category,
                    "description": info["description"],
                    "priority": info["priority"],
                    "size_bytes": dest_path.stat().st_size,
                    "sha256": get_file_hash(dest_path),
                }

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"Created manifest: {manifest_path}")


def main() -> int:
    """Run the main entry point."""
    parser = argparse.ArgumentParser(
        description="Download test data from zim-testing-suite repository",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --list                           # List available files
  %(prog)s                                  # Download priority 1 files
  %(prog)s --priority 2                     # Download priority 1-2 files
  %(prog)s --category basic invalid_files   # Download specific categories
  %(prog)s --all                            # Download all files
  %(prog)s --force                          # Force re-download existing files
        """,
    )

    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("test_data/zim-testing-suite"),
        help="Output directory (default: test_data/zim-testing-suite)",
    )

    parser.add_argument(
        "--list", "-l", action="store_true", help="List available files and exit"
    )

    parser.add_argument(
        "--category",
        "-c",
        action="append",
        choices=list(ESSENTIAL_FILES.keys()),
        help="Download specific categories (can be used multiple times)",
    )

    parser.add_argument(
        "--priority",
        "-p",
        type=int,
        choices=[1, 2, 3],
        default=1,
        help="Maximum priority level to download (default: 1)",
    )

    parser.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="Download all files (equivalent to --priority 3)",
    )

    parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force re-download even if files exist",
    )

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.list:
        list_available_files()
        return 0

    # Determine priority level
    max_priority = 3 if args.all else args.priority

    # Download files
    success = download_files(
        output_dir=args.output_dir,
        categories=args.category,
        max_priority=max_priority,
        force=args.force,
    )

    if success:
        create_manifest(args.output_dir)

        # Print usage instructions
        output_path = args.output_dir.absolute()
        print("\n[INFO] Usage Instructions:")
        print(f"Set environment variable: export ZIM_TEST_DATA_DIR={output_path}")
        print(f"Or use in tests: ZIM_TEST_DATA_DIR={output_path} make test")

        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
