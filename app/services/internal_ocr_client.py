# app/services/internal_ocr_client.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import httpx


class InternalOcrError(RuntimeError):
    pass


class InternalOcrClient:
    """
    Client HTTP vers un service OCR interne.
    Utilisé comme alternative à l'OCR local quand un endpoint dédié est disponible.
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout  = timeout

    async def extract_id_fields(
        self,
        *,
        file_path: Path,
        doc_type: str,
        country: Optional[str] = None,
        side: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Envoie le fichier au service OCR interne.
        Retourne un dict de champs extraits (last_name, first_name, dob, document_number...).

        Raises:
            InternalOcrError: si le service répond avec une erreur ou est injoignable.
        """
        url  = f"{self.base_url}/extract"
        data = {k: v for k, v in {"doc_type": doc_type, "country": country, "side": side}.items() if v is not None}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                with file_path.open("rb") as f:
                    resp = await client.post(
                        url,
                        data=data,
                        files={"file": (file_path.name, f, "application/octet-stream")},
                    )

            if resp.status_code >= 400:
                raise InternalOcrError(f"OCR service returned {resp.status_code}: {resp.text}")

            return resp.json()

        except InternalOcrError:
            raise
        except httpx.TimeoutException:
            raise InternalOcrError(f"OCR service timed out after {self.timeout}s")
        except httpx.ConnectError as e:
            raise InternalOcrError(f"Cannot connect to OCR service at {self.base_url}: {e}")
        except Exception as e:
            raise InternalOcrError(f"Unexpected OCR error: {e}") from e