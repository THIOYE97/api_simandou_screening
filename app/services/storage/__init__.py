from app.core.config import settings
from .local import LocalStorageService
from .s3 import S3StorageService
from .base import StorageService

def get_storage() -> StorageService:
    backend = (settings.STORAGE_BACKEND or "LOCAL").upper()
    if backend == "S3":
        return S3StorageService()
    return LocalStorageService()
