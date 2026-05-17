# app/services/local_ocr_service.py
"""
OCR via Claude Vision API.
Exposition :
  - run_local_ocr(file_path)         — sync, conservée pour compat (Celery worker / scripts)
  - run_local_ocr_async(file_path)   — async, à privilégier dans les routes FastAPI

L'async libère l'event loop pendant l'appel Anthropic (2-10s) → gain de
concurrence majeur sans toucher SQLAlchemy.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import anthropic
from anthropic import AsyncAnthropic

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("simandou.ocr")

_sync_client: Optional[anthropic.Anthropic] = None
_async_client: Optional[AsyncAnthropic] = None


def _require_api_key() -> str:
    key = settings.ANTHROPIC_API_KEY
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    return key


def _get_sync_client() -> anthropic.Anthropic:
    global _sync_client
    if _sync_client is None:
        _sync_client = anthropic.Anthropic(api_key=_require_api_key())
    return _sync_client


def _get_async_client() -> AsyncAnthropic:
    global _async_client
    if _async_client is None:
        _async_client = AsyncAnthropic(api_key=_require_api_key())
    return _async_client


def _mime_from_path(path: Path) -> str:
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",  ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(path.suffix.lower(), "image/jpeg")


SYSTEM_PROMPT = """\
You are a document OCR specialist. Extract identity fields from the provided identity document image.
ALWAYS respond with a single valid JSON object — no markdown, no explanation, no extra text.

JSON schema (all fields optional, omit if not found):
{
  "last_name":       "SURNAME in uppercase",
  "first_name":      "Given name(s) in uppercase",
  "full_name":       "FIRST LAST combined",
  "date_of_birth":   "YYYY-MM-DD",
  "document_number": "Alphanumeric ID number",
  "mrz":             "Full MRZ line(s) if visible",
  "confidence":      0.0 to 1.0
}

Rules:
- Extract exactly what is printed, do NOT infer.
- Dates must be ISO format YYYY-MM-DD.
- Names must be uppercase.
- confidence: 0.9+ if clear, 0.5-0.8 if partial, <0.5 if poor quality.
- If nothing readable: {"confidence": 0.0}
"""

CLAUDE_MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 512


def _parse_response(text: str) -> Dict[str, Any]:
    raw = re.sub(r"^```(?:json)?\s*", "", text.strip())
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        logger.warning("claude_vision_json_parse_failed", extra={"sample": raw[:200]})
        return {"confidence": 0.0}


def _build_messages_payload(image_data: bytes, mime_type: str) -> list:
    b64 = base64.standard_b64encode(image_data).decode("utf-8")
    return [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": b64}},
            {"type": "text",  "text": "Extract all identity fields from this document image."},
        ],
    }]


def _call_claude_vision_sync(image_data: bytes, mime_type: str) -> Dict[str, Any]:
    message = _get_sync_client().messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=_build_messages_payload(image_data, mime_type),
    )
    return _parse_response(message.content[0].text)


async def _call_claude_vision_async(image_data: bytes, mime_type: str) -> Dict[str, Any]:
    message = await _get_async_client().messages.create(
        model=CLAUDE_MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=_build_messages_payload(image_data, mime_type),
    )
    return _parse_response(message.content[0].text)


@dataclass
class OCRResult:
    fields: Dict[str, Any]
    confidence: float


def ocr_to_prefill(fields: dict) -> dict:
    prefill: Dict[str, Any] = {}
    if fields.get("last_name"):       prefill["nom"]         = fields["last_name"]
    if fields.get("first_name"):      prefill["prenom"]      = fields["first_name"]
    if fields.get("date_of_birth"):   prefill["dob"]         = fields["date_of_birth"]
    if fields.get("document_number"): prefill["card_number"] = fields["document_number"]
    return prefill


def _finalize(result: Dict[str, Any]) -> OCRResult:
    raw_conf = result.pop("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(raw_conf)))
    except (TypeError, ValueError):
        confidence = 0.5 if result else 0.0

    fields = {k: v for k, v in result.items() if v not in (None, "", [], {})}
    extracted = [k for k in ("last_name", "first_name", "date_of_birth", "document_number") if fields.get(k)]
    logger.info("claude_vision_done", extra={"confidence": round(confidence, 2), "extracted": extracted})
    return OCRResult(fields=fields, confidence=confidence)


def run_local_ocr(file_path: Path) -> OCRResult:
    """Version sync — usage: Celery worker, scripts, BackgroundTasks."""
    if not file_path.exists():
        raise FileNotFoundError(f"OCR: file not found: {file_path}")

    try:
        data = _call_claude_vision_sync(file_path.read_bytes(), _mime_from_path(file_path))
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Claude Vision API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError(f"Claude Vision connection error: {e}") from e

    return _finalize(data)


async def run_local_ocr_async(file_path: Path) -> OCRResult:
    """Version async — usage: routes FastAPI `async def`. Libère l'event loop."""
    if not file_path.exists():
        raise FileNotFoundError(f"OCR: file not found: {file_path}")

    # I/O fichier en thread pour ne pas bloquer (gros fichiers possibles)
    data_bytes = await asyncio.to_thread(file_path.read_bytes)
    mime = _mime_from_path(file_path)

    try:
        data = await _call_claude_vision_async(data_bytes, mime)
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Claude Vision API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError(f"Claude Vision connection error: {e}") from e

    return _finalize(data)
