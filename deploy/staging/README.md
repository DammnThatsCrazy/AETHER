# Aether Staging Deployment

## Quick Start

```bash
cd deploy/staging
./bootstrap.sh
```

This single command:
1. Generates production secrets (JWT, Fernet, passwords)
2. Starts PostgreSQL, Redis, Kafka, Zookeeper
3. Waits for all infrastructure health checks
4. Starts the backend API and ML serving
5. Validates service health
6. Creates the first admin API key
7. Runs endpoint smoke tests

## Prerequisites

- Docker and Docker Compose installed
- Ports available: 8000, 8080, 5432, 6379, 9092, 9090
- Python 3.9+ (for secret generation)

## Services

| Service | Port | Purpose |
|---------|------|---------|
| Backend API | 8000 | Main application server |
| ML Serving | 8080 | ML model inference |
| PostgreSQL | 5432 | Primary database |
| Redis | 6379 | Cache + rate limiting + auth |
| Kafka | 9092 | Event bus |
| Prometheus | 9090 | Metrics collection |

## Validation

After bootstrap:

```bash
# Health check (should show all dependencies as "ok")
curl http://localhost:8000/v1/health

# Prometheus metrics
curl http://localhost:8000/v1/metrics

# API docs
open http://localhost:8000/docs
```

## Custom Secrets

To use specific secrets instead of auto-generated ones:

```bash
export JWT_SECRET="your-secret-here"
export BYOK_ENCRYPTION_KEY="your-fernet-key-here"
export POSTGRES_PASSWORD="your-db-password"
export REDIS_PASSWORD="your-redis-password"
./bootstrap.sh
```

## Stopping

```bash
docker compose -f docker-compose.staging.yml down        # Stop services
docker compose -f docker-compose.staging.yml down -v     # Stop + delete data
```

## Logs

```bash
docker compose -f docker-compose.staging.yml logs -f           # All services
docker compose -f docker-compose.staging.yml logs -f backend   # Backend only
```

## ML Model Training

The staging ML serving starts without trained models. To train:

```bash
pip install -e ".[ml]"
cd "ML Models/aether-ml"
python -m training.pipelines.train --model all --output /tmp/aether-models
```

Then copy artifacts to the ML serving container or mount the volume.

## Known Limitations

- ML serving loads stub models (local-quality predictions) unless trained artifacts are provided
- Rewards fraud scoring uses heuristic fallback unless ML serving has trained bot detection model
- Neptune graph is not included (in-memory graph in staging compose)
