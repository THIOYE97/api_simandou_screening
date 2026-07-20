"""
Service métier — Bénéficiaires effectifs (BE).

Registre interne : une déclaration porte sur une personne morale, ses membres
forment une chaîne de détention. Chaque membre est confronté aux listes
(sanctions, PPE) par le MÊME moteur que le KYC/KYS et le KYT.

Règle LBC/FT appliquée : un bénéficiaire effectif rapproché d'une liste rend la
PERSONNE MORALE à risque — le risque ne reste pas cantonné à la personne
physique. L'évaluation produite porte donc sur la société, et l'alerte est
qualifiée d'origine « UBO » pour que la Conformité la distingue.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.alerting import AlertSource
from app.models.scoring import SubjectType
from app.models.ubo import PartyKind, UboDeclaration, UboMember
from app.services import alerting_service, list_screening, scoring_service

# Seuil légal usuel de détention à partir duquel une personne est bénéficiaire
# effectif (directive LBC/FT et Acte uniforme OHADA sur les sociétés).
OWNERSHIP_THRESHOLD = Decimal("25")


def _norm(value: str) -> str:
    """Dénomination comparable : sans accents, ponctuation ni forme juridique."""
    import re
    import unicodedata
    txt = unicodedata.normalize("NFD", str(value or ""))
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    txt = re.sub(r"[^A-Za-z0-9]+", " ", txt).strip().upper()
    return re.sub(r"\s+", " ", txt)


# --- Déclarations ------------------------------------------------------------

def list_declarations(db: Session, limit: int = 100) -> list[UboDeclaration]:
    return list(db.execute(
        select(UboDeclaration).order_by(UboDeclaration.created_at.desc()).limit(limit)
    ).scalars().all())


def get_declaration(db: Session, declaration_id: UUID) -> Optional[UboDeclaration]:
    return db.get(UboDeclaration, declaration_id)


def get_members(db: Session, declaration_id: UUID) -> list[UboMember]:
    return list(db.execute(
        select(UboMember)
        .where(UboMember.declaration_id == declaration_id)
        .order_by(UboMember.created_at)
    ).scalars().all())


def find_declaration_for_company(
    db: Session, company_name: Optional[str] = None, company_ref: Optional[str] = None,
) -> Optional[UboDeclaration]:
    """
    Rapproche une société de sa déclaration de bénéficiaires effectifs.

    L'identifiant (RCCM/NIF) prime sur la dénomination, qui varie dans son
    écriture (« SA », « S.A. », casse, accents).
    """
    if company_ref:
        found = db.execute(
            select(UboDeclaration).where(
                func.upper(UboDeclaration.company_ref) == company_ref.strip().upper()
            )
        ).scalars().first()
        if found:
            return found
    if company_name:
        key = _norm(company_name)
        for d in db.execute(select(UboDeclaration)).scalars().all():
            if _norm(d.company_name) == key:
                return d
    return None


def create_declaration(
    db: Session, data: dict, tenant_id: Optional[UUID] = None,
    created_by: Optional[UUID] = None,
) -> UboDeclaration:
    members = data.pop("members", None) or []
    decl = UboDeclaration(tenant_id=tenant_id, created_by=created_by, **data)
    db.add(decl)
    db.flush()
    for m in members:
        _add_member_obj(db, decl, m, tenant_id)
    db.commit()
    db.refresh(decl)
    return decl


def delete_declaration(db: Session, declaration_id: UUID) -> bool:
    decl = db.get(UboDeclaration, declaration_id)
    if not decl:
        return False
    db.delete(decl)   # cascade sur les membres
    db.commit()
    return True


# --- Membres de la chaîne de détention ---------------------------------------

def _effective_percent(db: Session, member: UboMember) -> Decimal:
    """
    Détention effective = produit des pourcentages le long de la chaîne.

    Détenir 80 % d'une société qui détient elle-même 60 % de la cible revient à
    en détenir 48 %. Sans ce calcul, une chaîne conçue pour diluer la détention
    apparente passerait sous le seuil de 25 % à chaque niveau.
    """
    pct = Decimal(str(member.ownership_percent or 0))
    parent_id, guard = member.parent_id, 0
    while parent_id and guard < 20:      # garde-fou anti-boucle
        parent = db.get(UboMember, parent_id)
        if not parent:
            break
        pct = pct * Decimal(str(parent.ownership_percent or 0)) / Decimal("100")
        parent_id, guard = parent.parent_id, guard + 1
    return pct.quantize(Decimal("0.001"))


def _add_member_obj(db: Session, decl: UboDeclaration, data: dict, tenant_id) -> UboMember:
    m = UboMember(tenant_id=tenant_id, declaration_id=decl.id, **data)
    db.add(m)
    db.flush()
    # Qualification automatique : seuil de détention OU contrôle par autre moyen.
    if m.kind == PartyKind.PERSON:
        eff = _effective_percent(db, m)
        m.is_beneficial_owner = bool(
            eff >= OWNERSHIP_THRESHOLD
            or str(m.control_nature or "").endswith("EFFECTIVE_CONTROL")
            or str(m.control_nature or "").endswith("LEGAL_REPRESENTATIVE")
        )
        db.flush()
    return m


def add_member(db: Session, declaration_id: UUID, data: dict, tenant_id=None) -> Optional[UboMember]:
    decl = db.get(UboDeclaration, declaration_id)
    if not decl:
        return None
    m = _add_member_obj(db, decl, data, tenant_id or decl.tenant_id)
    db.commit()
    db.refresh(m)
    return m


def update_member(db: Session, member_id: UUID, data: dict) -> Optional[UboMember]:
    m = db.get(UboMember, member_id)
    if not m:
        return None
    for k, v in data.items():
        setattr(m, k, v)
    db.flush()
    if m.kind == PartyKind.PERSON:
        m.is_beneficial_owner = bool(_effective_percent(db, m) >= OWNERSHIP_THRESHOLD
                                     or str(m.control_nature or "").endswith("EFFECTIVE_CONTROL")
                                     or str(m.control_nature or "").endswith("LEGAL_REPRESENTATIVE"))
    db.commit()
    db.refresh(m)
    return m


def delete_member(db: Session, member_id: UUID) -> bool:
    m = db.get(UboMember, member_id)
    if not m:
        return False
    db.delete(m)
    db.commit()
    return True


def member_out(db: Session, m: UboMember) -> dict[str, Any]:
    """Représentation enrichie de la détention effective (produit de la chaîne)."""
    return {
        "id": str(m.id),
        "parent_id": str(m.parent_id) if m.parent_id else None,
        "kind": m.kind.value if hasattr(m.kind, "value") else m.kind,
        "full_name": m.full_name,
        "nationality": m.nationality,
        "country": m.country,
        "date_of_birth": m.date_of_birth,
        "identifier": m.identifier,
        "ownership_percent": float(m.ownership_percent) if m.ownership_percent is not None else None,
        "effective_percent": float(_effective_percent(db, m)),
        "control_nature": m.control_nature.value if hasattr(m.control_nature, "value") else m.control_nature,
        "is_beneficial_owner": bool(m.is_beneficial_owner),
        "match_score": m.match_score,
        "is_pep": bool(m.is_pep),
        "screened_at": m.screened_at.isoformat() if m.screened_at else None,
        "matches": m.matches or [],
    }


# --- Filtrage contre les listes + risque de la personne morale ----------------

def screen_declaration(db: Session, declaration_id: UUID) -> Optional[dict]:
    """
    Filtre tous les membres, puis reporte le risque sur la personne morale.

    Retourne le détail du contrôle (membres filtrés, évaluation, alertes).
    """
    decl = db.get(UboDeclaration, declaration_id)
    if not decl:
        return None

    members = get_members(db, declaration_id)
    screened: list[dict] = []

    for m in members:
        if not list_screening.is_screenable(m.full_name):
            continue
        hit = list_screening.screen_name(
            db, name=m.full_name, tenant_id=decl.tenant_id,
            trigger="ubo.member_screening", country=m.country or m.nationality,
            extra_meta={"declaration_id": str(decl.id), "member_id": str(m.id)},
        )
        if hit is None:
            continue
        m.match_score = hit["score"]
        m.is_pep = hit["is_pep"]
        m.matches = hit["matches"]
        m.screening_request_id = UUID(hit["request_id"])
        m.screened_at = datetime.now(timezone.utc)
        screened.append({**hit, "member_id": str(m.id), "full_name": m.full_name,
                         "is_beneficial_owner": bool(m.is_beneficial_owner)})

    db.commit()

    # Le contexte tenant a été perdu par les commits du moteur.
    if decl.tenant_id:
        from app.core.db import set_tenant_context
        set_tenant_context(db, str(decl.tenant_id))

    # Risque de la SOCIÉTÉ : on ne retient que les bénéficiaires effectifs
    # rapprochés — un intermédiaire non retenu comme BE ne doit pas, à lui seul,
    # faire basculer la personne morale.
    owners = [s for s in screened if s["is_beneficial_owner"]]
    top = max((s["score"] for s in owners), default=0)
    ctx: dict[str, Any] = {
        "ubo_match_score": top,
        "ubo_is_pep": any(s["is_pep"] for s in owners),
        "ubo_count": len([m for m in members if m.is_beneficial_owner]),
        "screened_parties": [
            {
                "role": "Bénéficiaire effectif" if s["is_beneficial_owner"] else "Chaîne de détention",
                "name": s["full_name"], "screened": True, "score": s["score"],
                "is_pep": s["is_pep"], "match_count": len(s["matches"]),
                "top_match": s["matches"][0]["name"] if s["matches"] else None,
                "list": s["matches"][0]["source"] if s["matches"] else None,
            }
            for s in screened
        ],
    }
    if decl.company_country:
        ctx["country"] = decl.company_country

    assessment = scoring_service.score_subject(
        db, subject_type=SubjectType.COMPANY, context=ctx,
        subject_ref=decl.company_ref or str(decl.id),
        subject_label=decl.company_name,
        tenant_id=decl.tenant_id, persist=True,
    )
    decl.risk_assessment_id = assessment.id
    decl.last_screened_at = datetime.now(timezone.utc)
    db.commit()

    alerts = alerting_service.generate_from_assessment(db, assessment, source=AlertSource.UBO)

    matched = [s for s in screened if s["matches"]]
    if alerts and matched:
        detail = {
            "subject_label": decl.company_name,
            "matches": [mm for s in matched for mm in s["matches"]],
            "parties": ctx["screened_parties"],
        }
        for a in alerts:
            d = dict(a.detail or {})
            d["screening"] = detail
            a.detail = d
        db.commit()

    return {
        "declaration_id": str(decl.id),
        "company_name": decl.company_name,
        "risk_class": assessment.risk_class.value if hasattr(assessment.risk_class, "value") else assessment.risk_class,
        "total_score": assessment.total_score,
        "triggered": assessment.triggered,
        "alerts_created": len(alerts),
        "members": [member_out(db, m) for m in get_members(db, declaration_id)],
    }
