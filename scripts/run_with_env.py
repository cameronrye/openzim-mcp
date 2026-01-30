#!/usr/bin/env python3
"""Run commands with environment variables set.

This script provides cross-platform compatibility for setting environment variables.
"""

import os
import subprocess  # nosec B404 - needed for running build commands
import sys


def main():
    """Run commands with environment variables set."""
    if len(sys.argv) < 3:
        print("Usage: python run_with_env.py ENV_VAR=value command [args...]")
        sys.exit(1)

    # Parse environment variable assignment
    env_assignment = sys.argv[1]
    if "=" not in env_assignment:
        print(f"Error: Invalid environment variable assignment: {env_assignment}")
        print("Expected format: ENV_VAR=value")
        sys.exit(1)

    env_var, env_value = env_assignment.split("=", 1)

    # Get the command and arguments
    command_args = sys.argv[2:]

    # Set up environment
    env = os.environ.copy()
    env[env_var] = env_value

    # Run the command
    try:
        print(f"Running with {env_var}={env_value}: {' '.join(command_args)}")
        result = subprocess.run(command_args, env=env, check=True)  # nosec B603
        sys.exit(result.returncode)
    except subprocess.CalledProcessError as e:
        sys.exit(e.returncode)
    except FileNotFoundError:
        print(f"Error: Command not found: {command_args[0]}")
        sys.exit(1)
    except Exception as e:
        print(f"Error running command: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
