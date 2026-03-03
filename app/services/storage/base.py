from abc import ABC, abstractmethod

class StorageService(ABC):
    @abstractmethod
    def save(self, object_key: str, data: bytes, content_type: str | None = None) -> dict:
        """Return dict metadata, e.g. {size_bytes:...,}"""
        raise NotImplementedError

    @abstractmethod
    def delete(self, object_key: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def open(self, object_key: str):
        """Return a file-like or bytes iterator for streaming (LOCAL)."""
        raise NotImplementedError

    def presign_get(self, object_key: str, expires_seconds: int) -> str | None:
        """Optional (S3)."""
        return None
