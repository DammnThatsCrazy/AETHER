# Aether LEGACY local stack (quarantined)

**SUPERSEDED — not the canonical staging profile.**

This directory was previously named `deploy/staging` and presented a
"staging-equivalent" docker-compose stack provisioning PostgreSQL, **Redis**,
**Kafka + Zookeeper**, and **Prometheus**. The canonical staging profile
(`config/deployment_profiles.yaml`) forbids all three of Redis, Kafka, and
self-managed Prometheus/Grafana (`forbidden_resources`), so this stack
contradicts the profile it claimed to represent. It was validated by no CI
gate and is not referenced by any Makefile target.

It is retained **only as a local development harness** for exercising the
Redis + Kafka + Prometheus backends a machine may not otherwise have. It is
quarantined under `deploy/legacy-staging/` so it can never be mistaken for the
canonical staging deployment.

- **Canonical staging**: Terraform root
  `AWS Deployment/aether-aws/terraform/profiles/staging.tfvars`, exercised by
  `.github/workflows/staging-lifecycle.yml` and `terraform-promote.yml`.
- **This legacy stack**: local-only Redis/Kafka/Prometheus dev harness.

`scripts/release/check_delivery_compose_parity.py` enforces that this LEGACY
marker is present and that no compose file outside this directory claims the
staging profile.

## Quick Start (legacy local harness)

```bash
cd deploy/legacy-staging
./bootstrap.sh
```

This single command:
1. Generates local secrets (JWT, Fernet, passwords)
2. Starts PostgreSQL, Redis, Kafka, Zookeeper
3. Waits for all infrastructure health checks
4. Starts the backend API and ML serving
5. Validates service health
6. Creates the first admin API key
7. Runs endpoint smoke tests

## Services

| Service | Port | Purpose |
|---------|------|---------|
| Backend API | 8000 | Main application server |
| ML Serving | 8080 | ML model inference |
| PostgreSQL | 5432 | Primary database |
| Redis | 6379 | Cache + rate limiting + auth |
| Kafka | 9092 | Event bus |
| Prometheus | 9090 | Metrics collection |

## Stopping

```bash
docker compose -f docker-compose.staging.yml down        # Stop services
docker compose -f docker-compose.staging.yml down -v     # Stop + delete data
```

## Known Limitations

- ML serving loads stub models (local-quality predictions) unless trained artifacts are provided
- Rewards fraud scoring uses heuristic fallback unless ML serving has trained bot detection model
- Neptune graph is not included (in-memory graph in this legacy compose)
- **Not a staging deployment.** The canonical staging profile forbids the
  Redis/Kafka/Prometheus resources this stack provisions; use it only for
  local development.
