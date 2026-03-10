# app/services/local_ocr_service.py
"""
OCR via Claude Vision API (claude-sonnet-4-20250514).
Remplace EasyOCR — zéro RAM supplémentaire, même interface publique.
"""
from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import anthropic

_client: Optional[anthropic.Anthropic] = None

def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY environment variable is not set")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client

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

def _call_claude_vision(image_data: bytes, mime_type: str) -> Dict[str, Any]:
    b64 = base64.standard_b64encode(image_data).decode("utf-8")
    message = _get_client().messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": b64}},
                {"type": "text",  "text": "Extract all identity fields from this document image."},
            ],
        }],
    )
    raw = re.sub(r"^```(?:json)?\s*", "", message.content[0].text.strip())
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
        print(f"[claude_vision] ⚠️ JSON parse failed: {raw[:200]}")
        return {"confidence": 0.0}

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

def run_local_ocr(file_path: Path) -> OCRResult:
    if not file_path.exists():
        raise FileNotFoundError(f"OCR: file not found: {file_path}")

    try:
        result = _call_claude_vision(file_path.read_bytes(), _mime_from_path(file_path))
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Claude Vision API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise RuntimeError(f"Claude Vision connection error: {e}") from e

    raw_conf = result.pop("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(raw_conf)))
    except (TypeError, ValueError):
        confidence = 0.5 if result else 0.0

    fields = {k: v for k, v in result.items() if v not in (None, "", [], {})}
    extracted = [k for k in ("last_name", "first_name", "date_of_birth", "document_number") if fields.get(k)]
    print(f"[claude_vision] ✅ confidence={confidence:.2f} extracted={extracted}")

    return OCRResult(fields=fields, confidence=confidence)