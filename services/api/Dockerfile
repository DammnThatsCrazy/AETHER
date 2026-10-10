FROM python:3.11-slim AS builder

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies (full production stack including noesis/anthropic).
# alembic is required at runtime for the /v1/ready migrations-head check and
# the RUN_MIGRATIONS=1 entrypoint opt-in.
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[all,noesis]" "alembic>=1.13" "croniter>=2" tzdata

# ---------------------------------------------------------------------------
# Optional: install onnxruntime for ML_SERVING_INLINE=true.
# This stage is shared by both the standard backend image and the
# consolidated aether-app image (E2).  onnxruntime adds ~180 MB but
# the same image can run with or without ML_SERVING_INLINE; the runtime
# cost is zero when the env var is false.
# ---------------------------------------------------------------------------
RUN pip install --no-cache-dir "onnxruntime>=1.17.0" "onnx>=1.15.0"

# --- Production stage ---
FROM python:3.11-slim

WORKDIR /app

# Install only runtime system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code while preserving the repository-relative backend root.
# Several runtime authorities resolve canonical config/contracts by walking from
# __file__; flattening services/api into /app silently made those readers
# point at /nonexistent (or made route_registry.yaml disappear entirely). The
# backend root is the first PYTHONPATH entry below, so `main`, `config`,
# `dependencies`, `middleware`, `repositories`, `shared` and the domain packages
# (tenancy, ingestion, identity, ...) keep their import names without losing the source-tree depth.
COPY ["services/api/config/", "./services/api/config/"]
COPY ["services/api/dependencies/", "./services/api/dependencies/"]
COPY ["services/api/middleware/", "./services/api/middleware/"]
COPY ["services/api/repositories/", "./services/api/repositories/"]
COPY ["services/api/tenancy/", "./services/api/tenancy/"]
COPY ["services/api/ingestion/", "./services/api/ingestion/"]
COPY ["services/api/identity/", "./services/api/identity/"]
COPY ["services/api/graph/", "./services/api/graph/"]
COPY ["services/api/journeys/", "./services/api/journeys/"]
COPY ["services/api/intelligence/", "./services/api/intelligence/"]
COPY ["services/api/value/", "./services/api/value/"]
COPY ["services/api/actions/", "./services/api/actions/"]
COPY ["services/api/governance/", "./services/api/governance/"]
COPY ["services/api/workers/", "./services/api/workers/"]
COPY ["services/api/connectors/", "./services/api/connectors/"]
COPY ["services/api/replay/", "./services/api/replay/"]
COPY ["services/api/billing/", "./services/api/billing/"]
COPY ["services/api/shared/", "./services/api/shared/"]
COPY ["services/api/main.py", "./services/api/main.py"]
COPY ["services/api/alembic/", "./services/api/alembic/"]
COPY ["services/api/alembic.ini", "./services/api/alembic.ini"]

# These are runtime authorities, not build-only documentation. Keep the
# profile/route registries and the contract JSON that the consent, graph,
# projection, and capability readers load lazily after startup.
COPY ["config/", "./config/"]
COPY ["packages/shared/contracts/", "./packages/shared/contracts/"]
COPY ["packages/contracts/delivery/", "./packages/contracts/delivery/"]
COPY ["pyproject.toml", "./pyproject.toml"]

# Inline ML source trees (required when ML_SERVING_INLINE=true, E2). The
# serving router is mounted during backend startup; its model and monitoring
# authorities are lazy in places, but must still be present in the immutable
# image so readiness and inference never degrade because a source subtree was
# omitted from the build context.
COPY ["services/ml/common/", "./common/"]
COPY ["services/ml/edge/", "./edge/"]
COPY ["services/ml/monitoring/", "./monitoring/"]
COPY ["services/ml/server/", "./server/"]
COPY ["services/ml/serving/", "./serving/"]

ENV ML_SERVING_INLINE=false
ENV PYTHONPATH=/app/services/api:/app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -sf http://localhost:8000/v1/health || exit 1

# Entrypoint: parses DATABASE_URL_SECRET JSON (RDS manage_master_user_password)
# into DATABASE_URL before uvicorn starts. No-op when DATABASE_URL is already set.
COPY ["services/api/entrypoint.sh", "/entrypoint.sh"]
RUN chmod +x /entrypoint.sh

WORKDIR /app/services/api

USER appuser

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
