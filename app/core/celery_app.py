# app/core/celery_app.py
"""
Celery app — démarre toujours, même sans broker.

- Avec broker (CELERY_BROKER_URL ou REDIS_URL) : tâches enqueue → workers
- Sans broker : mode `task_always_eager` → exécution sync inline, comportement
  identique à l'app pré-S2. Utile en dev / déploiement minimaliste sans Redis.

Workers : `celery -A app.core.celery_app:celery_app worker -l info -c 4`
"""
from __future__ import annotations

from celery import Celery

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("simandou.celery")


def _build() -> Celery:
    broker = settings.effective_celery_broker
    backend = settings.effective_celery_backend

    app = Celery(
        "simandou_screening",
        broker=broker or "memory://",
        backend=backend or "cache+memory://",
        include=["app.tasks.pdf_export"],
    )

    app.conf.update(
        task_always_eager=settings.celery_eager,
        task_eager_propagates=True,
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_time_limit=settings.CELERY_TASK_TIME_LIMIT_SECONDS,
        task_soft_time_limit=settings.CELERY_TASK_SOFT_LIMIT_SECONDS,
        broker_connection_retry_on_startup=True,
        # Sérialisation efficace + résultats compressés (les blobs PDF peuvent être lourds)
        result_compression="gzip",
        # Préfère un acknowledgment tardif : si le worker crash en plein job, retry
        task_acks_late=True,
        worker_prefetch_multiplier=2,
    )

    logger.info(
        "celery_initialised",
        extra={
            "eager": settings.celery_eager,
            "broker_set": bool(broker),
            "backend_set": bool(backend),
        },
    )
    return app


celery_app = _build()
