#!/usr/bin/env python3
"""
Clean downloaded test data.
This script provides cross-platform compatibility for the make clean-test-data command.
"""

import shutil
import sys
from pathlib import Path


def main():
    """Main function to clean test data."""
    print("Cleaning test data...")
    
    # Get the project root directory
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    # Define test data directory
    test_data_dir = project_root / "test_data" / "zim-testing-suite"
    
    # Remove test data directory if it exists
    try:
        if test_data_dir.exists():
            shutil.rmtree(test_data_dir)
            print(f"  Removed: {test_data_dir}")
        else:
            print(f"  Test data directory does not exist: {test_data_dir}")
    except (OSError, PermissionError) as e:
        print(f"  Warning: Could not remove {test_data_dir}: {e}")
        sys.exit(1)
    
    print("Test data cleaned.")


if __name__ == "__main__":
    main()
