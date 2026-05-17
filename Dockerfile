# syntax=docker/dockerfile:1.7
# ============================================================================
# Simandou Screening — Dockerfile multi-stage
#
# Stages:
#   1. base      : python:3.12-slim + deps système
#   2. builder   : compile les wheels (gcc + libpq-dev)
#   3. runtime   : image finale, slim, sans toolchain
#
# Build:
#   docker build -t simandou-screening:latest .
#
# Run API:
#   docker run --env-file .env -p 8000:8000 simandou-screening:latest
#
# Run worker:
#   docker run --env-file .env simandou-screening:latest worker
# ============================================================================

ARG PYTHON_VERSION=3.12.8

# ----------------------------------------------------------------------------
# Stage 1 — base
# ----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONFAULTHANDLER=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

# ----------------------------------------------------------------------------
# Stage 2 — builder (compile wheels)
# ----------------------------------------------------------------------------
FROM base AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt ./
RUN python -m pip install --upgrade pip wheel \
 && pip wheel --wheel-dir /wheels -r requirements.txt

# ----------------------------------------------------------------------------
# Stage 3 — runtime (image finale)
# ----------------------------------------------------------------------------
FROM base AS runtime

# User non-root
RUN groupadd -r app --gid 1000 \
 && useradd -r -g app --uid 1000 --create-home --home-dir /home/app app

WORKDIR /app

# Install depuis les wheels précompilés (rapide, no toolchain)
COPY --from=builder /wheels /wheels
COPY requirements.txt ./
RUN pip install --no-index --find-links /wheels -r requirements.txt \
 && rm -rf /wheels

# Copie du code
COPY --chown=app:app app ./app
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./

# Storage local par défaut (override en prod via STORAGE_BACKEND=S3)
RUN mkdir -p /app/storage /app/uploads && chown -R app:app /app/storage /app/uploads

USER app

ENV PORT=8000

EXPOSE 8000

# tini = PID 1 propre (signal handling). entrypoint.sh route entre web/worker/migrate.
COPY --chown=app:app docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/docker-entrypoint.sh"]
CMD ["web"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${PORT}/readyz" || exit 1
