from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.logging import get_logger

router = APIRouter()
logger = get_logger("simandou.health")


@router.get("/health")
def health():
    """Liveness probe — toujours 200 si le process tourne."""
    return {"status": "ok", "env": settings.ENVIRONMENT}


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


@router.get("/readyz")
def readyz():
    """Readiness probe — vérifie les dépendances critiques."""
    checks: dict[str, str] = {}
    ok = True

    # DB
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            checks["db"] = "ok"
        finally:
            db.close()
    except Exception as e:
        ok = False
        checks["db"] = f"down: {type(e).__name__}"
        logger.exception("readyz_db_failed")

    # Anthropic key présent ?
    checks["anthropic"] = "ok" if settings.ANTHROPIC_API_KEY else "missing"

    payload = {"status": "ok" if ok else "degraded", "checks": checks}
    return JSONResponse(status_code=200 if ok else 503, content=payload)
