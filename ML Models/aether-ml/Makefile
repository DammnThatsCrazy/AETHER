.PHONY: setup test test-unit test-integration lint format train serve docker-up docker-down export clean help

# ─────────────────────────────────────────────────────────────
# Aether ML — Development Makefile
# ─────────────────────────────────────────────────────────────

PYTHON := python
PIP := pip
PYTEST := $(PYTHON) -m pytest

# ── Setup ────────────────────────────────────────────────────

setup:  ## Install dependencies
	$(PIP) install -e ".[dev]"

# ── Testing ──────────────────────────────────────────────────

test:  ## Run all tests
	$(PYTEST) tests/ -v --tb=short

test-unit:  ## Run unit tests only
	$(PYTEST) tests/unit/ -v --tb=short

test-integration:  ## Run integration tests
	$(PYTEST) tests/integration/ -v --tb=short

test-coverage:  ## Run tests with coverage
	$(PYTEST) tests/ --cov=. --cov-report=html --cov-report=term

# ── Code Quality ─────────────────────────────────────────────

lint:  ## Lint and type-check
	ruff check .
	mypy common/ edge/ server/ serving/ --ignore-missing-imports

format:  ## Auto-format code
	black .
	ruff check --fix .

# ── Training ─────────────────────────────────────────────────

train:  ## Train all models: make train MODEL=churn_prediction
	$(PYTHON) -m training.pipelines.train --model $(or $(MODEL),all) --output-dir /tmp/aether-models

train-intent:       ; $(PYTHON) -m training.pipelines.train --model intent_prediction
train-bot:          ; $(PYTHON) -m training.pipelines.train --model bot_detection
train-session:      ; $(PYTHON) -m training.pipelines.train --model session_scorer
train-identity:     ; $(PYTHON) -m training.pipelines.train --model identity_resolution
train-journey:      ; $(PYTHON) -m training.pipelines.train --model journey_prediction
train-churn:        ; $(PYTHON) -m training.pipelines.train --model churn_prediction
train-ltv:          ; $(PYTHON) -m training.pipelines.train --model ltv_prediction
train-anomaly:      ; $(PYTHON) -m training.pipelines.train --model anomaly_detection
train-attribution:  ; $(PYTHON) -m training.pipelines.train --model campaign_attribution

# ── Serving ──────────────────────────────────────────────────

serve:  ## Start the FastAPI serving API
	$(PYTHON) -m serving.src.api

# ── Docker ───────────────────────────────────────────────────

docker-build-serving:  ## Build serving Docker image
	docker build -f docker/Dockerfile --target serving -t aether-ml-serving:latest .

docker-build-training:  ## Build training Docker image
	docker build -f docker/Dockerfile --target training -t aether-ml-training:latest .

docker-up:  ## Start full Docker Compose stack
	cd docker && docker compose up -d

docker-down:  ## Stop Docker Compose stack
	cd docker && docker compose down

docker-logs:  ## View Docker logs
	cd docker && docker compose logs -f

# ── Export ───────────────────────────────────────────────────

export:  ## Export edge models to TF.js/ONNX
	$(PYTHON) -c "from export.exporter import export_all_edge_models; print(export_all_edge_models())"

# ── Cleanup ──────────────────────────────────────────────────

clean:  ## Remove build artifacts
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true

# ── Help ─────────────────────────────────────────────────────

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
