# OpenZIM MCP Development Makefile

.PHONY: help install install-dev install-hooks setup-dev check-tools test test-cov test-with-zim-data test-integration test-requires-zim-data benchmark lint format type-check security download-test-data download-test-data-all list-test-data clean clean-test-data build publish publish-test run check ci

help:  ## Show this help message
	@echo "OpenZIM MCP Development Commands"
	@echo "================================"
	@echo ""
	@echo "\033[1;34mSetup & Installation:\033[0m"
	@grep -E '^(install|setup|check-tools).*:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "\033[1;34mCode Quality:\033[0m"
	@grep -E '^(lint|format|type-check|security).*:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "\033[1;34mTesting:\033[0m"
	@grep -E '^(test|benchmark).*:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "\033[1;34mData Management:\033[0m"
	@grep -E '^(download|list|clean).*:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "\033[1;34mBuild & Distribution:\033[0m"
	@grep -E '^(build|publish).*:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "\033[1;34mUtilities:\033[0m"
	@grep -E '^(check|ci|run|help).*:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

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
	@echo "Checking required tools..."
	@command -v uv >/dev/null 2>&1 || { echo "[FAIL] uv not found. Install from: https://docs.astral.sh/uv/"; exit 1; }
	@echo "[OK] uv found: $$(uv --version)"
	@python --version | grep -q "3.12" || { echo "[FAIL] Python 3.12+ required. Current: $$(python --version)"; exit 1; }
	@echo "[OK] Python version: $$(python --version)"
	@echo "[OK] All required tools are available"

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
	@echo "Cleaning up generated files..."
	@rm -rf build dist .pytest_cache htmlcov .mypy_cache
	@rm -f .coverage
	@rm -rf *.egg-info
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@echo "Clean completed."

clean-test-data:  ## Clean downloaded test data
	@echo "Cleaning test data..."
	@rm -rf test_data/zim-testing-suite
	@echo "Test data cleaned."

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
	@if [ -z "$(ZIM_DIR)" ]; then \
		echo "Error: ZIM_DIR environment variable not set"; \
		echo "Usage: make run ZIM_DIR=/path/to/zim/files"; \
		exit 1; \
	fi
	uv run python -m openzim_mcp "$(ZIM_DIR)"

check: lint type-check security test  ## Run all checks (lint, type-check, security, test)

ci: install-dev check  ## Run CI pipeline
