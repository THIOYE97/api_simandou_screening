from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from app.models.document import StorageBackend, OCRStatus

class DocumentOut(BaseModel):
    id: UUID
    case_id: UUID
    doc_type: str
    storage_backend: StorageBackend
    object_key: str
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    sha256: Optional[str] = None
    ocr_status: OCRStatus

    class Config:
        from_attributes = True

class DownloadResponse(BaseModel):
    url: Optional[str] = None
    expires_in: Optional[int] = None
