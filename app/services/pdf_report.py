"""
Générateur de rapports PDF — présentation institutionnelle BCRG, claire et
explicite, sans identifiants techniques (UUID).

- Rapport de vérification (personne / entreprise)
- Rapport d'opération (transaction)

Chaque rapport : bandeau officiel, référence courte, résultat, détails métier,
correspondances / motifs, et historique des décisions de la Conformité.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import text
from sqlalchemy.orm import Session

# ----- palette institutionnelle -----
NAVY = colors.HexColor("#1b2a52")
BRAND = colors.HexColor("#20458f")
GOLD = colors.HexColor("#c8a24a")
INK = colors.HexColor("#222c42")
SOFT = colors.HexColor("#5f6c86")
LINE = colors.HexColor("#dbe2ee")
BG = colors.HexColor("#f3f6fb")

RISK = {
    "LOW": ("FAIBLE", colors.HexColor("#2f9e63")),
    "MEDIUM": ("MOYEN", colors.HexColor("#c67c1e")),
    "HIGH": ("ÉLEVÉ", colors.HexColor("#d9662f")),
    "CRITICAL": ("TRÈS ÉLEVÉ", colors.HexColor("#cf4444")),
}
SOURCE_LABEL = {
    "T24": "Core Banking (T24)", "SWIFT": "Virement international (SWIFT)",
    "ACH": "Compensation (ACP/ACH)", "RTGS": "Virement temps réel (RTGS)", "MANUAL": "Saisie manuelle",
}
CHANNEL_LABEL = {"CASH": "Espèces", "WIRE": "Virement", "CHECK": "Chèque", "CARD": "Carte", "OTHER": "Autre"}
ACTION_LABEL = {
    "TAKE_CHARGE": "Prise en charge", "ESCALATE": "Escaladée",
    "CONFIRM": "Soupçon confirmé", "DISMISS": "Alerte levée",
}


def _styles() -> dict:
    base = getSampleStyleSheet()
    S: dict = {}
    S["org"] = ParagraphStyle("org", parent=base["Normal"], fontSize=13, textColor=colors.white, fontName="Helvetica-Bold", leading=15)
    S["orgsub"] = ParagraphStyle("orgsub", parent=base["Normal"], fontSize=8.5, textColor=colors.HexColor("#c9d4ec"), leading=11)
    S["conf"] = ParagraphStyle("conf", parent=base["Normal"], fontSize=8, textColor=NAVY, fontName="Helvetica-Bold", alignment=1)
    S["title"] = ParagraphStyle("title", parent=base["Normal"], fontSize=16, textColor=INK, fontName="Helvetica-Bold", spaceBefore=16, leading=20)
    S["sub"] = ParagraphStyle("sub", parent=base["Normal"], fontSize=9, textColor=SOFT, spaceAfter=2)
    S["h"] = ParagraphStyle("h", parent=base["Normal"], fontSize=10.5, textColor=NAVY, fontName="Helvetica-Bold", leading=13)
    S["k"] = ParagraphStyle("k", parent=base["Normal"], fontSize=9, textColor=SOFT)
    S["v"] = ParagraphStyle("v", parent=base["Normal"], fontSize=10, textColor=INK, leading=13)
    S["cell"] = ParagraphStyle("cell", parent=base["Normal"], fontSize=8.6, textColor=INK, leading=11)
    S["cellh"] = ParagraphStyle("cellh", parent=base["Normal"], fontSize=8, textColor=colors.white, fontName="Helvetica-Bold")
    return S


def _fmt_date(v: Any) -> str:
    if not v:
        return "—"
    try:
        d = v if isinstance(v, datetime) else datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d.strftime("%d/%m/%Y à %Hh%M")
    except Exception:
        return str(v)


def _ref(prefix: str, rid: str) -> str:
    """Référence courte et lisible (pas d'UUID complet)."""
    short = rid.replace("-", "")[:6].upper()
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{short}"


# ---------- blocs de présentation ----------

def _bandeau(S: dict) -> Table:
    left = [
        Paragraph("BANQUE CENTRALE DE LA RÉPUBLIQUE DE GUINÉE", S["org"]),
        Paragraph("Direction de la Conformité · Dispositif LBC/FT", S["orgsub"]),
    ]
    conf = Table([[Paragraph("CONFIDENTIEL", S["conf"])]], colWidths=[30 * mm])
    conf.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GOLD), ("TOPPADDING", (0, 0), (-1, -1), 5),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 5), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    band = Table([[left, conf]], colWidths=[135 * mm, 30 * mm])
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LEFTPADDING", (0, 0), (0, 0), 12), ("RIGHTPADDING", (1, 0), (1, 0), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -1), 2.5, GOLD),
    ]))
    return band


def _meta(rows: list[tuple[str, str]], S: dict) -> Table:
    cells = []
    for k, v in rows:
        cells.append([Paragraph(k.upper(), ParagraphStyle("mk", parent=S["k"], fontSize=7.2, textColor=SOFT)),
                      Paragraph(f"<b>{v}</b>", S["v"])])
    t = Table([[c[0] for c in cells], [c[1] for c in cells]], colWidths=[165 / len(rows) * mm] * len(rows))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG), ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
    ]))
    return t


def _section(title: str, S: dict) -> Table:
    bar = Table([[""]], colWidths=[3 * mm], rowHeights=[6 * mm])
    bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GOLD)]))
    t = Table([[bar, Paragraph(title, S["h"])]], colWidths=[5 * mm, 160 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


def _risk_card(risk: str, score: Any, S: dict) -> Table:
    label, col = RISK.get(str(risk or "").upper(), ("NON DÉTERMINÉ", SOFT))
    left = Paragraph("NIVEAU DE RISQUE GLOBAL", ParagraphStyle("rl", parent=S["k"], fontSize=8, textColor=colors.white))
    big = Paragraph(f"<font size=15><b>{label}</b></font>", ParagraphStyle("rv", parent=S["v"], textColor=colors.white))
    sc = Paragraph(f"Score : <b>{score}/100</b>" if score is not None else "", ParagraphStyle("rs", parent=S["v"], textColor=colors.white, alignment=2, fontSize=10))
    t = Table([[[left, big], sc]], colWidths=[120 * mm, 45 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), col),
        ("LEFTPADDING", (0, 0), (0, 0), 12), ("RIGHTPADDING", (1, 0), (1, 0), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _kv(rows: list[tuple[str, str]], S: dict) -> Table:
    data = [[Paragraph(k, S["k"]), Paragraph(v or "—", S["v"])] for k, v in rows]
    t = Table(data, colWidths=[48 * mm, 117 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINE),
    ]))
    return t


def _table(header: list[str], rows: list[list[str]], widths: list[float], S: dict) -> Table:
    data = [[Paragraph(h.upper(), S["cellh"]) for h in header]]
    for r in rows:
        data.append([Paragraph(str(c), S["cell"]) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("BOX", (0, 0), (-1, -1), 0.4, LINE), ("LINEBELOW", (0, 0), (-1, -1), 0.3, LINE),
    ]))
    return t


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 14 * mm, A4[0] - 18 * mm, 14 * mm)
    canvas.setFillColor(SOFT)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(18 * mm, 9.5 * mm, "Document strictement confidentiel — Banque Centrale de la République de Guinée · Dispositif LBC/FT")
    canvas.drawRightString(A4[0] - 18 * mm, 9.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _match_motifs(reasons: Any) -> str:
    """Reconstruit des motifs lisibles à partir des données de rapprochement."""
    if not isinstance(reasons, dict):
        return "—"
    parts: list[str] = []
    sim = reasons.get("trigram_similarity")
    if sim is not None:
        parts.append(f"Similarité du nom : {int(round(float(sim) * 100))}%")
    inp, mat = reasons.get("input_normalized"), reasons.get("matched_normalized")
    if inp and mat:
        parts.append(f"« {inp} » ↔ « {mat} »")
    return " ; ".join(parts) or "Rapprochement de nom avec une entité des listes."


def _events_rows(db: Session, subject_id: str) -> list[list[str]]:
    rows = db.execute(text("""
        SELECT action, decision, justification, created_at
        FROM compliance_events WHERE subject_id = :sid ORDER BY created_at ASC
    """), {"sid": subject_id}).mappings().all()
    out = []
    for e in rows:
        dec = "Sujet bloqué" if e["decision"] == "BLOCKED" else "Sujet autorisé" if e["decision"] == "AUTHORIZED" else "—"
        out.append([_fmt_date(e["created_at"]), ACTION_LABEL.get(e["action"], e["action"]), dec, e["justification"] or "—"])
    return out


def _build(story: list, title: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=14 * mm, bottomMargin=18 * mm,
                            leftMargin=18 * mm, rightMargin=18 * mm, title=title)
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


# =========================================================================
# Rapport de vérification (personne / entreprise)
# =========================================================================

def build_screening_pdf(db: Session, request_id, tenant_id: Optional[str] = None) -> bytes:
    rid = str(request_id if isinstance(request_id, UUID) else request_id)
    S = _styles()

    req = db.execute(text("""
        SELECT request_payload, created_at FROM screening_requests WHERE id = CAST(:rid AS uuid)
    """), {"rid": rid}).mappings().first()
    payload = (req or {}).get("request_payload") or {}
    res = db.execute(text("""
        SELECT risk_level, recommended_action, confidence FROM screening_results
        WHERE request_id = CAST(:rid AS uuid) LIMIT 1
    """), {"rid": rid}).mappings().first() or {}
    matches = db.execute(text("""
        SELECT sm.match_score, sm.reasons, e.primary_name AS name,
               COALESCE(so.source_code, e.source_name) AS source, sr.program, sr.record_type
        FROM screening_matches sm
        LEFT JOIN entities e ON e.id = sm.entity_id
        LEFT JOIN source_records sr ON sr.id = sm.source_record_id
        LEFT JOIN sources so ON so.id = sr.source_id
        WHERE sm.request_id = CAST(:rid AS uuid) ORDER BY sm.match_score DESC LIMIT 50
    """), {"rid": rid}).mappings().all()

    name = (payload.get("override_name")
            or " ".join(x for x in [payload.get("first_name"), payload.get("last_name")] if x).strip()
            or payload.get("company_name") or payload.get("name") or "Client")
    is_company = bool(payload.get("company_name")) or str(payload.get("entity_type", "")).upper() in ("COMPANY", "KYB")
    typ = "Entreprise" if is_company else "Personne physique"

    st: list[Any] = [_bandeau(S)]
    st.append(Paragraph("Rapport de vérification de conformité (KYC/KYB)", S["title"]))
    st.append(Paragraph("Filtrage contre les listes de sanctions, PEP et adverse media.", S["sub"]))
    st.append(Spacer(1, 10))
    st.append(_meta([("Référence", _ref("VER", rid)), ("Type", typ), ("Émis le", _fmt_date(datetime.now(timezone.utc)))], S))
    st.append(Spacer(1, 14))

    st.append(_risk_card(res.get("risk_level"), res.get("confidence"), S))
    st.append(Spacer(1, 16))

    st.append(_section("Identité du client vérifié", S))
    st.append(_kv([
        ("Nom / dénomination", name),
        ("Type", typ),
        ("Nationalité / pays", payload.get("nationality") or payload.get("country") or "—"),
        ("Date de la vérification", _fmt_date((req or {}).get("created_at"))),
        ("Correspondances trouvées", str(len(matches))),
    ], S))
    st.append(Spacer(1, 14))

    st.append(_section("Correspondances avec les listes", S))
    st.append(Spacer(1, 4))
    if matches:
        rows = []
        for m in matches:
            rows.append([m["name"] or "—", m["source"] or "—", m["program"] or m["record_type"] or "—",
                         f"{int(m['match_score'] or 0)}%", _match_motifs(m["reasons"])])
        st.append(_table(["Nom sur la liste", "Source", "Programme", "Score", "Motifs du rapprochement"],
                         rows, [38 * mm, 22 * mm, 25 * mm, 13 * mm, 67 * mm], S))
    else:
        st.append(Paragraph("Aucune correspondance avec les listes de sanction. Client conforme.", S["v"]))
    st.append(Spacer(1, 14))

    st.append(_section("Historique des décisions de la Conformité", S))
    st.append(Spacer(1, 4))
    ev = _events_rows(db, rid)
    if ev:
        st.append(_table(["Date", "Action", "Décision", "Justification"], ev, [32 * mm, 33 * mm, 26 * mm, 74 * mm], S))
    else:
        st.append(Paragraph("Aucune décision de conformité enregistrée à ce jour.", S["v"]))

    return _build(st, "Rapport de vérification")


# =========================================================================
# Rapport d'opération (transaction)
# =========================================================================

def build_transaction_pdf(db: Session, transaction_id, tenant_id: Optional[str] = None) -> bytes:
    tid = str(transaction_id if isinstance(transaction_id, UUID) else transaction_id)
    S = _styles()

    t = db.execute(text("""
        SELECT external_ref, source_system, channel, amount, currency, customer_ref,
               counterparty_name, counterparty_country, decision, risk_assessment_id::text AS raid, created_at
        FROM kyt_transactions WHERE id = CAST(:tid AS uuid)
    """), {"tid": tid}).mappings().first()
    if not t:
        raise ValueError("Transaction introuvable")

    a = {}
    if t["raid"]:
        a = db.execute(text("""
            SELECT total_score, risk_class, triggered FROM risk_assessments WHERE id = CAST(:aid AS uuid)
        """), {"aid": t["raid"]}).mappings().first() or {}

    dec = t["decision"]
    dec_label = "Opération bloquée" if dec == "BLOCKED" else "Opération autorisée" if dec == "AUTHORIZED" else "En attente de décision"

    st: list[Any] = [_bandeau(S)]
    st.append(Paragraph("Rapport de surveillance d'opération (KYT)", S["title"]))
    st.append(Paragraph("Analyse des comportements atypiques sur les transactions.", S["sub"]))
    st.append(Spacer(1, 10))
    st.append(_meta([("Référence", _ref("OPE", tid)), ("Statut", dec_label), ("Émis le", _fmt_date(datetime.now(timezone.utc)))], S))
    st.append(Spacer(1, 14))

    st.append(_risk_card(a.get("risk_class"), a.get("total_score"), S))
    st.append(Spacer(1, 16))

    st.append(_section("Détails de l'opération", S))
    st.append(_kv([
        ("Client concerné", t["customer_ref"] or "—"),
        ("Bénéficiaire", t["counterparty_name"] or "—"),
        ("Pays du bénéficiaire", t["counterparty_country"] or "—"),
        ("Montant", f"{t['amount']} {t['currency']}"),
        ("Provenance", SOURCE_LABEL.get(t["source_system"], t["source_system"])),
        ("Moyen de paiement", CHANNEL_LABEL.get(t["channel"], t["channel"])),
        ("Date de l'opération", _fmt_date(t["created_at"])),
        ("Décision de la Conformité", dec_label),
    ], S))
    st.append(Spacer(1, 14))

    triggered = a.get("triggered") or []
    if triggered:
        st.append(_section("Motifs de risque détectés", S))
        st.append(Spacer(1, 4))
        rows = [[m.get("name", "—"), str(m.get("severity", "—")).capitalize(), f"+{m.get('weight', 0)}"] for m in triggered]
        st.append(_table(["Motif", "Gravité", "Poids"], rows, [115 * mm, 35 * mm, 15 * mm], S))
        st.append(Spacer(1, 14))

    st.append(_section("Historique des décisions de la Conformité", S))
    st.append(Spacer(1, 4))
    ev = _events_rows(db, tid)
    if ev:
        st.append(_table(["Date", "Action", "Décision", "Justification"], ev, [32 * mm, 33 * mm, 26 * mm, 74 * mm], S))
    else:
        st.append(Paragraph("Aucune décision de conformité enregistrée à ce jour.", S["v"]))

    return _build(st, "Rapport d'opération")
