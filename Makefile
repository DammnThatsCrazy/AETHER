# =============================================================================
# Aether Platform — Root Makefile
#
# Quick start:
#   make setup     Install all dependencies (editable mode)
#   make test      Run all tests across all subsystems
#   make lint      Lint all Python code
#   make help      Show all available targets
# =============================================================================

.DEFAULT_GOAL := help
.PHONY: setup setup-dev setup-minimal \
        test test-security test-ml test-coverage \
        lint format typecheck \
        serve-backend serve-ml \
        docker-up docker-down docker-logs \
        clean validate-docs validate-frontmatter extract-docs docs-drift docs-stamp docs bump-version help

# Centralized subsystem paths — single place to rename if directories move.
BACKEND_DIR := Backend Architecture/aether-backend
ML_DIR      := ML Models/aether-ml
AGENT_DIR   := Agent Layer

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

setup: ## Install all Python dependencies in editable mode
	pip install -e ".[all]"

setup-dev: ## Install dev-only dependencies (security + tests)
	pip install -e ".[dev,security]"

setup-minimal: ## Install minimal dependencies (security module only)
	pip install -e ".[security]"

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test: ## Run ALL tests across all subsystems (matches pyproject.toml testpaths)
	python -m pytest tests/ "$(ML_DIR)/tests/" -v

test-security: ## Run extraction defense tests only
	python -m pytest tests/security/ -v

test-ml: ## Run ML model tests only
	python -m pytest "$(ML_DIR)/tests/" -v

test-coverage: ## Run tests with coverage report (all subsystems)
	python -m pytest tests/ "$(ML_DIR)/tests/" \
		--cov=security \
		--cov="$(BACKEND_DIR)" \
		--cov-report=term-missing -v

# ---------------------------------------------------------------------------
# Code Quality
# ---------------------------------------------------------------------------

lint: ## Lint all Python code with ruff
	python -m ruff check .

format: ## Format all Python code with ruff
	python -m ruff format .

typecheck: ## Run mypy type checking
	python -m mypy security/ --ignore-missing-imports

# ---------------------------------------------------------------------------
# Serving
# ---------------------------------------------------------------------------

serve-backend: ## Start the backend API server (port 8000)
	cd "$(BACKEND_DIR)" && \
	python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

serve-ml: ## Start the ML serving API (port 8080)
	cd "$(ML_DIR)" && \
	python -m uvicorn serving.src.api:app --host 0.0.0.0 --port 8080 --reload

# ---------------------------------------------------------------------------
# Docker
# ---------------------------------------------------------------------------

docker-up: ## Start full stack via docker compose
	docker compose up -d

docker-down: ## Stop all docker services
	docker compose down

docker-logs: ## Tail logs from all docker services
	docker compose logs -f

# ---------------------------------------------------------------------------
# Version & Documentation Management
# ---------------------------------------------------------------------------

validate-docs: ## Check for version drift across docs
	python scripts/validate_docs.py

validate-frontmatter: ## Validate YAML frontmatter on docs/*.md against scripts/docs_schema.json
	python scripts/validate_frontmatter.py

extract-docs: ## Regenerate docs/_generated/*.json from canonical sources
	python scripts/docs_extract/run_all.py

docs-drift: ## Detect drift between doc source_files frontmatter and the repo
	python scripts/docs_drift.py

docs-stamp: ## Stamp last_synced_commit on every doc with source_files (after a re-review pass)
	python scripts/docs_drift.py --update

docs: ## Run the full documentation pipeline (extract + sync + validate + drift)
	python scripts/docs_extract/run_all.py
	python scripts/sync_docs.py
	python scripts/validate_docs.py
	python scripts/validate_frontmatter.py
	python scripts/docs_drift.py
	python scripts/validate_contracts.py

bump-version: ## Bump version across all files (usage: make bump-version V=8.4.0)
	@if [ -z "$(V)" ]; then echo "Usage: make bump-version V=8.4.0"; exit 1; fi
	python scripts/bump_version.py $(V)

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

clean: ## Remove caches, build artifacts, and temp files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ build/ .coverage htmlcov/ .mypy_cache/

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------

help: ## Show this help message
	@echo "Aether Platform — Available targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
