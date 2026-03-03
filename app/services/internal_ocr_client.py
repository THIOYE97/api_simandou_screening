# app/services/internal_ocr_client.py
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Optional
import httpx

class InternalOcrError(RuntimeError):
    pass

class InternalOcrClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def extract_id_fields(
        self,
        *,
        file_path: Path,
        doc_type: str,
        country: Optional[str] = None,
        side: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Envoie le fichier à ton système interne, récupère un JSON de champs extraits.
        """
        url = f"{self.base_url}/extract"  # adapte au vrai endpoint interne
        data = {"doc_type": doc_type, "country": country, "side": side}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                with file_path.open("rb") as f:
                    files = {"file": (file_path.name, f, "application/octet-stream")}
                    r = await client.post(url, data=data, files=files)
            if r.status_code >= 400:
                raise InternalOcrError(f"OCR error {r.status_code}: {r.text}")
            return r.json()
        except Exception as e:
            raise InternalOcrError(str(e)) from e
