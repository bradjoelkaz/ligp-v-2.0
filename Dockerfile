# =============================================================================
# IIGP v2.0 — API / Admin / Observability image (Phase 8)
# Slim runtime: installs the lightweight requirements-dev set (no heavy ML
# stack). Layer-specific extras are added in downstream images.
# =============================================================================
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_ENV=production \
    LOG_LEVEL=INFO

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements-dev.txt ./
RUN python -m pip install --upgrade pip && \
    pip install -r requirements-dev.txt

# Copy application source.
COPY . .

EXPOSE 8000

# Lightweight liveness probe against the /health route.
HEALTHCHECK --interval=30s --timeout=4s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)" || exit 1

# Factory pattern: create_app() is the ASGI app factory.
CMD ["uvicorn", "api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
