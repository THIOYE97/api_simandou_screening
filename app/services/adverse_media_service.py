"""
Service métier — Adverse media.

Screening d'un nom candidat contre la base adverse media, via le moteur de
matching flou existant (normalize_name / tokenize / score_candidate).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.adverse_media import AdverseMediaCategory, AdverseMediaRecord
from app.services.matching import normalize_name, score_candidate, tokenize

MATCH_THRESHOLD = 65  # POSSIBLE ou mieux


def _trigrams(norm: str) -> set[str]:
    s = norm.replace(" ", "")
    if len(s) < 3:
        return {s} if s else set()
    return {s[i:i + 3] for i in range(len(s) - 2)}


def _similarity(a_norm: str, b_norm: str) -> int:
    ta, tb = _trigrams(a_norm), _trigrams(b_norm)
    trig = (len(ta & tb) / len(ta | tb)) if (ta or tb) else 0.0
    sa, sb = set(tokenize(a_norm)), set(tokenize(b_norm))
    tok = (len(sa & sb) / max(len(sa), len(sb))) if (sa or sb) else 0.0
    return score_candidate(trig, tok)


def screen_name(db: Session, name: str, threshold: int = MATCH_THRESHOLD) -> list[dict]:
    """Retourne les enregistrements adverse media proches du nom, triés par score."""
    target = normalize_name(name)
    records = db.execute(
        select(AdverseMediaRecord).where(AdverseMediaRecord.active.is_(True))
    ).scalars().all()

    out: list[dict] = []
    for r in records:
        score = _similarity(target, r.normalized_name)
        if score >= threshold:
            out.append({
                "id": str(r.id),
                "entity_name": r.entity_name,
                "category": r.category.value,
                "source": r.source,
                "url": r.url,
                "summary": r.summary,
                "score": score,
            })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def has_adverse_media(db: Session, name: str, threshold: int = MATCH_THRESHOLD) -> bool:
    return len(screen_name(db, name, threshold)) > 0


def add_record(db: Session, data: dict) -> AdverseMediaRecord:
    data = dict(data)
    data["normalized_name"] = normalize_name(data.get("entity_name", ""))
    obj = AdverseMediaRecord(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def list_records(db: Session, limit: int = 200) -> list[AdverseMediaRecord]:
    return list(db.execute(
        select(AdverseMediaRecord).order_by(AdverseMediaRecord.created_at.desc()).limit(limit)
    ).scalars().all())


_SEED = [
    ("Viktor Petrov", AdverseMediaCategory.MONEY_LAUNDERING,
     "ICIJ", "Enquête sur un réseau de blanchiment transfrontalier."),
    ("Global Mining SARL", AdverseMediaCategory.CORRUPTION,
     "OCCRP", "Soupçons de corruption liés à l'attribution de licences minières."),
    ("Ahmed Al-Rashid", AdverseMediaCategory.TERRORISM,
     "Reuters", "Cité dans une enquête sur le financement du terrorisme."),
    ("Sofia Ndiaye", AdverseMediaCategory.FRAUD,
     "Le Monde", "Mise en cause dans une affaire de fraude financière."),
]


def seed_adverse_media(db: Session) -> int:
    existing = {r.entity_name for r in list_records(db)}
    n = 0
    for name, cat, source, summary in _SEED:
        if name not in existing:
            db.add(AdverseMediaRecord(
                entity_name=name, normalized_name=normalize_name(name),
                category=cat, source=source, summary=summary,
            ))
            n += 1
    db.commit()
    return n
