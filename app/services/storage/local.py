from pathlib import Path
from app.core.config import settings
from .base import StorageService

class LocalStorageService(StorageService):
    def __init__(self):
        self.root = Path(settings.LOCAL_STORAGE_ROOT)

    def save(self, object_key: str, data: bytes, content_type: str | None = None) -> dict:
        path = self.root / object_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"size_bytes": len(data)}

    def delete(self, object_key: str) -> None:
        path = self.root / object_key
        if path.exists():
            path.unlink()

    def open(self, object_key: str):
        path = self.root / object_key
        return path.open("rb")
