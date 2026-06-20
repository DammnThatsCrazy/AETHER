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
        ml-validate ml-test ml-test-unit ml-test-integration ml-test-security \
        ml-train-smoke ml-artifact-verify ml-docs-check ml-ci \
        lint format typecheck \
        serve-backend serve-ml \
        dev dev-streaming dev-analytics dev-notebooks dev-full dev-down \
        docker-up docker-down docker-logs \
        smoke byok-reencrypt \
        clean validate-docs validate-frontmatter validate-ml-registry extract-docs docs-drift docs-stamp docs bump-version \
        repo-doctor repo-doctor-fix docs-check ci-check docs-fix \
        production-status release-gate help

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

test: ## Run ALL tests across all subsystems (suites run separately to avoid conftest collision)
	python -m pytest tests/ -v
	python -m pytest "$(ML_DIR)/tests/" -v

test-security: ## Run extraction defense tests only
	python -m pytest tests/security/ -v

test-ml: ## Run ML model tests only
	python -m pytest "$(ML_DIR)/tests/" -v

validate-ml-registry: ## Validate ML model registry consistency (CI gate)
	python scripts/validate_ml_registry.py

# ---------------------------------------------------------------------------
# ML-specific targets (mono-prompt section 28)
# ---------------------------------------------------------------------------

ml-validate: ## Registry + contract consistency gate
	python scripts/validate_ml_registry.py

ml-test-unit: ## ML unit tests only
	python -m pytest "$(ML_DIR)/tests/unit/" -v

ml-test-integration: ## ML integration tests
	python -m pytest "$(ML_DIR)/tests/integration/" -v

ml-test-security: ## ML security tests (extraction defense)
	python -m pytest tests/security/ -v

ml-test: ml-test-unit ml-test-integration ## All ML tests

ml-train-smoke: ## Smoke-train all 9 models using synthetic deterministic fixtures
	python -m pytest "$(ML_DIR)/tests/unit/test_training_pipeline.py::TestTrainingPipelineSynthetic" -v

ml-artifact-verify: ## Verify artifact loadability and metadata for all trained models
	python -m pytest "$(ML_DIR)/tests/unit/test_training_pipeline.py::TestArtifactLoadability" -v

ml-docs-check: ## Check ML documentation consistency
	python scripts/validate_ml_registry.py
	python scripts/docs_drift.py --strict 2>/dev/null || true

ml-ci: ml-validate ml-test ml-train-smoke ml-artifact-verify ml-docs-check ## All blocking ML CI gates

test-coverage: ## Run tests with coverage report (all subsystems)
	python -m pytest tests/ \
		--cov=security \
		--cov="$(BACKEND_DIR)" \
		--cov-report=term-missing -v
	python -m pytest "$(ML_DIR)/tests/" --cov-report=term-missing -v

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
# Dev shortcuts (minimal boot — default stack only)
# ---------------------------------------------------------------------------

dev: ## Start minimal dev stack: postgres + backend only (~1.5 GB RAM, ML inline)
	docker compose up -d
	@echo ""
	@echo "  Backend API (+ ML predict routes inline): http://localhost:8000"
	@echo ""
	@echo "  Add-on profiles:"
	@echo "    make dev-streaming   LocalStack SQS+SNS+DynamoDB (prod equivalent)"
	@echo "    make dev-analytics   ClickHouse (analytics queries)"
	@echo "    make dev-notebooks   Jupyter Lab (ML training)"
	@echo "    make dev-legacy      Redis + standalone ml-serving (pre-E1/E2 rollback)"
	@echo "    make dev-full        everything"

dev-legacy: ## Start pre-E1/E2 stack with Redis + standalone ml-serving (rollback)
	docker compose --profile legacy up -d
	@echo ""
	@echo "  Backend API:  http://localhost:8000"
	@echo "  ML Serving:   http://localhost:8080"
	@echo "  Redis:        localhost:6379"

dev-streaming: ## Add LocalStack SQS+SNS+DynamoDB to the running stack (prod streaming equivalent)
	docker compose --profile streaming up -d
	@echo ""
	@echo "  LocalStack SQS+SNS+DynamoDB:  http://localhost:4566"
	@echo "  Set AWS_ENDPOINT_URL=http://localhost:4566 for local boto3 calls."

dev-analytics: ## Add ClickHouse to the running stack
	docker compose --profile analytics up -d

dev-notebooks: ## Start Jupyter Lab for ML exploration (http://localhost:8888)
	docker compose --profile notebooks up -d
	@echo ""
	@echo "  Jupyter Lab: http://localhost:8888 (no token required)"

dev-full: ## Start full stack with all optional services (~8 GB RAM)
	docker compose --profile full up -d

dev-down: ## Stop all dev services and remove containers
	docker compose --profile full down

# ---------------------------------------------------------------------------
# Docker (legacy aliases — prefer dev/dev-down for daily use)
# ---------------------------------------------------------------------------

docker-up: ## Start full stack via docker compose
	docker compose up -d

docker-down: ## Stop all docker services
	docker compose down

docker-logs: ## Tail logs from all docker services
	docker compose logs -f

# ---------------------------------------------------------------------------
# Post-deploy verification
# ---------------------------------------------------------------------------

smoke: ## Run golden-path smoke test against a live deployment (set BASE_URL and API_KEY)
	@if [ -z "$(BASE_URL)" ]; then \
	  echo "Usage: make smoke BASE_URL=https://api.example.com API_KEY=<key>"; exit 1; fi
	python scripts/smoke_test.py \
	  --base-url "$(BASE_URL)" \
	  --api-key  "$(API_KEY)" \
	  --verbose

byok-reencrypt: ## Re-encrypt BYOK keys after rotating BYOK_ENCRYPTION_KEY (see script for full usage)
	@if [ -z "$(OLD_KEY)" ] || [ -z "$(NEW_KEY)" ]; then \
	  echo "Usage: make byok-reencrypt OLD_KEY=<old-fernet-key> NEW_KEY=<new-fernet-key>"; exit 1; fi
	python scripts/byok_reencrypt.py \
	  --old-key "$(OLD_KEY)" \
	  --new-key "$(NEW_KEY)" \
	  --verbose

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

# ---------------------------------------------------------------------------
# Repo-Enforced Consistency (single command for humans, agents, and CI)
# ---------------------------------------------------------------------------

repo-doctor: ## Validate full repo consistency (no mutations)
	python scripts/repo_doctor.py --check

repo-doctor-fix: ## Regenerate generated docs + sync, then validate
	python scripts/repo_doctor.py --fix

docs-check: ## Docs/version/frontmatter/drift checks only (fast gate)
	python scripts/repo_doctor.py --check --docs-only

ci-check: ## CI-safe full validation; fails if generators produce a diff
	python scripts/repo_doctor.py --ci

docs-fix: ## Regenerate and sync docs only
	python scripts/repo_doctor.py --fix --docs-only

bump-version: ## Bump version across all files (usage: make bump-version V=8.4.0)
	@if [ -z "$(V)" ]; then echo "Usage: make bump-version V=8.4.0"; exit 1; fi
	python scripts/bump_version.py $(V)

# ---------------------------------------------------------------------------
# Production status & release gate
# ---------------------------------------------------------------------------

production-status: ## Readiness scorecard + blockers + live consistency checks (advisory)
	python scripts/production_status.py

audit-prep: ## Smart contract pre-audit checklist (exit 1 if blockers found with --check)
	python scripts/smart_contract_audit_prep.py

release-gate: ## Full release gate: repo consistency (CI mode) + strict production status
	python scripts/repo_doctor.py --ci
	python scripts/production_status.py --strict

load-smoke: ## Load smoke gate: 20 users, 30s against localhost:8000 (exits 2 if backend unreachable)
	python scripts/load_smoke.py

load-smoke-ci: ## Load smoke in CI — exits 0 when backend unreachable (non-blocking), fails on threshold breach
	python scripts/load_smoke.py || [ $$? -eq 2 ]

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
