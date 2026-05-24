# =============================================================================
# Aether ML — Multi-stage Dockerfile
# Stages: base, training, serving, features, monitoring
#
# Build examples:
#   docker build --target serving -t aether-ml-serving:latest .
#   docker build --target training -t aether-ml-training:latest .
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1 — Base image: system deps and an installable package skeleton.
# Optional extras are installed per stage below so each image only carries
# what it actually needs.
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
RUN pip install --upgrade pip && pip install -e "."

# ---------------------------------------------------------------------------
# Stage 2 — Training image (heavy: full source tree + GPU-capable ML stack)
# ---------------------------------------------------------------------------
FROM base AS training

RUN pip install -e ".[training]"

COPY . .

ENV AETHER_ENV=training

RUN mkdir -p /opt/ml/model /opt/ml/input /opt/ml/output

ENTRYPOINT ["python", "-m", "training.pipelines.train"]

# ---------------------------------------------------------------------------
# Stage 3 — Serving image (slim target: ONNX runtime only).
#
# Today this still installs the [training] extras because the native model
# loaders in server/*.py import torch / xgboost / tensorflow. Once
# server-side ONNX exports land (M6, M7, M9 are tabular and trivial; M4,
# M5, M8-AE follow), flip the extras to just `.[serving]` and the image
# drops from ~4.5 GB to ~600 MB with no API contract change.
# ---------------------------------------------------------------------------
FROM base AS serving

RUN pip install -e ".[serving,training]"

COPY common/ common/
COPY edge/ edge/
COPY server/ server/
COPY serving/ serving/
COPY export/ export/

ENV AETHER_ENV=serving

RUN mkdir -p /opt/ml/models

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["python", "-m", "serving.src.api"]

# ---------------------------------------------------------------------------
# Stage 4 — Feature pipeline image (batch feature computation)
# ---------------------------------------------------------------------------
FROM base AS features

RUN pip install -e ".[training]"

COPY common/ common/
COPY features/ features/

ENV AETHER_ENV=features

ENTRYPOINT ["python", "-m", "features.pipeline"]

# ---------------------------------------------------------------------------
# Stage 5 — Monitoring image
# ---------------------------------------------------------------------------
FROM base AS monitoring

RUN pip install -e ".[serving]"

COPY common/ common/
COPY monitoring/ monitoring/

ENV AETHER_ENV=monitoring

ENTRYPOINT ["python", "-m", "monitoring.monitor"]
