#!/usr/bin/env bash
# =============================================================================
# Aether Backend — Development CLI
# =============================================================================

set -euo pipefail
cd "$(dirname "$0")/.."

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${BLUE}[aether]${NC} $1"; }
ok() { echo -e "${GREEN}[aether]${NC} $1"; }
err() { echo -e "${RED}[aether]${NC} $1"; }

case "${1:-help}" in
  dev)
    log "Starting ingestion service in dev mode..."
    npx tsx watch services/ingestion/src/index.ts
    ;;

  test)
    log "Running unit tests..."
    npx vitest run
    ;;

  test:watch)
    npx vitest
    ;;

  test:integration)
    log "Running integration tests..."
    npx vitest run tests/integration/
    ;;

  build)
    log "Building TypeScript..."
    npx tsc -b
    ok "Build complete"
    ;;

  lint)
    log "Linting..."
    npx eslint . --ext .ts
    ok "Lint passed"
    ;;

  typecheck)
    log "Type checking..."
    npx tsc --noEmit
    ok "Types OK"
    ;;

  docker:up)
    log "Starting Docker stack..."
    docker compose -f docker/docker-compose.yml up -d
    ok "Stack running. Ingestion: http://localhost:3001 | Kafka UI: http://localhost:8080"
    ;;

  docker:down)
    log "Stopping Docker stack..."
    docker compose -f docker/docker-compose.yml down
    ;;

  docker:build)
    log "Building ingestion Docker image..."
    docker build -f docker/Dockerfile.ingestion -t aether-ingestion:latest .
    ok "Image built: aether-ingestion:latest"
    ;;

  smoke)
    log "Smoke test: sending batch to localhost:3001..."
    curl -s -X POST http://localhost:3001/v1/batch \
      -H "Content-Type: application/json" \
      -H "Authorization: Bearer ak_dev_aether_test_key_12345678" \
      -d '{
        "batch": [
          {
            "id": "evt_smoke_001",
            "type": "track",
            "timestamp": "'"$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"'",
            "sessionId": "sess_smoke",
            "anonymousId": "anon_smoke",
            "event": "smoke_test",
            "properties": { "source": "dev_cli" },
            "context": { "library": { "name": "@aether/sdk", "version": "4.0.0" } }
          }
        ],
        "sentAt": "'"$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"'"
      }' | jq .
    ;;

  health)
    curl -s http://localhost:3001/health | jq .
    ;;

  metrics)
    curl -s http://localhost:3001/metrics | jq .
    ;;

  status)
    curl -s http://localhost:3001/status | jq .
    ;;

  clean)
    log "Cleaning build artifacts..."
    rm -rf packages/*/dist services/*/dist node_modules/.cache
    ok "Clean"
    ;;

  help|*)
    echo "Aether Backend CLI"
    echo ""
    echo "Usage: ./scripts/dev.sh <command>"
    echo ""
    echo "Commands:"
    echo "  dev              Start ingestion in dev mode (hot reload)"
    echo "  test             Run unit tests"
    echo "  test:watch       Run tests in watch mode"
    echo "  test:integration Run integration tests"
    echo "  build            Compile TypeScript"
    echo "  lint             Run ESLint"
    echo "  typecheck        Check types"
    echo "  docker:up        Start full Docker stack"
    echo "  docker:down      Stop Docker stack"
    echo "  docker:build     Build ingestion Docker image"
    echo "  smoke            Send a smoke test batch"
    echo "  health           Check health endpoint"
    echo "  metrics          Check metrics endpoint"
    echo "  status           Check status endpoint"
    echo "  clean            Remove build artifacts"
    ;;
esac
