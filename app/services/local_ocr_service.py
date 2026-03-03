# app/services/local_ocr_service.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import re

import pytesseract
from PIL import Image, ImageOps, ImageEnhance, ImageFilter


# ----------------------------
# Regex / constants
# ----------------------------

# MRZ lines are typically long sequences with <, A-Z, 0-9
MRZ_RE = re.compile(r"^[A-Z0-9<]{25,}$")

# Common OCR confusions (only apply in numeric contexts)
_NUM_FIX = str.maketrans({"O": "0", "D": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"})

# French labels (CNI / ID cards)
RE_NOM = re.compile(r"(?:\bNOM\b|Nom)\s*[:\-]?\s*([A-ZÀ-ÖØ-Ý' \-]{2,})", re.IGNORECASE)
RE_PRENOMS = re.compile(
    r"(?:\bPR[ÉE]NOM(?:\(S\))?\b|Pr[ée]nom(?:\(s\))?)\s*[:\-]?\s*([A-ZÀ-ÖØ-Ý' \-]{2,})",
    re.IGNORECASE,
)

# DOB patterns
RE_DOB_1 = re.compile(
    r"(?:\bN[ÉE]\(?E?\)?\b.*?\bLE\b|N[ée]\(?e?\)?\s*le)\s*[:\-]?\s*([0-3]?\d[\/\-\.\s][01]?\d[\/\-\.\s](?:19|20)\d{2})",
    re.IGNORECASE,
)
RE_DOB_2 = re.compile(r"\b([0-3]\d[\/\-][01]\d[\/\-](?:19|20)\d{2})\b")
RE_DOB_3 = re.compile(r"\b([0-3]?\d)\s+([01]?\d)\s+((?:19|20)\d{2})\b")

# Document number patterns
RE_DOCNO_ALNUM = re.compile(
    r"(?:N[°O]\s*DU\s*DOCUMENT|Document\s*No|N°|No|N0)\s*[:\-]?\s*([A-Z0-9]{6,15})",
    re.IGNORECASE,
)
RE_DOCNO_DIGITS = re.compile(r"\b(\d{9,13})\b")  # digit-only IDs fallback

DOCNO_STOPWORDS = {
    "DOCUMENT", "DOC", "DOCNO", "DUDOCUMENT", "DUDOC",
    "DATE", "DEXPIR", "EXPIR", "EXPIRY", "DELIVR", "DELIVRANCE",
    "NO", "N0", "NUMERO", "N",
}

# Labels (tolerant)
LABEL_NOM = re.compile(r"\bNOM\b|SURNAM[E]?", re.IGNORECASE)
LABEL_PRENOM = re.compile(r"PR[ÉE]NOMS?|PRENOMS?|GIVEN\s*NAMES?", re.IGNORECASE)
LABEL_DOB = re.compile(r"DATE\s+DE\s+NAISS|DATE\s+OF\s+BIRTH", re.IGNORECASE)
LABEL_CARDNO = re.compile(r"(NUM[ÉE]RO\s+DE\s+CARTE|CARD\s+NUMBER)", re.IGNORECASE)

# Generic date finder (supports 29 08 1977, 29/08/1977, 29-08-1977, etc.)
RE_ANY_DATE = re.compile(r"\b([0-3]?\d)[\/\-\.\s]([01]?\d)[\/\-\.\s]((?:19|20)?\d{2})\b")

# Noise tokens for name lines (Mali cards often have "ss", "ds", etc.)
NOISE_TOKENS = {"SS", "DS", "PB", "EE", "UE", "LE", "LA", "DE", "DU", "DES", "DATE"}

# OCR tuning knobs (MVP perf)
DEFAULT_LANG = "fra+eng"
MRZ_LANG = "eng"
FAST_PSM = 6
MRZ_PSM = 6
MAX_SIDE = 1600


# ----------------------------
# Helpers
# ----------------------------

def _normalize_spaces(s: str) -> str:
    return " ".join(s.split()).strip()


def _clean_name(s: str) -> str:
    s = _normalize_spaces(s)
    s = re.sub(r"[^A-ZÀ-ÖØ-Ý'\- ]+", " ", s.upper())
    s = _normalize_spaces(s)
    toks = [t for t in s.split() if len(t) >= 2]
    return " ".join(toks).strip()


def _best_name_from_line(line: str) -> str:
    cleaned = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'\- ,]+", " ", line)
    cleaned = _normalize_spaces(cleaned).upper()
    toks = [t for t in cleaned.split() if len(t) >= 2 and t not in NOISE_TOKENS]
    return " ".join(toks).strip()


def _fix_numeric_token(s: str) -> str:
    s2 = re.sub(r"\s+", "", s.upper())
    return s2.translate(_NUM_FIX)


def _normalize_year(yyyy: str) -> int:
    """
    Fix OCR weird years like 1097 -> 1997 (take last 2 digits).
    """
    y = int(yyyy)
    if y < 100:  # 2-digit year
        return 1900 + y if y >= 30 else 2000 + y
    if y < 1900:  # e.g. 1097
        return 1900 + (y % 100)
    return y


def _extract_date_after_label(text: str, label_re: re.Pattern) -> Optional[str]:
    """
    Find a date on the same line as label, otherwise in next lines.
    Returns YYYY-MM-DD.
    """
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
                year = _normalize_year(yyyy)
                return f"{year:04d}-{int(mm):02d}-{int(dd):02d}"
    return None


def _extract_token_after_label(text: str, label_re: re.Pattern, token_re: str = r"[A-Z0-9]{6,20}") -> Optional[str]:
    """
    Find token after label (same line or next line).
    """
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
    """
    Return first "real" line after a label, skipping noise/very short punctuation lines.
    """
    lines = [l.strip() for l in text.splitlines()]
    for i, line in enumerate(lines):
        if label_re.search(line):
            for j in range(i + 1, min(i + 6, len(lines))):
                cand = lines[j].strip()
                if not cand:
                    continue
                if len(re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ0-9]+", "", cand)) < 2:
                    continue
                return cand
    return None


def _extract_docno_smart(text: str) -> Optional[str]:
    """
    Robust doc number extraction for lines like:
    'N° DU DOCUMENT / Document No DATE DEXPIR ...'
    then next line contains 'XEOXJ2E57 ...'

    We look at the "document zone", collect tokens from same + next line,
    and return the first non-label token.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        u = line.upper()
        compact = u.replace(" ", "")
        if "DOCUMENT" in compact and ("DOCUMENTNO" in compact or "DUDOCUMENT" in compact or "N°" in line or "NO" in compact or "N0" in compact):
            cand_lines = [u]
            if i + 1 < len(lines):
                cand_lines.append(lines[i + 1].upper())

            tokens: list[str] = []
            for cl in cand_lines:
                tokens.extend(re.findall(r"[A-Z0-9]{6,15}", cl))

            for tok in tokens:
                if tok in DOCNO_STOPWORDS:
                    continue
                if "DOCUMENT" in tok or "EXPIR" in tok:
                    continue
                return tok
    return None


def _extract_mrz(text: str) -> Optional[str]:
    lines = [l.strip().replace(" ", "") for l in text.splitlines()]
    lines = [l for l in lines if MRZ_RE.match(l)]
    if len(lines) >= 2:
        return "\n".join(lines[-2:])
    if len(lines) == 1:
        return lines[0]
    return None


def _parse_mrz_td1(mrz: str) -> Dict[str, Any]:
    """
    Best-effort MRZ parser (TD1-ish).
    Mainly: last_name, first_name, date_of_birth, document_number.
    """
    out: Dict[str, Any] = {}
    lines = [l.strip() for l in mrz.splitlines() if l.strip()]
    if not lines:
        return out

    name_line = next((l for l in lines if "<<" in l), None)
    if name_line:
        parts = name_line.split("<<", 1)
        surname_raw = parts[0]
        given_raw = parts[1] if len(parts) > 1 else ""
        surname_raw = re.sub(r"^[A-Z]{1,2}[A-Z0-9<]{0,3}[A-Z]{3}", "", surname_raw)  # rough
        surname = _clean_name(surname_raw.replace("<", " "))
        given = _clean_name(given_raw.replace("<", " "))
        if surname:
            out["last_name"] = surname
        if given:
            out["first_name"] = given
            out["full_name"] = _normalize_spaces(f"{given} {surname}".strip())

    for l in lines:
        md = RE_DOCNO_DIGITS.search(l.replace("<", " "))
        if md and "document_number" not in out:
            out["document_number"] = md.group(1)

        # YYMMDD present somewhere
        m_yy = re.search(r"\b(\d{6})\b", l.replace("<", " "))
        if m_yy and "date_of_birth" not in out:
            yy, mm, dd = m_yy.group(1)[:2], m_yy.group(1)[2:4], m_yy.group(1)[4:6]
            yy_i = int(yy)
            year = 1900 + yy_i if yy_i >= 30 else 2000 + yy_i
            if 1 <= int(mm) <= 12 and 1 <= int(dd) <= 31:
                out["date_of_birth"] = f"{year:04d}-{int(mm):02d}-{int(dd):02d}"

    return out


def _resize_limit(img: Image.Image, max_side: int = MAX_SIDE) -> Image.Image:
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    m = max(w, h)
    if m <= max_side:
        return img
    scale = max_side / float(m)
    nw, nh = int(w * scale), int(h * scale)
    return img.resize((nw, nh), Image.Resampling.LANCZOS)


def _preprocess_fast(img: Image.Image) -> Tuple[Image.Image, Image.Image]:
    base = _resize_limit(img)
    gray = ImageOps.grayscale(base)
    c1 = ImageEnhance.Contrast(gray).enhance(1.6)
    s1 = c1.filter(ImageFilter.UnsharpMask(radius=2, percent=180, threshold=3))
    return gray, s1


def _preprocess_mrz_crop(img: Image.Image) -> Image.Image:
    base = _resize_limit(img)
    w, h = base.size
    crop = base.crop((0, int(h * 0.62), w, h))  # bottom ~38%
    gray = ImageOps.grayscale(crop)
    c1 = ImageEnhance.Contrast(gray).enhance(1.8)
    s1 = c1.filter(ImageFilter.UnsharpMask(radius=2, percent=200, threshold=3))
    bw = s1.point(lambda p: 255 if p > 160 else 0)
    return bw


def _ocr_string(img: Image.Image, lang: str, psm: int) -> str:
    cfg = f"--oem 1 --psm {psm}"
    return (pytesseract.image_to_string(img, lang=lang, config=cfg) or "").strip()


def _ocr_confidence_quick(img: Image.Image, lang: str, psm: int) -> Tuple[str, float]:
    txt = _ocr_string(img, lang=lang, psm=psm)
    if not txt:
        return "", 0.0

    cfg = f"--oem 1 --psm {psm}"
    data = pytesseract.image_to_data(img, lang=lang, config=cfg, output_type=pytesseract.Output.DICT)

    words = data.get("text", []) or []
    confs = data.get("conf", []) or []
    vals = []
    for w, c in zip(words, confs):
        if not w or not str(w).strip():
            continue
        try:
            ci = float(c)
        except Exception:
            continue
        if ci >= 0:
            vals.append(ci)

    avg_conf = (sum(vals) / max(len(vals), 1)) if vals else 0.0
    return txt, float(avg_conf)


# ----------------------------
# Field extraction
# ----------------------------

def _guess_fields_from_text(text: str) -> Dict[str, Any]:
    fields: Dict[str, Any] = {"raw_text": text}
    t = text

    # --- DOB: first try anchored label (avoid grabbing issue/expiry dates) ---
    dob = _extract_date_after_label(t, LABEL_DOB)
    if dob:
        fields["date_of_birth"] = dob

    # fallback patterns if not found
    if "date_of_birth" not in fields:
        m = RE_DOB_1.search(t) or RE_DOB_2.search(t)
        if m:
            dob_raw = m.group(1)
            dob_raw = re.sub(r"\s+", "", dob_raw).replace(".", "/").replace("-", "/")
            parts = dob_raw.split("/")
            if len(parts) == 3:
                dd, mm, yyyy = parts
                if len(yyyy) == 4:
                    fields["date_of_birth"] = f"{yyyy}-{int(mm):02d}-{int(dd):02d}"
        else:
            m3 = RE_DOB_3.search(t)
            if m3:
                dd, mm, yyyy = m3.group(1), m3.group(2), m3.group(3)
                fields["date_of_birth"] = f"{yyyy}-{int(mm):02d}-{int(dd):02d}"

    # --- DOCUMENT NUMBER ---
    # 1) card number label (useful for Mali)
    card = _extract_token_after_label(t, LABEL_CARDNO, token_re=r"[A-Z0-9]{6,15}")
    if card:
        fields["document_number"] = card

    # 2) smart "Document No" extraction (fix DEXPIR bug)
    if "document_number" not in fields:
        docno = _extract_docno_smart(t)
        if docno:
            fields["document_number"] = docno

    # 3) fallback regex
    if "document_number" not in fields:
        m_al = RE_DOCNO_ALNUM.search(t.replace(" ", "").upper())
        if m_al:
            tok = m_al.group(1).strip().upper()
            if tok not in DOCNO_STOPWORDS and "EXPIR" not in tok:
                fields["document_number"] = tok

    # 4) last resort digits anywhere
    if "document_number" not in fields:
        m_digits = RE_DOCNO_DIGITS.search(t.translate(_NUM_FIX))
        if m_digits:
            fields["document_number"] = m_digits.group(1)

    # --- LAST NAME / FIRST NAME(S) ---
    if "last_name" not in fields:
        m_nom = RE_NOM.search(t)
        if m_nom:
            fields["last_name"] = _clean_name(m_nom.group(1))
        else:
            nxt = _after_label_line(t, LABEL_NOM)
            if nxt:
                fields["last_name"] = _best_name_from_line(nxt)

    if "first_name" not in fields:
        m_pre = RE_PRENOMS.search(t)
        if m_pre:
            fields["first_name"] = _clean_name(m_pre.group(1))
        else:
            nxt = _after_label_line(t, LABEL_PRENOM)
            if nxt:
                # keep commas for multiple first names
                cleaned = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'\- ,]+", " ", nxt)
                fields["first_name"] = _normalize_spaces(cleaned).upper()

    if fields.get("first_name") and fields.get("last_name"):
        fields["full_name"] = _normalize_spaces(f"{fields['first_name']} {fields['last_name']}")

    # Final cleanup
    for k in ("first_name", "last_name"):
        v = fields.get(k)
        if isinstance(v, str):
            v2 = _clean_name(v)
            if len(v2) < 2 or v2 in {"R", "RR", "II"}:
                fields.pop(k, None)
            else:
                fields[k] = v2

    return fields


# ----------------------------
# Public API
# ----------------------------

@dataclass
class OCRResult:
    fields: Dict[str, Any]
    confidence: float


def ocr_to_prefill(fields: dict) -> dict:
    prefill: Dict[str, Any] = {}
    if fields.get("last_name"):
        prefill["nom"] = fields["last_name"]
    if fields.get("first_name"):
        prefill["prenom"] = fields["first_name"]
    if fields.get("date_of_birth"):
        prefill["dob"] = fields["date_of_birth"]
    if fields.get("document_number"):
        prefill["card_number"] = fields["document_number"]
    return prefill


def run_local_ocr(file_path: Path) -> OCRResult:
    img = Image.open(file_path)

    # 1) FAST PATH: MRZ crop first
    mrz_img = _preprocess_mrz_crop(img)
    mrz_txt = _ocr_string(mrz_img, lang=MRZ_LANG, psm=MRZ_PSM)
    mrz = _extract_mrz(mrz_txt)

    if mrz:
        mrz_fields = _parse_mrz_td1(mrz)
        minimal_fields: Dict[str, Any] = {"raw_text": mrz_txt, "mrz": mrz}
        for k in ("last_name", "first_name", "date_of_birth", "document_number", "full_name"):
            if mrz_fields.get(k):
                minimal_fields[k] = mrz_fields[k]

        essentials = sum(1 for k in ("last_name", "first_name", "date_of_birth", "document_number") if minimal_fields.get(k))
        confidence = min(0.99, 0.55 + 0.10 * essentials)
        return OCRResult(fields=minimal_fields, confidence=confidence)

    # 2) FALLBACK: lightweight full OCR
    gray, sharp = _preprocess_fast(img)

    t1, c1 = _ocr_confidence_quick(gray, lang=DEFAULT_LANG, psm=FAST_PSM)
    t2, c2 = _ocr_confidence_quick(sharp, lang=DEFAULT_LANG, psm=FAST_PSM)

    best_text, best_conf = (t1, c1) if (c1 > c2 or (abs(c1 - c2) < 1e-6 and len(t1) >= len(t2))) else (t2, c2)

    fields = _guess_fields_from_text(best_text)

    # Try MRZ extraction from best_text (rare but possible)
    mrz2 = _extract_mrz(best_text)
    if mrz2:
        fields["mrz"] = mrz2
        mrz_fields2 = _parse_mrz_td1(mrz2)
        for k in ("last_name", "first_name", "date_of_birth", "document_number", "full_name"):
            if mrz_fields2.get(k):
                fields[k] = mrz_fields2[k]

    conf01 = max(0.0, min(1.0, best_conf / 100.0))
    essentials = sum(1 for k in ("last_name", "first_name", "date_of_birth", "document_number") if fields.get(k))
    boost = 0.12 * essentials + (0.15 if fields.get("mrz") else 0.0)
    confidence = max(0.0, min(0.99, conf01 + boost))

    minimal_fields: Dict[str, Any] = {"raw_text": fields.get("raw_text", "")}
    for k in ("last_name", "first_name", "date_of_birth", "document_number", "full_name", "mrz"):
        if fields.get(k):
            minimal_fields[k] = fields[k]

    return OCRResult(fields=minimal_fields, confidence=confidence)
