# app/services/export_pdf_service.py
# ─────────────────────────────────────────────────────────────
# PROFESSIONAL PDF EXPORT — Simandou Screening
# ✅ FIX: SQL raw au lieu d'ORM pour éviter les 404 sur HIGH RISK
# ─────────────────────────────────────────────────────────────
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Union
from uuid import UUID

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, HRFlowable, KeepTogether,
)
from reportlab.pdfgen.canvas import Canvas

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.core.db import set_tenant_context

from app.models.screening_db import (
    ScreeningMatch, SourceRecord, Entity,
)

# ─── Constants ────────────────────────────────────────────────
ASSETS_DIR        = Path(__file__).resolve().parents[1] / "assets"
DEFAULT_LOGO_PATH = ASSETS_DIR / "simandou_screening_logo1.png"
SOURCE_FALLBACK   = {1: "UN", 2: "OFAC", 3: "EU"}
PAGE_W, PAGE_H    = A4
MARGIN            = 18 * mm
CONTENT_W         = PAGE_W - MARGIN * 2

# ─── Brand colors ─────────────────────────────────────────────
C_DARK    = colors.HexColor("#0A1628")
C_NAVY    = colors.HexColor("#0D1E35")
C_BLUE    = colors.HexColor("#2D7FD6")
C_BLUE_LT = colors.HexColor("#EBF4FD")
C_WHITE   = colors.white
C_GRAY_DK = colors.HexColor("#1E293B")
C_GRAY_MD = colors.HexColor("#475569")
C_GRAY_LT = colors.HexColor("#E2E8F0")
C_GRAY_XL = colors.HexColor("#F8FAFC")
C_RED     = colors.HexColor("#DC2626")
C_ORANGE  = colors.HexColor("#D97706")
C_GREEN   = colors.HexColor("#059669")
C_RED_BG  = colors.HexColor("#FEF2F2")
C_ORG_BG  = colors.HexColor("#FFFBEB")
C_GRN_BG  = colors.HexColor("#F0FDF4")
C_BORDER  = colors.HexColor("#CBD5E1")


# ─── Helpers ──────────────────────────────────────────────────
def _safe_uuid(v: Union[str, UUID]) -> UUID:
    if isinstance(v, UUID):
        return v
    try:
        return UUID(str(v))
    except Exception as e:
        raise ValueError(f"Invalid UUID: {v!r}") from e


def _as_text(v: Any) -> str:
    return "" if v is None else str(v)


def _coalesce(*vals: Any, default: str = "-") -> str:
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return default


def _normalize_band(band: Any) -> str:
    v = str(band or "").upper().strip()
    if v in ("STRONG", "HIGH"):
        return "Forte"
    if v in ("MEDIUM", "MID"):
        return "Moyenne"
    if v in ("WEAK", "LOW"):
        return "Faible"
    return v or "-"


def _risk_style(risk: str) -> tuple:
    r = str(risk or "").upper()
    if r == "HIGH":
        return C_RED, C_RED_BG, "⚠ ÉLEVÉ"
    if r == "MEDIUM":
        return C_ORANGE, C_ORG_BG, "◆ MOYEN"
    if r == "LOW":
        return C_GREEN, C_GRN_BG, "✓ FAIBLE"
    return C_GRAY_MD, C_GRAY_XL, str(risk or "—")


def _action_style(action: str) -> tuple:
    v = str(action or "").upper()
    if v == "PASS":
        return C_GREEN, "✓ APPROUVER"
    if v == "MANUAL_REVIEW":
        return C_ORANGE, "◆ REVUE MANUELLE"
    if v == "BLOCK":
        return C_RED, "✗ BLOQUER"
    return C_GRAY_MD, str(action or "—")


def _humanize_reasons(reasons: Any) -> list[str]:
    if reasons is None:
        return ["Correspondance détectée par le moteur."]
    if isinstance(reasons, str):
        return [reasons.strip()] if reasons.strip() else ["Correspondance détectée par le moteur."]
    if isinstance(reasons, list):
        out = [str(it).strip() for it in reasons[:20] if it and str(it).strip()]
        return out[:10] or ["Correspondance détectée par le moteur."]
    if isinstance(reasons, dict):
        bullets: list[str] = []
        sim = reasons.get("trigram_similarity") or reasons.get("similarity")
        try:
            v = float(sim)
            pct = int(round(v * 100 if v <= 1 else v))
            bullets.append(f"Similarité nom : {pct}%")
        except Exception:
            pass
        inp = reasons.get("input_normalized") or reasons.get("input")
        mat = reasons.get("matched_normalized") or reasons.get("primary_name")
        if inp and mat:
            bullets.append(f"Nom analysé : «{inp}» → trouvé : «{mat}»")
        for k, label in [
            ("dob_match",     "Date de naissance ✓"),
            ("doc_match",     "N° document ✓"),
            ("country_match", "Pays ✓"),
        ]:
            if reasons.get(k):
                bullets.append(label)
        return bullets[:8] or ["Correspondance détectée par le moteur."]
    return ["Correspondance détectée par le moteur."]


def _sanction_bullets(sr: SourceRecord | None) -> list[str]:
    if not sr:
        return []
    bullets: list[str] = []
    for attr in ("summary", "program", "record_type"):
        v = getattr(sr, attr, None)
        if v:
            bullets.append(f"{attr.replace('_', ' ').title()} : {v}")
    lo = getattr(sr, "listed_on", None)
    if lo:
        bullets.append(f"Inscrit le : {lo}")
    ul = getattr(sr, "unlisted_on", None)
    if ul:
        bullets.append(f"Retiré le : {ul}")
    raw = getattr(sr, "raw_payload", None)
    if isinstance(raw, dict):
        for k in ("reason", "reasons", "grounds", "narrative_summary", "remarks"):
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                bullets.append(v.strip())
                break
            if isinstance(v, list) and v:
                s = " / ".join(str(x).strip() for x in v[:3] if x)
                if s:
                    bullets.append(s)
                    break
    seen: set[str] = set()
    out: list[str] = []
    for b in bullets:
        if b.lower() not in seen:
            out.append(b)
            seen.add(b.lower())
    return out[:8]


def _best_effort(db: Session, fn: Callable, default: Any) -> Any:
    try:
        with db.begin_nested():
            return fn()
    except Exception:
        return default


def _case_id_from_payload(p: Any) -> str | None:
    if not isinstance(p, dict):
        return None
    meta = p.get("meta") or {}
    if isinstance(meta, dict):
        c = meta.get("case_id")
        if c and str(c).lower() != "none":
            return str(c)
    c2 = p.get("case_id")
    if c2 and str(c2).lower() != "none":
        return str(c2)
    return None


def _load_analyst_decisions(
    db: Session,
    *,
    request_id: str | None = None,
    case_id: str | None = None,
) -> tuple[dict | None, list[dict]]:
    if not request_id and not case_id:
        return None, []

    def _rows(rows: Any) -> tuple[dict | None, list[dict]]:
        h = [dict(r) for r in rows]
        return (h[0] if h else None), h

    def _run() -> tuple[dict | None, list[dict]]:
        has = db.execute(
            text("SELECT to_regclass('public.case_screening_decisions')")
        ).scalar()
        if not has:
            return None, []

        Q = """
            SELECT decision, comment, decided_at, decided_by_email,
                   decided_by_user_id::text, request_id::text, case_id::text
            FROM public.case_screening_decisions
            WHERE {col} = CAST(:{p} AS uuid)
            ORDER BY decided_at DESC LIMIT 50
        """

        if request_id:
            rows = db.execute(
                text(Q.format(col="request_id", p="rid")), {"rid": request_id}
            ).mappings().all()
            l, h = _rows(rows)
            if l:
                return l, h

        if case_id:
            rows = db.execute(
                text(Q.format(col="case_id", p="cid")), {"cid": case_id}
            ).mappings().all()
            return _rows(rows)

        return None, []

    return _best_effort(db, _run, (None, []))


# ─── Styles ───────────────────────────────────────────────────
def _build_styles() -> dict:
    S = getSampleStyleSheet()

    def ps(name: str, **kw: Any) -> ParagraphStyle:
        return ParagraphStyle(name, parent=S["Normal"], **kw)

    return {
        "title": ps("pdf_title",
            fontName="Helvetica-Bold", fontSize=20, leading=24,
            textColor=C_DARK, spaceAfter=4, alignment=TA_LEFT),
        "section_header": ps("pdf_section_header",
            fontName="Helvetica-Bold", fontSize=8, leading=10,
            textColor=C_WHITE, alignment=TA_LEFT),
        "label": ps("pdf_label",
            fontName="Helvetica-Bold", fontSize=8, leading=11,
            textColor=C_GRAY_MD),
        "value": ps("pdf_value",
            fontName="Helvetica", fontSize=10, leading=13,
            textColor=C_DARK),
        "body": ps("pdf_body",
            fontName="Helvetica", fontSize=9, leading=13,
            textColor=C_GRAY_DK),
        "small": ps("pdf_small",
            fontName="Helvetica", fontSize=8, leading=11,
            textColor=C_GRAY_MD),
        "bullet": ps("pdf_bullet",
            fontName="Helvetica", fontSize=9, leading=13,
            textColor=C_GRAY_DK, leftIndent=10),
    }


# ─── Canvas header/footer ─────────────────────────────────────
def _make_header_footer(title: str, report_id: str, tenant: str = "Simandou Screening"):
    def draw(canvas: Canvas, doc: Any) -> None:
        w, h = A4
        # Header
        canvas.setFillColor(C_NAVY)
        canvas.rect(0, h - 12 * mm, w, 12 * mm, fill=1, stroke=0)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.setFillColor(C_WHITE)
        canvas.drawString(MARGIN, h - 7.5 * mm, title)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#94A3B8"))
        canvas.drawRightString(w - MARGIN, h - 7.5 * mm, f"Réf: {report_id[:16]}…")
        # Footer
        canvas.setFillColor(C_GRAY_XL)
        canvas.rect(0, 0, w, 10 * mm, fill=1, stroke=0)
        canvas.setStrokeColor(C_BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, 10 * mm, w - MARGIN, 10 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(C_GRAY_MD)
        canvas.drawString(MARGIN, 3.5 * mm, f"CONFIDENTIEL — {tenant} — Document généré automatiquement")
        canvas.setFillColor(C_BLUE)
        canvas.drawRightString(w - MARGIN, 3.5 * mm, f"Page {canvas.getPageNumber()}")

    return draw


# ─── Table builders ───────────────────────────────────────────
def _section_header_table(title: str, ST: dict) -> Table:
    t = Table([[Paragraph(title.upper(), ST["section_header"])]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), C_NAVY),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _two_col_table(rows: list[tuple[str, str]], ST: dict) -> Table:
    data = [[Paragraph(k, ST["label"]), Paragraph(v, ST["value"])] for k, v in rows]
    t = Table(data, colWidths=[42 * mm, CONTENT_W - 42 * mm])
    t.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW",     (0, 0), (-1, -2), 0.4, C_GRAY_LT),
    ]))
    return t


def _kpi_row(kpis: list[dict], ST: dict) -> Table:
    cells = []
    for kpi in kpis:
        col = kpi["color"]
        cells.append([
            Paragraph(
                kpi["label"].upper(),
                ParagraphStyle(f"kl_{kpi['label']}", fontName="Helvetica", fontSize=7,
                               textColor=col, leading=9),
            ),
            Paragraph(
                kpi["value"],
                ParagraphStyle(f"kv_{kpi['label']}", fontName="Helvetica-Bold", fontSize=16,
                               textColor=col, leading=18),
            ),
        ])
    col_w = CONTENT_W / len(kpis)
    t = Table([cells], colWidths=[col_w] * len(kpis))
    t.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("BOX",           (0, 0), (-1, -1), 0.5, C_BORDER),
        ("LINEAFTER",     (0, 0), (-2, -1), 0.5, C_BORDER),
        ("BACKGROUND",    (0, 0), (-1, -1), C_GRAY_XL),
    ]))
    return t


# ─── Main ─────────────────────────────────────────────────────
def build_screening_pdf(db: Session, request_id: Union[str, UUID],tenant_id: str | None = None) -> bytes:
    if tenant_id:
        set_tenant_context(db, tenant_id)

    req_id = _safe_uuid(request_id)
    req_id_str = str(req_id)

    # 🔑 important : reposer le tenant context
    try:
        tid = db.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar()
        if tid:
            set_tenant_context(db, tid)
    except Exception:
        pass

   

    # ✅ FIX: SQL raw — contourne le cache de session ORM dégradé
    req_row = db.execute(
    text("""
        SELECT
            r.id::text AS id,
            r.provider,
            r.status,
            r.created_at,
            r.completed_at,
            r.case_id::text AS case_id,
            r.client_id,
            r.request_payload
        FROM public.screening_requests r
        WHERE r.id = CAST(:rid AS uuid)

        UNION ALL

        SELECT
            s.request_id::text AS id,
            'INTERNAL' AS provider,
            'DONE' AS status,
            NULL AS created_at,
            NULL AS completed_at,
            NULL AS case_id,
            NULL AS client_id,
            '{}'::jsonb AS request_payload
        FROM screening_results s
        WHERE s.request_id = CAST(:rid AS uuid)

        LIMIT 1
    """),
    {"rid": req_id_str},
).mappings().first()
    
    print(
    db.execute(
        text("""
        SELECT
            EXISTS(SELECT 1 FROM screening_requests WHERE id=:rid) as req,
            EXISTS(SELECT 1 FROM screening_results WHERE request_id=:rid) as res
        """),
        {"rid": req_id_str}
    ).fetchone()
)

    if not req_row:
        raise ValueError(
            f"ScreeningRequest {req_id_str} introuvable "
            "(vérifiez tenant context et UUID)"
        )

    req_payload = req_row.get("request_payload") or {}
    if not isinstance(req_payload, dict):
        req_payload = {}

    # Proxy compatible avec le reste du code
    class _Req:
        id              = req_row["id"]
        provider        = req_row.get("provider")     or "INTERNAL"
        status          = req_row.get("status")       or "DONE"
        created_at      = req_row.get("created_at")
        completed_at    = req_row.get("completed_at")
        case_id         = req_row.get("case_id")
        client_id       = req_row.get("client_id")
        request_payload = req_payload

    req = _Req()

    # ✅ FIX: result via SQL raw aussi
    res_row = db.execute(
        text("""
            SELECT
                id::text            AS id,
                request_id::text    AS request_id,
                risk_level,
                confidence,
                recommended_action,
                decided_by,
                decided_at,
                notes
            FROM public.screening_results
            WHERE request_id = CAST(:rid AS uuid)
            LIMIT 1
        """),
        {"rid": req_id_str},
    ).mappings().first()

    class _Res:
        risk_level         = res_row.get("risk_level")         if res_row else None
        confidence         = res_row.get("confidence")         if res_row else None
        recommended_action = res_row.get("recommended_action") if res_row else None
        decided_by         = res_row.get("decided_by")         if res_row else "SYSTEM"
        decided_at         = res_row.get("decided_at")         if res_row else None
        notes              = res_row.get("notes")              if res_row else None

    res = _Res() if res_row else None

    # ✅ FIX: matches via SQL raw
    match_rows = db.execute(
        text("""
            SELECT
                id,
                request_id::text        AS request_id,
                entity_id,
                source_record_id,
                match_score,
                match_band,
                reasons,
                created_at
            FROM public.screening_matches
            WHERE request_id = CAST(:rid AS uuid)
            ORDER BY match_score DESC
            LIMIT 200
        """),
        {"rid": req_id_str},
    ).mappings().all()
    matches = list(match_rows)

    # Case ID
    case_id = _coalesce(
        getattr(req, "case_id", None),
        _case_id_from_payload(req_payload),
        default="",
    )

    # Documents
    if case_id:
        def _load_docs() -> list[dict]:
            rows = db.execute(
                text("""
                    SELECT
                        d.id::text              AS id,
                        d.case_id::text         AS case_id,
                        d.doc_type::text        AS doc_type,
                        d.uploaded_at,
                        d.ocr_status::text      AS ocr_status,
                        d.ocr_confidence,
                        d.original_filename,
                        d.extracted_fields
                    FROM documents d
                    WHERE d.case_id = CAST(:cid AS uuid)
                    ORDER BY d.uploaded_at DESC LIMIT 10
                """),
                {"cid": case_id},
            ).mappings().all()
            return [dict(r) for r in rows]

        docs = _best_effort(db, _load_docs, [])
        if docs:
            req_payload["documents"] = docs

    # Decisions
    latest_dec, dec_history = _load_analyst_decisions(
        db, request_id=req_id_str, case_id=case_id or None
    )

    # Enrich matches with ORM (entities + source records)
    entity_ids = []
    for r in matches:
        eid = r.get("entity_id")
        if not eid:
            pass  # skip if eid is None
        else:
            try:
                entity_ids.append(UUID(str(eid)))
            except Exception:
                pass
    sr_ids = []
    for r in matches:
        sid = r.get("source_record_id")
        if sid:
            sr_ids.append(str(sid))

    entities: dict[str, Entity] = {}
    if entity_ids:
        ents = db.execute(
            select(Entity).where(Entity.id.in_(entity_ids))
        ).scalars().all()
        entities = {str(e.id): e for e in ents}

    src_recs: dict[str, SourceRecord] = {}
    if sr_ids:
        srs = db.execute(
            select(SourceRecord).where(SourceRecord.id.in_(sr_ids))
        ).scalars().all()
        src_recs = {str(s.id): s for s in srs}

    def _load_srcs() -> dict[int, dict]:
        has = db.execute(text("SELECT to_regclass('public.sources')")).scalar()
        if not has:
            return {}
        rows = db.execute(
            text("SELECT id::int, COALESCE(code::text,'') AS code, COALESCE(name::text,'') AS name FROM sources")
        ).mappings().all()
        out: dict[int, dict] = {}
        for r in rows:
            sid  = int(r["id"])
            code = (r.get("code") or "").strip() or SOURCE_FALLBACK.get(sid, f"SRC{sid}")
            name = (r.get("name") or "").strip() or None
            out[sid] = {"code": code, "name": name}
        return out

    srcs_map = _best_effort(db, _load_srcs, {})

    # Identity
    full_name    = _coalesce(req_payload.get("override_name"), req_payload.get("name"), req_payload.get("company_name"), default="-")
    entity_type  = _coalesce(req_payload.get("entity_type"), req_payload.get("kind"), default="-")
    client_id_v  = _coalesce(getattr(req, "client_id", None), req_payload.get("client_id"), default="-")
    provider     = _coalesce(getattr(req, "provider", None), default="INTERNAL")
    status_v     = _coalesce(getattr(req, "status", None), default="-")
    created_at   = _as_text(getattr(req, "created_at", None))
    completed_at = _as_text(getattr(req, "completed_at", None))

    risk_level   = _as_text(getattr(res, "risk_level", None) if res else None)
    confidence   = getattr(res, "confidence", None) if res else None
    action       = _as_text(getattr(res, "recommended_action", None) if res else None)
    notes        = _as_text(getattr(res, "notes", None) if res else None)

    risk_color, risk_bg, risk_txt   = _risk_style(risk_level)
    action_color, action_txt        = _action_style(action)

    ST    = _build_styles()
    story: list[Any] = []

    # ── Cover ──────────────────────────────────────────────────
    logo_cell: Any = ""
    if DEFAULT_LOGO_PATH.exists():
        try:
            logo    = Image(str(DEFAULT_LOGO_PATH))
            tw      = 36 * mm
            iw, ih  = float(logo.imageWidth), float(logo.imageHeight)
            logo.drawWidth  = tw
            logo.drawHeight = tw * (ih / iw if iw else 0.3)
            logo_cell = logo
        except Exception:
            pass

    title_block = [
        Paragraph("RAPPORT DE SCREENING", ST["title"]),
        Paragraph(f"Request ID : {req_id_str}", ST["small"]),
        Paragraph(f"Généré le : {created_at[:19] if created_at else '—'}", ST["small"]),
    ]
    header_tbl = Table(
        [[logo_cell, title_block]],
        colWidths=[44 * mm, CONTENT_W - 44 * mm],
    )
    header_tbl.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_tbl)
    story.append(HRFlowable(width=CONTENT_W, thickness=2, color=C_BLUE, spaceAfter=10))

    # ── KPI row ────────────────────────────────────────────────
    story.append(_kpi_row([
        {"label": "Risque",         "value": risk_txt,                                       "color": risk_color,   "bg": risk_bg},
        {"label": "Action",         "value": action_txt,                                     "color": action_color},
        {"label": "Confiance",      "value": f"{confidence}%" if confidence is not None else "—", "color": C_BLUE},
        {"label": "Correspondances","value": str(len(matches)),                               "color": C_GRAY_DK},
    ], ST))
    story.append(Spacer(1, 8))

    # ── Section 1 : Dossier ────────────────────────────────────
    story.append(_section_header_table("1 — Informations du dossier", ST))
    story.append(Spacer(1, 6))
    story.append(_two_col_table([
        ("Nom / Raison sociale", full_name),
        ("Type d'entité",        entity_type),
        ("Client ID",            client_id_v),
        ("Case ID",              case_id or "—"),
        ("Provider",             provider),
        ("Statut",               status_v),
        ("Créé le",              created_at[:19] if created_at else "—"),
        ("Terminé le",           completed_at[:19] if completed_at else "—"),
    ], ST))
    story.append(Spacer(1, 10))

    # ── Section 2 : Décision moteur ────────────────────────────
    story.append(_section_header_table("2 — Décision du moteur de screening", ST))
    story.append(Spacer(1, 6))
    dec_rows: list[tuple[str, str]] = [
        ("Niveau de risque",   risk_txt),
        ("Confiance",          f"{confidence}%" if confidence is not None else "—"),
        ("Action recommandée", action_txt),
        ("Décidé par",         _as_text(getattr(res, "decided_by", "SYSTEM") if res else "SYSTEM")),
    ]
    if notes:
        dec_rows.append(("Notes", notes))
    story.append(_two_col_table(dec_rows, ST))
    story.append(Spacer(1, 10))

    # ── Section 3 : Décision analyst ──────────────────────────
    story.append(_section_header_table("3 — Décision analyst (Bypass)", ST))
    story.append(Spacer(1, 6))
    if latest_dec:
        story.append(_two_col_table([
            ("Décision",    _as_text(latest_dec.get("decision"))),
            ("Analyste",    _as_text(latest_dec.get("decided_by_email"))),
            ("Date",        _as_text(latest_dec.get("decided_at"))[:19] if latest_dec.get("decided_at") else "—"),
            ("Commentaire", _as_text(latest_dec.get("comment")) or "—"),
        ], ST))
        if len(dec_history) > 1:
            story.append(Paragraph(f"{len(dec_history) - 1} décision(s) antérieure(s).", ST["small"]))
    else:
        story.append(Paragraph("Aucune décision analyst enregistrée.", ST["body"]))
    story.append(Spacer(1, 10))

    # ── Section 4 : Tableau récap correspondances ──────────────
    story.append(_section_header_table(f"4 — Correspondances trouvées ({len(matches)})", ST))
    story.append(Spacer(1, 6))

    top_matches = matches[:50]
    if not top_matches:
        story.append(Paragraph("✓ Aucune correspondance détectée.", ST["body"]))
    else:
        hdr = [
            Paragraph("N°",        ST["label"]),
            Paragraph("Entité",    ST["label"]),
            Paragraph("Catégorie", ST["label"]),
            Paragraph("Source",    ST["label"]),
            Paragraph("Programme", ST["label"]),
            Paragraph("Score",     ST["label"]),
        ]
        tbl_data = [hdr]
        for i, r in enumerate(top_matches, 1):
            ent   = entities.get(str(r.get("entity_id") or ""))
            sr    = src_recs.get(str(r.get("source_record_id") or "")) if r.get("source_record_id") else None
            sid   = int(getattr(sr, "source_id", 0) or 0) if sr else 0
            scode = srcs_map.get(sid, {}).get("code") or SOURCE_FALLBACK.get(sid, "—")
            score = int(round(float(r.get("match_score") or 0)))
            sc    = C_RED if score >= 85 else C_ORANGE if score >= 70 else C_GRAY_MD
            tbl_data.append([
                Paragraph(str(i), ST["small"]),
                Paragraph(_coalesce(getattr(ent, "primary_name", None), default="—"), ST["body"]),
                Paragraph(_normalize_band(r.get("match_band")), ST["small"]),
                Paragraph(scode, ST["small"]),
                Paragraph(_coalesce(getattr(sr, "program", None), default="—"), ST["small"]),
                Paragraph(f"<font color='{sc}'><b>{score}%</b></font>", ST["body"]),
            ])

        tm = Table(tbl_data, colWidths=[8 * mm, 50 * mm, 22 * mm, 18 * mm, 48 * mm, 14 * mm])
        tm.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  C_NAVY),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  C_WHITE),
            ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
            ("FONTSIZE",      (0, 0), (-1, 0),  8),
            ("BOX",           (0, 0), (-1, -1), 0.5, C_BORDER),
            ("INNERGRID",     (0, 1), (-1, -1), 0.3, C_GRAY_LT),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_WHITE, C_GRAY_XL]),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(tm)
    story.append(Spacer(1, 8))

    # ── Section 5 : Fiches détaillées ─────────────────────────
    if top_matches:
        story.append(PageBreak())
        story.append(_section_header_table("5 — Fiches détaillées des correspondances", ST))
        story.append(Spacer(1, 8))

        for idx, r in enumerate(top_matches[:20], 1):
            ent      = entities.get(str(r.get("entity_id") or ""))
            sr       = src_recs.get(str(r.get("source_record_id") or "")) if r.get("source_record_id") else None
            sid      = int(getattr(sr, "source_id", 0) or 0) if sr else 0
            src_code = srcs_map.get(sid, {}).get("code") or SOURCE_FALLBACK.get(sid, "—")
            src_name = srcs_map.get(sid, {}).get("name") or src_code
            score    = int(float(r.get("match_score") or 0))
            band     = _normalize_band(r.get("match_band"))
            sc       = C_RED if score >= 85 else C_ORANGE if score >= 70 else C_GRAY_MD
            name_txt = _coalesce(getattr(ent, "primary_name", None), default="Entité inconnue")

            card_header = Table([[
                Paragraph(
                    f"{idx}. {name_txt}",
                    ParagraphStyle(f"ch{idx}", fontName="Helvetica-Bold", fontSize=10,
                                   textColor=C_WHITE, leading=13),
                ),
                Paragraph(
                    f"Score : <b>{score}%</b>",
                    ParagraphStyle(f"cs{idx}", fontName="Helvetica-Bold", fontSize=9,
                                   textColor=sc,
                                   leading=12, alignment=TA_RIGHT),
                ),
            ]], colWidths=[CONTENT_W - 30 * mm, 30 * mm])
            card_header.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), C_DARK),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
                ("TOPPADDING",    (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
            ]))

            meta_str  = f"Catégorie : {band}  |  Source : {src_name}  |  Programme : {_coalesce(getattr(sr, 'program', None), default='—')}"
            lo        = getattr(sr, "listed_on", None)
            if lo:
                meta_str += f"  |  Inscrit le : {lo}"
            meta_row  = Table([[Paragraph(meta_str, ST["small"])]], colWidths=[CONTENT_W])
            meta_row.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, -1), C_BLUE_LT),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))

            body_items: list[Any] = []
            sanc = _sanction_bullets(sr)
            body_items.append(
                Paragraph("Motifs / Raisons :", ParagraphStyle(
                    f"bl{idx}", fontName="Helvetica-Bold", fontSize=8.5,
                    textColor=C_DARK, leading=11, spaceBefore=4))
            )
            for b in (sanc or ["Aucun motif détaillé disponible."]):
                body_items.append(Paragraph(f"• {b}", ST["bullet"]))

            body_items.append(Spacer(1, 4))
            body_items.append(
                Paragraph("Raisons techniques (matching) :", ParagraphStyle(
                    f"bl2{idx}", fontName="Helvetica-Bold", fontSize=8.5,
                    textColor=C_DARK, leading=11, spaceBefore=4))
            )
            for b in _humanize_reasons(r.get("reasons"))[:6]:
                body_items.append(Paragraph(f"• {b}", ST["bullet"]))

            links = getattr(sr, "evidence_urls", None) if sr else None
            if isinstance(links, list) and links:
                body_items.append(Spacer(1, 4))
                body_items.append(
                    Paragraph("Liens (preuves) :", ParagraphStyle(
                        f"bl3{idx}", fontName="Helvetica-Bold", fontSize=8.5,
                        textColor=C_DARK, leading=11))
                )
                for url in links[:4]:
                    body_items.append(
                        Paragraph(
                            f"<link href='{url}' color='#2D7FD6'>• {url[:80]}{'…' if len(url) > 80 else ''}</link>",
                            ST["small"],
                        )
                    )

            body_tbl = Table([[body_items]], colWidths=[CONTENT_W])
            body_tbl.setStyle(TableStyle([
                ("BOX",           (0, 0), (-1, -1), 0.5, C_BORDER),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
                ("TOPPADDING",    (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))
            story.append(KeepTogether([card_header, meta_row, body_tbl, Spacer(1, 8)]))

    # ── Section 6 : Historique décisions ──────────────────────
    if len(dec_history) > 1:
        story.append(Spacer(1, 6))
        story.append(_section_header_table(f"6 — Historique des décisions ({len(dec_history)})", ST))
        story.append(Spacer(1, 6))
        hist_data = [[Paragraph(h, ST["label"]) for h in ["Décision", "Analyste", "Date", "Commentaire"]]]
        for d in dec_history[:20]:
            hist_data.append([
                Paragraph(_as_text(d.get("decision")), ST["body"]),
                Paragraph(_as_text(d.get("decided_by_email")), ST["body"]),
                Paragraph((_as_text(d.get("decided_at")) or "")[:16], ST["small"]),
                Paragraph((_as_text(d.get("comment")) or "—")[:120], ST["body"]),
            ])
        ht = Table(hist_data, colWidths=[22 * mm, 42 * mm, 28 * mm, CONTENT_W - 92 * mm])
        ht.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  C_NAVY),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  C_WHITE),
            ("BOX",           (0, 0), (-1, -1), 0.5, C_BORDER),
            ("INNERGRID",     (0, 1), (-1, -1), 0.3, C_GRAY_LT),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [C_WHITE, C_GRAY_XL]),
            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(ht)

    # ── Build ──────────────────────────────────────────────────
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN,  rightMargin=MARGIN,
        topMargin=16 * mm,  bottomMargin=14 * mm,
        title="Rapport de Screening", author="Simandou Screening",
    )
    hf = _make_header_footer("Rapport de Screening", req_id_str)
    doc.build(story, onFirstPage=hf, onLaterPages=hf)
    return buf.getvalue()