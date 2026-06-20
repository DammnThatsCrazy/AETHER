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

RUN mkdir -p /opt/ml/model /opt/ml/input /opt/ml/output && \
    addgroup --system --gid 1001 aether && \
    adduser --system --uid 1001 --ingroup aether --no-create-home aether && \
    chown -R aether:aether /opt/ml

USER aether

ENTRYPOINT ["python", "-m", "training.pipelines.train"]

# ---------------------------------------------------------------------------
# Stage 3 — Serving image (slim: ONNX runtime only, ~600 MB).
#
# M6/M7 churn and LTV are served via OnnxChurnModel / OnnxLTVModel when an
# *.onnx artifact is present (see serving/src/onnx_models.py); the native
# XGBoost loaders are only reached as a fallback in the training image.
# M4/M5/M8 (identity, journey, anomaly-AE) are on SageMaker Serverless.
# M9 (attribution) is algorithmic — only needs numpy/pandas (base deps).
# ---------------------------------------------------------------------------
FROM base AS serving

RUN pip install -e ".[serving]"

COPY common/ common/
COPY edge/ edge/
COPY server/ server/
COPY serving/ serving/
COPY export/ export/

ENV AETHER_ENV=serving

RUN mkdir -p /opt/ml/models && \
    addgroup --system --gid 1001 aether && \
    adduser --system --uid 1001 --ingroup aether --no-create-home aether && \
    chown -R aether:aether /opt/ml

USER aether

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

RUN addgroup --system --gid 1001 aether && \
    adduser --system --uid 1001 --ingroup aether --no-create-home aether

USER aether

ENTRYPOINT ["python", "-m", "features.pipeline"]

# ---------------------------------------------------------------------------
# Stage 5 — Monitoring image
# ---------------------------------------------------------------------------
FROM base AS monitoring

RUN pip install -e ".[serving]"

COPY common/ common/
COPY monitoring/ monitoring/

ENV AETHER_ENV=monitoring

RUN addgroup --system --gid 1001 aether && \
    adduser --system --uid 1001 --ingroup aether --no-create-home aether

USER aether

ENTRYPOINT ["python", "-m", "monitoring.monitor"]
