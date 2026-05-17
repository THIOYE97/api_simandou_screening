# app/tasks/pdf_export.py
"""
Tâche Celery : génération asynchrone du PDF de screening.

- En mode eager (pas de broker) : exécution inline, comportement identique à
  l'appel sync direct.
- En mode broker actif : worker pioche le job, écrit le PDF dans le storage
  (local/S3), met à jour le résultat avec l'object_key. L'API renvoie un job_id ;
  le client polle `/screening/jobs/{id}`.

Note : Celery démarre sa propre session DB (le worker n'a pas le contexte RLS
de la requête HTTP). On repose donc `app.tenant_id` au début de la tâche.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from app.core.celery_app import celery_app
from app.core.db import SessionLocal, set_tenant_context
from app.core.logging import get_logger
from app.services.export_pdf_service import build_screening_pdf
from app.services.storage import get_storage

logger = get_logger("simandou.tasks.pdf")


PDF_OBJECT_KEY_TEMPLATE = "exports/screenings/{tenant_id}/screening-{request_id}.pdf"


def _pdf_object_key(tenant_id: str, request_id: str) -> str:
    return PDF_OBJECT_KEY_TEMPLATE.format(tenant_id=tenant_id, request_id=request_id)


@celery_app.task(
    name="simandou.pdf.export_screening",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=2,
)
def export_screening_pdf_task(self, request_id: str, tenant_id: str) -> dict[str, Any]:
    """
    Génère le PDF et le stocke. Retourne le metadata :
      {
        "request_id": "...",
        "tenant_id": "...",
        "object_key": "exports/screenings/.../screening-xxx.pdf",
        "size_bytes": 123456,
        "storage": "LOCAL" | "S3",
      }
    """
    logger.info(
        "pdf_export_started",
        extra={"request_id": request_id, "tenant_id": tenant_id, "task_id": self.request.id},
    )

    db = SessionLocal()
    try:
        # Workers Celery démarrent hors contexte HTTP — on repose tenant_id pour RLS.
        # NB: la session est sur le rôle applicatif par défaut, pas auth_bypass_rls.
        db.execute(text("RESET ROLE"))
        set_tenant_context(db, tenant_id)

        pdf_bytes = build_screening_pdf(db, str(request_id))

        if not pdf_bytes:
            raise RuntimeError("build_screening_pdf returned empty bytes")

        storage = get_storage()
        object_key = _pdf_object_key(tenant_id, request_id)
        meta = storage.save(object_key, pdf_bytes, content_type="application/pdf")

        from app.core.config import settings  # local import (évite cycle au boot)

        result = {
            "request_id": str(request_id),
            "tenant_id": str(tenant_id),
            "object_key": object_key,
            "size_bytes": meta.get("size_bytes", len(pdf_bytes)),
            "storage": settings.STORAGE_BACKEND,
        }
        logger.info("pdf_export_done", extra=result)
        return result

    finally:
        try:
            db.execute(text("SELECT set_config('app.tenant_id', '', false)"))
            db.execute(text("RESET ROLE"))
        except Exception:
            pass
        db.close()
