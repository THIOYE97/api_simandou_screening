# app/services/local_ocr_service.py
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

# ─────────────────────────────────────────────
# Lazy EasyOCR reader (chargé une seule fois)
# ─────────────────────────────────────────────

_reader = None

def _get_reader():
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(["fr", "en"], gpu=False)
    return _reader


# ─────────────────────────────────────────────
# Constants & regex
# ─────────────────────────────────────────────

MRZ_RE       = re.compile(r"^[A-Z0-9<]{25,}$")
_NUM_FIX     = str.maketrans({"O": "0", "D": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"})

RE_NOM       = re.compile(r"(?:\bNOM\b|Nom)\s*[:\-]?\s*([A-ZÀ-ÖØ-Ý' \-]{2,})", re.IGNORECASE)
RE_PRENOMS   = re.compile(r"(?:\bPR[ÉE]NOM(?:\(S\))?\b|Pr[ée]nom(?:\(s\))?)\s*[:\-]?\s*([A-ZÀ-ÖØ-Ý' \-]{2,})", re.IGNORECASE)

RE_DOB_1     = re.compile(r"(?:\bN[ÉE]\(?E?\)?\b.*?\bLE\b|N[ée]\(?e?\)?\s*le)\s*[:\-]?\s*([0-3]?\d[\/\-\.\s][01]?\d[\/\-\.\s](?:19|20)\d{2})", re.IGNORECASE)
RE_DOB_2     = re.compile(r"\b([0-3]\d[\/\-][01]\d[\/\-](?:19|20)\d{2})\b")
RE_DOB_3     = re.compile(r"\b([0-3]?\d)\s+([01]?\d)\s+((?:19|20)\d{2})\b")
RE_ANY_DATE  = re.compile(r"\b([0-3]?\d)[\/\-\.\s]([01]?\d)[\/\-\.\s]((?:19|20)?\d{2})\b")

RE_DOCNO_ALNUM  = re.compile(r"(?:N[°O]\s*DU\s*DOCUMENT|Document\s*No|N°|No|N0)\s*[:\-]?\s*([A-Z0-9]{6,15})", re.IGNORECASE)
RE_DOCNO_DIGITS = re.compile(r"\b(\d{9,13})\b")

LABEL_NOM    = re.compile(r"\bNOM\b|SURNAM[E]?",               re.IGNORECASE)
LABEL_PRENOM = re.compile(r"PR[ÉE]NOMS?|PRENOMS?|GIVEN\s*NAMES?", re.IGNORECASE)
LABEL_DOB    = re.compile(r"DATE\s+DE\s+NAISS|DATE\s+OF\s+BIRTH", re.IGNORECASE)
LABEL_CARDNO = re.compile(r"(NUM[ÉE]RO\s+DE\s+CARTE|CARD\s+NUMBER)", re.IGNORECASE)

DOCNO_STOPWORDS = {
    "DOCUMENT", "DOC", "DOCNO", "DUDOCUMENT", "DUDOC",
    "DATE", "DEXPIR", "EXPIR", "EXPIRY", "DELIVR", "DELIVRANCE",
    "NO", "N0", "NUMERO", "N",
}
NOISE_TOKENS = {"SS", "DS", "PB", "EE", "UE", "LE", "LA", "DE", "DU", "DES", "DATE"}

MAX_SIDE = 1600


# ─────────────────────────────────────────────
# Image preprocessing
# ─────────────────────────────────────────────

def _resize_limit(img: Image.Image, max_side: int = MAX_SIDE) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    scale = max_side / max(w, h)
    if scale >= 1:
        return img
    return img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)


def _preprocess(img: Image.Image) -> Image.Image:
    base = _resize_limit(img)
    gray = ImageOps.grayscale(base)
    c1   = ImageEnhance.Contrast(gray).enhance(1.6)
    return c1.filter(ImageFilter.UnsharpMask(radius=2, percent=180, threshold=3))


def _preprocess_mrz_crop(img: Image.Image) -> Image.Image:
    base = _resize_limit(img)
    w, h = base.size
    crop = base.crop((0, int(h * 0.62), w, h))
    gray = ImageOps.grayscale(crop)
    c1   = ImageEnhance.Contrast(gray).enhance(1.8)
    s1   = c1.filter(ImageFilter.UnsharpMask(radius=2, percent=200, threshold=3))
    return s1.point(lambda p: 255 if p > 160 else 0)


# ─────────────────────────────────────────────
# EasyOCR runner
# ─────────────────────────────────────────────

def _run_easyocr(img: Image.Image) -> Tuple[str, float]:
    """Retourne (texte, confidence 0-1)."""
    import numpy as np
    reader  = _get_reader()
    arr     = np.array(img)
    results = reader.readtext(arr, detail=1)
    if not results:
        return "", 0.0
    text       = "\n".join(r[1] for r in results)
    confidence = sum(r[2] for r in results) / len(results)
    return text.strip(), round(float(confidence), 4)


# ─────────────────────────────────────────────
# String helpers
# ─────────────────────────────────────────────

def _normalize_spaces(s: str) -> str:
    return " ".join(s.split()).strip()


def _clean_name(s: str) -> str:
    s    = _normalize_spaces(s)
    s    = re.sub(r"[^A-ZÀ-ÖØ-Ý'\- ]+", " ", s.upper())
    toks = [t for t in _normalize_spaces(s).split() if len(t) >= 2]
    return " ".join(toks).strip()


def _best_name_from_line(line: str) -> str:
    cleaned = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'\- ,]+", " ", line)
    toks    = [t for t in _normalize_spaces(cleaned).upper().split() if len(t) >= 2 and t not in NOISE_TOKENS]
    return " ".join(toks).strip()


def _normalize_year(yyyy: str) -> int:
    y = int(yyyy)
    if y < 100:
        return 1900 + y if y >= 30 else 2000 + y
    if y < 1900:
        return 1900 + (y % 100)
    return y


# ─────────────────────────────────────────────
# Label-aware extractors
# ─────────────────────────────────────────────

def _extract_date_after_label(text: str, label_re: re.Pattern) -> Optional[str]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        if label_re.search(line):
            m = RE_ANY_DATE.search(line)
            if not m:
                for j in range(i + 1, min(i + 4, len(lines))):
                    m = RE_ANY_DATE.search(lines[j])
                    if m:
                        break
            if m:
                dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
                return f"{_normalize_year(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"
    return None


def _extract_token_after_label(text: str, label_re: re.Pattern, token_re: str = r"[A-Z0-9]{6,20}") -> Optional[str]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        if label_re.search(line):
            toks = re.findall(token_re, line.upper())
            if toks:
                return toks[-1]
            if i + 1 < len(lines):
                toks = re.findall(token_re, lines[i + 1].upper())
                if toks:
                    return toks[0]
    return None


def _after_label_line(text: str, label_re: re.Pattern) -> Optional[str]:
    lines = [l.strip() for l in text.splitlines()]
    for i, line in enumerate(lines):
        if label_re.search(line):
            for j in range(i + 1, min(i + 6, len(lines))):
                cand = lines[j].strip()
                if cand and len(re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ0-9]+", "", cand)) >= 2:
                    return cand
    return None


def _extract_docno_smart(text: str) -> Optional[str]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        u       = line.upper()
        compact = u.replace(" ", "")
        if "DOCUMENT" in compact and any(x in compact for x in ("DOCUMENTNO", "DUDOCUMENT", "N°", "NO", "N0")):
            cand_lines = [u] + ([lines[i + 1].upper()] if i + 1 < len(lines) else [])
            tokens = [tok for cl in cand_lines for tok in re.findall(r"[A-Z0-9]{6,15}", cl)]
            for tok in tokens:
                if tok not in DOCNO_STOPWORDS and "DOCUMENT" not in tok and "EXPIR" not in tok:
                    return tok
    return None


def _extract_mrz(text: str) -> Optional[str]:
    lines = [l.strip().replace(" ", "") for l in text.splitlines() if MRZ_RE.match(l.strip().replace(" ", ""))]
    if len(lines) >= 2:
        return "\n".join(lines[-2:])
    return lines[0] if lines else None


def _parse_mrz_td1(mrz: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    lines = [l.strip() for l in mrz.splitlines() if l.strip()]
    if not lines:
        return out

    name_line = next((l for l in lines if "<<" in l), None)
    if name_line:
        parts   = name_line.split("<<", 1)
        surname = _clean_name(re.sub(r"^[A-Z]{1,2}[A-Z0-9<]{0,3}[A-Z]{3}", "", parts[0]).replace("<", " "))
        given   = _clean_name(parts[1].replace("<", " ")) if len(parts) > 1 else ""
        if surname: out["last_name"]  = surname
        if given:   out["first_name"] = given
        if surname and given:
            out["full_name"] = _normalize_spaces(f"{given} {surname}")

    for l in lines:
        clean = l.replace("<", " ")
        if "document_number" not in out:
            md = RE_DOCNO_DIGITS.search(clean)
            if md:
                out["document_number"] = md.group(1)
        if "date_of_birth" not in out:
            m_yy = re.search(r"\b(\d{6})\b", clean)
            if m_yy:
                raw  = m_yy.group(1)
                yy, mm, dd = int(raw[:2]), int(raw[2:4]), int(raw[4:6])
                year = 1900 + yy if yy >= 30 else 2000 + yy
                if 1 <= mm <= 12 and 1 <= dd <= 31:
                    out["date_of_birth"] = f"{year:04d}-{mm:02d}-{dd:02d}"
    return out


# ─────────────────────────────────────────────
# Field extraction from raw text
# ─────────────────────────────────────────────

def _guess_fields_from_text(text: str) -> Dict[str, Any]:
    fields: Dict[str, Any] = {"raw_text": text}

    # DOB
    dob = _extract_date_after_label(text, LABEL_DOB)
    if dob:
        fields["date_of_birth"] = dob

    if "date_of_birth" not in fields:
        m = RE_DOB_1.search(text) or RE_DOB_2.search(text)
        if m:
            raw   = re.sub(r"\s+", "", m.group(1)).replace(".", "/").replace("-", "/")
            parts = raw.split("/")
            if len(parts) == 3 and len(parts[2]) == 4:
                dd, mm, yyyy = parts
                fields["date_of_birth"] = f"{yyyy}-{int(mm):02d}-{int(dd):02d}"
        else:
            m3 = RE_DOB_3.search(text)
            if m3:
                fields["date_of_birth"] = f"{m3.group(3)}-{int(m3.group(2)):02d}-{int(m3.group(1)):02d}"

    # Document number (4 strategies in order)
    card = _extract_token_after_label(text, LABEL_CARDNO, token_re=r"[A-Z0-9]{6,15}")
    if card:
        fields["document_number"] = card

    if "document_number" not in fields:
        docno = _extract_docno_smart(text)
        if docno:
            fields["document_number"] = docno

    if "document_number" not in fields:
        m_al = RE_DOCNO_ALNUM.search(text.replace(" ", "").upper())
        if m_al:
            tok = m_al.group(1).strip().upper()
            if tok not in DOCNO_STOPWORDS and "EXPIR" not in tok:
                fields["document_number"] = tok

    if "document_number" not in fields:
        m_d = RE_DOCNO_DIGITS.search(text.translate(_NUM_FIX))
        if m_d:
            fields["document_number"] = m_d.group(1)

    # Last name
    if "last_name" not in fields:
        m_nom = RE_NOM.search(text)
        fields["last_name"] = _clean_name(m_nom.group(1)) if m_nom else (
            _best_name_from_line(nxt) if (nxt := _after_label_line(text, LABEL_NOM)) else None
        )

    # First name
    if "first_name" not in fields:
        m_pre = RE_PRENOMS.search(text)
        if m_pre:
            fields["first_name"] = _clean_name(m_pre.group(1))
        else:
            nxt = _after_label_line(text, LABEL_PRENOM)
            if nxt:
                fields["first_name"] = _normalize_spaces(re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'\- ,]+", " ", nxt)).upper()

    # Full name
    if fields.get("first_name") and fields.get("last_name"):
        fields["full_name"] = _normalize_spaces(f"{fields['first_name']} {fields['last_name']}")

    # Final cleanup
    for k in ("first_name", "last_name"):
        v = fields.get(k)
        if isinstance(v, str):
            v2 = _clean_name(v)
            fields[k] = v2 if len(v2) >= 2 and v2 not in {"R", "RR", "II"} else None

    # Remove None values
    return {k: v for k, v in fields.items() if v is not None}


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

@dataclass
class OCRResult:
    fields: Dict[str, Any]
    confidence: float


def ocr_to_prefill(fields: dict) -> dict:
    prefill: Dict[str, Any] = {}
    if fields.get("last_name"):      prefill["nom"]         = fields["last_name"]
    if fields.get("first_name"):     prefill["prenom"]      = fields["first_name"]
    if fields.get("date_of_birth"):  prefill["dob"]         = fields["date_of_birth"]
    if fields.get("document_number"): prefill["card_number"] = fields["document_number"]
    return prefill


def run_local_ocr(file_path: Path) -> OCRResult:
    img = Image.open(file_path)

    # ── 1) Essai MRZ sur la bande basse ──────────────────────────────────
    mrz_img  = _preprocess_mrz_crop(img)
    mrz_txt, _ = _run_easyocr(mrz_img)
    mrz      = _extract_mrz(mrz_txt)

    if mrz:
        mrz_fields = _parse_mrz_td1(mrz)
        out: Dict[str, Any] = {"raw_text": mrz_txt, "mrz": mrz}
        for k in ("last_name", "first_name", "date_of_birth", "document_number", "full_name"):
            if mrz_fields.get(k):
                out[k] = mrz_fields[k]
        essentials = sum(1 for k in ("last_name", "first_name", "date_of_birth", "document_number") if out.get(k))
        return OCRResult(fields=out, confidence=min(0.99, 0.55 + 0.10 * essentials))

    # ── 2) Fallback : OCR pleine image ───────────────────────────────────
    processed      = _preprocess(img)
    best_text, raw_conf = _run_easyocr(processed)

    fields = _guess_fields_from_text(best_text)

    # Tentative MRZ dans le texte complet
    mrz2 = _extract_mrz(best_text)
    if mrz2:
        fields["mrz"] = mrz2
        for k, v in _parse_mrz_td1(mrz2).items():
            if v:
                fields[k] = v

    essentials = sum(1 for k in ("last_name", "first_name", "date_of_birth", "document_number") if fields.get(k))
    boost      = 0.12 * essentials + (0.15 if fields.get("mrz") else 0.0)
    confidence = max(0.0, min(0.99, raw_conf + boost))

    minimal: Dict[str, Any] = {"raw_text": fields.get("raw_text", "")}
    for k in ("last_name", "first_name", "date_of_birth", "document_number", "full_name", "mrz"):
        if fields.get(k):
            minimal[k] = fields[k]

    return OCRResult(fields=minimal, confidence=confidence)