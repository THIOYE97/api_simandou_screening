# app/services/documents_service.py
from __future__ import annotations

import hashlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.case import Case
from app.models.document import Document, OCRStatus, StorageBackend
from app.services.local_ocr_service import run_local_ocr
from app.services.storage import get_storage

# ─────────────────────────────────────────────
# Storage root
# ─────────────────────────────────────────────

APP_DIR     = Path(__file__).resolve().parents[1]   # .../app
PROJECT_DIR = APP_DIR.parent                        # .../<repo>
UPLOAD_ROOT = (PROJECT_DIR / "uploads").resolve()
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

print("[documents_service] UPLOAD_ROOT =", UPLOAD_ROOT, "| cwd =", Path.cwd())


# ─────────────────────────────────────────────
# Tenant helpers
# ─────────────────────────────────────────────

def _current_tenant_uuid(db: Session) -> Optional[UUID]:
    val = db.execute(
        text("SELECT nullif(current_setting('app.tenant_id', true), '')")
    ).scalar()
    return UUID(str(val)) if val else None


def _require_tenant_uuid(db: Session) -> UUID:
    tid = _current_tenant_uuid(db)
    if not tid:
        raise HTTPException(status_code=400, detail="tenant context missing (app.tenant_id not set)")
    return tid


# ─────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    name = (name or "upload.bin").replace("/", "_").replace("\\", "_").strip()
    return (name or "upload.bin")[:180]


def _local_path(object_key: str) -> Path:
    return (UPLOAD_ROOT / object_key).resolve()


def _ocr_fields_to_prefill(fields: Dict[str, Any]) -> Dict[str, Any]:
    prefill: Dict[str, Any] = {}
    if fields.get("last_name"):
        prefill["nom"] = fields["last_name"]
    if fields.get("first_name"):
        prefill["prenom"] = fields["first_name"]
    if fields.get("date_of_birth"):
        prefill["dob"] = fields["date_of_birth"]
    if fields.get("document_number"):
        prefill["card_number"] = fields["document_number"]
    return prefill


# ─────────────────────────────────────────────
# Case prefill
# ─────────────────────────────────────────────

def apply_ocr_prefill_to_case(
    db: Session,
    case_id: Any,
    extracted_fields: Dict[str, Any],
    overwrite: bool = False,
) -> Dict[str, Any]:
    if not case_id:
        return {}

    prefill = _ocr_fields_to_prefill(extracted_fields)
    case    = db.query(Case).filter(Case.id == case_id).one_or_none()
    if not case:
        return prefill

    mapping = {
        "nom":         "last_name",
        "prenom":      "first_name",
        "dob":         "dob",
        "card_number": "document_number",
    }

    changed = False
    for src_key, case_attr in mapping.items():
        new_val = prefill.get(src_key)
        if not new_val or not hasattr(case, case_attr):
            continue
        if overwrite or not getattr(case, case_attr, None):
            setattr(case, case_attr, new_val)
            changed = True

    if changed:
        db.add(case)
        db.commit()
        db.refresh(case)

    return prefill


# ─────────────────────────────────────────────
# File upload helpers (shared)
# ─────────────────────────────────────────────

def _active_backend() -> str:
    return (settings.STORAGE_BACKEND or "LOCAL").upper()


async def _store_upload(file: UploadFile, obj_key: str) -> tuple[int, str, str, str | None]:
    """
    Lit le fichier uploadé et le stocke selon le backend configuré :
    - LOCAL : écrit sur disque (UPLOAD_ROOT) ;
    - S3    : envoie sur le bucket via la couche de stockage.
    Retourne (size_bytes, sha256_hex, backend, file_path|None).
    """
    sha = hashlib.sha256()
    size = 0
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf.extend(chunk)
        sha.update(chunk)
        size += len(chunk)
    data = bytes(buf)

    backend = _active_backend()
    try:
        if backend == "S3":
            get_storage().save(obj_key, data, file.content_type)
            file_path = None
        else:
            dest = _local_path(obj_key)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            file_path = str(dest)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    return size, sha.hexdigest(), backend, file_path


# ─────────────────────────────────────────────
# Upload : document lié à un case
# ─────────────────────────────────────────────

async def save_document(
    db: Session,
    case_id: UUID,
    doc_type: str,
    file: UploadFile,
    uploaded_by: Optional[UUID],
) -> Document:
    tenant_id = _require_tenant_uuid(db)

    doc_id   = uuid4()
    original = _safe_filename(file.filename or "upload.bin")
    obj_key  = f"cases/{case_id}/{doc_id}_{original}"

    size, sha256, backend, file_path = await _store_upload(file, obj_key)

    doc = Document(
        id=doc_id,
        tenant_id=tenant_id,
        case_id=case_id,
        doc_type=doc_type,
        storage_backend=backend,
        object_key=obj_key,
        file_path=file_path,
        original_filename=original,
        mime_type=file.content_type,
        size_bytes=size,
        sha256=sha256,
        uploaded_by=uploaded_by,
        uploaded_at=datetime.now(timezone.utc),
        ocr_status=OCRStatus.PENDING,
        ocr_confidence=None,
        extracted_fields={},
    )

    try:
        db.add(doc)
        db.commit()
        return doc
    except Exception as e:
        db.rollback()
        try:
            get_storage().delete(obj_key)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to create document: {e}")


# ─────────────────────────────────────────────
# Upload : document standalone (sans case)
# ─────────────────────────────────────────────

async def save_document_standalone(
    db: Session,
    doc_type: str,
    file: UploadFile,
    uploaded_by: Optional[str] = None,
) -> Document:
    tenant_id = _require_tenant_uuid(db)

    doc_type = (doc_type or "").strip()
    if not doc_type:
        raise HTTPException(status_code=400, detail="doc_type is required")

    try:
        uploader_uuid = UUID(str(uploaded_by)) if uploaded_by else None
    except Exception:
        raise HTTPException(status_code=400, detail="uploaded_by must be a valid UUID")

    doc_id   = uuid4()
    original = _safe_filename((file.filename or "upload.bin").strip())
    obj_key  = f"standalone/{doc_id}_{original}"

    size, sha256, backend, file_path = await _store_upload(file, obj_key)

    doc = Document(
        id=doc_id,
        tenant_id=tenant_id,
        case_id=None,
        doc_type=doc_type,
        storage_backend=backend,
        object_key=obj_key,
        file_path=file_path,
        original_filename=original,
        mime_type=(file.content_type or "application/octet-stream"),
        size_bytes=size,
        sha256=sha256,
        uploaded_by=uploader_uuid,
        uploaded_at=datetime.now(timezone.utc),
        ocr_status=OCRStatus.PENDING,
        ocr_confidence=None,
        extracted_fields={},
    )

    try:
        db.add(doc)
        db.commit()
        return doc
    except Exception as e:
        db.rollback()
        try:
            get_storage().delete(obj_key)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to create document: {e}")


# ─────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────

def list_documents(db: Session, case_id: UUID):
    return (
        db.query(Document)
        .filter(Document.case_id == case_id)
        .order_by(Document.uploaded_at.desc())
        .all()
    )


def get_document(db: Session, doc_id: UUID) -> Document:
    doc = db.query(Document).filter(Document.id == doc_id).one_or_none()
    if not doc:
        raise ValueError("Document not found")
    return doc


# ─────────────────────────────────────────────
# OCR
# ─────────────────────────────────────────────

def extract_document_fields_local(db: Session, doc_id: UUID) -> Document:
    doc = get_document(db, doc_id)

    backend = (getattr(doc, "storage_backend", None) or "LOCAL").upper()
    tmp_path: Optional[Path] = None

    if backend == StorageBackend.S3.value:
        # Télécharge le fichier depuis S3 vers un fichier temporaire pour l'OCR.
        try:
            body = get_storage().open(doc.object_key)
            data = body.read() if hasattr(body, "read") else bytes(body)
        except Exception as e:
            db.execute(update(Document).where(Document.id == doc_id).values(ocr_status=OCRStatus.FAILED))
            db.commit()
            raise ValueError(f"Impossible de lire le fichier depuis S3: {e}")
        suffix = Path(doc.object_key or "").suffix or ".bin"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(data)
        tmp.close()
        tmp_path = Path(tmp.name)
        file_path = tmp_path
    else:
        if not getattr(doc, "file_path", None):
            raise ValueError("file_path missing on document record")
        file_path = Path(doc.file_path)
        if not file_path.exists():
            db.execute(update(Document).where(Document.id == doc_id).values(ocr_status=OCRStatus.FAILED))
            db.commit()
            raise ValueError(f"File not found on disk: {file_path}")

    try:
        result = run_local_ocr(file_path)
    except Exception as e:
        db.execute(update(Document).where(Document.id == doc_id).values(ocr_status=OCRStatus.FAILED))
        db.commit()
        raise ValueError(f"OCR engine error: {type(e).__name__}: {e}")
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    new_status = OCRStatus.DONE if result.confidence >= 0.65 else OCRStatus.LOW_CONFIDENCE

    db.execute(
        update(Document)
        .where(Document.id == doc_id)
        .values(
            extracted_fields=result.fields or {},
            ocr_confidence=result.confidence,
            ocr_status=new_status,
        )
    )
    db.commit()

    # ❌ db.refresh(doc) — échoue car tenant context resetté après commit
    # return get_document(db, doc_id) — idem, RLS bloque

    # ✅ Met à jour l'objet en mémoire directement, zéro SELECT
    doc.extracted_fields = result.fields or {}
    doc.ocr_confidence   = result.confidence
    doc.ocr_status       = new_status
    return doc