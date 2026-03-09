# app/api/routes/documents.py
from __future__ import annotations

from uuid import UUID
from pathlib import Path
from typing import Dict, Any
from sqlalchemy import text
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session 
from fastapi import BackgroundTasks 
from app.api.deps.auth import get_current_user
from app.api.deps.db import get_db_rls as get_db

from app.api.deps.db import get_db_rls as get_db

from app.models.document import Document  # ✅ plus de StorageBackend ici

from app.services.documents_service import (
    save_document,
    list_documents,
    extract_document_fields_local,
    save_document_standalone,
    apply_ocr_prefill_to_case,
    get_document,
    UPLOAD_ROOT,
)

router = APIRouter(prefix="/documents", tags=["documents"])


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def _user_id(user: Any):
    if user is None:
        return None
    if isinstance(user, dict):
        return user.get("id") or user.get("user_id") or user.get("sub")
    return getattr(user, "id", None) or getattr(user, "user_id", None)


def _build_urls(doc_id: UUID) -> Dict[str, str]:
    return {
        "preview_url": f"/documents/{doc_id}/file",
        "download_url": f"/documents/{doc_id}/file?dl=1",
    }

def _guess_mime(doc: Document) -> str:
    if getattr(doc, "mime_type", None):
        return str(doc.mime_type)
    name = (getattr(doc, "original_filename", None) or getattr(doc, "object_key", None) or "").lower()
    if name.endswith(".pdf"):
        return "application/pdf"
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".jpg") or name.endswith(".jpeg"):
        return "image/jpeg"
    if name.endswith(".webp"):
        return "image/webp"
    return "application/octet-stream"

def _resolve_local_file_path(doc: Document) -> Path:
    fp = getattr(doc, "file_path", None)
    if fp:
        p = Path(str(fp))
        if p.exists() and p.is_file():
            return p

    object_key = getattr(doc, "object_key", None)
    if object_key:
        p2 = Path(UPLOAD_ROOT) / str(object_key)
        if p2.exists() and p2.is_file():
            return p2

    raise HTTPException(status_code=404, detail="File not found on disk")

def _is_local_backend(doc: Document) -> bool:
    # doc.storage_backend peut être un Enum Python, ou une string DB
    val = getattr(doc, "storage_backend", None)
    if val is None:
        return False
    s = str(val)
    return s.endswith("LOCAL") or s == "LOCAL"

# -----------------------------------------------------------------------------
# Upload
# -----------------------------------------------------------------------------

@router.post("/cases/{case_id}/upload")
async def upload_document(
    case_id: UUID,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    doc = await save_document(db, case_id, doc_type, file, uploaded_by=_user_id(user))
    return {
        "document_id": str(doc.id),
        "case_id": str(doc.case_id) if doc.case_id else None,
        "ocr_status": str(doc.ocr_status),
        "object_key": doc.object_key,       
        **_build_urls(doc.id),
    }

@router.post("/upload")
async def upload_document_standalone(
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    try:
        doc = await save_document_standalone(
            db=db,
            doc_type=doc_type,
            file=file,
            uploaded_by=_user_id(user),
        )
    except HTTPException:
        raise
    except Exception as e:
        # remonte le message au lieu d'un 500 opaque
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "document_id": str(doc.id),
        "case_id": str(doc.case_id) if getattr(doc, "case_id", None) else None,
        "ocr_status": str(doc.ocr_status),
        "object_key": doc.object_key,
        **_build_urls(doc.id),
    }


# -----------------------------------------------------------------------------
# List documents for a case
# -----------------------------------------------------------------------------

@router.get("/cases/{case_id}")
def get_case_documents(case_id: UUID, db: Session = Depends(get_db),user=Depends(get_current_user),):
    docs = list_documents(db, case_id)
    out = []
    for d in docs:
        out.append( 
            {
                "id": str(d.id),
                "case_id": str(d.case_id) if getattr(d, "case_id", None) else None,
                "doc_type": getattr(d, "doc_type", None),
                "uploaded_at": getattr(d, "uploaded_at", None),
                "ocr_status": str(getattr(d, "ocr_status", "")) if getattr(d, "ocr_status", None) else None,
                "ocr_confidence": float(d.ocr_confidence) if getattr(d, "ocr_confidence", None) is not None else None,
                "original_filename": getattr(d, "original_filename", None),
                "mime_type": getattr(d, "mime_type", None),
                "size_bytes": getattr(d, "size_bytes", None),
                "sha256": getattr(d, "sha256", None),
                "storage_backend": str(getattr(d, "storage_backend", "")) if getattr(d, "storage_backend", None) else None,
                "object_key": getattr(d, "object_key", None),
                "file_path": getattr(d, "file_path", None),
                "extracted_fields": getattr(d, "extracted_fields", None),
                **_build_urls(d.id),
            }
        )
    return out


# -----------------------------------------------------------------------------
# Extract OCR + prefill
# -----------------------------------------------------------------------------

@router.post("/{doc_id}/extract")
def extract_document(
    doc_id: UUID,
    background_tasks: BackgroundTasks,   # ← ajouter
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    # Vérifier que le doc existe avant de répondre
    from app.services.documents_service import get_document
    doc = get_document(db, doc_id)  # lève 404 si absent

    # ✅ Répondre IMMÉDIATEMENT, OCR tourne en arrière-plan
    background_tasks.add_task(_run_ocr_background, doc_id)

    return {
        "doc_id": str(doc.id),
        "case_id": str(doc.case_id) if doc.case_id else None,
        "ocr_status": "PENDING",
        "message": "OCR en cours, vérifiez le statut dans quelques secondes.",
        **_build_urls(doc.id),
    }


def _run_ocr_background(doc_id: UUID):
    """Tourne hors du cycle request/response — pas de timeout Gunicorn."""
    from app.core.db import SessionLocal
    db = SessionLocal()
    try:
        doc = extract_document_fields_local(db, doc_id)
        prefill = apply_ocr_prefill_to_case(
            db=db,
            case_id=doc.case_id,
            extracted_fields=doc.extracted_fields or {},
            overwrite=False,
        )
        print(f"[ocr background] ✅ doc={doc_id} confidence={doc.ocr_confidence} prefill={prefill}")
    except Exception as e:
        print(f"[ocr background] ❌ doc={doc_id} error={e}")
    finally:
        db.close()
# -----------------------------------------------------------------------------
# Serve file (preview/download)
# -----------------------------------------------------------------------------

@router.get("/{doc_id}/file")
def get_document_file(
    doc_id: UUID,
    dl: int = Query(default=0, description="dl=1 => force download"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    doc = get_document(db, doc_id)

    if not _is_local_backend(doc):
        raise HTTPException(status_code=501, detail="Only LOCAL storage_backend is supported for file serving")

    path = _resolve_local_file_path(doc)
    blob = path.read_bytes()

    mime = _guess_mime(doc)
    filename = (getattr(doc, "original_filename", None) or path.name or str(doc_id)).replace('"', "")

    disp = "attachment" if int(dl or 0) == 1 else "inline"
    headers = {"Content-Disposition": f'{disp}; filename="{filename}"'}

    return StreamingResponse(iter([blob]), media_type=mime, headers=headers)
