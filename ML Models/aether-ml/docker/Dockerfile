# =============================================================================
# AETHER ML — Multi-stage Dockerfile
# Stages: base, training, serving, features, monitoring
#
# Build examples:
#   docker build --target serving -t aether-ml-serving:latest .
#   docker build --target training -t aether-ml-training:latest .
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1 — Base image with system deps and Python packages
# ---------------------------------------------------------------------------
FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && \
    pip install -e "."

# ---------------------------------------------------------------------------
# Stage 2 — Training image (heavy: full source tree + GPU support)
# ---------------------------------------------------------------------------
FROM base AS training

COPY . .

ENV AETHER_ENV=training

# SageMaker-compatible directory structure
RUN mkdir -p /opt/ml/model /opt/ml/input /opt/ml/output

ENTRYPOINT ["python", "-m", "training.pipelines.train"]

# ---------------------------------------------------------------------------
# Stage 3 — Serving image (lighter: only inference code + models)
# ---------------------------------------------------------------------------
FROM base AS serving

COPY common/ common/
COPY edge/ edge/
COPY server/ server/
COPY serving/ serving/
COPY export/ export/

ENV AETHER_ENV=serving

# Model artifacts mounted or copied at deploy time
RUN mkdir -p /opt/ml/models

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["python", "-m", "serving.src.api"]

# ---------------------------------------------------------------------------
# Stage 4 — Feature pipeline image (batch feature computation)
# ---------------------------------------------------------------------------
FROM base AS features

COPY common/ common/
COPY features/ features/

ENV AETHER_ENV=features

ENTRYPOINT ["python", "-m", "features.pipeline"]

# ---------------------------------------------------------------------------
# Stage 5 — Monitoring image
# ---------------------------------------------------------------------------
FROM base AS monitoring

COPY common/ common/
COPY monitoring/ monitoring/

ENV AETHER_ENV=monitoring

ENTRYPOINT ["python", "-m", "monitoring.monitor"]
