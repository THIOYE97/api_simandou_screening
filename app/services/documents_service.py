# app/services/documents_service.py
from __future__ import annotations

from pathlib import Path
from uuid import uuid4, UUID
from uuid import UUID as UUID_T
from datetime import datetime, timezone
from typing import Dict, Any
import hashlib

from sqlalchemy import text, update
from sqlalchemy.orm import Session
from fastapi import UploadFile, HTTPException

from app.models.document import Document, StorageBackend, OCRStatus
from app.services.local_ocr_service import run_local_ocr
from app.models.case import Case


# -----------------------------------------------------------------------------
# Storage path (ABSOLUTE)
# -----------------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parents[1]   # .../app
PROJECT_DIR = APP_DIR.parent                   # .../<repo>
UPLOAD_ROOT = (PROJECT_DIR / "uploads").resolve()
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

print("[documents_service] UPLOAD_ROOT =", UPLOAD_ROOT, "| cwd =", Path.cwd())


# -----------------------------------------------------------------------------
# Tenant helpers (RLS)
# -----------------------------------------------------------------------------
def _current_tenant_uuid(db: Session) -> UUID_T | None:
    val = db.execute(
        text("SELECT nullif(current_setting('app.tenant_id', true), '')")
    ).scalar()
    if not val:
        return None
    return UUID_T(str(val))


def _require_tenant_uuid(db: Session) -> UUID_T:
    tid = _current_tenant_uuid(db)
    if not tid:
        raise HTTPException(status_code=400, detail="tenant context missing (app.tenant_id is not set)")
    return tid


# -----------------------------------------------------------------------------
# Utils
# -----------------------------------------------------------------------------
def _safe_filename(name: str) -> str:
    name = (name or "upload.bin").replace("/", "_").replace("\\", "_").strip()
    if not name:
        name = "upload.bin"
    return name[:180]


def _local_path_from_object_key(object_key: str) -> Path:
    return (UPLOAD_ROOT / object_key).resolve()


def _ocr_fields_to_prefill(extracted_fields: Dict[str, Any]) -> Dict[str, Any]:
    prefill: Dict[str, Any] = {}
    if extracted_fields.get("last_name"):
        prefill["nom"] = extracted_fields["last_name"]
    if extracted_fields.get("first_name"):
        prefill["prenom"] = extracted_fields["first_name"]
    if extracted_fields.get("date_of_birth"):
        prefill["dob"] = extracted_fields["date_of_birth"]
    if extracted_fields.get("document_number"):
        prefill["card_number"] = extracted_fields["document_number"]
    return prefill


# -----------------------------------------------------------------------------
# Prefill case (optional)
# -----------------------------------------------------------------------------
def apply_ocr_prefill_to_case(
    db: Session,
    case_id,
    extracted_fields: Dict[str, Any],
    overwrite: bool = False,
) -> Dict[str, Any]:
    if not case_id:
        return {}

    prefill = _ocr_fields_to_prefill(extracted_fields)

    case = db.query(Case).filter(Case.id == case_id).one_or_none()
    if not case:
        return prefill

    mapping = {
        "nom": "last_name",
        "prenom": "first_name",
        "dob": "dob",
        "card_number": "document_number",
    }

    changed = False
    for src_key, case_attr in mapping.items():
        if src_key not in prefill:
            continue
        new_val = prefill[src_key]
        if not new_val:
            continue
        if not hasattr(case, case_attr):
            continue

        cur_val = getattr(case, case_attr, None)
        if overwrite or not cur_val:
            setattr(case, case_attr, new_val)
            changed = True

    if changed:
        db.add(case)
        db.commit()
        db.refresh(case)

    return prefill


# -----------------------------------------------------------------------------
# CRUD
# -----------------------------------------------------------------------------
async def save_document(
    db: Session,
    case_id: UUID,
    doc_type: str,
    file: UploadFile,
    uploaded_by: UUID | None,
) -> Document:
    tenant_id = _require_tenant_uuid(db)

    doc_id = uuid4()
    original = _safe_filename(file.filename or "upload.bin")

    object_key = f"cases/{case_id}/{doc_id}_{original}"
    file_path = _local_path_from_object_key(object_key)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    sha = hashlib.sha256()
    size_bytes = 0

    try:
        with file_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                sha.update(chunk)
                size_bytes += len(chunk)
    except Exception as e:
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    print("[upload case] saved:", file_path, "| exists:", file_path.exists())

    doc = Document(
        id=doc_id,
        tenant_id=tenant_id,
        case_id=case_id,
        doc_type=doc_type,

        # ✅ DB = string
        storage_backend=StorageBackend.LOCAL.value,

        object_key=object_key,
        file_path=str(file_path),

        original_filename=original,
        mime_type=file.content_type,
        size_bytes=size_bytes,
        sha256=sha.hexdigest(),
        uploaded_by=uploaded_by,
        uploaded_at=datetime.now(timezone.utc),

        ocr_status=OCRStatus.PENDING,
        ocr_confidence=None,

        # ✅ jamais NULL (colonne NOT NULL)
        extracted_fields={},
    )

    try:
        db.add(doc)
        db.commit()
        return doc
    except Exception as e:
        db.rollback()
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to create document: {e}")


async def save_document_standalone(
    db: Session,
    doc_type: str,
    file: UploadFile,
    uploaded_by: str | None = None,
) -> Document:
    tenant_id = _require_tenant_uuid(db)

    doc_type = (doc_type or "").strip()
    if not doc_type:
        raise HTTPException(status_code=400, detail="doc_type is required")

    original_filename = _safe_filename((file.filename or "upload.bin").strip())
    mime_type = (file.content_type or "application/octet-stream").strip()

    try:
        uploaded_by_uuid = (
            uploaded_by
            if isinstance(uploaded_by, UUID_T)
            else (UUID_T(str(uploaded_by)) if uploaded_by else None)
        )
    except Exception:
        raise HTTPException(status_code=400, detail="uploaded_by must be a valid UUID")

    doc_id = uuid4()

    object_key = f"standalone/{doc_id}_{original_filename}"
    file_path = _local_path_from_object_key(object_key)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    sha = hashlib.sha256()
    size_bytes = 0

    try:
        with file_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                sha.update(chunk)
                size_bytes += len(chunk)
    except Exception as e:
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    print("[upload standalone] saved:", file_path, "| exists:", file_path.exists())

    doc = Document(
        id=doc_id,
        tenant_id=tenant_id,
        case_id=None,
        doc_type=doc_type,
        uploaded_by=uploaded_by_uuid,
        uploaded_at=datetime.now(timezone.utc),

        # ✅ DB = string
        storage_backend=StorageBackend.LOCAL.value,

        object_key=object_key,
        file_path=str(file_path),

        original_filename=original_filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        sha256=sha.hexdigest(),

        ocr_status=OCRStatus.PENDING,
        ocr_confidence=None,

        # ✅ jamais NULL
        extracted_fields={},
    )

    try:
        db.add(doc)
        db.commit()
        return doc
    except Exception as e:
        db.rollback()
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to create document: {e}")


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


# -----------------------------------------------------------------------------
# OCR
# -----------------------------------------------------------------------------
def extract_document_fields_local(db: Session, doc_id: UUID) -> Document:
    doc = get_document(db, doc_id)

    # ✅ storage_backend = string
    backend = (doc.storage_backend or "").upper()
    if backend != StorageBackend.LOCAL.value:
        raise ValueError(f"Local OCR supports only LOCAL storage_backend (got {doc.storage_backend!r})")

    if not getattr(doc, "file_path", None):
        raise ValueError("File path missing on document record")

    file_path = Path(doc.file_path)

    print("[ocr] will read:", file_path, "| exists:", file_path.exists())

    if not file_path.exists():
        db.execute(
            update(Document)
            .where(Document.id == doc_id)
            .values(ocr_status=OCRStatus.FAILED)
        )
        db.commit()
        raise ValueError(f"File not found on disk: {file_path}")

    try:
        ocr = run_local_ocr(file_path)
    except Exception as e:
        db.execute(
            update(Document)
            .where(Document.id == doc_id)
            .values(ocr_status=OCRStatus.FAILED)
        )
        db.commit()
        raise ValueError(f"OCR engine error: {type(e).__name__}: {e}")

    new_status = OCRStatus.DONE if ocr.confidence >= 0.65 else OCRStatus.LOW_CONFIDENCE

    db.execute(
        update(Document)
        .where(Document.id == doc_id)
        .values(
            extracted_fields=ocr.fields or {},   # ✅ jamais NULL
            ocr_confidence=ocr.confidence,
            ocr_status=new_status,
        )
    )
    db.commit()

    return get_document(db, doc_id)
