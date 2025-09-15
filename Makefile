# OpenZIM MCP Development Makefile

.PHONY: help install install-dev test test-cov lint format type-check clean run

help:  ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install:  ## Install production dependencies
	uv sync --no-dev

install-dev:  ## Install development dependencies
	uv sync

setup-dev:  ## Setup complete development environment
	python scripts/setup_dev_env.py

test:  ## Run tests
	uv run pytest

test-cov:  ## Run tests with coverage
	uv run pytest --cov=openzim_mcp --cov-report=html --cov-report=term-missing --cov-report=xml

test-with-zim-data:  ## Run tests with ZIM test data
	ZIM_TEST_DATA_DIR=test_data/zim-testing-suite uv run pytest

test-integration:  ## Run integration tests only
	uv run pytest -m "integration"

test-requires-zim-data:  ## Run tests that require ZIM test data
	ZIM_TEST_DATA_DIR=test_data/zim-testing-suite uv run pytest -m "requires_zim_data"

lint:  ## Run linting
	uv run flake8 openzim_mcp tests
	uv run isort --check-only openzim_mcp tests

format:  ## Format code
	uv run black openzim_mcp tests
	uv run isort openzim_mcp tests

type-check:  ## Run type checking
	uv run mypy openzim_mcp

download-test-data:  ## Download ZIM test data files
	python scripts/download_test_data.py --priority 1

download-test-data-all:  ## Download all ZIM test data files
	python scripts/download_test_data.py --all

list-test-data:  ## List available ZIM test data files
	python scripts/download_test_data.py --list

clean:  ## Clean up generated files
	@echo "Cleaning up generated files..."
	@uv run python -c "import shutil, os, glob; [shutil.rmtree(d, ignore_errors=True) for d in ['build', 'dist', '.pytest_cache', 'htmlcov', '.mypy_cache'] if os.path.exists(d)]"
	@uv run python -c "import os; [os.remove(f) for f in ['.coverage'] if os.path.exists(f)]"
	@uv run python -c "import shutil, os, glob; [shutil.rmtree(d, ignore_errors=True) for d in glob.glob('*.egg-info')]"
	@uv run python -c "import shutil, os; [shutil.rmtree(os.path.join(root, d), ignore_errors=True) for root, dirs, files in os.walk('.') for d in dirs if d == '__pycache__']"
	@uv run python -c "import os; [os.remove(os.path.join(root, f)) for root, dirs, files in os.walk('.') for f in files if f.endswith('.pyc')]"
	@echo "Clean completed."

clean-test-data:  ## Clean downloaded test data
	@echo "Cleaning test data..."
	@rm -rf test_data/zim-testing-suite
	@echo "Test data cleaned."

run:  ## Run the server (requires ZIM_DIR environment variable)
	@if [ -z "$(ZIM_DIR)" ]; then \
		echo "Error: ZIM_DIR environment variable not set"; \
		echo "Usage: make run ZIM_DIR=/path/to/zim/files"; \
		exit 1; \
	fi
	uv run python -m openzim_mcp "$(ZIM_DIR)"

check: lint type-check test  ## Run all checks (lint, type-check, test)

ci: install-dev check  ## Run CI pipeline
