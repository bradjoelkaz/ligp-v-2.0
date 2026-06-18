# =============================================================================
# IIGP v2.0 — Multi-stage Dockerfile
# Stage 1 builder: compile wheels for the slim production deps
# Stage 2 runtime: minimal image, non-root user, healthcheck
#
# NOTE: we install requirements-prod.txt (API/worker runtime only), not the
# full requirements.txt — the heavy ML/data libs are not needed to serve the
# API and would bloat the image / slow the build. The pipeline jobs that need
# them run in a separate environment.
# =============================================================================

# -- Stage 1: builder ---------------------------------------------------------
FROM python:3.11-slim AS builder
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt .
RUN pip install --upgrade pip \
    && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements-prod.txt

# -- Stage 2: runtime ---------------------------------------------------------
FROM python:3.11-slim AS runtime
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels /wheels/*.whl \
    && rm -rf /wheels

# Source copy (data/, .env, tests/ excluded via .dockerignore)
COPY . .
RUN rm -rf data/ .env tests/ .git/

# Non-root user (security)
RUN useradd -m -u 1000 iigp && chown -R iigp:iigp /app
USER iigp

EXPOSE 8000

# Healthcheck every 30s
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "api.main:app", \
     "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
