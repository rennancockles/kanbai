.PHONY: help start install pre-commit lint-fix lint ruff mypy ty ruff-check format-check ruff-fix fmt pre-commit-sim type-check test test-unit test-ci pre-commit-run dev release-dry release release-info tag-release inspect-release publish-docs docs env-check mcp-run mcp-inspector
.DEFAULT_GOAL := help
# .ONESHELL:

# Load .env (if present) and export its vars to all recipe subprocesses.
# Optional so targets still work without a .env file.
-include .env
export

# Variables
PROJECT_NAME=KanbAI
ENV_PREFIX=$(shell python -c "if __import__('pathlib').Path('.venv/bin/pip').exists(): print('.venv/bin/')")
# Parallel pytest workers (pytest-xdist); use -n0 to disable (e.g. test-watch)
PYTEST_PARALLEL ?= -n auto

# Colors for output
BOLD := \033[1m
RED := \033[31m
GREEN := \033[32m
YELLOW := \033[33m
BLUE := \033[34m
RESET := \033[0m

help: ## Show this help message
	@echo "$(BOLD)$(PROJECT_NAME) Development Commands$(RESET)"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "$(BLUE)%-20s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "$(YELLOW)Main Commands:$(RESET)"
	@echo "  $(GREEN)make start$(RESET)       - Start API, wait for health, setup pre-commit, run CLI"
	@echo "  $(GREEN)make lint$(RESET)        - Run all linting and formatting checks"
	@echo "  $(GREEN)make test$(RESET)        - Run all tests with coverage"
	@echo ""
	@echo "$(YELLOW)Development Workflow:$(RESET)"
	@echo "  1. $(GREEN)make lint-fix$(RESET) - Fix code issues before staging"
	@echo "  2. $(GREEN)git add .$(RESET)     - Stage your changes"
	@echo "  3. $(GREEN)git commit$(RESET)    - Commit (pre-commit hooks will run)"

start: install pre-commit ## Start local environment

install: ## Install project dev dependencies
	@echo "$(YELLOW)Installing dev dependencies with UV...$(RESET)"
	@uv sync --all-extras
	@echo "$(GREEN)✓ Dev dependencies installed$(RESET)"

pre-commit: ## Install and configure pre-commit hooks
	@echo "$(YELLOW)Setting up pre-commit hooks...$(RESET)"
	@uv run pre-commit install
	@echo "$(GREEN)✓ Pre-commit hooks configured$(RESET)"


# Development and Quality Commands
# Note: The order of lint operations matches pre-commit hooks for consistency:
lint-fix: fmt ruff-fix ruff-check format-check type-check ## Run all linting and formatting checks
lint: ruff-check format-check type-check ## Run all linting and formatting checks
ruff: ruff-check format-check ## Run Ruff linting and formatting checks
type-check: mypy ty ## Run MyPy and Ty type checks

ruff-check: ## Run Ruff linting
	@echo "$(YELLOW)Running Ruff linting...$(RESET)"
	@uv run ruff check .

format-check: ## Check code formatting without making changes
	@echo "$(YELLOW)Checking code formatting...$(RESET)"
	@uv run ruff format . --check

ruff-fix: ## Run Ruff linting with auto-fix (matches pre-commit behavior)
	@echo "$(YELLOW)Running Ruff linting with auto-fix...$(RESET)"
	@uv run ruff check . --fix || true

fmt: ## Run code formatting
	@echo "$(YELLOW)Running code formatting...$(RESET)"
	@uv run ruff format .

pre-commit-sim: ## Simulate pre-commit hooks exactly (for troubleshooting)
	@echo "$(YELLOW)Simulating pre-commit hooks...$(RESET)"
	@uv run ruff check . --fix --exit-non-zero-on-fix || echo "Ruff applied fixes"
	@uv run ruff format .

mypy: ## Run MyPy type checking
	@echo "$(YELLOW)Running MyPy type checking...$(RESET)"
	@uv run mypy

ty: ## Run Ty type checking
	@echo "$(YELLOW)Running Ty check...$(RESET)"
	@uv run ty check

test: ## Run all tests with coverage (parallel via pytest-xdist)
	@echo "$(YELLOW)Running all tests with coverage...$(RESET)"
	@uv run pytest $(PYTEST_PARALLEL) --cov --cov-report=term-missing:skip-covered --cov-report=html

test-unit: ## Run all unit tests with coverage (parallel via pytest-xdist)
	@echo "$(YELLOW)Running unit tests with coverage...$(RESET)"
	@uv run pytest $(PYTEST_PARALLEL) --cov --cov-report=term-missing:skip-covered --cov-report=html -m "unit"

# Jenkins CI/CD specific test targets with XML output
test-ci: ## Run all tests with CI-friendly output (JUnit XML + Coverage XML)
	@echo "$(YELLOW)Running tests with CI-friendly output...$(RESET)"
	@uv run pytest $(PYTEST_PARALLEL) --cov --cov-report=term-missing --cov-report=html --cov-report=xml:coverage.xml --cov-fail-under=75 --junitxml=test-results.xml -m "not integration"

# Security and Quality Assurance
security-scan: ## Run security scans
	@echo "$(YELLOW)Running security scans...$(RESET)"
	@uv run gitleaks dir -v .

pre-commit-run: ## Run pre-commit on all files
	@echo "$(YELLOW)Running pre-commit on all files...$(RESET)"
	@uv run pre-commit run --all-files

# Development shortcuts
dev: start ## Alias for start command

# Release and versioning
release-dry: ## Dry run semantic release
	@echo "$(YELLOW)Running semantic release dry run...$(RESET)"
	@uv run semantic-release version --print

release: ## Create a new release
	@echo "$(YELLOW)Creating new release...$(RESET)"
	@uv run semantic-release version

# Environment management
env-check: ## Check environment setup
	@echo "$(YELLOW)Checking environment setup...$(RESET)"
	@echo "$(BLUE)Python version:$(RESET) $$(python --version 2>/dev/null || echo 'Not found')"
	@echo "$(BLUE)uv version:$(RESET) $$(uv --version 2>/dev/null || echo 'Not found')"
	@echo "$(BLUE)Docker version:$(RESET) $$(docker --version 2>/dev/null || echo 'Not found')"
	@echo "$(BLUE)Docker Compose version:$(RESET) $$(docker compose version 2>/dev/null || echo 'Not found')"
	@echo "$(BLUE)Pre-commit installed:$(RESET) $$(uv run pre-commit --version 2>/dev/null || echo 'Not found')"
	@if [ -f .env ]; then \
		echo "$(GREEN)✓ .env file exists$(RESET)"; \
	else \
		echo "$(YELLOW)⚠ .env file not found - copy from .env.example$(RESET)"; \
	fi
