#!/usr/bin/env python3
"""
Run the OpenZIM MCP server with proper environment variable checking.
This script provides cross-platform compatibility for the make run command.
"""

import os
import sys
import subprocess
from pathlib import Path


def main():
    """Main function to run the server with ZIM_DIR validation."""
    # Check if ZIM_DIR environment variable is set
    zim_dir = os.environ.get("ZIM_DIR")
    
    if not zim_dir:
        print("Error: ZIM_DIR environment variable not set")
        print("Usage: make run ZIM_DIR=/path/to/zim/files")
        print("   or: ZIM_DIR=/path/to/zim/files make run")
        print("   or: set ZIM_DIR=/path/to/zim/files && make run  (Windows)")
        sys.exit(1)
    
    # Validate that the directory exists
    zim_path = Path(zim_dir)
    if not zim_path.exists():
        print(f"Error: ZIM_DIR path does not exist: {zim_dir}")
        sys.exit(1)
    
    if not zim_path.is_dir():
        print(f"Error: ZIM_DIR is not a directory: {zim_dir}")
        sys.exit(1)
    
    # Run the server
    try:
        print(f"Starting OpenZIM MCP server with ZIM_DIR: {zim_dir}")
        result = subprocess.run([
            "uv", "run", "python", "-m", "openzim_mcp", zim_dir
        ], check=True)
        sys.exit(result.returncode)
    except subprocess.CalledProcessError as e:
        print(f"Error running server: {e}")
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        print("\nServer stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
