# app/services/sumsub_client.py
from __future__ import annotations

import time
import json
import hmac
import hashlib
from dataclasses import dataclass
from typing import Any, Optional, Dict, Tuple, List
from urllib.parse import quote

import httpx


@dataclass
class SumsubConfig:
    base_url: str
    app_token: str
    secret_key: str


class SumsubClient:
    """
    Minimal, consistent client:
    - request_json(): signed JSON calls
    - request_bytes(): signed binary calls
    - applicants: create/get/one (+ find by externalUserId)
    - websdk: link + access token (userId + applicantId)
    - inspections resources: info + download
    - bundle + files extraction helper
    - download_file_by_id(): resolves file_id -> inspectionId -> resource bytes
    """

    def __init__(self, cfg: SumsubConfig):
        self.cfg = cfg

    # -----------------------------
    # Signing / headers
    # -----------------------------

    def _sign(self, ts: str, method: str, path: str, body: str) -> str:
        payload = f"{ts}{method.upper()}{path}{body}"
        return hmac.new(
            self.cfg.secret_key.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _headers(self, ts: str, sig: str, content_type: str = "application/json") -> Dict[str, str]:
        return {
            "Content-Type": content_type,
            "X-App-Token": self.cfg.app_token,
            "X-App-Access-Ts": ts,
            "X-App-Access-Sig": sig,
        }

    # -----------------------------
    # HTTP helpers
    # -----------------------------

    async def request_json(self, method: str, path: str, body_obj: dict | None = None) -> Any:
        body = json.dumps(body_obj) if body_obj is not None else ""
        ts = str(int(time.time()))
        sig = self._sign(ts, method, path, body)

        url = self.cfg.base_url.rstrip("/") + path
        headers = self._headers(ts, sig, "application/json")

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, url, headers=headers, content=body.encode("utf-8"))

        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        if resp.status_code >= 400:
            raise RuntimeError({"status": resp.status_code, "error": data})
        return data

    async def request_bytes(self, method: str, path: str) -> Tuple[bytes, Optional[str], Optional[str]]:
        """
        Binary fetch (image/pdf).
        Returns: (bytes, content_type, filename)
        """
        body = ""
        ts = str(int(time.time()))
        sig = self._sign(ts, method, path, body)

        url = self.cfg.base_url.rstrip("/") + path
        headers = self._headers(ts, sig, "application/json")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.request(method, url, headers=headers)

        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:
                err = {"raw": resp.text}
            raise RuntimeError({"status": resp.status_code, "error": err})

        content_type = resp.headers.get("content-type")
        filename = _parse_filename_from_cd(resp.headers.get("content-disposition"))
        return resp.content, content_type, filename

    # -----------------------------
    # Applicants
    # -----------------------------

    async def create_applicant(self, external_user_id: str, level_name: str) -> dict:
        path = f"/resources/applicants?levelName={quote(level_name, safe='')}"
        return await self.request_json("POST", path, {"externalUserId": external_user_id})

    async def get_applicant(self, externalUserId: str) -> dict:
        # attention: ce endpoint n'est pas toujours "by externalUserId" selon configs.
        # conservé pour compat.
        path = f"/resources/applicants/{quote(str(externalUserId), safe='')}"
        return await self.request_json("GET", path, None)

    async def get_applicant_one(self, applicant_id: str) -> dict:
        """
        GET /resources/applicants/{applicantId}/one
        Contains inspectionId, info.idDocs, review, etc.
        """
        path = f"/resources/applicants/{quote(str(applicant_id), safe='')}/one"
        return await self.request_json("GET", path, None)

    async def find_applicant_by_external_user_id(self, external_user_id: str) -> Optional[dict]:
        """
        GET /resources/applicants?externalUserId=<...>
        Returns first matching applicant dict or None.
        """
        eid = quote(str(external_user_id), safe="")
        path = f"/resources/applicants?externalUserId={eid}"
        data = await self.request_json("GET", path, None)

        if isinstance(data, dict):
            items = None
            if isinstance(data.get("list"), dict):
                items = data["list"].get("items")
            if items is None:
                items = data.get("items")
            if isinstance(items, list) and items:
                return items[0]

        if isinstance(data, list) and data:
            return data[0]

        return None

    async def get_applicant_by_external_user_id_one(self, external_user_id: str) -> dict:
        """
        Recommended stable endpoint to retrieve applicant by externalUserId:
        GET /resources/applicants/-;externalUserId=<externalUserId>/one
        """
        eid = quote(str(external_user_id), safe="")
        path = f"/resources/applicants/-;externalUserId={eid}/one"
        return await self.request_json("GET", path, None)

    # -----------------------------
    # WebSDK (permalink link)
    # -----------------------------

    async def generate_websdk_link(self, applicant_id: str, level_name: str, ttl_in_secs: int = 1800) -> dict:
        path = f"/resources/sdkIntegrations/levels/{quote(level_name, safe='')}/websdkLink"
        body = {"applicantId": applicant_id, "ttlInSecs": int(ttl_in_secs)}
        return await self.request_json("POST", path, body)

    # -----------------------------
    # WebSDK token (SDK-only friendly)
    # -----------------------------

    async def generate_access_token_user(
        self,
        external_user_id: str,
        level_name: str,
        ttl_in_seconds: Optional[int] = None,
    ) -> dict:
        """
        ✅ SDK-only token via userId/externalUserId.
    Sumsub endpoint is strict: do NOT send JSON body (can return 'Unexpected body').
    Use query params only
        """
        uid = quote(str(external_user_id), safe="")
        lvl = quote(str(level_name), safe="")
        path = f"/resources/accessTokens?userId={uid}&levelName={lvl}"
        if ttl_in_seconds is not None:
            path += f"&ttlInSecs={int(ttl_in_seconds)}"
        return await self.request_json("POST", path, None)

    async def generate_access_token_sdk(
        self,
        applicant_id: str,
        level_name: str,
        ttl_in_seconds: Optional[int] = None,
    ) -> dict:
        """
        Token basé sur applicantId (à garder pour compat si tu l’utilises ailleurs)
        POST /resources/accessTokens/sdk
        """
        path = "/resources/accessTokens/sdk"
        payload: Dict[str, Any] = {"applicantId": applicant_id, "levelName": level_name}

        if ttl_in_seconds is not None:
            payload["ttlInSecs"] = int(ttl_in_seconds)
        return await self.request_json("POST", path, payload)

    # -----------------------------
    # Inspections resources (binary)
    # -----------------------------

    async def get_document_image_info(self, inspection_id: str, image_id: str) -> dict:
        path = f"/resources/inspections/{quote(str(inspection_id), safe='')}/resources/{quote(str(image_id), safe='')}/info"
        return await self.request_json("GET", path, None)

    async def download_document_image(self, inspection_id: str, image_id: str) -> Tuple[bytes, Optional[str], Optional[str]]:
        path = f"/resources/inspections/{quote(str(inspection_id), safe='')}/resources/{quote(str(image_id), safe='')}"
        return await self.request_bytes("GET", path)

    # -----------------------------
    # Bundle helpers
    # -----------------------------

    async def get_applicant_one_bundle(self, applicant_id: str) -> dict:
        one = await self.get_applicant_one(applicant_id)
        out: dict = {"applicant_id": applicant_id, "applicant_one": one}

        inspection_id = (one or {}).get("inspectionId")
        out["inspection_id"] = inspection_id

        resources = extract_resource_ids_from_applicant_one(one)
        out["resources"] = resources

        if inspection_id and resources:
            infos: List[dict] = []
            for rid in resources[:50]:
                try:
                    info = await self.get_document_image_info(str(inspection_id), str(rid))
                    infos.append({"id": str(rid), "info": info})
                except Exception as e:
                    infos.append({"id": str(rid), "error": str(e)})
            out["resource_infos"] = infos

        return out

    async def download_file_by_id(self, applicant_id: str, file_id: str) -> Tuple[bytes, Optional[str], Optional[str]]:
        one = await self.get_applicant_one(applicant_id)
        inspection_id = (one or {}).get("inspectionId")
        if not inspection_id:
            raise RuntimeError({"status": 404, "error": {"detail": "inspectionId missing in applicant_one"}})

        blob, content_type, filename = await self.download_document_image(str(inspection_id), str(file_id))

        if not filename:
            ext = guess_ext_from_content_type(content_type)
            filename = f"sumsub_{file_id}{ext}"

        return blob, content_type, filename


# -----------------------------------------------------------------------------
# Pure helpers (no http)
# -----------------------------------------------------------------------------

def _parse_filename_from_cd(content_disposition: Optional[str]) -> Optional[str]:
    if not content_disposition:
        return None
    lower = content_disposition.lower()
    if "filename=" not in lower:
        return None
    try:
        part = content_disposition.split("filename=", 1)[1].strip()
        if part.startswith('"'):
            return part.split('"', 2)[1]
        return part.split(";", 1)[0].strip()
    except Exception:
        return None


def guess_ext_from_content_type(content_type: Optional[str]) -> str:
    if not content_type:
        return ""
    ct = content_type.split(";")[0].strip().lower()
    if ct == "application/pdf":
        return ".pdf"
    if ct in ("image/jpeg", "image/jpg"):
        return ".jpg"
    if ct == "image/png":
        return ".png"
    if ct == "image/webp":
        return ".webp"
    return ""


def extract_resource_ids_from_applicant_one(one: Any) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()

    def add(x: Any):
        if not x:
            return
        s = str(x)
        if s in seen:
            return
        seen.add(s)
        out.append(s)

    def walk(obj: Any):
        if isinstance(obj, dict):
            if isinstance(obj.get("imageIds"), list):
                for iid in obj["imageIds"]:
                    add(iid)

            if isinstance(obj.get("images"), list):
                for im in obj["images"]:
                    if isinstance(im, dict):
                        add(im.get("imageId") or im.get("id") or im.get("fileId"))
                    else:
                        add(im)

            add(obj.get("imageId"))
            add(obj.get("fileId"))

            for v in obj.values():
                walk(v)

        elif isinstance(obj, list):
            for it in obj:
                walk(it)

    walk(one)
    return out
