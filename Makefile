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
        ml-train-smoke ml-artifact-verify ml-docs-check ml-container-build ml-ci \
        generate-ml-manifest ml-container-smoke ml-staging-smoke ml-load-test \
        lint format typecheck \
        serve-backend serve-ml \
        dev dev-streaming dev-analytics dev-notebooks dev-full dev-down \
        docker-up docker-down docker-logs \
        smoke byok-reencrypt \
        clean validate-docs validate-frontmatter validate-ml-registry extract-docs docs-drift docs-stamp docs bump-version \
        repo-doctor repo-doctor-fix docs-check ci-check docs-fix \
        frontend-data-truth frontend-data-truth-bundles frontend-route-state \
        frontend-data-truth-report \
        demo-seed demo-reset demo-status demo-verify dev-demo \
        clean-install-smoke demo-seed-smoke demo-reset-smoke \
        design-partner-demo-up design-partner-demo-seed design-partner-demo-check design-partner-demo-down \
        temporal-integrity temporal-contract-parity mutation-gateway-check exploration-readiness \
        production-status release-gate ops-readiness help \
        validate-profile-config validate-cost-policy validate-cost-policy-terraform validate-delivery-topology \
        validate-route-registry validate-implementation-ledger validate-reference-packs \
        validate-storage-policies audit-readiness-check founding-tenant-release-gate validate-founding-tenant-surface runtime-readiness-gate integration-durable integration-faults \
        validate-terraform-profile-policy validate-cost-model test-terraform-profiles test-runtime-topology \
        test-workflow-controls test-cost-model test-staging-lifecycle test-plan-policy \
        deployment-readiness-score collect-deployment-evidence deployment-profile-gate validate-staging-budget

# Centralized subsystem paths — single place to rename if directories move.
BACKEND_DIR := Backend Architecture/aether-backend
ML_DIR      := ML Models/aether-ml
AGENT_DIR   := Agent Layer
DEMO_TENANT_ID ?= aether-demo-v1
DEMO_SEED_NAMESPACE ?= aether-demo-v1
DEMO_DATABASE_URL ?= postgresql://aether:aether_dev_password@localhost:5432/aether
PYTHON ?= python3
# The live Terraform root. NOT terraform/environments/* — that tree references
# seven modules that do not exist and `terraform init` fails there.
TF_DIR      := AWS Deployment/aether-aws/terraform

# Project virtualenv. The system interpreter resolves /usr/lib/python3/dist-packages,
# where Debian's cryptography build panics under pyo3 and its PyJWT cannot be replaced
# by pip. Gates must run against this isolated interpreter, not the system one.
VENV        := .venv
VENV_PY     := $(VENV)/bin/python

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

bootstrap: ## Create an isolated .venv and install all extras (reproducible toolchain)
	python3 -m venv $(VENV)
	$(VENV_PY) -m pip install --upgrade pip setuptools wheel
	$(VENV_PY) -m pip install -e ".[all]"
	$(VENV_PY) scripts/validate_toolchain.py

toolchain-check: ## Assert every release-critical dependency imports (fails, never skips)
	$(VENV_PY) scripts/validate_toolchain.py

setup: ## Install all Python dependencies in editable mode
	pip install -e ".[all]"

setup-dev: ## Install dev-only dependencies (security + tests)
	pip install -e ".[dev,security]"

setup-minimal: ## Install minimal dependencies (security module only)
	pip install -e ".[security]"

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

test: ## Run every Python test subsystem: root tests/, full backend tree, and ML tests/ (suites run separately to avoid conftest collision; TypeScript and Smart Contracts have their own gates -- see ci-check)
	python -m pytest tests/ -v
	python -m pytest "$(BACKEND_DIR)/tests/" -v
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

ml-docs-check: ## Check ML documentation consistency (blocking — all checks must pass)
	python scripts/validate_ml_registry.py
	python scripts/docs_drift.py --strict
	python scripts/generate_ml_manifest.py --check

generate-ml-manifest: ## Generate docs/_generated/ml-implementation-manifest.json from registry
	python scripts/generate_ml_manifest.py

ml-container-build: ## Build all ML Docker stages (requires Docker daemon)
	docker build --target serving    -t aether-ml-serving:dev    "$(ML_DIR)"
	docker build --target training   -t aether-ml-training:dev   "$(ML_DIR)"
	docker build --target features   -t aether-ml-features:dev   "$(ML_DIR)"
	docker build --target monitoring -t aether-ml-monitoring:dev "$(ML_DIR)"

ml-container-smoke: ## Health/ready/predict smoke against built serving container (requires Docker; fails closed on a non-200 /ready)
	@echo "Building serving image for smoke test..."
	docker build --target serving -t aether-ml-serving:smoke "$(ML_DIR)" -q
	docker run --rm -d --name aether-ml-smoke -p 8765:8000 -e AETHER_ENV=local aether-ml-serving:smoke
	sleep 4
	@status=0; \
	curl -sf http://localhost:8765/health | python -m json.tool | grep '"status"' || status=1; \
	ready_code=$$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8765/ready || echo 000); \
	if [ "$$ready_code" != "200" ]; then \
	  echo "ERROR: /ready returned HTTP $$ready_code (expected 200)"; status=1; \
	fi; \
	docker stop aether-ml-smoke >/dev/null 2>&1; \
	exit $$status
	@echo "Container smoke test complete."

ml-staging-smoke: ## Staging-like integration run (AETHER_ENV=staging, no stubs, expects local services)
	AETHER_ENV=staging \
	python -m pytest "$(ML_DIR)/tests/integration/" -v -m "not requires_cloud" --tb=short

ml-load-test: ## Basic latency load test for ML serving edge models (requires locust)
	@which locust > /dev/null 2>&1 || (echo "Install locust: pip install locust" && exit 1)
	locust -f "$(ML_DIR)/tests/load/locustfile.py" \
	    --headless -u 10 -r 2 --run-time 30s --host http://localhost:8000

ml-ci: ml-validate ml-test ml-train-smoke ml-artifact-verify ml-docs-check ## All blocking ML CI gates (excludes ml-container-build — run separately when Docker is available)

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

# Gate targets run on the isolated interpreter when the project venv exists:
# doc generators import backend registries (fastapi et al.), which the system
# interpreter cannot resolve — see the toolchain notes at the top of this file.
GATE_PY := $(shell test -x $(VENV_PY) && echo $(VENV_PY) || echo python)

repo-doctor: ## Validate full repo consistency (no mutations)
	$(GATE_PY) scripts/repo_doctor.py --check

repo-doctor-fix: ## Regenerate generated docs + sync, then validate
	$(GATE_PY) scripts/repo_doctor.py --fix

docs-check: ## Docs/version/frontmatter/drift checks only (fast gate)
	$(GATE_PY) scripts/repo_doctor.py --check --docs-only

ci-check: ## CI-safe full validation; fails if generators produce a diff
	$(GATE_PY) scripts/repo_doctor.py --ci

docs-fix: ## Regenerate and sync docs only
	$(GATE_PY) scripts/repo_doctor.py --fix --docs-only

frontend-data-truth: ## Enforce Aether/Kyber runtime source data-truth boundaries
	python scripts/validate_frontend_data_truth.py

frontend-data-truth-bundles: ## Build and scan Aether/Kyber production bundles for synthetic literals
	python scripts/validate_frontend_data_truth.py --build-bundles

frontend-route-state: ## Enforce exhaustive frontend route empty/error coverage
	python scripts/validate_frontend_route_state_matrix.py --enforce

frontend-data-truth-report: ## Run release certification and write machine-readable evidence
	python scripts/generate_frontend_data_truth_report.py

demo-seed: ## Explicitly seed the versioned backend demo dataset
	cd "$(BACKEND_DIR)" && AETHER_ENV="$${AETHER_ENV:-local}" DATABASE_URL="$(DEMO_DATABASE_URL)" \
		$(PYTHON) -m services.demo_seed.cli seed --tenant "$(DEMO_TENANT_ID)" --namespace "$(DEMO_SEED_NAMESPACE)"

demo-status: ## Show backend demo seed ledger status
	cd "$(BACKEND_DIR)" && AETHER_ENV="$${AETHER_ENV:-local}" DATABASE_URL="$(DEMO_DATABASE_URL)" \
		$(PYTHON) -m services.demo_seed.cli status --tenant "$(DEMO_TENANT_ID)" --namespace "$(DEMO_SEED_NAMESPACE)"

demo-verify: ## Verify the demo manifest checksum, records, and provenance
	cd "$(BACKEND_DIR)" && AETHER_ENV="$${AETHER_ENV:-local}" DATABASE_URL="$(DEMO_DATABASE_URL)" \
		$(PYTHON) -m services.demo_seed.cli verify --tenant "$(DEMO_TENANT_ID)" --namespace "$(DEMO_SEED_NAMESPACE)"

demo-reset: ## Reset only seeded records (requires DEMO_RESET_CONFIRMATION)
	@if [ -z "$(DEMO_RESET_CONFIRMATION)" ]; then \
		echo 'Set DEMO_RESET_CONFIRMATION="RESET $(DEMO_TENANT_ID) $(DEMO_SEED_NAMESPACE)"'; exit 1; \
	fi
	cd "$(BACKEND_DIR)" && AETHER_ENV="$${AETHER_ENV:-local}" DATABASE_URL="$(DEMO_DATABASE_URL)" \
		$(PYTHON) -m services.demo_seed.cli reset --tenant "$(DEMO_TENANT_ID)" --namespace "$(DEMO_SEED_NAMESPACE)" --confirm "$(DEMO_RESET_CONFIRMATION)"

dev-demo: ## Explicitly start local backend with in-process demo seeding
	AETHER_ENV=local AETHER_DEMO_SEED_ON_START=true \
	AETHER_DEMO_TENANT_ID="$(DEMO_TENANT_ID)" AETHER_DEMO_SEED_NAMESPACE="$(DEMO_SEED_NAMESPACE)" \
	docker compose up -d
	@echo "Demo seed requested explicitly. Run 'make demo-verify' after backend startup."

clean-install-smoke: ## Verify normal startup has no seed run and truthful empty state
	cd "$(BACKEND_DIR)" && $(PYTHON) -m pytest -q -o addopts='' tests/test_demo_seed.py -k "clean_install or normal_startup"
	$(PYTHON) scripts/validate_frontend_data_truth.py

demo-seed-smoke: ## Verify seed visibility, provenance, checksum, and idempotency
	cd "$(BACKEND_DIR)" && $(PYTHON) -m pytest -q -o addopts='' tests/test_demo_seed.py -k "idempotent or status_contract or production_refuses or startup_seed_refuses"

demo-reset-smoke: ## Verify reset isolation, control-record preservation, and audit
	cd "$(BACKEND_DIR)" && $(PYTHON) -m pytest -q -o addopts='' tests/test_demo_seed.py -k "reset or tenant_ids_are_isolated"

# ---------------------------------------------------------------------------
# Design-partner demo (M7) — local/automated end-to-end demo stack
# ---------------------------------------------------------------------------
# Brings up postgres + backend (migrations applied), seeds the versioned demo
# dataset (notifications/continuations/exceptions/incidents/runs/reviews),
# and verifies the seeded state is API-visible. Provider fakes run in-process
# under AETHER_ENV=local and fail closed outside local/dev. JWT_SECRET here is
# a local-only demo default; staging/prod still require bootstrap.sh.
design-partner-demo-up: ## Bring up the design-partner demo stack (postgres + backend + migrations)
	docker compose --profile migrate run --rm migrate
	JWT_SECRET="$${JWT_SECRET:-local-design-partner-demo-secret}" AETHER_ENV=local docker compose up -d
	@echo "Design-partner demo stack is up. Run 'make design-partner-demo-seed' then 'make design-partner-demo-check'."

design-partner-demo-seed: ## Seed the design-partner demo dataset (idempotent; safe reset via demo-reset)
	$(MAKE) demo-seed

design-partner-demo-check: ## Verify the demo dataset is seeded, provenance-clean, and API-visible
	$(MAKE) demo-verify
	$(MAKE) demo-seed-smoke
	$(MAKE) demo-reset-smoke

design-partner-demo-down: ## Stop the design-partner demo stack
	docker compose down
	@echo "Design-partner demo stack stopped. Seeded records persist in postgres; reset with 'make demo-reset'."

bump-version: ## Bump version across all files (usage: make bump-version V=8.4.0)
	@if [ -z "$(V)" ]; then echo "Usage: make bump-version V=8.4.0"; exit 1; fi
	python scripts/bump_version.py $(V)

# ---------------------------------------------------------------------------
# Graph — layer exhaustiveness, write safety, replay workloads
# ---------------------------------------------------------------------------

graph-test: ## Run all graph tests (root-level + backend tests)
	python -m pytest tests/graph/ "Backend Architecture/aether-backend/tests/graph/" -v --tb=short

graph-replay: ## Run synthetic graph replay workload (in-memory, no Neptune required)
	python scripts/graph/replay_relationship_layers.py

graph-release-check: ## Machine-readable graph release gate (exits 0 on pass, 1 on fail)
	python scripts/graph/check_graph_release_gate.py

graph-docs-check: ## Docs drift check scoped to graph source files
	python scripts/docs_drift.py --strict

# ---------------------------------------------------------------------------
# Production status & release gate
# ---------------------------------------------------------------------------

generate-contracts: ## Regenerate all contract artifacts from JSON canonical registries
	python scripts/generate_contracts.py

generate-contracts-check: ## CI gate — exits 1 if generated contract artifacts differ from committed
	python scripts/generate_contracts.py --check

# ---------------------------------------------------------------------------
# Mobile / continuity / notification productization gates (program C0-C8)
# ---------------------------------------------------------------------------
.PHONY: mobile-contracts-check continuity-check notification-check notification-provider-check mobile-typecheck mobile-test mobile-app-typecheck mobile-app-test mobile-compliance-check

mobile-compliance-check: ## CI gate — mobile compliance umbrella: privacy manifests + DSR coverage + contract parity + distribution-profile + SDK conformance
	$(MAKE) privacy-manifest-check
	$(MAKE) dsr-coverage-check
	$(MAKE) mobile-contracts-check
	$(MAKE) mobile-build-check
	$(GATE_PY) scripts/release/sdk_conformance.py --quiet

mobile-typecheck: ## CI gate — TypeScript typecheck of the mobile SDK packages
	npm run typecheck --workspace=packages/mobile-core --if-present
	npm run typecheck --workspace=packages/mobile-ui --if-present

mobile-test: ## CI gate — unit tests for the mobile SDK packages
	npm run test --workspace=packages/mobile-core --if-present
	npm run test --workspace=packages/mobile-ui --if-present

mobile-app-typecheck: ## CI gate — TypeScript typecheck of the Expo app shells (needs mobile-core dist, gitignored)
	npm run build --workspace=packages/mobile-core
	npm run typecheck --workspace=apps/aether-mobile
	npm run typecheck --workspace=apps/kyber-mobile

mobile-app-test: ## CI gate — app-level unit tests (no-op until C5 screens land tests in M3/M4; kept --if-present)
	npm run test --workspace=apps/aether-mobile --if-present
	npm run test --workspace=apps/kyber-mobile --if-present

delivery-safety-check: ## CI gate — D11 delivery-safety validator (unsafe delivery patterns fail the build)
	$(GATE_PY) scripts/release/validate_delivery_safety.py

mobile-build-check: ## Mobile app scaffold invariants + honest native-build posture (report; exit 0 unless a scaffold is broken)
	python scripts/mobile_build_check.py

.PHONY: privacy-manifest-check dsr-coverage-check
privacy-manifest-check: ## CI gate — regenerate app privacy manifests (Apple + Play) and fail on drift
	python scripts/generate_privacy_manifests.py --check

dsr-coverage-check: ## CI gate — every principal-scoped mobile table is reachable by a DSR erasure
	python scripts/release/check_dsr_coverage.py

mobile-contracts-check: ## CI gate — mobile/continuity/notification TS<->Python contract parity
	python -m pytest tests/contracts/test_continuation_contract_parity.py \
		tests/contracts/test_sync_event_contract_parity.py \
		tests/contracts/test_delivery_receipt_parity.py \
		tests/contracts/test_notification_contract_parity.py \
		tests/contracts/test_mobile_projection_contract_parity.py -q

continuity-check: ## CI gate — cross-device continuation plane + client-sync feed
	python -m pytest \
		"$(BACKEND_DIR)/tests/unit/test_continuation_repo.py" \
		"$(BACKEND_DIR)/tests/unit/test_continuation_routes.py" \
		"$(BACKEND_DIR)/tests/unit/test_continuation_ddl_parity.py" \
		"$(BACKEND_DIR)/tests/unit/test_client_sync_repo.py" \
		"$(BACKEND_DIR)/tests/unit/test_client_sync_routes.py" \
		"$(BACKEND_DIR)/tests/unit/test_client_sync_ddl_parity.py" \
		"$(BACKEND_DIR)/tests/unit/test_continuation_sync_integration.py" -q

notification-check: ## CI gate — notification/delivery contract twins
	python -m pytest tests/contracts/test_notification_contract_parity.py \
		tests/contracts/test_delivery_receipt_parity.py -q

notification-provider-check: ## CI gate — mobile push/email provider adapters + local fakes
	python -m pytest \
		"$(BACKEND_DIR)/tests/unit/test_notification_provider_adapters.py" \
		"$(BACKEND_DIR)/tests/unit/test_delivery_adapters.py" -q

credentials-inventory: ## Credential registry inventory (report; never prints secrets; exit 0)
	python scripts/credentials_status.py --mode inventory

credentials-preflight: ## Credential preflight — no live send; --strict blocks missing required creds
	python scripts/credentials_status.py --mode preflight

credentials-activation-smoke: ## Credential activation posture — no live send; never reports "ready"
	python scripts/credentials_status.py --mode activation-smoke

validate-schema-parity: ## Check event-registry.json, TS, and Python are in parity
	python scripts/validate_event_schema_parity.py

validate-mobile-event-parity: ## Check event-registry.json, iOS, and Android event maps are in parity
	python scripts/validate_mobile_event_parity.py

validate-consent-parity: ## Check consent-registry.json, TS, and Python are in parity
	python scripts/validate_consent_schema_parity.py

test\:contracts: ## Run contract registry parity tests (TS + Python)
	python scripts/validate_event_schema_parity.py
	python scripts/validate_mobile_event_parity.py
	python scripts/validate_consent_schema_parity.py

test\:privacy: ## Run privacy and consent model tests
	python -m pytest tests/unit/test_extract_events.py tests/unit/test_extract_more.py tests/unit/test_ingestion_batch.py -v

test\:ingestion-roundtrip: ## Run SDK→Bronze field round-trip tests
	python -m pytest tests/unit/test_ingestion_roundtrip.py -v

validate-meter-names: ## Check metrics.increment() names in ingestion/connector paths are canonical
	python scripts/validate_meter_names.py

validate-reference-packs: ## Validate agent-access reference packs (schema, unique pack ids, grounded reference packs)
	python scripts/validate_reference_packs.py

# ── Unified Intelligence Plane gates ────────────────────────────────────────
temporal-integrity: ## Temporal static gates + kernel/ingestion temporal tests
	python scripts/validate_temporal_integrity.py
	python -m pytest tests/unit/temporal -q -o addopts=""

temporal-contract-parity: ## Temporal + platform contract generators clean, TS/Py parity green
	python scripts/generate_platform_contracts.py --check
	python -m pytest tests/contracts -q -o addopts=""

mutation-gateway-check: ## Graph write-path freeze (direct writers pending gateway migration)
	python scripts/validate_graph_write_paths.py

exploration-readiness: ## Exploration fabric contract + registry + planner gates (grows per PR)
	python -m pytest tests/contracts/test_exploration_contract_parity.py \
		tests/contracts/test_filter_field_registry_parity.py \
		tests/contracts/test_surface_capability_parity.py \
		tests/unit/exploration -q -o addopts=""

production-status: ## Readiness scorecard + blockers + live consistency checks (advisory)
	python scripts/production_status.py

credentialless-certification: ## Provider certification matrix + honest CredentialReadiness states (report; exit 0)
	python scripts/credentialless_certification.py

credentialless-certification-strict: ## Enforce every first-release provider >= CREDENTIAL_WAITING (no SCAFFOLDED); PR7-time gate
	python scripts/credentialless_certification.py --strict

.PHONY: financial-credential-readiness financial-credential-readiness-strict payment-rails-certification stablecoin-observer-certification financial-pilot-preflight

financial-credential-readiness: ## Financial cohort (payments + stablecoin_chain) credential-readiness truth (report; exit 0)
	python scripts/financial_credential_readiness.py

financial-credential-readiness-strict: ## Fail-closed: every financial adapter READY (>= CREDENTIAL_WAITING, checks pass); NOT wired into ci-check
	python scripts/financial_credential_readiness.py --strict

payment-rails-certification: ## Fail-closed payment-rail cohort certification (Privy/Stripe/Coinbase/MoonPay/Bridge)
	python scripts/financial_credential_readiness.py --domain payments --strict

stablecoin-observer-certification: ## Fail-closed stablecoin-chain observer certification (EVM + Solana)
	python scripts/financial_credential_readiness.py --domain stablecoin_chain --strict

financial-pilot-preflight: ## Compose: strict financial readiness gate + validate the financial observation pilot manifest (fail-closed)
	python scripts/financial_credential_readiness.py --strict
	python scripts/validate_pilot_manifest.py config/pilot/examples/financial-observation.yaml --strict-providers

audit-prep: ## Smart contract pre-audit checklist (exit 1 if blockers found with --check)
	python scripts/smart_contract_audit_prep.py

ops-readiness: ## One-person ops readiness gate (flags, stores, bridge fail-closed, approval gating)
	python scripts/ops_readiness.py

release-gate: ## Full release gate: repo consistency (CI mode) + strict production status + ops readiness + founding-tenant control spine
	$(GATE_PY) scripts/repo_doctor.py --ci
	$(GATE_PY) scripts/production_status.py --strict
	$(GATE_PY) scripts/ops_readiness.py
	$(GATE_PY) scripts/release/check_foundation.py
	$(GATE_PY) scripts/release/check_implementation_ledger.py
	$(GATE_PY) scripts/release/check_profile_config.py
	$(GATE_PY) scripts/release/check_cost_policy.py
	$(GATE_PY) scripts/release/check_cost_policy_terraform.py
	$(GATE_PY) scripts/release/check_delivery_topology.py
	# Plan-level deployment-profile enforcement. The plan-policy gate emits the
	# inventory the cost model prices, so the order here is a real dependency.
	$(GATE_PY) scripts/release/check_terraform_plan_policy.py \
		--profile "$(PLAN_PROFILE)" --plan-json "$(PLAN_JSON)"
	$(GATE_PY) scripts/release/check_cost_model.py \
		--profile "$(PLAN_PROFILE)" --inventory artifacts/profile-resource-inventory.json
	$(MAKE) validate-staging-budget
	$(GATE_PY) scripts/release/check_deployment_readiness.py
	$(GATE_PY) scripts/release/check_route_registry.py
	$(GATE_PY) scripts/release/check_storage_policies.py
	$(GATE_PY) scripts/validate_sdk_release_alignment.py
	$(GATE_PY) scripts/release/sdk_conformance.py --quiet
	$(GATE_PY) scripts/release/check_required_checks.py
	$(MAKE) security-release-check
	$(MAKE) supply-chain-check

# ---------------------------------------------------------------------------
# Supply-chain & security release gates
#   Local commands are advisory; release commands fail closed (no `|| true`).
#   Fail-closed policy: npm production CRITICAL vulns, high-confidence secrets,
#   and SBOM generation. Advisory (surfaced, tracked): npm production HIGH vulns
#   and pip-audit (which also reports base-image CVEs outside the app's control).
# ---------------------------------------------------------------------------

secret-scan: ## Fail-closed secret scan of tracked files
	python scripts/security/secret_scan.py

secret-scan-advisory: ## Secret scan (advisory; never fails)
	python scripts/security/secret_scan.py --advisory

sbom: ## Generate a CycloneDX SBOM of the Python environment (reports/sbom/)
	@mkdir -p reports/sbom
	$(GATE_PY) -m cyclonedx_py environment --output-file reports/sbom/python-sbom.json --output-format JSON
	@echo "SBOM: reports/sbom/python-sbom.json"

supply-chain-audit: ## Advisory supply-chain report (never fails)
	-npm audit --omit=dev --audit-level=high
	-$(GATE_PY) -m pip_audit --skip-editable --progress-spinner off

supply-chain-check: ## Fail-closed supply-chain gate (npm prod criticals + SBOM required)
	@echo "== npm production dependency audit — CRITICAL vulns fail =="
	npm audit --omit=dev --audit-level=critical
	@echo "== npm production HIGH-severity — advisory (tracked) =="
	-npm audit --omit=dev --audit-level=high
	@echo "== Python dependency audit — advisory (base-image CVEs tracked) =="
	-$(GATE_PY) -m pip_audit --skip-editable --progress-spinner off
	@echo "== CycloneDX SBOM generation (required) =="
	$(MAKE) sbom

security-release-check: ## Fail-closed security gate: secrets + security-control regressions
	$(GATE_PY) scripts/security/secret_scan.py
	$(GATE_PY) -m pytest tests/security/test_extraction_defense_mode.py tests/unit/test_release_profile_enforcement.py -q -o addopts=""

# ---------------------------------------------------------------------------
# Founding-tenant production — control-spine gates (additive; ci-check unchanged)
# ---------------------------------------------------------------------------

validate-profile-config: ## Validate deployment-profile matrix + founding-tenant posture
	python scripts/release/check_profile_config.py

validate-cost-policy: ## Validate production-lean cost policy (forbidden/required resources)
	python scripts/release/check_cost_policy.py

validate-cost-policy-terraform: ## Validate Terraform locals/profiles honor the production-lean cost policy
	python scripts/release/check_cost_policy_terraform.py

# ---------------------------------------------------------------------------
# Deployment-profile enforcement (FT-9)
#
# check_cost_policy_terraform.py above is a STATIC tripwire: it reads profiles.tf
# as text and proves the enable_* locals are false-by-derivation for lean. The
# targets below prove the stronger property — that a generated PLAN actually
# excludes the forbidden resources and prices within the profile's budget.
# Both are kept: the static gate needs no plan and catches a regression the
# moment it is written, the plan gate catches one the locals cannot express.
# ---------------------------------------------------------------------------

# PLAN_JSON defaults to the committed lean fixture so the gate is runnable with
# no AWS credentials. CI overrides it with a credentialed `terraform show -json`.
PLAN_PROFILE ?= production-lean
PLAN_JSON    ?= tests/fixtures/terraform_plans/production-lean-valid.json

validate-terraform-profile-policy: ## Prove a Terraform plan matches its profile's required/forbidden resources
	python scripts/release/check_terraform_plan_policy.py \
		--profile "$(PLAN_PROFILE)" --plan-json "$(PLAN_JSON)"

validate-cost-model: ## Price a plan inventory against the profile's numeric budget (fails closed on unpriced fixed cost)
	python scripts/release/check_terraform_plan_policy.py \
		--profile "$(PLAN_PROFILE)" --plan-json "$(PLAN_JSON)"
	python scripts/release/check_cost_model.py \
		--profile "$(PLAN_PROFILE)" --inventory artifacts/profile-resource-inventory.json

# Staging has its own budget (target 25 / hard 50 against a 40h awake month) and
# its own usage scenario. It was previously exercised only by unit tests, because
# every gate ran PLAN_PROFILE=production-lean and the only caller of the staging
# path needed AWS credentials — so a staging budget regression could not surface
# offline. Both wake states are gated here: asleep is where "no always-on staging
# compute" is actually provable.
validate-staging-budget: ## Plan-policy + cost gate for staging, awake and asleep
	python scripts/release/check_terraform_plan_policy.py --profile staging \
		--plan-json tests/fixtures/terraform_plans/staging-awake.json \
		--out-dir artifacts/staging-awake
	python scripts/release/check_cost_model.py --profile staging \
		--inventory artifacts/staging-awake/profile-resource-inventory.json \
		--out-dir reports/cost/staging-awake
	python scripts/release/check_terraform_plan_policy.py --profile staging \
		--plan-json tests/fixtures/terraform_plans/staging-asleep.json \
		--out-dir artifacts/staging-asleep
	python scripts/release/check_cost_model.py --profile staging \
		--inventory artifacts/staging-asleep/profile-resource-inventory.json \
		--out-dir reports/cost/staging-asleep

test-terraform-profiles: ## Provider-mocked plan tests asserting per-profile module cardinality
	cd "$(TF_DIR)" && terraform init -backend=false -input=false >/dev/null && \
		terraform validate && \
		terraform test -filter=tests/profile_plan.tftest.hcl -no-color

test-runtime-topology: ## Execution-group topology: every worker role owned by exactly one service
	python -m pytest tests/unit/test_runtime_topology.py tests/unit/test_runtime_execution_groups.py -q

test-workflow-controls: ## Structural controls: no automatic apply, no false-green, reviewed-plan integrity
	python -m pytest tests/unit/test_release_workflow_controls.py -q

test-cost-model: ## Cost-model unit tests (ceilings, fail-closed pricing, exception expiry)
	python -m pytest tests/unit/test_cost_model.py -q

test-staging-lifecycle: ## Staging wake/sleep + TTL guard structural controls
	python -m pytest tests/unit/test_staging_lifecycle_controls.py -q

test-plan-policy: ## Plan-policy validator against the pass/fail plan fixtures
	python -m pytest tests/unit/test_terraform_plan_policy.py tests/unit/test_terraform_resource_contracts.py -q

deployment-readiness-score: ## Evidence-backed readiness scorecard (code-complete vs externally verified)
	python scripts/release/check_deployment_readiness.py

collect-deployment-evidence: ## Materialise the release-evidence bundle with checksummed manifest
	python scripts/release/collect_evidence.py --bundle-dir release-evidence

deployment-profile-gate: ## Every deployment-profile gate that runs without AWS credentials
	$(MAKE) validate-profile-config
	$(MAKE) validate-cost-policy
	$(MAKE) validate-cost-policy-terraform
	$(MAKE) validate-delivery-topology
	$(MAKE) validate-terraform-profile-policy
	$(MAKE) validate-cost-model
	$(MAKE) validate-staging-budget
	$(MAKE) test-plan-policy
	$(MAKE) test-runtime-topology
	$(MAKE) test-workflow-controls
	$(MAKE) test-cost-model
	$(MAKE) test-staging-lifecycle
	$(MAKE) deployment-readiness-score

validate-delivery-topology: ## Validate immutable delivery and profile-to-role topology
	python scripts/release/check_delivery_topology.py

validate-route-registry: ## Validate route policy registry seed schema
	python scripts/release/check_route_registry.py

validate-implementation-ledger: ## Reject stale or overstated implementation-ledger claims
	python scripts/release/check_implementation_ledger.py

validate-storage-policies: ## Validate storage policy registry (schema + per-persistent-type coverage)
	python scripts/release/check_storage_policies.py

validate-required-release-checks: ## Validate required-check catalog against hosted workflows
	python scripts/release/check_required_checks.py

sdk-release-gate: ## SDK metadata, conformance, and hosted required-check contract
	python scripts/validate_sdk_release_alignment.py
	python scripts/release/sdk_conformance.py --quiet
	python scripts/release/check_required_checks.py

audit-readiness-check: ## Validate the founding-tenant control spine (ledger + catalog + posture)
	python scripts/release/check_foundation.py

founding-tenant-release-gate: ## control-spine validators + durable-suite proof + evidence bundle (never passes without the durable suites)
	python scripts/repo_doctor.py --ci
	python scripts/release/check_foundation.py
	python scripts/release/check_implementation_ledger.py
	python scripts/release/check_profile_config.py
	python scripts/release/check_cost_policy.py
	python scripts/release/check_cost_policy_terraform.py
	python scripts/release/check_route_registry.py
	python scripts/release/check_storage_policies.py
	python scripts/release/check_founding_tenant_surface.py
	python scripts/validate_sdk_release_alignment.py
	python scripts/release/sdk_conformance.py --quiet
	python scripts/release/check_required_checks.py
	@if [ -n "$(FOUNDING_GATE_HOSTED_EVIDENCE)" ]; then \
		echo "Founding gate: verifying hosted evidence via collect_evidence.py --release-mode (requires GITHUB_TOKEN/GITHUB_REPOSITORY and FOUNDING_GATE_CI_LOG)"; \
		python scripts/release/collect_evidence.py --release-mode \
			--github-checks "$(FOUNDING_GATE_HOSTED_EVIDENCE)" \
			$(if $(FOUNDING_GATE_CI_LOG),--ci-log "$(FOUNDING_GATE_CI_LOG)"); \
	else \
		echo "Founding gate: running the durable suites locally (set FOUNDING_GATE_HOSTED_EVIDENCE=<checks.json> to substitute API-verified hosted evidence). Missing Docker or staging access is a gate FAILURE, not a skip."; \
		$(MAKE) runtime-readiness-gate; \
		$(MAKE) integration-durable; \
		$(MAKE) integration-faults; \
		$(MAKE) staging-preflight; \
		python scripts/release/collect_evidence.py; \
	fi

validate-founding-tenant-surface: ## Validate founding-tenant routes, roles, consumers, flags, and rollout controls
	python scripts/release/check_founding_tenant_surface.py

runtime-readiness-gate: ## Validate durable backend, explicit runtime-role, and consumer ownership topology
	python scripts/release/check_runtime_readiness.py

integration-durable: ## Run the production-shaped durable integration suite (requires Docker)
	docker compose -f deploy/integration/docker-compose.durable.yml config --quiet
	docker compose -f deploy/integration/docker-compose.durable.yml run --rm api python -m pytest tests/integration/test_batch_endpoint.py -q

integration-faults: ## Run durable outbox/storage crash, replay, and lifecycle fault tests (requires Docker)
	docker compose -f deploy/integration/docker-compose.durable.yml config --quiet
	docker compose -f deploy/integration/docker-compose.durable.yml run --rm api python -m pytest tests/unit/test_outbox_relay.py tests/unit/test_object_backed_bronze.py -q

.PHONY: staging-preflight staging-preflight-dry-run \
        staging-preflight-credentialless staging-infra-plan staging-deploy \
        pilot-smoke pilot-evidence pilot-manifest-validate staging-capability-matrix
staging-preflight: ## Staging preflight gate: env/Settings, DB migrations + table shape, Redis, HTTP health, contracts (fail-closed)
	python scripts/staging_preflight.py

staging-preflight-dry-run: ## Staging preflight self-test against committed fixtures (no live services; does not certify an environment)
	python scripts/staging_preflight.py --dry-run

# ---------------------------------------------------------------------------
# Credential-waiting staging capstone (credentialless — exits 0 without creds;
# fails closed on real code/route/scaffold/PII/float/secret/topology problems)
# ---------------------------------------------------------------------------

staging-preflight-credentialless: ## Full credentialless staging preflight: code/routes/workers/alembic/IaC/compose/mock-replay/scaffold/PII/float/secret/docs (Docker/cloud gated as honest SKIP)
	python scripts/staging_preflight_credentialless.py

staging-capability-matrix: ## Validate the canonical deploy-profile capability matrix (local compose <-> cloud terraform <-> runtime roles)
	python scripts/staging_capability_matrix.py

staging-infra-plan: ## Terraform validate/plan (or structural equivalent) — NEVER applies
	python scripts/staging_infra_plan.py

staging-deploy: ## Documented apply/helm entrypoint (cloud creds required; documented no-op without STAGING_APPLY=1)
	@echo "AETHER staging deploy — documented entrypoint. This wrapper NEVER applies on its own."
	@echo ""
	@echo "Prerequisites (cloud/credential gated — unavailable in a credentialless env):"
	@echo "  1. terraform >= 1.6 and AWS creds (AWS_ACCESS_KEY_ID/SECRET or AWS_PROFILE)"
	@echo "  2. make staging-preflight-credentialless   # must pass"
	@echo "  3. make staging-infra-plan                 # review the plan (no apply)"
	@echo ""
	@echo "Apply steps (run manually, opt-in):"
	@echo "  terraform -chdir='AWS Deployment/aether-aws/terraform' apply -var-file=profiles/staging.tfvars"
	@echo "  # migrations: run the RUN_MIGRATIONS=1 one-off ECS task (compose: make dev + 'up migrate')"
	@echo "  # verify:     make staging-preflight BASE_URL=https://api.staging.aether.io"
	@if [ "$(STAGING_APPLY)" = "1" ]; then \
	  command -v terraform >/dev/null 2>&1 || { echo ""; echo "ERROR: STAGING_APPLY=1 but terraform is not installed."; exit 1; }; \
	  echo ""; echo "STAGING_APPLY=1 set — run the apply steps above (this wrapper does not embed apply)."; \
	else \
	  echo ""; echo "STAGING_APPLY not set — documented no-op (nothing was applied)."; \
	fi

pilot-manifest-validate: ## Validate every pilot manifest under config/pilot/examples against the schema + semantics
	python scripts/validate_pilot_manifest.py

pilot-smoke: ## One-command credentialless smoke across the nine platform capabilities (mock/replay)
	python scripts/pilot_smoke.py

pilot-evidence: ## Generate the checksummed, tenant-scoped pilot evidence package (credentialless mock)
	python scripts/pilot_evidence.py --out artifacts/pilot-evidence

load-baselines: ## Record staging load baselines via Locust (requires STAGING_URL and running backend)
	mkdir -p tests/load/results
	locust -f tests/load/locustfile.py --headless -u 50 -r 10 \
	  --run-time 5m --host $(STAGING_URL) \
	  --csv tests/load/results/baseline

ml-artifacts: ## Publish staged ML model artifacts to S3 and mark promoted (requires ML_ARTIFACT_BUCKET + ML_SERVING_URL)
	python scripts/publish_ml_artifacts.py

load-smoke: ## Load smoke gate: 20 users, 30s against localhost:8000 (fails closed: unreachable backend, no traffic, and threshold breaches are all failures)
	python scripts/load_smoke.py

load-smoke-ci: ## Load smoke gate for CI pipelines (same fail-closed contract as load-smoke; distinct name for workflow wiring)
	python scripts/load_smoke.py


# ---------------------------------------------------------------------------
# Semantic Sentiment Intelligence
# ---------------------------------------------------------------------------

semantic-sentiment-unit-test: ## Run semantic/sentiment unit and API tests
	cd "Backend Architecture/aether-backend" && python -m pytest tests/semantic_intelligence -v

semantic-sentiment-test: semantic-sentiment-unit-test ## Run semantic/sentiment test suite

semantic-sentiment-release-check: ## Validate semantic/sentiment release assets
	python scripts/semantic_sentiment/check_release_gate.py

semantic-sentiment-contracts-check: ## Validate semantic/sentiment shared contract exports
	npm run build --workspace=packages/shared

semantic-sentiment-migration-check: ## Validate semantic/sentiment migration file is present
	python scripts/semantic_sentiment/check_release_gate.py

semantic-sentiment-release-check-strict: semantic-sentiment-contracts-check ## Validate semantic/sentiment assets and tests
	python scripts/semantic_sentiment/check_release_gate.py --strict

# ---------------------------------------------------------------------------
# Campaign Intelligence
# ---------------------------------------------------------------------------

campaign-test: ## Run campaign registry unit tests
	cd "Backend Architecture/aether-backend" && python -m pytest tests/unit/test_campaign_registry.py -v

campaign-integration-test: ## Run campaign registry integration tests
	cd "Backend Architecture/aether-backend" && python -m pytest tests/integration/test_campaign_registry_api.py -v

campaign-e2e: ## Run campaign registry E2E tests
	cd "Backend Architecture/aether-backend" && python -m pytest tests/e2e/test_campaign_registry_e2e.py -v

campaign-security-check: ## Run campaign registry security tests
	cd "Backend Architecture/aether-backend" && python -m pytest tests/security/test_campaign_registry_security.py -v

campaign-migration-check: ## Verify campaign registry migration round-trip
	cd "Backend Architecture/aether-backend" && alembic upgrade head && alembic downgrade -1 && alembic upgrade head

campaign-contracts-check: ## Validate campaign registry contracts
	python scripts/validate_contracts.py --domain campaign

campaign-release-check: ## Run full Campaign Intelligence release gate
	python scripts/campaign/check_campaign_release_gate.py

campaign-release-check-strict: ## Run Campaign Intelligence release gate with test suites
	python scripts/campaign/check_campaign_release_gate.py --strict


# ---------------------------------------------------------------------------
# Derivatives Intelligence
# ---------------------------------------------------------------------------

derivatives-test: ## Run derivatives ingestion/accounting foundation tests
	python -m pytest tests/unit/test_derivatives_ingestion.py -v

derivatives-connector-test: derivatives-test ## Validate derivatives connector normalization and credential gates

derivatives-position-test: derivatives-test ## Validate deterministic derivatives position reconstruction

derivatives-reconciliation-test: derivatives-test ## Validate derivatives reconciliation variance detection

derivatives-replay: derivatives-test ## Validate deterministic derivatives replay fixtures

derivatives-ingestion-release-check: derivatives-test ## PR2 derivatives ingestion release gate

# ---------------------------------------------------------------------------
# Derivatives Intelligence
# ---------------------------------------------------------------------------

.PHONY: derivatives-test derivatives-connector-test derivatives-position-test derivatives-reconciliation-test derivatives-replay derivatives-ingestion-release-check derivatives-graph-check derivatives-profile-check derivatives-intelligence-release-check

derivatives-test: ## Run derivatives ingestion, accounting, reconciliation, and replay tests
	python -m pytest tests/unit/test_derivatives_ingestion.py -v

derivatives-connector-test: derivatives-test ## Run derivatives connector tests

derivatives-position-test: derivatives-test ## Run derivatives position engine tests

derivatives-reconciliation-test: derivatives-test ## Run derivatives reconciliation tests

derivatives-replay: derivatives-test ## Run derivatives replay tests

derivatives-ingestion-release-check: derivatives-test ## Run full derivatives ingestion release gate

derivatives-graph-check: ## Run derivatives intelligence graph projection tests
	python -m pytest tests/unit/test_derivatives_intelligence.py -v

derivatives-profile-check: ## Run derivatives Profile360 and campaign tests
	python -m pytest tests/unit/test_derivatives_intelligence.py -v

derivatives-intelligence-release-check: derivatives-graph-check derivatives-profile-check ## Run full derivatives intelligence release gate
	python -m pytest tests/unit/test_derivatives_ingestion.py tests/unit/test_derivatives_intelligence.py -v

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

.PHONY: derivatives-graph-check derivatives-profile-check derivatives-intelligence-release-check
derivatives-graph-check:
	python -m pytest tests/unit/test_derivatives_intelligence.py -v

derivatives-profile-check:
	python -m pytest tests/unit/test_derivatives_intelligence.py -v

derivatives-intelligence-release-check: derivatives-graph-check derivatives-profile-check
	python -m pytest tests/unit/test_derivatives_ingestion.py tests/unit/test_derivatives_intelligence.py -v

.PHONY: derivatives-product-check derivatives-ops-check derivatives-pr4-release-check
derivatives-product-check:
	python -m pytest tests/unit/test_derivatives_product.py -v

derivatives-ops-check:
	python -m pytest tests/unit/test_derivatives_product.py -v

derivatives-pr4-release-check: derivatives-product-check derivatives-ops-check derivatives-intelligence-release-check
	python -m pytest tests/unit/test_derivatives_ingestion.py tests/unit/test_derivatives_intelligence.py tests/unit/test_derivatives_product.py -v

.PHONY: derivatives-contracts-check derivatives-migration-check derivatives-accounting-test derivatives-security-check derivatives-privacy-check derivatives-load-test derivatives-docs-check derivatives-release-check derivatives-release-check-strict

derivatives-contracts-check:
	python -m pytest tests/unit/test_derivatives_release.py -v

derivatives-migration-check:
	python -m pytest tests/unit/test_derivatives_ingestion.py -v

derivatives-accounting-test: derivatives-position-test

derivatives-security-check:
	python -m pytest tests/unit/test_derivatives_product.py tests/unit/test_derivatives_release.py -v

derivatives-privacy-check:
	python -m pytest tests/unit/test_derivatives_intelligence.py tests/unit/test_derivatives_release.py -v

derivatives-load-test:
	python -m pytest tests/unit/test_derivatives_release.py -v

derivatives-docs-check:
	python scripts/validate_frontmatter.py
	python scripts/docs_drift.py --strict

derivatives-release-check: derivatives-pr4-release-check derivatives-contracts-check derivatives-security-check derivatives-privacy-check derivatives-docs-check

derivatives-release-check-strict: derivatives-release-check derivatives-load-test
	python -m pytest tests/unit/test_derivatives_ingestion.py tests/unit/test_derivatives_intelligence.py tests/unit/test_derivatives_product.py tests/unit/test_derivatives_release.py -v
