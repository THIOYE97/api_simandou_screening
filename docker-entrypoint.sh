#!/usr/bin/env bash
# ============================================================================
# Docker entrypoint — route entre les rôles selon le 1er argument.
#   web      : gunicorn + uvicorn worker (API)
#   worker   : celery worker
#   beat     : celery beat (scheduler, pour les tâches périodiques)
#   migrate  : alembic upgrade head et exit
#   shell    : bash interactif (debug)
#   <other>  : exec direct (ex: pytest, python -c ..., etc.)
# ============================================================================
set -euo pipefail

ROLE="${1:-web}"
shift || true

PORT="${PORT:-8000}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-4}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-60}"
CELERY_CONCURRENCY="${CELERY_CONCURRENCY:-4}"
CELERY_LOG_LEVEL="${CELERY_LOG_LEVEL:-info}"

case "$ROLE" in
  web)
    echo "[entrypoint] starting web (gunicorn workers=${GUNICORN_WORKERS})"
    exec gunicorn app.main:app \
      --bind "0.0.0.0:${PORT}" \
      --workers "${GUNICORN_WORKERS}" \
      --worker-class uvicorn.workers.UvicornWorker \
      --timeout "${GUNICORN_TIMEOUT}" \
      --graceful-timeout 30 \
      --keep-alive 5 \
      --max-requests 1000 \
      --max-requests-jitter 100 \
      --access-logfile - \
      --error-logfile -
    ;;

  worker)
    echo "[entrypoint] starting celery worker (concurrency=${CELERY_CONCURRENCY})"
    exec celery -A app.core.celery_app:celery_app worker \
      --loglevel="${CELERY_LOG_LEVEL}" \
      --concurrency="${CELERY_CONCURRENCY}"
    ;;

  beat)
    echo "[entrypoint] starting celery beat"
    exec celery -A app.core.celery_app:celery_app beat \
      --loglevel="${CELERY_LOG_LEVEL}"
    ;;

  migrate)
    echo "[entrypoint] running alembic upgrade head"
    exec alembic upgrade head
    ;;

  seed)
    echo "[entrypoint] seeding referentiel + users (conformité / analyste)"
    exec python -m app.scripts.seed_users
    ;;

  shell)
    exec bash
    ;;

  *)
    echo "[entrypoint] exec custom command: $ROLE $*"
    exec "$ROLE" "$@"
    ;;
esac
