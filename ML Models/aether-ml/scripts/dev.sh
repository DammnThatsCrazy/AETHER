#!/usr/bin/env bash
# =============================================================================
# Aether ML — Development CLI
#
# Usage:
#   ./scripts/dev.sh <command> [args...]
#
# Commands:
#   setup         Install all dependencies (including dev extras)
#   test          Run full pytest suite (pass extra args after --)
#   train         Train a model: dev.sh train <model_name|all>
#   serve         Start FastAPI serving API locally
#   export        Export edge models to TF.js / ONNX / TFLite
#   lint          Run ruff linter + mypy type checker
#   format        Auto-format with black + ruff --fix
#   docker-up     Start the Docker Compose dev stack
#   docker-down   Tear down the Docker Compose dev stack
#   clean         Remove build artifacts, caches, and temp files
#   help          Show this message
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

PYTHON="${PYTHON:-python}"

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

cmd_setup() {
    echo -e "${BLUE}[aether] Installing dependencies...${NC}"
    pip install -e ".[dev]"
    echo -e "${GREEN}[aether] Setup complete.${NC}"
}

cmd_test() {
    echo -e "${BLUE}[aether] Running tests...${NC}"
    shift || true
    $PYTHON -m pytest tests/ -v --tb=short "$@"
}

cmd_train() {
    local model="${2:-all}"
    echo -e "${BLUE}[aether] Training model: ${model}${NC}"
    if [ "$model" = "all" ]; then
        $PYTHON -m training.pipelines.train --model all --output-dir /tmp/aether-models
    else
        $PYTHON -m training.pipelines.train --model "$model" --output-dir /tmp/aether-models
    fi
}

cmd_serve() {
    echo -e "${BLUE}[aether] Starting serving API on port 8000...${NC}"
    $PYTHON -m serving.src.api
}

cmd_export() {
    local model="${2:-all}"
    echo -e "${BLUE}[aether] Exporting edge models: ${model}${NC}"
    $PYTHON -c "
from export.exporter import export_all_edge_models
results = export_all_edge_models()
for name, info in results.items():
    print(f'  {name}: {info}')
"
}

cmd_lint() {
    echo -e "${BLUE}[aether] Linting...${NC}"
    ruff check .
    mypy common/ edge/ server/ serving/ --ignore-missing-imports
    echo -e "${GREEN}[aether] Lint passed.${NC}"
}

cmd_format() {
    echo -e "${BLUE}[aether] Formatting...${NC}"
    black .
    ruff check --fix .
    echo -e "${GREEN}[aether] Format complete.${NC}"
}

cmd_docker_up() {
    echo -e "${BLUE}[aether] Starting Docker Compose stack...${NC}"
    docker compose -f docker/docker-compose.yml up -d
    echo -e "${GREEN}[aether] Services running:${NC}"
    echo "  Serving API:  http://localhost:8000"
    echo "  MLflow:       http://localhost:5000"
    echo "  Prometheus:   http://localhost:9090"
    echo "  Jupyter Lab:  http://localhost:8888"
    echo "  Redis:        localhost:6379"
}

cmd_docker_down() {
    echo -e "${BLUE}[aether] Stopping Docker Compose stack...${NC}"
    docker compose -f docker/docker-compose.yml down
    echo -e "${GREEN}[aether] Stack stopped.${NC}"
}

cmd_clean() {
    echo -e "${YELLOW}[aether] Cleaning build artifacts...${NC}"
    rm -rf build/ dist/ *.egg-info .eggs/
    rm -rf __pycache__ .pytest_cache .mypy_cache .ruff_cache
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find . -type f -name "*.pyc" -delete 2>/dev/null || true
    echo -e "${GREEN}[aether] Clean complete.${NC}"
}

cmd_help() {
    echo -e "${BLUE}Aether ML — Development CLI${NC}"
    echo ""
    echo "Usage: ./scripts/dev.sh <command> [args...]"
    echo ""
    echo "Commands:"
    echo "  setup         Install all dependencies (including dev extras)"
    echo "  test          Run full pytest suite (pass extra args after command)"
    echo "  train <name>  Train a model (or 'all')"
    echo "  serve         Start FastAPI serving API locally"
    echo "  export        Export edge models to TF.js / ONNX"
    echo "  lint          Run ruff linter + mypy type checker"
    echo "  format        Auto-format with black + ruff --fix"
    echo "  docker-up     Start the Docker Compose dev stack"
    echo "  docker-down   Tear down the Docker Compose dev stack"
    echo "  clean         Remove build artifacts, caches, and temp files"
    echo "  help          Show this message"
    echo ""
    echo "Available models:"
    echo "  intent_prediction, bot_detection, session_scorer,"
    echo "  identity_resolution, journey_prediction, churn_prediction,"
    echo "  ltv_prediction, anomaly_detection, campaign_attribution"
}

# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

case "${1:-help}" in
    setup)        cmd_setup ;;
    test)         cmd_test "$@" ;;
    train)        cmd_train "$@" ;;
    serve)        cmd_serve ;;
    export)       cmd_export "$@" ;;
    lint)         cmd_lint ;;
    format)       cmd_format ;;
    docker-up)    cmd_docker_up ;;
    docker-down)  cmd_docker_down ;;
    clean)        cmd_clean ;;
    help|*)       cmd_help ;;
esac
