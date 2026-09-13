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

# Copy application code
# Build context is the repository root, so paths are relative to repo root.
# The aether-backend/ tree provides main.py and the shared/ package used by
# imports of the form `from shared.X import ...`. The top-level security/
# package is consumed via `from security.X import ...`.
COPY ["services/backend/config/", "./config/"]
COPY ["services/backend/dependencies/", "./dependencies/"]
COPY ["services/backend/middleware/", "./middleware/"]
COPY ["services/backend/repositories/", "./repositories/"]
COPY ["services/backend/services/", "./services/"]
COPY ["services/backend/shared/", "./shared/"]
COPY ["services/backend/main.py", "./main.py"]
COPY ["services/backend/alembic/", "./alembic/"]
COPY ["services/backend/alembic.ini", "./alembic.ini"]
COPY security/ ./security/

# ML serving source tree (required when ML_SERVING_INLINE=true, E2).
# Routes are lazy-loaded per request; the image boots without them.
COPY ["services/ml/common/", "./common/"]
COPY ["services/ml/serving/", "./serving/"]

ENV ML_SERVING_INLINE=false

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -sf http://localhost:8000/v1/health || exit 1

# Entrypoint: parses DATABASE_URL_SECRET JSON (RDS manage_master_user_password)
# into DATABASE_URL before uvicorn starts. No-op when DATABASE_URL is already set.
COPY ["services/backend/entrypoint.sh", "/entrypoint.sh"]
RUN chmod +x /entrypoint.sh

USER appuser

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
