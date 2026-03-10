# app/services/export_pdf_service.py
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Union
from uuid import UUID

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image,
    PageBreak,
)
from reportlab.pdfgen.canvas import Canvas

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.screening_db import (
    ScreeningRequest,
    ScreeningResult,
    ScreeningMatch,
    SourceRecord,
    Entity,
)

# -----------------------------------------------------------------------------
# Assets
# -----------------------------------------------------------------------------
ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
DEFAULT_LOGO_PATH = ASSETS_DIR / "simandou_screening_logo1.png"

# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------
SOURCE_FALLBACK = {1: "UN", 2: "OFAC", 3: "EU"}


def _safe_uuid(v: Union[str, UUID]) -> UUID:
    """Accepte str ou UUID, retourne toujours UUID."""
    if isinstance(v, UUID):
        return v
    try:
        return UUID(str(v))
    except Exception as exc:
        raise ValueError(f"Invalid UUID: {v!r}") from exc


def _as_text(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def _coalesce(*vals: Any, default: str = "-") -> str:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return default


def _normalize_band(band: Any) -> str:
    if band is None:
        return "-"
    v = str(band).upper().strip()
    if v in ("STRONG", "HIGH"):
        return "Forte"
    if v in ("MEDIUM", "MID"):
        return "Moyenne"
    if v in ("WEAK", "LOW"):
        return "Faible"
    return v or "-"


def _risk_badge(risk: str) -> tuple[str, colors.Color]:
    rr = (risk or "").upper().strip()
    if rr in ("HIGH", "H"):
        return "HIGH", colors.HexColor("#B91C1C")
    if rr in ("MEDIUM", "MID", "M"):
        return "MEDIUM", colors.HexColor("#B45309")
    if rr in ("LOW", "L"):
        return "LOW", colors.HexColor("#065F46")
    return (rr or "-"), colors.HexColor("#334155")


def _humanize_match_reasons(reasons: Any) -> list[str]:
    if reasons is None:
        return ["Correspondance détectée par le moteur."]
    if isinstance(reasons, str):
        s = reasons.strip()
        return [s] if s else ["Correspondance détectée par le moteur."]
    if isinstance(reasons, list):
        out = []
        for it in reasons[:30]:
            if it is None:
                continue
            s = str(it).strip()
            if s:
                out.append(s)
        return out[:12] or ["Correspondance détectée par le moteur."]
    if isinstance(reasons, dict):
        bullets: list[str] = []

        sim = reasons.get("trigram_similarity") or reasons.get("similarity")
        try:
            v = float(sim)
            pct = int(round((v * 100) if v <= 1 else v))
            bullets.append(f"Similarité nom (après normalisation) : {pct}%.")
        except Exception:
            pass

        tok = reasons.get("token_overlap")
        try:
            if tok is not None:
                bullets.append(f"Mots en commun (token overlap) : {int(tok)}.")
        except Exception:
            pass

        inp = reasons.get("input_normalized") or reasons.get("input")
        mat = reasons.get("matched_normalized") or reasons.get("matched") or reasons.get("primary_name")
        if inp and mat:
            bullets.append(f"Nom analysé : « {inp} » → trouvé : « {mat} ».")

        for k, label in [
            ("dob_match", "Date de naissance correspondante."),
            ("doc_match", "Numéro de document correspondant."),
            ("country_match", "Pays / nationalité correspondante."),
        ]:
            if reasons.get(k) is True:
                bullets.append(label)

        return bullets[:12] or ["Correspondance détectée par le moteur (détails disponibles)."]

    return ["Correspondance détectée par le moteur (détails disponibles)."]


def _wrapable(s: str, every: int = 48) -> str:
    if not s:
        return s
    out = []
    for tok in s.split(" "):
        if len(tok) <= every:
            out.append(tok)
            continue
        chunks = [tok[i: i + every] for i in range(0, len(tok), every)]
        out.append(" ".join(chunks))
    return " ".join(out)


def _safe_pre(s: str, limit: int = 1800) -> str:
    s = s or ""
    s = s.replace("\r", "")
    if len(s) > limit:
        s = s[:limit] + " …"
    return _wrapable(s)


def _extract_sanction_bullets(sr: SourceRecord | None) -> list[str]:
    if not sr:
        return []

    bullets: list[str] = []

    summary = getattr(sr, "summary", None)
    if isinstance(summary, str) and summary.strip():
        bullets.append(summary.strip())

    program = getattr(sr, "program", None)
    if program:
        bullets.append(f"Programme / régime : {program}")

    record_type = getattr(sr, "record_type", None)
    if record_type:
        bullets.append(f"Type d'enregistrement : {record_type}")

    listed_on = getattr(sr, "listed_on", None)
    if listed_on:
        bullets.append(f"Date d'inscription : {str(listed_on)}")

    unlisted_on = getattr(sr, "unlisted_on", None)
    if unlisted_on:
        bullets.append(f"Date de radiation : {str(unlisted_on)}")

    raw_payload = getattr(sr, "raw_payload", None)
    if isinstance(raw_payload, dict):
        for k in [
            "reason", "reasons", "grounds", "narrative", "narrative_summary",
            "remarks", "designation_reason", "listing_reason", "basis",
        ]:
            v = raw_payload.get(k)
            if isinstance(v, str) and v.strip():
                bullets.append(v.strip())
                break
            if isinstance(v, list) and v:
                vv = [str(x).strip() for x in v if x is not None and str(x).strip()]
                if vv:
                    bullets.append(" / ".join(vv[:3]))
                    break

    out = []
    seen = set()
    for b in bullets:
        key = b.strip().lower()
        if key and key not in seen:
            out.append(b.strip())
            seen.add(key)

    return out[:12]


def _extract_raw_excerpt(sr: SourceRecord | None) -> Any:
    if not sr:
        return None
    raw_payload = getattr(sr, "raw_payload", None)
    if isinstance(raw_payload, dict):
        keep_keys = [
            "source_code", "source_ref", "record_type", "program",
            "primary_name", "aliases", "nationality", "country",
            "dob", "birth_place", "identifiers",
            "reason", "reasons", "narrative_summary", "remarks", "summary",
        ]
        excerpt = {k: raw_payload.get(k) for k in keep_keys if k in raw_payload}
        if excerpt:
            return excerpt
        return {k: raw_payload.get(k) for k in list(raw_payload.keys())[:25]}
    return raw_payload


def _case_id_from_request_payload(req_payload: Any) -> str | None:
    if not isinstance(req_payload, dict):
        return None
    meta = req_payload.get("meta") or {}
    if isinstance(meta, dict):
        cid = meta.get("case_id")
        if cid and str(cid).lower() != "none":
            return str(cid)
    cid2 = req_payload.get("case_id")
    if cid2 and str(cid2).lower() != "none":
        return str(cid2)
    return None


def _best_effort(db: Session, fn: Callable[[], Any], default: Any) -> Any:
    """
    Exécute fn() dans un SAVEPOINT.
    Si ça échoue (RLS, table absente, cast…), rollback le savepoint
    sans casser la transaction principale.
    """
    try:
        with db.begin_nested():
            return fn()
    except Exception:
        return default


# -----------------------------------------------------------------------------
# ✅ FIX: _load_analyst_decisions est la source unique de vérité.
#    L'ancienne version "best_effort" inline dans build_screening_pdf est supprimée.
# -----------------------------------------------------------------------------
def _load_analyst_decisions(
    db: Session,
    *,
    request_id: str | None = None,
    case_id: str | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """
    Retourne (latest, history) depuis case_screening_decisions.
    - Cherche d'abord par request_id, puis fallback case_id.
    - Wrappé dans _best_effort pour ne jamais casser la transaction principale.
    """
    if not request_id and not case_id:
        return None, []

    def _rows_to_latest_history(rows) -> tuple[dict | None, list[dict]]:
        history = [dict(r) for r in rows]
        return (history[0] if history else None), history

    def _run() -> tuple[dict | None, list[dict]]:
        has_tbl = db.execute(
            text("SELECT to_regclass('public.case_screening_decisions')")
        ).scalar()
        if not has_tbl:
            return None, []

        # 1) par request_id
        if request_id:
            rows = db.execute(
                text("""
                    SELECT
                      decision, comment, decided_at,
                      decided_by_email,
                      decided_by_user_id::text AS decided_by_user_id,
                      request_id::text AS request_id,
                      case_id::text AS case_id
                    FROM public.case_screening_decisions
                    WHERE request_id = CAST(:rid AS uuid)
                    ORDER BY decided_at DESC
                    LIMIT 50
                """),
                {"rid": request_id},
            ).mappings().all()
            latest, history = _rows_to_latest_history(rows)
            if latest:
                return latest, history

        # 2) fallback par case_id
        if case_id:
            rows = db.execute(
                text("""
                    SELECT
                      decision, comment, decided_at,
                      decided_by_email,
                      decided_by_user_id::text AS decided_by_user_id,
                      request_id::text AS request_id,
                      case_id::text AS case_id
                    FROM public.case_screening_decisions
                    WHERE case_id = CAST(:cid AS uuid)
                    ORDER BY decided_at DESC
                    LIMIT 50
                """),
                {"cid": case_id},
            ).mappings().all()
            return _rows_to_latest_history(rows)

        return None, []

    return _best_effort(db, _run, (None, []))


# -----------------------------------------------------------------------------
# Header / Footer
# -----------------------------------------------------------------------------
def _header_footer(canvas: Canvas, doc, title: str) -> None:
    w, h = A4

    canvas.setStrokeColor(colors.HexColor("#CBD5E1"))
    canvas.setLineWidth(0.6)
    canvas.line(18 * mm, h - 18 * mm, w - 18 * mm, h - 18 * mm)

    canvas.setFont("Helvetica-Bold", 10)
    canvas.setFillColor(colors.HexColor("#0F172A"))
    canvas.drawString(18 * mm, h - 14 * mm, title)

    canvas.setStrokeColor(colors.HexColor("#E2E8F0"))
    canvas.setLineWidth(0.6)
    canvas.line(18 * mm, 14 * mm, w - 18 * mm, 14 * mm)

    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(colors.HexColor("#475569"))
    canvas.drawString(18 * mm, 9 * mm, "Confidentiel – Simandou Screening")

    page = canvas.getPageNumber()
    canvas.drawRightString(w - 18 * mm, 9 * mm, f"Page {page}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def build_screening_pdf(db: Session, request_id: Union[str, UUID]) -> bytes:
    """
    Génère le PDF de rapport pour un screening_request.

    Args:
        db:          Session SQLAlchemy avec tenant context posé (RLS actif).
        request_id:  str ou UUID — ID de screening_requests.id

    Raises:
        ValueError: si le screening n'existe pas (RLS ou UUID inconnu → 404 côté route).
    """
    # ✅ FIX: normalisation robuste str|UUID → UUID
    req_id = _safe_uuid(request_id)
    req_id_str = str(req_id)

    # ✅ FIX: one_or_none() + ValueError propre → la route attrape et retourne 404
    req = db.query(ScreeningRequest).filter(ScreeningRequest.id == req_id).one_or_none()
    if not req:
        raise ValueError(
            f"ScreeningRequest {req_id_str} introuvable "
            "(vérifiez que le tenant context est posé et que l'UUID est correct)"
        )

    res = db.query(ScreeningResult).filter(ScreeningResult.request_id == req_id).one_or_none()

    # matches
    matches = (
        db.execute(
            select(
                ScreeningMatch.id,
                ScreeningMatch.request_id,
                ScreeningMatch.entity_id,
                ScreeningMatch.source_record_id,
                ScreeningMatch.match_score,
                ScreeningMatch.match_band,
                ScreeningMatch.reasons,
                ScreeningMatch.created_at,
            )
            .where(ScreeningMatch.request_id == req_id)
            .order_by(ScreeningMatch.created_at.desc(), ScreeningMatch.id.asc())
            .limit(200)
        )
        .mappings()
        .all()
    )

    payload = getattr(req, "request_payload", {}) or {}
    if not isinstance(payload, dict):
        payload = {}

    # case_id: req.case_id > payload.case_id > payload.meta.case_id
    case_id = (
        _coalesce(
            getattr(req, "case_id", None),
            payload.get("case_id"),
            _case_id_from_request_payload(payload),
            default="",
        )
        or ""
    )

    # ✅ FIX: documents via _best_effort (SAVEPOINT) → jamais de crash si table absent
    if case_id:
        def _load_documents():
            rows = db.execute(
                text("""
                    SELECT
                      d.id::text AS id,
                      d.case_id::text AS case_id,
                      d.doc_type::text AS doc_type,
                      d.uploaded_at AS uploaded_at,
                      d.ocr_status::text AS ocr_status,
                      d.ocr_confidence AS ocr_confidence,
                      d.original_filename AS original_filename,
                      d.object_key AS object_key,
                      d.mime_type AS mime,
                      d.extracted_fields AS extracted_fields
                    FROM documents d
                    WHERE d.case_id = CAST(:cid AS uuid)
                    ORDER BY d.uploaded_at DESC
                    LIMIT 50
                """),
                {"cid": case_id},
            ).mappings().all()
            return [dict(r) for r in rows]

        docs = _best_effort(db, _load_documents, [])
        if docs:
            payload["documents"] = docs

    # ✅ FIX: utilise _load_analyst_decisions (module-level) — plus de copie inline
    latest_decision, decision_history = _load_analyst_decisions(
        db,
        request_id=req_id_str,
        case_id=case_id or None,
    )

    # bulk enrich (entities + source records)
    entity_ids = list({r["entity_id"] for r in matches if r.get("entity_id")})
    sr_ids = list({r["source_record_id"] for r in matches if r.get("source_record_id")})

    entities_by_id: dict[str, Entity] = {}
    if entity_ids:
        ents = db.execute(select(Entity).where(Entity.id.in_(entity_ids))).scalars().all()
        entities_by_id = {str(e.id): e for e in ents}

    source_records_by_id: dict[str, SourceRecord] = {}
    if sr_ids:
        srs = db.execute(select(SourceRecord).where(SourceRecord.id.in_(sr_ids))).scalars().all()
        source_records_by_id = {str(s.id): s for s in srs}

    # ✅ FIX: sources map via _best_effort — jamais de crash si table absente
    def _load_sources_map() -> dict[int, dict[str, str | None]]:
        has_sources = db.execute(text("SELECT to_regclass('public.sources')")).scalar()
        if not has_sources:
            return {}
        rows = db.execute(
            text("""
                SELECT id::int AS id,
                       COALESCE(code::text, '') AS code,
                       COALESCE(name::text, '') AS name
                FROM sources
            """)
        ).mappings().all()
        out: dict[int, dict[str, str | None]] = {}
        for r in rows:
            sid = int(r["id"])
            code = (r.get("code") or "").strip() or SOURCE_FALLBACK.get(sid, f"SOURCE_{sid}")
            name = (r.get("name") or "").strip() or None
            out[sid] = {"code": code, "name": name}
        return out

    sources_map: dict[int, dict[str, str | None]] = _best_effort(db, _load_sources_map, {})

    # identity
    full_name = _coalesce(
        payload.get("override_name"),
        payload.get("name"),
        payload.get("full_name"),
        payload.get("company_name"),
        default="-",
    )
    entity_type = _coalesce(payload.get("entity_type"), payload.get("kind"), default="-")
    client_id = _coalesce(getattr(req, "client_id", None), payload.get("client_id"), default="-")

    # décision moteur
    risk_level = getattr(res, "risk_level", None) if res else None
    confidence = getattr(res, "confidence", None) if res else None
    action = getattr(res, "recommended_action", None) if res else None
    decided_by = getattr(res, "decided_by", None) if res else None
    notes = getattr(res, "notes", None) if res else None
    risk_txt, risk_color = _risk_badge(_as_text(risk_level))

    # --------------------------------------------------------------------------
    # Styles
    # --------------------------------------------------------------------------
    styles = getSampleStyleSheet()
    H1 = ParagraphStyle(
        "H1", parent=styles["Heading1"],
        fontName="Helvetica-Bold", fontSize=16, leading=20,
        textColor=colors.HexColor("#0F172A"), spaceAfter=8,
    )
    H2 = ParagraphStyle(
        "H2", parent=styles["Heading2"],
        fontName="Helvetica-Bold", fontSize=12, leading=14,
        textColor=colors.HexColor("#0F172A"), spaceBefore=10, spaceAfter=6,
    )
    P = ParagraphStyle(
        "P", parent=styles["BodyText"],
        fontName="Helvetica", fontSize=10, leading=13,
        textColor=colors.HexColor("#0F172A"),
    )
    SMALL = ParagraphStyle("SMALL", parent=P, fontSize=9, leading=12, textColor=colors.HexColor("#334155"))
    MUTED = ParagraphStyle("MUTED", parent=P, fontSize=9, leading=12, textColor=colors.HexColor("#64748B"))

    CARD_BG    = colors.HexColor("#111827")
    CARD_BG_2  = colors.HexColor("#0B1220")
    CARD_BORDER= colors.HexColor("#334155")
    CARD_TEXT  = colors.white
    CARD_MUTED = colors.HexColor("#C7D2FE")

    CARD_H   = ParagraphStyle("CARD_H",   parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=14, textColor=CARD_TEXT, spaceAfter=2)
    CARD_SUB = ParagraphStyle("CARD_SUB", parent=P, fontSize=9, leading=12, textColor=colors.HexColor("#E5E7EB"))
    CARD_TXT = ParagraphStyle("CARD_TXT", parent=P, fontSize=9, leading=12, textColor=colors.HexColor("#F3F4F6"))
    CARD_SEC = ParagraphStyle("CARD_SEC", parent=P, fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=CARD_MUTED, spaceAfter=2)

    # --------------------------------------------------------------------------
    # Document
    # --------------------------------------------------------------------------
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=22 * mm,  bottomMargin=18 * mm,
        title="Rapport de Screening", author="Simandou Screening",
    )

    story: list[Any] = []

    # Logo
    if DEFAULT_LOGO_PATH.exists():
        try:
            logo = Image(str(DEFAULT_LOGO_PATH))
            target_w = 48 * mm
            iw, ih = float(logo.imageWidth), float(logo.imageHeight)
            ratio = (ih / iw) if iw else 0.3
            logo.drawWidth = target_w
            logo.drawHeight = target_w * ratio
            lt = Table([[logo]], colWidths=[doc.width])
            lt.setStyle(TableStyle([
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("BOTTOMPADDING", (0, 0), (0, 0), 4),
            ]))
            story.append(lt)
        except Exception:
            pass

    story.append(Paragraph("Rapport de Screening", H1))
    story.append(Paragraph(f"<b>Request ID:</b> {req_id_str} &nbsp;&nbsp; <b>Client ID:</b> {client_id}", MUTED))
    if case_id:
        story.append(Paragraph(f"<b>Case ID:</b> {case_id}", MUTED))
    story.append(Spacer(1, 6 * mm))

    # --------------------------------------------------------------------------
    # Identité
    # --------------------------------------------------------------------------
    identity_rows = [
        [Paragraph("<b>Identité screenée</b>", H2), ""],
        [Paragraph("<b>Nom / Raison sociale</b>", SMALL), Paragraph(_as_text(full_name) or "-", P)],
        [Paragraph("<b>Type</b>", SMALL), Paragraph(_as_text(entity_type) or "-", P)],
    ]
    t = Table(identity_rows, colWidths=[48 * mm, 120 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
        ("SPAN", (0, 0), (1, 0)),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 1), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(t)
    story.append(Spacer(1, 6 * mm))

    # --------------------------------------------------------------------------
    # Décision moteur
    # --------------------------------------------------------------------------
    story.append(Paragraph("Décision (moteur)", H2))
    story.append(Paragraph(f"Risque : <font color='{risk_color.hexval()}'><b>{risk_txt}</b></font>", P))
    story.append(Paragraph(f"Confiance : <b>{_as_text(confidence) if confidence is not None else '-'}</b>", P))
    story.append(Paragraph(f"Action recommandée : <b>{_as_text(action) or '-'}</b>", P))
    story.append(Paragraph(f"Décidé par : <b>{_as_text(decided_by) or '-'}</b>", P))
    if notes:
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(f"<b>Notes :</b> {_as_text(notes)}", P))

    # --------------------------------------------------------------------------
    # Décision analyst
    # --------------------------------------------------------------------------
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Décision analyst (Bypass)", H2))

    if latest_decision:
        story.append(Paragraph(f"Décision : <b>{_as_text(latest_decision.get('decision'))}</b>", P))
        story.append(Paragraph(f"Pris par : <b>{_as_text(latest_decision.get('decided_by_email'))}</b>", P))
        story.append(Paragraph(f"Le : <b>{_as_text(latest_decision.get('decided_at'))}</b>", P))
        cmt = _as_text(latest_decision.get("comment"))
        story.append(Paragraph(f"Raison : {cmt if cmt else '-'}", P))
    else:
        story.append(Paragraph("Aucune décision analyst enregistrée.", P))

    # --------------------------------------------------------------------------
    # Historique
    # --------------------------------------------------------------------------
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("Historique des actions", H2))

    created_at   = getattr(req, "created_at", None)
    completed_at = getattr(req, "completed_at", None)
    provider     = _coalesce(getattr(req, "provider", None), payload.get("provider"), default="-")
    status       = _coalesce(getattr(req, "status", None), payload.get("status"), default="-")

    events: list[tuple[str, str]] = [
        ("Screening créé", _as_text(created_at) or "-"),
        ("Provider", provider),
        ("Statut", status),
    ]
    if completed_at:
        events.append(("Screening terminé", _as_text(completed_at)))

    docs_list = payload.get("documents") if isinstance(payload.get("documents"), list) else []
    if docs_list:
        d0 = docs_list[0] if isinstance(docs_list[0], dict) else None
        if d0:
            events.append(("Document upload",  _coalesce(d0.get("uploaded_at"), d0.get("created_at"), default="-")))
            events.append(("OCR status",        _coalesce(d0.get("ocr_status"), default="-")))
            events.append(("OCR confidence",    _coalesce(d0.get("ocr_confidence"), default="-")))

    if latest_decision:
        events.append((
            "Décision analyst",
            f"{_as_text(latest_decision.get('decision'))} — {_as_text(latest_decision.get('decided_at'))}",
        ))

    hist_rows = [[Paragraph("<b>Action</b>", SMALL), Paragraph("<b>Détail</b>", SMALL)]]
    for a, d in events[:20]:
        hist_rows.append([Paragraph(_as_text(a), SMALL), Paragraph(_safe_pre(_as_text(d), 300), SMALL)])

    tbl = Table(hist_rows, colWidths=[50 * mm, 118 * mm])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tbl)

    # --------------------------------------------------------------------------
    # Correspondances (résumé)
    # --------------------------------------------------------------------------
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("Correspondances trouvées", H2))

    header = [
        Paragraph("<b>#</b>", SMALL),
        Paragraph("<b>Nom</b>", SMALL),
        Paragraph("<b>Catégorie</b>", SMALL),
        Paragraph("<b>Réf</b>", SMALL),
        Paragraph("<b>Programme</b>", SMALL),
        Paragraph("<b>Score</b>", SMALL),
    ]
    match_rows = [header]

    top = sorted(matches, key=lambda r: float(r.get("match_score") or 0), reverse=True)[:50]

    if not top:
        match_rows.append([
            Paragraph("-", SMALL),
            Paragraph("Aucune correspondance", SMALL),
            Paragraph("-", SMALL), Paragraph("-", SMALL),
            Paragraph("-", SMALL), Paragraph("-", SMALL),
        ])
    else:
        for i, r in enumerate(top, start=1):
            ent = entities_by_id.get(str(r.get("entity_id") or ""))
            sr  = source_records_by_id.get(str(r.get("source_record_id") or "")) if r.get("source_record_id") else None
            band    = _normalize_band(r.get("match_band"))
            ref     = _coalesce(getattr(sr, "source_ref", None), default="-")
            program = _coalesce(getattr(sr, "program", None), default="-")
            score   = int(float(r.get("match_score") or 0))
            match_rows.append([
                Paragraph(str(i), SMALL),
                Paragraph(_coalesce(getattr(ent, "primary_name", None), default="-"), SMALL),
                Paragraph(band, SMALL),
                Paragraph(ref, SMALL),
                Paragraph(program, SMALL),
                Paragraph(f"{score}%", SMALL),
            ])

    tm = Table(match_rows, colWidths=[8 * mm, 42 * mm, 22 * mm, 30 * mm, 42 * mm, 16 * mm])
    tm.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(tm)

    # --------------------------------------------------------------------------
    # Détails cards (seulement si matches)
    # --------------------------------------------------------------------------
    if top:
        story.append(PageBreak())
        story.append(Paragraph("Détails des correspondances (sanctions / décisions)", H1))
        story.append(Spacer(1, 3 * mm))

        for idx, r in enumerate(top[:30], start=1):
            ent = entities_by_id.get(str(r.get("entity_id") or ""))
            sr  = source_records_by_id.get(str(r.get("source_record_id") or "")) if r.get("source_record_id") else None

            score       = int(float(r.get("match_score") or 0))
            band        = _normalize_band(r.get("match_band"))
            ref         = _coalesce(getattr(sr, "source_ref", None), default="-")
            program     = _coalesce(getattr(sr, "program", None), default="-")
            record_type = _coalesce(getattr(sr, "record_type", None), default="-")
            listed_on   = _coalesce(getattr(sr, "listed_on", None), default="-")
            summary_sr  = _coalesce(getattr(sr, "summary", None), default="-")

            sid      = int(getattr(sr, "source_id", 0) or 0) if sr else 0
            src_code = sources_map.get(sid, {}).get("code") if sid else (SOURCE_FALLBACK.get(sid) if sid else None)
            src_name = sources_map.get(sid, {}).get("name") if sid else None
            src_label = _coalesce(src_name, src_code, default="-")

            sanction_bullets = _extract_sanction_bullets(sr)
            tech_bullets     = _humanize_match_reasons(r.get("reasons"))

            links = getattr(sr, "evidence_urls", None) if sr else None
            links = links if isinstance(links, list) else ([] if links is None else [links])
            links = [str(x).strip() for x in links if x and str(x).strip()]

            raw_excerpt = _extract_raw_excerpt(sr)

            title_name  = _coalesce(getattr(ent, "primary_name", None), default="(Nom indisponible)")
            subtitle    = f"Catégorie : {band} · Réf : {ref} · Programme : {program}"
            score_badge = Paragraph(
                f"<b>Score : {score}%</b>",
                ParagraphStyle("SCORE", parent=CARD_TXT, textColor=colors.HexColor("#FCA5A5")),
            )

            header_tbl = Table(
                [[Paragraph(title_name.upper(), CARD_H), score_badge]],
                colWidths=[doc.width - 28 * mm, 28 * mm],
            )
            header_tbl.setStyle(TableStyle([
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN",         (1, 0), (1, 0),   "RIGHT"),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
                ("TOPPADDING",    (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("BACKGROUND",    (0, 0), (-1, -1), CARD_BG),
            ]))

            body: list[Any] = [
                header_tbl,
                Paragraph(subtitle, CARD_SUB),
                Spacer(1, 3 * mm),
                Paragraph("MOTIFS / RAISONS (SANCTION / DÉCISION)", CARD_SEC),
            ]
            if sanction_bullets:
                for b in sanction_bullets:
                    body.append(Paragraph(f"• {b}", CARD_TXT))
            else:
                body.append(Paragraph("• (Aucun motif détaillé disponible)", CARD_TXT))

            body += [
                Spacer(1, 3 * mm),
                Paragraph("SOURCE OFFICIELLE", CARD_SEC),
                Paragraph(f"<b>Source :</b> {src_label}", CARD_TXT),
                Paragraph(f"<b>Type :</b> {record_type}", CARD_TXT),
                Paragraph(f"<b>Inscrit le :</b> {listed_on}", CARD_TXT),
            ]
            if summary_sr and summary_sr != "-":
                body.append(Paragraph(f"<b>Résumé :</b> {summary_sr}", CARD_TXT))

            if links:
                body.append(Paragraph("<b>Liens (preuves) :</b>", CARD_TXT))
                for url in links[:8]:
                    body.append(Paragraph(f"• <link href='{url}' color='#93C5FD'>{url}</link>", CARD_TXT))
            else:
                body.append(Paragraph("<b>Liens (preuves) :</b> -", CARD_TXT))

            body += [
                Spacer(1, 3 * mm),
                Paragraph("POURQUOI CE MATCH (TECHNIQUE)", CARD_SEC),
            ]
            for b in (tech_bullets or ["Correspondance détectée par le moteur."]):
                body.append(Paragraph(f"• {b}", CARD_TXT))

            if raw_excerpt is not None:
                body += [
                    Spacer(1, 2 * mm),
                    Paragraph("DÉTAILS BRUTS (SOURCE / SANCTION)", CARD_SEC),
                    Paragraph(_safe_pre(_as_text(raw_excerpt), limit=1200).replace("\n", "<br/>"), CARD_TXT),
                ]

            card_tbl = Table([[body]], colWidths=[doc.width])
            card_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), CARD_BG_2),
                ("BOX",           (0, 0), (-1, -1), 1.0, CARD_BORDER),
                ("LEFTPADDING",   (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
                ("TOPPADDING",    (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))

            story.append(card_tbl)
            story.append(Spacer(1, 5 * mm))

    title = "Rapport de Screening"
    doc.build(
        story,
        onFirstPage=lambda canv, d: _header_footer(canv, d, title),
        onLaterPages=lambda canv, d: _header_footer(canv, d, title),
    )
    return buf.getvalue()