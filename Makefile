# OpenZIM MCP Development Makefile

.PHONY: help install install-dev install-hooks setup-dev check-tools test test-cov test-with-zim-data test-integration test-requires-zim-data benchmark lint format type-check security download-test-data download-test-data-all list-test-data clean clean-test-data build publish publish-test run check ci

help:  ## Show this help message
	@uv run python scripts/generate_help.py

install:  ## Install production dependencies
	uv sync --no-dev

install-dev:  ## Install development dependencies
	uv sync

install-hooks:  ## Install pre-commit hooks
	@echo "Installing pre-commit hooks..."
	uv run pre-commit install
	@echo "Pre-commit hooks installed successfully"

setup-dev:  ## Setup complete development environment
	uv run python scripts/setup_dev_env.py

check-tools:  ## Verify required tools are available
	@uv run python scripts/check_tools.py

test:  ## Run tests
	uv run pytest

test-cov:  ## Run tests with coverage
	uv run pytest --cov=openzim_mcp --cov-report=html --cov-report=term-missing --cov-report=xml

test-with-zim-data:  ## Run tests with ZIM test data
	@uv run python scripts/run_with_env.py ZIM_TEST_DATA_DIR=test_data/zim-testing-suite uv run pytest

test-integration:  ## Run integration tests only
	uv run pytest -m "integration"

test-requires-zim-data:  ## Run tests that require ZIM test data
	@uv run python scripts/run_with_env.py ZIM_TEST_DATA_DIR=test_data/zim-testing-suite uv run pytest -m "requires_zim_data"

benchmark:  ## Run performance benchmarks
	@echo "Running performance benchmarks..."
	uv run pytest tests/test_benchmarks.py -v --benchmark-only
	@echo "Benchmark completed. Results saved to .benchmarks/"

lint:  ## Run linting
	uv run flake8 openzim_mcp tests
	uv run isort --check-only openzim_mcp tests

format:  ## Format code
	uv run black openzim_mcp tests
	uv run isort openzim_mcp tests

type-check:  ## Run type checking
	uv run mypy openzim_mcp

security:  ## Run security scans
	@echo "Running security scans..."
	@echo "Running bandit security scan..."
	@uv run bandit -r openzim_mcp -ll || echo "Bandit found low-severity issues (non-blocking)"
	@echo "Running safety dependency scan..."
	@uv run safety check --json || echo "Safety scan completed with warnings"

download-test-data:  ## Download ZIM test data files
	uv run python scripts/download_test_data.py --priority 1

download-test-data-all:  ## Download all ZIM test data files
	uv run python scripts/download_test_data.py --all

list-test-data:  ## List available ZIM test data files
	uv run python scripts/download_test_data.py --list

clean:  ## Clean up generated files
	@uv run python scripts/clean.py

clean-test-data:  ## Clean downloaded test data
	@uv run python scripts/clean_test_data.py

build:  ## Build distribution packages
	@echo "Building distribution packages..."
	uv build
	@echo "Build completed. Check dist/ directory."

publish:  ## Publish to PyPI (requires authentication)
	@echo "Publishing to PyPI..."
	@echo "Note: Ensure you have proper authentication configured"
	uv publish

publish-test:  ## Publish to TestPyPI (requires authentication)
	@echo "Publishing to TestPyPI..."
	@echo "Note: Ensure you have proper authentication configured"
	uv publish --index-url https://test.pypi.org/simple/

run:  ## Run the server (requires ZIM_DIR environment variable)
	@uv run python scripts/run_server.py

check: lint type-check security test  ## Run all checks (lint, type-check, security, test)

ci: install-dev check  ## Run CI pipeline
